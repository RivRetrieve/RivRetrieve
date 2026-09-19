"""Installed drainage lookup : BuiltDistribution × StationSelection → DrainageAreaMetadata."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tarfile import open as open_tar
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import pytest

_PROJECTION = "rivretrieve/_internal/catalogues/drainage_areas.parquet"


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("distribution", ["wheel", "sdist-wheel"])
def test_installed_drainage_areas_offline(distribution: str) -> None:
    repository = Path(__file__).resolve().parents[1]
    checks = repository / ".worktrees" / "distribution-checks"
    checks.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=f"drainage-{distribution}-", dir=checks) as temporary:
        workspace = Path(temporary)
        dist = workspace / "dist"
        source = repository
        if distribution == "sdist-wheel":
            _run(["uv", "build", "--sdist", "--out-dir", str(dist)], cwd=repository)
            archives = tuple(dist.glob("rivretrieve-*.tar.gz"))
            assert len(archives) == 1
            with open_tar(archives[0], "r:gz") as archive:
                names = archive.getnames()
                assert not any(name.endswith("/native.parquet") for name in names)
                assert any(name.endswith("/src/" + _PROJECTION) for name in names)
                extracted = workspace / "extracted"
                archive.extractall(extracted, filter="data")
            sources = tuple(extracted.iterdir())
            assert len(sources) == 1
            source = sources[0]
        _run(["uv", "build", "--wheel", "--out-dir", str(dist)], cwd=source)
        wheels = tuple(dist.glob("rivretrieve-*.whl"))
        assert len(wheels) == 1
        with ZipFile(wheels[0]) as wheel:
            assert _PROJECTION in wheel.namelist()
            assert not any(name.endswith("/native.parquet") for name in wheel.namelist())

        environment = workspace / "environment"
        execution = workspace / "execution"
        execution.mkdir()
        _run(
            ["uv", "venv", "--system-site-packages", "--python", sys.executable, str(environment)],
            cwd=execution,
        )
        python = environment / "bin" / "python"
        _run(
            ["uv", "pip", "install", "--no-deps", "--python", str(python), str(wheels[0])],
            cwd=execution,
        )
        # uv resolves the base interpreter, not the invoking project's virtualenv.
        # Reuse dependency directories without executing their editable-install .pth files.
        sites = tuple((environment / "lib").glob("python*/site-packages"))
        assert len(sites) == 1
        dependency_paths = [
            path
            for path in sys.path
            if Path(path).name == "site-packages" and Path(path).is_relative_to(Path(sys.prefix))
        ]
        assert dependency_paths
        (sites[0] / "project_dependencies.pth").write_text("\n".join(dependency_paths) + "\n")
        # No inherited provider credentials, dotenv files, or Python import overrides.
        clean_environment = {"PATH": os.environ["PATH"], "HOME": str(execution)}
        _run([str(python), "-I", "-c", _VERIFICATION], cwd=execution, env=clean_environment)


_VERIFICATION = r"""
import json
import socket
import sys
from importlib.resources import files
from pathlib import Path


def forbid_network(*args, **kwargs):
    raise AssertionError("Installed drainage-area lookup attempted network access")


socket.socket.connect = forbid_network
socket.socket.connect_ex = forbid_network
socket.create_connection = forbid_network
socket.getaddrinfo = forbid_network

import polars as pl
from polars.testing import assert_frame_equal
import rivretrieve as rr

assert Path(rr.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), rr.__file__
assert "site-packages" in Path(rr.__file__).parts
catalogues = files("rivretrieve._internal.catalogues")
assert catalogues.joinpath("drainage_areas.parquet").is_file()
provider_root = files("rivretrieve._internal.providers")
provider_ids = rr.providers()["provider_id"].to_list()
frames = []
selections = []
for provider_id in provider_ids:
    catalogue = provider_root.joinpath(provider_id, "catalogue")
    assert not catalogue.joinpath("native.parquet").is_file()
    stations = pl.read_parquet(catalogue.joinpath("stations.parquet"))
    station_id = "02GA010" if provider_id == "ca_eccc" else stations["station_id"][0]
    selection = rr.find(provider=provider_id, station=station_id)
    selections.append(rr.from_bundle(rr.to_bundle(selection)))
    frames.append(rr.drainage_areas(selections[-1]))

actual = pl.concat(frames)
schema = pl.Schema({
    "provider_id": pl.String,
    "station_id": pl.String,
    "source_field": pl.String,
    "source_value": pl.String,
    "source_dtype": pl.String,
    "source_unit": pl.String,
    "state": pl.Enum(["value", "source_null", "no_metadata"]),
})
assert actual.schema == schema
assert set(actual["provider_id"]) == set(provider_ids)
keys = ["provider_id", "station_id", "source_field"]
assert actual.unique(subset=keys).height == actual.height
assert_frame_equal(actual, pl.concat([rr.drainage_areas(item) for item in selections]))
for value in actual["source_value"].drop_nulls():
    assert isinstance(json.loads(value), (str, int, float, bool))
assert actual.filter(pl.col("state") != "value")["source_value"].null_count() == actual.filter(
    pl.col("state") != "value"
).height
canada = actual.filter(pl.col("provider_id") == "ca_eccc")
gross = canada.filter(pl.col("source_field") == "DRAINAGE_AREA_GROSS").row(0, named=True)
assert gross["station_id"] == "02GA010"
assert gross["source_value"] == "1035.0"
assert json.loads(gross["source_value"]) == 1035.0
assert gross["source_dtype"] == "Float64"
assert gross["state"] == "value"
effective = canada.filter(pl.col("source_field") == "DRAINAGE_AREA_EFFECT").row(0, named=True)
assert effective["source_dtype"] == "Float64"
assert effective["source_value"] is None
assert effective["state"] == "source_null"
empty = rr.pick(rr.pick(selection, quantity="discharge"), quantity="stage")
assert_frame_equal(rr.drainage_areas(empty), pl.DataFrame(schema=schema))
"""

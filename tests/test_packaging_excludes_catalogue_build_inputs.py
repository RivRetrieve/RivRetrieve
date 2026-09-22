"""Distribution payload : BuiltDistribution → RuntimeCatalogues Without MaintenanceInputs."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from tarfile import open as open_tar
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import pytest

_FORBIDDEN_PARTS = {
    "planning",
    "scratchpad",
    ".pce",
    "research",
    "maintenance",
    ".worktrees",
    ".venv",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".distribution-checks",
    "credentials",
}


def _run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def _assert_payload(names: list[str]) -> None:
    forbidden = []
    for name in names:
        path = PurePosixPath(name)
        if (
            _FORBIDDEN_PARTS.intersection(path.parts)
            or path.name == ".env"
            or path.name.startswith(".env.")
            or path.suffix in {".env", ".pem", ".key", ".pyc"}
            or name.endswith("/catalogue/native.parquet")
            or "/tests/test_data/" in name
            or "/tests/recordings/" in name
            or "br_ana_inventory" in name
            or "no_nve_stations_active_" in name
            or "no_nve_station_catalogue_capture" in name
            or "no_nve_swagger" in name
        ):
            forbidden.append(name)
    assert forbidden == []


@pytest.mark.parametrize("distribution", ["wheel", "sdist-wheel"])
def test_distribution_keeps_only_runtime_catalogues(distribution: str, tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    # Extracted source trees must stay inside the repository's worktree area.
    checks = repository / ".worktrees" / "distribution-checks"
    checks.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=distribution + "-", dir=checks) as temporary:
        workspace = Path(temporary)
        dist = workspace / "dist"
        source = repository
        expected = {
            path.relative_to(repository / "src").as_posix(): path.read_bytes()
            for path in (repository / "src/rivretrieve/_internal/providers").glob("*/catalogue/*")
            if path.is_file() and path.name != "native.parquet"
        }
        assert expected
        if distribution == "sdist-wheel":
            _run(["uv", "build", "--offline", "--force-pep517", "--sdist", "--out-dir", str(dist)], repository)
            archives = tuple(dist.glob("rivretrieve-*.tar.gz"))
            assert len(archives) == 1
            with open_tar(archives[0], "r:gz") as archive:
                names = archive.getnames()
                _assert_payload(names)
                prefix = names[0].split("/", 1)[0]
                for name, content in expected.items():
                    member = archive.extractfile(f"{prefix}/src/{name}")
                    assert member is not None
                    assert member.read() == content
                archive.extractall(workspace / "extracted", filter="data")
            source = workspace / "extracted" / prefix
        _run(["uv", "build", "--offline", "--force-pep517", "--wheel", "--out-dir", str(dist)], source)
        wheels = tuple(dist.glob("rivretrieve-*.whl"))
        assert len(wheels) == 1
        with ZipFile(wheels[0]) as wheel:
            _assert_payload(wheel.namelist())
            for name, content in expected.items():
                assert wheel.read(name) == content
            assert not any(b"NVE_API_KEY=" in wheel.read(name) for name in wheel.namelist())

        environment = workspace / "environment"
        _run(["uv", "venv", "--offline", "--python", sys.executable, str(environment)], tmp_path)
        python = environment / "bin" / "python"
        _run(["uv", "pip", "install", "--offline", "--no-deps", "--python", str(python), str(wheels[0])], tmp_path)
        sites = tuple((environment / "lib").glob("python*/site-packages"))
        assert len(sites) == 1
        # Reuse installed dependencies, not the editable project's .pth files.
        dependencies = list(
            dict.fromkeys(
                str(Path(path).resolve())
                for path in sys.path
                if Path(path).is_absolute() and Path(path).name == "site-packages" and Path(path).is_dir()
            )
        )
        assert dependencies
        assert all(not Path(path).is_relative_to(repository / "src") for path in dependencies)
        (sites[0] / "dependencies.pth").write_text("\n".join(dependencies) + "\n")
        _run(
            [str(python), "-I", "-c", _VERIFICATION],
            tmp_path,
            {"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
        )


@pytest.mark.parametrize("distribution", ["wheel", "sdist"])
def test_distributions_exclude_local_files(distribution: str) -> None:
    repository = Path(__file__).resolve().parents[1]
    checks = repository / ".worktrees" / "distribution-checks"
    checks.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="local-files-", dir=checks) as temporary:
        workspace = Path(temporary)
        source = workspace / "source"
        source.mkdir()
        for name in ("pyproject.toml", "README.md"):
            shutil.copyfile(repository / name, source / name)
        shutil.copytree(repository / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
        # These are harmless markers, never copies of real credentials or private evidence.
        local_paths = [
            "planning/visions/release.md",
            "planning/execution/events.jsonl",
            "scratchpad/notes.txt",
            ".pce/repository-contract.json",
            "research/evidence.json",
            "maintenance/catalogue/source/evidence.json",
            ".worktrees/local/source.py",
            ".env",
            ".env.release",
            "credentials/token.txt",
            "src/rivretrieve/.env",
            "src/rivretrieve/.env.release",
            "src/rivretrieve/local.env",
            "src/rivretrieve/private.pem",
            "src/rivretrieve/private.key",
            "src/rivretrieve/.distribution-checks/source.py",
            "src/rivretrieve/credentials/token.txt",
            "src/rivretrieve/.worktrees/local/source.py",
        ]
        for name in local_paths:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("distribution exclusion marker\n")
        dist = workspace / "dist"
        _run(["uv", "build", "--offline", "--force-pep517", "--" + distribution, "--out-dir", str(dist)], source)
        if distribution == "wheel":
            with ZipFile(next(dist.glob("*.whl"))) as wheel:
                _assert_payload(wheel.namelist())
                assert "rivretrieve/__init__.py" in wheel.namelist()
        else:
            with open_tar(next(dist.glob("*.tar.gz")), "r:gz") as archive:
                _assert_payload(archive.getnames())
                assert any(name.endswith("/src/rivretrieve/__init__.py") for name in archive.getnames())


_VERIFICATION = r"""
import socket
import sys
from pathlib import Path
from importlib.resources import files


def forbid_network(*args, **kwargs):
    raise AssertionError("Installed catalogue discovery attempted network access")


socket.socket.connect = forbid_network
socket.socket.connect_ex = forbid_network
socket.create_connection = forbid_network
socket.getaddrinfo = forbid_network

import polars as pl
import rivretrieve as rr

assert Path(rr.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), rr.__file__
assert "site-packages" in Path(rr.__file__).parts
provider_root = files("rivretrieve._internal.providers")
provider_ids = rr.providers()["provider_id"].to_list()
assert provider_ids
for provider_id in provider_ids:
    catalogue = provider_root.joinpath(provider_id, "catalogue")
    assert not catalogue.joinpath("native.parquet").is_file()
    stations = pl.read_parquet(catalogue.joinpath("stations.parquet"))
    selection = rr.find(provider=provider_id, station=stations["station_id"][0])
    assert rr.as_frame(selection).height > 0, provider_id
    assert rr.describe(provider_id)
"""

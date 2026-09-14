"""Wheel installation : BuiltWheel → ReadableBuiltInCatalogues."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_CANONICAL_CATALOGUE_FILES = {
    "croissant.json",
    "products.parquet",
    "provider.json",
    "station_products.parquet",
    "stations.parquet",
}

_PROVENANCE_PROVIDER_IDS = {
    "ba_fhmzbih",
    "br_ana",
    "ca_eccc",
    "ch_foen",
    "cz_chmi",
    "fr_hubeau",
    "jp_mlit",
    "lt_lhmt",
    "no_nve",
    "pl_imgw",
    "th_thaiwater",
    "usgs_nwis",
    "za_dws",
}


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True, text=True, capture_output=True)


def test_wheel_carries_every_manifest_catalogue(tmp_path: Path) -> None:
    repository = Path(__file__).parents[1]
    wheel_directory = tmp_path / "dist"
    environment = tmp_path / "environment"
    execution_directory = tmp_path / "outside-repository"
    execution_directory.mkdir()

    _run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_directory)],
        cwd=repository,
    )
    wheels = tuple(wheel_directory.glob("rivretrieve-*.whl"))
    assert len(wheels) == 1

    _run(["uv", "venv", str(environment)], cwd=execution_directory)
    python = environment / "bin" / "python"
    _run(
        ["uv", "pip", "install", "--python", str(python), str(wheels[0])],
        cwd=execution_directory,
    )

    expected_descriptor = json.loads(
        (repository / "src/rivretrieve/_internal/providers/usgs_nwis/catalogue/croissant.json").read_text()
    )
    verification = f"""
import json
import socket
import sys

def forbid_network(*args, **kwargs):
    raise AssertionError("Network access during installed-wheel discovery")

socket.socket.connect = forbid_network
socket.socket.connect_ex = forbid_network
socket.create_connection = forbid_network

from importlib.resources import files

import rivretrieve
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

before_describe = set(sys.modules)
assert rivretrieve.describe("usgs_nwis") == json.loads({json.dumps(expected_descriptor)!r})
assert not {{name.split(".")[0] for name in set(sys.modules) - before_describe}} - sys.stdlib_module_names - {{"rivretrieve"}}
assert "mlcroissant" not in sys.modules
provider_frame = rivretrieve.providers()
assert provider_frame.columns == ["provider_id", "credentials", "access"]
provider_ids = tuple(provider_frame["provider_id"])
assert provider_ids == BUILTIN_PROVIDER_IDS
provider_root = files("rivretrieve._internal.providers")
for provider_id in provider_ids:
    catalogue = provider_root.joinpath(provider_id, "catalogue")
    packaged_names = {{item.name for item in catalogue.iterdir()}}
    assert {_CANONICAL_CATALOGUE_FILES!r} <= packaged_names, (provider_id, packaged_names)
    if provider_id in {_PROVENANCE_PROVIDER_IDS!r}:
        assert "provenance.json" in packaged_names
    assert "native.parquet" not in packaged_names
    assert rivretrieve.describe(provider_id) == json.loads(catalogue.joinpath("croissant.json").read_text())
    assert not any(name.endswith((".eml", ".xlsx")) for name in packaged_names)

france = rivretrieve.find(provider="fr_hubeau")
assert len(france.series) == 33_139
assert not france.acquisition_provenance[0].withheld_facts
bosnia = rivretrieve.find(provider="ba_fhmzbih")
assert len(bosnia.series) == 180
assert len({{series.station_id for series in bosnia.series}}) == 60
assert sum(series.availability == "available" for series in bosnia.series) == 132
assert sum(series.availability == "unknown" for series in bosnia.series) == 48
assert bosnia.acquisition_provenance[0].withheld_facts == ()
unknown_bosnia = rivretrieve.find(provider="ba_fhmzbih", station="2101-B", product="water_temperature_reported")
assert len(unknown_bosnia.series) == 1 and unknown_bosnia.series[0].availability == "unknown"
assert not provider_root.joinpath("ba_fhmzbih", "catalogue", "baseline_workbook_access.json").is_file()
norway = rivretrieve.find(
    provider="no_nve", station="1.200.0", product="stage_daily_mean"
)
assert len(norway.series) == 1
assert norway.series[0].availability == "available"
assert norway.acquisition_provenance[0].native_table is not None
thailand = rivretrieve.find(
    provider="th_thaiwater", station="1", product="stage_reported"
)
assert rivretrieve.as_frame(thailand).height == 1
groups = thailand.acquisition_provenance[0].withheld_facts
assert groups == ()
"""
    clean_environment = os.environ.copy()
    clean_environment.pop("PYTHONPATH", None)
    clean_environment.pop("VIRTUAL_ENV", None)
    _run(
        [str(python), "-c", verification],
        cwd=execution_directory,
        env=clean_environment,
    )

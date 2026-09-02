"""Wheel installation : BuiltWheel → ReadableBuiltInCatalogues."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_CANONICAL_CATALOGUE_FILES = {
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

    verification = f"""
from importlib.resources import files

import rivretrieve
from rivretrieve._internal.provider_manifest import BUILTIN_PROVIDER_IDS

provider_ids = tuple(rivretrieve.providers())
assert provider_ids == BUILTIN_PROVIDER_IDS
provider_root = files("rivretrieve._internal.providers")
for provider_id in provider_ids:
    catalogue = provider_root.joinpath(provider_id, "catalogue")
    packaged_names = {{item.name for item in catalogue.iterdir()}}
    assert {_CANONICAL_CATALOGUE_FILES!r} <= packaged_names, (provider_id, packaged_names)
    if provider_id in {_PROVENANCE_PROVIDER_IDS!r}:
        assert "provenance.json" in packaged_names
    assert not any(name.endswith((".eml", ".xlsx")) for name in packaged_names)

for provider_id, station_id, count in (
    ("ba_fhmzbih", "1010", 298),
    ("fr_hubeau", "01001336", 47_785),
):
    try:
        rivretrieve.find(provider=provider_id, station=station_id)
    except Exception as exc:
        assert type(exc).__name__ == "UnknownStationError"
    else:
        raise AssertionError((provider_id, station_id))
    provider_selection = rivretrieve.find(provider=provider_id)
    groups = provider_selection.acquisition_provenance[0].withheld_facts
    assert len(groups) == count
    assert {{group.reason for group in groups}} == {{"no_acquisition_record_established"}}
thailand = rivretrieve.find(
    provider="th_thaiwater", station="1", product="stage_instantaneous"
)
assert rivretrieve.as_frame(thailand).is_empty()
groups = thailand.acquisition_provenance[0].withheld_facts
assert len(groups) == 1_650
assert {{group.reason for group in groups}} == {{"no_acquisition_record_established"}}
"""
    clean_environment = os.environ.copy()
    clean_environment.pop("PYTHONPATH", None)
    clean_environment.pop("VIRTUAL_ENV", None)
    _run(
        [str(python), "-c", verification],
        cwd=execution_directory,
        env=clean_environment,
    )

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
    if provider_id == "jp_mlit":
        assert "provenance.json" in packaged_names
"""
    clean_environment = os.environ.copy()
    clean_environment.pop("PYTHONPATH", None)
    clean_environment.pop("VIRTUAL_ENV", None)
    _run(
        [str(python), "-c", verification],
        cwd=execution_directory,
        env=clean_environment,
    )

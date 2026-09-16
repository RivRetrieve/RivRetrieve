"""Distribution payload : BuiltWheel × BuiltSdist → RuntimePayload Minus NativeCatalogueInputs."""

from __future__ import annotations

import subprocess
from pathlib import Path
from tarfile import open as open_tar
from zipfile import ZipFile


def test_wheel_excludes_catalogue_build_inputs(tmp_path: Path) -> None:
    wheel_directory = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_directory)],
        cwd=Path(__file__).parents[1],
        check=True,
        text=True,
        capture_output=True,
    )
    wheels = tuple(wheel_directory.glob("rivretrieve-*.whl"))
    assert len(wheels) == 1

    with ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        native_inputs = sorted(name for name in names if name.endswith("/catalogue/native.parquet"))
        forbidden = [
            name
            for name in names
            if "br_ana_inventory" in name
            or "station-coverage/br_ana" in name
            or "no_nve_stations_active_" in name
            or "no_nve_station_catalogue_capture" in name
            or "no_nve_swagger" in name
            or name.endswith("/.env")
        ]
        payload = b"".join(wheel.read(name) for name in names)

    assert native_inputs == []
    assert forbidden == []
    assert b"NVE_API_KEY=" not in payload


def test_sdist_excludes_catalogue_build_inputs_and_keeps_runtime_catalogues(tmp_path: Path) -> None:
    directory = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(directory)],
        cwd=Path(__file__).parents[1],
        check=True,
        text=True,
        capture_output=True,
    )
    archives = tuple(directory.glob("rivretrieve-*.tar.gz"))
    assert len(archives) == 1
    with open_tar(archives[0], "r:gz") as archive:
        names = archive.getnames()
    forbidden = [
        name
        for name in names
        if name.endswith("/catalogue/native.parquet")
        or "/tests/test_data/" in name
        or "/research/" in name
        or "/reference/legacy_observations/" in name
        or name.endswith("/.env")
    ]
    assert forbidden == []
    prefix = names[0].split("/", 1)[0]
    providers = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers"
    for provider in providers.iterdir():
        catalogue = provider / "catalogue"
        if not catalogue.is_dir():
            continue
        for artifact in catalogue.iterdir():
            if artifact.is_file() and artifact.name != "native.parquet":
                assert (
                    f"{prefix}/src/rivretrieve/_internal/providers/{provider.name}/catalogue/{artifact.name}" in names
                )
    assert f"{prefix}/src/rivretrieve/_internal/providers/br_ana/generate_catalogue.py" in names

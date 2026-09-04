"""Wheel payload : BuiltWheel → RuntimePayload Minus NativeCatalogueInputs."""

from __future__ import annotations

import subprocess
from pathlib import Path
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
            if "no_nve_stations_active_" in name
            or "no_nve_station_catalogue_capture" in name
            or "no_nve_swagger" in name
            or name.endswith("/.env")
        ]
        payload = b"".join(wheel.read(name) for name in names)

    assert native_inputs == []
    assert forbidden == []
    assert b"NVE_API_KEY=" not in payload

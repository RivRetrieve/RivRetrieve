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
        native_inputs = sorted(
            name for name in wheel.namelist() if name.endswith("/catalogue/native.parquet")
        )

    assert native_inputs == []

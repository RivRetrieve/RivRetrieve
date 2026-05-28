from __future__ import annotations

import subprocess
import sys

import rivretrieve as rr


def test_providers_includes_ch_foen_after_discovery_call() -> None:
    assert "ch_foen" in rr.providers()


def test_global_stations_include_ch_foen_rows() -> None:
    result = rr.stations()

    ch_foen_rows = result.data.filter(result.data["provider_id"] == "ch_foen")
    assert ch_foen_rows.height == 246
    assert ch_foen_rows.filter(ch_foen_rows["station_id"] == "2016").select("name").item() == "Brugg"


def test_global_products_include_ch_foen_rows() -> None:
    result = rr.products()

    ch_foen_rows = result.data.filter(result.data["provider_id"] == "ch_foen")
    assert ch_foen_rows.height == 6


def test_provider_handle_station_products_returns_ch_foen_rows() -> None:
    result = rr.provider("ch_foen").station_products()

    assert result.data.height == 1476
    assert set(result.data["availability"].cast(str).to_list()) == {"unknown"}


def test_global_provider_info_includes_ch_foen_row() -> None:
    result = rr.provider_info()

    ch_foen_rows = result.data.filter(result.data["provider_id"] == "ch_foen")
    assert ch_foen_rows.height == 1
    assert ch_foen_rows.select("name").item() == "Swiss Federal Office for the Environment FOEN / BAFU"


def test_ch_foen_internal_metadata_import_does_not_leak_public_names() -> None:
    from rivretrieve._internal.providers.ch_foen import metadata

    assert metadata.ChFoenStationMetadata.__name__ == "ChFoenStationMetadata"
    for name in (
        "ChFoenStationMetadata",
        "ChFoenProductMetadata",
        "ChFoenStationProductMetadata",
    ):
        assert not hasattr(rr, name)


def test_import_rivretrieve_does_not_import_ch_foen_runtime_modules() -> None:
    script = """
import sys
import rivretrieve

assert "rivretrieve._internal.providers.ch_foen.module" not in sys.modules
assert "rivretrieve._internal.providers.ch_foen.generate_catalogue" not in sys.modules
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr

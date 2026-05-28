from __future__ import annotations

import subprocess
import sys

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.observations import ObservationResult
from rivretrieve._internal.primitives import OnIssue
from rivretrieve._internal.results import CatalogResult


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


def test_ch_foen_catalogue_methods_return_catalog_results_with_provenance() -> None:
    results = (
        rr.stations(),
        rr.products(),
        rr.provider_info(),
        rr.provider("ch_foen").station_products(),
    )

    for result in results:
        assert isinstance(result, CatalogResult)
        assert isinstance(result.data, pl.DataFrame)
        assert result.provenance.source == "packaged"
        assert result.issues == ()

    assert results[0].data.filter(results[0].data["provider_id"] == "ch_foen").height == 246
    assert results[1].data.filter(results[1].data["provider_id"] == "ch_foen").height == 6
    assert results[2].data.filter(results[2].data["provider_id"] == "ch_foen").height == 1
    assert results[3].provenance.provider_id == "ch_foen"
    assert results[3].data.height == 1476


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_ch_foen_handle_observations_placeholder_returns_result_for_all_on_issue(on_issue: OnIssue) -> None:
    result = rr.provider("ch_foen").observations(
        stations="2016",
        products="discharge_daily_mean",
        start="2026-01-01",
        end="2026-01-02",
        on_issue=on_issue,
    )

    assert isinstance(result, ObservationResult)
    assert result.data.is_empty()
    assert result.row_annotations.data.is_empty()
    assert result.series_annotations.data.is_empty()
    assert result.row_annotations.schema.name == "RowAnnotationTable"
    assert result.series_annotations.schema.name == "SeriesAnnotationTable"
    assert result.provenance.source == "placeholder"
    assert result.provenance.provider_id == "ch_foen"
    assert result.raw is None
    assert len(result.issues) == 1
    assert result.issues[0].code == "observations_not_yet_implemented"


def test_ch_foen_handle_observations_placeholder_uses_default_on_issue() -> None:
    result = rr.provider("ch_foen").observations(
        stations="2016",
        products="discharge_daily_mean",
        start="2026-01-01",
        end="2026-01-02",
    )

    assert isinstance(result, ObservationResult)
    assert result.data.is_empty()
    assert result.issues[0].code == "observations_not_yet_implemented"


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

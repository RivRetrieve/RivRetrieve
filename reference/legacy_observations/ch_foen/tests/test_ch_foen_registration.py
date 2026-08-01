from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.observations import ObservationResult
from rivretrieve._internal.primitives import OnIssue
from rivretrieve._internal.providers.ch_foen import module as ch_foen_module
from rivretrieve._internal.providers.ch_foen.observation_client import (
    ChFoenObservationClient,
    ChFoenTransportRequest,
    ChFoenTransportResponse,
)
from rivretrieve._internal.results import CatalogResult

TEST_DATA = Path(__file__).parent / "test_data"


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
def test_ch_foen_handle_observations_returns_result_for_all_on_issue(monkeypatch, on_issue: OnIssue) -> None:
    _install_discharge_transport(monkeypatch)

    result = rr.provider("ch_foen").observations(
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue=on_issue,
    )

    assert isinstance(result, ObservationResult)
    assert result.data.height == 144
    assert result.row_annotations.data.height > 0
    assert result.series_annotations.data.height > 0
    assert result.row_annotations.schema.name == "RowAnnotationTable"
    assert result.series_annotations.schema.name == "SeriesAnnotationTable"
    assert result.provenance.source == "live"
    assert result.provenance.provider_id == "ch_foen"
    assert result.raw is not None


def test_ch_foen_handle_observations_uses_default_on_issue(monkeypatch) -> None:
    _install_discharge_transport(monkeypatch)

    result = rr.provider("ch_foen").observations(
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
    )

    assert isinstance(result, ObservationResult)
    assert result.data.height == 144
    assert result.issues == ()


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


def _install_discharge_transport(monkeypatch) -> None:
    def transport(_request: ChFoenTransportRequest) -> ChFoenTransportResponse:
        return ChFoenTransportResponse(
            content=(TEST_DATA / "switzerland_2206_discharge_20250101.csv").read_bytes(),
            status_code=200,
            retrieved_at=datetime(2026, 5, 28, tzinfo=UTC),
        )

    monkeypatch.setattr(
        ch_foen_module,
        "_observation_client_factory",
        lambda: ChFoenObservationClient(token="fake-token", transport=transport),
    )

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.observations import ObservationRequest
from rivretrieve._internal.providers.cz_chmi.generate_catalogue import (
    generate_catalogue_from_fixture,
)
from rivretrieve._internal.providers.cz_chmi.observation_client import (
    CzChmiObservationClient,
    CzChmiTransportResponse,
)
from rivretrieve._internal.providers.cz_chmi.parser import parse_cz_chmi_observation_json
from rivretrieve._internal.providers.cz_chmi.retrieval import retrieve_observations
from rivretrieve._internal.providers.cz_chmi.transform import PRODUCT_POLICIES

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_FIXTURE_DAILY = _TEST_DATA_DIR / "cz_chmi_0-203-1-016000_daily_2020.json"
_METADATA_FIXTURE = _TEST_DATA_DIR / "cz_chmi_metadata.json"


# ---------------------------------------------------------------------------
# Catalogue generation from fixture
# ---------------------------------------------------------------------------


def test_generate_catalogue_from_fixture_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 3


def test_generate_catalogue_from_fixture_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 5


def test_generate_catalogue_from_fixture_station_products_cross() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products.height == 3 * 5


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    station = cat.stations.filter(pl.col("station_id") == "0-203-1-016000")
    assert station.height == 1
    assert station["name"][0] == "Prague - Modřany"
    assert station["country"][0] == "Czech Republic"
    assert station["elevation_m"][0] is None


def test_generate_catalogue_drainage_area_set() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    station = cat.stations.filter(pl.col("station_id") == "0-203-1-016000")
    assert station["drainage_area_km2"][0] == pytest.approx(14260.0)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_discharge_daily() -> None:
    content = _FIXTURE_DAILY.read_bytes()
    result = parse_cz_chmi_observation_json(content, station_id="0-203-1-016000", ts_con_id="QD")
    assert not result.records.is_empty()
    assert result.records.height == 5
    assert result.records["native_value"][0] == pytest.approx(12.5)


def test_parse_stage_daily_raw_cm() -> None:
    content = _FIXTURE_DAILY.read_bytes()
    result = parse_cz_chmi_observation_json(content, station_id="0-203-1-016000", ts_con_id="HD")
    assert not result.records.is_empty()
    assert result.records["native_value"][0] == pytest.approx(205.0)


def test_parse_temperature_daily() -> None:
    content = _FIXTURE_DAILY.read_bytes()
    result = parse_cz_chmi_observation_json(content, station_id="0-203-1-016000", ts_con_id="TD")
    assert not result.records.is_empty()
    assert result.records["native_value"][0] == pytest.approx(2.1)


def test_parse_missing_tsconid_returns_empty_with_issue() -> None:
    content = _FIXTURE_DAILY.read_bytes()
    result = parse_cz_chmi_observation_json(content, station_id="0-203-1-016000", ts_con_id="QH")
    assert result.records.is_empty()
    assert len(result.issues) > 0


def test_parse_empty_content_returns_missing_data_issue() -> None:
    result = parse_cz_chmi_observation_json(b"", station_id="S1", ts_con_id="QD")
    assert result.records.is_empty()
    assert any("missing_data" in str(i.code) for i in result.issues)


def test_parse_timestamps_are_utc() -> None:
    content = _FIXTURE_DAILY.read_bytes()
    result = parse_cz_chmi_observation_json(content, station_id="0-203-1-016000", ts_con_id="QD")
    assert result.records.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


# ---------------------------------------------------------------------------
# Product policies
# ---------------------------------------------------------------------------


def test_product_policies_stage_conversion() -> None:
    policy = PRODUCT_POLICIES["stage_daily_mean"]
    assert policy.unit_conversion == "divide_by_100"
    assert policy.ts_con_id == "HD"


def test_product_policies_discharge_no_conversion() -> None:
    policy = PRODUCT_POLICIES["discharge_daily_mean"]
    assert policy.unit_conversion is None
    assert policy.ts_con_id == "QD"


def test_product_policies_temperature_no_conversion() -> None:
    policy = PRODUCT_POLICIES["water_temperature_daily_mean"]
    assert policy.unit_conversion is None
    assert policy.ts_con_id == "TD"


def test_product_policies_hourly_discharge() -> None:
    policy = PRODUCT_POLICIES["discharge_instantaneous"]
    assert policy.url_type == "hourly"
    assert policy.ts_con_id == "QH"


# ---------------------------------------------------------------------------
# Fixture-backed retrieval
# ---------------------------------------------------------------------------


def _make_transport(station_id: str, year: int, response_bytes: bytes):
    """Returns a transport callable that returns the fixture bytes for matching requests."""

    def transport(request):  # type: ignore[no-untyped-def]
        if str(year) in request.url and station_id in request.url:
            return CzChmiTransportResponse(
                content=response_bytes,
                status_code=200,
                retrieved_at=datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC),
            )
        return CzChmiTransportResponse(
            content=b'{"tsList":[]}', status_code=200, retrieved_at=datetime(2026, 6, 2, tzinfo=UTC)
        )

    return transport


def test_retrieve_discharge_daily_mean() -> None:
    content = _FIXTURE_DAILY.read_bytes()
    transport = _make_transport("0-203-1-016000", 2020, content)
    client_factory = lambda: CzChmiObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="cz_chmi",
        stations=("0-203-1-016000",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="raise", client_factory=client_factory)
    assert not result.data.is_empty()
    assert result.data.height == 5
    assert result.data["product_id"].unique().to_list() == ["discharge_daily_mean"]
    assert result.data["value"][0] == pytest.approx(12.5)


def test_retrieve_stage_daily_mean_converts_cm_to_m() -> None:
    content = _FIXTURE_DAILY.read_bytes()
    transport = _make_transport("0-203-1-016000", 2020, content)
    client_factory = lambda: CzChmiObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="cz_chmi",
        stations=("0-203-1-016000",),
        products=("stage_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="warn", client_factory=client_factory)
    assert not result.data.is_empty()
    # Native value 205 cm → 2.05 m
    assert result.data["value"][0] == pytest.approx(2.05)


def test_retrieve_temperature_daily_mean() -> None:
    content = _FIXTURE_DAILY.read_bytes()
    transport = _make_transport("0-203-1-016000", 2020, content)
    client_factory = lambda: CzChmiObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="cz_chmi",
        stations=("0-203-1-016000",),
        products=("water_temperature_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="raise", client_factory=client_factory)
    assert not result.data.is_empty()
    assert result.data["value"][0] == pytest.approx(2.1)


def test_retrieve_result_data_schema() -> None:
    content = _FIXTURE_DAILY.read_bytes()
    transport = _make_transport("0-203-1-016000", 2020, content)
    client_factory = lambda: CzChmiObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="cz_chmi",
        stations=("0-203-1-016000",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="warn", client_factory=client_factory)
    assert result.data.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")
    assert "station_id" in result.data.columns
    assert "product_id" in result.data.columns
    assert "value" in result.data.columns


def test_retrieve_series_annotations_emitted() -> None:
    content = _FIXTURE_DAILY.read_bytes()
    transport = _make_transport("0-203-1-016000", 2020, content)
    client_factory = lambda: CzChmiObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="cz_chmi",
        stations=("0-203-1-016000",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="warn", client_factory=client_factory)
    annotation_ids = set(result.series_annotations.data["annotation"].to_list())
    assert "resolved_timezone" in annotation_ids
    assert "timezone_source" in annotation_ids
    assert "returned_time_range_start" in annotation_ids


def test_retrieve_row_annotations_emitted() -> None:
    content = _FIXTURE_DAILY.read_bytes()
    transport = _make_transport("0-203-1-016000", 2020, content)
    client_factory = lambda: CzChmiObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="cz_chmi",
        stations=("0-203-1-016000",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="warn", client_factory=client_factory)
    annotation_ids = set(result.row_annotations.data["annotation"].to_list())
    assert "ts_con_id" in annotation_ids
    assert "raw_value" in annotation_ids


def test_retrieve_404_emits_issue_not_fatal() -> None:
    import requests

    def transport_404(request):  # type: ignore[no-untyped-def]
        mock_resp = type("R", (), {"status_code": 404})()
        raise requests.HTTPError(response=mock_resp)

    client_factory = lambda: CzChmiObservationClient(transport=transport_404)  # noqa: E731
    request = ObservationRequest.from_inputs(
        provider_id="cz_chmi",
        stations=("0-203-1-016000",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 5, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.data.is_empty()
    assert any("http_not_found" in str(i.code) for i in result.issues)

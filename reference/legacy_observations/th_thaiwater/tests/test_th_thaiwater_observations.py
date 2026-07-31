from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.observations import ObservationRequest
from rivretrieve._internal.providers.th_thaiwater.generate_catalogue import (
    generate_catalogue_from_fixture,
)
from rivretrieve._internal.providers.th_thaiwater.observation_client import (
    ThThaiWaterObservationClient,
    ThThaiWaterTransportResponse,
)
from rivretrieve._internal.providers.th_thaiwater.parser import parse_th_thaiwater_observation_json
from rivretrieve._internal.providers.th_thaiwater.retrieval import retrieve_observations
from rivretrieve._internal.providers.th_thaiwater.transform import PRODUCT_POLICIES

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_FIXTURE_GRAPH = _TEST_DATA_DIR / "th_thaiwater_S13A_waterlevel_graph.json"
_METADATA_FIXTURE = _TEST_DATA_DIR / "th_thaiwater_metadata.json"


# ---------------------------------------------------------------------------
# Catalogue generation from fixture
# ---------------------------------------------------------------------------


def test_generate_catalogue_from_fixture_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    # fixture has 4 entries but only 3 are tele_waterlevel
    assert cat.stations.height == 3


def test_generate_catalogue_from_fixture_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 4


def test_generate_catalogue_from_fixture_station_products_cross() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products.height == 3 * 4


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    station = cat.stations.filter(pl.col("station_id") == "S13A")
    assert station.height == 1
    assert station["name"][0] == "Wang Noi"
    assert station["country"][0] == "Thailand"
    assert station["elevation_m"][0] is None
    assert station["drainage_area_km2"][0] is None


def test_generate_catalogue_filters_non_waterlevel_stations() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    station_ids = set(cat.stations["station_id"].to_list())
    assert "RAIN01" not in station_ids


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_stage_instantaneous() -> None:
    content = _FIXTURE_GRAPH.read_bytes()
    result = parse_th_thaiwater_observation_json(content, station_id="S13A")
    assert not result.records.is_empty()
    assert result.records.height == 9
    # First value is 1.52 (stage)
    first = result.records.sort("time").row(0, named=True)
    assert first["value_field"] == pytest.approx(1.52)


def test_parse_discharge_instantaneous() -> None:
    content = _FIXTURE_GRAPH.read_bytes()
    result = parse_th_thaiwater_observation_json(content, station_id="S13A")
    first = result.records.sort("time").row(0, named=True)
    assert first["discharge_field"] == pytest.approx(120.5)


def test_parse_timestamps_are_utc() -> None:
    content = _FIXTURE_GRAPH.read_bytes()
    result = parse_th_thaiwater_observation_json(content, station_id="S13A")
    assert result.records.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_parse_bangkok_to_utc_conversion() -> None:
    """Bangkok 2023-06-01 01:00:00 (UTC+7) must become 2023-05-31 18:00:00 UTC."""
    content = _FIXTURE_GRAPH.read_bytes()
    result = parse_th_thaiwater_observation_json(content, station_id="S13A")
    first_utc = result.records.sort("time")["time"][0]
    assert first_utc.year == 2023
    assert first_utc.month == 5
    assert first_utc.day == 31
    assert first_utc.hour == 18


def test_parse_empty_content_returns_missing_data_issue() -> None:
    result = parse_th_thaiwater_observation_json(b"", station_id="S13A")
    assert result.records.is_empty()
    assert any("missing_data" in str(i.code) for i in result.issues)


# ---------------------------------------------------------------------------
# Product policies
# ---------------------------------------------------------------------------


def test_product_policies_stage_daily_uses_value_field() -> None:
    policy = PRODUCT_POLICIES["stage_daily_mean"]
    assert policy.native_field == "value_field"
    assert policy.aggregate_daily is True
    assert policy.canonical_unit == "m"


def test_product_policies_discharge_daily_uses_discharge_field() -> None:
    policy = PRODUCT_POLICIES["discharge_daily_mean"]
    assert policy.native_field == "discharge_field"
    assert policy.aggregate_daily is True
    assert policy.canonical_unit == "m3/s"


def test_product_policies_instantaneous_no_aggregation() -> None:
    policy = PRODUCT_POLICIES["stage_instantaneous"]
    assert policy.aggregate_daily is False


# ---------------------------------------------------------------------------
# Fixture-backed retrieval
# ---------------------------------------------------------------------------


def _make_transport(station_id: str, response_bytes: bytes):  # type: ignore[return]
    def transport(request):  # type: ignore[no-untyped-def]
        if station_id in request.params.get("station_id", ""):
            return ThThaiWaterTransportResponse(
                content=response_bytes,
                status_code=200,
                retrieved_at=datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC),
            )
        return ThThaiWaterTransportResponse(
            content=b'{"data":{"graph_data":[]}}',
            status_code=200,
            retrieved_at=datetime(2026, 6, 2, tzinfo=UTC),
        )

    return transport


def test_retrieve_stage_instantaneous() -> None:
    content = _FIXTURE_GRAPH.read_bytes()
    transport = _make_transport("S13A", content)
    client_factory = lambda: ThThaiWaterObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="th_thaiwater",
        stations=("S13A",),
        products=("stage_instantaneous",),
        start=datetime(2023, 6, 1, tzinfo=UTC),
        end=datetime(2023, 6, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    assert result.data["product_id"].unique().to_list() == ["stage_instantaneous"]
    assert result.data.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_retrieve_discharge_daily_mean_aggregates() -> None:
    content = _FIXTURE_GRAPH.read_bytes()
    transport = _make_transport("S13A", content)
    client_factory = lambda: ThThaiWaterObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="th_thaiwater",
        stations=("S13A",),
        products=("discharge_daily_mean",),
        start=datetime(2023, 6, 1, tzinfo=UTC),
        end=datetime(2023, 6, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    # 3 Bangkok days → 3 daily rows
    assert result.data.height == 3
    assert result.data["product_id"].unique().to_list() == ["discharge_daily_mean"]


def test_retrieve_stage_daily_mean_value() -> None:
    content = _FIXTURE_GRAPH.read_bytes()
    transport = _make_transport("S13A", content)
    client_factory = lambda: ThThaiWaterObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="th_thaiwater",
        stations=("S13A",),
        products=("stage_daily_mean",),
        start=datetime(2023, 6, 1, tzinfo=UTC),
        end=datetime(2023, 6, 1, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    # Bangkok day 2023-06-01: three values 1.52, 1.61, 1.58 → mean ≈ 1.5700
    assert result.data["value"][0] == pytest.approx((1.52 + 1.61 + 1.58) / 3)


def test_retrieve_result_data_utc_schema() -> None:
    content = _FIXTURE_GRAPH.read_bytes()
    transport = _make_transport("S13A", content)
    client_factory = lambda: ThThaiWaterObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="th_thaiwater",
        stations=("S13A",),
        products=("stage_daily_mean",),
        start=datetime(2023, 6, 1, tzinfo=UTC),
        end=datetime(2023, 6, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.data.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")
    assert "station_id" in result.data.columns
    assert "product_id" in result.data.columns
    assert "value" in result.data.columns


def test_retrieve_series_annotations_timezone() -> None:
    content = _FIXTURE_GRAPH.read_bytes()
    transport = _make_transport("S13A", content)
    client_factory = lambda: ThThaiWaterObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="th_thaiwater",
        stations=("S13A",),
        products=("stage_instantaneous",),
        start=datetime(2023, 6, 1, tzinfo=UTC),
        end=datetime(2023, 6, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    ann = result.series_annotations.data
    ann_dict = dict(zip(ann["annotation"].to_list(), ann["value"].to_list(), strict=False))
    assert ann_dict.get("resolved_timezone") == "UTC"
    assert ann_dict.get("timezone_source") == "local_to_utc_conversion"
    assert ann_dict.get("local_timezone") == "Asia/Bangkok"


def test_retrieve_timezone_issue_emitted() -> None:
    content = _FIXTURE_GRAPH.read_bytes()
    transport = _make_transport("S13A", content)
    client_factory = lambda: ThThaiWaterObservationClient(transport=transport)  # noqa: E731

    request = ObservationRequest.from_inputs(
        provider_id="th_thaiwater",
        stations=("S13A",),
        products=("stage_instantaneous",),
        start=datetime(2023, 6, 1, tzinfo=UTC),
        end=datetime(2023, 6, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert any("timezone_local_to_utc" in str(i.code) for i in result.issues)


def test_retrieve_404_emits_issue_not_fatal() -> None:
    import requests

    def transport_404(request):  # type: ignore[no-untyped-def]
        mock_resp = type("R", (), {"status_code": 404})()
        raise requests.HTTPError(response=mock_resp)

    client_factory = lambda: ThThaiWaterObservationClient(transport=transport_404)  # noqa: E731
    request = ObservationRequest.from_inputs(
        provider_id="th_thaiwater",
        stations=("S13A",),
        products=("stage_instantaneous",),
        start=datetime(2023, 6, 1, tzinfo=UTC),
        end=datetime(2023, 6, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.data.is_empty()
    assert any("http_not_found" in str(i.code) for i in result.issues)

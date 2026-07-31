from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.observations import ObservationRequest
from rivretrieve._internal.providers.za_dws.generate_catalogue import (
    generate_catalogue_from_fixture,
)
from rivretrieve._internal.providers.za_dws.observation_client import (
    ZaDwsObservationClient,
    ZaDwsTransportRequest,
    ZaDwsTransportResponse,
)
from rivretrieve._internal.providers.za_dws.parser import (
    parse_daily_response,
    parse_point_response,
)
from rivretrieve._internal.providers.za_dws.retrieval import retrieve_observations
from rivretrieve._internal.providers.za_dws.transform import PRODUCT_POLICIES

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_METADATA_FIXTURE = _TEST_DATA_DIR / "za_dws_metadata.json"
_DAILY_FIXTURE = _TEST_DATA_DIR / "za_dws_X3H001_daily_2020-01.txt"
_POINT_FIXTURE = _TEST_DATA_DIR / "za_dws_X3H001_point_2020-01.txt"


# ---------------------------------------------------------------------------
# Catalogue generation
# ---------------------------------------------------------------------------


def test_generate_catalogue_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 3


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 3


def test_generate_catalogue_station_products_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.station_products.height == 9  # 3 stations × 3 products


def test_generate_catalogue_station_fields_x3h001() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "X3H001")
    assert row.height == 1
    assert row["country"][0] == "South Africa"
    assert row["latitude"][0] == pytest.approx(-26.875)
    assert row["longitude"][0] == pytest.approx(28.1111)
    assert row["drainage_area_km2"][0] == pytest.approx(38560.0)


def test_generate_catalogue_null_drainage_area() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "A1H001")
    assert row.height == 1
    assert row["drainage_area_km2"][0] is None
    assert row["elevation_m"][0] is None


def test_generate_catalogue_station_name_split() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "A2H001")
    assert row.height == 1
    # "Krokodil River @ Hartbeespoort" → name=Hartbeespoort
    assert row["name"][0] == "Hartbeespoort"


def test_generate_catalogue_product_ids() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    product_ids = set(cat.products["product_id"].to_list())
    assert product_ids == {"discharge_daily_mean", "discharge_instantaneous", "stage_instantaneous"}


# ---------------------------------------------------------------------------
# Parser — daily
# ---------------------------------------------------------------------------


def test_parse_daily_response_row_count() -> None:
    content = _DAILY_FIXTURE.read_text(encoding="utf-8")
    parsed = parse_daily_response(content, station_id="X3H001")
    assert parsed.records.height == 30  # Jan 2020 has 31 days but response returned 30


def test_parse_daily_response_first_value() -> None:
    content = _DAILY_FIXTURE.read_text(encoding="utf-8")
    parsed = parse_daily_response(content, station_id="X3H001")
    assert parsed.records["d_avg_fr"][0] == pytest.approx(1.257)
    assert parsed.records["date_str"][0] == "20200101"


def test_parse_daily_no_data_response() -> None:
    parsed = parse_daily_response("No data for requested period.\n\n<html>", station_id="X3H001")
    assert parsed.records.is_empty()
    assert parsed.has_no_data


def test_parse_daily_sentinel_filtered() -> None:
    content = "<pre>DATE D AVG F/R QUAL\n20200101 99999.999 0\n20200102 1.500 1\n</pre>"
    parsed = parse_daily_response(content, station_id="X3H001")
    assert parsed.records.height == 1
    assert parsed.records["d_avg_fr"][0] == pytest.approx(1.500)


# ---------------------------------------------------------------------------
# Parser — point
# ---------------------------------------------------------------------------


def test_parse_point_response_row_count() -> None:
    content = _POINT_FIXTURE.read_text(encoding="utf-8")
    parsed = parse_point_response(content, station_id="X3H001")
    assert parsed.records.height > 0


def test_parse_point_response_first_cor_level() -> None:
    content = _POINT_FIXTURE.read_text(encoding="utf-8")
    parsed = parse_point_response(content, station_id="X3H001")
    assert parsed.records["cor_level"][0] == pytest.approx(0.146)


def test_parse_point_response_first_cor_flow() -> None:
    content = _POINT_FIXTURE.read_text(encoding="utf-8")
    parsed = parse_point_response(content, station_id="X3H001")
    assert parsed.records["cor_flow"][0] == pytest.approx(1.230)


def test_parse_point_time_format() -> None:
    content = _POINT_FIXTURE.read_text(encoding="utf-8")
    parsed = parse_point_response(content, station_id="X3H001")
    assert parsed.records["date_str"][0] == "20200101"
    assert parsed.records["time_str"][0] == "000000"


def test_parse_point_no_data() -> None:
    parsed = parse_point_response("No data for requested period.\n\n<html>", station_id="X3H001")
    assert parsed.records.is_empty()
    assert parsed.has_no_data


# ---------------------------------------------------------------------------
# Product policies / transform
# ---------------------------------------------------------------------------


def test_discharge_daily_policy() -> None:
    policy = PRODUCT_POLICIES["discharge_daily_mean"]
    assert policy.data_type == "Daily"
    assert policy.value_column == "d_avg_fr"
    assert policy.native_unit == "m3/s"
    assert policy.canonical_unit == "m3/s"
    assert policy.chunk_years == 20
    assert policy.is_daily is True


def test_discharge_instantaneous_policy() -> None:
    policy = PRODUCT_POLICIES["discharge_instantaneous"]
    assert policy.data_type == "Point"
    assert policy.value_column == "cor_flow"
    assert policy.is_daily is False
    assert policy.chunk_years == 1


def test_stage_instantaneous_policy() -> None:
    policy = PRODUCT_POLICIES["stage_instantaneous"]
    assert policy.data_type == "Point"
    assert policy.value_column == "cor_level"
    assert policy.native_unit == "m"
    assert policy.canonical_unit == "m"
    assert policy.is_daily is False


# ---------------------------------------------------------------------------
# Retrieval (fixture-backed)
# ---------------------------------------------------------------------------


def _make_transport(daily_content: str, point_content: str):
    """Return a transport callable that serves fixture content by URL pattern."""

    def transport(req: ZaDwsTransportRequest) -> ZaDwsTransportResponse:
        content = daily_content if "DataType=Daily" in req.url else point_content
        return ZaDwsTransportResponse(
            content=content,
            status_code=200,
            retrieved_at=datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC),
        )

    return transport


def test_retrieve_discharge_daily_returns_data() -> None:
    daily_content = _DAILY_FIXTURE.read_text(encoding="utf-8")

    def client_factory() -> ZaDwsObservationClient:
        return ZaDwsObservationClient(transport=_make_transport(daily_content, ""))

    request = ObservationRequest(
        provider_id="za_dws",
        stations=("X3H001",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    assert set(result.data["product_id"].to_list()) == {"discharge_daily_mean"}
    assert set(result.data["station_id"].to_list()) == {"X3H001"}


def test_retrieve_discharge_daily_timestamps_utc_midnight() -> None:
    daily_content = _DAILY_FIXTURE.read_text(encoding="utf-8")

    def client_factory() -> ZaDwsObservationClient:
        return ZaDwsObservationClient(transport=_make_transport(daily_content, ""))

    request = ObservationRequest(
        provider_id="za_dws",
        stations=("X3H001",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    first_time = result.data.sort("time")["time"][0]
    assert first_time.tzinfo is not None
    assert first_time.hour == 0
    assert first_time.minute == 0


def test_retrieve_stage_instantaneous_sast_to_utc() -> None:
    point_content = _POINT_FIXTURE.read_text(encoding="utf-8")

    def client_factory() -> ZaDwsObservationClient:
        return ZaDwsObservationClient(transport=_make_transport("", point_content))

    request = ObservationRequest(
        provider_id="za_dws",
        stations=("X3H001",),
        products=("stage_instantaneous",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    times = result.data["time"].to_list()
    # All timestamps must be timezone-aware UTC
    assert all(t.tzinfo is not None for t in times)
    # All returned timestamps must be within the requested window
    assert all(datetime(2020, 1, 1, tzinfo=UTC) <= t <= datetime(2020, 1, 3, tzinfo=UTC) for t in times)


def test_retrieve_point_timestamps_clipped_to_requested_window() -> None:
    """SAST→UTC conversion shifts midnight SAST to 22:00 UTC the previous day.
    Those out-of-window rows must be clipped, not returned to the caller."""
    point_content = _POINT_FIXTURE.read_text(encoding="utf-8")

    def client_factory() -> ZaDwsObservationClient:
        return ZaDwsObservationClient(transport=_make_transport("", point_content))

    request = ObservationRequest(
        provider_id="za_dws",
        stations=("X3H001",),
        products=("stage_instantaneous",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    times = result.data["time"].to_list()
    assert all(t >= datetime(2020, 1, 1, tzinfo=UTC) for t in times), "Pre-start rows leaked through"
    assert all(t <= datetime(2020, 1, 3, tzinfo=UTC) for t in times), "Post-end rows leaked through"


def test_retrieve_point_cache_shared_between_products() -> None:
    """discharge_instantaneous and stage_instantaneous share one Point HTTP request per window."""
    point_content = _POINT_FIXTURE.read_text(encoding="utf-8")
    call_count = {"n": 0}

    def transport(req: ZaDwsTransportRequest) -> ZaDwsTransportResponse:
        if "DataType=Point" in req.url:
            call_count["n"] += 1
        return ZaDwsTransportResponse(
            content=point_content,
            status_code=200,
            retrieved_at=datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC),
        )

    def client_factory() -> ZaDwsObservationClient:
        return ZaDwsObservationClient(transport=transport)

    request = ObservationRequest(
        provider_id="za_dws",
        stations=("X3H001",),
        products=("discharge_instantaneous", "stage_instantaneous"),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    # One Point HTTP call for the single window, shared between both products
    assert call_count["n"] == 1


def test_retrieve_series_annotation_timezone_daily() -> None:
    daily_content = _DAILY_FIXTURE.read_text(encoding="utf-8")

    def client_factory() -> ZaDwsObservationClient:
        return ZaDwsObservationClient(transport=_make_transport(daily_content, ""))

    request = ObservationRequest(
        provider_id="za_dws",
        stations=("X3H001",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    sa = result.series_annotations.data
    tz_source = sa.filter(
        (pl.col("station_id") == "X3H001")
        & (pl.col("product_id") == "discharge_daily_mean")
        & (pl.col("annotation") == "timezone_source")
    )["value"][0]
    assert tz_source == "date_only_utc_midnight"


def test_retrieve_series_annotation_timezone_point() -> None:
    point_content = _POINT_FIXTURE.read_text(encoding="utf-8")

    def client_factory() -> ZaDwsObservationClient:
        return ZaDwsObservationClient(transport=_make_transport("", point_content))

    request = ObservationRequest(
        provider_id="za_dws",
        stations=("X3H001",),
        products=("stage_instantaneous",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 3, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    sa = result.series_annotations.data
    tz_source = sa.filter(
        (pl.col("station_id") == "X3H001")
        & (pl.col("product_id") == "stage_instantaneous")
        & (pl.col("annotation") == "timezone_source")
    )["value"][0]
    assert tz_source == "local_to_utc_conversion"

    source_tz = sa.filter(
        (pl.col("station_id") == "X3H001")
        & (pl.col("product_id") == "stage_instantaneous")
        & (pl.col("annotation") == "source_timezone")
    )["value"][0]
    assert source_tz == "Africa/Johannesburg"


def test_retrieve_missing_data_emits_warning_issue() -> None:
    def transport(req: ZaDwsTransportRequest) -> ZaDwsTransportResponse:
        return ZaDwsTransportResponse(
            content="No data for requested period.\n\n<html></html>",
            status_code=200,
            retrieved_at=datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC),
        )

    def client_factory() -> ZaDwsObservationClient:
        return ZaDwsObservationClient(transport=transport)

    request = ObservationRequest(
        provider_id="za_dws",
        stations=("A2H001",),
        products=("discharge_daily_mean",),
        start=datetime(2020, 1, 1, tzinfo=UTC),
        end=datetime(2020, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.data.is_empty()
    issue_codes = {i.code for i in result.issues}
    assert "missing_data" in issue_codes

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.observations import ObservationRequest
from rivretrieve._internal.providers.ba_fhmzbih.generate_catalogue import (
    generate_catalogue_from_fixture,
)
from rivretrieve._internal.providers.ba_fhmzbih.observation_client import (
    BaFhmzbihObservationClient,
    BaFhmzbihTransportRequest,
    BaFhmzbihTransportResponse,
)
from rivretrieve._internal.providers.ba_fhmzbih.parser import parse_ba_fhmzbih_workbook
from rivretrieve._internal.providers.ba_fhmzbih.retrieval import retrieve_observations
from rivretrieve._internal.providers.ba_fhmzbih.transform import PRODUCT_POLICIES

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_METADATA_FIXTURE = _TEST_DATA_DIR / "ba_fhmzbih_metadata.json"
_DISCHARGE_FIXTURE = _TEST_DATA_DIR / "ba_fhmzbih_4510_Q_1Y.xlsx"
_STAGE_FIXTURE = _TEST_DATA_DIR / "ba_fhmzbih_4510_H_1Y.xlsx"
_TEMPERATURE_FIXTURE = _TEST_DATA_DIR / "ba_fhmzbih_4510_Tvode_1Y.xlsx"


# ---------------------------------------------------------------------------
# Catalogue generation
# ---------------------------------------------------------------------------


def test_generate_catalogue_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 2


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.height == 6


def test_generate_catalogue_station_products_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    # 2 stations x 6 products = 12
    assert cat.station_products.height == 12


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "4510")
    assert row.height == 1
    assert row["name"][0] == "HS Kaloševići"
    assert row["country"][0] == "Bosnia and Herzegovina"
    assert row["elevation_m"][0] == pytest.approx(233.0)


def test_generate_catalogue_drainage_area_parsed_from_catchment_size() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "4121")
    assert row.height == 1
    assert row["drainage_area_km2"][0] == pytest.approx(123.4)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_discharge_workbook_values() -> None:
    content = _DISCHARGE_FIXTURE.read_bytes()
    parsed = parse_ba_fhmzbih_workbook(content, station_id="4510", product_id="discharge_instantaneous")
    assert parsed.records.height > 0
    assert parsed.records["raw_value"][0] == pytest.approx(8.304)


def test_parse_discharge_workbook_naive_local_timestamps() -> None:
    content = _DISCHARGE_FIXTURE.read_bytes()
    parsed = parse_ba_fhmzbih_workbook(content, station_id="4510", product_id="discharge_instantaneous")
    times = parsed.records["time_local"].to_list()
    assert times[0] == datetime(2025, 3, 23, 0, 0, 0)
    assert all(t.tzinfo is None for t in times)


def test_parse_stage_workbook_values_in_cm() -> None:
    content = _STAGE_FIXTURE.read_bytes()
    parsed = parse_ba_fhmzbih_workbook(content, station_id="4510", product_id="stage_instantaneous")
    assert parsed.records.height > 0
    assert parsed.records["raw_value"][0] == pytest.approx(82.2)


def test_parse_empty_temperature_workbook() -> None:
    content = _TEMPERATURE_FIXTURE.read_bytes()
    parsed = parse_ba_fhmzbih_workbook(content, station_id="4510", product_id="water_temperature_instantaneous")
    assert parsed.records.is_empty()
    assert len(parsed.issues) == 0


# ---------------------------------------------------------------------------
# Transform / product policies
# ---------------------------------------------------------------------------


def test_discharge_policy_no_conversion() -> None:
    policy = PRODUCT_POLICIES["discharge_instantaneous"]
    assert policy.conversion_factor == 1.0
    assert policy.native_unit == "m3/s"
    assert policy.canonical_unit == "m3/s"
    assert policy.aggregate_daily is False


def test_stage_policy_cm_to_m() -> None:
    policy = PRODUCT_POLICIES["stage_instantaneous"]
    assert policy.conversion_factor == 100.0
    assert policy.native_unit == "cm"
    assert policy.canonical_unit == "m"


def test_daily_mean_policies_marked_aggregate() -> None:
    assert PRODUCT_POLICIES["discharge_daily_mean"].aggregate_daily is True
    assert PRODUCT_POLICIES["stage_daily_mean"].aggregate_daily is True
    assert PRODUCT_POLICIES["water_temperature_daily_mean"].aggregate_daily is True
    assert PRODUCT_POLICIES["discharge_instantaneous"].aggregate_daily is False


# ---------------------------------------------------------------------------
# Retrieval with fixture transport
# ---------------------------------------------------------------------------


def _make_fixture_transport():
    """Return a transport callable serving fixtures from station group 4."""

    def transport(request: BaFhmzbihTransportRequest) -> BaFhmzbihTransportResponse:
        if "/4/4510/Q/" in request.url:
            content = _DISCHARGE_FIXTURE.read_bytes()
        elif "/4/4510/H/" in request.url:
            content = _STAGE_FIXTURE.read_bytes()
        elif "/4/4510/WT/" in request.url:
            content = _TEMPERATURE_FIXTURE.read_bytes()
        else:
            return BaFhmzbihTransportResponse(
                content=b"", status_code=404, retrieved_at=datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
            )
        return BaFhmzbihTransportResponse(
            content=content, status_code=200, retrieved_at=datetime(2026, 6, 3, 12, 0, tzinfo=UTC)
        )

    return transport


def _request(products: list[str], start: datetime, end: datetime) -> ObservationRequest:
    return ObservationRequest(
        provider_id="ba_fhmzbih",
        stations=["4510"],
        products=products,
        start=start,
        end=end,
    )


def test_retrieve_discharge_returns_data() -> None:
    client_factory = lambda: BaFhmzbihObservationClient(transport=_make_fixture_transport())  # noqa: E731
    request = _request(
        ["discharge_instantaneous"], datetime(2025, 3, 23, tzinfo=UTC), datetime(2025, 3, 25, tzinfo=UTC)
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    assert set(result.data["product_id"].unique().to_list()) == {"discharge_instantaneous"}
    assert set(result.data["station_id"].unique().to_list()) == {"4510"}


def test_retrieve_stage_values_converted_to_m() -> None:
    client_factory = lambda: BaFhmzbihObservationClient(transport=_make_fixture_transport())  # noqa: E731
    request = _request(["stage_instantaneous"], datetime(2025, 3, 23, tzinfo=UTC), datetime(2025, 3, 25, tzinfo=UTC))
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    # First retained row is local 2025-03-23 01:00 (CET, UTC+1) = 2025-03-23 00:00 UTC: 81.5 cm -> 0.815 m
    assert result.data["value"][0] == pytest.approx(0.815)


def test_retrieve_stage_raw_value_annotation_in_cm() -> None:
    client_factory = lambda: BaFhmzbihObservationClient(transport=_make_fixture_transport())  # noqa: E731
    request = _request(["stage_instantaneous"], datetime(2025, 3, 23, tzinfo=UTC), datetime(2025, 3, 25, tzinfo=UTC))
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    raw_ann = result.row_annotations.data.filter(pl.col("annotation") == "raw_value")
    assert raw_ann.height > 0
    assert float(raw_ann["value"][0]) == pytest.approx(81.5)


def test_retrieve_timestamps_utc_and_localized() -> None:
    client_factory = lambda: BaFhmzbihObservationClient(transport=_make_fixture_transport())  # noqa: E731
    request = _request(
        ["discharge_instantaneous"], datetime(2025, 3, 23, tzinfo=UTC), datetime(2025, 3, 25, tzinfo=UTC)
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    times = result.data["time"].to_list()
    assert all(t.tzinfo is not None for t in times), "All timestamps must be timezone-aware"
    # Filter window is [2025-03-23 00:00 UTC, 2025-03-26 00:00 UTC); the first
    # retained row is local 2025-03-23 01:00 (CET, UTC+1) -> 2025-03-23 00:00 UTC
    assert times[0] == datetime(2025, 3, 23, 0, 0, tzinfo=UTC)


def test_retrieve_daily_mean_aggregates_by_local_calendar_day() -> None:
    client_factory = lambda: BaFhmzbihObservationClient(transport=_make_fixture_transport())  # noqa: E731
    request = _request(["discharge_daily_mean"], datetime(2025, 3, 23, tzinfo=UTC), datetime(2025, 3, 26, tzinfo=UTC))
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert not result.data.is_empty()
    times = result.data["time"].to_list()
    # Anchored at local midnight (UTC+1 in late March before EU DST starts)
    assert times[0] == datetime(2025, 3, 22, 23, 0, tzinfo=UTC)
    # One row per local calendar day
    assert len(times) == len(set(times))


def test_retrieve_series_annotation_timezone() -> None:
    client_factory = lambda: BaFhmzbihObservationClient(transport=_make_fixture_transport())  # noqa: E731
    request = _request(
        ["discharge_instantaneous"], datetime(2025, 3, 23, tzinfo=UTC), datetime(2025, 3, 25, tzinfo=UTC)
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    sa = result.series_annotations.data
    tz_source = sa.filter(pl.col("annotation") == "timezone_source")["value"][0]
    assert tz_source == "local_to_utc_conversion"
    source_tz = sa.filter(pl.col("annotation") == "source_timezone")["value"][0]
    assert source_tz == "Europe/Sarajevo"
    resolved_tz = sa.filter(pl.col("annotation") == "resolved_timezone")["value"][0]
    assert resolved_tz == "UTC"


def test_retrieve_emits_timezone_info_issue() -> None:
    client_factory = lambda: BaFhmzbihObservationClient(transport=_make_fixture_transport())  # noqa: E731
    request = _request(
        ["discharge_instantaneous"], datetime(2025, 3, 23, tzinfo=UTC), datetime(2025, 3, 25, tzinfo=UTC)
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    codes = [i.code for i in result.issues]
    assert "timezone_local_to_utc" in codes


def test_retrieve_empty_temperature_workbook_emits_missing_data() -> None:
    client_factory = lambda: BaFhmzbihObservationClient(transport=_make_fixture_transport())  # noqa: E731
    request = _request(
        ["water_temperature_instantaneous"], datetime(2025, 3, 23, tzinfo=UTC), datetime(2025, 3, 25, tzinfo=UTC)
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.data.is_empty()
    codes = [i.code for i in result.issues]
    assert "missing_data" in codes


def test_retrieve_station_group_not_found_for_unknown_station() -> None:
    client_factory = lambda: BaFhmzbihObservationClient(transport=_make_fixture_transport())  # noqa: E731
    request = ObservationRequest(
        provider_id="ba_fhmzbih",
        stations=["99999999"],
        products=["discharge_instantaneous"],
        start=datetime(2025, 3, 23, tzinfo=UTC),
        end=datetime(2025, 3, 25, tzinfo=UTC),
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert result.data.is_empty()
    codes = [i.code for i in result.issues]
    assert "station_group_not_found" in codes


def test_retrieve_provenance_endpoints() -> None:
    client_factory = lambda: BaFhmzbihObservationClient(transport=_make_fixture_transport())  # noqa: E731
    request = _request(
        ["discharge_instantaneous"], datetime(2025, 3, 23, tzinfo=UTC), datetime(2025, 3, 25, tzinfo=UTC)
    )
    result = retrieve_observations(request, on_issue="ignore", client_factory=client_factory)
    assert len(result.provenance.calls_made) == 1
    assert result.provenance.calls_made[0]["station_group"] == 4

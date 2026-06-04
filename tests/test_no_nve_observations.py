"""Tests for no_nve observation parsing, transformation, and retrieval."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.providers.no_nve.parser import parse_nve_response

_TEST_DATA = Path(__file__).parent / "test_data"
_DAILY_JSON = _TEST_DATA / "no_nve_12.210.0_discharge_daily_2023.json"
_HOURLY_JSON = _TEST_DATA / "no_nve_12.210.0_discharge_hourly_202301.json"


# ---------------------------------------------------------------------------
# Daily parser tests
# ---------------------------------------------------------------------------


def test_daily_parser_produces_utc_timestamps() -> None:
    content = _DAILY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=1440)
    assert not payload.records.is_empty()
    tz = payload.records["time"].dtype.time_zone
    assert tz == "UTC"


def test_daily_parser_utc_midnight_convention() -> None:
    """Daily timestamps must be interpreted as UTC midnight regardless of provider offset."""
    content = _DAILY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=1440)
    for t in payload.records["time"].to_list():
        assert t is not None
        assert t.hour == 0
        assert t.minute == 0
        assert t.second == 0


def test_daily_parser_cet_offset_becomes_utc_midnight() -> None:
    """'2023-01-01T00:00:00+01:00' → UTC midnight 2023-01-01 (not 2022-12-31)."""
    content = _DAILY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=1440)
    first = payload.records.sort("time")["time"][0]
    assert first == datetime(2023, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_daily_parser_filters_missing_sentinel() -> None:
    """Values ≤ -9999 must be excluded (fixture has one -9999.0 row)."""
    content = _DAILY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=1440)
    values = payload.records["raw_value"].to_list()
    assert all(v is not None and v > -9999 for v in values)


def test_daily_parser_correct_record_count() -> None:
    # Fixture has 5 rows, 1 sentinel (-9999) → 4 valid.
    content = _DAILY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=1440)
    assert len(payload.records) == 4


def test_daily_parser_emits_date_only_timestamp_issue() -> None:
    content = _DAILY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=1440)
    codes = [i.code for i in payload.issues]
    assert "date_only_timestamp" in codes


def test_daily_parser_date_only_issue_is_warning() -> None:
    content = _DAILY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=1440)
    date_issues = [i for i in payload.issues if i.code == "date_only_timestamp"]
    assert date_issues
    assert date_issues[0].severity == "warning"


def test_daily_parser_station_id_column() -> None:
    content = _DAILY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=1440)
    assert payload.records["station_id"].unique().to_list() == ["12.210.0"]


def test_daily_parser_empty_content_returns_missing_data_issue() -> None:
    payload = parse_nve_response(b"", station_id="12.210.0", resolution_time=1440)
    assert payload.records.is_empty()
    codes = [i.code for i in payload.issues]
    assert "missing_data" in codes


# ---------------------------------------------------------------------------
# Hourly parser tests
# ---------------------------------------------------------------------------


def test_hourly_parser_produces_utc_timestamps() -> None:
    content = _HOURLY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=60)
    assert not payload.records.is_empty()
    assert payload.records["time"].dtype.time_zone == "UTC"


def test_hourly_parser_offset_to_utc_conversion() -> None:
    """'2023-01-01T00:00:00+01:00' = 2022-12-31T23:00:00Z (CET → UTC: -1h)."""
    content = _HOURLY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=60)
    first = payload.records.sort("time")["time"][0]
    expected = datetime(2022, 12, 31, 23, 0, 0, tzinfo=UTC)
    assert first == expected


def test_hourly_parser_emits_timezone_info_issue() -> None:
    content = _HOURLY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=60)
    codes = [i.code for i in payload.issues]
    assert "timezone_local_to_utc" in codes


def test_hourly_parser_timezone_issue_is_info_severity() -> None:
    content = _HOURLY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=60)
    tz_issues = [i for i in payload.issues if i.code == "timezone_local_to_utc"]
    assert tz_issues
    assert tz_issues[0].severity == "info"


def test_hourly_parser_correct_record_count() -> None:
    content = _HOURLY_JSON.read_bytes()
    payload = parse_nve_response(content, station_id="12.210.0", resolution_time=60)
    assert len(payload.records) == 3


# ---------------------------------------------------------------------------
# Retrieval with mocked transport
# ---------------------------------------------------------------------------


def _make_client(response_bytes: bytes):
    from datetime import UTC, datetime

    from rivretrieve._internal.providers.no_nve.observation_client import (
        NoNveObservationClient,
        NoNveTransportResponse,
    )

    class _FakeClient(NoNveObservationClient):
        def __init__(self) -> None:
            super().__init__(api_key="fake-test-key")

        def fetch_observations(self, station_id, parameter_id, resolution_time, reference_time):
            return NoNveTransportResponse(
                content=response_bytes,
                status_code=200,
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            )

    return _FakeClient


def test_retrieval_daily_returns_observation_result() -> None:
    content = _DAILY_JSON.read_bytes()
    client_factory = _make_client(content)

    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.no_nve.retrieval import retrieve_observations

    req = ObservationRequest(
        provider_id="no_nve",
        stations=["12.210.0"],
        products=["discharge_daily_mean"],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(req, client_factory=client_factory, on_issue="ignore")
    assert not result.data.is_empty()
    assert result.data["product_id"].unique().to_list() == ["discharge_daily_mean"]


def test_retrieval_daily_timestamps_are_utc() -> None:
    content = _DAILY_JSON.read_bytes()
    client_factory = _make_client(content)

    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.no_nve.retrieval import retrieve_observations

    req = ObservationRequest(
        provider_id="no_nve",
        stations=["12.210.0"],
        products=["discharge_daily_mean"],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(req, client_factory=client_factory, on_issue="ignore")
    assert result.data["time"].dtype.time_zone == "UTC"


def test_retrieval_hourly_utc_timestamps() -> None:
    content = _HOURLY_JSON.read_bytes()
    client_factory = _make_client(content)

    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.no_nve.retrieval import retrieve_observations

    req = ObservationRequest(
        provider_id="no_nve",
        stations=["12.210.0"],
        products=["discharge_hourly_mean"],
        start=datetime(2022, 12, 31, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )
    result = retrieve_observations(req, client_factory=client_factory, on_issue="ignore")
    assert not result.data.is_empty()
    assert result.data["time"].dtype.time_zone == "UTC"


def test_retrieval_series_annotations_timezone_source_daily() -> None:
    content = _DAILY_JSON.read_bytes()
    client_factory = _make_client(content)

    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.no_nve.retrieval import retrieve_observations

    req = ObservationRequest(
        provider_id="no_nve",
        stations=["12.210.0"],
        products=["discharge_daily_mean"],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(req, client_factory=client_factory, on_issue="ignore")
    sa = result.series_annotations.data
    tz_row = sa.filter(pl.col("annotation") == "timezone_source")
    assert not tz_row.is_empty()
    assert tz_row["value"][0] == "date_only_utc_midnight"


def test_retrieval_series_annotations_timezone_source_hourly() -> None:
    content = _HOURLY_JSON.read_bytes()
    client_factory = _make_client(content)

    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.no_nve.retrieval import retrieve_observations

    req = ObservationRequest(
        provider_id="no_nve",
        stations=["12.210.0"],
        products=["discharge_hourly_mean"],
        start=datetime(2022, 12, 31, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )
    result = retrieve_observations(req, client_factory=client_factory, on_issue="ignore")
    sa = result.series_annotations.data
    tz_row = sa.filter(pl.col("annotation") == "timezone_source")
    assert not tz_row.is_empty()
    assert tz_row["value"][0] == "provider_timestamp_offset"


def test_retrieval_auth_missing_emits_issue() -> None:
    """When no API key is set, auth_missing issue should be returned."""
    import os

    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.no_nve.observation_client import NoNveObservationClient
    from rivretrieve._internal.providers.no_nve.retrieval import retrieve_observations

    class _NoKeyClient(NoNveObservationClient):
        def __init__(self) -> None:
            super().__init__(api_key=None)
            self.api_key = None  # Force no credentials regardless of env.

    req = ObservationRequest(
        provider_id="no_nve",
        stations=["12.210.0"],
        products=["discharge_daily_mean"],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 31, tzinfo=UTC),
    )
    # Temporarily clear env var to ensure the client has no key.
    saved = os.environ.pop("NVE_API_KEY", None)
    try:
        result = retrieve_observations(req, client_factory=_NoKeyClient, on_issue="ignore")
    finally:
        if saved is not None:
            os.environ["NVE_API_KEY"] = saved

    codes = [i.code for i in result.issues]
    assert "auth_missing" in codes
    assert result.data.is_empty()


def test_retrieval_unsupported_product_raises() -> None:
    from rivretrieve._internal.issues import InvalidObservationRequestError
    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.no_nve.retrieval import retrieve_observations

    # Must use a client with fake credentials so auth check passes and product
    # validation is reached.
    client_factory = _make_client(b"{}")

    req = ObservationRequest(
        provider_id="no_nve",
        stations=["12.210.0"],
        products=["precipitation_daily_sum"],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 31, tzinfo=UTC),
    )
    with pytest.raises(InvalidObservationRequestError):
        retrieve_observations(req, client_factory=client_factory, on_issue="ignore")

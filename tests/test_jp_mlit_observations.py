"""Tests for jp_mlit observation parsing, transformation, and retrieval."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.providers.jp_mlit.parser import (
    parse_jp_mlit_daily_dat,
    parse_jp_mlit_hourly_dat,
)

_TEST_DATA = Path(__file__).parent / "test_data"
_HOURLY_DAT = _TEST_DATA / "jp_mlit_301011281104010_kind2_202301.dat"
_DAILY_DAT = _TEST_DATA / "jp_mlit_301011281104010_kind7_2023.dat"


# ---------------------------------------------------------------------------
# Hourly parser
# ---------------------------------------------------------------------------


def test_hourly_parser_produces_utc_timestamps() -> None:
    content = _HOURLY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_hourly_dat(content, station_id="301011281104010")
    assert not payload.records.is_empty()
    tz = payload.records["time"].dtype.time_zone
    assert tz == "UTC"


def test_hourly_parser_jst_to_utc_conversion() -> None:
    """Hour 1 on 2023-01-01 JST = 00:00 JST = 14:00 UTC on 2022-12-31 (UTC+9 → UTC: -9h)."""
    content = _HOURLY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_hourly_dat(content, station_id="301011281104010")
    first_time = payload.records.sort("time")["time"][0]
    # 2023-01-01 00:00 JST = 2022-12-31 15:00 UTC
    expected = datetime(2022, 12, 31, 15, 0, 0, tzinfo=UTC)
    assert first_time == expected


def test_hourly_parser_emits_timezone_issue() -> None:
    content = _HOURLY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_hourly_dat(content, station_id="301011281104010")
    codes = [i.code for i in payload.issues]
    assert "timezone_local_to_utc" in codes


def test_hourly_parser_timezone_issue_is_info_severity() -> None:
    content = _HOURLY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_hourly_dat(content, station_id="301011281104010")
    tz_issues = [i for i in payload.issues if i.code == "timezone_local_to_utc"]
    assert tz_issues
    assert tz_issues[0].severity == "info"


def test_hourly_parser_filters_missing_sentinel() -> None:
    """Values ≤ -9999 must be excluded."""
    content = _HOURLY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_hourly_dat(content, station_id="301011281104010")
    values = payload.records["raw_value"].to_list()
    assert all(v is not None and v > -9999 for v in values)


def test_hourly_parser_correct_record_count() -> None:
    # Fixture has 2 days × 24 hours = 48 records.
    content = _HOURLY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_hourly_dat(content, station_id="301011281104010")
    assert len(payload.records) == 48


def test_hourly_parser_station_id_column() -> None:
    content = _HOURLY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_hourly_dat(content, station_id="301011281104010")
    assert payload.records["station_id"].unique().to_list() == ["301011281104010"]


def test_hourly_parser_empty_returns_missing_data_issue() -> None:
    payload = parse_jp_mlit_hourly_dat("", station_id="301011281104010")
    assert payload.records.is_empty()
    codes = [i.code for i in payload.issues]
    assert "missing_data" in codes


# ---------------------------------------------------------------------------
# Daily parser
# ---------------------------------------------------------------------------


def test_daily_parser_produces_utc_timestamps() -> None:
    content = _DAILY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_daily_dat(content, station_id="301011281104010")
    assert not payload.records.is_empty()
    tz = payload.records["time"].dtype.time_zone
    assert tz == "UTC"


def test_daily_parser_utc_midnight_convention() -> None:
    """Daily timestamps must be interpreted as UTC midnight."""
    content = _DAILY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_daily_dat(content, station_id="301011281104010")
    times = payload.records["time"].to_list()
    for t in times:
        assert t is not None
        assert t.hour == 0
        assert t.minute == 0
        assert t.second == 0


def test_daily_parser_emits_date_only_issue() -> None:
    content = _DAILY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_daily_dat(content, station_id="301011281104010")
    codes = [i.code for i in payload.issues]
    assert "date_only_timestamp" in codes


def test_daily_parser_date_only_issue_is_warning() -> None:
    content = _DAILY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_daily_dat(content, station_id="301011281104010")
    date_issues = [i for i in payload.issues if i.code == "date_only_timestamp"]
    assert date_issues
    assert date_issues[0].severity == "warning"


def test_daily_parser_filters_missing_sentinel() -> None:
    """Fixture has -9999.99 values that must be filtered."""
    content = _DAILY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_daily_dat(content, station_id="301011281104010")
    values = payload.records["raw_value"].to_list()
    assert all(v is not None and v > -9999 for v in values)


def test_daily_parser_known_value() -> None:
    """First January entry should be 10.5."""
    content = _DAILY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_daily_dat(content, station_id="301011281104010")
    sorted_records = payload.records.sort("time")
    first_time = sorted_records["time"][0]
    first_value = sorted_records["raw_value"][0]
    # 2023-01-01 UTC midnight
    assert first_time == datetime(2023, 1, 1, tzinfo=UTC)
    assert float(first_value) == pytest.approx(10.5)


def test_daily_parser_no_invalid_dates() -> None:
    """Invalid calendar dates (e.g. Feb 30) must be silently skipped."""
    content = _DAILY_DAT.read_text(encoding="utf-8")
    payload = parse_jp_mlit_daily_dat(content, station_id="301011281104010")
    times = payload.records["time"].to_list()
    # All timestamps must be valid datetimes (no None).
    assert all(t is not None for t in times)


def test_daily_parser_empty_returns_missing_data_issue() -> None:
    payload = parse_jp_mlit_daily_dat("", station_id="301011281104010")
    assert payload.records.is_empty()
    codes = [i.code for i in payload.issues]
    assert "missing_data" in codes


# ---------------------------------------------------------------------------
# Retrieval with mocked transport
# ---------------------------------------------------------------------------


def _make_dat_response(dat_content: str, dat_url: str = "http://mock/dat/file.dat"):
    from datetime import UTC, datetime

    from rivretrieve._internal.providers.jp_mlit.observation_client import JpMlitDatResponse

    return JpMlitDatResponse(
        dat_content=dat_content,
        html_url="http://mock/html",
        dat_url=dat_url,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _make_client(dat_content: str):
    from rivretrieve._internal.providers.jp_mlit.observation_client import JpMlitObservationClient

    class _FakeClient(JpMlitObservationClient):
        def fetch_observation_window(self, station_id, kind, begin_date, end_date):
            return _make_dat_response(dat_content)

    return _FakeClient


def test_retrieval_daily_returns_observation_result() -> None:


    dat_content = _DAILY_DAT.read_text(encoding="utf-8")
    client_factory = _make_client(dat_content)

    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.jp_mlit.retrieval import retrieve_observations

    req = ObservationRequest(
        provider_id="jp_mlit",
        stations=["301011281104010"],
        products=["discharge_daily_mean"],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(req, client_factory=client_factory, on_issue="ignore")
    assert not result.data.is_empty()
    assert result.data["product_id"].unique().to_list() == ["discharge_daily_mean"]


def test_retrieval_daily_timestamps_are_utc() -> None:
    dat_content = _DAILY_DAT.read_text(encoding="utf-8")
    client_factory = _make_client(dat_content)

    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.jp_mlit.retrieval import retrieve_observations

    req = ObservationRequest(
        provider_id="jp_mlit",
        stations=["301011281104010"],
        products=["discharge_daily_mean"],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(req, client_factory=client_factory, on_issue="ignore")
    assert result.data["time"].dtype.time_zone == "UTC"


def test_retrieval_hourly_jst_to_utc() -> None:
    """Retrieval of hourly data must produce UTC-aware timestamps."""
    dat_content = _HOURLY_DAT.read_text(encoding="utf-8")
    client_factory = _make_client(dat_content)

    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.jp_mlit.retrieval import retrieve_observations

    req = ObservationRequest(
        provider_id="jp_mlit",
        stations=["301011281104010"],
        products=["stage_hourly_mean"],
        start=datetime(2022, 12, 31, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )
    result = retrieve_observations(req, client_factory=client_factory, on_issue="ignore")
    assert not result.data.is_empty()
    assert result.data["time"].dtype.time_zone == "UTC"


def test_retrieval_series_annotations_timezone_source_daily() -> None:
    dat_content = _DAILY_DAT.read_text(encoding="utf-8")
    client_factory = _make_client(dat_content)

    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.jp_mlit.retrieval import retrieve_observations

    req = ObservationRequest(
        provider_id="jp_mlit",
        stations=["301011281104010"],
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
    dat_content = _HOURLY_DAT.read_text(encoding="utf-8")
    client_factory = _make_client(dat_content)

    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.jp_mlit.retrieval import retrieve_observations

    req = ObservationRequest(
        provider_id="jp_mlit",
        stations=["301011281104010"],
        products=["stage_hourly_mean"],
        start=datetime(2022, 12, 31, tzinfo=UTC),
        end=datetime(2023, 1, 2, tzinfo=UTC),
    )
    result = retrieve_observations(req, client_factory=client_factory, on_issue="ignore")
    sa = result.series_annotations.data
    tz_row = sa.filter(pl.col("annotation") == "timezone_source")
    assert not tz_row.is_empty()
    assert tz_row["value"][0] == "local_to_utc_conversion"


def test_retrieval_no_dat_link_emits_issue() -> None:
    """When HTML has no .dat link, a no_dat_link issue must be emitted."""
    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.jp_mlit.observation_client import (
        JpMlitDatResponse,
        JpMlitObservationClient,
    )
    from rivretrieve._internal.providers.jp_mlit.retrieval import retrieve_observations

    class _NoLinkClient(JpMlitObservationClient):
        def fetch_observation_window(self, station_id, kind, begin_date, end_date):
            return JpMlitDatResponse(
                dat_content="",
                html_url="http://mock/html",
                dat_url=None,
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            )

    req = ObservationRequest(
        provider_id="jp_mlit",
        stations=["301011281104010"],
        products=["discharge_daily_mean"],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 31, tzinfo=UTC),
    )
    result = retrieve_observations(req, client_factory=_NoLinkClient, on_issue="ignore")
    codes = [i.code for i in result.issues]
    assert "no_dat_link" in codes


def test_retrieval_unsupported_product_raises() -> None:
    from rivretrieve._internal.issues import InvalidObservationRequestError
    from rivretrieve._internal.observations import ObservationRequest
    from rivretrieve._internal.providers.jp_mlit.retrieval import retrieve_observations

    req = ObservationRequest(
        provider_id="jp_mlit",
        stations=["301011281104010"],
        products=["water_temperature_daily_mean"],
        start=datetime(2023, 1, 1, tzinfo=UTC),
        end=datetime(2023, 1, 31, tzinfo=UTC),
    )
    with pytest.raises(InvalidObservationRequestError):
        retrieve_observations(req, on_issue="ignore")

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.providers.pl_imgw.observation_client import CACHE_FILENAME, ImgwCacheClient
from rivretrieve._internal.providers.pl_imgw.parser import parse_imgw_csv_bytes, parse_imgw_zip

_TEST_DATA_DIR = Path(__file__).parent / "test_data"
_FIXTURE_ZIP = _TEST_DATA_DIR / "pl_imgw_151140030_annual_2023.zip"
_FIXTURE_PARQUET = _TEST_DATA_DIR / "pl_imgw_cache_fixture.parquet"
_STATION_ID = "151140030"


def _make_csv_2023(rows: list[str]) -> bytes:
    return ("﻿" + "\r\n".join(rows) + "\r\n").encode("utf-8")


def _make_csv_legacy(rows: list[str]) -> bytes:
    return ("\r\n".join(rows) + "\r\n").encode("cp1250")


_CSV_2023_ROWS = [
    "151140030;Przewożniki;Skroda;2023;03;01;225;1.500;2.5;1",
    "151140030;Przewożniki;Skroda;2023;03;02;220;1.450;99.9;1",  # missing temp
    "151140030;Przewożniki;Skroda;2023;03;03;9999;1.420;3.1;1",  # missing level
    "999000000;Other;Vistula;2023;03;01;100;2.000;10.0;1",  # other station
]


def test_parse_csv_2023_row_count() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    assert result.records.height == 3


def test_parse_csv_station_filter() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    assert set(result.records["station_id"].to_list()) == {_STATION_ID}


def test_parse_csv_all_stations_when_empty_filter() -> None:
    """Empty station_ids = all stations (cache-build mode)."""
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset())
    assert result.records.height == 4


def test_parse_csv_timestamps_utc() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    assert result.records.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_parse_csv_first_date_is_2023_01_01() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    assert result.records["time"][0] == datetime(2023, 1, 1, tzinfo=UTC)


def test_parse_csv_sentinel_level_replaced() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    row3 = result.records.filter(result.records["time"] == datetime(2023, 1, 3, tzinfo=UTC))
    assert row3["level_cm"][0] is None


def test_parse_csv_sentinel_temp_replaced() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    row2 = result.records.filter(result.records["time"] == datetime(2023, 1, 2, tzinfo=UTC))
    assert row2["temp_c"][0] is None


def test_parse_csv_flow_value() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    row1 = result.records.filter(result.records["time"] == datetime(2023, 1, 1, tzinfo=UTC))
    assert row1["flow_m3s"][0] == pytest.approx(1.5)


def test_parse_csv_date_only_issue_emitted() -> None:
    raw = _make_csv_2023(_CSV_2023_ROWS)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    assert any("date_only_timestamp" in str(i.code) for i in result.issues)


def test_parse_csv_legacy_cp1250() -> None:
    legacy = [
        '" 149180020","CHAŁUPKI","Odra (1)","2015","03","01",127,30.000,99.9,"1"',
        '" 149180020","CHAŁUPKI","Odra (1)","2015","03","02",130,29.500,3.5,"1"',
    ]
    raw = _make_csv_legacy(legacy)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({"149180020"}))
    assert result.records.height == 2
    assert result.records["time"][0] == datetime(2015, 1, 1, tzinfo=UTC)
    assert result.records["temp_c"][0] is None  # 99.9 → sentinel


def test_parse_csv_november_hydro_year() -> None:
    """Month indicator 01 = November; hydro_year - 1 is calendar year for Nov/Dec."""
    rows = ["151140030;Przewożniki;Skroda;2023;01;15;200;1.200;5.0;11"]
    raw = _make_csv_2023(rows)
    result = parse_imgw_csv_bytes(raw, station_ids=frozenset({_STATION_ID}))
    assert result.records.height == 1
    assert result.records["time"][0] == datetime(2022, 11, 15, tzinfo=UTC)


# ---------------------------------------------------------------------------
# ZIP parser
# ---------------------------------------------------------------------------


def test_parse_zip_fixture_row_count() -> None:
    zip_bytes = _FIXTURE_ZIP.read_bytes()
    result = parse_imgw_zip(zip_bytes, station_ids=frozenset({_STATION_ID}))
    assert result.records.height == 3


def test_parse_zip_bad_bytes_raises() -> None:
    from rivretrieve._internal.providers.pl_imgw.parser import PlImgwParserError

    with pytest.raises(PlImgwParserError, match="not a valid ZIP"):
        parse_imgw_zip(b"not a zip", station_ids=frozenset({_STATION_ID}))


def _client() -> ImgwCacheClient:
    return ImgwCacheClient(cache_path_override=_FIXTURE_PARQUET)


def test_cache_status_with_fixture() -> None:
    status = _client().cache_status()
    assert status.exists is True
    assert status.path == _FIXTURE_PARQUET
    assert status.format == "parquet"


def test_cache_ensure_returns_fixture_path() -> None:
    path, issues = _client().ensure_cache()
    assert path == _FIXTURE_PARQUET
    assert issues == []


def test_cache_refresh_override_skips_download() -> None:
    issues = _client().refresh_cache()
    assert [issue.code for issue in issues] == ["imgw_refresh_skipped"]


def test_runtime_cache_client_has_no_observation_query() -> None:
    assert not hasattr(ImgwCacheClient, "query")


def test_stale_cache_message_does_not_advertise_handle(tmp_path: Path) -> None:
    cache_path = tmp_path / CACHE_FILENAME
    cache_path.touch()
    stale_timestamp = (datetime.now(UTC) - timedelta(days=91)).timestamp()
    os.utime(cache_path, (stale_timestamp, stale_timestamp))
    path, issues = ImgwCacheClient(cache_dir=tmp_path).ensure_cache()
    assert path == cache_path
    assert [issue.code for issue in issues] == ["imgw_cache_stale"]
    assert all("rr.provider" not in issue.message for issue in issues)

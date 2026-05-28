from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ch_foen.issue_codes import (
    ChFoenObservationIssueCodes,
    ChFoenParserFatalCodes,
)
from rivretrieve._internal.providers.ch_foen.parser import (
    ChFoenObservationParserError,
    parse_ch_foen_observation_csv,
)
from rivretrieve._internal.providers.ch_foen.raw_payload import (
    ChFoenRawCsvResponse,
    ChFoenRawPayload,
)

TEST_DATA = Path(__file__).parent / "test_data"
UTC_DTYPE = pl.Datetime(time_unit="us", time_zone="UTC")


def test_ch_foen_observation_fixture_files_are_present() -> None:
    for filename in (
        "switzerland_2016_temperature_20200101.csv",
        "switzerland_2206_discharge_20250101.csv",
        "switzerland_2282_stage_20250101.csv",
    ):
        path = TEST_DATA / filename

        assert path.is_file()
        assert path.stat().st_size > 0


def test_ch_foen_parser_temperature_fixture_derives_native_records() -> None:
    parsed = parse_ch_foen_observation_csv((TEST_DATA / "switzerland_2016_temperature_20200101.csv").read_bytes())
    records = parsed.records

    assert records.height == 287
    assert records.schema["time"] == UTC_DTYPE
    assert records.schema["window_start"] == UTC_DTYPE
    assert records.schema["window_stop"] == UTC_DTYPE
    assert set(records["station_id"].to_list()) == {"2016"}
    assert set(records["native_field"].to_list()) == {"temperature"}
    assert _native_unit_for("temperature") == "degC"
    assert set(records["measurement"].to_list()) == {"hydro"}
    assert records["native_value"].min() == 6.5
    assert records["native_value"].max() == 6.77
    assert records["time"].min() == _utc("2020-01-01T00:00:00Z")
    assert records["time"].max() == _utc("2020-01-02T23:50:00Z")
    assert set(records["window_start"].to_list()) == {_utc("2020-01-01T00:00:00Z")}
    assert set(records["window_stop"].to_list()) == {_utc("2020-01-03T00:00:00Z")}
    assert parsed.issues == ()


def test_ch_foen_parser_discharge_fixture_derives_native_records() -> None:
    parsed = parse_ch_foen_observation_csv((TEST_DATA / "switzerland_2206_discharge_20250101.csv").read_bytes())
    records = parsed.records

    assert records.height == 144
    assert set(records["station_id"].to_list()) == {"2206"}
    assert set(records["native_field"].to_list()) == {"flow_ls"}
    assert _native_unit_for("flow_ls") == "L/s"
    assert set(records["measurement"].to_list()) == {"hydro"}
    assert records["native_value"].min() == 14.0
    assert records["native_value"].max() == 15.0
    mean_value = records["native_value"].mean()
    assert isinstance(mean_value, float)
    assert math.isclose(mean_value, 14.944444444444, rel_tol=0.0, abs_tol=1e-12)
    assert records["time"].min() == _utc("2025-01-01T00:00:00Z")
    assert records["time"].max() == _utc("2025-01-01T23:50:00Z")
    assert parsed.issues == ()


def test_ch_foen_parser_stage_fixture_derives_native_records() -> None:
    parsed = parse_ch_foen_observation_csv((TEST_DATA / "switzerland_2282_stage_20250101.csv").read_bytes())
    records = parsed.records

    assert records.height == 141
    assert set(records["station_id"].to_list()) == {"2282"}
    assert set(records["native_field"].to_list()) == {"height_abs"}
    assert _native_unit_for("height_abs") == "m"
    assert set(records["measurement"].to_list()) == {"hydro"}
    assert records["native_value"].min() == 0.161
    assert records["native_value"].max() == 0.165
    assert records["time"].min() == _utc("2025-01-01T00:00:00Z")
    assert records["time"].max() == _utc("2025-01-01T23:50:00Z")
    assert parsed.issues == ()


def test_ch_foen_parser_rejects_missing_required_columns() -> None:
    csv_bytes = b"_time,_value,_field,_measurement\n2025-01-01T00:00:00Z,1.0,flow,hydro\n"

    with pytest.raises(ChFoenObservationParserError) as exc_info:
        parse_ch_foen_observation_csv(csv_bytes)

    assert exc_info.value.code == ChFoenParserFatalCodes.MISSING_REQUIRED_COLUMN


def test_ch_foen_parser_reports_invalid_rows_as_recoverable_when_valid_rows_remain() -> None:
    csv_bytes = (
        b",result,table,_start,_stop,_time,_value,_field,_measurement,loc\n"
        b",_result,0,2025-01-01T00:00:00Z,2025-01-02T00:00:00Z,not-a-time,1.0,flow,hydro,2206\n"
        b",_result,0,2025-01-01T00:00:00Z,2025-01-02T00:00:00Z,2025-01-01T00:10:00Z,bad,flow,hydro,2206\n"
        b",_result,0,2025-01-01T00:00:00Z,2025-01-02T00:00:00Z,2025-01-01T00:20:00Z,2.0,flow,hydro,2206\n"
    )

    parsed = parse_ch_foen_observation_csv(csv_bytes)

    assert parsed.records.height == 1
    assert parsed.records["native_value"].to_list() == [2.0]
    assert {issue.code for issue in parsed.issues} == {
        ChFoenObservationIssueCodes.INVALID_TIMESTAMP,
        ChFoenObservationIssueCodes.INVALID_NUMERIC_VALUE,
    }


def test_ch_foen_raw_payload_preserves_bytes_and_redacts_auth() -> None:
    csv_bytes = (TEST_DATA / "switzerland_2206_discharge_20250101.csv").read_bytes()
    response = ChFoenRawCsvResponse(
        csv_bytes=csv_bytes,
        endpoint="https://influx.konzept.space/api/v2/query?org=api.existenz.ch",
        query='from(bucket: "existenzApi") |> filter(fn: (r) => r["_field"] == "flow_ls")',
        status_code=200,
    )

    payload = ChFoenRawPayload(provider_id=ProviderId("ch_foen"), responses=(response,))

    assert payload.responses[0].csv_bytes == csv_bytes
    assert "Authorization" not in payload.responses[0].endpoint
    assert "Authorization" not in payload.responses[0].query
    assert "fake-token" not in repr(payload)


def test_ch_foen_observation_issue_codes_cover_m4_codes() -> None:
    assert {code.value for code in ChFoenObservationIssueCodes} == {
        "observations_not_yet_implemented",
        "missing_data",
        "partial_response",
        "source_request_failed",
        "gap",
        "overlap",
        "conflict",
        "unit_conversion_ambiguity",
        "timezone_ambiguity",
        "invalid_timestamp",
        "invalid_numeric_value",
    }


def test_ch_foen_parser_error_codes_cover_fatal_parser_codes() -> None:
    assert {code.value for code in ChFoenParserFatalCodes} == {
        "malformed_csv",
        "missing_required_column",
    }


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _native_unit_for(native_field: str) -> str:
    return {
        "temperature": "degC",
        "flow": "m3/s",
        "flow_ls": "L/s",
        "height_abs": "m",
        "height": "m",
    }[native_field]

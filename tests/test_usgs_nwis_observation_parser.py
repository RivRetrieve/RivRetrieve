from __future__ import annotations

from pathlib import Path

import polars as pl

from rivretrieve._internal.providers.usgs_nwis.parser import (
    parse_usgs_nwis_observation_json,
)

FIXTURE_PATH = Path("tests/test_data/usgs_nwis_07374000_dv_00060_2023-01-01.json")
STATION_ID = "07374000"


def test_parser_fixture_discharge_row_count() -> None:
    content = FIXTURE_PATH.read_bytes()
    result = parse_usgs_nwis_observation_json(content, station_id=STATION_ID)
    assert not result.records.is_empty()
    assert result.records.height == 10


def test_parser_fixture_discharge_values() -> None:
    content = FIXTURE_PATH.read_bytes()
    result = parse_usgs_nwis_observation_json(content, station_id=STATION_ID)
    values = result.records["native_value"].to_list()
    assert values[0] == 373000.0
    assert values[1] == 373000.0
    assert values[3] == 377000.0
    assert values[4] == 382000.0


def test_parser_time_is_utc() -> None:
    content = FIXTURE_PATH.read_bytes()
    result = parse_usgs_nwis_observation_json(content, station_id=STATION_ID)
    assert result.records["time"].dtype == pl.Datetime(time_unit="us", time_zone="UTC")


def test_parser_timestamps_converted_from_cst() -> None:
    """NWIS timestamps at 2023-01-01T00:00:00.000-06:00 → 2023-01-01T06:00:00Z."""
    content = FIXTURE_PATH.read_bytes()
    result = parse_usgs_nwis_observation_json(content, station_id=STATION_ID)
    first_time = result.records["time"][0]
    assert first_time.hour == 6
    assert first_time.year == 2023
    assert first_time.month == 1
    assert first_time.day == 1


def test_parser_qualifier_preserved() -> None:
    content = FIXTURE_PATH.read_bytes()
    result = parse_usgs_nwis_observation_json(content, station_id=STATION_ID)
    qualifiers = result.records["qualifier"].to_list()
    assert qualifiers[0] == "A"
    assert qualifiers[3] == "P"
    assert "e" in qualifiers[4]


def test_parser_station_id_set() -> None:
    content = FIXTURE_PATH.read_bytes()
    result = parse_usgs_nwis_observation_json(content, station_id=STATION_ID)
    assert result.records["station_id"].unique().to_list() == [STATION_ID]


def test_parser_empty_content_returns_missing_data_issue() -> None:
    result = parse_usgs_nwis_observation_json(b"", station_id=STATION_ID)
    assert result.records.is_empty()
    assert len(result.issues) >= 1
    codes = [i.code for i in result.issues]
    assert "missing_data" in codes


def test_parser_no_data_value_skipped() -> None:
    import json

    fixture = {
        "value": {
            "timeSeries": [
                {
                    "variable": {"noDataValue": -999999.0},
                    "values": [
                        {
                            "value": [
                                {"value": "-999999", "qualifiers": ["P"], "dateTime": "2023-01-01T00:00:00.000-06:00"},
                                {"value": "100.0", "qualifiers": ["A"], "dateTime": "2023-01-02T00:00:00.000-06:00"},
                            ]
                        }
                    ],
                }
            ]
        }
    }
    result = parse_usgs_nwis_observation_json(json.dumps(fixture).encode(), station_id=STATION_ID)
    assert result.records.height == 1
    assert result.records["native_value"][0] == 100.0
    codes = [i.code for i in result.issues]
    assert "no_data_value" in codes

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.providers.lt_lhmt.parser import (
    LtLhmtObservationParserError,
    parse_lt_lhmt_observation_json,
)

FIXTURE_PATH = Path("tests/test_data/lithuania_anyksciu_vms_2023_06.json")


def test_parser_fixture_discharge(tmp_path: Path) -> None:
    content = FIXTURE_PATH.read_bytes()
    parsed = parse_lt_lhmt_observation_json(content, station_id="anyksciu-vms", native_field="waterDischarge")
    assert not parsed.records.is_empty()
    assert parsed.records.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")
    assert parsed.records.schema["native_field"] == pl.Utf8
    assert parsed.records.schema["native_value"] == pl.Float64


def test_parser_fixture_stage() -> None:
    content = FIXTURE_PATH.read_bytes()
    parsed = parse_lt_lhmt_observation_json(content, station_id="anyksciu-vms", native_field="waterLevel")
    assert not parsed.records.is_empty()
    # Values are in cm (raw)
    values = parsed.records["native_value"].to_list()
    assert all(v > 0 for v in values)


def test_parser_timestamps_are_utc_midnight() -> None:
    content = FIXTURE_PATH.read_bytes()
    parsed = parse_lt_lhmt_observation_json(content, station_id="anyksciu-vms", native_field="waterDischarge")
    times = parsed.records["time"].to_list()
    for t in times:
        assert t.hour == 0
        assert t.minute == 0
        assert t.second == 0


def test_parser_emits_date_only_issue() -> None:
    content = FIXTURE_PATH.read_bytes()
    parsed = parse_lt_lhmt_observation_json(content, station_id="anyksciu-vms", native_field="waterDischarge")
    issue_codes = [i.code for i in parsed.issues]
    assert "date_only_timestamp" in issue_codes


def test_parser_empty_bytes() -> None:
    parsed = parse_lt_lhmt_observation_json(b"", station_id="x", native_field="waterDischarge")
    assert parsed.records.is_empty()
    assert any(i.code == "missing_data" for i in parsed.issues)


def test_parser_empty_observations_list() -> None:
    content = json.dumps({"observations": []}).encode()
    parsed = parse_lt_lhmt_observation_json(content, station_id="x", native_field="waterDischarge")
    assert parsed.records.is_empty()
    assert any(i.code == "missing_data" for i in parsed.issues)


def test_parser_invalid_json() -> None:
    with pytest.raises(LtLhmtObservationParserError):
        parse_lt_lhmt_observation_json(b"not json", station_id="x", native_field="waterDischarge")


def test_parser_missing_native_field_skipped() -> None:
    content = json.dumps({"observations": [{"observationDateUtc": "2023-06-01", "waterLevel": 20}]}).encode()
    parsed = parse_lt_lhmt_observation_json(content, station_id="x", native_field="waterDischarge")
    assert parsed.records.is_empty()


def test_parser_discharge_count_matches_fixture() -> None:
    content = FIXTURE_PATH.read_bytes()
    parsed = parse_lt_lhmt_observation_json(content, station_id="anyksciu-vms", native_field="waterDischarge")
    raw = json.loads(content)
    obs_with_discharge = [o for o in raw["observations"] if o.get("waterDischarge") is not None]
    assert parsed.records.height == len(obs_with_discharge)

"""USGS decoding uses returned coordinates and preserves response method evidence."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.engine import (
    Payload,
    RowsSchema,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.usgs_nwis.config import config
from rivretrieve._internal.providers.usgs_nwis.parse import parse
from rivretrieve._internal.recordings import read_recording

IV = Path("tests/test_data/usgs_nwis_07374000_iv_00060_2023-03-12.recording.json")
DV = Path("tests/test_data/usgs_nwis_07374000_dv_00060_00003_2023-01-01_2023-01-03.recording.json")


def _payload(content, product="discharge_instantaneous"):
    unknown = UnknownOriginFact()
    return Payload(
        SourceCoordinates(object()),
        (("07374000", ProductId(product)),),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2023, 1, 1)), WindowEndpoint.from_datetime(datetime(2023, 3, 13))
        ),
        content,
        SourceCallOrigin(unknown, unknown, unknown, unknown, unknown, unknown, unknown),
        (),
    )


def test_recorded_singleton_preserves_id_empty_description_native_values_and_offsets():
    recording = read_recording(IV)
    source = json.loads(recording.content)["value"]["timeSeries"][0]
    entries = source["values"][0]["value"]
    result = parse(_payload(recording.content), config())
    (series,) = result.series
    assert series.identity.published_id == str(source["values"][0]["method"][0]["methodID"])
    assert series.identity.description == ""
    expected = pl.DataFrame(
        {
            "station_id": ["07374000"] * len(entries),
            "product_id": ["discharge_instantaneous"] * len(entries),
            "time": [datetime.fromisoformat(e["dateTime"]).replace(tzinfo=None) for e in entries],
            "value": [float(e["value"]) for e in entries],
            "time_zone": [e["dateTime"][-6:] for e in entries],
            "series_id": [series.series_id] * len(entries),
            "facts_id": [series.facts[0].facts_id] * len(entries),
            "source_unit": ["ft3/s"] * len(entries),
        },
        schema=RowsSchema.polars_schema,
    )
    pl_testing.assert_frame_equal(result.rows, expected)
    assert result.rows["time_zone"].to_list() == ["-06:00"] * 8 + ["-05:00"] * 84
    assert "qualifier" not in result.rows.columns
    assert not result.issues


def test_recorded_daily_keeps_naive_labels_and_unknown_zone():
    result = parse(_payload(read_recording(DV).content, "discharge_daily_mean"), config())
    assert result.rows.select("time", "time_zone").rows() == [
        (datetime(2023, 1, day), "unknown") for day in range(1, 4)
    ]
    assert result.series[0].facts[0].day_definition.value is None


@pytest.mark.parametrize(
    "field,value", [("site", "99999999"), ("parameter", "00065"), ("statistic", "00001"), ("unit", "unrecognised")]
)
def test_response_coordinate_or_unit_contradiction_is_not_converted(field, value):
    doc = json.loads(read_recording(DV).content)
    item = doc["value"]["timeSeries"][0]
    if field == "site":
        item["sourceInfo"]["siteCode"][0]["value"] = value
    elif field == "parameter":
        item["variable"]["variableCode"][0]["value"] = value
    elif field == "statistic":
        item["variable"]["options"]["option"][0]["optionCode"] = value
    else:
        item["variable"]["unit"]["unitCode"] = value
    result = parse(_payload(json.dumps(doc).encode(), "discharge_daily_mean"), config())
    assert result.rows.is_empty()
    assert result.outcomes[0].status == "unsupported"
    assert result.issues


@pytest.mark.parametrize(
    "stamp",
    [
        "2023-01-01T00:00:00",
        "2023-01-01T00:00:00CST",
        "2023-01-01T00:00:00-0600",
        "2023-01-01T00:00:00-25:00",
        "not-a-time",
    ],
)
def test_unrepresentable_source_timestamp_is_identified_unsupported(stamp):
    doc = json.loads(read_recording(IV).content)
    doc["value"]["timeSeries"][0]["values"][0]["value"][0]["dateTime"] = stamp
    result = parse(_payload(json.dumps(doc).encode()), config())
    assert result.rows.is_empty()
    assert result.outcomes[0].status == "unsupported"
    assert result.outcomes[0].series_id == result.series[0].series_id


@pytest.mark.parametrize("content", [b"", b"{", b"[]", bytes([255]), b"{}"])
def test_unreadable_publisher_content_is_retained_as_source_limitation(content):
    result = parse(_payload(content), config())
    pl_testing.assert_frame_equal(result.rows, pl.DataFrame(schema=RowsSchema.polars_schema))
    assert result.outcomes[0].status == "unsupported"
    assert result.issues


def test_unknown_internal_product_is_fatal():
    with pytest.raises(FatalContractError, match="absent from provider config"):
        parse(_payload(b"", "undeclared"), config())


def test_explicit_empty_published_method_has_successful_empty_outcome():
    doc = json.loads(read_recording(IV).content)
    doc["value"]["timeSeries"][0]["values"][0]["value"] = []
    result = parse(_payload(json.dumps(doc).encode()), config())
    assert result.rows.is_empty()
    assert result.outcomes[0].status == "empty"
    assert result.outcomes[0].series_id == result.series[0].series_id


def test_parse_normalizes_explicit_z_to_positive_zero_without_station_zone_inference():
    doc = json.loads(read_recording(IV).content)
    values = doc["value"]["timeSeries"][0]["values"][0]["value"]
    values[:] = [{"dateTime": "2023-01-01T00:00:00Z", "value": "1.5"}]
    parsed = parse(_payload(json.dumps(doc).encode()), config())
    assert parsed.rows.select("time", "time_zone", "value").row(0) == (datetime(2023, 1, 1), "+00:00", 1.5)
    assert parsed.outcomes[0].status == "success"


def test_naive_nonmidnight_daily_label_is_unsupported_not_reinterpreted():
    doc = json.loads(read_recording(DV).content)
    doc["value"]["timeSeries"][0]["values"][0]["value"][0]["dateTime"] = "2023-01-01T12:00:00"
    parsed = parse(_payload(json.dumps(doc).encode(), "discharge_daily_mean"), config())
    assert parsed.rows.is_empty()
    assert parsed.outcomes[0].status == "unsupported"
    assert "midnight" in parsed.outcomes[0].reason
    assert parsed.outcomes[0].series_id == parsed.series[0].series_id


@pytest.mark.parametrize(
    "bad_values", [["1", "not-a-number"], ["not-a-number", "not-a-number"]], ids=["mixed-invalid", "all-invalid"]
)
def test_unrepresentable_numeric_method_is_unsupported_without_discarding_sibling(bad_values):
    from copy import deepcopy

    doc = json.loads(read_recording(DV).content)
    blocks = doc["value"]["timeSeries"][0]["values"]
    good = deepcopy(blocks[0])
    good["method"][0]["methodID"] = 0
    blocks.append(good)
    blocks[0]["value"] = [
        {"value": number, "dateTime": f"2023-01-0{index + 1}T00:00:00"} for index, number in enumerate(bad_values)
    ]
    parsed = parse(_payload(json.dumps(doc).encode(), "discharge_daily_mean"), config())
    healthy = next(s for s in parsed.series if s.identity.published_id == "0")
    failed = next(s for s in parsed.series if s.identity.published_id != "0")
    assert parsed.rows.height == len(good["value"])
    assert parsed.rows["series_id"].unique().to_list() == [healthy.series_id]
    assert any(o.series_id == failed.series_id and o.status == "unsupported" for o in parsed.outcomes)
    assert not any(o.series_id == failed.series_id and o.status in ("success", "empty") for o in parsed.outcomes)
    assert any(o.series_id == healthy.series_id and o.status == "success" for o in parsed.outcomes)
    assert any(i.details["series_id"] == failed.series_id for i in parsed.issues)


def test_iv_service_does_not_establish_an_observation_frequency():
    parsed = parse(_payload(read_recording(IV).content), config())
    assert all(s.facts[0].frequency.value is None for s in parsed.series)
    assert all(s.facts[0].frequency.state == "not_established" for s in parsed.series)


def test_iv_response_contradictory_statistic_is_not_relabelled_instantaneous():
    doc = json.loads(read_recording(IV).content)
    doc["value"]["timeSeries"][0]["variable"]["options"]["option"][0]["optionCode"] = "00003"
    parsed = parse(_payload(json.dumps(doc).encode()), config())
    assert parsed.rows.is_empty()
    assert parsed.outcomes[0].status == "unsupported"
    assert "statistic" in parsed.outcomes[0].reason.lower()


def test_iv_meaning_cites_retained_primary_definition_not_typical_cadence():
    from hashlib import sha256

    definition = Path("tests/test_data/usgs_nwis_instantaneous_values_definition.html").read_bytes()
    provenance = json.loads(
        Path("tests/test_data/usgs_nwis_instantaneous_values_definition.provenance.json").read_text()
    )
    assert sha256(definition).hexdigest() == provenance["sha256"]
    assert b"Instantaneous Values" in definition
    parsed = parse(_payload(read_recording(IV).content), config())
    for series in parsed.series:
        facts = series.facts[0]
        assert provenance["url"] in facts.statistic.evidence
        assert provenance["url"] in facts.temporal_support.evidence
        assert facts.frequency.value is None


def test_daily_midnight_labels_are_not_evidence_of_a_physical_timestamp_anchor():
    parsed = parse(_payload(read_recording(DV).content, "discharge_daily_mean"), config())
    assert parsed.rows.height == 3
    for series in parsed.series:
        facts = series.facts[0]
        assert facts.timestamp_anchor.value is None
        assert facts.timestamp_anchor.state == "not_established"
        assert facts.label_time == "00:00"
        assert facts.clipping_axis == "calendar_date"

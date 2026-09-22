"""Immutable historical WaterServices evidence, not active provider-route tests.

Modern route coverage lives in test_usgs_modern_parse.py and modern retrieval
recordings. These checks retain the old recordings' raw counts and time labels.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from rivretrieve._internal.recordings import read_recording

_DATA = Path(__file__).parent / "test_data"


def _readings(filename):
    recording = read_recording(_DATA / filename)
    assert recording.request.url.startswith("https://waterservices.usgs.gov/nwis/")
    document = json.loads(recording.content)
    return [row for series in document["value"]["timeSeries"] for block in series["values"] for row in block["value"]]


@pytest.mark.parametrize(
    "parameter,statistic", [("00060", "00003"), ("00065", "00003"), ("00065", "00001"), ("00065", "00002")]
)
def test_historical_daily_recordings_keep_three_naive_labels(parameter, statistic):
    readings = _readings(f"usgs_nwis_07374000_dv_{parameter}_{statistic}_2023-01-01_2023-01-03.recording.json")
    assert [row["dateTime"] for row in readings] == [
        "2023-01-01T00:00:00.000",
        "2023-01-02T00:00:00.000",
        "2023-01-03T00:00:00.000",
    ]
    assert all(datetime.fromisoformat(row["dateTime"]).tzinfo is None for row in readings)


def test_historical_stage_recording_keeps_offset_and_missing_reading():
    readings = _readings("usgs_nwis_07374000_iv_00065_2023-01-01_2023-01-03.recording.json")
    assert len(readings) == 287
    assert readings[0]["dateTime"] == "2023-01-01T00:00:00.000-06:00"
    assert readings[-1]["dateTime"] == "2023-01-03T23:45:00.000-06:00"
    assert all(row["dateTime"].endswith("-06:00") for row in readings)


def test_historical_arizona_recording_keeps_padded_window_and_local_hour():
    readings = _readings("usgs_nwis_09380000_iv_00060_2020-07-01.recording.json")
    assert len(readings) == 480
    assert readings[0]["dateTime"] == "2020-06-29T00:00:00.000-07:00"
    assert readings[-1]["dateTime"] == "2020-07-03T23:45:00.000-07:00"
    assert all(row["dateTime"].endswith("-07:00") for row in readings)
    # The prior boundary probe requested this local-day subset. Retain its
    # evidence without executing a retired provider or inferring a timezone.
    selected = [
        row
        for row in readings
        if datetime(2020, 7, 1)
        <= datetime.fromisoformat(row["dateTime"]).replace(tzinfo=None)
        <= datetime(2020, 7, 1, 23)
    ]
    assert len(selected) == 93
    assert selected[0]["dateTime"] == "2020-07-01T00:00:00.000-07:00"
    assert selected[-1]["dateTime"] == "2020-07-01T23:00:00.000-07:00"

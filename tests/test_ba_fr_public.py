"""Public Bosnia/France selection : certified edge → engine stages → five canonical columns."""

from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport, read_recording

DATA = Path(__file__).parent / "test_data"


def _public(monkeypatch, provider, station, product, start, end, recordings):
    replay = ReplayTransport(tuple(read_recording(DATA / name) for name in recordings))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(provider=provider, station=station, product=product)
    result = rr.fetch(selection, start=start, end=end, receipts=True, on_issue="ignore")
    assert result.data.columns == ["time", "time_zone", "station_id", "product_id", "value"]
    assert result.receipts.entries
    return result


def test_bosnia_public_path_clips_converts_and_keeps_exact_receipts(monkeypatch):
    result = _public(
        monkeypatch,
        "ba_fhmzbih",
        "4024",
        "stage_reported",
        "2025-09-03",
        "2026-09-02T12:00:00",
        ("ba_fhmzbih_metadata_index.recording.json", "ba_fhmzbih_4024_H_1Y.recording.json"),
    )
    assert result.data.height == 8348
    assert result.data["value"][0] == pytest.approx(0.405)
    assert len(result.receipts.entries) == 2
    assert (
        result.receipts.entries[0].content == read_recording(DATA / "ba_fhmzbih_metadata_index.recording.json").content
    )
    assert result.receipts.entries[1].content == read_recording(DATA / "ba_fhmzbih_4024_H_1Y.recording.json").content


def test_france_public_paths_clip_and_preserve_quality_codes_in_receipts(monkeypatch):
    cases = (
        (
            "1011000101",
            "discharge_daily_mean",
            "2025-01-03",
            "2025-01-03",
            ("fr_hubeau_1011000101_QmnJ_padded.recording.json",),
            1,
        ),
        (
            "01001336",
            "water_temperature_reported",
            "2008-07-09",
            "2008-07-10T23:59:59",
            tuple(f"fr_hubeau_01001336_temp_padded_p{i}.recording.json" for i in range(1, 6)),
            37,
        ),
        (
            "Y251002001",
            "stage_instantaneous",
            "2020-01-01",
            "2020-01-02T23:59:59",
            ("fr_hydroportail_H_padded.recording.json",),
            576,
        ),
        (
            "Y251002001",
            "discharge_instantaneous",
            "2020-01-01",
            "2020-01-02T23:59:59",
            ("fr_hydroportail_Q_padded.recording.json",),
            576,
        ),
    )
    for station, product, start, end, recordings, count in cases:
        result = _public(monkeypatch, "fr_hubeau", station, product, start, end, recordings)
        assert result.data.height == count
        contents = b"".join(entry.content for entry in result.receipts.entries)
        if "instantaneous" in product and station == "Y251002001":
            assert b'"s":4' in contents and b'"q":' in contents and b'"m":' in contents and b'"c":0' in contents


def test_bosnia_public_selection_exposes_all_acquired_pairs_including_unknown():
    selection = rr.find(provider="ba_fhmzbih")
    ba = rr.as_frame(selection)
    assert ba.height == 180
    assert ba["station_id"].n_unique() == 60
    assert sum(series.availability == "available" for series in selection.series) == 132
    assert sum(series.availability == "unknown" for series in selection.series) == 48
    unknown = rr.find(provider="ba_fhmzbih", station="2101-B", product="water_temperature_reported")
    assert len(unknown.series) == 1
    assert unknown.series[0].availability == "unknown"


def test_france_sparse_catalogue_does_not_invent_cross_products():
    fr = rr.as_frame(rr.find(provider="fr_hubeau"))
    assert fr.height == 6
    assert rr.as_frame(rr.find(provider="fr_hubeau", station="01001336", product="stage_instantaneous")).is_empty()

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
            "1232000101",
            "discharge_instantaneous",
            "2026-06-01",
            "2026-06-02",
            ("fr_hydroportail_station_Q_padded.recording.json",),
            282,
        ),
    )
    for station, product, start, end, recordings, count in cases:
        result = _public(monkeypatch, "fr_hubeau", station, product, start, end, recordings)
        assert result.data.height == count
        contents = b"".join(entry.content for entry in result.receipts.entries)
        if "instantaneous" in product and station == "Y251002001":
            assert b'"s":4' in contents and b'"q":' in contents and b'"m":' in contents and b'"c":0' in contents


def test_sparse_catalogues_do_not_invent_cross_products():
    ba = rr.as_frame(rr.find(provider="ba_fhmzbih"))
    fr = rr.as_frame(rr.find(provider="fr_hubeau"))
    assert set(zip(ba["station_id"], ba["product_id"], strict=True)) == {
        ("4024", "discharge_reported"),
        ("4024", "stage_reported"),
        ("4110", "water_temperature_reported"),
    }
    assert fr.height == 33_139
    assert rr.as_frame(rr.find(provider="fr_hubeau", station="01001336", product="stage_instantaneous")).is_empty()


def test_france_station_discharge_uses_series_unit_not_display_preference(monkeypatch):
    result = _public(
        monkeypatch,
        "fr_hubeau",
        "1232000101",
        "discharge_instantaneous",
        "2026-06-01",
        "2026-06-02",
        ("fr_hydroportail_station_Q_padded.recording.json",),
    )
    # Raw lexical witnesses supplied independently; existing L/s → m³/s conversion retained.
    assert result.data["value"][0] == pytest.approx(1.28)
    assert result.data["value"][-1] == pytest.approx(1.23)
    recording = read_recording(DATA / "fr_hydroportail_station_Q_padded.recording.json")
    assert result.receipts.entries[0].content == recording.content


def test_france_valid_station_discharge_capture_can_clip_to_empty(monkeypatch):
    result = _public(
        monkeypatch,
        "fr_hubeau",
        "1232000101",
        "discharge_instantaneous",
        "2026-06-03",
        "2026-06-06",
        ("fr_hydroportail_station_Q_empty_clip.recording.json",),
    )
    assert result.data.is_empty()


@pytest.mark.parametrize(
    "station,product",
    [
        ("1120000202", "discharge_daily_max"),
        ("1120000201", "discharge_instantaneous"),
        ("1011000201", "discharge_instantaneous"),
        ("J783301020", "discharge_instantaneous"),
    ],
)
def test_france_unknown_pairs_remain_selectable(station, product):
    selection = rr.find(provider="fr_hubeau", station=station, product=product)
    assert len(selection.series) == 1
    assert selection.series[0].availability == "unknown"
    assert not selection.acquisition_provenance[0].withheld_facts

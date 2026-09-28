"""Execute all CAMELS Markdown snippets against exact USGS publisher responses."""

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from tests.test_documentation_examples import blocks, execute_block
from tests.usgs_modern_recordings import MANIFEST, ModernReplay, body

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = "docs/examples/camels-us.md"
STATIONS = ["01013500", "01022500", "01030500"]
RECORDINGS = [f"daily-camels-{station}-2025" for station in STATIONS]


def test_complete_camels_page(monkeypatch, tmp_path):
    import rivretrieve._internal.discovery as discovery

    replay = ModernReplay(*RECORDINGS)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    scope = {}
    checked = []
    for index, block in enumerate(blocks(PAGE)):
        checked.extend(execute_block(block, scope, f"{PAGE}:block-{index}"))
    assert checked
    assert len(replay.calls) == 3
    assert sorted(request.params["monitoring_location_id"] for request in replay.calls) == [
        "USGS-" + station for station in STATIONS
    ]
    result = scope["result"]
    assert not result.issues
    assert result.data.height == 1095
    assert result.data["station_id"].unique().sort().to_list() == STATIONS
    assert result.data["time"].min() == datetime(2025, 1, 1)
    assert result.data["time"].max() == datetime(2025, 12, 31)
    assert result.data["time_zone"].unique().to_list() == ["unknown"]
    assert result.data["unit"].unique().to_list() == ["m3/s"]
    assert result.data["source_unit"].unique().to_list() == ["ft^3/s"]
    assert result.data["value"].null_count() == 0
    assert result.data["series_id"].n_unique() == 3
    assert len(result.source_series) == 3
    assert_frame_equal(pl.read_parquet(tmp_path / "usgs_daily_2025.parquet"), result.data)
    assert_frame_equal(scope["restored"].data, result.data)
    assert scope["restored"].source_series == result.source_series
    assert scope["restored"].issues == result.issues

    # Decode publisher values independently of the provider parser. Check every
    # retained date/value, not merely the displayed counts or endpoint labels.
    native_rows = []
    identities = []
    for name in RECORDINGS:
        receipt = MANIFEST[name]
        assert receipt["status"] == 200
        assert "2024-12-30%2F2026-01-02" in receipt["original_url"]
        document = json.loads(body(name))
        coordinates = set()
        for feature in document["features"]:
            item = feature["properties"]
            station = item["monitoring_location_id"].removeprefix("USGS-")
            assert item["unit_of_measure"] == "ft^3/s"
            coordinates.add((station, "USGS.WaterData.time_series_id", item["time_series_id"], "catalogue"))
            time = datetime.fromisoformat(item["time"])
            if time.year == 2025:
                native_rows.append((station, time, float(item["value"]) * 0.028316846592))
        identities.extend(coordinates)
    expected = pl.DataFrame(native_rows, schema=["station_id", "time", "value"], orient="row")
    assert_frame_equal(
        result.data.select(expected.columns).sort("station_id", "time"),
        expected.sort("station_id", "time"),
    )
    expected_methods = pl.DataFrame(
        identities, schema=["station_id", "identity_namespace", "published_id", "identity_origin"], orient="row"
    ).sort("station_id")
    assert_frame_equal(scope["source_series"].select(expected_methods.columns).sort("station_id"), expected_methods)
    assert len(result.outcomes) == 3
    for outcome in result.outcomes:
        assert outcome.status == "success"
        assert outcome.window.start == datetime(2025, 1, 1)
        assert outcome.window.end == datetime(2025, 12, 31, 23, 59, 59, 999999)
    assert scope["restored"].outcomes == result.outcomes
    assert scope["restored"].inventories == result.inventories
    assert scope["rr"].to_bundle(scope["restored"]) == scope["rr"].to_bundle(result)

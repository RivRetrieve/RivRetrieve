"""Execute all CAMELS Markdown snippets against exact USGS publisher responses."""

import json
import re
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from tests.usgs_modern_recordings import ModernReplay, body, manifest

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]
PAGE = "docs/examples/camels-us.md"
STATIONS = ["01013500", "01022500", "01030500"]
RECORDINGS = [f"daily-camels-{station}-2015-2026" for station in STATIONS]


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_complete_camels_page(monkeypatch, tmp_path, capsys, retained_evidence_root: Path):
    import rivretrieve._internal.discovery as discovery

    replay = ModernReplay(*RECORDINGS, evidence_root=retained_evidence_root)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MPLBACKEND", "Agg")
    monkeypatch.chdir(tmp_path)
    scope = {}
    examples = re.findall(
        r"```python\n(.*?)```(?:\n\nOutput:\n\n```text\n(.*?)```)?", (ROOT / PAGE).read_text(), re.DOTALL
    )
    assert len(examples) == 5
    displayed = 0
    for index, (code, output) in enumerate(examples):
        exec(compile(code, f"{PAGE}:block-{index}", "exec"), scope)
        assert capsys.readouterr().out == output
        displayed += bool(output)
    assert displayed == 4
    assert len(replay.calls) == 3
    assert sorted(request.params["monitoring_location_id"] for request in replay.calls) == [
        "USGS-" + station for station in STATIONS
    ]
    result = scope["result"]
    assert not result.issues
    assert result.data.height == 3 * 4291
    assert result.data["station_id"].unique().sort().to_list() == STATIONS
    assert result.data["time"].min() == datetime(2015, 1, 1)
    assert result.data["time"].max() == datetime(2026, 9, 30)
    assert result.data["time_zone"].unique().to_list() == ["unknown"]
    assert result.data["unit"].unique().to_list() == ["m3/s"]
    assert result.data["source_unit"].unique().to_list() == ["ft^3/s"]
    assert result.data["value"].null_count() == 0
    assert result.data["series_id"].n_unique() == 3
    assert len(result.source_series) == 3
    assert (tmp_path / "camels_daily_discharge.png").stat().st_size > 0

    # Decode publisher values independently of the provider parser. Check every
    # retained date/value, not merely the displayed counts or endpoint labels.
    native_rows = []
    identities = []
    for name in RECORDINGS:
        receipt = manifest(retained_evidence_root)[name]
        assert receipt["status"] == 200
        assert "2014-12-30%2F2026-10-02" in receipt["original_url"]
        document = json.loads(body(name, evidence_root=retained_evidence_root))
        coordinates = set()
        for feature in document["features"]:
            item = feature["properties"]
            station = item["monitoring_location_id"].removeprefix("USGS-")
            assert item["unit_of_measure"] == "ft^3/s"
            coordinates.add((station, "USGS.WaterData.time_series_id", item["time_series_id"], "catalogue"))
            time = datetime.fromisoformat(item["time"])
            if datetime(2015, 1, 1) <= time <= datetime(2026, 9, 30):
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
    assert_frame_equal(scope["rr"].series(result).select(expected_methods.columns).sort("station_id"), expected_methods)
    assert len(result.outcomes) == 3
    for outcome in result.outcomes:
        assert outcome.status == "success"
        assert outcome.window.start == datetime(2015, 1, 1)
        assert outcome.window.end == datetime(2026, 9, 30, 23, 59, 59, 999999)

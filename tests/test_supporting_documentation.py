"""Execute supporting documentation against packaged evidence and publisher bytes."""

import re
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROOT = Path(__file__).resolve().parents[1]


def execute(page):
    scope = {}
    for block in re.findall(r"```python\n(.*?)```", (ROOT / page).read_text(), re.DOTALL):
        exec(compile(block, page, "exec"), scope)
    return scope


def test_station_metadata_markdown():
    scope = execute("docs/station-metadata.md")
    stations = scope["stations"]
    source = scope["source"]
    keys = ["provider_id", "station_id"]
    assert stations.unique(subset=keys).height == stations.height
    assert_frame_equal(stations.select(keys).sort(keys), source.select(keys).unique().sort(keys))
    areas = scope["areas"].filter(pl.col("station_id") == "02GA010")
    assert areas.height == 2
    assert set(areas["state"]) == {"value", "source_null"}
    assert 1035.0 in scope["values"]


def test_catalogue_evidence_markdown():
    scope = execute("docs/catalogue-evidence.md")
    assert scope["fact"].height == 1
    assert scope["direct"]["acquisition_id"].to_list() == ["workbook:2101-B:water_temperature_reported"]
    assert scope["direct"]["requested_from"].to_list() == [
        ["https://vodostaji.voda.ba/data/internet/stations/3/2101-B/WT/Tvode_1Y.xlsx"]
    ]
    assert scope["graph_document"]["about"]
    assert len(scope["graph"]) > 0


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_architecture_markdown_exact_receipt(monkeypatch, tmp_path, retained_evidence_root: Path):
    import rivretrieve._internal.discovery as discovery
    from tests.usgs_modern_recordings import ModernReplay, body, manifest

    name = "daily-07374000-discharge-mean"
    replay = ModernReplay(name, evidence_root=retained_evidence_root)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    result = execute("docs/architecture.md")["result"]
    expected = pl.DataFrame(
        {
            "time": [datetime(2024, 1, day) for day in range(1, 8)],
            "time_zone": ["unknown"] * 7,
            "station_id": ["07374000"] * 7,
            "product_id": ["discharge_daily_mean"] * 7,
            "unit": ["m3/s"] * 7,
            "source_unit": ["ft^3/s"] * 7,
            "value": [value * 0.028316846592 for value in (174000, 181000, 185000, 187000, 185000, 201000, 214000)],
        }
    )
    assert_frame_equal(result.data.select(expected.columns), expected)
    assert result.data["series_id"].n_unique() == 1
    assert result.source_series
    assert not result.issues
    assert len(replay.calls) == 1
    assert replay.calls[0].params["datetime"] == "2023-12-30/2024-01-09"
    assert result.receipts.entries[0].content == body(name, evidence_root=retained_evidence_root)
    assert result.receipts.entries[0].authorship.value == "publisher_payload"
    assert result.receipts.entries[0].origin.retrieved_at == datetime.fromisoformat(
        manifest(retained_evidence_root)[name]["acquired_utc"]
    )


def test_physical_product_markdown():
    scope = execute("docs/product_dictionary.md")
    facts = scope["facts"]
    assert facts.height > 0
    assert facts["quantity"].unique().to_list() == ["discharge"]
    assert facts["unit"].unique().to_list() == ["m3/s"]
    assert facts["frequency"].null_count() == facts.height
    assert scope["daily_facts"].is_empty()

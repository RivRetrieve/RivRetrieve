"""Execute supporting documentation against packaged evidence and publisher bytes."""

import re
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    "docs/README.md",
    "docs/architecture.md",
    "docs/reference.md",
    "docs/product_dictionary.md",
    "docs/drainage-areas.md",
    "docs/catalogue-evidence.md",
    "docs/catalogue-provenance.md",
    "docs/catalogue-absence.md",
    "docs/design/observation-store-layout.md",
    "docs/development-conventions.md",
    "CONTEXT.md",
)


def execute(page):
    scope = {}
    for block in re.findall(r"```python\n(.*?)```", (ROOT / page).read_text(), re.DOTALL):
        exec(compile(block, page, "exec"), scope)
    return scope


def test_drainage_area_markdown():
    scope = execute("docs/drainage-areas.md")
    assert scope["value"] == 1035.0
    assert scope["areas"].height == 2
    assert set(scope["areas"]["state"]) == {"value", "source_null"}
    assert scope["areas"]["station_id"].unique().to_list() == ["02GA010"]


def test_catalogue_evidence_markdown():
    scope = execute("docs/catalogue-evidence.md")
    assert scope["fact"].height == 1
    assert scope["direct"]["acquisition_id"].to_list() == ["workbook:2101-B:water_temperature_reported"]
    assert scope["direct"]["requested_from"].to_list() == [
        ["https://vodostaji.voda.ba/data/internet/stations/3/2101-B/WT/Tvode_1Y.xlsx"]
    ]
    assert scope["graph_document"]["about"]
    assert len(scope["graph"]) > 0


def test_architecture_markdown_exact_receipt(monkeypatch, tmp_path):
    import rivretrieve._internal.discovery as discovery
    from tests.usgs_modern_recordings import MANIFEST, ModernReplay, body

    name = "daily-07374000-discharge-mean"
    replay = ModernReplay(name)
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
    assert result.receipts.entries[0].content == body(name)
    assert result.receipts.entries[0].authorship.value == "publisher_payload"
    assert result.receipts.entries[0].origin.retrieved_at == datetime.fromisoformat(MANIFEST[name]["acquired_utc"])


@pytest.mark.parametrize("page", PAGES)
def test_supporting_documentation_links(page):
    path = ROOT / page
    for destination in re.findall(r"\[[^\]]*\]\(([^)]+)\)", path.read_text()):
        if "://" in destination or destination.startswith("mailto:"):
            continue
        local, _, fragment = destination.partition("#")
        target = (path.parent / local).resolve() if local else path
        assert target.exists(), (page, destination)
        if fragment and target.suffix == ".md":
            headings = re.findall(r"^#{1,6} (.+)$", target.read_text(), re.MULTILINE)
            anchors = [re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-") for heading in headings]
            assert fragment in anchors, (page, destination)


def test_physical_product_markdown():
    scope = execute("docs/product_dictionary.md")
    facts = scope["facts"]
    assert facts.height > 0
    assert facts["quantity"].unique().to_list() == ["discharge"]
    assert facts["unit"].unique().to_list() == ["m3/s"]
    assert facts["frequency"].null_count() == facts.height
    assert scope["daily_facts"].is_empty()

"""Execute supporting documentation against packaged evidence and publisher bytes."""

import re
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

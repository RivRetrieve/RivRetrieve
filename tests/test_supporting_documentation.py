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
    import rivretrieve as rr

    scope = execute("docs/station-metadata.md")
    stations = scope["metadata"]
    source = rr.metadata(scope["selection"], view="source")
    keys = ["provider_id", "station_id"]
    assert stations.unique(subset=keys).height == stations.height
    assert_frame_equal(stations.select(keys).sort(keys), source.select(keys).unique().sort(keys))
    assert_frame_equal(
        scope["areas"],
        pl.DataFrame(
            {
                "station_id": ["05AA003", "05AA003"],
                "drainage_area_field": ["DRAINAGE_AREA_EFFECT", "DRAINAGE_AREA_GROSS"],
                "drainage_area_value": ["1129.0", "1130.0"],
                "drainage_area_unit": ["km2", "km2"],
            }
        ),
    )
    assert scope["row"]["water_body_name_field"] is None
    assert scope["row"]["water_body_name_value"] is None
    missing = scope["missing_areas"]
    assert missing["drainage_area_value"] == [None, None, None, None]
    null_source = rr.metadata(rr.pick(scope["norway"], station="16.28.0"), view="source").filter(
        pl.col("attribute_role") == "drainage_area"
    )
    assert null_source["source_field"].to_list() == missing["drainage_area_field"]
    assert null_source["state"].to_list() == ["source_null"] * 4
    assert null_source["source_value"].null_count() == 4


def test_catalogue_evidence_markdown():
    scope = execute("docs/catalogue-evidence.md")
    assert scope["fact"].height == 1
    assert scope["direct"]["acquisition_id"].to_list() == ["workbook:2101-B:water_temperature_reported"]
    assert scope["direct"]["requested_from"].to_list() == [
        ["https://vodostaji.voda.ba/data/internet/stations/3/2101-B/WT/Tvode_1Y.xlsx"]
    ]
    assert scope["graph_document"]["about"]
    assert len(scope["graph"]) > 0

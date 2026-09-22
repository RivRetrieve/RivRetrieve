"""Untouched publisher evidence integrity and explicitly bounded historical comparisons."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

import polars as pl
import polars.testing as pt
import pytest

from tests.usgs_modern_recordings import DATA, MANIFEST, body


def test_every_retained_source_body_has_exact_hash_and_acquisition_manifest():
    hashes = dict(
        line.split("  ", 1)[::-1] for path in DATA.glob("*SHA256SUMS") for line in path.read_text().splitlines()
    )
    records = [
        *MANIFEST.values(),
        *json.loads((DATA / "curated-manifest.json").read_text()),
        *json.loads((DATA / "historical-manifest.json").read_text()),
    ]
    assert len(records) == 53
    assert len(hashes) == len({item["file"] for item in records}) == 47
    assert set(hashes) == {item["file"] for item in records}
    for item in records:
        content = (DATA / item["file"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == item["sha256"] == hashes[item["file"]]
        assert len(content) == item["bytes"]
    for name, digest in hashes.items():
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == digest
    for item in MANIFEST.values():
        assert item["authorship"] == "publisher_response"
        assert datetime.fromisoformat(item["acquired_utc"]).utcoffset().total_seconds() == 0
        assert item["final_url"]
        assert item["request_headers"]["User-Agent"] == "RivRetrieve-source-evidence"
    historical = json.loads((DATA / "historical-manifest.json").read_text())
    assert all(item["final_url"] is None for item in historical)


@pytest.mark.parametrize(
    "parameter,legacy_file,name",
    [
        ("00060", "legacy2010.body", "continuous-07374000-2010-discharge"),
        ("00065", "legacy-stage2010.body", "continuous-07374000-2010-stage"),
    ],
)
def test_bounded_2010_observations_match_legacy_published_instants_and_numbers(parameter, legacy_file, name):
    legacy = json.loads((DATA / "prior-history" / legacy_file).read_bytes())
    rows = [
        (datetime.fromisoformat(value["dateTime"]).astimezone(UTC), str(Decimal(value["value"])))
        for series in legacy["value"]["timeSeries"]
        if series["variable"]["variableCode"][0]["value"] == parameter
        for block in series["values"]
        for value in block["value"]
    ]
    modern = [
        (
            datetime.fromisoformat(feature["properties"]["time"]).astimezone(UTC),
            str(Decimal(feature["properties"]["value"])),
        )
        for feature in json.loads(body(name))["features"]
    ]
    lower, upper = datetime(2010, 6, 1, 5, tzinfo=UTC), datetime(2010, 6, 2, 4, 59, 59, tzinfo=UTC)
    rows = [row for row in rows if lower <= row[0] <= upper]
    modern = [row for row in modern if lower <= row[0] <= upper]
    assert len(rows) == len(modern) == 96
    pt.assert_frame_equal(
        pl.DataFrame(rows, schema=["time", "value"], orient="row").sort("time"),
        pl.DataFrame(modern, schema=["time", "value"], orient="row").sort("time"),
    )
    # A finite value comparison neither aliases the independent IDs nor proves all history.


def test_present_null_publisher_recording_is_not_an_empty_answer():
    from dataclasses import replace

    from rivretrieve._internal.engine import SourceCoordinates
    from rivretrieve._internal.providers.usgs_nwis.config import config
    from rivretrieve._internal.providers.usgs_nwis.parse import parse
    from tests.test_usgs_modern_parse import payload

    original = body("daily-11465200-present-null")
    base = payload({"type": "FeatureCollection", "features": []})
    coordinates = replace(base.source_coordinates.value, monitoring_location_id="USGS-11465200")
    result = parse(
        replace(
            base,
            content=original,
            station_products=(("11465200", base.station_products[0][1]),),
            source_coordinates=SourceCoordinates(coordinates),
        ),
        config(),
    )
    assert result.rows.height == 11
    assert result.rows["value"].null_count() == 11
    assert all(outcome.status.value == "success" for outcome in result.outcomes)
    source = json.loads(original)
    assert {f["properties"]["approval_status"] for f in source["features"]} == {"Provisional"}
    assert all(f["properties"]["qualifier"] == ["DISCONTINUED"] for f in source["features"])


def test_shared_documentation_bytes_keep_independent_historical_acquisitions():
    historical = json.loads((DATA / "historical-manifest.json").read_text())
    # This digest pins every pre-dedup acquisition field except its local body path.
    acquisitions = [{key: value for key, value in item.items() if key != "file"} for item in historical]
    assert (
        hashlib.sha256(json.dumps(acquisitions, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        == "6e0150a7a866cc6ded0dddaeaadfaf2b739f035f144c81ef26e90411ee1b0e0f"
    )
    shared = [item for item in historical if item["file"].startswith("new/")]
    assert len(shared) == 6
    for item in shared:
        current = next(record for record in MANIFEST.values() if record["file"] == item["file"])
        assert item["sha256"] == current["sha256"]
        assert item["acquired_utc"] != current["acquired_utc"]
        assert item["final_url"] is None
        assert item["provenance_completeness"] == "final_url_not_recorded"
        assert item["source_recording"].startswith(".worktrees/usgs-modern-history-assessment/")

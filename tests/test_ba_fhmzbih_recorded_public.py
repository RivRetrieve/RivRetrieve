"""Bosnia public replay : RecordedWorkbooks × SourceOnlyExpectations → PublicResultChecks.

Literal expectations: test_data/ba_fhmzbih_public_source_expectations.md.
Authored independently from complete source XML, not implementation output.
"""

from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    BoundaryProbe,
    WallClockExpectation,
    run_boundary_probes,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.recordings import ReplayTransport, read_recording

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

DATA = Path("tests/test_data")


@pytest.mark.parametrize(
    ("station", "product", "code", "start", "end", "count", "first", "last"),
    [
        (
            "2101-B",
            "discharge_reported",
            "Q",
            "2026-09-01",
            "2026-09-03T23:59:59",
            72,
            "2026-09-01T00:00:00",
            "2026-09-03T23:00:00",
        ),
        (
            "2101-B",
            "stage_reported",
            "H",
            "2026-09-01",
            "2026-09-03T23:59:59",
            72,
            "2026-09-01T00:00:00",
            "2026-09-03T23:00:00",
        ),
        (
            "2010",
            "discharge_reported",
            "Q",
            "2026-05-22",
            "2026-05-24T23:59:59",
            70,
            "2026-05-22T00:00:00",
            "2026-05-24T23:00:00",
        ),
    ],
)
def test_recorded_public_boundaries_keep_exact_identity_and_blank_rows(
    retained_evidence_root, monkeypatch, station, product, code, start, end, count, first, last
):
    metadata = read_recording(retained_evidence_root / DATA / "ba_fhmzbih_metadata_index.recording.json")
    workbook = read_recording(retained_evidence_root / DATA / f"ba_fhmzbih_{station}_{code}_1Y.recording.json")
    results = []

    def run(replay):
        monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
        selection = rr.find(provider="ba_fhmzbih", station=station, quantity={"Q": "discharge", "H": "stage"}[code])
        result = rr.fetch(selection, start=start, end=end, receipts=True, on_issue="ignore")
        results.append(result)
        return result.data

    probe = BoundaryProbe(
        ProviderId("ba_fhmzbih"),
        ProductId(product),
        (metadata, workbook),
        {
            READING_COUNT: count,
            FIRST_WALL_CLOCK_TIME: WallClockExpectation(first, "unknown"),
            LAST_WALL_CLOCK_TIME: WallClockExpectation(last, "unknown"),
        },
        run,
    )
    run_boundary_probes(((probe.provider_id, probe.product_id),), (probe,))
    result = results[0]
    assert result.data["station_id"].unique().to_list() == [station]
    assert result.data["product_id"].unique().to_list() == [product]
    assert [receipt.content for receipt in result.receipts.entries] == [metadata.content, workbook.content]
    if station == "2010":
        blank_times = result.data.filter(pl.col("value").is_null())["time"].to_list()
        assert blank_times == [datetime(2026, 5, 23, 1), datetime(2026, 5, 23, 4)]
    else:
        expected = 0.432 if code == "Q" else 0.052
        assert result.data["value"][0] == pytest.approx(expected)
        assert result.data["value"][-1] == pytest.approx(expected)


def test_recorded_empty_temperature_remains_selectable_and_keeps_receipts(retained_evidence_root, monkeypatch):
    recordings = tuple(
        read_recording(retained_evidence_root / DATA / name)
        for name in ("ba_fhmzbih_metadata_index.recording.json", "ba_fhmzbih_2101-B_WT_1Y.recording.json")
    )
    replay = ReplayTransport(recordings)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(provider="ba_fhmzbih", station="2101-B", quantity="temperature")
    assert len(selection.series) == 1
    assert all(inventory.completeness == "incomplete" for inventory in selection.inventories)
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-03T23:59:59", receipts=True, on_issue="ignore")
    assert result.data.is_empty()
    assert result.data.columns == [
        "time",
        "time_zone",
        "station_id",
        "product_id",
        "series_id",
        "facts_id",
        "quantity",
        "source_unit",
        "unit",
        "value",
    ]
    assert [receipt.content for receipt in result.receipts.entries] == [recording.content for recording in recordings]

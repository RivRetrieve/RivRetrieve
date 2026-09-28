"""Rolling publication rows do not certify completeness of requested history."""

import json
from datetime import UTC, datetime
from io import BytesIO

import openpyxl
import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.transport import TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def workbook(rows):
    document = openpyxl.Workbook()
    sheet = document.active
    for row in [
        ("#Station Name", "Authored station"),
        ("#Station Number", "4024"),
        ("#Station Parameter Name", "Vodostaj"),
        ("#Timeseries Name", "81 Web Kontinuirani"),
        ("#Unit Symbol", "cm"),
        ("#Rows", len(rows)),
        ("#", None),
        ("#Timestamp", "Value"),
        *rows,
    ]:
        sheet.append(row)
    stream = BytesIO()
    document.save(stream)
    document.close()
    return stream.getvalue()


class SnapshotTransport:
    def __init__(self, rows):
        self.content = workbook(rows)
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        metadata = request.url.endswith("index.json")
        content = (
            json.dumps([{"metadata_station_no": "4024", "metadata_site_no": "test"}]).encode()
            if metadata
            else self.content
        )
        return TransportResponse(
            content,
            200,
            datetime(2026, 9, 28, tzinfo=UTC),
            "application/json" if metadata else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            request.url,
            request.params or {},
        )


def test_advancing_snapshot_upserts_only_published_rows_and_keeps_held_history(monkeypatch, tmp_path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    old_label, overlap, new_label = (datetime(2025, 9, day) for day in (4, 5, 6))
    source = SnapshotTransport([(old_label, 10), (overlap, 20)])
    monkeypatch.setattr(discovery, "HttpClient", lambda: source)
    selection = rr.find(provider="ba_fhmzbih", station="4024", quantity="stage")

    def fetch(mode):
        return rr.fetch(selection, start="2025-09-04", end="2025-09-06", cache=mode, on_issue="ignore")

    seeded = fetch("refresh")
    assert seeded.data.height == 2
    assert all(item.coverage == "observations" for item in seeded.outcomes)
    source.content = workbook([(overlap, None), (new_label, 30)])
    refreshed = fetch("refresh")
    expected = pl.DataFrame({"time": [old_label, overlap, new_label], "value": [0.1, None, 0.3]})
    pt.assert_frame_equal(refreshed.data.select("time", "value").sort("time"), expected)
    # An empty snapshot has no published rows to replace and certifies no empty interval.
    source.content = workbook([])
    emptied = fetch("refresh")
    pt.assert_frame_equal(emptied.data.select("time", "value").sort("time"), expected)
    before = len(source.calls)
    reused = fetch("reuse")
    assert len(source.calls) > before
    pt.assert_frame_equal(reused.data.select("time", "value").sort("time"), expected)


def test_recent_snapshot_does_not_certify_arbitrary_old_empty_history(monkeypatch, tmp_path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    source = SnapshotTransport([(datetime(2026, 9, 1), 10)])
    monkeypatch.setattr(discovery, "HttpClient", lambda: source)
    selection = rr.find(provider="ba_fhmzbih", station="4024", quantity="stage")
    for _ in range(2):
        before = len(source.calls)
        result = rr.fetch(selection, start="2000-01-01", end="2000-01-31", cache="reuse", on_issue="ignore")
        assert result.data.is_empty()
        assert len(source.calls) > before
        assert all(item.coverage == "observations" for item in result.outcomes)

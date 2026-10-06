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
        self.retrieved_at = datetime(2026, 9, 28, tzinfo=UTC)

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
            self.retrieved_at,
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
    source.retrieved_at = datetime(2026, 9, 29, tzinfo=UTC)
    source.content = workbook([(overlap, None), (new_label, 30)])
    refreshed = fetch("refresh")
    expected = pl.DataFrame({"time": [old_label, overlap, new_label], "value": [0.1, None, 0.3]})
    pt.assert_frame_equal(refreshed.data.select("time", "value").sort("time"), expected)

    def vintages(result):
        pairs = [(key[1], outcome.retrieved_at) for outcome in result.outcomes for key in outcome.observation_keys]
        assert len(pairs) == len({key for key, _ in pairs})
        return dict(pairs)

    expected_vintages = {
        old_label: datetime(2026, 9, 28, tzinfo=UTC),
        overlap: datetime(2026, 9, 29, tzinfo=UTC),
        new_label: datetime(2026, 9, 29, tzinfo=UTC),
    }
    # The read keeps the supporting acquisition unchanged, including its
    # originally published overlap key. Current row ownership remains exact in
    # the committed store, not inferred by rewriting returned acquisition IDs.
    assert seeded.outcomes[0] in refreshed.outcomes
    assert vintages(rr.cache_status("ba_fhmzbih").manifest) == expected_vintages
    assert {(key[1], outcome.retrieved_at) for outcome in refreshed.outcomes for key in outcome.observation_keys} == {
        *expected_vintages.items(),
        (overlap, datetime(2026, 9, 28, tzinfo=UTC)),
    }
    # An empty snapshot has no published rows to replace and certifies no empty interval.
    source.retrieved_at = datetime(2026, 9, 30, tzinfo=UTC)
    source.content = workbook([])
    emptied = fetch("refresh")
    pt.assert_frame_equal(emptied.data.select("time", "value").sort("time"), expected)
    assert vintages(emptied) == expected_vintages
    before = len(source.calls)
    reused = fetch("reuse")
    assert len(source.calls) > before
    pt.assert_frame_equal(reused.data.select("time", "value").sort("time"), expected)
    assert vintages(reused) == expected_vintages
    restored = rr.from_bundle(rr.to_bundle(reused))
    assert restored.outcomes == reused.outcomes


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


@pytest.mark.parametrize("defect", ["duplicate", "facts", "zone", "timestamp", "empty"])
def test_snapshot_key_contract_rejects_ambiguous_evidence(defect):
    from rivretrieve._internal.source_series import RetrievalOutcome

    key = ("facts", datetime(2025, 9, 4), "unknown")
    data = {
        "outcome_id": "snapshot",
        "series_id": "series",
        "station_id": "4024",
        "product_id": "stage_reported",
        "window": {"start": datetime(2025, 9, 4), "end": datetime(2025, 9, 5)},
        "status": "success",
        "facts_ids": ("facts",),
        "coverage": "observations",
        "observation_keys": (key,),
    }
    assert RetrievalOutcome.model_validate_json(RetrievalOutcome(**data).model_dump_json()).observation_keys == (key,)
    if defect == "duplicate":
        data["observation_keys"] = (key, key)
    elif defect == "facts":
        data["observation_keys"] = (("other-facts", key[1], key[2]),)
    elif defect == "zone":
        data["observation_keys"] = ((key[0], key[1], ""),)
    elif defect == "timestamp":
        data["observation_keys"] = ((key[0], datetime(2000, 1, 1), key[2]),)
    else:
        data["status"] = "empty"
    with pytest.raises(ValueError):
        RetrievalOutcome(**data)


def test_repeated_source_wall_clock_labels_keep_all_rows_with_one_acquisition_reference(monkeypatch, tmp_path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    label = datetime(2025, 9, 4)
    source = SnapshotTransport([(label, 10), (label, 20)])
    monkeypatch.setattr(discovery, "HttpClient", lambda: source)
    selection = rr.find(provider="ba_fhmzbih", station="4024", quantity="stage")
    first = rr.fetch(selection, start="2025-09-04", end="2025-09-04T23:59:59", cache="refresh", on_issue="ignore")
    assert first.data["value"].to_list() == [0.1, 0.2]
    assert sum(len(item.observation_keys) for item in first.outcomes) == 1
    source.content = workbook([])
    held = rr.fetch(selection, start="2025-09-04", end="2025-09-04T23:59:59", cache="refresh", on_issue="ignore")
    pt.assert_frame_equal(held.data, first.data)
    assert sum(len(item.observation_keys) for item in held.outcomes) == 1

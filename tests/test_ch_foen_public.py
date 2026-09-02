from datetime import datetime
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.observations import ReceiptAuthorship
from rivretrieve._internal.recordings import ReplayTransport, read_recording

_RECORDING = read_recording(Path(__file__).parent / "test_data" / "ch_foen_2135_rest_engine_2026-09-01.recording.json")


def test_public_selection_uses_anonymous_rest_and_returns_five_columns_with_raw_receipt(
    monkeypatch: pytest.MonkeyPatch,
):
    replay = ReplayTransport((_RECORDING,))
    monkeypatch.setattr(driver_module, "HttpClient", lambda: replay)
    selection = rr.find(provider="ch_foen", station="2135", product="discharge_reported")
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-02", receipts=True, on_issue="ignore")
    assert result.data.columns == ["time", "time_zone", "station_id", "product_id", "value"]
    assert dict(result.data.group_by("product_id").len().iter_rows()) == {"discharge_reported": 244}
    assert result.data["time"].min() == datetime(2026, 9, 1)
    assert result.data["time"].max() == datetime(2026, 9, 2, 16, 30)
    assert len(result.receipts.entries) == 1
    assert result.receipts.entries[0].content == _RECORDING.content
    assert result.receipts.entries[0].authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    utc = rr.to_utc(result)
    assert set(utc.data["time_zone"]) == {"+00:00"}


def test_public_receipts_false_omits_publisher_bytes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(driver_module, "HttpClient", lambda: ReplayTransport((_RECORDING,)))
    result = rr.fetch(
        rr.find(provider="ch_foen", station="2135", product="discharge_reported"),
        start="2026-09-01",
        end="2026-09-02",
        receipts=False,
        on_issue="ignore",
    )
    assert result.receipts.entries == ()
    assert result.provenance.endpoints == ("https://api.existenz.ch/apiv1/hydro/daterange",)
    assert result.provenance.retrieved_at == _RECORDING.retrieved_at
    assert len(result.provenance.calls_made) == 1
    assert result.provenance.calls_made[0]["request_parameters"] == dict(_RECORDING.request.parameters or {})
    assert result.provenance.calls_made[0]["query"] == {
        "status": "unknown",
        "reason": "unknown",
    }

"""publisher receipt : USGSFetch × ReceiptRequest → UntouchedPublisherPayload."""

from datetime import datetime
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.observations import ReceiptAuthorship
from tests.usgs_modern_recordings import ModernReplay, body, manifest

_RECORDING = "daily-07374000-discharge-mean"


def test_usgs_fetch_receipt_is_untouched_publisher_payload(
    monkeypatch: pytest.MonkeyPatch, retained_evidence_root: Path
) -> None:
    recording = manifest(retained_evidence_root)[_RECORDING]
    replay = ModernReplay(_RECORDING, evidence_root=retained_evidence_root)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    selection = rr.find(
        provider="usgs_nwis",
        station="07374000",
        quantity="discharge",
        frequency="daily",
        statistic="mean",
    )
    result = rr.fetch(
        selection,
        start="2024-01-01",
        end="2024-01-07",
        receipts=True,
        on_issue="ignore",
    )

    assert result.provenance.provider_id == "usgs_nwis"
    assert result.provenance.source == "live"
    assert result.data.select("station_id", "product_id", "time", "time_zone").row(0) == (
        "07374000",
        "discharge_daily_mean",
        datetime(2024, 1, 1),
        "unknown",
    )
    assert not hasattr(result, "raw")
    assert len(result.receipts.entries) == 1
    receipt = result.receipts.entries[0]
    assert receipt.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    assert receipt.authorship.value == "publisher_payload"
    assert receipt.content == body(_RECORDING, evidence_root=retained_evidence_root)
    assert receipt.origin.url == "https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items"
    assert dict(receipt.origin.request_parameters) == dict(replay.calls[0].params)
    assert receipt.origin.status_code == recording["status"]
    assert receipt.origin.retrieved_at == datetime.fromisoformat(recording["acquired_utc"])
    assert receipt.origin.content_type == recording["headers"]["Content-Type"]

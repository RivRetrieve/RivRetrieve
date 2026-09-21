"""publisher receipt : USGSFetch × ReceiptRequest → UntouchedPublisherPayload."""

from datetime import datetime
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.observations import ReceiptAuthorship
from rivretrieve._internal.recordings import ReplayTransport, read_recording

_RECORDING = Path("tests/test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json")


def test_usgs_fetch_receipt_is_untouched_publisher_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    recording = read_recording(_RECORDING)
    replay = ReplayTransport((recording,))
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
        start="2023-01-01",
        end="2023-01-01",
        receipts=True,
        on_issue="ignore",
    )

    assert result.provenance.provider_id == "usgs_nwis"
    assert result.provenance.source == "live"
    assert result.data.select("station_id", "product_id", "time", "time_zone").row(0) == (
        "07374000",
        "discharge_daily_mean",
        datetime(2023, 1, 1),
        "unknown",
    )
    assert not hasattr(result, "raw")
    assert len(result.receipts.entries) == 1
    receipt = result.receipts.entries[0]
    assert receipt.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    assert receipt.authorship.value == "publisher_payload"
    assert receipt.content is recording.content
    assert receipt.origin.url == "https://waterservices.usgs.gov/nwis/dv/"
    assert receipt.origin.request_parameters == recording.request.parameters
    assert receipt.origin.status_code == recording.status_code
    assert receipt.origin.retrieved_at == recording.retrieved_at
    assert receipt.origin.content_type == recording.content_type

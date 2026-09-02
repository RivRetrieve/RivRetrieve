"""publisher receipt : USGSFetch × ReceiptRequest → UntouchedPublisherPayload."""

from datetime import datetime
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.observations import ReceiptAuthorship
from rivretrieve._internal.recordings import RecordingEnvelope, read_recording
from rivretrieve._internal.transport import TransportRequest, TransportResponse

_RECORDING = Path("tests/test_data/usgs_nwis_07374000_dv_00060_00003_2023-01-01_2023-01-03.recording.json")


class _PublisherClient:
    def __init__(self, recording: RecordingEnvelope) -> None:
        self.recording = recording
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        return TransportResponse(
            content=self.recording.content,
            status_code=self.recording.status_code,
            retrieved_at=self.recording.retrieved_at,
            content_type=self.recording.content_type,
            url=request.url,
            request_parameters={} if request.params is None else request.params,
        )


def test_usgs_fetch_receipt_is_untouched_publisher_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    recording = read_recording(_RECORDING)
    client = _PublisherClient(recording)
    monkeypatch.setattr(driver_module, "HttpClient", lambda: client)

    selection = rr.find(
        provider="usgs_nwis",
        station="07374000",
        product="discharge_daily_mean",
    )
    result = rr.fetch(
        selection,
        start="2023-01-01",
        end="2023-01-01",
        receipts=True,
        on_issue="ignore",
    )

    assert len(client.requests) == 1
    assert client.requests[0].url == "https://waterservices.usgs.gov/nwis/dv/"
    assert client.requests[0].params == {
        "format": "json",
        "sites": "07374000",
        "startDT": "2022-12-30",
        "endDT": "2023-01-03",
        "parameterCd": "00060",
        "statCd": "00003",
    }
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
    assert receipt.origin.request_parameters == client.requests[0].params
    assert receipt.origin.retrieved_at == recording.retrieved_at
    assert receipt.origin.content_type == recording.content_type

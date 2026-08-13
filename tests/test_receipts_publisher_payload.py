"""publisher receipt : USGSFetch × ReceiptRequest → UntouchedPublisherPayload."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal.observations import ReceiptAuthorship
from rivretrieve._internal.providers.usgs_nwis import fetch as fetch_module
from rivretrieve._internal.transport import TransportRequest, TransportResponse

_FIXTURE = Path("tests/test_data/usgs_nwis_07374000_dv_00060_2023-01-01.json")


class _PublisherClient:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        return TransportResponse(
            content=self.body,
            status_code=200,
            retrieved_at=datetime(2026, 8, 11, tzinfo=UTC),
            content_type="application/json",
            url=request.url,
            request_parameters={} if request.params is None else request.params,
        )


def test_usgs_fetch_receipt_is_untouched_publisher_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    publisher_body = _FIXTURE.read_bytes() + b" "
    client = _PublisherClient(publisher_body)
    monkeypatch.setattr(fetch_module, "HttpClient", lambda: client)

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
    assert not hasattr(result, "raw")
    assert len(result.receipts.entries) == 1
    receipt = result.receipts.entries[0]
    assert receipt.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    assert receipt.authorship.value == "publisher_payload"
    assert receipt.content is publisher_body

"""Public live path : selection × exact recording → coalesced result and receipt."""

from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.engine import UnknownOriginFact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.recordings import RecordingEnvelope, ReplayTransport, read_recording
from rivretrieve._internal.transport import TransportRequest, TransportResponse


class _CountingReplay(ReplayTransport):
    def __init__(self, recording: RecordingEnvelope) -> None:
        super().__init__((recording,))
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        response = super().send(request)
        self.requests.append(request)
        return response


@pytest.mark.parametrize(
    ("provider", "station", "recording", "start", "end", "expected_rows"),
    [
        (
            "lt_lhmt",
            "anyksciu-vms",
            "lt_lhmt_anyksciu-vms_2023-06.recording.json",
            "2023-06-03",
            "2023-06-28",
            52,
        ),
        (
            "th_thaiwater",
            "1373273",
            "th_thaiwater_1373273_2026-07-30_2026-08-04.recording.json",
            "2026-08-01",
            "2026-08-02T23:50:00",
            576,
        ),
    ],
)
def test_public_fetch_replays_padded_request_and_coalesces_one_call_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    station: str,
    recording: str,
    start: str,
    end: str,
    expected_rows: int,
) -> None:
    envelope = read_recording(Path(__file__).parent / "test_data" / recording)
    replay = _CountingReplay(envelope)
    monkeypatch.setattr(driver_module, "HttpClient", lambda: replay)

    selection = rr.find(provider=provider, station=station)
    result = rr.fetch(selection, start=start, end=end, receipts=True, on_issue="ignore")

    assert result.data.columns == ["time", "time_zone", "station_id", "product_id", "value"]
    assert result.data.height == expected_rows
    assert result.data.equals(
        result.data.sort(["station_id", "product_id", "time", "time_zone", "value"], maintain_order=True)
    )
    assert set(result.data["product_id"]) == set(rr.products(provider))
    assert len(replay.requests) == 1
    assert len(result.receipts.entries) == 1
    receipt = result.receipts.entries[0]
    assert receipt.content == envelope.content
    assert receipt.origin.url == envelope.request.url
    assert not isinstance(receipt.origin.request_parameters, UnknownOriginFact)
    assert dict(receipt.origin.request_parameters) == dict(envelope.request.parameters or {})
    assert receipt.origin.status_code == envelope.status_code
    assert receipt.origin.retrieved_at == envelope.retrieved_at
    assert receipt.origin.content_type == envelope.content_type

    omitted_replay = _CountingReplay(envelope)
    monkeypatch.setattr(driver_module, "HttpClient", lambda: omitted_replay)
    without_receipts = rr.fetch(selection, start=start, end=end, receipts=False, on_issue="ignore")
    assert len(omitted_replay.requests) == 1
    assert without_receipts.receipts.entries == ()

    if provider == "th_thaiwater":
        with pytest.raises(FatalContractError, match="576 observation rows for provider 'th_thaiwater'.*unknown"):
            rr.to_utc(result)


def test_thaiwater_find_has_only_the_two_recorded_edges() -> None:
    established = rr.as_frame(rr.find(provider="th_thaiwater", station="1373273"))
    absent = rr.as_frame(rr.find(provider="th_thaiwater", station="1373272"))

    assert established.select("station_id", "product_id").sort("product_id").rows() == [
        ("1373273", "discharge_reported"),
        ("1373273", "stage_reported"),
    ]
    assert absent.is_empty()

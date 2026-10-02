"""Public live path : selection × exact recording → coalesced result and receipt."""

from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
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
@pytest.mark.recorded(
    "tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json",
    "tests/test_data/th_thaiwater_1373273_2026-07-30_2026-08-04.recording.json",
)
def test_public_fetch_preserves_provider_acquisition_boundaries(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    station: str,
    recording: str,
    start: str,
    end: str,
    expected_rows: int,
) -> None:
    envelope = read_recording(retained_evidence_root / "tests/test_data" / recording)
    replay = _CountingReplay(envelope)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    selection = rr.find(provider=provider, station=station)
    result = rr.fetch(selection, start=start, end=end, receipts=True, on_issue="ignore")

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
    assert result.data.height == expected_rows
    assert result.data.equals(
        result.data.sort(["station_id", "product_id", "time", "time_zone", "value"], maintain_order=True)
    )
    assert set(result.data["product_id"]) == set(rr.products(provider))
    expected_calls = 1 if provider == "lt_lhmt" else 2
    assert len(replay.requests) == expected_calls
    assert len(result.receipts.entries) == expected_calls
    receipt = result.receipts.entries[0]
    assert receipt.content == envelope.content
    assert receipt.origin.url == envelope.request.url
    assert not isinstance(receipt.origin.request_parameters, UnknownOriginFact)
    assert dict(receipt.origin.request_parameters) == dict(envelope.request.parameters or {})
    assert receipt.origin.status_code == envelope.status_code
    assert receipt.origin.retrieved_at == envelope.retrieved_at
    assert receipt.origin.content_type == envelope.content_type

    omitted_replay = _CountingReplay(envelope)
    monkeypatch.setattr(discovery, "HttpClient", lambda: omitted_replay)
    without_receipts = rr.fetch(selection, start=start, end=end, receipts=False, on_issue="ignore")
    assert len(omitted_replay.requests) == expected_calls
    assert without_receipts.receipts.entries == ()

    if provider == "th_thaiwater":
        with pytest.raises(FatalContractError, match="576 observation rows for provider 'th_thaiwater'.*unknown"):
            rr.to_utc(result)


def test_thaiwater_find_exposes_the_original_baseline_available_and_unknown_pairs() -> None:
    baseline = rr.as_frame(rr.find(provider="th_thaiwater"))
    positive_beyond_sample = rr.as_frame(rr.find(provider="th_thaiwater", station="1373272"))
    unknown_beyond_sample = rr.as_frame(rr.find(provider="th_thaiwater", station="11688546"))

    assert baseline.height == 1650
    assert baseline["station_id"].n_unique() == 825
    assert positive_beyond_sample.select("station_id", "product_id").sort("product_id").rows() == [
        ("1373272", "discharge_reported"),
        ("1373272", "stage_reported"),
    ]
    assert unknown_beyond_sample.select("station_id", "product_id").sort("product_id").rows() == [
        ("11688546", "discharge_reported"),
        ("11688546", "stage_reported"),
    ]


@pytest.mark.recorded("tests/test_data/th_thaiwater_11688546_2026-06-08_2026-09-06.recording.json")
def test_thaiwater_null_rows_do_not_establish_complete_inventory_for_reuse(
    retained_evidence_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = read_recording(
        retained_evidence_root / "tests/test_data/th_thaiwater_11688546_2026-06-08_2026-09-06.recording.json"
    )
    replay = _CountingReplay(envelope)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(provider="th_thaiwater", station="11688546")
    result = rr.fetch(selection, start="2026-06-10", end="2026-09-04", cache="reuse", receipts=True, on_issue="ignore")
    assert not result.data.is_empty()
    assert result.data["value"].is_null().all()
    assert result.data["time_zone"].unique().to_list() == ["unknown"]
    assert set(result.data["station_id"]) == {"11688546"}
    assert len(replay.requests) == 2
    assert all(entry.content == envelope.content for entry in result.receipts.entries)
    repeated = rr.fetch(selection, start="2026-06-10", end="2026-09-04", cache="reuse", on_issue="ignore")
    # Incomplete source inventory cannot satisfy an unrestricted all-series request.
    assert len(replay.requests) == 4
    from polars.testing import assert_frame_equal

    assert_frame_equal(result.data, repeated.data)
    assert len(rr.cache_status("th_thaiwater").coverage) == 2

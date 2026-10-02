"""Public ThaiWater source windows and accumulated-cache behavior over exact recordings."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    LiveBoundaryProbe,
    WallClockExpectation,
    run_boundary_probes,
)
from rivretrieve._internal.coverage import RequestedInterval
from rivretrieve._internal.observations import ReceiptAuthorship
from rivretrieve._internal.primitives import CacheMode, ProductId, ProviderId
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.transport import TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


@pytest.fixture
def recordings(retained_evidence_root: Path):
    data = retained_evidence_root / "tests/test_data"
    return (
        read_recording(data / "th_thaiwater_1373273_2025-09-09_2026-09-08.recording.json"),
        read_recording(data / "th_thaiwater_1373273_2026-09-09_2026-09-12.recording.json"),
    )


_PROVIDER = ProviderId("th_thaiwater")
_PRODUCTS = (ProductId("stage_reported"), ProductId("discharge_reported"))
_START, _END = "2025-09-11", "2026-09-10"


class CountedReplay(ReplayTransport):
    def __init__(self, recordings) -> None:
        super().__init__(recordings)
        self.calls: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.calls.append(request)
        return super().send(request)


@pytest.mark.parametrize("cache", ["bypass", "reuse", "refresh"])
def test_public_365_date_request_splits_the_padded_source_window(
    recordings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cache: CacheMode
) -> None:
    replay = CountedReplay(recordings)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(provider="th_thaiwater", station="1373273", quantity="stage")
    result = rr.fetch(selection, start=_START, end=_END, cache=cache, receipts=True, on_issue="ignore")
    bounds = [(str(call.params["start_date"]), str(call.params["end_date"])) for call in replay.calls if call.params]
    assert bounds == [("2025-09-09", "2026-09-08"), ("2026-09-09", "2026-09-12")]
    assert all((date.fromisoformat(end) - date.fromisoformat(start)).days + 1 <= 365 for start, end in bounds)
    assert len(result.receipts.entries) == 2
    assert tuple(entry.content for entry in result.receipts.entries) == tuple(record.content for record in recordings)
    assert not any(issue.severity == "error" for issue in result.issues)


def test_each_product_has_an_independently_authored_public_multi_window_boundary_probe(
    recordings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Independent source-only author: thai-source-boundary/RUNTIME-V2-REPORT.md,
    # reviewed under Effort225. Full request/body identities are in the fixture manifest.
    # The author read neither provider code nor implementation outputs. Nulls are source rows.
    def run(product: ProductId, replay: ReplayTransport):
        monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
        selection = rr.find(
            provider="th_thaiwater",
            station="1373273",
            quantity={"stage_reported": "stage", "discharge_reported": "discharge"}[product],
        )
        return rr.fetch(selection, start=_START, end=_END, on_issue="ignore").data

    probes = tuple(
        LiveBoundaryProbe(
            provider_id=_PROVIDER,
            product_id=product,
            recordings=recordings,
            assertions={
                READING_COUNT: 52560,
                FIRST_WALL_CLOCK_TIME: WallClockExpectation("2025-09-11T00:00:00", "unknown"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation("2026-09-10T23:50:00", "unknown"),
            },
            run=lambda replay, product=product: run(product, replay),
        )
        for product in _PRODUCTS
    )
    run_boundary_probes(tuple((_PROVIDER, product) for product in _PRODUCTS), probes)


def test_public_multi_window_reuse_and_refresh_preserve_complete_requested_coverage(
    recordings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = CountedReplay(recordings)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    discovered = rr.find(provider="th_thaiwater", station="1373273")
    # Explicit source IDs freeze this test scope; incomplete all-series inventory cannot be reused.
    selection = rr.pick(discovered, series_id=[series.series_id for series in discovered.series])
    first = rr.fetch(selection, start=_START, end=_END, cache="reuse", receipts=True, on_issue="ignore")
    assert len(replay.calls) == 4  # Two genuine source requests for each product, not public coalescing.
    repeated = rr.fetch(selection, start=_START, end=_END, cache="reuse", receipts=True, on_issue="ignore")
    assert len(replay.calls) == 4
    assert_frame_equal(first.data, repeated.data)
    early = rr.fetch(selection, start=_START, end=_START, cache="reuse", on_issue="ignore")
    assert len(replay.calls) == 4
    assert not early.data.is_empty()
    import polars as pl

    assert_frame_equal(first.data.filter(pl.col("time").dt.date() == date(2025, 9, 11)), early.data)
    # Reuse retains original source-call provenance without making another request.
    assert repeated.provenance.calls_made == first.provenance.calls_made
    assert all(entry.authorship is ReceiptAuthorship.STORE_EXCERPT for entry in repeated.receipts.entries)
    status = rr.cache_status("th_thaiwater")
    assert len(status.coverage) == 4
    assert {item.series_id for item in status.coverage} == {series.series_id for series in selection.series}
    assert {item.interval for item in status.coverage} == {
        RequestedInterval(datetime(2025, 9, 11), datetime(2026, 9, 8, 23, 59, 59, 999999)),
        RequestedInterval(datetime(2026, 9, 9), datetime(2026, 9, 10, 23, 59, 59, 999999)),
    }
    refreshed = rr.fetch(selection, start=_START, end=_END, cache="refresh", receipts=True, on_issue="ignore")
    assert len(replay.calls) == 8
    assert_frame_equal(first.data, refreshed.data)
    assert all(entry.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD for entry in refreshed.receipts.entries)
    # A refresh replays actual source responses; the test does not claim a later source vintage.
    assert {item.retrieved_at for item in rr.cache_status("th_thaiwater").coverage} == {
        record.retrieved_at for record in recordings
    }


def test_declared_source_cap_splits_engine_padding_across_the_leap_date() -> None:
    """Arithmetic only: complete private leap-null capture certifies the first source span."""
    from rivretrieve._internal.driver import _padded_interval
    from rivretrieve._internal.providers.th_thaiwater.config import window_declarations
    from rivretrieve._internal.window_planning import plan_windows

    requested = RequestedInterval(datetime(2023, 3, 5), datetime(2024, 3, 3, 23, 59, 59, 999999))
    for declaration in window_declarations().products.values():
        windows = plan_windows(_padded_interval(requested), declaration)
        assert [(window.start, window.stop) for window in windows] == [
            ("2023-03-03", "2024-03-01"),
            ("2024-03-02", "2024-03-05"),
        ]
    # No response or measurements are invented for the second source window.


def test_retained_source_recordings_match_their_capture_manifest(retained_evidence_root: Path) -> None:
    import hashlib
    import json

    manifest = json.loads((Path(__file__).parent / "test_data/th_thaiwater_source_window_manifest.json").read_text())
    for capture in manifest["captures"]:
        path = retained_evidence_root / "tests/test_data" / capture["recording"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == capture["recording_sha256"]
        recording = read_recording(path)
        assert recording.sha256 == capture["response_sha256"]
        assert recording.retrieved_at == datetime.fromisoformat(capture["retrieved_at"])
    historical = next(capture for capture in manifest["captures"] if capture["name"] == "historical_null")
    raw = (retained_evidence_root / "tests/test_data" / historical["recording"]).read_bytes()
    assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == historical["original_git_blob"]

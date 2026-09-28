"""Independent ThaiWater source requests retain bounded successes and failures."""

from datetime import UTC, datetime

import pytest

from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.th_thaiwater.config import config, window_declarations
from rivretrieve._internal.providers.th_thaiwater.fetch import fetch
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse
from rivretrieve._internal.window_planning import plan_windows


@pytest.mark.parametrize("failed", [(0,), (1,), (2,), (0, 1, 2)])
def test_shared_chunks_keep_precise_bounds_and_call_identity(failed):
    products = (ProductId("stage_reported"), ProductId("discharge_reported"))
    product = products[0]
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 3)),
        WindowEndpoint.from_datetime(datetime(2026, 3, 15)),
    )
    windows = plan_windows(window, window_declarations().products[product])
    assert len(windows) == 3
    calls = []

    class Transport:
        def send(self, request):
            index = len(calls)
            calls.append(request)
            if index in failed:
                raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 2, status_code=503)
            return TransportResponse(
                content=b'{"items":[]}',
                status_code=200,
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                content_type="application/json",
                url=request.url,
                request_parameters=request.params,
            )

    result = fetch(("1373273",), products, dict.fromkeys(products, windows), window, config(), Transport())
    assert len(calls) == 3
    assert [payload.fetch_window for payload in result.value] == [
        item.bounds for index, item in enumerate(windows) if index not in failed
    ]
    assert len(result.failed_requests) == 2 * len(failed)
    assert len({failure.call_id for failure in result.failed_requests}) == len(failed)
    assert len({failure.event_id for failure in result.failed_requests}) == 2 * len(failed)
    for failure, index in zip(result.failed_requests, [i for i in failed for _ in products], strict=True):
        assert failure.series.product_id in products
        assert failure.window.start.isoformat() == windows[index].bounds.start.isoformat()
        assert failure.window.end.isoformat() == windows[index].bounds.end.isoformat()
        assert failure.failure.status_code == 503
        assert failure.request is calls[index]


@pytest.mark.parametrize("failed_index", [0, 1])
def test_public_failed_span_retains_sibling_rows(monkeypatch, failed_index):
    from pathlib import Path

    import rivretrieve as rr
    from rivretrieve._internal import discovery
    from rivretrieve._internal.recordings import ReplayTransport

    class Transport(ReplayTransport):
        def __init__(self):
            data = Path(__file__).parent / "test_data"
            super().__init__(
                [
                    data / "th_thaiwater_1373273_2025-09-09_2026-09-08.recording.json",
                    data / "th_thaiwater_1373273_2026-09-09_2026-09-12.recording.json",
                ]
            )
            self.calls = []

        def send(self, request):
            index = len(self.calls)
            self.calls.append(request)
            if index == failed_index:
                raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
            return super().send(request)

    transport = Transport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    chosen = rr.find(provider="th_thaiwater", station="1373273", quantity="stage")
    result = rr.fetch(chosen, start="2025-09-11", end="2026-09-10", cache="bypass", receipts=True, on_issue="ignore")
    assert len(transport.calls) == 2
    assert not result.data.is_empty()
    assert len(result.receipts.entries) == 1
    assert len(result.provenance.calls_made) == 2
    failures = [outcome for outcome in result.outcomes if outcome.status.value == "failed"]
    assert len(failures) == 1
    assert (
        failures[0].window.end < datetime(2026, 9, 9)
        if failed_index == 0
        else (failures[0].window.start == datetime(2026, 9, 9))
    )


def test_unbounded_rendering_is_a_fatal_contract_error():
    from rivretrieve._internal.engine import RenderedWindow
    from rivretrieve._internal.issues import FatalContractError

    product = ProductId("stage_reported")
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 31)),
    )

    class Transport:
        def send(self, request):
            pytest.fail("invalid bounds must fail before transport")

    with pytest.raises(FatalContractError):
        fetch(
            ("1373273",),
            (product,),
            {product: (RenderedWindow("2024-01-01", "2024-01-31"),)},
            window,
            config(),
            Transport(),
        )

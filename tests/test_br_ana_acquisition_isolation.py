"""Independent ANA source requests retain bounded successes and failures."""

from datetime import UTC, datetime

import pytest

from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.br_ana.config import config, window_declarations
from rivretrieve._internal.providers.br_ana.fetch import fetch
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse
from rivretrieve._internal.window_planning import plan_windows


@pytest.mark.parametrize("product", ["discharge_daily_mean_bruto", "stage_instantaneous"])
@pytest.mark.parametrize("failed", [(0,), (1,), (2,), (0, 1, 2)])
def test_independent_chunks_keep_precise_bounds(product, failed):
    product = ProductId(product)
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 3)),
        WindowEndpoint.from_datetime(datetime(2024, 3, 15)),
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

    result = fetch(("15400000",), (product,), {product: windows}, window, config(), Transport())
    assert len(calls) == 3
    assert [payload.fetch_window for payload in result.value] == [
        item.bounds for index, item in enumerate(windows) if index not in failed
    ]
    assert len(result.failed_requests) == len(failed)
    for failure, index in zip(result.failed_requests, failed, strict=True):
        assert failure.series.product_id == product
        assert failure.window.start.isoformat() == windows[index].bounds.start.isoformat()
        assert failure.window.end.isoformat() == windows[index].bounds.end.isoformat()
        assert failure.failure.status_code == 503
        assert failure.request is calls[index]


@pytest.mark.parametrize("failed_month", ["2024-01", "2024-02"])
def test_daily_driver_retains_healthy_month_and_failed_call(failed_month):
    from pathlib import Path

    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.engine import ObservationRequest, RequestedWindow
    from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.providers.br_ana.parse import parse as parse_response
    from rivretrieve._internal.recordings import ReplayTransport

    class Stages:
        config = config()
        window_declarations = window_declarations()
        fetch = staticmethod(fetch)
        parse = staticmethod(parse_response)

    class Transport(ReplayTransport):
        def __init__(self):
            super().__init__(
                list(
                    (Path(__file__).parent / "recordings/br_ana").glob(
                        "HidroSerieVazao_15400000_2024-0[12]-01_*.recording.json"
                    )
                )
            )
            self.calls = []

        def send(self, request):
            self.calls.append(request)
            if str(request.params["Data Inicial (yyyy-MM-dd)"]).startswith(failed_month):
                raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
            return super().send(request)

    transport = Transport()
    provider = ProviderId("br_ana")
    result = drive(
        ObservationRequest(
            provider,
            ("15400000",),
            (ProductId("discharge_daily_mean_bruto"),),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2024, 1, 10)), WindowEndpoint.from_datetime(datetime(2024, 2, 20))
            ),
        ),
        Stages(),
        provenance=ObservationProvenance(source="test", provider_id=provider),
        transport=transport,
        receipts=ReceiptMode.INCLUDE,
    )
    assert len(transport.calls) == 2
    healthy = {"2024-01", "2024-02"} - {failed_month}
    assert set(result.canonical_rows["time"].dt.strftime("%Y-%m")) == healthy
    assert len(result.receipts.entries) == 1
    failures = [outcome for outcome in result.outcomes if outcome.status.value == "failed"]
    assert len(failures) == 1
    assert failures[0].window.start.strftime("%Y-%m") == failed_month
    assert len(result.provenance.calls_made) == 2


def test_unbounded_rendering_is_a_fatal_contract_error():
    from rivretrieve._internal.engine import RenderedWindow
    from rivretrieve._internal.issues import FatalContractError

    product = ProductId("stage_instantaneous")
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 31)),
    )

    class Transport:
        def send(self, request):
            pytest.fail("invalid bounds must fail before transport")

    with pytest.raises(FatalContractError):
        fetch(
            ("15400000",),
            (product,),
            {product: (RenderedWindow("2024-01-01", "2024-01-31"),)},
            window,
            config(),
            Transport(),
        )


@pytest.mark.parametrize("malformed", [False, True])
def test_equal_ana_responses_keep_acquisition_identity_and_call_linkage(malformed):
    from dataclasses import replace

    from rivretrieve._internal.providers.br_ana.parse import parse
    from rivretrieve._internal.recordings import ReplayTransport
    from tests.test_br_ana_daily import _recording

    product = ProductId("discharge_daily_mean_bruto")
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 3)), WindowEndpoint.from_datetime(datetime(2024, 1, 4))
    )
    windows = plan_windows(window, window_declarations().products[product])
    original = fetch(
        ("15400000",),
        (product,),
        {product: windows},
        window,
        config(),
        ReplayTransport([_recording(product, "2024-01")]),
    ).value[0]
    first = replace(original, content=b"{}") if malformed else original
    second = replace(first, acquisition_id="another-ana-call")
    parsed_first, parsed_second = parse(first, config()), parse(second, config())
    assert {item.outcome_id for item in parsed_first.outcomes}.isdisjoint(
        {item.outcome_id for item in parsed_second.outcomes}
    )
    assert all(item.calls == (first.acquisition_id,) for item in parsed_first.outcomes)
    assert all(item.calls == (second.acquisition_id,) for item in parsed_second.outcomes)
    assert {item.snapshot_id for item in parsed_first.inventories}.isdisjoint(
        {item.snapshot_id for item in parsed_second.inventories}
    )

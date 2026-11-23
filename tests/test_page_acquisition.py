"""Source-independent contract tests for engine-owned cursor pagination."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from rivretrieve._internal.engine import (
    Payload,
    RowsSchema,
    SourceCallOrigin,
    SourceCoordinates,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.page_acquisition import PageStep, acquire_pages
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.source_acquisition import SourceRequestTarget
from rivretrieve._internal.source_series import ParsedSeries, SeriesWindow
from rivretrieve._internal.transport import (
    HttpMethod,
    TransportAttempt,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)


def _window() -> SeriesWindow:
    return SeriesWindow(start=datetime(2025, 1, 1), end=datetime(2025, 1, 2))


def _fetch_window():
    return _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2025, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2025, 1, 2)),
    )


def _empty_parsed() -> ParsedSeries:
    return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), ())


def _build_payload(response: TransportResponse, *, acq_id: str | None = None) -> Payload:
    return Payload(
        source_coordinates=SourceCoordinates({"route": "test"}),
        station_products=(("s1", ProductId("p1")),),
        fetch_window=_fetch_window(),
        content=response.content,
        origin=SourceCallOrigin.from_response(response),
        prerequisite_calls=response.prerequisite_calls,
        attempt_traces=response.attempt_traces,
        **({"acquisition_id": acq_id} if acq_id is not None else {}),
    )


class _ScriptedTransport:
    def __init__(self, responses: list[object]) -> None:
        self._items = iter(responses)
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        item = next(self._items)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, TransportResponse)
        return item


def _response(
    request: TransportRequest, body: bytes, *, attempts: tuple[TransportAttempt, ...] = ()
) -> TransportResponse:
    return TransportResponse(
        content=body,
        status_code=200,
        retrieved_at=datetime(2026, 1, 1, 12, tzinfo=UTC),
        content_type="application/json",
        url=request.url,
        request_parameters=request.params or {},
        attempts=len(attempts) or 1,
        attempt_traces=attempts,
    )


def test_acquire_pages_collects_multi_page_payloads_interpretations_and_calls() -> None:
    req1 = TransportRequest(HttpMethod.GET, "https://example.invalid/page1", {"limit": "10"})
    req2 = TransportRequest(HttpMethod.GET, "https://example.invalid/page2", {"cursor": "c2"})
    t = _ScriptedTransport(
        [
            _response(req1, b"p1"),
            _response(req2, b"p2"),
        ]
    )
    interpreted_pages: list[bytes] = []

    def interpret(payload: Payload) -> PageStep:
        interpreted_pages.append(payload.content)
        if payload.content == b"p1":
            return PageStep(parsed=_empty_parsed(), next_request=req2, cursor_key=("c2",))
        return PageStep(parsed=_empty_parsed(), next_request=None)

    acq = acquire_pages(
        req1,
        transport=t,
        window=_window(),
        build_payload=_build_payload,
        interpret_page=interpret,
        failure_targets=lambda: (SourceRequestTarget("s1", "p1"),),
    )

    assert acq.completed is True
    assert acq.stop_reason is None
    assert [p.content for p in acq.payloads] == [b"p1", b"p2"]
    assert interpreted_pages == [b"p1", b"p2"]
    assert len(acq.interpretations) == 2
    assert [i.context.acquisition_id for i in acq.interpretations] == [p.acquisition_id for p in acq.payloads]
    assert acq.calls == tuple(p.acquisition_id for p in acq.payloads)
    assert acq.failed_requests == ()
    assert acq.issues == ()


def test_acquire_pages_retains_late_failure_attempts_and_prerequisite_links() -> None:
    req1 = TransportRequest(HttpMethod.GET, "https://example.invalid/page1")
    req2 = TransportRequest(HttpMethod.GET, "https://example.invalid/page2")
    p1_attempt = TransportAttempt(
        "p1-try-1",
        req1.url,
        {},
        datetime(2026, 1, 1, 12, tzinfo=UTC),
        status_code=200,
        content_type="application/json",
    )
    p2_attempts = (
        TransportAttempt(
            "p2-try-1",
            req2.url,
            {},
            datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
            status_code=503,
            failure_category=TransportFailureCategory.HTTP_STATUS,
        ),
        TransportAttempt(
            "p2-try-2",
            req2.url,
            {},
            datetime(2026, 1, 1, 12, 2, tzinfo=UTC),
            status_code=503,
            failure_category=TransportFailureCategory.HTTP_STATUS,
        ),
    )
    failure = TransportFailure(
        req2,
        TransportFailureReason.HTTP_STATUS,
        2,
        status_code=503,
        category=TransportFailureCategory.HTTP_STATUS,
        attempt_traces=p2_attempts,
    )
    t = _ScriptedTransport([_response(req1, b"p1", attempts=(p1_attempt,)), failure])

    acq = acquire_pages(
        req1,
        transport=t,
        window=_window(),
        build_payload=_build_payload,
        interpret_page=lambda payload: PageStep(parsed=_empty_parsed(), next_request=req2, cursor_key="page2"),
        failure_targets=lambda: (SourceRequestTarget("s1", "p1"),),
        prerequisite_acquisition_ids=("lookup-1",),
    )

    assert acq.completed is False
    assert acq.stop_reason == str(failure)
    assert len(acq.payloads) == 1
    assert acq.payloads[0].prerequisite_acquisition_ids == ("lookup-1",)
    assert len(acq.failed_requests) == 1
    assert acq.failed_requests[0].prerequisite_acquisition_ids == ("lookup-1",)
    assert acq.failed_requests[0].failure is failure
    assert acq.calls == ("p1-try-1", "p2-try-1", "p2-try-2")


def test_acquire_pages_detects_cursor_cycle_after_page_interpretation() -> None:
    req1 = TransportRequest(HttpMethod.GET, "https://example.invalid/page1")
    req2 = TransportRequest(HttpMethod.GET, "https://example.invalid/page2")
    t = _ScriptedTransport([_response(req1, b"p1"), _response(req2, b"p2"), _response(req2, b"p3")])
    cycle_issue = Issue(
        severity="error",
        code="source.acquisition_incomplete",
        message="cycle detected",
        provider_id=ProviderId("test"),
    )

    acq = acquire_pages(
        req1,
        transport=t,
        window=_window(),
        build_payload=_build_payload,
        interpret_page=lambda payload: PageStep(parsed=_empty_parsed(), next_request=req2, cursor_key="same-cursor"),
        failure_targets=lambda: (SourceRequestTarget("s1", "p1"),),
        on_cycle=lambda: ("cycle detected", (cycle_issue,)),
    )

    assert len(t.requests) == 2
    assert acq.completed is False
    assert acq.stop_reason == "cycle detected"
    assert acq.issues == (cycle_issue,)
    assert len(acq.payloads) == 2
    assert len(acq.interpretations) == 2


def test_acquire_pages_preserves_provider_stop_reason_and_rejects_invalid_steps() -> None:
    req1 = TransportRequest(HttpMethod.GET, "https://example.invalid/page1")
    t = _ScriptedTransport([_response(req1, b"bad")])
    step_issue = Issue(
        severity="error",
        code="source.acquisition_incomplete",
        message="bad link",
        provider_id=ProviderId("test"),
    )

    acq = acquire_pages(
        req1,
        transport=t,
        window=_window(),
        build_payload=_build_payload,
        interpret_page=lambda payload: PageStep(parsed=_empty_parsed(), stop_reason="bad link", issues=(step_issue,)),
        failure_targets=lambda: (SourceRequestTarget("s1", "p1"),),
    )

    assert acq.completed is False
    assert acq.stop_reason == "bad link"
    assert acq.issues == (step_issue,)
    assert len(acq.interpretations) == 1

    with pytest.raises(FatalContractError, match="ParsedSeries"):
        PageStep(parsed="not-parsed")  # type: ignore[arg-type]

    with pytest.raises(FatalContractError, match="next request after stopping"):
        PageStep(parsed=_empty_parsed(), next_request=req1, stop_reason="stopped")

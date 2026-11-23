"""Engine-owned cursor pagination over bounded provider page interpretations."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import uuid4

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import InterpretedPayload, Payload
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.source_acquisition import (
    FailedSourceRequest,
    SourceRequestTarget,
    SourceResponseMeaning,
    attempt_request,
    http_response_meaning,
)
from rivretrieve._internal.source_series import ParsedSeries, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import Transport, TransportFailure, TransportRequest, TransportResponse


@dataclass(frozen=True, slots=True)
class PageStep:
    """One decoded observation page's parsed series and pagination continuation."""

    parsed: ParsedSeries
    next_request: TransportRequest | None = None
    cursor_key: Hashable | None = None
    stop_reason: str | None = None
    issues: tuple[Issue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.parsed, ParsedSeries):
            raise FatalContractError("Page step requires a ParsedSeries")
        if self.stop_reason is not None and self.next_request is not None:
            raise FatalContractError("Page step cannot supply a next request after stopping")


@dataclass(frozen=True, slots=True)
class PageAcquisition:
    """Payloads, context-bound interpretations, calls, and failures from a cursor chain."""

    payloads: tuple[Payload, ...]
    interpretations: tuple[InterpretedPayload, ...]
    failed_requests: tuple[FailedSourceRequest, ...]
    calls: tuple[str, ...]
    issues: tuple[Issue, ...]
    retrieved_at: datetime | None
    stop_reason: str | None = None

    @property
    def completed(self) -> bool:
        """Return whether the cursor chain finished without transport or pagination failure."""
        return self.stop_reason is None and not self.failed_requests


def acquire_pages(
    initial_request: TransportRequest,
    *,
    transport: Transport,
    window: SeriesWindow,
    build_payload: Callable[[TransportResponse], Payload],
    interpret_page: Callable[[Payload], PageStep],
    failure_targets: Callable[[], Sequence[SourceSeries | SourceRequestTarget]],
    on_cycle: Callable[[], tuple[str, tuple[Issue, ...]]] | None = None,
    prerequisite_acquisition_ids: tuple[str, ...] = (),
    response_meanings: Mapping[int, SourceResponseMeaning] | None = None,
) -> PageAcquisition:
    """Drive a paginated source request loop while keeping provider rules separate."""
    request: TransportRequest | None = initial_request
    visited: set[Hashable] = set()
    payloads: list[Payload] = []
    interpretations: list[InterpretedPayload] = []
    failed_requests: list[FailedSourceRequest] = []
    calls: list[str] = []
    issues: list[Issue] = []
    retrieved_at: datetime | None = None
    stop_reason: str | None = None

    while request is not None:
        attempted = attempt_request(transport, request)
        if isinstance(attempted, (TransportFailure, CredentialExchangeError)):
            targets = tuple(failure_targets())
            if not targets:
                raise FatalContractError("Page acquisition failure requires at least one failure target")
            call_id = uuid4().hex
            meaning = (
                http_response_meaning(attempted, response_meanings)
                if response_meanings is not None
                else SourceResponseMeaning.UNSPECIFIED
            )
            if isinstance(attempted, TransportFailure) and attempted.attempt_traces:
                calls.extend(item.attempt_id for item in attempted.attempt_traces)
            else:
                calls.append(call_id)
            for target in targets:
                failed_requests.append(
                    FailedSourceRequest(
                        uuid4().hex,
                        target,
                        window,
                        request,
                        attempted,
                        meaning=meaning,
                        call_id=call_id,
                        prerequisite_acquisition_ids=prerequisite_acquisition_ids,
                    )
                )
            stop_reason = str(attempted)
            break

        retrieved_at = attempted.retrieved_at
        payload = build_payload(attempted)
        if prerequisite_acquisition_ids:
            combined_prereqs = tuple(
                dict.fromkeys((*prerequisite_acquisition_ids, *payload.prerequisite_acquisition_ids))
            )
            if combined_prereqs != payload.prerequisite_acquisition_ids:
                payload = replace(payload, prerequisite_acquisition_ids=combined_prereqs)
        payloads.append(payload)
        if payload.attempt_traces:
            calls.extend(item.attempt_id for item in payload.attempt_traces)
        else:
            calls.append(payload.acquisition_id)

        step = interpret_page(payload)
        if not isinstance(step, PageStep):
            raise FatalContractError("Page acquisition interpret_page must return PageStep")
        interpretations.append(InterpretedPayload.from_payload(payload, step.parsed))
        issues.extend(step.issues)

        if step.stop_reason is not None:
            stop_reason = step.stop_reason
            break
        if step.next_request is None:
            break
        if step.cursor_key is not None:
            if step.cursor_key in visited:
                if on_cycle is not None:
                    cycle_reason, cycle_issues = on_cycle()
                    stop_reason = cycle_reason
                    issues.extend(cycle_issues)
                else:
                    stop_reason = "Source pagination cursor cycle"
                break
            visited.add(step.cursor_key)
        request = step.next_request

    return PageAcquisition(
        payloads=tuple(payloads),
        interpretations=tuple(interpretations),
        failed_requests=tuple(failed_requests),
        calls=tuple(calls),
        issues=tuple(issues),
        retrieved_at=retrieved_at,
        stop_reason=stop_reason,
    )

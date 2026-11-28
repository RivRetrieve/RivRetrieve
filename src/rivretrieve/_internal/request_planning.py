"""Whole-selection source request planning, lookup deduplication, and batch execution."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol, cast, runtime_checkable
from uuid import uuid4

import polars as pl

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.coverage import RequestedInterval
from rivretrieve._internal.engine import (
    FetchWindow,
    InterpretedPayload,
    Payload,
    ProviderConfig,
    RenderedWindow,
    RowsSchema,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
    _clamp_fetch_window,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.page_acquisition import PageAcquisition, PageStep, acquire_pages
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.source_acquisition import (
    FailedSourceRequest,
    SourceRequestTarget,
    SourceResponseMeaning,
    attempt_request,
    http_response_meaning,
)
from rivretrieve._internal.source_annotations import AnnotationBundle
from rivretrieve._internal.source_series import (
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    TimeAxis,
    stable_id,
)
from rivretrieve._internal.transport import (
    Transport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)


@dataclass(frozen=True, slots=True)
class ConsumerNeed:
    """Uncached consumer request unit passed to a provider request planner."""

    station: str
    product: ProductId
    scope: SeriesScope
    known_series: tuple[SourceSeries, ...]
    interval: RequestedInterval
    window: SeriesWindow
    fetch_window: FetchWindow
    rendered: tuple[RenderedWindow, ...]


@dataclass(frozen=True, slots=True)
class SourceRequestIdentity:
    """Canonical key identifying one deduplicable publisher HTTP request."""

    method: str
    url: str
    params: tuple[tuple[str, str | None], ...]
    body_digest: str
    window_start: str | None
    window_end: str | None
    axis: TimeAxis
    access_context: str = "default"


def request_identity(
    request: TransportRequest,
    *,
    window: FetchWindow | None = None,
    axis: TimeAxis = TimeAxis.NATIVE,
    access_context: str = "default",
) -> SourceRequestIdentity:
    """Compute a canonical request identity for deduplicating identical calls.

    Parameters
    ----------
    request : TransportRequest
        Outbound HTTP request specification.
    window : FetchWindow | None, optional
        Engine-established source fetch window when request bounds distinguish
        distinct acquisitions.
    axis : TimeAxis, optional
        Time axis associated with the request bounds.
    access_context : str, optional
        Credential or route context distinguishing separate access tiers.
    """
    params = tuple(sorted((str(k), None if v is None else str(v)) for k, v in (request.params or {}).items()))
    raw_body = (
        request.body.encode("utf-8")
        if isinstance(request.body, str)
        else (request.body if request.body is not None else b"")
    )
    return SourceRequestIdentity(
        method=str(request.method.value),
        url=request.url,
        params=params,
        body_digest=hashlib.sha256(raw_body).hexdigest(),
        window_start=window.start.isoformat() if window is not None else None,
        window_end=window.end.isoformat() if window is not None else None,
        axis=axis,
        access_context=access_context,
    )


@dataclass(frozen=True, slots=True)
class LookupFailureOutcome:
    """Custom evidence emitted when a planned lookup request fails."""

    series: tuple[SourceSeries, ...] = ()
    inventories: tuple[InventorySnapshot, ...] = ()
    outcomes: tuple[RetrievalOutcome, ...] = ()
    issues: tuple[Issue, ...] = ()
    failed_requests: tuple[FailedSourceRequest, ...] = ()
    calls: tuple[SourceCallOrigin, ...] = ()


@dataclass(frozen=True, slots=True)
class LookupFailureResult:
    """Lookup resolution entry indicating the deduplicated lookup failed."""

    call_id: str
    failure: TransportFailure | CredentialExchangeError


@dataclass(frozen=True, slots=True)
class ResolvedLookup:
    """Resolved prerequisite lookup shared across matching consumers."""

    value: object
    acquisition_id: str = ""
    payload: Payload | None = None
    parsed: ParsedSeries | None = None
    series: tuple[SourceSeries, ...] = ()
    inventories: tuple[InventorySnapshot, ...] = ()
    outcomes: tuple[RetrievalOutcome, ...] = ()
    issues: tuple[Issue, ...] = ()
    calls: tuple[SourceCallOrigin, ...] = ()
    failed_requests: tuple[FailedSourceRequest, ...] = ()


LookupResolution = ResolvedLookup | LookupFailureResult


@dataclass(frozen=True, slots=True)
class PlannedLookup:
    """Deduplicable prerequisite metadata or discovery HTTP request."""

    key: Hashable
    consumers: tuple[ConsumerNeed, ...]
    request: TransportRequest
    source_coordinates: SourceCoordinates
    fetch_window: FetchWindow
    axis: TimeAxis = TimeAxis.NATIVE
    access_context: str = "default"
    window_in_identity: bool = False
    prerequisite_acquisition_ids: tuple[str, ...] = ()
    emit_payload: bool = False
    record_auxiliary_call: bool = True
    response_meanings: Mapping[int, SourceResponseMeaning] | None = None
    on_response: Callable[[TransportResponse, tuple[ConsumerNeed, ...], str, ProviderConfig], ResolvedLookup] | None = (
        None
    )
    interpret_payload: Callable[[Payload, ProviderConfig], ParsedSeries] | None = None
    interpret_group: (
        Callable[
            [Payload, Mapping[tuple[str, ProductId], Payload], ProviderConfig],
            Mapping[tuple[str, ProductId], ParsedSeries],
        ]
        | None
    ) = None
    resolve_payload: (
        Callable[
            [Payload, Mapping[tuple[str, ProductId], Payload], ProviderConfig],
            tuple[object, Mapping[tuple[str, ProductId], ParsedSeries]],
        ]
        | None
    ) = None
    on_failure: (
        Callable[
            [TransportFailure | CredentialExchangeError, TransportRequest, tuple[ConsumerNeed, ...], str, str],
            LookupFailureOutcome | Iterable[FailedSourceRequest],
        ]
        | None
    ) = None

    @property
    def identity(self) -> SourceRequestIdentity:
        return request_identity(
            self.request,
            window=self.fetch_window if self.window_in_identity else None,
            axis=self.axis,
            access_context=self.access_context,
        )


@dataclass(frozen=True, slots=True)
class BatchPageStep:
    """Single decoded page inside a batched pagination chain."""

    interpretations: Mapping[tuple[str, ProductId], ParsedSeries] = field(default_factory=dict)
    next_request: TransportRequest | None = None
    cursor_key: Hashable | None = None
    stop_reason: str | None = None
    issues: tuple[Issue, ...] = ()
    extra_series: tuple[SourceSeries, ...] = ()


@dataclass(frozen=True, slots=True)
class UnseenConsumerEvidence:
    """Complete-chain evidence emitted for a consumer unseen on any page."""

    series: tuple[SourceSeries, ...] = ()
    inventories: tuple[InventorySnapshot, ...] = ()
    outcomes: tuple[RetrievalOutcome, ...] = ()


@dataclass(frozen=True, slots=True)
class BatchPaginationSpec:
    """Pagination hooks for single or multi-station cursor/page chains."""

    step_page: Callable[[Payload, tuple[ConsumerNeed, ...], ProviderConfig], BatchPageStep]
    finalize_unseen_consumer: (
        Callable[
            [ConsumerNeed, tuple[Payload, ...], ProviderConfig],
            RetrievalOutcome | UnseenConsumerEvidence | None,
        ]
        | None
    ) = None
    build_unresolved_outcome: Callable[[ConsumerNeed, PageAcquisition, ProviderConfig], RetrievalOutcome] | None = None
    on_cycle: Callable[[tuple[ConsumerNeed, ...]], tuple[str, tuple[Issue, ...]]] | None = None


@dataclass(frozen=True, slots=True)
class PlannedObservationRequest:
    """Deduplicable or batched source observation request."""

    consumers: tuple[ConsumerNeed, ...]
    request: TransportRequest
    source_coordinates: SourceCoordinates
    fetch_window: FetchWindow
    acquisition_axis: TimeAxis = TimeAxis.NATIVE
    access_context: str = "default"
    prerequisite_acquisition_ids: tuple[str, ...] = ()
    failure_targets: tuple[SourceSeries | SourceRequestTarget, ...] = ()
    response_meanings: Mapping[int, SourceResponseMeaning] | None = None
    interpret_payload: Callable[[Payload, ProviderConfig], ParsedSeries] | None = None
    interpret_group: (
        Callable[
            [Payload, Mapping[tuple[str, ProductId], Payload], ProviderConfig],
            Mapping[tuple[str, ProductId], ParsedSeries],
        ]
        | None
    ) = None
    pagination: BatchPaginationSpec | None = None
    pre_failure_outcomes: (
        Callable[
            [tuple[ConsumerNeed, ...], TransportFailure | CredentialExchangeError, TransportRequest, str],
            tuple[RetrievalOutcome, ...],
        ]
        | None
    ) = None

    @property
    def identity(self) -> SourceRequestIdentity:
        return request_identity(
            self.request,
            window=self.fetch_window,
            axis=self.acquisition_axis,
            access_context=self.access_context,
        )


@dataclass(frozen=True, slots=True)
class ObservationPlan:
    """Observation requests plus metadata-settled outcomes, issues, and calls."""

    requests: tuple[PlannedObservationRequest, ...] = ()
    series: tuple[SourceSeries, ...] = ()
    inventories: tuple[InventorySnapshot, ...] = ()
    outcomes: tuple[RetrievalOutcome, ...] = ()
    issues: tuple[Issue, ...] = ()
    calls: tuple[SourceCallOrigin, ...] = ()
    failed_requests: tuple[FailedSourceRequest, ...] = ()
    finalize: Callable[[SourceAcquisition], SourceAcquisition] | None = None


@dataclass(frozen=True, slots=True)
class BatchSelector:
    """Deterministic selector packing respecting count and URL length limits."""

    max_items: int
    max_url_length: int | None = None

    def __post_init__(self) -> None:
        if self.max_items < 1:
            raise ValueError("BatchSelector max_items must be positive")
        if self.max_url_length is not None and self.max_url_length < 1:
            raise ValueError("BatchSelector max_url_length must be positive")

    def pack_batches[T](
        self,
        items: Sequence[T],
        *,
        estimate_url_length: Callable[[tuple[T, ...]], int] | None = None,
    ) -> tuple[tuple[T, ...], ...]:
        """Group ``items`` into bounded deterministic batches in input order."""
        batches: list[tuple[T, ...]] = []
        current: list[T] = []
        for item in items:
            candidate = (*current, item)
            over_items = len(candidate) > self.max_items
            over_url = (
                self.max_url_length is not None
                and estimate_url_length is not None
                and len(current) > 0
                and estimate_url_length(candidate) > self.max_url_length
            )
            if current and (over_items or over_url):
                batches.append(tuple(current))
                current = [item]
            else:
                current.append(item)
        if current:
            batches.append(tuple(current))
        return tuple(batches)


@runtime_checkable
class SourceRequestPlanner(Protocol):
    """Provider planner declaring lookup and observation requests for a selection."""

    def plan_lookups(
        self,
        needs: tuple[ConsumerNeed, ...],
        config: ProviderConfig,
    ) -> tuple[PlannedLookup, ...]: ...

    def plan_observations(
        self,
        needs: tuple[ConsumerNeed, ...],
        lookups: Mapping[tuple[Hashable, str, ProductId], LookupResolution],
        config: ProviderConfig,
    ) -> ObservationPlan: ...


def _merge_consumers(needs: Sequence[ConsumerNeed]) -> tuple[ConsumerNeed, ...]:
    merged: dict[tuple[str, ProductId], ConsumerNeed] = {}
    for need in needs:
        merged.setdefault((need.station, need.product), need)
    return tuple(merged.values())


def _merge_fetch_windows(windows: Sequence[FetchWindow]) -> FetchWindow:
    start = min(window.start for window in windows)
    end = max(window.end for window in windows)
    return _make_fetch_window(start, end)


def _merge_group_scope(consumers: Sequence[ConsumerNeed]) -> SeriesScope | None:
    if not consumers:
        return None
    if len(consumers) == 1:
        return consumers[0].scope
    first = consumers[0].scope
    return first.model_copy(
        update={
            "station_ids": tuple(dict.fromkeys(need.station for need in consumers)),
            "product_ids": tuple(dict.fromkeys(str(need.product) for need in consumers)),
            "series_ids": tuple(dict.fromkeys(key for need in consumers for key in need.scope.series_ids)),
        }
    )


def _merge_known_series(consumers: Sequence[ConsumerNeed]) -> tuple[SourceSeries, ...]:
    merged: dict[str, SourceSeries] = {}
    for need in consumers:
        for item in need.known_series:
            merged.setdefault(item.series_id, item)
    return tuple(merged.values())


def _append_call_station_products(
    target: list[tuple[str, tuple[tuple[str, ProductId], ...]]],
    origins: Sequence[SourceCallOrigin],
    station_products: tuple[tuple[str, ProductId], ...],
) -> None:
    for origin in origins:
        if origin.acquisition_id:
            target.append((origin.acquisition_id, station_products))


def _narrow_consumer_payload(received: Payload, need: ConsumerNeed, *, shared: bool) -> Payload:
    if shared:
        pair_known = tuple(
            item
            for item in received.known_series
            if item.station_id == need.station and item.product_id == need.product
        )
        return replace(
            received,
            station_products=((need.station, need.product),),
            fetch_window=_clamp_fetch_window(received.fetch_window, need.fetch_window),
            scope=need.scope,
            known_series=pair_known or need.known_series,
        )
    return replace(
        received,
        scope=received.scope or need.scope,
        known_series=received.known_series or need.known_series,
    )


def _failure_targets_for_consumers(
    consumers: Sequence[ConsumerNeed],
    explicit_targets: Sequence[SourceSeries | SourceRequestTarget] = (),
) -> tuple[SourceSeries | SourceRequestTarget, ...]:
    if explicit_targets:
        seen: dict[tuple[str | None, str, str], SourceSeries | SourceRequestTarget] = {}
        for target in explicit_targets:
            seen.setdefault((target.series_id, target.station_id, target.product_id), target)
        return tuple(seen.values())
    targets: list[SourceSeries | SourceRequestTarget] = []
    for need in consumers:
        matched = tuple(item for item in need.known_series if need.scope.matches(item))
        if matched:
            targets.extend(matched)
        else:
            targets.append(SourceRequestTarget(need.station, str(need.product)))
    return tuple(targets)


def _validate_grouped_parsed(
    grouped: object,
    expected_keys: AbstractSet[tuple[str, ProductId]],
    label: str,
) -> Mapping[tuple[str, ProductId], ParsedSeries]:
    if not isinstance(grouped, Mapping):
        raise FatalContractError(f"{label} must return a mapping")
    if set(grouped.keys()) != set(expected_keys):
        raise FatalContractError(f"{label} keys must match requested pair payloads")
    for pair_parsed in grouped.values():
        if not isinstance(pair_parsed, ParsedSeries):
            raise FatalContractError(f"{label} values must be ParsedSeries")
    return cast("Mapping[tuple[str, ProductId], ParsedSeries]", grouped)


def _execute_paginated_group(
    head: PlannedObservationRequest,
    consumers: tuple[ConsumerNeed, ...],
    station_products: tuple[tuple[str, ProductId], ...],
    prereqs: tuple[str, ...],
    targets: tuple[SourceSeries | SourceRequestTarget, ...],
    shared_scope: SeriesScope | None,
    shared_known: tuple[SourceSeries, ...],
    bounds: SeriesWindow,
    config: ProviderConfig,
    transport: Transport,
    *,
    payloads: list[Payload],
    interpretations: list[InterpretedPayload],
    definitions: list[SourceSeries],
    inventories: list[InventorySnapshot],
    outcomes: list[RetrievalOutcome],
    failed_requests: list[FailedSourceRequest],
    issues: list[Issue],
) -> None:
    spec = head.pagination
    assert spec is not None
    page_interpretations: list[InterpretedPayload] = []
    seen_pairs: set[tuple[str, ProductId]] = set()
    series_by_pair: dict[tuple[str, ProductId], SourceSeries] = {}

    def _build_page_payload(response: TransportResponse) -> Payload:
        return Payload(
            source_coordinates=head.source_coordinates,
            station_products=station_products,
            fetch_window=head.fetch_window,
            content=response.content,
            origin=SourceCallOrigin.from_response(response),
            prerequisite_calls=response.prerequisite_calls,
            scope=shared_scope,
            known_series=shared_known,
            attempt_traces=response.attempt_traces,
            acquisition_axis=head.acquisition_axis,
            prerequisite_acquisition_ids=prereqs,
        )

    def _step(payload: Payload) -> PageStep:
        step = spec.step_page(payload, consumers, config)
        if not isinstance(step.interpretations, Mapping):
            raise FatalContractError("Batch page step interpretations must be a mapping")
        is_shared = len(payload.station_products) > 1
        definitions.extend(step.extra_series)
        for s_def in step.extra_series:
            series_by_pair[(s_def.station_id, ProductId(s_def.product_id))] = s_def
        for pair_key, pair_parsed in step.interpretations.items():
            if not isinstance(pair_parsed, ParsedSeries):
                raise FatalContractError("Batch page step interpretations must contain ParsedSeries values")
            definitions.extend(pair_parsed.series)
            for s_def in pair_parsed.series:
                series_by_pair[(s_def.station_id, ProductId(s_def.product_id))] = s_def
            need = next((item for item in consumers if (item.station, item.product) == pair_key), None)
            if need is None:
                raise FatalContractError("Batch page step returned interpretation for an unrequested pair")
            narrowed = _narrow_consumer_payload(payload, need, shared=is_shared)
            page_interpretations.append(InterpretedPayload.from_payload(narrowed, pair_parsed))
            has_settled_evidence = (not pair_parsed.rows.is_empty()) or any(
                outcome.status
                in (
                    OutcomeStatus.SUCCESS,
                    OutcomeStatus.EMPTY,
                    OutcomeStatus.FAILED,
                    OutcomeStatus.UNSUPPORTED,
                    OutcomeStatus.UNRESOLVED,
                )
                for outcome in pair_parsed.outcomes
            )
            if has_settled_evidence:
                seen_pairs.add(pair_key)
        if step.interpretations:
            for need in consumers:
                pair_key = (need.station, need.product)
                if pair_key in step.interpretations:
                    continue
                narrowed = _narrow_consumer_payload(payload, need, shared=is_shared)
                page_interpretations.append(
                    InterpretedPayload.from_payload(
                        narrowed,
                        ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), ()),
                    )
                )
        return PageStep(
            parsed=None,
            next_request=step.next_request,
            cursor_key=step.cursor_key,
            stop_reason=step.stop_reason,
            issues=step.issues,
        )

    on_cycle_cb = spec.on_cycle
    page_acq = acquire_pages(
        head.request,
        transport=transport,
        window=bounds,
        build_payload=_build_page_payload,
        interpret_page=_step,
        failure_targets=lambda: targets,
        on_cycle=(lambda cb=on_cycle_cb, batch=consumers: cb(batch)) if on_cycle_cb is not None else None,
        prerequisite_acquisition_ids=prereqs,
        response_meanings=head.response_meanings,
    )
    payloads.extend(page_acq.payloads)
    failed_requests.extend(page_acq.failed_requests)
    issues.extend(page_acq.issues)
    if page_acq.stop_reason is not None:
        sanitized_page_interpretations = [
            replace(
                ip,
                parsed=replace(
                    ip.parsed,
                    rows=pl.DataFrame(schema=RowsSchema.polars_schema),
                    annotations=AnnotationBundle.empty(),
                    inventories=(),
                    outcomes=tuple(
                        o for o in ip.parsed.outcomes if o.status not in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY)
                    ),
                ),
            )
            for ip in page_interpretations
        ]
        interpretations.extend(sanitized_page_interpretations)
        call_refs = tuple(dict.fromkeys(page_acq.calls))
        for need in consumers:
            if spec.build_unresolved_outcome is not None:
                outcomes.append(spec.build_unresolved_outcome(need, page_acq, config))
            else:
                candidate = series_by_pair.get((need.station, need.product))
                s_def = (
                    candidate
                    if candidate is not None and need.scope.matches(candidate)
                    else next(
                        (item for item in need.known_series if need.scope.matches(item)),
                        None,
                    )
                )
                outcomes.append(
                    RetrievalOutcome(
                        outcome_id=stable_id(
                            "batch-unresolved",
                            need.station,
                            str(need.product),
                            *call_refs,
                        ),
                        series_id=s_def.series_id if s_def is not None else None,
                        station_id=need.station,
                        product_id=str(need.product),
                        window=bounds,
                        status=OutcomeStatus.UNRESOLVED,
                        reason=page_acq.stop_reason,
                        facts_ids=(
                            tuple(f.facts_id for f in s_def.facts if need.scope.matches_facts(f))
                            if s_def is not None
                            else ()
                        ),
                        calls=call_refs,
                    )
                )
        return

    interpretations.extend(page_interpretations)
    if spec.finalize_unseen_consumer is not None:
        for need in consumers:
            if (need.station, need.product) in seen_pairs:
                continue
            unseen_result = spec.finalize_unseen_consumer(need, page_acq.payloads, config)
            if isinstance(unseen_result, UnseenConsumerEvidence):
                definitions.extend(unseen_result.series)
                inventories.extend(unseen_result.inventories)
                outcomes.extend(unseen_result.outcomes)
            elif unseen_result is not None:
                outcomes.append(unseen_result)


def execute_planned_acquisition(
    planner: SourceRequestPlanner,
    needs: tuple[ConsumerNeed, ...],
    config: ProviderConfig,
    transport: Transport,
) -> SourceAcquisition:
    """Execute deduplicated lookups and observation requests for one provider selection."""
    payloads: list[Payload] = []
    interpretations: list[InterpretedPayload] = []
    issues: list[Issue] = []
    definitions: list[SourceSeries] = []
    inventories: list[InventorySnapshot] = []
    outcomes: list[RetrievalOutcome] = []
    calls: list[SourceCallOrigin] = []
    call_station_products: list[tuple[str, tuple[tuple[str, ProductId], ...]]] = []
    failed_requests: list[FailedSourceRequest] = []

    planned_lookups = planner.plan_lookups(needs, config)
    grouped_lookups: dict[tuple[Hashable, SourceRequestIdentity], list[PlannedLookup]] = {}
    for item in planned_lookups:
        grouped_lookups.setdefault((item.key, item.identity), []).append(item)

    lookup_resolutions: dict[tuple[Hashable, str, ProductId], LookupResolution] = {}
    for (lookup_key, _identity), entries in grouped_lookups.items():
        head = entries[0]
        if any(
            entry.emit_payload != head.emit_payload
            or entry.record_auxiliary_call != head.record_auxiliary_call
            or entry.window_in_identity != head.window_in_identity
            or entry.axis is not head.axis
            or entry.access_context != head.access_context
            or entry.response_meanings != head.response_meanings
            or (entry.on_response is None) != (head.on_response is None)
            or (entry.on_failure is None) != (head.on_failure is None)
            or (entry.interpret_payload is None) != (head.interpret_payload is None)
            or (entry.interpret_group is None) != (head.interpret_group is None)
            or (entry.resolve_payload is None) != (head.resolve_payload is None)
            for entry in entries[1:]
        ):
            raise FatalContractError("Planned lookups sharing a key and identity disagree on execution spec")
        consumers = _merge_consumers([need for entry in entries for need in entry.consumers])
        station_products = tuple((need.station, need.product) for need in consumers)
        prereqs = tuple(dict.fromkeys(pid for entry in entries for pid in entry.prerequisite_acquisition_ids))
        merged_window = _merge_fetch_windows([entry.fetch_window for entry in entries])
        attempted = attempt_request(transport, head.request)
        if isinstance(attempted, (TransportFailure, CredentialExchangeError)):
            call_id = uuid4().hex
            if head.on_failure is not None:
                failure_outcome = head.on_failure(attempted, head.request, consumers, call_id, call_id)
                if isinstance(failure_outcome, LookupFailureOutcome):
                    definitions.extend(failure_outcome.series)
                    inventories.extend(failure_outcome.inventories)
                    outcomes.extend(failure_outcome.outcomes)
                    issues.extend(failure_outcome.issues)
                    failed_requests.extend(failure_outcome.failed_requests)
                    calls.extend(failure_outcome.calls)
                    _append_call_station_products(call_station_products, failure_outcome.calls, station_products)
                else:
                    failed_requests.extend(failure_outcome)
            else:
                meaning = (
                    http_response_meaning(attempted, head.response_meanings)
                    if head.response_meanings is not None
                    else SourceResponseMeaning.UNSPECIFIED
                )
                for target in _failure_targets_for_consumers(consumers):
                    failed_requests.append(
                        FailedSourceRequest(
                            uuid4().hex,
                            target,
                            _series_window_from_fetch(merged_window, head.axis),
                            head.request,
                            attempted,
                            meaning=meaning,
                            call_id=call_id,
                            prerequisite_acquisition_ids=prereqs,
                        )
                    )
            failure_result = LookupFailureResult(call_id=call_id, failure=attempted)
            for need in consumers:
                lookup_resolutions[(lookup_key, need.station, need.product)] = failure_result
            continue

        acq_id = uuid4().hex
        if head.emit_payload:
            payload = Payload(
                source_coordinates=head.source_coordinates,
                station_products=station_products,
                fetch_window=merged_window,
                content=attempted.content,
                origin=SourceCallOrigin.from_response(attempted),
                prerequisite_calls=attempted.prerequisite_calls,
                scope=_merge_group_scope(consumers),
                known_series=_merge_known_series(consumers),
                attempt_traces=attempted.attempt_traces,
                acquisition_id=acq_id,
                acquisition_axis=head.axis,
                prerequisite_acquisition_ids=prereqs,
            )
            payloads.append(payload)
            parsed: ParsedSeries | None = None
            is_shared = len(consumers) > 1 or len(payload.station_products) > 1
            if head.resolve_payload is not None:
                pair_payloads = {
                    (need.station, need.product): _narrow_consumer_payload(payload, need, shared=is_shared)
                    for need in consumers
                }
                resolved_value, raw_grouped = head.resolve_payload(payload, pair_payloads, config)
                grouped = _validate_grouped_parsed(raw_grouped, pair_payloads.keys(), "PlannedLookup resolve_payload")
                for pair_key, pair_parsed in grouped.items():
                    interpretations.append(InterpretedPayload.from_payload(pair_payloads[pair_key], pair_parsed))
                    definitions.extend(pair_parsed.series)
                parsed = next(iter(grouped.values()), None)
                resolution: LookupResolution = ResolvedLookup(
                    value=resolved_value,
                    acquisition_id=acq_id,
                    payload=payload,
                    parsed=parsed,
                )
            else:
                if head.interpret_group is not None:
                    pair_payloads = {
                        (need.station, need.product): _narrow_consumer_payload(payload, need, shared=is_shared)
                        for need in consumers
                    }
                    grouped = _validate_grouped_parsed(
                        head.interpret_group(payload, pair_payloads, config),
                        pair_payloads.keys(),
                        "PlannedLookup interpret_group",
                    )
                    for pair_key, pair_parsed in grouped.items():
                        interpretations.append(InterpretedPayload.from_payload(pair_payloads[pair_key], pair_parsed))
                        definitions.extend(pair_parsed.series)
                    parsed = next(iter(grouped.values()), None)
                elif head.interpret_payload is not None:
                    parsed = head.interpret_payload(payload, config)
                    definitions.extend(parsed.series)
                    for need in consumers:
                        narrowed = _narrow_consumer_payload(payload, need, shared=is_shared)
                        interpretations.append(InterpretedPayload.from_payload(narrowed, parsed))
                resolution = ResolvedLookup(
                    value=attempted.content,
                    acquisition_id=acq_id,
                    payload=payload,
                    parsed=parsed,
                )
        else:
            if head.record_auxiliary_call:
                origin = SourceCallOrigin.from_response(attempted)
                calls.append(
                    replace(
                        origin,
                        acquisition_id=acq_id,
                        prerequisite_acquisition_ids=prereqs,
                        attempt_traces=attempted.attempt_traces,
                    )
                )
                call_station_products.append((acq_id, station_products))
            if head.on_response is not None:
                resolution = head.on_response(attempted, consumers, acq_id, config)
                if not resolution.acquisition_id:
                    resolution = replace(resolution, acquisition_id=acq_id)
                definitions.extend(resolution.series)
                inventories.extend(resolution.inventories)
                outcomes.extend(resolution.outcomes)
                issues.extend(resolution.issues)
                calls.extend(resolution.calls)
                _append_call_station_products(call_station_products, resolution.calls, station_products)
                failed_requests.extend(resolution.failed_requests)
            else:
                resolution = ResolvedLookup(value=attempted.content, acquisition_id=acq_id)
        for need in consumers:
            lookup_resolutions[(lookup_key, need.station, need.product)] = resolution

    plan = planner.plan_observations(needs, lookup_resolutions, config)
    del lookup_resolutions
    definitions.extend(plan.series)
    inventories.extend(plan.inventories)
    outcomes.extend(plan.outcomes)
    issues.extend(plan.issues)
    calls.extend(plan.calls)
    failed_requests.extend(plan.failed_requests)

    grouped_obs: dict[SourceRequestIdentity, list[PlannedObservationRequest]] = {}
    for req in plan.requests:
        grouped_obs.setdefault(req.identity, []).append(req)

    for entries in grouped_obs.values():
        head = entries[0]
        if any(
            entry.acquisition_axis is not head.acquisition_axis
            or entry.access_context != head.access_context
            or entry.response_meanings != head.response_meanings
            or entry.pagination != head.pagination
            or (entry.interpret_payload is None) != (head.interpret_payload is None)
            or (entry.interpret_group is None) != (head.interpret_group is None)
            or (entry.pre_failure_outcomes is None) != (head.pre_failure_outcomes is None)
            for entry in entries[1:]
        ):
            raise FatalContractError("Planned observation requests sharing an identity disagree on execution spec")
        consumers = _merge_consumers([need for entry in entries for need in entry.consumers])
        station_products = tuple((need.station, need.product) for need in consumers)
        prereqs = tuple(dict.fromkeys(pid for entry in entries for pid in entry.prerequisite_acquisition_ids))
        targets = _failure_targets_for_consumers(
            consumers, [target for entry in entries for target in entry.failure_targets]
        )
        shared_scope = _merge_group_scope(consumers)
        shared_known = _merge_known_series(consumers)
        bounds = _series_window_from_fetch(head.fetch_window, head.acquisition_axis)

        if head.pagination is not None:
            _execute_paginated_group(
                head,
                consumers,
                station_products,
                prereqs,
                targets,
                shared_scope,
                shared_known,
                bounds,
                config,
                transport,
                payloads=payloads,
                interpretations=interpretations,
                definitions=definitions,
                inventories=inventories,
                outcomes=outcomes,
                failed_requests=failed_requests,
                issues=issues,
            )
            continue

        attempted = attempt_request(transport, head.request)
        if isinstance(attempted, (TransportFailure, CredentialExchangeError)):
            call_id = uuid4().hex
            meaning = (
                http_response_meaning(attempted, head.response_meanings)
                if head.response_meanings is not None
                else SourceResponseMeaning.UNSPECIFIED
            )
            if head.pre_failure_outcomes is not None:
                outcomes.extend(head.pre_failure_outcomes(consumers, attempted, head.request, call_id))
            for target in targets:
                failed_requests.append(
                    FailedSourceRequest(
                        uuid4().hex,
                        target,
                        bounds,
                        head.request,
                        attempted,
                        meaning=meaning,
                        call_id=call_id,
                        prerequisite_acquisition_ids=prereqs,
                    )
                )
            continue

        payload = Payload(
            source_coordinates=head.source_coordinates,
            station_products=station_products,
            fetch_window=head.fetch_window,
            content=attempted.content,
            origin=SourceCallOrigin.from_response(attempted),
            prerequisite_calls=attempted.prerequisite_calls,
            scope=shared_scope,
            known_series=shared_known,
            attempt_traces=attempted.attempt_traces,
            acquisition_axis=head.acquisition_axis,
            prerequisite_acquisition_ids=prereqs,
        )
        payloads.append(payload)
        is_shared = len(consumers) > 1 or len(payload.station_products) > 1
        if head.interpret_group is not None:
            pair_payloads = {
                (need.station, need.product): _narrow_consumer_payload(payload, need, shared=is_shared)
                for need in consumers
            }
            grouped = _validate_grouped_parsed(
                head.interpret_group(payload, pair_payloads, config),
                pair_payloads.keys(),
                "PlannedObservationRequest interpret_group",
            )
            for pair_key, pair_parsed in grouped.items():
                interpretations.append(InterpretedPayload.from_payload(pair_payloads[pair_key], pair_parsed))
                definitions.extend(pair_parsed.series)
        elif head.interpret_payload is not None:
            parsed = head.interpret_payload(payload, config)
            definitions.extend(parsed.series)
            for need in consumers:
                narrowed = _narrow_consumer_payload(payload, need, shared=is_shared)
                interpretations.append(InterpretedPayload.from_payload(narrowed, parsed))

    unique_defs = tuple({item.series_id: item for item in definitions}.values())
    acquisition = SourceAcquisition(
        value=tuple(payloads),
        issues=tuple(issues),
        series=unique_defs,
        inventories=tuple(inventories),
        outcomes=tuple(outcomes),
        calls=tuple(calls),
        failed_requests=tuple(failed_requests),
        interpretations=tuple(interpretations),
        call_station_products=tuple(call_station_products),
    )
    return plan.finalize(acquisition) if plan.finalize is not None else acquisition


def _series_window_from_fetch(fetch_window: FetchWindow, axis: TimeAxis) -> SeriesWindow:
    return SeriesWindow(
        start=datetime.fromisoformat(fetch_window.start.isoformat()),
        end=datetime.fromisoformat(fetch_window.end.isoformat()),
        axis=axis,
    )

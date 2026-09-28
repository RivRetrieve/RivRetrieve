"""drive : ObservationRequest × ProviderStages × ObservationProvenance × ReceiptMode × Transport × CredentialVariableNames × CacheMode × StoreRoot → _AssemblyResult × StoreEffects; route_window_declarations : ProviderStages × Transport → ProductWindowDeclarations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from types import MappingProxyType
from typing import Protocol, runtime_checkable

import polars as pl

from rivretrieve._internal.assembly import _AssemblyResult, assemble
from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.conversion import convert, validate_native_rows
from rivretrieve._internal.coverage import (
    CoverageInterval,
    RequestedInterval,
    interval_envelope,
    remainder,
    served_coverage,
)
from rivretrieve._internal.engine import (
    CanonicalRows,
    CanonicalRowsSchema,
    Daily,
    FetchWindow,
    Hourly,
    Instant,
    ObservationRequest,
    Payload,
    ProductWindowDeclarations,
    ProviderConfig,
    RenderedWindow,
    RequestedWindow,
    Rows,
    RowsSchema,
    SourceAcquisition,
    SourceCallOrigin,
    SourceQuery,
    UnknownOriginFact,
    UnknownTemporalSupport,
    WindowEndpoint,
    WithIssues,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.observations import (
    ObservationProvenance,
    ReceiptAuthorship,
    ReceiptEntry,
    ReceiptMode,
    Receipts,
)
from rivretrieve._internal.primitives import CacheMode, ProductId, ProviderId
from rivretrieve._internal.source_acquisition import SourceResponseMeaning
from rivretrieve._internal.source_series import (
    ClippingAxis,
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    RequestedSelector,
    RestrictionKind,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    admission,
    stable_id,
    validate_series_rows,
)
from rivretrieve._internal.store import StoreQuery, StoreReader, StoreRoot
from rivretrieve._internal.store.accumulation import StoreUpdate, SuccessfulReplacement, accumulate
from rivretrieve._internal.store.receipts import encode_store_excerpt
from rivretrieve._internal.store.validation import (
    AccumulatedStoreManifest,
    ObservationStoreRefusedError,
    StoreManifest,
    StoreRefusal,
    StoreRefusalKind,
)
from rivretrieve._internal.time_axis import TimeAxis, axis_time_expression
from rivretrieve._internal.transport import (
    AuthenticationCapability,
    HttpClient,
    SecretCallTrace,
    Transport,
    TransportAttempt,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)
from rivretrieve._internal.window_planning import plan_windows

_FETCH_WINDOW_PADDING = timedelta(days=2)


def _require_fetch_window_contains_requested(
    fetch_window: FetchWindow,
    requested_window: RequestedWindow,
) -> None:
    if fetch_window.start <= requested_window.start and fetch_window.end >= requested_window.end:
        return
    raise FatalContractError(
        "Engine-created FetchWindow does not contain RequestedWindow: "
        f"fetch_start={fetch_window.start.isoformat()}, fetch_end={fetch_window.end.isoformat()}, "
        f"requested_start={requested_window.start.isoformat()}, "
        f"requested_end={requested_window.end.isoformat()}. This is an internal engine contract "
        "breach before provider fetch; please report it with these four endpoints."
    )


def _require_canonical_rows_within_requested(
    rows: CanonicalRows,
    series: tuple[SourceSeries, ...],
    requested_window: RequestedWindow,
) -> None:
    """Validate converted output against admitted facts and the caller's physical window."""
    validate_catalogue(rows, CanonicalRowsSchema, on_issue="raise")
    validate_series_rows(rows, series)
    facts = {fact.facts_id: fact for definition in series for fact in definition.facts}
    for row in rows.iter_rows(named=True):
        fact = facts[row["facts_id"]]
        decision = admission(fact)
        if row["quantity"] != fact.quantity.value or row["unit"] != decision.target_unit:
            raise FatalContractError("Canonical row contradicts its admitted physical facts")
    if _clip_native(rows, series, requested_window).height != rows.height:
        raise FatalContractError("CanonicalRows contain observations outside the RequestedWindow physical axis")


def _unknown_origin_value(value: UnknownOriginFact) -> dict[str, object]:
    return {"status": "unknown", "reason": value.reason.value}


def _copy_origin_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _origin_value(item) for key, item in value.items()}


def _origin_value(value: object) -> object:
    if isinstance(value, UnknownOriginFact):
        return _unknown_origin_value(value)
    if isinstance(value, bytes):
        import base64

        return {"encoding": "base64", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Mapping):
        return {str(key): _origin_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return tuple(_origin_value(item) for item in value)
    return value


def _query_value(value: SourceQuery | UnknownOriginFact) -> dict[str, object]:
    if isinstance(value, UnknownOriginFact):
        return _unknown_origin_value(value)
    return {"statement": value.statement, "parameters": tuple(_origin_value(item) for item in value.parameters)}


def _secret_call(call: SecretCallTrace) -> dict[str, object]:
    return {
        "method": call.method.value,
        "url": call.url,
        "request_parameters": None if call.request_parameters is None else dict(call.request_parameters),
        "request_body_shape": call.request_body_shape.value,
        "credential_header_names": call.credential_header_names,
        "status_code": call.status_code,
        "retrieved_at": call.retrieved_at,
        "content_type": call.content_type,
        "response_disposition": call.response_disposition.value,
    }


def _origin_call(origin: SourceCallOrigin) -> dict[str, object]:
    return {
        "url": _origin_value(origin.url),
        "request_parameters": _origin_value(origin.request_parameters),
        "status_code": _origin_value(origin.status_code),
        "retrieved_at": _origin_value(origin.retrieved_at),
        "content_type": _origin_value(origin.content_type),
        "source_path": _origin_value(origin.source_path),
        "query": _query_value(origin.query),
        **({"attempts": origin.attempts} if origin.attempts is not None else {}),
    }


def _attempt_call(attempt: TransportAttempt) -> dict[str, object]:
    """Retain facts observed at one sender invocation, not an inferred retry history."""
    return {
        "call_id": attempt.attempt_id,
        "url": attempt.url,
        "request_parameters": dict(attempt.request_parameters),
        "status_code": attempt.status_code,
        "retrieved_at": attempt.retrieved_at,
        "content_type": attempt.content_type or _origin_value(UnknownOriginFact()),
        "failure_reason": attempt.failure_category.value if attempt.failure_category is not None else None,
        "failure_category": attempt.failure_category.value if attempt.failure_category is not None else None,
    }


def _payload_calls(payload: Payload) -> tuple[dict[str, object], ...]:
    if not payload.attempt_traces:
        return ({**_origin_call(payload.origin), "call_id": payload.acquisition_id},)
    acquisition_id = payload.acquisition_id
    return tuple(
        {
            **(_origin_call(payload.origin) if index == len(payload.attempt_traces) else {}),
            **_attempt_call(attempt),
            "acquisition_id": acquisition_id,
            "attempt": index,
            "attempts": len(payload.attempt_traces),
        }
        for index, attempt in enumerate(payload.attempt_traces, 1)
    )


def _provenance_with_payload_origins(
    provenance: ObservationProvenance,
    payloads: tuple[Payload, ...],
    *,
    source_series_by_payload: tuple[tuple[str, ...], ...] = (),
) -> ObservationProvenance:
    """Bind ordered prerequisite event(s), then one payload-origin event per payload, independent of receipts."""
    if (
        provenance.calls_made
        or provenance.endpoints
        or provenance.retrieved_at is not None
        or provenance.query is not None
    ):
        raise FatalContractError(
            "Driver payload-origin enrichment requires empty call-derived base provenance; "
            "pre-populated calls, endpoints, retrieval time, or query would be ambiguous."
        )
    if not payloads:
        return provenance
    origins = tuple(payload.origin for payload in payloads)
    if source_series_by_payload and len(source_series_by_payload) != len(payloads):
        raise FatalContractError("Source-call identity context does not match its acquired payloads")
    contexts = tuple(
        {
            "station_products": payload.station_products,
            **({"series_ids": source_series_by_payload[index]} if source_series_by_payload else {}),
        }
        for index, payload in enumerate(payloads)
    )
    calls = tuple(
        call
        for index, payload in enumerate(payloads)
        for call in (
            *({**_secret_call(item), **contexts[index]} for item in payload.prerequisite_calls),
            *({**item, **contexts[index]} for item in _payload_calls(payload)),
        )
    )
    endpoints = tuple(
        dict.fromkeys(
            url
            for payload in payloads
            for url in (
                *(call.url for call in payload.prerequisite_calls),
                *((payload.origin.url,) if isinstance(payload.origin.url, str) else ()),
            )
        )
    )
    retrieved = tuple(
        instant
        for payload in payloads
        for instant in (
            *(call.retrieved_at for call in payload.prerequisite_calls),
            *((payload.origin.retrieved_at,) if isinstance(payload.origin.retrieved_at, datetime) else ()),
        )
    )
    query_values = tuple(_query_value(origin.query) for origin in origins if isinstance(origin.query, SourceQuery))
    known_query_list: list[dict[str, object]] = []
    for query_value in query_values:
        if query_value not in known_query_list:
            known_query_list.append(query_value)
    known_queries = tuple(known_query_list)
    query: dict[str, object] | None
    if not known_queries:
        query = None
    elif len(known_queries) == 1:
        query = known_queries[0]
    else:
        query = {"calls": known_queries}
    return provenance.model_copy(
        update={
            "calls_made": calls,
            "endpoints": endpoints,
            "retrieved_at": max(retrieved) if retrieved else None,
            "query": query,
        }
    )


class _SourceResponseTransport:
    """source response transport : TransportRequest × Transport → TransportResponse ∪ TransportFailure."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def can_authenticate(self, url: str) -> bool:
        return isinstance(self._transport, AuthenticationCapability) and self._transport.can_authenticate(url)

    def send(self, request: TransportRequest) -> TransportResponse:
        response = self._transport.send(request)
        if 200 <= response.status_code < 300:
            return response
        raise TransportFailure(
            request,
            TransportFailureReason.HTTP_STATUS,
            response.attempts,
            status_code=response.status_code,
            category=TransportFailureCategory.HTTP_STATUS,
            response=response,
            attempt_traces=response.attempt_traces,
        )


def _source_failure_issue(
    provider_id: ProviderId,
    station_id: str,
    product_id: ProductId,
    failure: TransportFailure | CredentialExchangeError,
    credential_names: tuple[str, ...],
) -> Issue:
    """source failure classification : Series × (TransportFailure | CredentialExchangeError) × CredentialNames → Issue."""
    details: dict[str, object] = {
        "station_id": station_id,
        "product_id": str(product_id),
        "failure_reason": failure.reason.value,
        "attempts": failure.attempts,
        "status_code": failure.status_code,
    }
    if failure.category is not None:
        details["failure_category"] = failure.category.value
    details["request_url"] = failure.request.url
    if isinstance(failure, CredentialExchangeError) and failure.transport_reason is not None:
        details["transport_failure_reason"] = failure.transport_reason.value
    if failure.status_code == 404 and not isinstance(failure, CredentialExchangeError):
        return Issue(
            severity="warning",
            code="source.http_not_found",
            message=(
                f"Provider {provider_id} source returned HTTP 404 for station {station_id}, product {product_id}."
            ),
            details=details,
            provider_id=provider_id,
        )
    if failure.status_code in (401, 403) and credential_names:
        names = ", ".join(credential_names)
        details["credential_variables"] = list(credential_names)
        message = (
            f"Provider {provider_id} rejected the credential for station {station_id}, product {product_id}: "
            f"HTTP {failure.status_code}; check {names}."
        )
    elif isinstance(failure, CredentialExchangeError):
        message = (
            f"Provider {provider_id} authentication failed for station {station_id}, product {product_id}: "
            f"{failure.reason.value}."
        )
    elif failure.reason is TransportFailureReason.HTTP_STATUS:
        message = (
            f"Provider {provider_id} failed for station {station_id}, product {product_id}: HTTP {failure.status_code}."
        )
    else:
        reason_text = {
            TransportFailureReason.RETRY_EXHAUSTED: (
                "transport retries were exhausted after a timeout, connection interruption, or retryable response"
            ),
            TransportFailureReason.TERMINAL_SENDER_FAILURE: "the transport sender failed terminally",
            TransportFailureReason.REPLAY_UNSAFE: "the failed request could not safely be repeated",
            TransportFailureReason.RETRY_DELAY_EXCEEDED: "the server retry delay exceeded the bounded waiting policy",
            TransportFailureReason.REDIRECT_REFUSED: "a credentialed redirect was refused",
            TransportFailureReason.RETAINED_METADATA_UNSAFE: (
                "the response could not be retained without exposing a credential"
            ),
            TransportFailureReason.HTTP_STATUS: "the source returned a non-success HTTP status",
        }[failure.reason]
        status = f" with HTTP status {failure.status_code}" if failure.status_code is not None else ""
        message = f"Provider {provider_id} failed for station {station_id}, product {product_id}: {reason_text}{status} ({failure.category.value})."
    return Issue(
        severity="error",
        code="source.request_failed",
        message=message,
        details=details,
        provider_id=provider_id,
    )


class ProviderStages(Protocol):
    """Fetch returns ordered source calls; parse receives each exact Payload without transformation."""

    config: ProviderConfig
    window_declarations: ProductWindowDeclarations

    @staticmethod
    def fetch(
        stations: tuple[str, ...],
        products: tuple[ProductId, ...],
        rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
        fetch_window: FetchWindow,
        config: ProviderConfig,
        transport: Transport,
        *,
        scope: SeriesScope | None = None,
        known_series: tuple[SourceSeries, ...] = (),
    ) -> WithIssues[tuple[Payload, ...]]: ...

    @staticmethod
    def parse(
        payload: Payload,
        config: ProviderConfig,
    ) -> ParsedSeries: ...


@runtime_checkable
class SharedAcquisitionProvider(Protocol):
    """Declare products co-published by one independently exhaustive source route."""

    shared_acquisition_products: tuple[frozenset[ProductId], ...]


@runtime_checkable
class TransportWindowDeclarationProvider(Protocol):
    """Select source window semantics from an engine-supplied transport capability."""

    @staticmethod
    def window_declarations_for_transport(transport: Transport) -> ProductWindowDeclarations: ...


def _requested_interval(
    window: RequestedWindow, semantics: Instant | Daily | Hourly | UnknownTemporalSupport | None
) -> RequestedInterval:
    start = datetime.fromisoformat(window.start.isoformat())
    end = datetime.fromisoformat(window.end.isoformat())
    if isinstance(semantics, Daily):
        start = datetime.combine(start.date(), time.min)
        end = datetime.combine(end.date(), time.max)
    return RequestedInterval(start, end)


def _padded_interval(interval: RequestedInterval) -> FetchWindow:
    return _make_fetch_window(
        WindowEndpoint.from_datetime(interval.start - _FETCH_WINDOW_PADDING),
        WindowEndpoint.from_datetime(interval.end + _FETCH_WINDOW_PADDING),
    )


def _scope_for_pair(scope: SeriesScope, provider: str, station: str, product: str) -> SeriesScope:
    return scope.model_copy(update={"provider_ids": (provider,), "station_ids": (station,), "product_ids": (product,)})


def _merge_definitions(definitions: dict[str, SourceSeries], additions: tuple[SourceSeries, ...]) -> None:
    for item in additions:
        previous = definitions.get(item.series_id)
        if previous is None:
            definitions[item.series_id] = item
            continue
        if (
            previous.provider_id,
            previous.station_id,
            previous.product_id,
            previous.identity.namespace,
            previous.identity.published_id,
        ) != (item.provider_id, item.station_id, item.product_id, item.identity.namespace, item.identity.published_id):
            raise FatalContractError("A source-series identifier changed its source identity")
        facts = {fact.facts_id: fact for fact in previous.facts}
        for fact in item.facts:
            if fact.facts_id in facts and facts[fact.facts_id] != fact:
                raise FatalContractError("A physical-facts identifier changed its meaning")
            facts[fact.facts_id] = fact
        definitions[item.series_id] = item.model_copy(update={"facts": tuple(facts.values())})


def _validate_parsed_series(parsed: ParsedSeries) -> None:
    """Reject ambiguous coverage claims within one payload, without deduplicating source rows."""
    identities: set[str] = set()
    windows: dict[tuple[str, str], list[RetrievalOutcome]] = {}
    for outcome in parsed.outcomes:
        if outcome.outcome_id in identities:
            raise FatalContractError(f"ParsedSeries contains duplicate outcome_id {outcome.outcome_id!r}")
        identities.add(outcome.outcome_id)
        if outcome.series_id is None:
            continue
        for facts_id in dict.fromkeys(outcome.facts_ids):
            windows.setdefault((outcome.series_id, facts_id), []).append(outcome)
    for (series_id, facts_id), outcomes in windows.items():
        positive: RetrievalOutcome | None = None
        unsuccessful: RetrievalOutcome | None = None
        for outcome in sorted(outcomes, key=lambda item: item.window.start):
            is_positive = outcome.status in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY)
            conflicts = (positive, unsuccessful) if is_positive else (positive,)
            for previous in conflicts:
                if previous is not None and outcome.window.axis is not previous.window.axis:
                    raise FatalContractError("One source series cannot mix acquisition time axes")
                if previous is not None and outcome.window.start <= previous.window.end:
                    raise FatalContractError(
                        "ParsedSeries positive outcome coverage overlaps for "
                        f"series_id={series_id!r}, facts_id={facts_id!r}: "
                        f"outcome_id={previous.outcome_id!r} ({previous.status.value}) and "
                        f"outcome_id={outcome.outcome_id!r} ({outcome.status.value})"
                    )
            if is_positive:
                if positive is None or outcome.window.end > positive.window.end:
                    positive = outcome
            elif unsuccessful is None or outcome.window.end > unsuccessful.window.end:
                unsuccessful = outcome


def _clip_native(rows: Rows, series: tuple[SourceSeries, ...], window: RequestedWindow) -> Rows:
    facts = {fact.facts_id: fact for item in series for fact in item.facts}
    start = datetime.fromisoformat(window.start.isoformat())
    end = datetime.fromisoformat(window.end.isoformat())
    keep = []
    for row in rows.iter_rows(named=True):
        fact = facts.get(row["facts_id"])
        if fact is None:
            raise FatalContractError("Native clipping references unknown physical facts")
        timestamp = row["time"]
        keep.append(
            start.date() <= timestamp.date() <= end.date()
            if fact.clipping_axis is ClippingAxis.CALENDAR_DATE
            else start <= timestamp <= end
        )
    return rows.filter(pl.Series(keep, dtype=pl.Boolean))


def _exclude_native_intervals(
    rows: Rows, series: tuple[SourceSeries, ...], intervals: tuple[tuple[str, RequestedInterval], ...]
) -> Rows:
    """Exclude concrete source intervals on each physical fact's clipping axis."""
    if rows.is_empty() or not intervals:
        return rows
    daily_facts = tuple(
        facts.facts_id for item in series for facts in item.facts if facts.clipping_axis is ClippingAxis.CALENDAR_DATE
    )
    daily = pl.col("facts_id").is_in(daily_facts)
    keep = pl.lit(True)
    for series_id, interval in intervals:
        inside = (
            axis_time_expression(interval.axis).is_between(interval.start, interval.end, closed="both")
            if interval.axis is TimeAxis.UTC
            else (
                daily & pl.col("time").dt.date().is_between(interval.start.date(), interval.end.date(), closed="both")
            )
            | (~daily & pl.col("time").is_between(interval.start, interval.end, closed="both"))
        )
        keep = keep & ~((pl.col("series_id") == series_id) & inside)
    return rows.filter(keep)


def _snapshot_matches(snapshot: InventorySnapshot, scope: SeriesScope, window: SeriesWindow) -> bool:
    held = snapshot.scope
    if snapshot.window is not None and snapshot.window.axis is not window.axis:
        converted = interval_envelope(
            RequestedInterval(window.start, window.end, axis=window.axis), snapshot.window.axis
        )
        window = SeriesWindow(start=converted.start, end=converted.end, axis=converted.axis)
    if snapshot.origin == "catalogue":
        return False
    if snapshot.window is not None and (snapshot.window.start > window.start or snapshot.window.end < window.end):
        return False
    if (
        held.provider_ids != scope.provider_ids
        or held.station_ids != scope.station_ids
        or held.product_ids != scope.product_ids
        or not set(held.predicates).issubset(scope.predicates)
    ):
        return False
    if scope.restriction is RestrictionKind.ALL:
        return held.restriction is RestrictionKind.ALL and snapshot.completeness is InventoryCompleteness.COMPLETE
    if held == scope:
        return snapshot.completeness is InventoryCompleteness.COMPLETE
    return held.restriction is RestrictionKind.ALL and snapshot.completeness is InventoryCompleteness.COMPLETE


@dataclass(frozen=True, slots=True)
class _ReusePlan:
    inventories: tuple[InventorySnapshot, ...]
    series: tuple[SourceSeries, ...]


def _reconcile_acquired_inventories(
    acquired: SourceAcquisition,
    parsed_results: tuple[ParsedSeries, ...],
    scope: SeriesScope,
    window: SeriesWindow,
) -> tuple[InventorySnapshot, ...]:
    """Keep current inventory knowledge separate from transaction-bounded retrieval proof."""
    declared = {item.series_id: item for item in acquired.series}
    outcomes = (*acquired.outcomes, *(item for parsed in parsed_results for item in parsed.outcomes))
    reconciled = []
    for snapshot in acquired.inventories:
        compared = interval_envelope(
            RequestedInterval(window.start, window.end, axis=window.axis),
            snapshot.window.axis if snapshot.window is not None else window.axis,
        )
        snapshot_window = (
            SeriesWindow(start=compared.start, end=compared.end, axis=compared.axis)
            if snapshot.window is None
            else SeriesWindow(
                start=max(compared.start, snapshot.window.start),
                end=min(compared.end, snapshot.window.end),
                axis=compared.axis,
            )
            if snapshot.window.start <= compared.end and snapshot.window.end >= compared.start
            else None
        )
        if snapshot_window is None or not _snapshot_matches(snapshot, scope, snapshot_window):
            continue
        scoped_outcomes = tuple(
            item
            for item in outcomes
            if item.window.axis is snapshot_window.axis
            and item.window.start <= snapshot_window.end
            and item.window.end >= snapshot_window.start
        )
        reasons: list[str] = []
        members = set(snapshot.members)
        declared_facts = dict(snapshot.member_facts)
        scoped_observed = tuple(
            definition
            for parsed in parsed_results
            if any(
                item.window.axis is snapshot_window.axis
                and item.window.start <= snapshot_window.end
                and item.window.end >= snapshot_window.start
                for item in parsed.outcomes
            )
            for definition in parsed.series
        )
        if not members.issubset(declared):
            reasons.append("Acquisition inventory members lack declared physical definitions")
        for item in scoped_observed:
            definition = declared.get(item.series_id)
            if item.series_id not in members or definition is None:
                reasons.append("An observation response identifies a member outside the acquired inventory")
                continue
            if any(
                fact not in definition.facts
                or (item.series_id in declared_facts and fact.facts_id not in declared_facts[item.series_id])
                for fact in item.facts
            ):
                reasons.append("Observation physical facts differ from the acquired inventory facts")
        if any(
            event.window.axis is snapshot_window.axis
            and event.window.start <= snapshot_window.end
            and event.window.end >= snapshot_window.start
            for event in acquired.failed_requests
        ) or any(
            outcome.status in (OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED)
            for outcome in scoped_outcomes
        ):
            reasons.append("This acquisition has failed, unsupported or unresolved observation outcomes")
        for key in snapshot.members:
            definition = declared.get(key)
            if definition is None or not scope.matches(definition):
                continue
            for fact in definition.facts:
                if key in declared_facts and fact.facts_id not in declared_facts[key]:
                    continue
                if not scope.matches_facts(fact) or admission(fact).status != "supported":
                    continue
                observed_definition = any(item.series_id == key and fact in item.facts for item in scoped_observed)
                acquired_empty = any(
                    item.series_id == key and fact.facts_id in item.facts_ids and item.status is OutcomeStatus.EMPTY
                    for item in scoped_outcomes
                )
                if not observed_definition and not acquired_empty:
                    reasons.append("A matching admitted member lacks a concrete response definition")
                coverage = tuple(
                    RequestedInterval(outcome.window.start, outcome.window.end, axis=outcome.window.axis)
                    for outcome in scoped_outcomes
                    if outcome.series_id == key
                    and fact.facts_id in outcome.facts_ids
                    and outcome.status in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY)
                )
                if remainder(
                    RequestedInterval(snapshot_window.start, snapshot_window.end, axis=snapshot_window.axis), coverage
                ):
                    reasons.append("A matching admitted member lacks successful coverage in this acquisition")
        reason = "; ".join(dict.fromkeys(reasons)) if reasons else None
        evidence = (
            *snapshot.evidence,
            f"source-inventory:{snapshot.snapshot_id}",
            *(f"retrieval-outcome:{outcome.outcome_id}" for outcome in scoped_outcomes),
        )
        instants = tuple(
            instant
            for instant in (snapshot.acquired_at, *(outcome.retrieved_at for outcome in scoped_outcomes))
            if instant is not None
        )
        reconciled.append(
            InventorySnapshot(
                snapshot_id=stable_id(
                    snapshot.snapshot_id, scope.model_dump_json(), snapshot_window.model_dump_json(), *evidence, reason
                ),
                scope=scope,
                members=snapshot.members,
                member_facts=tuple(
                    (
                        key,
                        tuple(
                            fact.facts_id
                            for fact in declared[key].facts
                            if key not in declared_facts or fact.facts_id in declared_facts[key]
                        ),
                    )
                    for key in snapshot.members
                    if key in declared
                ),
                completeness=InventoryCompleteness.INCOMPLETE if reasons else InventoryCompleteness.COMPLETE,
                access=f"{snapshot.access}; reconciled against this retrieval's concrete outcomes",
                origin="response",
                acquired_at=max(instants) if instants else None,
                window=snapshot_window,
                evidence=evidence,
                reason=reason,
            )
        )
    for axis in TimeAxis:
        complete = tuple(
            item
            for item in reconciled
            if item.completeness is InventoryCompleteness.COMPLETE
            and item.window is not None
            and item.window.axis is axis
        )
        requested = interval_envelope(RequestedInterval(window.start, window.end, axis=window.axis), axis)
        intervals = tuple(
            RequestedInterval(item.window.start, item.window.end, axis=axis)
            for item in complete
            if item.window is not None
        )
        if len(complete) < 2 or remainder(requested, intervals):
            continue
        members = tuple(dict.fromkeys(key for item in complete for key in item.members))
        member_facts = tuple(
            (
                key,
                tuple(
                    dict.fromkeys(
                        fact
                        for item in complete
                        for member, facts in item.member_facts
                        if member == key
                        for fact in facts
                    )
                ),
            )
            for key in members
        )
        instants = tuple(item.acquired_at for item in complete if item.acquired_at is not None)
        reconciled.append(
            InventorySnapshot(
                snapshot_id=stable_id("complete-acquisition-inventory", *(item.snapshot_id for item in complete)),
                scope=scope,
                members=members,
                member_facts=member_facts,
                completeness=InventoryCompleteness.COMPLETE,
                access="Complete independently bounded source acquisitions",
                origin="response",
                acquired_at=max(instants) if instants else None,
                window=SeriesWindow(start=requested.start, end=requested.end, axis=axis),
                evidence=tuple(f"source-inventory:{item.snapshot_id}" for item in complete),
            )
        )
    return tuple(reconciled)


def _covered_facts(
    manifest: AccumulatedStoreManifest,
    definition: SourceSeries,
    scope: SeriesScope,
    window: SeriesWindow,
    inventories: tuple[InventorySnapshot, ...] = (),
) -> bool:
    interval = RequestedInterval(window.start, window.end, axis=window.axis)
    return all(
        any(
            not remainder(
                interval_envelope(interval, axis),
                (
                    *(
                        item.interval
                        for item in manifest.coverage
                        if item.series_id == definition.series_id
                        and fact.facts_id in item.facts_ids
                        and item.interval.axis is axis
                    ),
                    *(
                        RequestedInterval(item.window.start, item.window.end, axis=axis)
                        for item in inventories
                        if item.completeness is InventoryCompleteness.COMPLETE
                        and item.origin != "catalogue"
                        and item.window is not None
                        and _snapshot_matches(item, scope, item.window)
                        and item.window.axis is axis
                        and (
                            definition.series_id not in item.members
                            or (
                                definition.series_id in dict(item.member_facts)
                                and fact.facts_id not in dict(item.member_facts)[definition.series_id]
                            )
                        )
                    ),
                ),
            )
            for axis in TimeAxis
        )
        for fact in definition.facts
        if scope.matches_facts(fact) and admission(fact).status == "supported"
    )


def _explicit_reuse(manifest: AccumulatedStoreManifest, scope: SeriesScope, window: SeriesWindow) -> _ReusePlan | None:
    """A closed identity scope may use independently acquired member inventories."""
    identity_scope = scope.model_copy(update={"predicates": ()})
    members = []
    snapshots: dict[str, InventorySnapshot] = {}
    for definition in manifest.series:
        if not identity_scope.matches(definition):
            continue
        observed = None
        for snapshot in reversed(manifest.inventories):
            held = snapshot.scope
            if snapshot.origin == "catalogue" or (held.provider_ids, held.station_ids, held.product_ids) != (
                scope.provider_ids,
                scope.station_ids,
                scope.product_ids,
            ):
                continue
            compared = interval_envelope(
                RequestedInterval(window.start, window.end, axis=window.axis),
                snapshot.window.axis if snapshot.window else window.axis,
            )
            if snapshot.window is not None and (
                snapshot.window.start > compared.end or snapshot.window.end < compared.start
            ):
                continue
            if definition.series_id in snapshot.members:
                facts = dict(snapshot.member_facts).get(definition.series_id)
                observed = (
                    definition
                    if facts is None
                    else definition.model_copy(
                        update={"facts": tuple(fact for fact in definition.facts if fact.facts_id in facts)}
                    )
                )
                if scope.matches(observed):
                    snapshots[snapshot.snapshot_id] = snapshot
                break
            if snapshot.completeness is InventoryCompleteness.COMPLETE and _snapshot_matches(snapshot, scope, window):
                break
        if observed is None or not scope.matches(observed):
            continue
        contributors = tuple(
            item for item in manifest.inventories if f"source-inventory:{item.snapshot_id}" in snapshot.evidence
        )
        if not _covered_facts(manifest, observed, scope, window, contributors):
            return None
        members.append(observed)
    ids = {item.series_id for item in members}
    variants = {value for item in members for value in (item.variant, item.identity.published_id) if value is not None}
    if not members or not set(scope.series_ids).issubset(ids) or not set(scope.variants).issubset(variants):
        return None
    if not any(
        scope.matches_facts(fact) and admission(fact).status == "supported" for item in members for fact in item.facts
    ):
        return None
    return _ReusePlan(tuple(snapshots.values()), tuple(members))


def _reusable_snapshot(
    manifest: AccumulatedStoreManifest, scope: SeriesScope, window: SeriesWindow
) -> _ReusePlan | None:
    if scope.restriction is RestrictionKind.EXPLICIT:
        return _explicit_reuse(manifest, scope, window)
    definitions = {item.series_id: item for item in manifest.series}
    newer_overlaps: list[InventorySnapshot] = []
    for snapshot in reversed(manifest.inventories):
        held = snapshot.scope
        if snapshot.origin == "catalogue":
            continue
        compared = interval_envelope(
            RequestedInterval(window.start, window.end, axis=window.axis),
            snapshot.window.axis if snapshot.window else window.axis,
        )
        if (held.provider_ids, held.station_ids, held.product_ids) != (
            scope.provider_ids,
            scope.station_ids,
            scope.product_ids,
        ):
            continue
        if any(
            left.field == right.field and left.value != right.value
            for left in held.predicates
            for right in scope.predicates
        ):
            continue
        if held.restriction is RestrictionKind.EXPLICIT and scope.restriction is RestrictionKind.EXPLICIT:
            if held.series_ids and scope.series_ids and not set(held.series_ids).intersection(scope.series_ids):
                continue
            if held.variants and scope.variants and not set(held.variants).intersection(scope.variants):
                continue
        if snapshot.window is not None and (
            snapshot.window.start > compared.start or snapshot.window.end < compared.end
        ):
            if snapshot.window.start <= compared.end and snapshot.window.end >= compared.start:
                newer_overlaps.append(snapshot)
            continue
        # New narrower source knowledge can invalidate an older broad identity
        # proof even when the old interval still has successfully cached rows.
        if any(
            (
                item.scope.restriction is RestrictionKind.ALL
                and (
                    item.completeness is not InventoryCompleteness.COMPLETE
                    or set(item.members) != set(snapshot.members)
                    or (item.member_facts and dict(item.member_facts) != dict(snapshot.member_facts))
                )
            )
            or not set(item.members).issubset(snapshot.members)
            or any(
                not set(facts).issubset(dict(snapshot.member_facts).get(member, ()))
                for member, facts in item.member_facts
            )
            for item in newer_overlaps
        ):
            return None
        # A newer applicable observation cannot be hidden by an older inventory.
        if scope.restriction is RestrictionKind.ALL and not _snapshot_matches(snapshot, scope, window):
            return None
        acquired_facts = dict(snapshot.member_facts)
        observed_members = tuple(
            definitions[key].model_copy(
                update={
                    "facts": tuple(
                        fact
                        for fact in definitions[key].facts
                        if key not in acquired_facts or fact.facts_id in acquired_facts[key]
                    )
                }
            )
            for key in snapshot.members
            if key in definitions
        )
        members = tuple(item for item in observed_members if scope.matches(item))
        if scope.restriction is RestrictionKind.EXPLICIT:
            ids = {item.series_id for item in members}
            variants = {
                value for item in members for value in (item.variant, item.identity.published_id) if value is not None
            }
            if not members or not set(scope.series_ids).issubset(ids) or not set(scope.variants).issubset(variants):
                return None
        if members and not any(
            scope.matches_facts(fact) and admission(fact).status == "supported"
            for definition in members
            for fact in definition.facts
        ):
            return None
        contributors = tuple(
            item for item in manifest.inventories if f"source-inventory:{item.snapshot_id}" in snapshot.evidence
        )
        if all(_covered_facts(manifest, definition, scope, window, contributors) for definition in members):
            return _ReusePlan((snapshot,), members)
        return None
    return None


def _overlaps(outcome: RetrievalOutcome, interval: RequestedInterval) -> bool:
    compared = interval_envelope(interval, outcome.window.axis)
    return outcome.window.start <= compared.end and outcome.window.end >= compared.start


def _issue_in_scope(
    issue: Issue,
    station: str,
    product: str,
    series_ids: tuple[str, ...],
    *,
    interval: RequestedInterval,
    outcomes: tuple[RetrievalOutcome, ...],
    resolved_scope: SeriesScope | None = None,
) -> bool:
    details = issue.details or {}
    inventory_scope = details.get("inventory_scope")
    if (
        issue.code == "source.inventory_unresolved"
        and not any(
            details.get(key) is not None
            for key in ("series_id", "series_ids", "variant", "variants", "facts_id", "facts_ids")
        )
        and resolved_scope is not None
        and resolved_scope.restriction is RestrictionKind.EXPLICIT
        and inventory_scope is not None
    ):
        try:
            assessed_scope = SeriesScope.model_validate(inventory_scope)
        except (ValueError, TypeError) as error:
            raise FatalContractError("Stored inventory diagnostic scope is malformed") from error
        if assessed_scope.restriction is RestrictionKind.ALL:
            return False
    if not all(
        details.get(key) is None or details[key] in allowed
        for key, allowed in (
            ("station_id", (station,)),
            ("product_id", (product,)),
            ("series_id", series_ids),
        )
    ):
        return False
    assessments = tuple(
        item
        for item in outcomes
        if item.station_id == station
        and item.product_id == product
        and (item.series_id is None or item.series_id in series_ids)
        and (details.get("series_id") is None or item.series_id == details["series_id"])
        and item.reason == issue.message
    )
    return not assessments or any(_overlaps(item, interval) for item in assessments)


def _calls_in_scope(
    manifest: AccumulatedStoreManifest,
    station: str,
    product: str,
    series_ids: tuple[str, ...],
    *,
    interval: RequestedInterval,
) -> tuple[dict[str, object], ...]:
    referenced = {call for item in manifest.outcomes for call in item.calls}
    relevant = {
        call
        for item in manifest.outcomes
        if item.station_id == station
        and item.product_id == product
        and (item.series_id is None or item.series_id in series_ids)
        and _overlaps(item, interval)
        for call in item.calls
    }
    retained = []
    for call in manifest.source_calls:
        associated = call.get("series_ids")
        if isinstance(associated, (list, tuple)) and associated and not set(associated).intersection(series_ids):
            continue
        if call.get("call_id") in referenced and call.get("call_id") not in relevant:
            continue
        pairs = call.get("station_products")
        if isinstance(pairs, (list, tuple)):
            coordinates = tuple(tuple(pair) for pair in pairs if isinstance(pair, (list, tuple)))
            if len(coordinates) != len(pairs) or any(len(pair) != 2 for pair in coordinates):
                raise FatalContractError("Stored source-call routing coordinates are malformed")
            if (station, product) not in coordinates:
                continue
        if any(
            call.get(key) is not None and call[key] not in allowed
            for key, allowed in (
                ("station_id", (station,)),
                ("product_id", (product,)),
                ("series_id", series_ids),
            )
        ):
            continue
        retained.append(call)
    return tuple(retained)


def _finite_selector_assessments(
    provider_id: ProviderId,
    assessments: list[tuple[SeriesScope, SeriesWindow]],
    definitions: dict[str, SourceSeries],
    inventories: list[InventorySnapshot],
    outcomes: list[RetrievalOutcome],
    issues: list[Issue],
) -> tuple[RetrievalOutcome, ...]:
    """Account for each finite caller member without inventing a source identity."""
    previous = {item.outcome_id for item in outcomes if item.requested_selector is not None}
    outcomes[:] = [item for item in outcomes if item.requested_selector is None]
    issues[:] = [item for item in issues if (item.details or {}).get("outcome_id") not in previous]
    generated = []
    for scope, window in assessments:
        if scope.restriction is not RestrictionKind.EXPLICIT:
            continue
        station, product = scope.station_ids[0], scope.product_ids[0]
        selectors = (
            *(RequestedSelector(kind="variant", value=value) for value in scope.variants),
            *(RequestedSelector(kind="series_id", value=value) for value in scope.series_ids),
        )
        for selector in selectors:
            narrowed = scope.model_copy(
                update={"variants" if selector.kind == "variant" else "series_ids": (selector.value,)}
            )
            identity_scope = narrowed.model_copy(update={"predicates": ()})
            represented = False
            for outcome in outcomes:
                definition = definitions.get(outcome.series_id) if outcome.series_id is not None else None
                if definition is None or not identity_scope.matches(definition):
                    continue
                if not _overlaps(outcome, RequestedInterval(window.start, window.end, axis=window.axis)):
                    continue
                if outcome.status not in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY):
                    represented = True
                    break
                if any(
                    fact.facts_id in outcome.facts_ids and narrowed.matches_facts(fact) for fact in definition.facts
                ):
                    represented = True
                    break
            if represented:
                continue
            relevant = [
                item
                for item in inventories
                if item.origin != "catalogue"
                and (not item.scope.provider_ids or set(narrowed.provider_ids).issubset(item.scope.provider_ids))
                and (not item.scope.station_ids or set(narrowed.station_ids).issubset(item.scope.station_ids))
                and (not item.scope.product_ids or set(narrowed.product_ids).issubset(item.scope.product_ids))
                and set(item.scope.predicates).issubset(narrowed.predicates)
                and (
                    item.window is None
                    or (
                        item.window.start
                        <= interval_envelope(
                            RequestedInterval(window.start, window.end, axis=window.axis), item.window.axis
                        ).start
                        and item.window.end
                        >= interval_envelope(
                            RequestedInterval(window.start, window.end, axis=window.axis), item.window.axis
                        ).end
                    )
                )
                and (
                    not item.scope.series_ids
                    or (bool(narrowed.series_ids) and set(narrowed.series_ids).issubset(item.scope.series_ids))
                )
                and (
                    not item.scope.variants
                    or (bool(narrowed.variants) and set(narrowed.variants).issubset(item.scope.variants))
                )
            ]
            settled = bool(relevant) and relevant[-1].completeness is InventoryCompleteness.COMPLETE
            reason = (
                f"No source series matches requested {selector.kind} {selector.value!r} in the acquired scoped inventory"
                if settled
                else f"The acquired evidence cannot settle requested {selector.kind} {selector.value!r}"
            )
            outcome = RetrievalOutcome(
                outcome_id=stable_id(
                    "requested-selector",
                    str(provider_id),
                    station,
                    product,
                    narrowed.model_dump_json(),
                    window.model_dump_json(),
                    *(item.snapshot_id for item in relevant),
                    reason,
                ),
                series_id=None,
                station_id=station,
                product_id=product,
                window=window,
                status=OutcomeStatus.NO_MATCH if settled else OutcomeStatus.UNRESOLVED,
                reason=reason,
                requested_selector=selector,
            )
            generated.append(outcome)
            issues.append(
                Issue(
                    severity="warning",
                    code="source.no_match" if settled else "source.inventory_unresolved",
                    message=reason,
                    details={
                        "station_id": station,
                        "product_id": product,
                        "outcome_id": outcome.outcome_id,
                        "requested_selector": selector.model_dump(mode="json"),
                        "inventory_scope": scope.model_dump(mode="json"),
                    },
                    provider_id=provider_id,
                )
            )
    outcomes.extend(generated)
    return tuple(generated)


def _result_metadata(
    scope: SeriesScope,
    definitions: dict[str, SourceSeries],
    inventories: list[InventorySnapshot],
    outcomes: list[RetrievalOutcome],
) -> tuple[tuple[SourceSeries, ...], tuple[InventorySnapshot, ...], tuple[RetrievalOutcome, ...]]:
    selected_ids = {item.series_id for item in definitions.values() if scope.matches(item)}
    identity_scope = scope.model_copy(update={"predicates": ()})
    requested_ids = {item.series_id for item in definitions.values() if identity_scope.matches(item)}
    retained_outcomes = tuple(
        item
        for item in outcomes
        if item.series_id is None
        or item.series_id in selected_ids
        or (item.status not in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY) and item.series_id in requested_ids)
    )
    return (
        tuple(definitions.values()),
        tuple({item.snapshot_id: item for item in inventories}.values()),
        tuple({item.outcome_id: item for item in retained_outcomes}.values()),
    )


def _combine_replacements(
    replacements: list[SuccessfulReplacement],
    fresh_outcomes: list[RetrievalOutcome],
    outcomes: list[RetrievalOutcome],
) -> list[SuccessfulReplacement]:
    """Replace one concrete window once, with every acquired native contribution."""
    grouped: dict[tuple[str, RequestedInterval], list[SuccessfulReplacement]] = {}
    by_id = {item.outcome_id: item for item in fresh_outcomes}
    failures = tuple(
        item
        for item in fresh_outcomes
        if item.status in (OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED)
    )
    acquisition_axes: dict[tuple[str, str], TimeAxis] = {}
    for replacement in replacements:
        for facts_id in replacement.coverage.facts_ids:
            key = replacement.coverage.series_id, facts_id
            previous_axis = acquisition_axes.setdefault(key, replacement.coverage.interval.axis)
            if previous_axis is not replacement.coverage.interval.axis:
                raise FatalContractError("One source series cannot mix acquisition time axes")
        original = by_id[replacement.coverage.outcome_id]
        excluded = tuple(
            RequestedInterval(item.window.start, item.window.end, axis=item.window.axis)
            for item in failures
            if (
                item.series_id == original.series_id
                or (
                    item.series_id is None
                    and item.status in (OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED)
                    and item.station_id == original.station_id
                    and item.product_id == original.product_id
                )
            )
        )
        if any(item.axis is not replacement.coverage.interval.axis for item in excluded):
            raise FatalContractError("One source series cannot mix acquisition time axes")
        for interval in remainder(replacement.coverage.interval, excluded):
            part = replacement
            if interval != replacement.coverage.interval:
                native = replacement.rows.filter(
                    axis_time_expression(interval.axis).is_between(interval.start, interval.end)
                )
                outcome = original.model_copy(
                    update={
                        "outcome_id": stable_id(
                            original.outcome_id, interval.start.isoformat(), interval.end.isoformat()
                        ),
                        "window": SeriesWindow(start=interval.start, end=interval.end, axis=interval.axis),
                        "status": OutcomeStatus.EMPTY if native.is_empty() else OutcomeStatus.SUCCESS,
                        "observation_keys": tuple(
                            dict.fromkeys(native.select("facts_id", "time", "time_zone").iter_rows())
                        )
                        if original.coverage == "observations"
                        else (),
                    }
                )
                outcomes.append(outcome)
                fresh_outcomes.append(outcome)
                by_id[outcome.outcome_id] = outcome
                part = replace(
                    replacement,
                    rows=native,
                    coverage=replace(replacement.coverage, interval=interval, outcome_id=outcome.outcome_id),
                )
            key = part.coverage.series_id, part.coverage.interval
            grouped.setdefault(key, []).append(part)
    combined = []
    snapshot_keys: set[tuple[str, str, datetime, str]] = set()
    for (series_id, interval), parts in grouped.items():
        for part in parts:
            if by_id[part.coverage.outcome_id].coverage != "observations":
                continue
            keys = {(series_id, *key) for key in part.rows.select("facts_id", "time", "time_zone").iter_rows()}
            if snapshot_keys.intersection(keys):
                raise FatalContractError("Independent snapshot acquisitions overlap observation keys")
            snapshot_keys.update(keys)
        if len(parts) == 1:
            combined.append(parts[0])
            continue
        if any(by_id[part.coverage.outcome_id].coverage == "observations" for part in parts):
            if not all(by_id[part.coverage.outcome_id].coverage == "observations" for part in parts):
                raise FatalContractError("A replacement window mixes interval and observation-only evidence")
            combined.extend(parts)
            continue
        contributors = tuple(by_id[item.coverage.outcome_id] for item in parts)
        native = pl.concat([item.rows for item in parts])
        instants = tuple(item.retrieved_at for item in contributors if item.retrieved_at is not None)
        outcome = contributors[0].model_copy(
            update={
                "outcome_id": stable_id("combined", *(item.outcome_id for item in contributors)),
                "status": OutcomeStatus.EMPTY if native.is_empty() else OutcomeStatus.SUCCESS,
                "facts_ids": tuple(dict.fromkeys(fact for item in contributors for fact in item.facts_ids)),
                "retrieved_at": max(instants) if instants else None,
                "calls": tuple(dict.fromkeys(call for item in contributors for call in item.calls)),
            }
        )
        outcomes.append(outcome)
        fresh_outcomes.append(outcome)
        combined.append(
            SuccessfulReplacement(
                CoverageInterval(series_id, interval, outcome.retrieved_at, outcome.outcome_id, outcome.facts_ids),
                native,
                replaced_facts_ids=tuple(
                    dict.fromkeys(
                        fact for part in parts for fact in (part.replaced_facts_ids or part.coverage.facts_ids)
                    )
                ),
            )
        )
    return combined


@dataclass(frozen=True, slots=True)
class _PairRetrieval:
    """Independent selection, cache proof and source bounds for one station product."""

    station: str
    product: ProductId
    scope: SeriesScope
    series: tuple[SourceSeries, ...]
    interval: RequestedInterval
    window: SeriesWindow
    reuse: _ReusePlan | None
    fetch_window: FetchWindow | None
    rendered: tuple[RenderedWindow, ...]


def _acquisition_groups(
    plans: list[_PairRetrieval], shared_products: tuple[frozenset[ProductId], ...]
) -> tuple[tuple[_PairRetrieval, ...], ...]:
    """Share declared co-published products with equal engine-established bounds.

    Cache eligibility remains per pair. Providers without an explicit source-route
    declaration retain singleton failure boundaries.
    """
    groups: list[list[_PairRetrieval]] = []
    for plan in plans:
        if plan.reuse is not None:
            continue
        compatible = next(
            (
                group
                for group in groups
                if any(
                    {plan.product, *(item.product for item in group)}.issubset(products) for products in shared_products
                )
                and group[0].station == plan.station
                and group[0].fetch_window == plan.fetch_window
                and group[0].rendered == plan.rendered
            ),
            None,
        )
        if compatible is None:
            groups.append([plan])
        else:
            compatible.append(plan)
    return tuple(tuple(group) for group in groups)


def _unique_calls(calls: tuple[dict[str, object], ...]) -> tuple[dict[str, object], ...]:
    """Retain distinct attempts, including legacy evidence without an attempt ID."""
    seen: set[str] = set()
    result = []
    for call in calls:
        identity = call.get("call_id")
        if isinstance(identity, str):
            if identity in seen:
                continue
            seen.add(identity)
        result.append(call)
    return tuple(result)


def drive(
    request: ObservationRequest,
    provider: ProviderStages,
    *,
    provenance: ObservationProvenance,
    receipts: ReceiptMode = ReceiptMode.OMIT,
    transport: Transport | None = None,
    credential_names: tuple[str, ...] = (),
    cache: CacheMode = "bypass",
    store: StoreRoot | None = None,
) -> _AssemblyResult:
    if not isinstance(receipts, ReceiptMode):
        raise TypeError("receipts must be ReceiptMode")
    if cache not in ("bypass", "reuse", "refresh"):
        raise ValueError("cache must be bypass, reuse, or refresh")
    if cache != "bypass" and store is None:
        raise FatalContractError("Caching requires a resolved store path")
    scope = request.scope or SeriesScope(
        provider_ids=(str(request.provider_id),), station_ids=request.stations, product_ids=tuple(request.products)
    )
    config = provider.config
    # Catalogue route candidates guide acquisition; only response/store definitions
    # describe the acquired result. A route placeholder is not an extra method.
    definitions: dict[str, SourceSeries] = {}
    inventories: list[InventorySnapshot] = [
        item
        for item in request.inventories
        if item.catalogue_claims
        and (not item.scope.provider_ids or str(request.provider_id) in item.scope.provider_ids)
        and (not item.scope.station_ids or set(item.scope.station_ids).intersection(request.stations))
        and (not item.scope.product_ids or set(item.scope.product_ids).intersection(request.products))
    ]
    outcomes: list[RetrievalOutcome] = []
    all_issues: list[Issue] = []
    rows: list[Rows] = [pl.DataFrame(schema=RowsSchema.polars_schema)]
    receipt_entries: list[ReceiptEntry] = []
    payloads: list[Payload] = []
    source_series_by_payload: list[tuple[str, ...]] = []
    cached_calls: list[dict[str, object]] = []
    served: list[CoverageInterval] = []
    pending: list[SuccessfulReplacement] = []
    fresh_definitions: dict[str, SourceSeries] = {}
    fresh_inventories: list[InventorySnapshot] = list(inventories)
    fresh_outcomes: list[RetrievalOutcome] = []
    manifest: AccumulatedStoreManifest | None = None
    if cache != "bypass":
        assert store is not None
        held = StoreReader().status(store, request.provider_id).manifest
        if held is not None:
            if not isinstance(held, AccumulatedStoreManifest):
                raise FatalContractError("Live retrieval requires an accumulated store")
            manifest = held
    resolved_transport = HttpClient() if transport is None else transport
    declarations = (
        provider.window_declarations_for_transport(resolved_transport)
        if isinstance(provider, TransportWindowDeclarationProvider)
        else provider.window_declarations
    )
    finite_assessments: list[tuple[SeriesScope, SeriesWindow]] = []
    plans: list[_PairRetrieval] = []
    for station in request.stations:
        for product in request.products:
            pair_scope = _scope_for_pair(scope, str(request.provider_id), station, str(product))
            if scope.series_ids:
                known_identities = {item.series_id: item for item in request.known_series}
                if manifest is not None:
                    known_identities.update((item.series_id, item) for item in manifest.series)
                local_ids = tuple(
                    key
                    for key in scope.series_ids
                    if key not in known_identities
                    or (known_identities[key].station_id == station and known_identities[key].product_id == product)
                )
                if not local_ids:
                    continue
                pair_scope = pair_scope.model_copy(update={"series_ids": local_ids})
            pair_series = tuple(
                item for item in request.known_series if item.station_id == station and item.product_id == product
            )
            if manifest is not None:
                acquired_series = tuple(
                    item for item in manifest.series if item.station_id == station and item.product_id == product
                )
                if acquired_series:
                    candidates = {item.series_id: item for item in pair_series}
                    _merge_definitions(candidates, acquired_series)
                    pair_series = tuple(candidates.values())
            # Daily calendar-date windows retain the established clipping rule.
            interval = _requested_interval(request.window, config.products[product].semantics)
            window = SeriesWindow(start=interval.start, end=interval.end)
            finite_assessments.append((pair_scope, window))
            reuse = _reusable_snapshot(manifest, pair_scope, window) if cache == "reuse" and manifest else None
            fetch_window = None
            rendered = ()
            if reuse is None:
                if product not in declarations.products:
                    raise FatalContractError(f"Missing window declaration for {product}")
                fetch_window = _padded_interval(interval)
                _require_fetch_window_contains_requested(fetch_window, request.window)
                rendered = plan_windows(fetch_window, declarations.products[product])
            plans.append(
                _PairRetrieval(
                    station, product, pair_scope, pair_series, interval, window, reuse, fetch_window, rendered
                )
            )
    shared_products = provider.shared_acquisition_products if isinstance(provider, SharedAcquisitionProvider) else ()
    groups = _acquisition_groups(plans, shared_products)
    group_for_pair = {(plan.station, plan.product): index for index, group in enumerate(groups) for plan in group}
    acquired: dict[int, WithIssues[tuple[Payload, ...]] | TransportFailure | CredentialExchangeError] = {}
    payload_indices: dict[tuple[int, int], int] = {}
    for plan in plans:
        station, product = plan.station, plan.product
        pair_scope, pair_series = plan.scope, plan.series
        interval, window, reuse = plan.interval, plan.window, plan.reuse
        if reuse is not None:
            assert manifest is not None
            members = reuse.series
            referenced = {key for item in reuse.inventories for key in item.members}
            acquired_members = tuple(item for item in manifest.series if item.series_id in referenced)
            _merge_definitions(definitions, acquired_members)
            inventories.extend(reuse.inventories)
            snapshot = reuse.inventories[0]
            ids = tuple(item.series_id for item in members)
            matching_facts = tuple(
                fact.facts_id for item in members for fact in item.facts if pair_scope.matches_facts(fact)
            )
            if not ids:
                reason = "The retained source inventory contains no matching series"
                outcomes.append(
                    RetrievalOutcome(
                        outcome_id=stable_id(
                            snapshot.snapshot_id, pair_scope.model_dump_json(), window.model_dump_json(), "no_match"
                        ),
                        series_id=None,
                        station_id=station,
                        product_id=str(product),
                        window=window,
                        status=OutcomeStatus.NO_MATCH,
                        reason=reason,
                    )
                )
                all_issues.append(
                    Issue(
                        severity="warning",
                        code="source.no_match",
                        message=reason,
                        details={"station_id": station, "product_id": str(product)},
                        provider_id=request.provider_id,
                    )
                )
            outcomes.extend(
                item
                for item in manifest.outcomes
                if _overlaps(item, interval)
                and (
                    item.series_id in ids
                    or (item.series_id is None and item.station_id == station and item.product_id == product)
                )
            )
            all_issues.extend(
                issue
                for issue in manifest.issues
                if _issue_in_scope(
                    issue,
                    station,
                    str(product),
                    ids,
                    interval=interval,
                    outcomes=manifest.outcomes,
                    resolved_scope=pair_scope,
                )
            )
            cached_calls.extend(_calls_in_scope(manifest, station, str(product), ids, interval=interval))
            for key in ids:
                served.extend(
                    replace(item, facts_ids=tuple(fact for fact in item.facts_ids if fact in matching_facts))
                    for axis in TimeAxis
                    for item in served_coverage(manifest.coverage, key, interval_envelope(interval, axis))
                    if set(item.facts_ids).intersection(matching_facts)
                )
            if ids:
                assert store is not None
                read = StoreReader().query(
                    StoreQuery(
                        store,
                        request.provider_id,
                        (station,),
                        (product,),
                        interval.start,
                        interval.end,
                        series_ids=ids,
                        facts_ids=matching_facts,
                    )
                )
                rows.append(read.rows)
                if receipts is ReceiptMode.INCLUDE:
                    receipt_entries.append(encode_store_excerpt(read))
            continue

        restored_held_ids: set[str] = set()

        def retain_held_successes(
            target_ids: tuple[str, ...] = (),
            *,
            held_scope: SeriesScope = pair_scope,
            held_interval: RequestedInterval = interval,
            held_station: str = station,
            held_product: ProductId = product,
            restored_ids: set[str] = restored_held_ids,
        ) -> None:
            if cache == "bypass" or manifest is None or store is None:
                return
            held_series = tuple(
                item
                for item in manifest.series
                if held_scope.matches(item) and (not target_ids or item.series_id in target_ids)
            )
            ids = tuple(item.series_id for item in held_series)
            fact_ids = tuple(
                fact.facts_id for item in held_series for fact in item.facts if held_scope.matches_facts(fact)
            )
            coverage = tuple(
                replace(item, interval=remaining)
                for key in ids
                for axis in TimeAxis
                for item in served_coverage(manifest.coverage, key, interval_envelope(held_interval, axis))
                if set(item.facts_ids).intersection(fact_ids)
                for remaining in remainder(
                    item.interval,
                    tuple(
                        previous.interval
                        for previous in served
                        if previous.series_id == item.series_id
                        and set(item.facts_ids).issubset(previous.facts_ids)
                        and previous.interval.axis is item.interval.axis
                    ),
                )
            )
            if not coverage:
                return
            held_read = StoreReader().query(
                StoreQuery(
                    store,
                    request.provider_id,
                    (held_station,),
                    (held_product,),
                    interval_envelope(held_interval, TimeAxis.NATIVE).start,
                    interval_envelope(held_interval, TimeAxis.NATIVE).end,
                    series_ids=ids,
                    facts_ids=fact_ids,
                )
            )
            restored_ids.update(ids)
            held_rows = _exclude_native_intervals(
                held_read.rows.filter(
                    axis_time_expression(held_interval.axis).is_between(held_interval.start, held_interval.end)
                ),
                held_series,
                tuple((item.series_id, item.interval) for item in served),
            )
            held_rows = _clip_native(held_rows, held_series, request.window)
            rows.append(held_rows)
            _merge_definitions(definitions, held_series)
            selected_snapshots = tuple(item for item in manifest.inventories if set(item.members).intersection(ids))
            referenced_ids = {key for item in selected_snapshots for key in item.members}
            _merge_definitions(definitions, tuple(item for item in manifest.series if item.series_id in referenced_ids))
            inventories[:0] = list(selected_snapshots)
            for item in manifest.outcomes:
                if item.series_id not in ids or not _overlaps(item, held_interval):
                    continue
                compared = interval_envelope(held_interval, item.window.axis)
                held_window = SeriesWindow(
                    start=max(item.window.start, compared.start),
                    end=min(item.window.end, compared.end),
                    axis=item.window.axis,
                )
                outcomes.append(
                    item.model_copy(
                        update={
                            "window": held_window,
                            "outcome_id": stable_id(item.outcome_id, held_window.model_dump_json()),
                        }
                    )
                )
            served.extend(coverage)
            all_issues.extend(
                issue
                for issue in manifest.issues
                if _issue_in_scope(
                    issue, held_station, str(held_product), ids, interval=held_interval, outcomes=manifest.outcomes
                )
            )
            cached_calls.extend(_calls_in_scope(manifest, held_station, str(held_product), ids, interval=held_interval))
            if receipts is ReceiptMode.INCLUDE:
                receipt_entries.append(encode_store_excerpt(held_read))

        group_index = group_for_pair[(station, product)]
        group = groups[group_index]
        if group_index not in acquired:
            fetch_window = group[0].fetch_window
            assert fetch_window is not None
            group_scope = pair_scope.model_copy(
                update={
                    "product_ids": tuple(item.product for item in group),
                    "series_ids": tuple(dict.fromkeys(key for item in group for key in item.scope.series_ids)),
                }
            )
            try:
                acquired[group_index] = provider.fetch(
                    (station,),
                    tuple(item.product for item in group),
                    MappingProxyType({item.product: item.rendered for item in group}),
                    fetch_window,
                    config,
                    _SourceResponseTransport(resolved_transport),
                    scope=group_scope,
                    known_series=tuple(series for item in group for series in item.series),
                )
            except (TransportFailure, CredentialExchangeError) as failure:
                acquired[group_index] = failure
        result = acquired[group_index]
        if isinstance(result, (TransportFailure, CredentialExchangeError)):
            failure = result
            issue = _source_failure_issue(request.provider_id, station, product, failure, credential_names)
            all_issues.append(issue)
            retain_held_successes()
            known_members = {
                key
                for snapshot in (*request.inventories, *(manifest.inventories if manifest is not None else ()))
                for key in snapshot.members
            }
            targets = tuple(
                item for item in pair_series if pair_scope.matches(item) and item.series_id in known_members
            )
            _merge_definitions(definitions, targets)
            _merge_definitions(fresh_definitions, targets)
            for target in targets or (None,):
                outcome = RetrievalOutcome(
                    outcome_id=stable_id(
                        "failure",
                        str(request.provider_id),
                        station,
                        str(product),
                        window.model_dump_json(),
                        str(len(fresh_outcomes)),
                        provenance.requested_at.isoformat() if provenance.requested_at else None,
                    ),
                    series_id=target.series_id if target else None,
                    station_id=station,
                    product_id=str(product),
                    window=window,
                    status=OutcomeStatus.FAILED,
                    reason=issue.message,
                )
                outcomes.append(outcome)
                fresh_outcomes.append(outcome)
            continue
        fetched = result
        all_issues.extend(
            issue.model_copy(
                update={"details": {**(issue.details or {}), "inventory_scope": pair_scope.model_dump(mode="json")}}
            )
            if issue.code == "source.inventory_unresolved"
            else issue
            for issue in fetched.issues
        )
        if isinstance(fetched, SourceAcquisition):
            _merge_definitions(definitions, fetched.series)
            _merge_definitions(fresh_definitions, fetched.series)
            inventories.extend(fetched.inventories)
            fresh_inventories.extend(fetched.inventories)
            outcomes.extend(fetched.outcomes)
            fresh_outcomes.extend(fetched.outcomes)
            # Transaction-level failures are known before any individual page is
            # assembled. Restore held concrete successes first, so later partial
            # page rows cannot overlap them. Inventory-only unknown failures do
            # not override independently successful concrete requests.
            failed_acquired_ids = tuple(
                item.series_id
                for item in fetched.outcomes
                if item.series_id is not None
                and item.status in (OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED)
            )
            for failed_outcome in fetched.outcomes:
                if failed_outcome.series_id not in failed_acquired_ids or failed_outcome.status not in (
                    OutcomeStatus.FAILED,
                    OutcomeStatus.UNSUPPORTED,
                    OutcomeStatus.UNRESOLVED,
                ):
                    continue
                requested_failure_axis = interval_envelope(interval, failed_outcome.window.axis)
                failed_start = max(requested_failure_axis.start, failed_outcome.window.start)
                failed_end = min(requested_failure_axis.end, failed_outcome.window.end)
                if failed_start <= failed_end:
                    retain_held_successes(
                        (failed_outcome.series_id,) if failed_outcome.series_id is not None else (),
                        held_interval=RequestedInterval(failed_start, failed_end, axis=failed_outcome.window.axis),
                    )
            # A fully exhausted source transaction can establish an empty answer
            # for a known concrete member even when no page contains its rows.
            for original in fetched.outcomes:
                if original.status is not OutcomeStatus.EMPTY:
                    continue
                definition = next((item for item in fetched.series if item.series_id == original.series_id), None)
                if definition is None:
                    raise FatalContractError("Acquired empty outcome lacks a concrete source definition")
                established = {fact.facts_id: fact for fact in definition.facts}
                if any(key not in established for key in original.facts_ids):
                    raise FatalContractError("Acquired empty outcome references unknown physical facts")
                matching_facts = tuple(
                    key
                    for key in original.facts_ids
                    if pair_scope.matches_facts(established[key]) and admission(established[key]).status == "supported"
                )
                if not pair_scope.matches(definition) or not matching_facts:
                    continue
                start, end = (
                    (original.window.start, original.window.end)
                    if original.window.axis is TimeAxis.UTC
                    else (max(window.start, original.window.start), min(window.end, original.window.end))
                )
                if start > end:
                    continue
                empty_outcome = original.model_copy(
                    update={
                        "window": SeriesWindow(start=start, end=end, axis=original.window.axis),
                        "facts_ids": matching_facts,
                        "outcome_id": stable_id(
                            original.outcome_id, start.isoformat(), end.isoformat(), *matching_facts
                        ),
                    }
                )
                outcomes.append(empty_outcome)
                fresh_outcomes.append(empty_outcome)
                pending.append(
                    SuccessfulReplacement(
                        CoverageInterval(
                            definition.series_id,
                            RequestedInterval(start, end, axis=original.window.axis),
                            empty_outcome.retrieved_at,
                            empty_outcome.outcome_id,
                            matching_facts,
                        ),
                        pl.DataFrame(schema=RowsSchema.polars_schema),
                        replaced_facts_ids=matching_facts,
                    )
                )
            cached_calls.extend(
                {**_origin_call(origin), "station_products": ((station, str(product)),)} for origin in fetched.calls
            )
            for event in fetched.failed_requests:
                target = event.series
                if len(group) > 1 and (target.station_id, target.product_id) != (station, product):
                    continue
                response = event.failure.response if isinstance(event.failure, TransportFailure) else None
                call = {
                    "call_id": event.call_id or event.event_id,
                    **(
                        {
                            "station_id": target.station_id,
                            "product_id": target.product_id,
                            "series_id": target.series_id,
                        }
                        if sum(
                            (item.call_id or item.event_id) == (event.call_id or event.event_id)
                            for item in fetched.failed_requests
                        )
                        == 1
                        else {}
                    ),
                    "station_products": tuple(
                        (item.series.station_id, item.series.product_id)
                        for item in fetched.failed_requests
                        if (item.call_id or item.event_id) == (event.call_id or event.event_id)
                    ),
                    "series_ids": tuple(
                        item.series.series_id
                        for item in fetched.failed_requests
                        if (item.call_id or item.event_id) == (event.call_id or event.event_id)
                        and item.series.series_id is not None
                    ),
                    "url": event.request.url,
                    "request_parameters": dict(event.request.params or {}),
                    "status_code": event.failure.status_code,
                    "retrieved_at": _origin_value(UnknownOriginFact()),
                    "content_type": _origin_value(UnknownOriginFact()),
                    "window": event.window.model_dump(mode="json"),
                    "failure_reason": event.failure.reason.value,
                    "attempts": event.failure.attempts,
                    "response_meaning": event.meaning.value,
                }
                if response is not None:
                    call.update(
                        url=response.url,
                        request_parameters=dict(response.request_parameters),
                        retrieved_at=response.retrieved_at,
                        content_type=response.content_type or _origin_value(UnknownOriginFact()),
                    )
                    cached_calls.extend(_secret_call(item) for item in response.prerequisite_calls)
                attempt_traces = event.failure.attempt_traces if isinstance(event.failure, TransportFailure) else ()
                if attempt_traces:
                    call_ids = tuple(attempt.attempt_id for attempt in attempt_traces)
                    cached_calls.extend(
                        {
                            **call,
                            **_attempt_call(attempt),
                            "acquisition_id": event.call_id or event.event_id,
                            "acquisition_failure_reason": event.failure.reason.value,
                            "attempt": index,
                            "response_meaning": (
                                event.meaning.value
                                if index == len(attempt_traces)
                                else SourceResponseMeaning.UNSPECIFIED.value
                            ),
                        }
                        for index, attempt in enumerate(attempt_traces, 1)
                    )
                else:
                    call_ids = (event.call_id or event.event_id,)
                    cached_calls.append(call)
                requested_failure_axis = interval_envelope(interval, event.window.axis)
                overlap_start = max(requested_failure_axis.start, event.window.start)
                overlap_end = min(requested_failure_axis.end, event.window.end)
                outside = overlap_start > overlap_end
                if (
                    outside
                    and event.meaning is SourceResponseMeaning.NO_OBSERVATIONS
                    and isinstance(event.failure, TransportFailure)
                    and event.failure.reason is TransportFailureReason.HTTP_STATUS
                    and event.failure.status_code == 404
                ):
                    continue
                if isinstance(target, SourceSeries):
                    _merge_definitions(definitions, (target,))
                    _merge_definitions(fresh_definitions, (target,))
                failed_window = (
                    event.window
                    if outside
                    else SeriesWindow(start=overlap_start, end=overlap_end, axis=event.window.axis)
                )
                if not outside:
                    retain_held_successes(
                        (target.series_id,) if target.series_id is not None else (),
                        held_interval=RequestedInterval(overlap_start, overlap_end, axis=event.window.axis),
                    )
                issue = _source_failure_issue(
                    request.provider_id,
                    target.station_id,
                    ProductId(target.product_id),
                    event.failure,
                    credential_names,
                )
                issue = issue.model_copy(
                    update={
                        "details": {
                            **(issue.details or {}),
                            "series_id": target.series_id,
                            "variant": target.variant,
                            "window": event.window.model_dump(mode="json"),
                            "outcome_id": event.event_id,
                        },
                        "message": issue.message
                        + (f" Source variant: {target.variant}." if target.variant is not None else "")
                        + f" Source interval: {event.window.start.isoformat()}..{event.window.end.isoformat()}.",
                    }
                )
                all_issues.append(issue)
                outcome = RetrievalOutcome(
                    outcome_id=event.event_id,
                    series_id=target.series_id,
                    station_id=target.station_id,
                    product_id=target.product_id,
                    window=failed_window,
                    status=OutcomeStatus.FAILED,
                    reason=issue.message,
                    calls=call_ids,
                )
                outcomes.append(outcome)
                fresh_outcomes.append(outcome)
        if not fetched.value and not (
            isinstance(fetched, SourceAcquisition) and (fetched.outcomes or fetched.failed_requests)
        ):
            reason = "Source acquisition returned no response; successful coverage is not established"
            outcome = RetrievalOutcome(
                outcome_id=stable_id(
                    "no-response", station, str(product), window.model_dump_json(), str(provenance.requested_at)
                ),
                series_id=None,
                station_id=station,
                product_id=str(product),
                window=window,
                status=OutcomeStatus.UNRESOLVED,
                reason=reason,
            )
            outcomes.append(outcome)
            fresh_outcomes.append(outcome)
            all_issues.append(
                Issue(
                    severity="warning",
                    code="source.inventory_unresolved",
                    message=reason,
                    details={"station_id": station, "product_id": str(product)},
                    provider_id=request.provider_id,
                )
            )
        transaction_parsed: list[ParsedSeries] = []
        parsed_payloads: list[tuple[int, ParsedSeries]] = []
        for received_index, received in enumerate(fetched.value):
            if len(group) > 1:
                if (station, product) not in received.station_products:
                    continue
                payload = replace(
                    received, station_products=((station, product),), scope=pair_scope, known_series=pair_series
                )
            else:
                payload = replace(
                    received, scope=received.scope or pair_scope, known_series=received.known_series or pair_series
                )
            # Pair-local parsing must not multiply the acquired bytes or call evidence.
            # Identity is the acquisition and payload position, never URL/content equality.
            payload_key = (group_index, received_index)
            if payload_key not in payload_indices:
                payload_indices[payload_key] = len(payloads)
                payloads.append(received)
                source_series_by_payload.append(())
                if receipts is ReceiptMode.INCLUDE:
                    receipt_entries.append(
                        ReceiptEntry(received.content, received.origin, ReceiptAuthorship.PUBLISHER_PAYLOAD)
                    )
            payload_index = payload_indices[payload_key]
            parsed = provider.parse(payload, config)
            if not isinstance(parsed, ParsedSeries):
                raise FatalContractError("Provider parse must return ParsedSeries")
            _validate_parsed_series(parsed)
            validate_native_rows(parsed.rows, config.products, series=parsed.series)
            transaction_parsed.append(parsed)
            parsed_payloads.append((payload_index, parsed))
        # Resolve held fallback for the entire acquisition before admitting fresh
        # rows. A late incomplete page has the same effect as an early one.
        for _, parsed in parsed_payloads:
            for failed_outcome in parsed.outcomes:
                if failed_outcome.status not in (
                    OutcomeStatus.FAILED,
                    OutcomeStatus.UNSUPPORTED,
                    OutcomeStatus.UNRESOLVED,
                ):
                    continue
                requested_failure_axis = interval_envelope(interval, failed_outcome.window.axis)
                failed_start = max(requested_failure_axis.start, failed_outcome.window.start)
                failed_end = min(requested_failure_axis.end, failed_outcome.window.end)
                if failed_start <= failed_end:
                    retain_held_successes(
                        (failed_outcome.series_id,) if failed_outcome.series_id is not None else (),
                        held_interval=RequestedInterval(failed_start, failed_end, axis=failed_outcome.window.axis),
                    )
        for payload_index, parsed in parsed_payloads:
            source_series_by_payload[payload_index] = tuple(
                dict.fromkeys((*source_series_by_payload[payload_index], *(item.series_id for item in parsed.series)))
            )
            _merge_definitions(definitions, parsed.series)
            _merge_definitions(fresh_definitions, parsed.series)
            acquired_facts = {item.series_id: tuple(fact.facts_id for fact in item.facts) for item in parsed.series}
            acquired_snapshots = []
            for original_snapshot in parsed.inventories:
                incomplete = any(
                    item.status in (OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED)
                    and item.series_id in original_snapshot.members
                    and (original_snapshot.window is None or item.window.axis is original_snapshot.window.axis)
                    and (
                        original_snapshot.window is None
                        or (
                            item.window.start <= original_snapshot.window.end
                            and item.window.end >= original_snapshot.window.start
                        )
                    )
                    for item in (
                        *(fetched.outcomes if isinstance(fetched, SourceAcquisition) else ()),
                        *(outcome for result in transaction_parsed for outcome in result.outcomes),
                    )
                )
                if incomplete:
                    original_snapshot = original_snapshot.model_copy(
                        update={
                            "completeness": InventoryCompleteness.INCOMPLETE,
                            "reason": "The source transaction has failed, unsupported or unresolved outcomes",
                        }
                    )
                snapshot = original_snapshot.model_copy(
                    update={
                        "member_facts": tuple(
                            (key, acquired_facts[key]) for key in original_snapshot.members if key in acquired_facts
                        ),
                    }
                )
                acquired_snapshots.append(
                    snapshot.model_copy(
                        update={
                            "snapshot_id": stable_id(
                                original_snapshot.snapshot_id, snapshot.model_dump_json(exclude={"snapshot_id"})
                            ),
                        }
                    )
                )
            inventories.extend(acquired_snapshots)
            fresh_inventories.extend(acquired_snapshots)
            all_issues.extend(parsed.issues)
            native = _clip_native(parsed.rows, parsed.series, request.window)
            selected_ids = {item.series_id for item in parsed.series if pair_scope.matches(item)}
            selected_facts = {
                fact.facts_id for item in parsed.series for fact in item.facts if pair_scope.matches_facts(fact)
            }
            native = native.filter(pl.col("series_id").is_in(selected_ids) & pl.col("facts_id").is_in(selected_facts))
            if isinstance(fetched, SourceAcquisition):
                unsupported = tuple(
                    (item.series_id, RequestedInterval(item.window.start, item.window.end, axis=item.window.axis))
                    for item in fetched.outcomes
                    if item.series_id is not None and item.status is OutcomeStatus.UNSUPPORTED
                )
                # A contradiction invalidates its bounded transaction, not other
                # independently acquired intervals of the same source series.
                native = _exclude_native_intervals(native, parsed.series, unsupported)
            # Coverage/outcome evidence describes the current source page even
            # when reuse serves held values instead of overlapping partial rows.
            coverage_native = (
                parsed.rows.filter(pl.col("series_id").is_in(selected_ids) & pl.col("facts_id").is_in(selected_facts))
                if any(item.window.axis is TimeAxis.UTC for item in parsed.outcomes)
                else native
            )
            if restored_held_ids:
                native = _exclude_native_intervals(
                    native,
                    parsed.series,
                    tuple((item.series_id, item.interval) for item in served if item.series_id in restored_held_ids),
                )
            rows.append(native)
            identity_scope = pair_scope.model_copy(update={"predicates": ()})
            requested_ids = {item.series_id for item in parsed.series if identity_scope.matches(item)}
            for original in parsed.outcomes:
                # Failure facts describe the source limitation, not admitted observations.
                # Keep that context without relaxing physical filtering of successful rows.
                failed = original.status in (
                    OutcomeStatus.FAILED,
                    OutcomeStatus.UNSUPPORTED,
                    OutcomeStatus.UNRESOLVED,
                )
                eligible_ids = requested_ids if failed else selected_ids
                if original.series_id is not None and original.series_id not in eligible_ids:
                    continue
                matching_outcome_facts = (
                    original.facts_ids if failed else tuple(key for key in original.facts_ids if key in selected_facts)
                )
                if original.facts_ids and not matching_outcome_facts:
                    continue
                overlap_start = (
                    original.window.start
                    if original.window.axis is TimeAxis.UTC
                    else max(window.start, original.window.start)
                )
                overlap_end = (
                    original.window.end
                    if original.window.axis is TimeAxis.UTC
                    else min(window.end, original.window.end)
                )
                if overlap_start > overlap_end:
                    continue
                observed_window = SeriesWindow(start=overlap_start, end=overlap_end, axis=original.window.axis)
                observed_interval = RequestedInterval(overlap_start, overlap_end, axis=original.window.axis)
                if original.window.axis is TimeAxis.UTC and original.status in (
                    OutcomeStatus.SUCCESS,
                    OutcomeStatus.EMPTY,
                ):
                    candidate = coverage_native.filter(pl.col("series_id") == original.series_id)
                    if candidate.select(axis_time_expression(TimeAxis.UTC).is_null().any()).item():
                        raise FatalContractError("UTC acquisition rows require published fixed offsets")
                concrete = (
                    coverage_native.filter(
                        (pl.col("series_id") == original.series_id)
                        & pl.col("facts_id").is_in(original.facts_ids)
                        & axis_time_expression(original.window.axis).is_between(
                            overlap_start, overlap_end, closed="both"
                        )
                    )
                    if original.series_id
                    else pl.DataFrame(schema=RowsSchema.polars_schema)
                )
                updates: dict[str, object] = {
                    "window": observed_window,
                    "outcome_id": stable_id(
                        original.outcome_id, observed_window.model_dump_json(), *matching_outcome_facts
                    ),
                    "facts_ids": matching_outcome_facts,
                }
                if original.status in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY):
                    updates["status"] = OutcomeStatus.EMPTY if concrete.is_empty() else OutcomeStatus.SUCCESS
                if original.coverage == "observations":
                    updates["observation_keys"] = tuple(
                        dict.fromkeys(concrete.select("facts_id", "time", "time_zone").iter_rows())
                    )
                outcome = original.model_copy(update=updates)
                outcomes.append(outcome)
                fresh_outcomes.append(outcome)
                if outcome.status in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY):
                    assert outcome.series_id is not None
                    pending.append(
                        SuccessfulReplacement(
                            CoverageInterval(
                                outcome.series_id,
                                observed_interval,
                                outcome.retrieved_at,
                                outcome.outcome_id,
                                outcome.facts_ids,
                            ),
                            concrete,
                            replaced_facts_ids=tuple(
                                dict.fromkeys(
                                    fact.facts_id
                                    for definition in (
                                        *parsed.series,
                                        *(manifest.series if manifest is not None else ()),
                                    )
                                    if definition.series_id == outcome.series_id
                                    for fact in definition.facts
                                    if pair_scope.matches_facts(fact)
                                )
                            ),
                        )
                    )
        if isinstance(fetched, SourceAcquisition):
            reconciled = _reconcile_acquired_inventories(fetched, tuple(transaction_parsed), pair_scope, window)
            inventories.extend(reconciled)
            fresh_inventories.extend(reconciled)
        pair_definitions = tuple(
            item
            for item in definitions.values()
            if item.station_id == station and item.product_id == product and pair_scope.matches(item)
        )
        pair_outcomes = tuple(item for item in outcomes if item.station_id == station and item.product_id == product)
        if pair_scope.restriction is RestrictionKind.ALL and not pair_definitions and not pair_outcomes:
            settled = any(_snapshot_matches(item, pair_scope, window) for item in inventories)
            status = OutcomeStatus.NO_MATCH if settled else OutcomeStatus.UNRESOLVED
            reason = (
                "The acquired source inventory contains no matching series"
                if settled
                else "The acquired inventory cannot settle the requested source scope"
            )
            outcome = RetrievalOutcome(
                outcome_id=stable_id(
                    str(request.provider_id),
                    station,
                    str(product),
                    pair_scope.model_dump_json(),
                    window.model_dump_json(),
                    str(provenance.requested_at),
                ),
                series_id=None,
                station_id=station,
                product_id=str(product),
                window=window,
                status=status,
                reason=reason,
            )
            outcomes.append(outcome)
            fresh_outcomes.append(outcome)
            all_issues.append(
                Issue(
                    severity="warning",
                    code="source.no_match" if settled else "source.inventory_unresolved",
                    message=reason,
                    details={"station_id": station, "product_id": str(product)},
                    provider_id=request.provider_id,
                )
            )
    fresh_outcomes.extend(
        _finite_selector_assessments(
            request.provider_id, finite_assessments, definitions, inventories, outcomes, all_issues
        )
    )
    pending = _combine_replacements(pending, fresh_outcomes, outcomes)
    combined = pl.concat(rows)
    # A rolling publication establishes only its explicit observation keys.
    # Preserve older snapshot rows absent from the new publication, without
    # presenting their dates as reusable interval coverage.
    if manifest is not None and store is not None:
        snapshot_ids = {
            item.series_id
            for item in manifest.outcomes
            if item.coverage == "observations" and item.status in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY)
        }
        held_series = tuple(item for item in manifest.series if item.series_id in snapshot_ids and scope.matches(item))
        if held_series:
            _merge_definitions(definitions, held_series)
            held_read = StoreReader().query(
                StoreQuery(
                    store,
                    request.provider_id,
                    request.stations,
                    request.products,
                    datetime.fromisoformat(request.window.start.isoformat()) - _FETCH_WINDOW_PADDING,
                    datetime.fromisoformat(request.window.end.isoformat()) + _FETCH_WINDOW_PADDING,
                    series_ids=tuple(item.series_id for item in held_series),
                    facts_ids=tuple(
                        fact.facts_id for item in held_series for fact in item.facts if scope.matches_facts(fact)
                    ),
                )
            )
            held_rows = _clip_native(held_read.rows, held_series, request.window).join(
                combined.select("series_id", "facts_id", "time", "time_zone").unique(),
                on=["series_id", "facts_id", "time", "time_zone"],
                how="anti",
            )
            combined = pl.concat([combined, held_rows])
            held_keys = set(held_rows.select("series_id", "facts_id", "time", "time_zone").iter_rows())
            # Outcomes remain immutable acquisition evidence in the store. The
            # last acquired reference owns a currently held observation key.
            attributed: set[tuple[str, str, datetime, str]] = set()
            for item in reversed(manifest.outcomes):
                if item.series_id is None or item.coverage != "observations":
                    continue
                keys = tuple(
                    key
                    for key in item.observation_keys
                    if (item.series_id, *key) in held_keys and (item.series_id, *key) not in attributed
                )
                if not keys:
                    continue
                attributed.update((item.series_id, *key) for key in keys)
                outcomes.append(
                    item.model_copy(
                        update={
                            "outcome_id": stable_id(item.outcome_id, repr(keys)),
                            "observation_keys": keys,
                        }
                    )
                )
            cached_calls.extend(manifest.source_calls)
            if receipts is ReceiptMode.INCLUDE and not held_rows.is_empty():
                receipt_entries.append(encode_store_excerpt(held_read))
    selected, retained_inventories, retained_outcomes = _result_metadata(scope, definitions, inventories, outcomes)
    converted = convert(combined, config, request.window, series=tuple(definitions.values()))
    _require_canonical_rows_within_requested(converted.value, tuple(definitions.values()), request.window)
    enriched = _provenance_with_payload_origins(
        provenance, tuple(payloads), source_series_by_payload=tuple(source_series_by_payload)
    )
    if cached_calls or served:
        enriched = enriched.model_copy(
            update={
                "calls_made": _unique_calls(tuple(cached_calls) + enriched.calls_made),
                "served_intervals": tuple(served),
            }
        )
    if cache != "bypass" and (fresh_outcomes or fresh_inventories or fresh_definitions):
        assert store is not None
        accumulate(
            store,
            request.provider_id,
            StoreUpdate(
                tuple(fresh_definitions.values()),
                tuple(fresh_inventories),
                tuple(fresh_outcomes),
                tuple(pending),
                tuple(all_issues),
                enriched.calls_made,
            ),
        )
    return assemble(
        converted.value,
        enriched,
        tuple(all_issues) + converted.issues,
        Receipts(request.provider_id, tuple(receipt_entries)),
        source_series=selected,
        inventories=retained_inventories,
        outcomes=retained_outcomes,
        scope=scope,
    )


def drive_store(
    request: ObservationRequest,
    config: ProviderConfig,
    store: StoreRoot,
    *,
    provenance: ObservationProvenance,
    receipts: ReceiptMode = ReceiptMode.OMIT,
    reader: StoreReader | None = None,
) -> _AssemblyResult:
    if not isinstance(receipts, ReceiptMode):
        raise TypeError("receipts must be ReceiptMode")
    scope = request.scope or SeriesScope(
        provider_ids=(str(request.provider_id),), station_ids=request.stations, product_ids=tuple(request.products)
    )
    resolved = reader or StoreReader()
    status = resolved.status(store, request.provider_id)
    if not isinstance(status.manifest, StoreManifest):
        raise FatalContractError("Bulk retrieval requires a compiled store")
    manifest = status.manifest
    retired_products = sorted({item.product_id for item in manifest.series} - set(config.products))
    if retired_products:
        raise ObservationStoreRefusedError(
            StoreRefusal(
                StoreRefusalKind.INCOMPATIBLE,
                store,
                request.provider_id,
                f"compiled source products are no longer supported: {', '.join(retired_products)}",
            )
        )
    selected = tuple(item for item in manifest.series if scope.matches(item))
    matching_facts = tuple(
        dict.fromkeys(
            fact.facts_id for definition in selected for fact in definition.facts if scope.matches_facts(fact)
        )
    )
    start = datetime.fromisoformat(request.window.start.isoformat())
    end = datetime.fromisoformat(request.window.end.isoformat())
    if selected:
        read = resolved.query(
            StoreQuery(
                store,
                request.provider_id,
                request.stations,
                request.products,
                start - _FETCH_WINDOW_PADDING,
                end + _FETCH_WINDOW_PADDING,
                series_ids=tuple(item.series_id for item in selected),
                facts_ids=matching_facts,
            )
        )
        native = read.rows
        receipt_entries = () if receipts is ReceiptMode.OMIT else (encode_store_excerpt(read),)
    else:
        native = pl.DataFrame(schema=RowsSchema.polars_schema)
        receipt_entries = ()
    converted = convert(native, config, request.window, series=selected)
    _require_canonical_rows_within_requested(converted.value, selected, request.window)
    # Compilation describes the artifact. These outcomes describe this local
    # query, not a new publisher call or a fresh publisher retrieval instant.
    outcomes: list[RetrievalOutcome] = []
    for definition in selected:
        for axis in ClippingAxis:
            facts = tuple(fact for fact in definition.facts if scope.matches_facts(fact) and fact.clipping_axis is axis)
            if not facts:
                continue
            window = SeriesWindow(
                start=datetime.combine(start.date(), time.min) if axis is ClippingAxis.CALENDAR_DATE else start,
                end=datetime.combine(end.date(), time.max) if axis is ClippingAxis.CALENDAR_DATE else end,
            )
            supported = tuple(fact.facts_id for fact in facts if admission(fact).status == "supported")
            if supported:
                concrete = converted.value.filter(
                    (pl.col("series_id") == definition.series_id) & pl.col("facts_id").is_in(supported)
                )
                outcomes.append(
                    RetrievalOutcome(
                        outcome_id=stable_id(
                            "compiled-query",
                            str(manifest.publisher_artifact.sha256),
                            definition.series_id,
                            *supported,
                            window.model_dump_json(),
                        ),
                        series_id=definition.series_id,
                        station_id=definition.station_id,
                        product_id=definition.product_id,
                        window=window,
                        status=OutcomeStatus.EMPTY if concrete.is_empty() else OutcomeStatus.SUCCESS,
                        facts_ids=supported,
                    )
                )
            unsupported = tuple(fact for fact in facts if admission(fact).status == "unsupported")
            if unsupported:
                outcomes.append(
                    RetrievalOutcome(
                        outcome_id=stable_id(
                            "compiled-query-unsupported",
                            str(manifest.publisher_artifact.sha256),
                            definition.series_id,
                            *(fact.facts_id for fact in unsupported),
                            window.model_dump_json(),
                        ),
                        series_id=definition.series_id,
                        station_id=definition.station_id,
                        product_id=definition.product_id,
                        window=window,
                        status=OutcomeStatus.UNSUPPORTED,
                        facts_ids=tuple(fact.facts_id for fact in unsupported),
                        reason="; ".join(
                            dict.fromkeys(
                                admission(fact).reason or "Physical admission is not established"
                                for fact in unsupported
                            )
                        ),
                    )
                )
    query_issues: list[Issue] = []
    finite_assessments: list[tuple[SeriesScope, SeriesWindow]] = []
    known_identities = {item.series_id: item for item in manifest.series}
    for station in request.stations:
        for product in request.products:
            if scope.restriction is RestrictionKind.EXPLICIT:
                local_ids = tuple(
                    key
                    for key in scope.series_ids
                    if key not in known_identities
                    or (known_identities[key].station_id == station and known_identities[key].product_id == product)
                )
                if scope.series_ids and not local_ids:
                    continue
                pair_scope = _scope_for_pair(scope, str(request.provider_id), station, str(product)).model_copy(
                    update={"series_ids": local_ids}
                )
                interval = _requested_interval(request.window, config.products[product].semantics)
                finite_assessments.append((pair_scope, SeriesWindow(start=interval.start, end=interval.end)))
                continue
            if any(item.station_id == station and item.product_id == product for item in selected):
                continue
            window = SeriesWindow(start=start, end=end)
            complete = any(
                inventory.origin == "compiled"
                and inventory.completeness is InventoryCompleteness.COMPLETE
                and inventory.scope.restriction is RestrictionKind.ALL
                and (not inventory.scope.provider_ids or str(request.provider_id) in inventory.scope.provider_ids)
                and (not inventory.scope.station_ids or station in inventory.scope.station_ids)
                and (not inventory.scope.product_ids or product in inventory.scope.product_ids)
                and set(inventory.scope.predicates).issubset(scope.predicates)
                and (inventory.window is None or inventory.window.start <= start and inventory.window.end >= end)
                for inventory in manifest.inventories
            )
            reason = (
                "The certified local artifact inventory contains no matching source series"
                if complete
                else "The local artifact inventory cannot settle the requested source scope"
            )
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(
                        "compiled-query-scope",
                        str(manifest.publisher_artifact.sha256),
                        station,
                        str(product),
                        scope.model_dump_json(),
                        window.model_dump_json(),
                    ),
                    series_id=None,
                    station_id=station,
                    product_id=str(product),
                    window=window,
                    status=OutcomeStatus.NO_MATCH if complete else OutcomeStatus.UNRESOLVED,
                    reason=reason,
                )
            )
            query_issues.append(
                Issue(
                    severity="warning",
                    code="source.no_match" if complete else "source.inventory_unresolved",
                    message=reason,
                    details={"station_id": station, "product_id": str(product)},
                    provider_id=request.provider_id,
                )
            )
    _finite_selector_assessments(
        request.provider_id,
        finite_assessments,
        known_identities,
        list(manifest.inventories),
        outcomes,
        query_issues,
    )
    provenance = provenance.model_copy(
        update={
            "source_vintage": manifest.source_vintage,
            "publisher_artifact_checksum": str(manifest.publisher_artifact.sha256),
            "publisher_artifact_checksums": tuple(str(item.sha256) for item in manifest.publisher_artifacts),
            "publisher_artifact_urls": tuple(item.url for item in manifest.publisher_artifacts),
            "calls_made": manifest.source_calls,
        }
    )
    return assemble(
        converted.value,
        provenance,
        manifest.issues + converted.issues + tuple(query_issues),
        Receipts(request.provider_id, receipt_entries),
        # Inventory is retained evidence, not a filtered view. Keep all its
        # definitions so restricted exports remain self-contained.
        source_series=manifest.series,
        inventories=manifest.inventories,
        outcomes=tuple(outcomes),
        scope=scope,
    )

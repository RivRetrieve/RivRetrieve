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
from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval, remainder, served_coverage
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
from rivretrieve._internal.transport import (
    AuthenticationCapability,
    HttpClient,
    SecretCallTrace,
    Transport,
    TransportFailure,
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
    }


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
            {**_origin_call(payload.origin), **contexts[index]},
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
            1,
            status_code=response.status_code,
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
        "attempts": None if isinstance(failure, CredentialExchangeError) else failure.attempts,
        "status_code": failure.status_code,
    }
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
                "transport retries were exhausted after a timeout or retryable response"
            ),
            TransportFailureReason.TERMINAL_SENDER_FAILURE: "the transport sender failed terminally",
            TransportFailureReason.REDIRECT_REFUSED: "a credentialed redirect was refused",
            TransportFailureReason.RETAINED_METADATA_UNSAFE: (
                "the response could not be retained without exposing a credential"
            ),
            TransportFailureReason.HTTP_STATUS: "the source returned a non-success HTTP status",
        }[failure.reason]
        status = f" with HTTP status {failure.status_code}" if failure.status_code is not None else ""
        message = (
            f"Provider {provider_id} failed for station {station_id}, product {product_id}: {reason_text}{status}."
        )
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


def _snapshot_matches(snapshot: InventorySnapshot, scope: SeriesScope, window: SeriesWindow) -> bool:
    held = snapshot.scope
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
    observed = tuple(item for parsed in parsed_results for item in parsed.series)
    outcomes = (*acquired.outcomes, *(item for parsed in parsed_results for item in parsed.outcomes))
    reconciled = []
    for snapshot in acquired.inventories:
        if not _snapshot_matches(snapshot, scope, window):
            continue
        reasons: list[str] = []
        members = set(snapshot.members)
        declared_facts = dict(snapshot.member_facts)
        if not members.issubset(declared):
            reasons.append("Acquisition inventory members lack declared physical definitions")
        for item in observed:
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
        if acquired.failed_requests or any(
            outcome.status in (OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED)
            for outcome in outcomes
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
                observed_definition = any(item.series_id == key and fact in item.facts for item in observed)
                acquired_empty = any(
                    item.series_id == key and fact.facts_id in item.facts_ids and item.status is OutcomeStatus.EMPTY
                    for item in acquired.outcomes
                )
                if not observed_definition and not acquired_empty:
                    reasons.append("A matching admitted member lacks a concrete response definition")
                coverage = tuple(
                    RequestedInterval(outcome.window.start, outcome.window.end)
                    for outcome in outcomes
                    if outcome.series_id == key
                    and fact.facts_id in outcome.facts_ids
                    and outcome.status in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY)
                )
                if remainder(RequestedInterval(window.start, window.end), coverage):
                    reasons.append("A matching admitted member lacks successful coverage in this acquisition")
        reason = "; ".join(dict.fromkeys(reasons)) if reasons else None
        evidence = (
            *snapshot.evidence,
            f"source-inventory:{snapshot.snapshot_id}",
            *(f"retrieval-outcome:{outcome.outcome_id}" for outcome in outcomes),
        )
        instants = tuple(
            instant
            for instant in (snapshot.acquired_at, *(outcome.retrieved_at for outcome in outcomes))
            if instant is not None
        )
        reconciled.append(
            InventorySnapshot(
                snapshot_id=stable_id(
                    snapshot.snapshot_id, scope.model_dump_json(), window.model_dump_json(), *evidence, reason
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
                window=window,
                evidence=evidence,
                reason=reason,
            )
        )
    return tuple(reconciled)


def _covered_facts(
    manifest: AccumulatedStoreManifest, definition: SourceSeries, scope: SeriesScope, window: SeriesWindow
) -> bool:
    interval = RequestedInterval(window.start, window.end)
    return all(
        not remainder(
            interval,
            tuple(
                item.interval
                for item in manifest.coverage
                if item.series_id == definition.series_id and fact.facts_id in item.facts_ids
            ),
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
            if snapshot.window is not None and (
                snapshot.window.start > window.start or snapshot.window.end < window.end
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
        if not _covered_facts(manifest, observed, scope, window):
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
    for snapshot in reversed(manifest.inventories):
        held = snapshot.scope
        if snapshot.origin == "catalogue":
            continue
        if snapshot.window is not None and (snapshot.window.start > window.start or snapshot.window.end < window.end):
            continue
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
        interval = RequestedInterval(window.start, window.end)
        outcome_facts = {item.outcome_id: item.facts_ids for item in manifest.outcomes}
        if all(
            not remainder(
                interval,
                tuple(
                    item.interval
                    for item in manifest.coverage
                    if item.series_id == definition.series_id
                    and fact.facts_id in (item.facts_ids or outcome_facts.get(item.outcome_id, ()))
                ),
            )
            for definition in members
            for fact in definition.facts
            if scope.matches_facts(fact) and admission(fact).status == "supported"
        ):
            return _ReusePlan((snapshot,), members)
        return None
    return None


def _overlaps(outcome: RetrievalOutcome, interval: RequestedInterval) -> bool:
    return outcome.window.start <= interval.end and outcome.window.end >= interval.start


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
                if outcome.window.start > window.end or outcome.window.end < window.start:
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
                and (item.window is None or (item.window.start <= window.start and item.window.end >= window.end))
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
    for replacement in replacements:
        key = replacement.coverage.series_id, replacement.coverage.interval
        grouped.setdefault(key, []).append(replacement)
    by_id = {item.outcome_id: item for item in fresh_outcomes}
    combined = []
    for (series_id, interval), parts in grouped.items():
        failed = any(
            item.series_id == series_id
            and item.status not in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY)
            and item.window.start <= interval.end
            and item.window.end >= interval.start
            for item in fresh_outcomes
        )
        if failed:
            continue
        if len(parts) == 1:
            combined.append(parts[0])
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
                        for item in served_coverage(manifest.coverage, key, interval)
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
                if cache != "reuse" or manifest is None or store is None:
                    return
                held_series = tuple(
                    item
                    for item in manifest.series
                    if held_scope.matches(item)
                    and item.series_id not in restored_ids
                    and (not target_ids or item.series_id in target_ids)
                )
                ids = tuple(item.series_id for item in held_series)
                fact_ids = tuple(
                    fact.facts_id for item in held_series for fact in item.facts if held_scope.matches_facts(fact)
                )
                coverage = tuple(
                    item
                    for key in ids
                    for item in served_coverage(manifest.coverage, key, held_interval)
                    if set(item.facts_ids).intersection(fact_ids)
                )
                if not coverage:
                    return
                held_read = StoreReader().query(
                    StoreQuery(
                        store,
                        request.provider_id,
                        (held_station,),
                        (held_product,),
                        held_interval.start,
                        held_interval.end,
                        series_ids=ids,
                        facts_ids=fact_ids,
                    )
                )
                restored_ids.update(ids)
                rows.append(held_read.rows)
                _merge_definitions(definitions, held_series)
                selected_snapshots = tuple(item for item in manifest.inventories if set(item.members).intersection(ids))
                referenced_ids = {key for item in selected_snapshots for key in item.members}
                _merge_definitions(
                    definitions, tuple(item for item in manifest.series if item.series_id in referenced_ids)
                )
                inventories[:0] = list(selected_snapshots)
                outcomes.extend(
                    item for item in manifest.outcomes if item.series_id in ids and _overlaps(item, held_interval)
                )
                served.extend(coverage)
                all_issues.extend(
                    issue
                    for issue in manifest.issues
                    if _issue_in_scope(
                        issue, held_station, str(held_product), ids, interval=held_interval, outcomes=manifest.outcomes
                    )
                )
                cached_calls.extend(
                    _calls_in_scope(manifest, held_station, str(held_product), ids, interval=held_interval)
                )
                if receipts is ReceiptMode.INCLUDE:
                    receipt_entries.append(encode_store_excerpt(held_read))

            if product not in declarations.products:
                raise FatalContractError(f"Missing window declaration for {product}")
            fetch_window = _padded_interval(interval)
            _require_fetch_window_contains_requested(fetch_window, request.window)
            rendered = MappingProxyType({product: plan_windows(fetch_window, declarations.products[product])})
            try:
                fetched = provider.fetch(
                    (station,),
                    (product,),
                    rendered,
                    fetch_window,
                    config,
                    _SourceResponseTransport(resolved_transport),
                    scope=pair_scope,
                    known_series=pair_series,
                )
            except (TransportFailure, CredentialExchangeError) as failure:
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
                        if pair_scope.matches_facts(established[key])
                        and admission(established[key]).status == "supported"
                    )
                    if not pair_scope.matches(definition) or not matching_facts:
                        continue
                    start, end = max(window.start, original.window.start), min(window.end, original.window.end)
                    if start > end:
                        continue
                    empty_outcome = original.model_copy(
                        update={
                            "window": SeriesWindow(start=start, end=end),
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
                                RequestedInterval(start, end),
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
                    retain_held_successes((target.series_id,))
                    _merge_definitions(definitions, (target,))
                    _merge_definitions(fresh_definitions, (target,))
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
                            },
                            "message": issue.message
                            + (f" Source variant: {target.variant}." if target.variant is not None else ""),
                        }
                    )
                    all_issues.append(issue)
                    outcome = RetrievalOutcome(
                        outcome_id=event.event_id,
                        series_id=target.series_id,
                        station_id=target.station_id,
                        product_id=target.product_id,
                        window=window,
                        status=OutcomeStatus.FAILED,
                        reason=issue.message,
                        calls=(event.event_id,),
                    )
                    outcomes.append(outcome)
                    fresh_outcomes.append(outcome)
                    cached_calls.append(
                        {
                            "call_id": event.event_id,
                            "station_id": target.station_id,
                            "product_id": target.product_id,
                            "series_id": target.series_id,
                            "url": event.request.url,
                            "request_parameters": dict(event.request.params or {}),
                            "status_code": event.failure.status_code,
                            "retrieved_at": _origin_value(UnknownOriginFact()),
                        }
                    )
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
            for received in fetched.value:
                payload = replace(
                    received, scope=received.scope or pair_scope, known_series=received.known_series or pair_series
                )
                payloads.append(payload)
                if receipts is ReceiptMode.INCLUDE:
                    receipt_entries.append(
                        ReceiptEntry(payload.content, payload.origin, ReceiptAuthorship.PUBLISHER_PAYLOAD)
                    )
                parsed = provider.parse(payload, config)
                if not isinstance(parsed, ParsedSeries):
                    raise FatalContractError("Provider parse must return ParsedSeries")
                _validate_parsed_series(parsed)
                validate_native_rows(parsed.rows, config.products, series=parsed.series)
                transaction_parsed.append(parsed)
                source_series_by_payload.append(tuple(item.series_id for item in parsed.series))
                _merge_definitions(definitions, parsed.series)
                _merge_definitions(fresh_definitions, parsed.series)
                acquired_facts = {item.series_id: tuple(fact.facts_id for fact in item.facts) for item in parsed.series}
                acquired_snapshots = []
                for original_snapshot in parsed.inventories:
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
                native = native.filter(
                    pl.col("series_id").is_in(selected_ids) & pl.col("facts_id").is_in(selected_facts)
                )
                if isinstance(fetched, SourceAcquisition):
                    unsupported = tuple(
                        item.series_id
                        for item in fetched.outcomes
                        if item.series_id is not None and item.status is OutcomeStatus.UNSUPPORTED
                    )
                    # Transaction-level contradictions can span individually valid pages.
                    # Keep their receipts and diagnostics, not ambiguous numeric rows.
                    if unsupported:
                        native = native.filter(~pl.col("series_id").is_in(unsupported))
                rows.append(native)
                failed_ids = {
                    item.series_id
                    for item in parsed.outcomes
                    if item.series_id is not None
                    and item.status in (OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED)
                }
                if isinstance(fetched, SourceAcquisition):
                    failed_ids.update(
                        item.series_id
                        for item in fetched.outcomes
                        if item.series_id is not None and item.status is OutcomeStatus.UNSUPPORTED
                    )
                if (
                    any(
                        item.series_id is None
                        and item.status in (OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED)
                        for item in parsed.outcomes
                    )
                    and manifest is not None
                ):
                    failed_ids.update(item.series_id for item in manifest.series if pair_scope.matches(item))
                failed_ids.difference_update(native.get_column("series_id").to_list())
                if failed_ids:
                    retain_held_successes(tuple(sorted(failed_ids)))
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
                        original.facts_ids
                        if failed
                        else tuple(key for key in original.facts_ids if key in selected_facts)
                    )
                    if original.facts_ids and not matching_outcome_facts:
                        continue
                    overlap_start = max(window.start, original.window.start)
                    overlap_end = min(window.end, original.window.end)
                    if overlap_start > overlap_end:
                        continue
                    observed_window = SeriesWindow(start=overlap_start, end=overlap_end)
                    observed_interval = RequestedInterval(overlap_start, overlap_end)
                    concrete = (
                        native.filter(
                            (pl.col("series_id") == original.series_id)
                            & pl.col("facts_id").is_in(original.facts_ids)
                            & pl.col("time").is_between(overlap_start, overlap_end, closed="both")
                        )
                        if original.series_id
                        else pl.DataFrame(schema=RowsSchema.polars_schema)
                    )
                    updates = {
                        "window": observed_window,
                        "outcome_id": stable_id(
                            original.outcome_id, observed_window.model_dump_json(), *matching_outcome_facts
                        ),
                        "facts_ids": matching_outcome_facts,
                    }
                    if original.status in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY):
                        updates["status"] = OutcomeStatus.EMPTY if concrete.is_empty() else OutcomeStatus.SUCCESS
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
            pair_outcomes = tuple(
                item for item in outcomes if item.station_id == station and item.product_id == product
            )
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
    selected, retained_inventories, retained_outcomes = _result_metadata(scope, definitions, inventories, outcomes)
    converted = convert(combined, config, request.window, series=tuple(definitions.values()))
    _require_canonical_rows_within_requested(converted.value, tuple(definitions.values()), request.window)
    enriched = _provenance_with_payload_origins(
        provenance, tuple(payloads), source_series_by_payload=tuple(source_series_by_payload)
    )
    if cached_calls or served:
        enriched = enriched.model_copy(
            update={"calls_made": tuple(cached_calls) + enriched.calls_made, "served_intervals": tuple(served)}
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

"""drive : ObservationRequest × ProviderStages × ObservationProvenance × ReceiptMode × Transport × CredentialVariableNames → _AssemblyResult; route_window_declarations : ProviderStages × Transport → ProductWindowDeclarations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Protocol, assert_never, runtime_checkable

import polars as pl

from rivretrieve._internal.assembly import _AssemblyResult, assemble
from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.conversion import convert
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
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.store import StoreQuery, StoreReader, StoreRoot
from rivretrieve._internal.store.receipts import encode_store_excerpt
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
    config: ProviderConfig,
    requested_window: RequestedWindow,
) -> None:
    requested_start = datetime.fromisoformat(requested_window.start.isoformat())
    requested_end = datetime.fromisoformat(requested_window.end.isoformat())
    requested_start_date = requested_window.start.date
    requested_end_date = requested_window.end.date
    for index, row in enumerate(rows.iter_rows(named=True)):
        product_id = ProductId(row["product_id"])
        semantics = config.products[product_id].semantics
        timestamp = row["time"]
        if isinstance(semantics, Daily):
            if requested_start_date <= timestamp.date().isoformat() <= requested_end_date:
                continue
            raise FatalContractError(
                f"CanonicalRows zero-based row index {index} is outside RequestedWindow on the Daily "
                f"date axis: timestamp={timestamp.isoformat()}, time_zone={row['time_zone']!r}, "
                f"station_id={row['station_id']!r}, product_id={row['product_id']!r}, "
                f"requested_start_date={requested_start_date}, requested_end_date={requested_end_date}. "
                "This is a convert-stage contract breach; please report this row and request window."
            )
        elif isinstance(semantics, (Hourly, Instant, UnknownTemporalSupport)):
            if requested_start <= timestamp <= requested_end:
                continue
            if isinstance(semantics, Hourly):
                axis = "Hourly label"
            elif isinstance(semantics, Instant):
                axis = "Instant timestamp"
            else:
                axis = "source time-label"
            raise FatalContractError(
                f"CanonicalRows zero-based row index {index} is outside RequestedWindow on the {axis} "
                f"axis: timestamp={timestamp.isoformat()}, time_zone={row['time_zone']!r}, "
                f"station_id={row['station_id']!r}, product_id={row['product_id']!r}, "
                f"requested_start={requested_start.isoformat()}, requested_end={requested_end.isoformat()}. "
                "This is a convert-stage contract breach; please report this row and request window."
            )
        else:
            assert_never(semantics)


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
        "ordinary_headers": dict(call.ordinary_headers),
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
    calls = tuple(
        call
        for payload in payloads
        for call in (*(_secret_call(item) for item in payload.prerequisite_calls), _origin_call(payload.origin))
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
    failure: TransportFailure,
    credential_names: tuple[str, ...],
) -> Issue:
    """source failure classification : Series × TransportFailure × CredentialNames → Issue."""
    details: dict[str, object] = {
        "station_id": station_id,
        "product_id": str(product_id),
        "failure_reason": failure.reason.value,
        "attempts": failure.attempts,
        "status_code": failure.status_code,
    }
    if failure.status_code == 404:
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
    ) -> WithIssues[tuple[Payload, ...]]: ...

    @staticmethod
    def parse(
        payload: Payload,
        config: ProviderConfig,
    ) -> WithIssues[Rows]: ...


@runtime_checkable
class TransportWindowDeclarationProvider(Protocol):
    """Select source window semantics from an engine-supplied transport capability."""

    @staticmethod
    def window_declarations_for_transport(transport: Transport) -> ProductWindowDeclarations: ...


def drive(
    request: ObservationRequest,
    provider: ProviderStages,
    *,
    provenance: ObservationProvenance,
    receipts: ReceiptMode = ReceiptMode.OMIT,
    transport: Transport | None = None,
    credential_names: tuple[str, ...] = (),
) -> _AssemblyResult:
    if receipts not in (ReceiptMode.OMIT, ReceiptMode.INCLUDE) or not isinstance(receipts, ReceiptMode):
        raise TypeError("receipts must be ReceiptMode.OMIT or ReceiptMode.INCLUDE")
    config = provider.config
    requested_start = request.window.start
    requested_end = request.window.end
    fetch_window = _make_fetch_window(
        WindowEndpoint.from_datetime(
            datetime(
                requested_start.year,
                requested_start.month,
                requested_start.day,
                requested_start.hour,
                requested_start.minute,
                requested_start.second,
                requested_start.microsecond,
            )
            - _FETCH_WINDOW_PADDING
        ),
        WindowEndpoint.from_datetime(
            datetime(
                requested_end.year,
                requested_end.month,
                requested_end.day,
                requested_end.hour,
                requested_end.minute,
                requested_end.second,
                requested_end.microsecond,
            )
            + _FETCH_WINDOW_PADDING
        ),
    )
    _require_fetch_window_contains_requested(fetch_window, request.window)
    resolved_transport = HttpClient() if transport is None else transport
    declarations = (
        provider.window_declarations_for_transport(resolved_transport)
        if isinstance(provider, TransportWindowDeclarationProvider)
        else provider.window_declarations
    )
    planned: dict[ProductId, tuple[RenderedWindow, ...]] = {}
    for product_id in request.products:
        try:
            declaration = declarations.products[product_id]
        except KeyError as error:
            raise FatalContractError(
                f"Provider {request.provider_id} has no window declaration for requested product {product_id}; "
                "this is an internal provider contract breach before fetch."
            ) from error
        planned[product_id] = plan_windows(fetch_window, declaration)
    fetched_payloads: list[Payload] = []
    fetch_issues: list[Issue] = []
    for station_id in request.stations:
        for product_id in request.products:
            rendered_windows = MappingProxyType({product_id: planned[product_id]})
            try:
                fetched = provider.fetch(
                    (station_id,),
                    (product_id,),
                    rendered_windows,
                    fetch_window,
                    config,
                    _SourceResponseTransport(resolved_transport),
                )
            except TransportFailure as failure:
                fetch_issues.append(
                    _source_failure_issue(
                        request.provider_id,
                        station_id,
                        product_id,
                        failure,
                        credential_names,
                    )
                )
                continue
            fetch_issues.extend(fetched.issues)
            fetched_payloads.extend(fetched.value)

    payloads = tuple(fetched_payloads)
    parsed: list[WithIssues[Rows]] = []
    receipt_entries: list[ReceiptEntry] = []
    for payload in payloads:
        if receipts is ReceiptMode.INCLUDE:
            receipt_entries.append(
                ReceiptEntry(
                    content=payload.content,
                    origin=payload.origin,
                    authorship=ReceiptAuthorship.PUBLISHER_PAYLOAD,
                )
            )
        parsed_payload = provider.parse(payload, config)
        validate_catalogue(parsed_payload.value, RowsSchema, on_issue="raise")
        parsed.append(parsed_payload)
    rows = pl.concat([result.value for result in parsed] + [pl.DataFrame(schema=RowsSchema.polars_schema)])
    converted = convert(rows, config, request.window)
    validate_catalogue(converted.value, CanonicalRowsSchema, on_issue="raise")
    _require_canonical_rows_within_requested(converted.value, config, request.window)
    issues = tuple(fetch_issues) + tuple(issue for result in parsed for issue in result.issues) + converted.issues
    receipt_payload = Receipts(provider_id=request.provider_id, entries=tuple(receipt_entries))
    enriched_provenance = _provenance_with_payload_origins(provenance, payloads)
    return assemble(converted.value, enriched_provenance, issues, receipt_payload)


def drive_store(
    request: ObservationRequest,
    config: ProviderConfig,
    store: StoreRoot,
    *,
    provenance: ObservationProvenance,
    receipts: ReceiptMode = ReceiptMode.OMIT,
    reader: StoreReader | None = None,
) -> _AssemblyResult:
    """Query a compiled store, then run the shared convert and assemble stages."""
    if receipts not in (ReceiptMode.OMIT, ReceiptMode.INCLUDE) or not isinstance(receipts, ReceiptMode):
        raise TypeError("receipts must be ReceiptMode.OMIT or ReceiptMode.INCLUDE")
    requested_start = datetime.fromisoformat(request.window.start.isoformat())
    requested_end = datetime.fromisoformat(request.window.end.isoformat())
    read = (reader or StoreReader()).query(
        StoreQuery(
            store=store,
            provider_id=request.provider_id,
            stations=request.stations,
            products=request.products,
            start=requested_start - _FETCH_WINDOW_PADDING,
            end=requested_end + _FETCH_WINDOW_PADDING,
        )
    )
    validate_catalogue(read.rows, RowsSchema, on_issue="raise")
    converted = convert(read.rows, config, request.window)
    validate_catalogue(converted.value, CanonicalRowsSchema, on_issue="raise")
    _require_canonical_rows_within_requested(converted.value, config, request.window)
    store_provenance = provenance.model_copy(
        update={
            "source_vintage": read.manifest.source_vintage,
            "publisher_artifact_checksum": str(read.manifest.publisher_artifact.sha256),
            "publisher_artifact_checksums": tuple(
                str(artifact.sha256) for artifact in read.manifest.publisher_artifacts
            ),
            "publisher_artifact_urls": tuple(artifact.url for artifact in read.manifest.publisher_artifacts),
        }
    )
    receipt_entries = () if receipts is ReceiptMode.OMIT else (encode_store_excerpt(read),)
    receipt_payload = Receipts(provider_id=request.provider_id, entries=receipt_entries)
    return assemble(converted.value, store_provenance, converted.issues, receipt_payload)

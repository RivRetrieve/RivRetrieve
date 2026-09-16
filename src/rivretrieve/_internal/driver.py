"""drive : ObservationRequest × ProviderStages × ObservationProvenance × ReceiptMode × Transport × CredentialVariableNames × CacheMode × StoreRoot → _AssemblyResult × StoreEffects; route_window_declarations : ProviderStages × Transport → ProductWindowDeclarations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from types import MappingProxyType
from typing import Protocol, assert_never, runtime_checkable

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
from rivretrieve._internal.store import StoreQuery, StoreReader, StoreRoot
from rivretrieve._internal.store.accumulation import accumulate
from rivretrieve._internal.store.receipts import encode_store_excerpt
from rivretrieve._internal.store.validation import AccumulatedStoreManifest, StoreManifest
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
    if receipts not in (ReceiptMode.OMIT, ReceiptMode.INCLUDE) or not isinstance(receipts, ReceiptMode):
        raise TypeError("receipts must be ReceiptMode.OMIT or ReceiptMode.INCLUDE")
    if cache not in ("bypass", "reuse", "refresh"):
        raise ValueError("cache must be bypass, reuse, or refresh")
    if cache != "bypass" and store is None:
        raise FatalContractError("Caching requires a resolved store path from the public entry point")
    config = provider.config
    requested = {
        product: _requested_interval(request.window, config.products[product].semantics if cache != "bypass" else None)
        for product in request.products
    }
    held: tuple[CoverageInterval, ...] = ()
    served: list[CoverageInterval] = []
    row_frames: list[Rows] = [pl.DataFrame(schema=RowsSchema.polars_schema)]
    receipt_entries: list[ReceiptEntry] = []
    if cache != "bypass":
        assert store is not None
        status = StoreReader().status(store, request.provider_id)
        if status.manifest is not None:
            if not isinstance(status.manifest, AccumulatedStoreManifest):
                raise FatalContractError(f'Expected an accumulated store at "{store}"')
            if cache == "reuse":
                held = status.manifest.coverage
                for station in request.stations:
                    for product, interval in requested.items():
                        served.extend(served_coverage(held, station, product, interval))
                if served:
                    read = StoreReader().query(
                        StoreQuery(
                            store,
                            request.provider_id,
                            request.stations,
                            request.products,
                            min(interval.start for interval in requested.values()),
                            max(interval.end for interval in requested.values()),
                        )
                    )
                    predicate = pl.any_horizontal(
                        [
                            (pl.col("product") == product) & pl.col("time").is_between(interval.start, interval.end)
                            for product, interval in requested.items()
                        ]
                    )
                    physical = read.physical_rows.filter(predicate)
                    rows = physical.select(
                        "station_id", pl.col("product").alias("product_id"), "time", "value", "time_zone"
                    )
                    read = replace(
                        read,
                        physical_rows=physical,
                        rows=rows,
                        optimized_plan=read.optimized_plan + "\nFILTER " + str(predicate),
                    )
                    row_frames.append(rows)
                    if receipts is ReceiptMode.INCLUDE:
                        receipt_entries.append(encode_store_excerpt(read))
    resolved_transport = HttpClient() if transport is None else transport
    declarations = (
        provider.window_declarations_for_transport(resolved_transport)
        if isinstance(provider, TransportWindowDeclarationProvider)
        else provider.window_declarations
    )
    for product_id in request.products:
        if product_id not in declarations.products:
            raise FatalContractError(
                f"Provider {request.provider_id} has no window declaration for requested product {product_id}; "
                "this is an internal provider contract breach before fetch."
            )
    fetch_windows: dict[RequestedInterval, FetchWindow] = {}
    planned_windows: dict[tuple[ProductId, RequestedInterval], tuple[RenderedWindow, ...]] = {}
    fetched_series: list[tuple[str, ProductId, RequestedInterval, WithIssues[tuple[Payload, ...]]]] = []
    fetched_payloads: list[Payload] = []
    all_issues: list[Issue] = []
    pending_writes: list[tuple[Rows, CoverageInterval]] = []
    failed_series: set[tuple[str, ProductId]] = set()
    for station_id in request.stations:
        for product_id in request.products:
            declaration = declarations.products[product_id]
            intervals = (
                remainder(
                    requested[product_id],
                    tuple(c.interval for c in served if c.station_id == station_id and c.product_id == product_id),
                )
                if cache == "reuse"
                else (requested[product_id],)
            )
            for interval in intervals:
                if interval not in fetch_windows:
                    fetch_windows[interval] = _padded_interval(interval)
                fetch_window = fetch_windows[interval]
                interval_window = RequestedWindow(
                    WindowEndpoint.from_datetime(interval.start), WindowEndpoint.from_datetime(interval.end)
                )
                _require_fetch_window_contains_requested(fetch_window, interval_window)
                key = (product_id, interval)
                if key not in planned_windows:
                    planned_windows[key] = plan_windows(fetch_window, declaration)
                rendered_windows = MappingProxyType({product_id: planned_windows[key]})
                try:
                    fetched = provider.fetch(
                        (station_id,),
                        (product_id,),
                        rendered_windows,
                        fetch_window,
                        config,
                        _SourceResponseTransport(resolved_transport),
                    )
                except (TransportFailure, CredentialExchangeError) as failure:
                    failed_series.add((station_id, product_id))
                    all_issues.append(
                        _source_failure_issue(
                            request.provider_id,
                            station_id,
                            product_id,
                            failure,
                            credential_names,
                        )
                    )
                    continue
                all_issues.extend(fetched.issues)
                fetched_payloads.extend(fetched.value)
                fetched_series.append((station_id, product_id, interval, fetched))
    for station_id, product_id, interval, fetched in fetched_series:
        series_issues: list[Issue] = []
        parsed: list[Rows] = [pl.DataFrame(schema=RowsSchema.polars_schema)]
        for payload in fetched.value:
            if receipts is ReceiptMode.INCLUDE:
                receipt_entries.append(
                    ReceiptEntry(
                        content=payload.content,
                        origin=payload.origin,
                        authorship=ReceiptAuthorship.PUBLISHER_PAYLOAD,
                    )
                )
            result = provider.parse(payload, config)
            validate_catalogue(result.value, RowsSchema, on_issue="raise")
            parsed.append(result.value)
            series_issues.extend(result.issues)
        rows = pl.concat(parsed)
        if cache != "bypass":
            validate_native_rows(rows, config.products)
            unexpected = rows.filter((pl.col("station_id") != station_id) | (pl.col("product_id") != product_id))
            if not unexpected.is_empty():
                raise FatalContractError("Parse output contains rows outside the fetched station-product series")
            rows = rows.filter(
                (pl.col("station_id") == station_id)
                & (pl.col("product_id") == product_id)
                & pl.col("time").is_between(interval.start, interval.end)
            )
            if any(issue.severity == "error" for issue in (*fetched.issues, *series_issues)):
                failed_series.add((station_id, product_id))
            else:
                retrieved = tuple(
                    p.origin.retrieved_at for p in fetched.value if isinstance(p.origin.retrieved_at, datetime)
                )
                retrieved_at = max(retrieved) if retrieved else datetime.now(UTC)
                assert store is not None
                pending_writes.append((rows, CoverageInterval(station_id, product_id, interval, retrieved_at)))
        row_frames.append(rows)
        all_issues.extend(series_issues)
    rows = pl.concat(row_frames)
    converted = convert(rows, config, request.window)
    validate_catalogue(converted.value, CanonicalRowsSchema, on_issue="raise")
    _require_canonical_rows_within_requested(converted.value, config, request.window)
    for native_rows, coverage in pending_writes:
        if (coverage.station_id, coverage.product_id) not in failed_series:
            assert store is not None
            accumulate(store, request.provider_id, native_rows, coverage)
    receipt_payload = Receipts(provider_id=request.provider_id, entries=tuple(receipt_entries))
    enriched_provenance = _provenance_with_payload_origins(provenance, tuple(fetched_payloads))
    if served:
        enriched_provenance = enriched_provenance.model_copy(update={"served_intervals": tuple(served)})
    return assemble(converted.value, enriched_provenance, tuple(all_issues) + converted.issues, receipt_payload)


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
    if not isinstance(read.manifest, StoreManifest):
        raise FatalContractError(f'Expected a compiled store at "{store}"')
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

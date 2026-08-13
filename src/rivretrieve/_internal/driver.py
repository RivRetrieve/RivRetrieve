"""drive : ObservationRequest × ProviderStages × ObservationProvenance × ReceiptMode → _AssemblyResult."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Protocol, assert_never

import polars as pl

from rivretrieve._internal.assembly import _AssemblyResult, assemble
from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.conversion import convert
from rivretrieve._internal.engine import (
    CanonicalRows,
    CanonicalRowsSchema,
    Daily,
    FetchWindow,
    Instant,
    ObservationRequest,
    Payload,
    ProductWindowDeclarations,
    ProviderConfig,
    RenderedWindow,
    RequestedWindow,
    Rows,
    RowsSchema,
    WindowEndpoint,
    WithIssues,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import (
    ObservationProvenance,
    ReceiptAuthorship,
    ReceiptEntry,
    ReceiptMode,
    Receipts,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.store import StoreQuery, StoreReader, StoreRoot
from rivretrieve._internal.store.receipts import encode_store_excerpt
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
        elif isinstance(semantics, Instant):
            if requested_start <= timestamp <= requested_end:
                continue
            raise FatalContractError(
                f"CanonicalRows zero-based row index {index} is outside RequestedWindow on the Instant "
                f"timestamp axis: timestamp={timestamp.isoformat()}, time_zone={row['time_zone']!r}, "
                f"station_id={row['station_id']!r}, product_id={row['product_id']!r}, "
                f"requested_start={requested_start.isoformat()}, requested_end={requested_end.isoformat()}. "
                "This is a convert-stage contract breach; please report this row and request window."
            )
        else:
            assert_never(semantics)


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
    ) -> WithIssues[tuple[Payload, ...]]: ...

    @staticmethod
    def parse(
        payload: Payload,
        config: ProviderConfig,
    ) -> WithIssues[Rows]: ...


def drive(
    request: ObservationRequest,
    provider: ProviderStages,
    *,
    provenance: ObservationProvenance,
    receipts: ReceiptMode = ReceiptMode.OMIT,
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
    planned: dict[ProductId, tuple[RenderedWindow, ...]] = {}
    for product_id in request.products:
        try:
            declaration = provider.window_declarations.products[product_id]
        except KeyError as error:
            raise FatalContractError(
                f"Provider {request.provider_id} has no window declaration for requested product {product_id}; "
                "this is an internal provider contract breach before fetch."
            ) from error
        planned[product_id] = plan_windows(fetch_window, declaration)
    rendered_windows = MappingProxyType(dict(planned))
    fetched = provider.fetch(request.stations, request.products, rendered_windows, fetch_window, config)
    parsed: list[WithIssues[Rows]] = []
    receipt_entries: list[ReceiptEntry] = []
    for payload in fetched.value:
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
    issues = fetched.issues + tuple(issue for result in parsed for issue in result.issues) + converted.issues
    receipt_payload = Receipts(provider_id=request.provider_id, entries=tuple(receipt_entries))
    return assemble(converted.value, provenance, issues, receipt_payload)


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
        }
    )
    receipt_entries = () if receipts is ReceiptMode.OMIT else (encode_store_excerpt(read),)
    receipt_payload = Receipts(provider_id=request.provider_id, entries=receipt_entries)
    return assemble(converted.value, store_provenance, converted.issues, receipt_payload)

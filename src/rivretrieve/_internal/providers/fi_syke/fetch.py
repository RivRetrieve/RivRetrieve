"""Acquire SYKE Hydrologiarajapinta OData observation pages, following nextLink."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit  # noqa: TID251 - URL validation only; no network access
from uuid import uuid4

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCallOrigin,
    UnknownOriginFact,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.fi_syke.config import FiSykeSourceCoordinates
from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget, attempt_request
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)

_BASE_URL = "https://rajapinnat.ymparisto.fi/api/Hydrologiarajapinta/1.1/odata"


def _request(native_table: str, station: str, rendered: RenderedWindow) -> TransportRequest:
    if rendered.stop is None:
        raise FatalContractError("fi_syke requires a rendered window with an explicit stop")
    # Never $top: that suppresses odata.nextLink entirely (confirmed live,
    # 2026-11-08), which would silently truncate a long range to 500 rows.
    filt = f"Paikka_Id eq {station} and Aika ge datetime'{rendered.start}' and Aika le datetime'{rendered.stop}'"
    return TransportRequest(
        method=HttpMethod.GET,
        url=f"{_BASE_URL}/{native_table}",
        params={"$filter": filt, "$orderby": "Aika asc"},
    )


def _next_request(
    content: bytes, initial: TransportRequest, visited: set[tuple[tuple[str, str], ...]]
) -> TransportRequest | None:
    """Follow one page's odata.nextLink, never trusting it beyond its own origin, path and filter."""
    try:
        document = json.loads(content)
    except (ValueError, UnicodeDecodeError) as error:
        raise UnsupportedSourceStructureError("fi_syke observation response is not valid JSON") from error
    if not isinstance(document, dict) or not isinstance(document.get("value"), list):
        raise UnsupportedSourceStructureError("fi_syke observation response must be a JSON object with a value array")
    link = document.get("odata.nextLink")
    if link is None:
        return None
    if not isinstance(link, str) or not link:
        raise UnsupportedSourceStructureError("fi_syke odata.nextLink is present but not a non-empty string")
    parsed = urlsplit(link)
    expected = urlsplit(initial.url)
    if (parsed.scheme, parsed.netloc, parsed.path) != (
        expected.scheme,
        expected.netloc,
        expected.path,
    ) or parsed.fragment:
        raise UnsupportedSourceStructureError("fi_syke odata.nextLink changes publisher origin or entity set")
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    params = dict(pairs)
    base = {key: str(value) for key, value in (initial.params or {}).items()}
    if len(pairs) != len(params) or set(params) != set(base) | {"$skip"} or not params.get("$skip"):
        raise UnsupportedSourceStructureError("fi_syke odata.nextLink has malformed paging or query parameters")
    if any(params.get(key) != value for key, value in base.items()):
        raise UnsupportedSourceStructureError("fi_syke odata.nextLink changes request filters")
    identity = tuple(sorted(params.items()))
    if identity in visited:
        raise UnsupportedSourceStructureError("fi_syke pagination cycle")
    visited.add(identity)
    return TransportRequest(
        method=HttpMethod.GET, url=f"{expected.scheme}://{expected.netloc}{expected.path}", params=params
    )


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
) -> SourceAcquisition:
    """Fetch each station-product's whole rendered window, paging via odata.nextLink.

    Each page becomes its own Payload (matching usgs_nwis's cursor-chain
    convention); the driver merges rows across pages normally. No prerequisite
    lookup call is needed, unlike au_bom's getTimeseriesList: the catalogue
    (#754) already pins each station to exactly one product's native table.
    """
    if not stations or not products:
        raise FatalContractError("fi_syke fetch requires at least one station and product")

    window = SeriesWindow(
        start=datetime.fromisoformat(fetch_window.start.isoformat()),
        end=datetime.fromisoformat(fetch_window.end.isoformat()),
    )
    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []

    for station in stations:
        for product in products:
            if product not in config.products:
                raise FatalContractError(f"fi_syke product is absent from provider config: {product}")
            coords = config.products[product].coordinates.value
            if not isinstance(coords, FiSykeSourceCoordinates):
                raise FatalContractError(f"fi_syke product has invalid source coordinates: {product}")
            windows = rendered_windows.get(product, ())
            if len(windows) != 1:
                raise FatalContractError(f"fi_syke product requires exactly one rendered window: {product}")
            initial = _request(coords.native_table, station, windows[0])
            request: TransportRequest | None = initial
            visited: set[tuple[tuple[str, str], ...]] = set()
            while request is not None:
                response = attempt_request(transport, request)
                if isinstance(response, (TransportFailure, CredentialExchangeError)):
                    failures.append(
                        FailedSourceRequest(
                            uuid4().hex,
                            _request_target(station, product, known_series),
                            window,
                            request,
                            response,
                        )
                    )
                    break
                payloads.append(
                    Payload(
                        source_coordinates=config.products[product].coordinates,
                        station_products=((station, product),),
                        fetch_window=fetch_window,
                        content=response.content,
                        origin=_origin(response),
                        prerequisite_calls=response.prerequisite_calls,
                        scope=scope,
                        known_series=known_series,
                        attempt_traces=response.attempt_traces,
                    )
                )
                try:
                    request = _next_request(response.content, initial, visited)
                except UnsupportedSourceStructureError:
                    # Parse independently classifies this payload's own content;
                    # a malformed nextLink stops paging without discarding it.
                    break

    return SourceAcquisition(value=tuple(payloads), failed_requests=tuple(failures))


def _request_target(
    station: str, product: ProductId, known_series: tuple[SourceSeries, ...]
) -> SourceSeries | SourceRequestTarget:
    matching = tuple(item for item in known_series if item.station_id == station and item.product_id == str(product))
    if len(matching) == 1:
        return matching[0]
    return SourceRequestTarget(station, str(product))


def _origin(response: TransportResponse) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=response.url,
        request_parameters=response.request_parameters,
        status_code=response.status_code,
        retrieved_at=response.retrieved_at,
        content_type=response.content_type if response.content_type is not None else UnknownOriginFact(),
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
        attempts=response.attempts,
    )

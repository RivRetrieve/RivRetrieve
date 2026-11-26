"""Acquire Rijkswaterstaat DDAPI 2.0 observations via POST OphalenWaarnemingen."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from uuid import uuid4

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.nl_rws.config import NlRwsProductCoordinates
from rivretrieve._internal.providers.nl_rws.series import (
    PRODUCT_BY_ID,
    PROVIDER_ID,
    WAARNEMINGEN_EVIDENCE,
    build_physical_facts,
)
from rivretrieve._internal.source_acquisition import FailedSourceRequest, attempt_request
from rivretrieve._internal.source_series import (
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    stable_id,
)
from rivretrieve._internal.transport import (
    HttpMethod,
    ReplaySafety,
    Transport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)

_OBSERVATIONS_URL = "https://ddapi20-waterwebservices.rijkswaterstaat.nl/ONLINEWAARNEMINGENSERVICES/OphalenWaarnemingen"


def _coordinates(product: ProductId, config: ProviderConfig) -> NlRwsProductCoordinates:
    value = config.products[product].coordinates.value
    if not isinstance(value, NlRwsProductCoordinates):
        raise FatalContractError(f"nl_rws product {product!r} has unexpected coordinates: {value!r}")
    return value


def _format_ddapi_instant(endpoint: WindowEndpoint) -> str:
    return (
        f"{endpoint.year:04d}-{endpoint.month:02d}-{endpoint.day:02d}"
        f"T{endpoint.hour:02d}:{endpoint.minute:02d}:{endpoint.second:02d}"
        f".{endpoint.microsecond // 1000:03d}+01:00"
    )


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


def _build_request(
    *,
    station: str,
    coords: NlRwsProductCoordinates,
    start: WindowEndpoint,
    stop: WindowEndpoint,
    include_wbw: bool,
) -> TransportRequest:
    aquo_metadata: dict[str, object] = {
        "Compartiment": {"Code": "OW"},
        "Grootheid": {"Code": coords.grootheid},
        "Eenheid": {"Code": coords.eenheid},
        "Hoedanigheid": {"Code": coords.hoedanigheid},
        "ProcesType": "meting",
    }
    if include_wbw:
        aquo_metadata["WaardeBewerkingsMethode"] = {"Code": coords.waarde_bewerkings_methode}
    payload = {
        "Locatie": {"Code": station},
        "AquoPlusWaarnemingMetadata": {"AquoMetadata": aquo_metadata},
        "Periode": {
            "Begindatumtijd": _format_ddapi_instant(start),
            "Einddatumtijd": _format_ddapi_instant(stop),
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return TransportRequest(
        method=HttpMethod.POST,
        url=_OBSERVATIONS_URL,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        body=body,
        replay_safety=ReplaySafety.SAFE,
    )


def _failure_series(station: str, product: ProductId, known_series: tuple[SourceSeries, ...]) -> SourceSeries:
    for item in known_series:
        if item.station_id == station and item.product_id == str(product):
            return item
    definition = PRODUCT_BY_ID[str(product)]
    facts = build_physical_facts(definition, time_zone_offset=None, facts_id=str(product))
    return SourceSeries(
        series_id=stable_id("nl_rws_failed_series", station, str(product)),
        provider_id=PROVIDER_ID,
        station_id=station,
        product_id=str(product),
        identity=SourceIdentity(
            namespace=f"nl_rws/{product}",
            origin="catalogue",
            description=f"Rijkswaterstaat DDAPI 2.0 request target {definition.native_id}",
            evidence=(WAARNEMINGEN_EVIDENCE,),
        ),
        facts=(facts,),
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
    """Fetch DDAPI 2.0 observations with ProcesType='meting' and adaptive NVT+GEM24H co-acquisition."""
    coords_by_product = {product: _coordinates(product, config) for product in products}

    # Group products that share both (Grootheid, Eenheid, Hoedanigheid) and identical rendered windows
    # so NVT + GEM24H on matching short windows co-acquire in a single POST.
    grouped_products: dict[tuple[tuple[str, str, str], tuple[RenderedWindow, ...]], list[ProductId]] = {}
    for product in products:
        group_key = (coords_by_product[product].shared_group_key, rendered_windows[product])
        grouped_products.setdefault(group_key, []).append(product)

    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []
    for station in stations:
        for (_, windows), group_prods in grouped_products.items():
            primary_coords = coords_by_product[group_prods[0]]
            include_wbw = len(group_prods) == 1
            for window in windows:
                if window.bounds is None:
                    raise FatalContractError("nl_rws requires engine-established window bounds")
                request = _build_request(
                    station=station,
                    coords=primary_coords,
                    start=window.bounds.start,
                    stop=window.bounds.end,
                    include_wbw=include_wbw,
                )
                response = attempt_request(transport, request)
                call_id = uuid4().hex
                if isinstance(response, (TransportFailure, CredentialExchangeError)):
                    win = SeriesWindow(
                        start=datetime.fromisoformat(window.bounds.start.isoformat()),
                        end=datetime.fromisoformat(window.bounds.end.isoformat()),
                    )
                    for product in group_prods:
                        failures.append(
                            FailedSourceRequest(
                                uuid4().hex,
                                _failure_series(station, product, known_series),
                                win,
                                request,
                                response,
                                call_id=call_id,
                            )
                        )
                    continue

                station_products = tuple((station, product) for product in group_prods)
                payloads.append(
                    Payload(
                        source_coordinates=SourceCoordinates(primary_coords),
                        station_products=station_products,
                        fetch_window=window.bounds,
                        content=response.content,
                        origin=_origin(response),
                        prerequisite_calls=response.prerequisite_calls,
                        scope=scope,
                        known_series=known_series,
                        attempt_traces=response.attempt_traces,
                    )
                )

    return SourceAcquisition(value=tuple(payloads), failed_requests=tuple(failures))

"""usgs_nwis fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

from collections.abc import Mapping

from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WithIssues,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.usgs_nwis.config import UsgsNwisSourceCoordinates
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest, TransportResponse

_BASE_URL = "https://waterservices.usgs.gov/nwis/"


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
) -> WithIssues[tuple[Payload, ...]]:
    resolved_products: list[tuple[ProductId, SourceCoordinates, UsgsNwisSourceCoordinates, str, str]] = []
    for product_id in products:
        source_coordinates, coordinates = _resolve_coordinates(
            product_id,
            config,
        )
        (rendered_window,) = rendered_windows[product_id]
        assert rendered_window.stop is not None
        resolved_products.append(
            (product_id, source_coordinates, coordinates, rendered_window.start, rendered_window.stop)
        )
    payloads: list[Payload] = []

    for station_id in stations:
        for product_id, source_coordinates, coordinates, start, end in resolved_products:
            request = _request(station_id, coordinates, start, end)
            response = transport.send(request)
            payloads.append(
                _payload(
                    source_coordinates,
                    station_id,
                    product_id,
                    fetch_window,
                    response,
                )
            )

    return WithIssues(value=tuple(payloads), issues=())


def _resolve_coordinates(
    product_id: ProductId,
    provider_config: ProviderConfig,
) -> tuple[SourceCoordinates, UsgsNwisSourceCoordinates]:
    try:
        product = provider_config.products[product_id]
    except KeyError as error:
        raise FatalContractError(f"usgs_nwis product is absent from provider config: {product_id}") from error
    source_coordinates = product.coordinates
    coordinates = source_coordinates.value
    if not isinstance(coordinates, UsgsNwisSourceCoordinates):
        raise FatalContractError(f"usgs_nwis product has invalid source coordinates: {product_id}")
    return source_coordinates, coordinates


def _request(
    station_id: str,
    coordinates: UsgsNwisSourceCoordinates,
    start: str | int | float,
    end: str | int | float,
) -> TransportRequest:
    params: dict[str, str | int | float | None] = {
        "format": "json",
        "sites": station_id,
        "startDT": start,
        "endDT": end,
        "parameterCd": coordinates.parameter_code,
    }
    if coordinates.statistic_code is not None:
        params["statCd"] = coordinates.statistic_code
    return TransportRequest(
        method=HttpMethod.GET,
        url=f"{_BASE_URL}{coordinates.endpoint}/",
        params=params,
        headers={"Accept": "application/json"},
    )


def _payload(
    source_coordinates: SourceCoordinates,
    station_id: str,
    product_id: ProductId,
    fetch_window: FetchWindow,
    response: TransportResponse,
) -> Payload:
    return Payload(
        source_coordinates=source_coordinates,
        station_products=((station_id, product_id),),
        fetch_window=fetch_window,
        content=response.content,
        origin=SourceCallOrigin(
            url=response.url,
            request_parameters=response.request_parameters,
            status_code=response.status_code,
            retrieved_at=response.retrieved_at,
            content_type=(response.content_type if response.content_type is not None else UnknownOriginFact()),
            source_path=UnknownOriginFact(),
            query=UnknownOriginFact(),
        ),
        prerequisite_calls=response.prerequisite_calls,
    )

"""no_nve fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

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
from rivretrieve._internal.providers.no_nve.config import NoNveSourceCoordinates
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest, TransportResponse

_URL = "https://hydapi.nve.no/api/v1/Observations"


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
) -> WithIssues[tuple[Payload, ...]]:
    resolved = tuple((product, _coordinates(product, config)) for product in products)
    payloads: list[Payload] = []
    for station in stations:
        for product, coordinates in resolved:
            for window in rendered_windows[product]:
                reference_time = _reference_time(window)
                request = _request(station, coordinates, reference_time)
                response = transport.send(request)
                payloads.append(
                    Payload(
                        source_coordinates=SourceCoordinates(coordinates),
                        station_products=((station, product),),
                        fetch_window=fetch_window,
                        content=response.content,
                        origin=_origin(response),
                        prerequisite_calls=response.prerequisite_calls,
                    )
                )
    return WithIssues(value=tuple(payloads), issues=())


def _coordinates(product: ProductId, config: ProviderConfig) -> NoNveSourceCoordinates:
    try:
        value = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"no_nve product is absent from provider config: {product}") from error
    if not isinstance(value, NoNveSourceCoordinates):
        raise FatalContractError(f"no_nve product has invalid source coordinates: {product}")
    return value


def _reference_time(window: RenderedWindow) -> str:
    if window.stop is None:
        raise FatalContractError("no_nve requires a rendered window closed at both ends")
    return f"{window.start}/{window.stop}"


def _request(station: str, coordinates: NoNveSourceCoordinates, reference_time: str) -> TransportRequest:
    return TransportRequest(
        method=HttpMethod.GET,
        url=_URL,
        params={
            "StationId": station,
            "Parameter": coordinates.parameter,
            "ResolutionTime": coordinates.resolution_time,
            "ReferenceTime": reference_time,
        },
        headers={"Accept": "application/json"},
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
    )

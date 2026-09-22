"""lt_lhmt fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

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
from rivretrieve._internal.providers.lt_lhmt.config import LtLhmtSourceCoordinates
from rivretrieve._internal.source_series import SeriesScope, SourceSeries
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest, TransportResponse


@dataclass(frozen=True, slots=True)
class LtLhmtHistoricalRoute:
    """The one source route that co-publishes both configured products."""


_BASE_URL = "https://api.meteo.lt/v1/hydro-stations"


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
) -> WithIssues[tuple[Payload, ...]]:
    for product in products:
        _coordinates(product, config)
    groups: dict[tuple[str, str | None], list[ProductId]] = {}
    for product in products:
        for window in rendered_windows[product]:
            groups.setdefault((window.start, window.stop), []).append(product)

    payloads: list[Payload] = []
    for station in stations:
        for (start, stop), group_products in groups.items():
            request = _request(station, start, stop)
            response = transport.send(request)
            payloads.append(
                Payload(
                    source_coordinates=SourceCoordinates(LtLhmtHistoricalRoute()),
                    station_products=tuple((station, product) for product in group_products),
                    fetch_window=fetch_window,
                    content=response.content,
                    origin=_origin(response),
                    prerequisite_calls=response.prerequisite_calls,
                    scope=scope,
                    known_series=known_series,
                )
            )
    return WithIssues(value=tuple(payloads), issues=())


def _coordinates(product: ProductId, config: ProviderConfig) -> LtLhmtSourceCoordinates:
    try:
        value = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"lt_lhmt product is absent from provider config: {product}") from error
    if not isinstance(value, LtLhmtSourceCoordinates):
        raise FatalContractError(f"lt_lhmt product has invalid source coordinates: {product}")
    return value


def _request(station: str, start: str, stop: str | None) -> TransportRequest:
    if stop is not None:
        raise FatalContractError("lt_lhmt year-month windows must not have a stop value")
    return TransportRequest(
        method=HttpMethod.GET,
        url=f"{_BASE_URL}/{station}/observations/historical/{start}",
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

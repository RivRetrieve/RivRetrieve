"""Acquire independently exhaustive historical months and retain bounded failures.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.lt_lhmt.config import SERIES_MAPPINGS, LtLhmtSourceCoordinates
from rivretrieve._internal.source_acquisition import (
    FailedSourceRequest,
    SourceResponseMeaning,
    attempt_request,
    http_response_meaning,
)
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)


@dataclass(frozen=True, slots=True)
class LtLhmtHistoricalRoute:
    """The one source route that co-publishes both configured products."""


_BASE_URL = "https://api.meteo.lt/v1/hydro-stations"
# Meteo.lt historical-route documentation: no stored station measurements.
_HISTORICAL_RESPONSE_MEANINGS = {404: SourceResponseMeaning.NO_OBSERVATIONS}


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
    for product in products:
        _coordinates(product, config)
    groups: dict[RenderedWindow, list[ProductId]] = {}
    for product in products:
        for window in rendered_windows[product]:
            groups.setdefault(window, []).append(product)

    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []
    for station in stations:
        for window, group_products in groups.items():
            if window.bounds is None:
                raise FatalContractError("lt_lhmt requires engine-established monthly bounds")
            request = _request(station, window.start, window.stop)
            response = attempt_request(transport, request)
            if isinstance(response, (TransportFailure, CredentialExchangeError)):
                meaning = http_response_meaning(response, _HISTORICAL_RESPONSE_MEANINGS)
                call_id = uuid4().hex
                for product in group_products:
                    failures.append(
                        FailedSourceRequest(
                            uuid4().hex,
                            SERIES_MAPPINGS[product].source_series("lt_lhmt", station, product),
                            SeriesWindow(
                                start=datetime.fromisoformat(window.bounds.start.isoformat()),
                                end=datetime.fromisoformat(window.bounds.end.isoformat()),
                            ),
                            request,
                            response,
                            meaning=meaning,
                            call_id=call_id,
                        )
                    )
                continue
            payloads.append(
                Payload(
                    source_coordinates=SourceCoordinates(LtLhmtHistoricalRoute()),
                    station_products=tuple((station, product) for product in group_products),
                    fetch_window=window.bounds,
                    content=response.content,
                    origin=_origin(response),
                    prerequisite_calls=response.prerequisite_calls,
                    scope=scope,
                    known_series=known_series,
                )
            )
    return SourceAcquisition(value=tuple(payloads), failed_requests=tuple(failures))


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
        attempts=response.attempts,
    )

"""Acquire independent source spans and retain their bounded failures.

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
from rivretrieve._internal.providers.th_thaiwater.config import SERIES_MAPPINGS, ThThaiWaterSourceCoordinates
from rivretrieve._internal.source_acquisition import FailedSourceRequest, attempt_request
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import HttpMethod, Transport, TransportFailure, TransportRequest, TransportResponse


@dataclass(frozen=True, slots=True)
class ThThaiWaterGraphRoute:
    """The one source route that co-publishes both configured products."""


_GRAPH_URL = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph"


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
                raise FatalContractError("th_thaiwater requires engine-established acquisition bounds")
            request = _request(station, window.start, window.stop)
            response = attempt_request(transport, request)
            if isinstance(response, (TransportFailure, CredentialExchangeError)):
                call_id = uuid4().hex
                for product in group_products:
                    failures.append(
                        FailedSourceRequest(
                            uuid4().hex,
                            SERIES_MAPPINGS[product].source_series("th_thaiwater", station, product),
                            SeriesWindow(
                                start=datetime.fromisoformat(window.bounds.start.isoformat()),
                                end=datetime.fromisoformat(window.bounds.end.isoformat()),
                            ),
                            request,
                            response,
                            call_id=call_id,
                        )
                    )
                continue
            payloads.append(
                Payload(
                    source_coordinates=SourceCoordinates(ThThaiWaterGraphRoute()),
                    station_products=tuple((station, product) for product in group_products),
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


def _coordinates(product: ProductId, config: ProviderConfig) -> ThThaiWaterSourceCoordinates:
    try:
        value = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"th_thaiwater product is absent from provider config: {product}") from error
    if not isinstance(value, ThThaiWaterSourceCoordinates):
        raise FatalContractError(f"th_thaiwater product has invalid source coordinates: {product}")
    return value


def _request(station: str, start: str, stop: str | None) -> TransportRequest:
    if stop is None:
        raise FatalContractError("th_thaiwater date windows require an end date")
    return TransportRequest(
        method=HttpMethod.GET,
        url=_GRAPH_URL,
        params={
            "station_type": "tele_waterlevel",
            "station_id": station,
            "start_date": start,
            "end_date": stop,
        },
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

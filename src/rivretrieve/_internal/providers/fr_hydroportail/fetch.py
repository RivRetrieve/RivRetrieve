"""fr_hydroportail fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

from collections.abc import Mapping

from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceCallOrigin,
    UnknownOriginFact,
    WithIssues,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.fr_hydroportail.config import FrHydroportailSourceCoordinates
from rivretrieve._internal.source_series import SeriesScope, SourceSeries
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest, TransportResponse

_HYDROPORTAIL_ROOT = "https://hydro.eaufrance.fr"


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
    payloads: list[Payload] = []
    for station in stations:
        for product in products:
            source = config.products[product].coordinates
            coordinates = source.value
            if not isinstance(coordinates, FrHydroportailSourceCoordinates):
                raise FatalContractError(f"fr_hydroportail product has invalid source coordinates: {product}")
            (window,) = rendered_windows[product]
            if window.stop is None:
                raise FatalContractError("fr_hydroportail product requires a rendered stop")
            start = window.start
            stop = window.stop
            request = TransportRequest(
                HttpMethod.GET,
                f"{_HYDROPORTAIL_ROOT}/stationhydro/ajax/{station}/series",
                {
                    "hydro_series[startAt]": start,
                    "hydro_series[endAt]": stop,
                    "hydro_series[variableType]": "simple_and_interpolated_and_hourly_variable",
                    "hydro_series[simpleAndInterpolatedAndHourlyVariable]": coordinates.field,
                    "hydro_series[statusData]": "raw",
                },
                {"Accept": "application/json"},
            )
            response = transport.send(request)
            payloads.append(
                Payload(
                    source,
                    ((station, product),),
                    fetch_window,
                    response.content,
                    _origin(response),
                    response.prerequisite_calls,
                    scope=scope,
                    known_series=known_series,
                )
            )
    return WithIssues(tuple(payloads))


def _origin(response: TransportResponse) -> SourceCallOrigin:
    return SourceCallOrigin(
        response.url,
        response.request_parameters,
        response.status_code,
        response.retrieved_at,
        response.content_type if response.content_type else UnknownOriginFact(),
        UnknownOriginFact(),
        UnknownOriginFact(),
    )

"""fr_hubeau fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

import json
from collections.abc import Mapping
from typing import cast

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
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.fr_hubeau.config import FrHubeauSourceCoordinates
from rivretrieve._internal.source_series import SeriesScope, SourceSeries
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest, TransportResponse

_DAILY_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab"
_TEMPERATURE_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/chronique"


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
            if not isinstance(coordinates, FrHubeauSourceCoordinates):
                raise FatalContractError(f"fr_hubeau product has invalid source coordinates: {product}")
            (window,) = rendered_windows[product]
            if window.stop is None:
                raise FatalContractError("fr_hubeau product requires a rendered stop")
            if coordinates.family == "daily":
                request = TransportRequest(
                    HttpMethod.GET,
                    _DAILY_URL,
                    {
                        "code_entite": station,
                        "date_debut_obs_elab": window.start,
                        "date_fin_obs_elab": window.stop,
                        "grandeur_hydro_elab": coordinates.field,
                        "size": 20,
                    },
                    {"Accept": "application/json"},
                )
            elif coordinates.family == "temperature":
                request = TransportRequest(
                    HttpMethod.GET,
                    _TEMPERATURE_URL,
                    {
                        "code_station": station,
                        "date_debut_mesure": window.start,
                        "date_fin_mesure": window.stop,
                        "size": 20,
                    },
                    {"Accept": "application/json"},
                )
            while True:
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
                try:
                    next_url = next_url_from_response(response.content)
                except UnsupportedSourceStructureError:
                    # Parse retains this page's unsupported outcome and exact bytes.
                    break
                if next_url is None:
                    break
                request = TransportRequest(HttpMethod.GET, next_url, None, {"Accept": "application/json"})
    return WithIssues(tuple(payloads))


def next_url_from_response(content: bytes) -> str | None:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("fr_hubeau payload content is not valid JSON") from error
    if not isinstance(document, dict):
        raise UnsupportedSourceStructureError("fr_hubeau payload must be a JSON object")
    value = cast("dict[str, object]", document).get("next")
    if value is not None and not isinstance(value, str):
        raise UnsupportedSourceStructureError("fr_hubeau response next must be a URL or null")
    if value is not None and not value.startswith("https://hubeau.eaufrance.fr/api/"):
        raise UnsupportedSourceStructureError("fr_hubeau response next URL is outside Hub Eau")
    return value


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

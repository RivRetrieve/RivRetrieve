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
from rivretrieve._internal.providers.fr_hubeau.config import FrHubeauSourceCoordinates
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest, TransportResponse

_DAILY_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab"
_TEMPERATURE_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/chronique"
_HYDROPORTAIL_ROOT = "https://hydro.eaufrance.fr"
_HYDROPORTAIL_IDENTITIES = {"Y251002001": {"station": "Y251002001", "site": "Y2510020"}}


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
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
            else:
                identities = _HYDROPORTAIL_IDENTITIES.get(station)
                if identities is None:
                    raise FatalContractError(
                        f"fr_hubeau has no evidenced HydroPortail entity mapping for station {station}"
                    )
                entity = identities[coordinates.entity_kind]
                start = window.start
                stop = window.stop
                request = TransportRequest(
                    HttpMethod.GET,
                    f"{_HYDROPORTAIL_ROOT}/{coordinates.entity_kind}hydro/ajax/{entity}/series",
                    {
                        "hydro_series[startAt]": start,
                        "hydro_series[endAt]": stop,
                        "hydro_series[variableType]": "simple_and_interpolated_and_hourly_variable",
                        "hydro_series[simpleAndInterpolatedAndHourlyVariable]": coordinates.field,
                        "hydro_series[statusData]": "raw",
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
                    )
                )
                if coordinates.family == "hydroportail":
                    break
                next_url = _next_url(response.content)
                if next_url is None:
                    break
                if not next_url.startswith("https://hubeau.eaufrance.fr/api/"):
                    raise FatalContractError("fr_hubeau response next URL is outside Hub Eau")
                request = TransportRequest(HttpMethod.GET, next_url, None, {"Accept": "application/json"})
    return WithIssues(tuple(payloads))


def _next_url(content: bytes) -> str | None:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FatalContractError("fr_hubeau payload content is not valid JSON") from error
    if not isinstance(document, dict):
        raise FatalContractError("fr_hubeau payload must be a JSON object")
    value = cast("dict[str, object]", document).get("next")
    if value is not None and not isinstance(value, str):
        raise FatalContractError("fr_hubeau response next must be a URL or null")
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

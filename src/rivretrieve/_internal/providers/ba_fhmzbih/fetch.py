"""ba_fhmzbih fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

import json
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
from rivretrieve._internal.providers.ba_fhmzbih.config import BaFhmzbihSourceCoordinates
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest, TransportResponse

_METADATA_URL = "https://vodostaji.voda.ba/data/internet/layers/20/index.json"
_WORKBOOK_ROOT = "https://vodostaji.voda.ba/data/internet/stations"


@dataclass(frozen=True, slots=True)
class BaFhmzbihMetadataCoordinates:
    pass


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
) -> WithIssues[tuple[Payload, ...]]:
    for product in products:
        if rendered_windows[product] != ():
            raise FatalContractError("ba_fhmzbih source-fixed product received an unexpected rendered window")
    metadata_response = _send(
        transport, TransportRequest(HttpMethod.GET, _METADATA_URL, params=None, headers={"Accept": "application/json"})
    )
    try:
        document = json.loads(metadata_response.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FatalContractError("ba_fhmzbih metadata index is not valid JSON") from error
    if not isinstance(document, list):
        raise FatalContractError("ba_fhmzbih metadata index must be a JSON array")
    groups: dict[str, str] = {}
    for station in stations:
        matches = [row for row in document if isinstance(row, dict) and row.get("metadata_station_no") == station]
        if (
            len(matches) != 1
            or not isinstance(matches[0].get("metadata_site_no"), str)
            or not matches[0]["metadata_site_no"]
        ):
            raise FatalContractError(
                f"ba_fhmzbih metadata index does not resolve exactly one group for station {station}"
            )
        groups[station] = matches[0]["metadata_site_no"]
    pairs = tuple((station, product) for station in stations for product in products)
    payloads = [_payload(SourceCoordinates(BaFhmzbihMetadataCoordinates()), pairs, fetch_window, metadata_response)]
    for station, product in pairs:
        product_config = config.products[product]
        coordinates = product_config.coordinates.value
        if not isinstance(coordinates, BaFhmzbihSourceCoordinates):
            raise FatalContractError(f"ba_fhmzbih product has invalid source coordinates: {product}")
        url = f"{_WORKBOOK_ROOT}/{groups[station]}/{station}/{coordinates.code}/{coordinates.workbook}"
        response = _send(
            transport,
            TransportRequest(
                HttpMethod.GET,
                url,
                params=None,
                headers={"Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            ),
        )
        payloads.append(_payload(product_config.coordinates, ((station, product),), fetch_window, response))
    return WithIssues(tuple(payloads))


def _send(transport: Transport, request: TransportRequest) -> TransportResponse:
    return transport.send(request)


def _payload(
    coordinates: SourceCoordinates,
    pairs: tuple[tuple[str, ProductId], ...],
    window: FetchWindow,
    response: TransportResponse,
) -> Payload:
    return Payload(
        coordinates,
        pairs,
        window,
        response.content,
        SourceCallOrigin(
            response.url,
            response.request_parameters,
            response.status_code,
            response.retrieved_at,
            response.content_type if response.content_type else UnknownOriginFact(),
            UnknownOriginFact(),
            UnknownOriginFact(),
        ),
        response.prerequisite_calls,
    )

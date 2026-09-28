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
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.ba_fhmzbih.config import BaFhmzbihSourceCoordinates
from rivretrieve._internal.source_series import SeriesScope, SourceSeries
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
    *,
    scope: SeriesScope | None = None,
    known_series: tuple[SourceSeries, ...] = (),
) -> WithIssues[tuple[Payload, ...]]:
    if len(stations) != 1 or len(products) != 1:
        raise FatalContractError("ba_fhmzbih fetch requires exactly one station-product pair")
    for product in products:
        if rendered_windows[product] != ():
            raise FatalContractError("ba_fhmzbih source-fixed product received an unexpected rendered window")
    metadata_response = transport.send(
        TransportRequest(HttpMethod.GET, _METADATA_URL, params=None, headers={"Accept": "application/json"})
    )
    pairs = tuple((station, product) for station in stations for product in products)
    metadata_payload = _payload(
        SourceCoordinates(BaFhmzbihMetadataCoordinates()), pairs, fetch_window, metadata_response, scope, known_series
    )
    try:
        groups = metadata_groups(metadata_response.content, stations)
    except UnsupportedSourceStructureError:
        # Keep exact source bytes for parse-owned diagnostics and optional receipts.
        return WithIssues((metadata_payload,))
    payloads = [metadata_payload]
    for station, product in pairs:
        product_config = config.products[product]
        coordinates = product_config.coordinates.value
        if not isinstance(coordinates, BaFhmzbihSourceCoordinates):
            raise FatalContractError(f"ba_fhmzbih product has invalid source coordinates: {product}")
        url = f"{_WORKBOOK_ROOT}/{groups[station]}/{station}/{coordinates.code}/{coordinates.workbook}"
        response = transport.send(
            TransportRequest(
                HttpMethod.GET,
                url,
                params=None,
                headers={"Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            ),
        )
        payloads.append(
            _payload(product_config.coordinates, ((station, product),), fetch_window, response, scope, known_series)
        )
    return WithIssues(tuple(payloads))


def _payload(
    coordinates: SourceCoordinates,
    pairs: tuple[tuple[str, ProductId], ...],
    window: FetchWindow,
    response: TransportResponse,
    scope: SeriesScope | None,
    known_series: tuple[SourceSeries, ...],
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
        scope=scope,
        known_series=known_series,
    )


def metadata_groups(content: bytes, stations: tuple[str, ...]) -> dict[str, str]:
    """Resolve publisher station routes without inventing missing group identifiers."""
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("ba_fhmzbih metadata index is not valid JSON") from error
    if not isinstance(document, list):
        raise UnsupportedSourceStructureError("ba_fhmzbih metadata index must be a JSON array")
    groups: dict[str, str] = {}
    for station in stations:
        matches = [row for row in document if isinstance(row, dict) and row.get("metadata_station_no") == station]
        if (
            len(matches) != 1
            or not isinstance(matches[0].get("metadata_site_no"), str)
            or not matches[0]["metadata_site_no"]
        ):
            raise UnsupportedSourceStructureError(
                f"ba_fhmzbih metadata index does not resolve exactly one group for station {station}"
            )
        groups[station] = matches[0]["metadata_site_no"]
    return groups

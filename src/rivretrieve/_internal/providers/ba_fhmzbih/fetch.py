"""ba_fhmzbih fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

from collections.abc import Mapping

from rivretrieve._internal.engine import (
    FetchWindow,
    InterpretedPayload,
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
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.ba_fhmzbih.config import (
    BaFhmzbihMetadataCoordinates as BaFhmzbihMetadataCoordinates,
)
from rivretrieve._internal.providers.ba_fhmzbih.config import (
    BaFhmzbihSourceCoordinates,
)
from rivretrieve._internal.providers.ba_fhmzbih.parse import (
    interpret_metadata_payload,
)
from rivretrieve._internal.providers.ba_fhmzbih.parse import (
    metadata_groups as metadata_groups,
)
from rivretrieve._internal.source_series import SeriesScope, SourceSeries
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest, TransportResponse

_METADATA_URL = "https://vodostaji.voda.ba/data/internet/layers/20/index.json"
_WORKBOOK_ROOT = "https://vodostaji.voda.ba/data/internet/stations"


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
    except UnsupportedSourceStructureError as error:
        # Keep exact source bytes for parse-owned diagnostics and optional receipts.
        metadata_parsed = interpret_metadata_payload(metadata_payload, config, error=error)
        return SourceAcquisition(
            value=(metadata_payload,),
            interpretations=(InterpretedPayload.from_payload(metadata_payload, metadata_parsed),),
        )
    metadata_parsed = interpret_metadata_payload(metadata_payload, config)
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
    del groups
    return SourceAcquisition(
        value=tuple(payloads),
        interpretations=(InterpretedPayload.from_payload(metadata_payload, metadata_parsed),),
    )


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

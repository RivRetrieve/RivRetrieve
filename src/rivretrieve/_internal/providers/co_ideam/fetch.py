"""Acquire Colombia IDEAM S3 historical CSV payloads with per-series failure isolation."""

from __future__ import annotations

from collections.abc import Mapping
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
    UnknownOriginFact,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.co_ideam.config import CoIdeamS3CsvCoordinates
from rivretrieve._internal.providers.co_ideam.series import association_product
from rivretrieve._internal.source_acquisition import (
    FailedSourceRequest,
    SourceRequestTarget,
    attempt_request,
)
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)

S3_HISTORICOS_CSV_BASE_URL = "https://datos.ideam.gov.co/s3-estacionesideam/observaciones/historicos/csv"


def _validate_station_id(station: str) -> None:
    if len(station) != 10 or not station.isascii() or not station.isdigit():
        raise FatalContractError(f"co_ideam station_id must be a canonical 10-digit ASCII code: {station!r}")


def s3_observation_csv_url(station: str, etiqueta: str) -> str:
    """Build the deterministic anonymous S3 CSV URL for ``(station, etiqueta)``."""
    _validate_station_id(station)
    association_product(etiqueta)
    return f"{S3_HISTORICOS_CSV_BASE_URL}/{etiqueta}/{station}-{etiqueta}.csv"


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
    """Fetch source-fixed IDEAM S3 CSVs while isolating per-series transport failures."""
    if not stations or not products:
        raise FatalContractError("co_ideam fetch requires at least one station and product")

    for station in stations:
        _validate_station_id(station)

    validated_products: list[tuple[ProductId, CoIdeamS3CsvCoordinates]] = []
    for product in products:
        try:
            product_config = config.products[product]
        except KeyError as error:
            raise FatalContractError(f"co_ideam product is absent from provider config: {product}") from error
        if rendered_windows.get(product, ()) != ():
            raise FatalContractError(f"co_ideam source-fixed product received unexpected rendered windows: {product}")
        coords = product_config.coordinates.value
        if not isinstance(coords, CoIdeamS3CsvCoordinates):
            raise FatalContractError(f"co_ideam product has invalid source coordinates: {product}")
        validated_products.append((product, coords))

    window = SeriesWindow(
        start=datetime.fromisoformat(fetch_window.start.isoformat()),
        end=datetime.fromisoformat(fetch_window.end.isoformat()),
    )
    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []

    for station in stations:
        for product, coords in validated_products:
            request = TransportRequest(
                method=HttpMethod.GET,
                url=s3_observation_csv_url(station, coords.etiqueta),
            )
            response = attempt_request(transport, request)
            if isinstance(response, (TransportFailure, CredentialExchangeError)):
                failures.append(
                    FailedSourceRequest(
                        uuid4().hex,
                        _request_target(station, product, known_series),
                        window,
                        request,
                        response,
                    )
                )
                continue
            payloads.append(
                Payload(
                    source_coordinates=config.products[product].coordinates,
                    station_products=((station, product),),
                    fetch_window=fetch_window,
                    content=response.content,
                    origin=_origin(response),
                    prerequisite_calls=response.prerequisite_calls,
                    scope=scope,
                    known_series=known_series,
                    attempt_traces=response.attempt_traces,
                )
            )

    return SourceAcquisition(value=tuple(payloads), failed_requests=tuple(failures))


def _request_target(
    station: str, product: ProductId, known_series: tuple[SourceSeries, ...]
) -> SourceSeries | SourceRequestTarget:
    matching = tuple(item for item in known_series if item.station_id == station and item.product_id == str(product))
    if len(matching) == 1:
        return matching[0]
    return SourceRequestTarget(station, str(product))


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

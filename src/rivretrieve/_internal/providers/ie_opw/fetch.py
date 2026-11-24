"""Acquire full-history OPW Hydro-Data ``year.json`` and ``*_complete.zip`` payloads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal
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
from rivretrieve._internal.providers.ie_opw.config import (
    OpwCompleteZipCoordinates,
    OpwDailyYearJsonCoordinates,
    OpwDailyYearJsonEndpointCoordinates,
)
from rivretrieve._internal.providers.ie_opw.series import (
    COMPLETE_ZIP_BY_PARAM,
    reused_series,
    source_series,
)
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

OPW_STATIONS_BASE_URL = "https://waterlevel.ie/hydro-data/data/internet/stations/0"
_MAX_FLOWING_STATION_NO = 41_000


def validate_station_id(station: str) -> None:
    """Enforce canonical 5-digit OPW Hydrometric Area flowing-watercourse IDs (``00001..41000``)."""
    if (
        not isinstance(station, str)
        or len(station) != 5
        or not station.isascii()
        or not station.isdigit()
        or not (1 <= int(station) <= _MAX_FLOWING_STATION_NO)
    ):
        raise FatalContractError(f"ie_opw station_id must be a 5-digit ASCII code in 00001..41000: {station!r}")


def daily_year_json_url(station: str, parameter: Literal["Q", "S", "TWater"]) -> str:
    """Build anonymous OPW Hydro-Data ``year.json`` endpoint URL for ``(station, parameter)``."""
    validate_station_id(station)
    if parameter not in ("Q", "S", "TWater"):
        raise FatalContractError(f"Unsupported ie_opw parameter for year.json: {parameter!r}")
    return f"{OPW_STATIONS_BASE_URL}/{station}/{parameter}/year.json"


def complete_zip_url(
    station: str,
    parameter: Literal["Q", "S", "TWater"],
    route: str | None = None,
) -> str:
    """Build anonymous OPW Hydro-Data ``*_complete.zip`` URL for ``(station, parameter)``."""
    validate_station_id(station)
    spec = COMPLETE_ZIP_BY_PARAM.get(parameter)
    if spec is None or (route is not None and route != spec.route):
        raise FatalContractError(f"Unsupported ie_opw complete.zip selector: parameter={parameter!r}, route={route!r}")
    return f"{OPW_STATIONS_BASE_URL}/{station}/{parameter}/{spec.route}"


def _request_target(
    station: str, product: ProductId, known_series: tuple[SourceSeries, ...]
) -> SourceSeries | SourceRequestTarget:
    matching = tuple(item for item in known_series if item.station_id == station and item.product_id == str(product))
    if len(matching) == 1:
        return matching[0]
    try:
        return reused_series(source_series(station, str(product), origin="mapping"), known_series)
    except FatalContractError:
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
        attempt_traces=response.attempt_traces,
    )


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
    """Acquire full-history OPW ``year.json`` (grouped per parameter) and ``*_complete.zip`` payloads."""
    if not stations or not products:
        raise FatalContractError("ie_opw fetch requires at least one station and product")
    for station in stations:
        validate_station_id(station)

    year_groups: dict[Literal["Q", "S", "TWater"], list[tuple[ProductId, OpwDailyYearJsonCoordinates]]] = {}
    zip_products: list[tuple[ProductId, OpwCompleteZipCoordinates]] = []

    for product in products:
        try:
            product_config = config.products[product]
        except KeyError as error:
            raise FatalContractError(f"ie_opw product is absent from provider config: {product}") from error
        if rendered_windows.get(product, ()) != ():
            raise FatalContractError(f"ie_opw source-fixed product received unexpected rendered windows: {product}")
        coords = product_config.coordinates.value
        if isinstance(coords, OpwDailyYearJsonCoordinates):
            year_groups.setdefault(coords.parameter, []).append((product, coords))
        elif isinstance(coords, OpwCompleteZipCoordinates):
            zip_products.append((product, coords))
        else:
            raise FatalContractError(f"ie_opw product has invalid source coordinates: {product}")

    requested_window = SeriesWindow(
        start=datetime.fromisoformat(fetch_window.start.isoformat()),
        end=datetime.fromisoformat(fetch_window.end.isoformat()),
    )
    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []

    for station in stations:
        for param, group_items in year_groups.items():
            group_products = tuple(product for product, _ in group_items)
            request = TransportRequest(
                method=HttpMethod.GET,
                url=daily_year_json_url(station, param),
            )
            response = attempt_request(transport, request)
            if isinstance(response, (TransportFailure, CredentialExchangeError)):
                call_id = uuid4().hex
                for product in group_products:
                    failures.append(
                        FailedSourceRequest(
                            uuid4().hex,
                            _request_target(station, product, known_series),
                            requested_window,
                            request,
                            response,
                            call_id=call_id,
                        )
                    )
                continue

            coords_box = (
                config.products[group_products[0]].coordinates
                if len(group_products) == 1
                else SourceCoordinates(OpwDailyYearJsonEndpointCoordinates(param))
            )
            payload_scope = (
                scope.model_copy(
                    update={
                        "station_ids": (station,),
                        "product_ids": tuple(str(p) for p in group_products),
                    }
                )
                if scope is not None
                else None
            )
            payloads.append(
                Payload(
                    source_coordinates=coords_box,
                    station_products=tuple((station, product) for product in group_products),
                    fetch_window=fetch_window,
                    content=response.content,
                    origin=_origin(response),
                    prerequisite_calls=response.prerequisite_calls,
                    scope=payload_scope,
                    known_series=known_series,
                    attempt_traces=response.attempt_traces,
                )
            )

        for product, coords in zip_products:
            request = TransportRequest(
                method=HttpMethod.GET,
                url=complete_zip_url(station, coords.parameter, coords.route),
            )
            response = attempt_request(transport, request)
            if isinstance(response, (TransportFailure, CredentialExchangeError)):
                failures.append(
                    FailedSourceRequest(
                        uuid4().hex,
                        _request_target(station, product, known_series),
                        requested_window,
                        request,
                        response,
                    )
                )
                continue
            pair_scope = (
                scope.model_copy(update={"station_ids": (station,), "product_ids": (str(product),)})
                if scope is not None
                else None
            )
            payloads.append(
                Payload(
                    source_coordinates=config.products[product].coordinates,
                    station_products=((station, product),),
                    fetch_window=fetch_window,
                    content=response.content,
                    origin=_origin(response),
                    prerequisite_calls=response.prerequisite_calls,
                    scope=pair_scope,
                    known_series=known_series,
                    attempt_traces=response.attempt_traces,
                )
            )

    return SourceAcquisition(value=tuple(payloads), failed_requests=tuple(failures))

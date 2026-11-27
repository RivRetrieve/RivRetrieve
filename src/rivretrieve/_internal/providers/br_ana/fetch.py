"""Acquire independent source spans and retain their bounded failures.

Contributed by: Thiago von Däniken
"""

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
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.br_ana.config import (
    BrAnaDailySourceCoordinates,
    BrAnaSharedEndpointCoordinates,
    BrAnaSourceCoordinates,
)
from rivretrieve._internal.providers.br_ana.series import describe_series
from rivretrieve._internal.source_acquisition import FailedSourceRequest, attempt_request
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import HttpMethod, Transport, TransportFailure, TransportRequest

_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1"
_Endpoint = Literal["HidroinfoanaSerieTelemetricaAdotada", "HidroSerieCotas", "HidroSerieVazao"]


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
    for station in stations:
        if not station.isascii() or not station.isdecimal() or str(int(station)) != station:
            raise FatalContractError("ANA station id must be a canonical decimal source code")

    request_groups: dict[
        tuple[_Endpoint, RenderedWindow],
        list[tuple[ProductId, SourceCoordinates, BrAnaSourceCoordinates | BrAnaDailySourceCoordinates]],
    ] = {}
    for product in products:
        coordinates = config.products[product].coordinates
        source = coordinates.value
        if not isinstance(source, (BrAnaSourceCoordinates, BrAnaDailySourceCoordinates)):
            raise FatalContractError("ANA product requires documented source coordinates")
        endpoint: _Endpoint = (
            source.endpoint
            if isinstance(source, BrAnaDailySourceCoordinates)
            else "HidroinfoanaSerieTelemetricaAdotada"
        )
        for window in rendered_windows[product]:
            if window.bounds is None:
                raise FatalContractError("ANA requires engine-established acquisition bounds")
            if window.stop is None:
                raise FatalContractError("ANA source requires an inclusive date stop")
            entries = request_groups.setdefault((endpoint, window), [])
            if all(existing_product != product for existing_product, _, _ in entries):
                entries.append((product, coordinates, source))

    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []
    for station in stations:
        station_code = int(station)
        for (endpoint, window), group_items in request_groups.items():
            assert window.bounds is not None
            assert window.stop is not None
            if endpoint != "HidroinfoanaSerieTelemetricaAdotada":
                url = f"https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/{endpoint}/v1"
                parameters: dict[str, str | int] = {
                    "Código da Estação": station_code,
                    "Tipo Filtro Data": "DATA_LEITURA",
                    "Data Inicial (yyyy-MM-dd)": window.start,
                    "Data Final (yyyy-MM-dd)": window.stop,
                }
            else:
                url = _URL
                parameters = {
                    "Código da Estação": station_code,
                    "Tipo Filtro Data": "DATA_LEITURA",
                    "Data de Busca (yyyy-MM-dd)": window.stop,
                    "Range Intervalo de busca": "DIAS_30",
                }
            series_window = SeriesWindow(
                start=datetime.fromisoformat(window.bounds.start.isoformat()),
                end=datetime.fromisoformat(window.bounds.end.isoformat()),
            )
            targets = [
                next(
                    (item for item in known_series if item.series_id == default_target.series_id),
                    default_target,
                )
                for product, _, source in group_items
                for default_target in (describe_series(station, product, source),)
            ]
            request = TransportRequest(method=HttpMethod.GET, url=url, params=parameters)
            response = attempt_request(transport, request)
            if isinstance(response, (TransportFailure, CredentialExchangeError)):
                call_id = uuid4().hex
                for target in targets:
                    failures.append(
                        FailedSourceRequest(
                            uuid4().hex,
                            target,
                            series_window,
                            request,
                            response,
                            call_id=call_id,
                        )
                    )
                continue
            payload_coordinates = (
                group_items[0][1]
                if len(group_items) == 1
                else SourceCoordinates(BrAnaSharedEndpointCoordinates(endpoint))
            )
            payloads.append(
                Payload(
                    source_coordinates=payload_coordinates,
                    station_products=tuple((station, product) for product, _, _ in group_items),
                    fetch_window=window.bounds,
                    content=response.content,
                    origin=SourceCallOrigin.from_response(response),
                    prerequisite_calls=response.prerequisite_calls,
                    scope=scope,
                    known_series=known_series,
                    attempt_traces=response.attempt_traces,
                )
            )
    return SourceAcquisition(tuple(payloads), failed_requests=tuple(failures))

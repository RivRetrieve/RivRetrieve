"""Acquire independent source spans and retain their bounded failures.

Contributed by: Thiago von Däniken
"""

from collections.abc import Mapping
from datetime import datetime

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
from rivretrieve._internal.providers.br_ana.config import BrAnaDailySourceCoordinates, BrAnaSourceCoordinates
from rivretrieve._internal.providers.br_ana.series import describe_series
from rivretrieve._internal.source_acquisition import FailedSourceRequest, attempt_series_request
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest

_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1"


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
    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []
    for station in stations:
        if not station.isascii() or not station.isdecimal() or str(int(station)) != station:
            raise FatalContractError("ANA station id must be a canonical decimal source code")
        for product in products:
            coordinates = config.products[product].coordinates
            source = coordinates.value
            if not isinstance(source, (BrAnaSourceCoordinates, BrAnaDailySourceCoordinates)):
                raise FatalContractError("ANA product requires documented source coordinates")
            for window in rendered_windows[product]:
                if window.bounds is None:
                    raise FatalContractError("ANA requires engine-established acquisition bounds")
                if window.stop is None:
                    raise FatalContractError("ANA source requires an inclusive date stop")
                if isinstance(source, BrAnaDailySourceCoordinates):
                    url = f"https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/{source.endpoint}/v1"
                    parameters = {
                        "Código da Estação": int(station),
                        "Tipo Filtro Data": "DATA_LEITURA",
                        "Data Inicial (yyyy-MM-dd)": window.start,
                        "Data Final (yyyy-MM-dd)": window.stop,
                    }
                else:
                    url = _URL
                    parameters = {
                        "Código da Estação": int(station),
                        "Tipo Filtro Data": "DATA_LEITURA",
                        "Data de Busca (yyyy-MM-dd)": window.stop,
                        "Range Intervalo de busca": "DIAS_30",
                    }
                response = attempt_series_request(
                    transport,
                    TransportRequest(method=HttpMethod.GET, url=url, params=parameters),
                    describe_series(station, product, source),
                    SeriesWindow(
                        start=datetime.fromisoformat(window.bounds.start.isoformat()),
                        end=datetime.fromisoformat(window.bounds.end.isoformat()),
                    ),
                )
                if isinstance(response, FailedSourceRequest):
                    failures.append(response)
                    continue
                payloads.append(
                    Payload(
                        source_coordinates=coordinates,
                        station_products=((station, product),),
                        fetch_window=window.bounds,
                        content=response.content,
                        origin=SourceCallOrigin(
                            url=response.url,
                            request_parameters=response.request_parameters,
                            status_code=response.status_code,
                            retrieved_at=response.retrieved_at,
                            content_type=response.content_type
                            if response.content_type is not None
                            else UnknownOriginFact(),
                            source_path=UnknownOriginFact(),
                            query=UnknownOriginFact(),
                            attempts=response.attempts,
                        ),
                        prerequisite_calls=response.prerequisite_calls,
                        scope=scope,
                        known_series=known_series,
                        attempt_traces=response.attempt_traces,
                    )
                )
    return SourceAcquisition(tuple(payloads), failed_requests=tuple(failures))

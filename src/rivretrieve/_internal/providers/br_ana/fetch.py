"""ANA fetch : Stations × Products × WindowRenderings × FetchWindow × ProviderConfig × Transport → WithIssues[Payloads].

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
from rivretrieve._internal.providers.br_ana.config import BrAnaSourceCoordinates
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest

_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1"


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
        if not station.isascii() or not station.isdecimal() or str(int(station)) != station:
            raise FatalContractError("ANA station id must be a canonical decimal source code")
        for product in products:
            coordinates = config.products[product].coordinates
            if not isinstance(coordinates.value, BrAnaSourceCoordinates):
                raise FatalContractError("ANA product requires adopted telemetry source coordinates")
            for window in rendered_windows[product]:
                if window.stop is None:
                    raise FatalContractError("ANA telemetry requires an inclusive date anchor")
                response = transport.send(
                    TransportRequest(
                        method=HttpMethod.GET,
                        url=_URL,
                        params={
                            "Código da Estação": int(station),
                            "Tipo Filtro Data": "DATA_LEITURA",
                            "Data de Busca (yyyy-MM-dd)": window.stop,
                            "Range Intervalo de busca": "DIAS_30",
                        },
                    )
                )
                payloads.append(
                    Payload(
                        source_coordinates=coordinates,
                        station_products=((station, product),),
                        fetch_window=fetch_window,
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
                        ),
                        prerequisite_calls=response.prerequisite_calls,
                    )
                )
    return WithIssues(tuple(payloads))

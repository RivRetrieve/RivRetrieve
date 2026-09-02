"""cz_chmi fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

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
from rivretrieve._internal.providers.cz_chmi.config import CzChmiSourceCoordinates
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest

_BASE = "https://opendata.chmi.cz/hydrology/historical/data"


@dataclass(frozen=True, slots=True)
class CzChmiRequestCoordinates:
    """The annual file and selected native series represented by one source call."""

    file_code: str
    ts_con_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.file_code not in ("DQ", "HQ"):
            raise ValueError("CHMI request file code must be DQ or HQ")
        if not self.ts_con_ids or len(self.ts_con_ids) != len(set(self.ts_con_ids)):
            raise ValueError("CHMI request native series must be non-empty and unique")


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
) -> WithIssues[tuple[Payload, ...]]:
    groups: dict[tuple[str, str, str], list[tuple[ProductId, CzChmiSourceCoordinates]]] = {}
    for station_id in stations:
        for product_id in products:
            try:
                product = config.products[product_id]
            except KeyError as error:
                raise FatalContractError(f"cz_chmi product is absent from provider config: {product_id}") from error
            coordinates = product.coordinates.value
            if not isinstance(coordinates, CzChmiSourceCoordinates):
                raise FatalContractError(f"cz_chmi product has invalid source coordinates: {product_id}")
            for rendered in rendered_windows[product_id]:
                if rendered.stop is not None:
                    raise FatalContractError("cz_chmi annual window must have no rendered stop")
                groups.setdefault((station_id, coordinates.file_code, rendered.start), []).append(
                    (product_id, coordinates)
                )

    payloads: list[Payload] = []
    for (station_id, file_code, year), members in groups.items():
        cadence = "daily" if file_code == "DQ" else "hourly"
        url = f"{_BASE}/{cadence}/H_{station_id}_{file_code}_{year}.json"
        response = transport.send(
            TransportRequest(method=HttpMethod.GET, url=url, headers={"Accept": "application/json"})
        )
        if not 200 <= response.status_code < 300:
            raise FatalContractError(f"cz_chmi request returned unexpected HTTP status {response.status_code}")
        payloads.append(
            Payload(
                source_coordinates=SourceCoordinates(
                    CzChmiRequestCoordinates(file_code, tuple(coordinates.ts_con_id for _, coordinates in members))
                ),
                station_products=tuple((station_id, product_id) for product_id, _ in members),
                fetch_window=fetch_window,
                content=response.content,
                origin=SourceCallOrigin(
                    url=response.url,
                    request_parameters=response.request_parameters,
                    status_code=response.status_code,
                    retrieved_at=response.retrieved_at,
                    content_type=response.content_type if response.content_type is not None else UnknownOriginFact(),
                    source_path=UnknownOriginFact(),
                    query=UnknownOriginFact(),
                ),
            )
        )
    return WithIssues(value=tuple(payloads), issues=())

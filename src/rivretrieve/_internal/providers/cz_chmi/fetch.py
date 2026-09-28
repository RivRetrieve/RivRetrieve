"""Acquire independent CHMI annual files and retain shared-product failures.

Contributed by: Thiago von Däniken
"""

from collections.abc import Mapping
from dataclasses import dataclass
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
    SourceCoordinates,
    UnknownOriginFact,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.cz_chmi.config import SERIES_MAPPINGS, CzChmiSourceCoordinates
from rivretrieve._internal.source_acquisition import FailedSourceRequest, attempt_request
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import HttpMethod, Transport, TransportFailure, TransportRequest

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
    *,
    scope: SeriesScope | None = None,
    known_series: tuple[SourceSeries, ...] = (),
) -> SourceAcquisition:
    groups: dict[tuple[str, str, RenderedWindow], list[tuple[ProductId, CzChmiSourceCoordinates]]] = {}
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
                if rendered.bounds is None:
                    raise FatalContractError("cz_chmi requires engine-established annual bounds")
                groups.setdefault((station_id, coordinates.file_code, rendered), []).append((product_id, coordinates))

    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []
    for (station_id, file_code, rendered), members in groups.items():
        bounds = rendered.bounds
        assert bounds is not None
        year = rendered.start
        cadence = "daily" if file_code == "DQ" else "hourly"
        url = f"{_BASE}/{cadence}/H_{station_id}_{file_code}_{year}.json"
        request = TransportRequest(method=HttpMethod.GET, url=url, headers={"Accept": "application/json"})
        response = attempt_request(transport, request)
        if isinstance(response, (TransportFailure, CredentialExchangeError)):
            call_id = uuid4().hex
            for product_id, _ in members:
                failures.append(
                    FailedSourceRequest(
                        uuid4().hex,
                        SERIES_MAPPINGS[product_id].source_series("cz_chmi", station_id, product_id),
                        SeriesWindow(
                            start=datetime.fromisoformat(bounds.start.isoformat()),
                            end=datetime.fromisoformat(bounds.end.isoformat()),
                        ),
                        request,
                        response,
                        call_id=call_id,
                    )
                )
            continue
        payloads.append(
            Payload(
                source_coordinates=SourceCoordinates(
                    CzChmiRequestCoordinates(file_code, tuple(coordinates.ts_con_id for _, coordinates in members))
                ),
                station_products=tuple((station_id, product_id) for product_id, _ in members),
                fetch_window=bounds,
                content=response.content,
                origin=SourceCallOrigin(
                    url=response.url,
                    request_parameters=response.request_parameters,
                    status_code=response.status_code,
                    retrieved_at=response.retrieved_at,
                    content_type=response.content_type if response.content_type is not None else UnknownOriginFact(),
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
    return SourceAcquisition(value=tuple(payloads), failed_requests=tuple(failures))

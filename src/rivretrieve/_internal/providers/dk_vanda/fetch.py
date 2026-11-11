"""Acquire VandA water-flows/water-levels/measurements-results-current pages.

One request per station-product pair, each covering the whole rendered
window: VandA has no pagination (research/dk-vanda-source-access.md, step 1,
reconfirmed step 4), so there is no cursor-chain or chunking logic here,
unlike `fi_syke`'s nextLink loop.
"""

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
from rivretrieve._internal.providers.dk_vanda.config import (
    ENDPOINT_PATH,
    REQUIRES_EXAMINATION_TYPE_SC,
    DkVandaSourceCoordinates,
)
from rivretrieve._internal.source_acquisition import FailedSourceRequest, SourceRequestTarget, attempt_request
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)

_BASE_URL = "https://vandah.miljoeportal.dk/api"


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
    """Fetch each station-product's whole rendered window in one request.

    A VandA HTTP 400 for an unresolved station/operator-station identity
    (research, step 1 and 4) is a request-shape error, not "this window has
    no observations": no `SourceResponseMeaning` mapping is supplied here, so
    it is retained as `SourceResponseMeaning.UNSPECIFIED`, exactly like any
    other undeclared failure, rather than being folded into an empty-result
    meaning it does not have.
    """
    if not stations or not products:
        raise FatalContractError("dk_vanda fetch requires at least one station and product")

    window = SeriesWindow(
        start=datetime.fromisoformat(fetch_window.start.isoformat()),
        end=datetime.fromisoformat(fetch_window.end.isoformat()),
    )
    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []

    for station in stations:
        for product in products:
            if product not in config.products:
                raise FatalContractError(f"dk_vanda product is absent from provider config: {product}")
            coordinates = config.products[product].coordinates.value
            if not isinstance(coordinates, DkVandaSourceCoordinates):
                raise FatalContractError(f"dk_vanda product has invalid source coordinates: {product}")
            windows = rendered_windows.get(product, ())
            if len(windows) != 1:
                raise FatalContractError(f"dk_vanda product requires exactly one rendered window: {product}")
            request = _request(station, coordinates, windows[0])
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


def _request(station: str, coordinates: DkVandaSourceCoordinates, rendered: RenderedWindow) -> TransportRequest:
    if rendered.stop is None:
        raise FatalContractError("dk_vanda requires a rendered window with an explicit stop")
    params: dict[str, str | int] = {"stationId": station, "from": rendered.start, "to": rendered.stop}
    if coordinates.endpoint in REQUIRES_EXAMINATION_TYPE_SC:
        params["examinationTypeSc"] = coordinates.examination_type_sc
    return TransportRequest(
        method=HttpMethod.GET,
        url=f"{_BASE_URL}/{ENDPOINT_PATH[coordinates.endpoint]}",
        params=params,
        headers={"Accept": "application/json"},
    )


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
        attempt_traces=response.attempt_traces,
    )

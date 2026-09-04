"""no_nve fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

from collections.abc import Mapping

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
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.no_nve.config import NoNveSourceCoordinates
from rivretrieve._internal.providers.no_nve.issue_codes import NoNveObservationIssueCodes
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

PROVIDER_ID = ProviderId("no_nve")
_URL = "https://hydapi.nve.no/api/v1/Observations"


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
) -> WithIssues[tuple[Payload, ...]]:
    resolved = tuple((product, _coordinates(product, config)) for product in products)
    payloads: list[Payload] = []
    issues: list[Issue] = []
    for station in stations:
        for product, coordinates in resolved:
            for window in rendered_windows[product]:
                reference_time = _reference_time(window)
                request = _request(station, coordinates, reference_time)
                try:
                    response = transport.send(request)
                except TransportFailure as error:
                    if error.reason is not TransportFailureReason.RETRY_EXHAUSTED:
                        raise
                    issues.append(_request_failed(station, product, coordinates, reference_time, error))
                    continue
                if response.status_code == 404:
                    issues.append(_not_found(station, product, coordinates, reference_time))
                    continue
                if not 200 <= response.status_code < 300:
                    raise FatalContractError(f"no_nve request returned unexpected HTTP status {response.status_code}")
                payloads.append(
                    Payload(
                        source_coordinates=SourceCoordinates(coordinates),
                        station_products=((station, product),),
                        fetch_window=fetch_window,
                        content=response.content,
                        origin=_origin(response),
                        prerequisite_calls=response.prerequisite_calls,
                    )
                )
    return WithIssues(value=tuple(payloads), issues=tuple(issues))


def _coordinates(product: ProductId, config: ProviderConfig) -> NoNveSourceCoordinates:
    try:
        value = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"no_nve product is absent from provider config: {product}") from error
    if not isinstance(value, NoNveSourceCoordinates):
        raise FatalContractError(f"no_nve product has invalid source coordinates: {product}")
    return value


def _reference_time(window: RenderedWindow) -> str:
    if window.stop is None:
        raise FatalContractError("no_nve requires a rendered window closed at both ends")
    return f"{window.start}/{window.stop}"


def _request(station: str, coordinates: NoNveSourceCoordinates, reference_time: str) -> TransportRequest:
    return TransportRequest(
        method=HttpMethod.GET,
        url=_URL,
        params={
            "StationId": station,
            "Parameter": coordinates.parameter,
            "ResolutionTime": coordinates.resolution_time,
            "ReferenceTime": reference_time,
        },
        headers={"Accept": "application/json"},
    )


def _origin(response: TransportResponse) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=response.url,
        request_parameters=response.request_parameters,
        status_code=response.status_code,
        retrieved_at=response.retrieved_at,
        content_type=response.content_type if response.content_type is not None else UnknownOriginFact(),
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


def _details(
    station: str,
    product: ProductId,
    coordinates: NoNveSourceCoordinates,
    reference_time: str,
) -> dict[str, object]:
    return {
        "station_id": station,
        "product_id": product,
        "source_coordinates": {
            "parameter": coordinates.parameter,
            "resolution_time": coordinates.resolution_time,
        },
        "reference_time": reference_time,
    }


def _not_found(
    station: str,
    product: ProductId,
    coordinates: NoNveSourceCoordinates,
    reference_time: str,
) -> Issue:
    details = _details(station, product, coordinates, reference_time)
    details["status_code"] = 404
    return Issue(
        severity="warning",
        code=NoNveObservationIssueCodes.HTTP_NOT_FOUND,
        message="No series available for station-product request (HTTP 404)",
        details=details,
        provider_id=PROVIDER_ID,
    )


def _request_failed(
    station: str,
    product: ProductId,
    coordinates: NoNveSourceCoordinates,
    reference_time: str,
    error: TransportFailure,
) -> Issue:
    details = _details(station, product, coordinates, reference_time)
    details.update({"failure_reason": error.reason.value, "attempts": error.attempts, "status_code": error.status_code})
    return Issue(
        severity="warning",
        code=NoNveObservationIssueCodes.SOURCE_REQUEST_FAILED,
        message="no_nve request failed after transport retries",
        details=details,
        provider_id=PROVIDER_ID,
    )

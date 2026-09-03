"""za_dws fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

One HyData.aspx request per (station, DataType, rendered window); every product sharing that
DataType is tagged on the same payload, so the two Point products never issue a second call.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

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
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.za_dws.config import ZaDwsDataType, ZaDwsSourceCoordinates
from rivretrieve._internal.providers.za_dws.issue_codes import ZaDwsObservationIssueCodes
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

PROVIDER_ID = ProviderId("za_dws")

_BASE_URL = "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx"
# The web form addresses a station's surface-water-level variable as "<station>100.00".
_STATION_VARIABLE_SUFFIX = "100.00"
_SITE_TYPE = "RIV"


@dataclass(frozen=True, slots=True)
class ZaDwsSourceRoute:
    """The HyData.aspx DataType one payload was requested with."""

    data_type: ZaDwsDataType


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
) -> WithIssues[tuple[Payload, ...]]:
    coordinates = {product: _coordinates(product, config) for product in products}
    calls: dict[tuple[ZaDwsDataType, str, str], dict[ProductId, None]] = {}
    for product in products:
        for window in rendered_windows[product]:
            if window.stop is None:
                raise FatalContractError("za_dws date windows must carry a rendered stop")
            calls.setdefault((coordinates[product].data_type, window.start, window.stop), {})[product] = None

    payloads: list[Payload] = []
    issues: list[Issue] = []
    for station in stations:
        for (data_type, start, stop), group in calls.items():
            group_products = tuple(group)
            request = _request(station, data_type, start, stop)
            try:
                response = transport.send(request)
            except TransportFailure as error:
                if error.reason is not TransportFailureReason.RETRY_EXHAUSTED:
                    raise
                issues.append(_request_failed(station, group_products, data_type, start, stop, error))
                continue
            if response.status_code == 404:
                issues.append(_not_found(station, group_products, data_type, start, stop))
                continue
            if not 200 <= response.status_code < 300:
                raise FatalContractError(f"za_dws request returned unexpected HTTP status {response.status_code}")
            payloads.append(
                Payload(
                    source_coordinates=SourceCoordinates(ZaDwsSourceRoute(data_type)),
                    station_products=tuple((station, product) for product in group_products),
                    fetch_window=fetch_window,
                    content=response.content,
                    origin=_origin(response),
                    prerequisite_calls=response.prerequisite_calls,
                )
            )
    return WithIssues(value=tuple(payloads), issues=tuple(issues))


def _coordinates(product: ProductId, config: ProviderConfig) -> ZaDwsSourceCoordinates:
    try:
        value = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"za_dws product is absent from provider config: {product}") from error
    if not isinstance(value, ZaDwsSourceCoordinates):
        raise FatalContractError(f"za_dws product has invalid source coordinates: {product}")
    return value


def _request(station: str, data_type: ZaDwsDataType, start: str, stop: str) -> TransportRequest:
    return TransportRequest(
        method=HttpMethod.GET,
        url=_BASE_URL,
        params={
            "Station": f"{station}{_STATION_VARIABLE_SUFFIX}",
            "DataType": data_type,
            "StartDT": start,
            "EndDT": stop,
            "SiteType": _SITE_TYPE,
        },
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
    station: str, products: tuple[ProductId, ...], data_type: ZaDwsDataType, start: str, stop: str
) -> dict[str, object]:
    return {
        "station_id": station,
        "product_ids": list(products),
        "data_type": data_type,
        "fetch_window": {"start": start, "end": stop},
    }


def _not_found(station: str, products: tuple[ProductId, ...], data_type: ZaDwsDataType, start: str, stop: str) -> Issue:
    details = _details(station, products, data_type, start, stop)
    details["status_code"] = 404
    return Issue(
        severity="warning",
        code=ZaDwsObservationIssueCodes.HTTP_NOT_FOUND,
        message="No data available for station-window request (HTTP 404)",
        details=details,
        provider_id=PROVIDER_ID,
    )


def _request_failed(
    station: str,
    products: tuple[ProductId, ...],
    data_type: ZaDwsDataType,
    start: str,
    stop: str,
    error: TransportFailure,
) -> Issue:
    details = _details(station, products, data_type, start, stop)
    details.update({"failure_reason": error.reason.value, "attempts": error.attempts, "status_code": error.status_code})
    return Issue(
        severity="warning",
        code=ZaDwsObservationIssueCodes.SOURCE_REQUEST_FAILED,
        message="za_dws request failed after transport retries",
        details=details,
        provider_id=PROVIDER_ID,
    )

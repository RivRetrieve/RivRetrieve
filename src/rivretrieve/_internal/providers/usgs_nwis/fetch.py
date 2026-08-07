"""usgs_nwis fetch : stations × products × rendered windows × FetchWindow × ProviderConfig → WithIssues[Payload[]]."""

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
from rivretrieve._internal.providers.usgs_nwis.config import UsgsNwisSourceCoordinates
from rivretrieve._internal.providers.usgs_nwis.issue_codes import UsgsNwisObservationIssueCodes
from rivretrieve._internal.transport import (
    HttpClient,
    HttpMethod,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

PROVIDER_ID = ProviderId("usgs_nwis")
_BASE_URL = "https://waterservices.usgs.gov/nwis/"


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
) -> WithIssues[tuple[Payload, ...]]:
    resolved_products: list[tuple[ProductId, SourceCoordinates, UsgsNwisSourceCoordinates, str, str]] = []
    for product_id in products:
        source_coordinates, coordinates = _resolve_coordinates(
            product_id,
            config,
        )
        (rendered_window,) = rendered_windows[product_id]
        assert rendered_window.stop is not None
        resolved_products.append(
            (product_id, source_coordinates, coordinates, rendered_window.start, rendered_window.stop)
        )
    client = HttpClient()
    payloads: list[Payload] = []
    issues: list[Issue] = []

    for station_id in stations:
        for product_id, source_coordinates, coordinates, start, end in resolved_products:
            request = _request(station_id, coordinates, start, end)
            try:
                response = client.send(request)
            except TransportFailure as error:
                if error.reason is not TransportFailureReason.RETRY_EXHAUSTED:
                    raise
                issues.append(
                    _transport_issue(
                        station_id,
                        product_id,
                        coordinates,
                        start,
                        end,
                        error,
                    )
                )
                continue

            if response.status_code == 404:
                issues.append(
                    _not_found_issue(
                        station_id,
                        product_id,
                        coordinates,
                        start,
                        end,
                    )
                )
                continue
            if not 200 <= response.status_code < 300:
                raise FatalContractError(f"usgs_nwis request returned unexpected HTTP status {response.status_code}")

            payloads.append(
                _payload(
                    source_coordinates,
                    station_id,
                    product_id,
                    fetch_window,
                    response,
                )
            )

    return WithIssues(value=tuple(payloads), issues=tuple(issues))


def _resolve_coordinates(
    product_id: ProductId,
    provider_config: ProviderConfig,
) -> tuple[SourceCoordinates, UsgsNwisSourceCoordinates]:
    try:
        product = provider_config.products[product_id]
    except KeyError as error:
        raise FatalContractError(f"usgs_nwis product is absent from provider config: {product_id}") from error
    source_coordinates = product.coordinates
    coordinates = source_coordinates.value
    if not isinstance(coordinates, UsgsNwisSourceCoordinates):
        raise FatalContractError(f"usgs_nwis product has invalid source coordinates: {product_id}")
    return source_coordinates, coordinates


def _request(
    station_id: str,
    coordinates: UsgsNwisSourceCoordinates,
    start: str | int | float,
    end: str | int | float,
) -> TransportRequest:
    params: dict[str, str | int | float | None] = {
        "format": "json",
        "sites": station_id,
        "startDT": start,
        "endDT": end,
        "parameterCd": coordinates.parameter_code,
    }
    if coordinates.statistic_code is not None:
        params["statCd"] = coordinates.statistic_code
    return TransportRequest(
        method=HttpMethod.GET,
        url=f"{_BASE_URL}{coordinates.endpoint}/",
        params=params,
        headers={"Accept": "application/json"},
    )


def _payload(
    source_coordinates: SourceCoordinates,
    station_id: str,
    product_id: ProductId,
    fetch_window: FetchWindow,
    response: TransportResponse,
) -> Payload:
    return Payload(
        source_coordinates=source_coordinates,
        station_products=((station_id, product_id),),
        fetch_window=fetch_window,
        content=response.content,
        origin=SourceCallOrigin(
            url=response.url,
            request_parameters=response.request_parameters,
            status_code=response.status_code,
            retrieved_at=response.retrieved_at,
            content_type=(response.content_type if response.content_type is not None else UnknownOriginFact()),
            source_path=UnknownOriginFact(),
            query=UnknownOriginFact(),
        ),
    )


def _call_details(
    station_id: str,
    product_id: ProductId,
    coordinates: UsgsNwisSourceCoordinates,
    start: str | int | float,
    end: str | int | float,
) -> dict[str, object]:
    return {
        "station_id": station_id,
        "product_id": product_id,
        "source_coordinates": {
            "endpoint": coordinates.endpoint,
            "parameter_code": coordinates.parameter_code,
            "statistic_code": coordinates.statistic_code,
        },
        "fetch_window": {"start": start, "end": end},
    }


def _not_found_issue(
    station_id: str,
    product_id: ProductId,
    coordinates: UsgsNwisSourceCoordinates,
    start: str | int | float,
    end: str | int | float,
) -> Issue:
    details = _call_details(
        station_id,
        product_id,
        coordinates,
        start,
        end,
    )
    details["status_code"] = 404
    return Issue(
        severity="warning",
        code=UsgsNwisObservationIssueCodes.HTTP_NOT_FOUND,
        message="No data available for station-product request (HTTP 404)",
        details=details,
        provider_id=PROVIDER_ID,
    )


def _transport_issue(
    station_id: str,
    product_id: ProductId,
    coordinates: UsgsNwisSourceCoordinates,
    start: str | int | float,
    end: str | int | float,
    error: TransportFailure,
) -> Issue:
    details = _call_details(
        station_id,
        product_id,
        coordinates,
        start,
        end,
    )
    details.update(
        {
            "failure_reason": error.reason.value,
            "attempts": error.attempts,
            "status_code": error.status_code,
        }
    )
    return Issue(
        severity="warning",
        code=UsgsNwisObservationIssueCodes.SOURCE_REQUEST_FAILED,
        message="usgs_nwis request failed after transport retries",
        details=details,
        provider_id=PROVIDER_ID,
    )

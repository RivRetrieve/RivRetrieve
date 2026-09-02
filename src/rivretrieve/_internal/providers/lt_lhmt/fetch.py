"""lt_lhmt fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

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
from rivretrieve._internal.providers.lt_lhmt.config import LtLhmtSourceCoordinates
from rivretrieve._internal.providers.lt_lhmt.issue_codes import LtLhmtObservationIssueCodes
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

PROVIDER_ID = ProviderId("lt_lhmt")


@dataclass(frozen=True, slots=True)
class LtLhmtHistoricalRoute:
    """The one source route that co-publishes both configured products."""


_BASE_URL = "https://api.meteo.lt/v1/hydro-stations"


def fetch(
    stations: tuple[str, ...],
    products: tuple[ProductId, ...],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    fetch_window: FetchWindow,
    config: ProviderConfig,
    transport: Transport,
) -> WithIssues[tuple[Payload, ...]]:
    for product in products:
        _coordinates(product, config)
    groups: dict[tuple[str, str | None], list[ProductId]] = {}
    for product in products:
        for window in rendered_windows[product]:
            groups.setdefault((window.start, window.stop), []).append(product)

    payloads: list[Payload] = []
    issues: list[Issue] = []
    for station in stations:
        for (start, stop), group_products in groups.items():
            request = _request(station, start, stop)
            try:
                response = transport.send(request)
            except TransportFailure as error:
                if error.reason is not TransportFailureReason.RETRY_EXHAUSTED:
                    raise
                issues.append(_request_failed(station, tuple(group_products), start, stop, error))
                continue
            if response.status_code == 404:
                issues.append(_not_found(station, tuple(group_products), start, stop))
                continue
            if not 200 <= response.status_code < 300:
                raise FatalContractError(f"lt_lhmt request returned unexpected HTTP status {response.status_code}")
            payloads.append(
                Payload(
                    source_coordinates=SourceCoordinates(LtLhmtHistoricalRoute()),
                    station_products=tuple((station, product) for product in group_products),
                    fetch_window=fetch_window,
                    content=response.content,
                    origin=_origin(response),
                )
            )
    return WithIssues(value=tuple(payloads), issues=tuple(issues))


def _coordinates(product: ProductId, config: ProviderConfig) -> LtLhmtSourceCoordinates:
    try:
        value = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"lt_lhmt product is absent from provider config: {product}") from error
    if not isinstance(value, LtLhmtSourceCoordinates):
        raise FatalContractError(f"lt_lhmt product has invalid source coordinates: {product}")
    return value


def _request(station: str, start: str, stop: str | None) -> TransportRequest:
    if stop is not None:
        raise FatalContractError("lt_lhmt year-month windows must not have a stop value")
    return TransportRequest(
        method=HttpMethod.GET,
        url=f"{_BASE_URL}/{station}/observations/historical/{start}",
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


def _details(station: str, products: tuple[ProductId, ...], start: str, stop: str | None) -> dict[str, object]:
    return {
        "station_id": station,
        "product_ids": list(products),
        "fetch_window": {"start": start, "end": stop},
    }


def _not_found(station: str, products: tuple[ProductId, ...], start: str, stop: str | None) -> Issue:
    details = _details(station, products, start, stop)
    details["status_code"] = 404
    return Issue(
        severity="warning",
        code=LtLhmtObservationIssueCodes.HTTP_NOT_FOUND,
        message="No data available for station-window request (HTTP 404)",
        details=details,
        provider_id=PROVIDER_ID,
    )


def _request_failed(
    station: str,
    products: tuple[ProductId, ...],
    start: str,
    stop: str | None,
    error: TransportFailure,
) -> Issue:
    details = _details(station, products, start, stop)
    details.update({"failure_reason": error.reason.value, "attempts": error.attempts, "status_code": error.status_code})
    return Issue(
        severity="warning",
        code=LtLhmtObservationIssueCodes.SOURCE_REQUEST_FAILED,
        message="lt_lhmt request failed after transport retries",
        details=details,
        provider_id=PROVIDER_ID,
    )

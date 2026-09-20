"""no_nve fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime

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
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.no_nve.config import NoNveSourceCoordinates
from rivretrieve._internal.source_acquisition import FailedSourceRequest, attempt_series_request
from rivretrieve._internal.source_series import (
    PhysicalFacts,
    RestrictionKind,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    stable_id,
)
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest, TransportResponse

_URL = "https://hydapi.nve.no/api/v1/Observations"


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
    resolved = tuple((product, _coordinates(product, config)) for product in products)
    payloads: list[Payload] = []
    issues: list[Issue] = []
    failed_requests: list[FailedSourceRequest] = []
    for station in stations:
        for product, coordinates in resolved:
            matching = tuple(
                item
                for item in known_series
                if item.station_id == station and item.product_id == product and (scope is None or scope.matches(item))
            )
            versions = {
                int(item.identity.published_id)
                for item in matching
                if item.identity.namespace == "HydAPI.version"
                and item.identity.published_id is not None
                and item.identity.published_id.isdecimal()
            }
            if coordinates.version_number is not None:
                versions.add(coordinates.version_number)
            if scope is not None and scope.restriction is RestrictionKind.EXPLICIT:
                versions.update(int(value) for value in scope.variants if value.isascii() and value.isdecimal())
            if not versions:
                issues.append(
                    Issue(
                        severity="warning",
                        code="source.inventory_unresolved",
                        message="No established HydAPI version selector is available; upstream default is not all-series retrieval",
                        details={"station_id": station, "product_id": product},
                        provider_id=ProviderId("no_nve"),
                    )
                )
                continue
            if scope is None or scope.restriction is RestrictionKind.ALL:
                issues.append(
                    Issue(
                        severity="warning",
                        code="source.inventory_unresolved",
                        message="HydAPI enumeration uses the acquired catalogue version inventory; current or historical completeness remains unresolved",
                        details={
                            "station_id": station,
                            "product_id": product,
                            "versions": sorted(versions),
                            "inventory_scope": (scope or SeriesScope())
                            .model_copy(
                                update={
                                    "provider_ids": ("no_nve",),
                                    "station_ids": (station,),
                                    "product_ids": (str(product),),
                                }
                            )
                            .model_dump(mode="json"),
                        },
                        provider_id=ProviderId("no_nve"),
                    )
                )
            for version in sorted(versions):
                concrete = replace(coordinates, version_number=version)
                for window in rendered_windows[product]:
                    reference_time = _reference_time(window)
                    request = _request(station, concrete, reference_time)
                    target = next((item for item in matching if item.identity.published_id == str(version)), None)
                    if target is None:
                        identifier = stable_id(
                            "no_nve",
                            station,
                            "HydAPI.requested_version",
                            concrete.parameter,
                            str(version),
                            concrete.resolution_time,
                        )
                        target = SourceSeries(
                            series_id=identifier,
                            provider_id="no_nve",
                            station_id=station,
                            product_id=product,
                            identity=SourceIdentity(
                                namespace="HydAPI.requested_version",
                                published_id=None,
                                origin="mapping",
                                evidence=(
                                    f"Caller requested documented VersionNumber selector {version}; source identity remains unestablished",
                                ),
                            ),
                            variant=str(version),
                            facts=(PhysicalFacts(facts_id=stable_id(identifier, "unestablished")),),
                        )
                    attempted = attempt_series_request(
                        transport,
                        request,
                        target,
                        SeriesWindow(
                            start=datetime.fromisoformat(fetch_window.start.isoformat()),
                            end=datetime.fromisoformat(fetch_window.end.isoformat()),
                        ),
                    )
                    if isinstance(attempted, FailedSourceRequest):
                        failed_requests.append(attempted)
                        continue
                    response = attempted
                    payloads.append(
                        Payload(
                            source_coordinates=SourceCoordinates(concrete),
                            station_products=((station, product),),
                            fetch_window=fetch_window,
                            content=response.content,
                            origin=_origin(response),
                            prerequisite_calls=response.prerequisite_calls,
                            scope=scope,
                            known_series=tuple(item for item in matching if item.identity.published_id == str(version)),
                        )
                    )
    return SourceAcquisition(value=tuple(payloads), issues=tuple(issues), failed_requests=tuple(failed_requests))


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
            "VersionNumber": coordinates.version_number,
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

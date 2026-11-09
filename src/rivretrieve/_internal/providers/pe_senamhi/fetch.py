"""Acquire bounded SENAMHI partitions while preserving the complete source bytes.

Hourly responses may extend before their planned ownership interval. Integration
must enforce that interval before combining responses, including revised values.
This module leaves parsing and public registration to their respective stages.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import (
    Payload,
    RenderedWindow,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    UnknownOriginFact,
    WindowDeclaration,
    WindowGranularity,
    WindowRenderingVocabulary,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.pe_senamhi.series import series_mappings
from rivretrieve._internal.source_acquisition import FailedSourceRequest, attempt_request
from rivretrieve._internal.source_series import OutcomeStatus, RetrievalOutcome, SeriesScope, SeriesWindow, SourceSeries
from rivretrieve._internal.transport import HttpMethod, Transport, TransportFailure, TransportRequest, TransportResponse


@dataclass(frozen=True, slots=True)
class SenamhiSourceCoordinates:
    subsystem: Literal["phisis", "monthly_archive"]
    resolution: Literal["DAILY", "HOURLY"] | None
    variable: str
    unit: str

    def __post_init__(self) -> None:
        series_mappings(self.subsystem, self.resolution, self.variable, self.unit)


def window_declaration(coordinates: SenamhiSourceCoordinates) -> WindowDeclaration:
    """Declare request partitions, independently of observation frequency."""
    if coordinates.subsystem == "monthly_archive":
        return WindowDeclaration(
            WindowGranularity("year-month"), WindowRenderingVocabulary.YEAR_MONTH, StopConvention.INCLUSIVE
        )
    if coordinates.resolution == "DAILY":
        return WindowDeclaration(
            WindowGranularity("year"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE, year_start_month=9
        )
    return WindowDeclaration(
        WindowGranularity("fixed-backward-span"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE, size=2
    )


def fetch(
    stations: tuple[str, ...],
    coordinates: Mapping[ProductId, SenamhiSourceCoordinates],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    transport: Transport,
    *,
    scope: SeriesScope | None = None,
    known_series: tuple[SourceSeries, ...] = (),
) -> SourceAcquisition:
    """Acquire every rendered partition using one already resolved transport.

    Bytes retain all returned rows, including the hourly prefix outside the
    disjoint planned interval in ``Payload.fetch_window``. That interval defines
    ownership for later shared integration; acquisition does not clip source
    bytes. Successful empty responses never stop traversal. No period-list or
    invented historical boundary restricts requests.
    """
    groups: dict[tuple[str, str | None, str | None, str | None, RenderedWindow], list[ProductId]] = {}
    for product, route in coordinates.items():
        if not isinstance(route, SenamhiSourceCoordinates) or not rendered_windows.get(product):
            raise FatalContractError("SENAMHI requires coordinates and planned windows for each product")
        for window in rendered_windows[product]:
            if window.bounds is None:
                raise FatalContractError("SENAMHI requires engine-established partition bounds")
            key = (
                route.subsystem,
                route.resolution,
                route.variable if route.subsystem == "phisis" else None,
                route.unit if route.subsystem == "phisis" else None,
                window,
            )
            groups.setdefault(key, []).append(product)
    payloads = []
    failures = []
    outcomes = []
    issues = []
    acquired_series: dict[str, SourceSeries] = {}
    for station in stations:
        for (_, _, _, _, window), products in groups.items():
            route = coordinates[products[0]]
            request = _request(station, route, window)
            response = attempt_request(transport, request)
            assert window.bounds is not None
            interval = SeriesWindow(
                start=datetime.fromisoformat(window.bounds.start.isoformat()),
                end=datetime.fromisoformat(window.bounds.end.isoformat()),
            )
            definitions = tuple(
                mapping.source_series("pe_senamhi", station, product)
                for product in products
                for mapping in series_mappings(
                    coordinates[product].subsystem,
                    coordinates[product].resolution,
                    coordinates[product].variable,
                    coordinates[product].unit,
                ).values()
            )
            acquired_series.update((definition.series_id, definition) for definition in definitions)
            if isinstance(response, (TransportFailure, CredentialExchangeError)):
                call_id = uuid4().hex
                failures.extend(
                    FailedSourceRequest(uuid4().hex, definition, interval, request, response, call_id=call_id)
                    for definition in definitions
                )
                continue
            payload = Payload(
                source_coordinates=SourceCoordinates(route),
                station_products=tuple((station, product) for product in products),
                fetch_window=window.bounds,
                content=response.content,
                origin=_origin(response),
                prerequisite_calls=response.prerequisite_calls,
                scope=scope,
                known_series=known_series,
                attempt_traces=response.attempt_traces,
            )
            payloads.append(payload)
            reason = _response_failure(response.content, route, station)
            if reason is not None:
                for definition in definitions:
                    outcome = RetrievalOutcome(
                        outcome_id=uuid4().hex,
                        series_id=definition.series_id,
                        station_id=station,
                        product_id=definition.product_id,
                        window=interval,
                        status=OutcomeStatus.FAILED,
                        facts_ids=tuple(fact.facts_id for fact in definition.facts),
                        reason=reason,
                        retrieved_at=response.retrieved_at,
                        calls=(payload.acquisition_id,),
                    )
                    outcomes.append(outcome)
                    issues.append(
                        Issue(
                            severity="error",
                            code="source.response_failed",
                            message=reason,
                            provider_id=ProviderId("pe_senamhi"),
                            details={
                                "station_id": station,
                                "product_id": definition.product_id,
                                "series_id": definition.series_id,
                                "outcome_id": outcome.outcome_id,
                                "window": interval.model_dump(mode="json"),
                            },
                        )
                    )
    return SourceAcquisition(
        value=tuple(payloads),
        series=tuple(acquired_series.values()),
        failed_requests=tuple(failures),
        outcomes=tuple(outcomes),
        issues=tuple(issues),
    )


def _request(station: str, route: SenamhiSourceCoordinates, window: RenderedWindow) -> TransportRequest:
    base = "https://servicios.senamhi.gob.pe/api"
    if route.subsystem == "monthly_archive":
        if window.stop is not None:
            raise FatalContractError("SENAMHI monthly selectors require year-month rendering")
        return TransportRequest(
            HttpMethod.GET,
            f"{base}/station/stations/{station}/readings",
            params={"period": window.start.replace("-", "")},
        )
    if window.stop is None:
        raise FatalContractError("SENAMHI PHISIS selectors require rendered date stops")
    clock = "T23:59" if route.resolution == "DAILY" else "T23:59:59"
    return TransportRequest(
        HttpMethod.GET,
        f"{base}/hydrology/stations/{station}/hydrogram",
        params={"type": route.resolution, "variable": route.variable, "date": window.stop + clock},
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
        attempts=response.attempts,
    )


def _response_failure(content: bytes, route: SenamhiSourceCoordinates, station: str) -> str | None:
    try:
        document = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return "Malformed SENAMHI JSON response"
    if not isinstance(document, dict) or type(document.get("status")) is not bool:
        return "Malformed SENAMHI response envelope"
    if not document["status"]:
        message = document.get("message")
        return "SENAMHI failed response: " + (message if isinstance(message, str) else "unpublished reason")
    data = document.get("data")
    if not isinstance(data, dict):
        return "Malformed SENAMHI response data"
    if route.subsystem == "monthly_archive":
        if not isinstance(data.get("columns"), list) or not isinstance(data.get("readings"), list):
            return "Malformed SENAMHI monthly response structure"
    else:
        rows = "daily" if route.resolution == "DAILY" else "hourly"
        if not isinstance(data.get(rows), list) or any(not isinstance(row, dict) for row in data[rows]):
            return "Malformed SENAMHI PHISIS response structure"
        identity = data.get("station")
        if not isinstance(identity, dict) or identity.get("code") != station:
            return "SENAMHI response does not match the requested station"
        if (data.get("type"), data.get("variable"), data.get("unit")) != (route.resolution, route.variable, route.unit):
            return "SENAMHI response does not match the requested product"
    return None

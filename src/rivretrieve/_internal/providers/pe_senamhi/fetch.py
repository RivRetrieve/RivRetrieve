"""Acquire bounded SENAMHI partitions while preserving the complete source bytes.

Hourly responses may extend before their planned ownership interval. Integration
must enforce that interval before combining responses, including revised values.
This module leaves parsing and public registration to their respective stages.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from datetime import datetime

from rivretrieve._internal.coverage import RequestedInterval
from rivretrieve._internal.engine import (
    FetchWindow,
    ProductConfig,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownTemporalSupport,
    WindowDeclaration,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.pe_senamhi.parse import interpret_planned_group
from rivretrieve._internal.providers.pe_senamhi.series import (
    SenamhiSourceCoordinates as SenamhiSourceCoordinates,
)
from rivretrieve._internal.providers.pe_senamhi.series import (
    series_mappings,
)
from rivretrieve._internal.request_planning import (
    ConsumerNeed,
    LookupResolution,
    ObservationPlan,
    PlannedLookup,
    PlannedObservationRequest,
    _merge_fetch_windows,
    execute_planned_acquisition,
)
from rivretrieve._internal.source_series import OutcomeStatus, SeriesScope, SeriesWindow, SourceSeries, TimeAxis
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest


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


class PeSenamhiRequestPlanner:
    """Coalesce SENAMHI monthly archive requests while preserving separate PHISIS routes."""

    def plan_lookups(
        self,
        needs: tuple[ConsumerNeed, ...],
        config: ProviderConfig,
    ) -> tuple[PlannedLookup, ...]:
        del needs, config
        return ()

    def plan_observations(
        self,
        needs: tuple[ConsumerNeed, ...],
        lookups: Mapping[tuple[Hashable, str, ProductId], LookupResolution],
        config: ProviderConfig,
    ) -> ObservationPlan:
        del lookups
        groups: dict[tuple[str, str, str | None, str | None, str | None, RenderedWindow], list[ConsumerNeed]] = {}
        for need in needs:
            try:
                route = config.products[need.product].coordinates.value
            except KeyError as error:
                raise FatalContractError(f"SENAMHI product is absent from provider config: {need.product}") from error
            if not isinstance(route, SenamhiSourceCoordinates) or not need.rendered:
                raise FatalContractError("SENAMHI requires coordinates and planned windows for each product")
            for window in need.rendered:
                if window.bounds is None:
                    raise FatalContractError("SENAMHI requires engine-established partition bounds")
                key = (
                    need.station,
                    route.subsystem,
                    route.resolution,
                    route.variable if route.subsystem == "phisis" else None,
                    route.unit if route.subsystem == "phisis" else None,
                    window,
                )
                groups.setdefault(key, []).append(need)

        requests: list[PlannedObservationRequest] = []
        for (station, _sub, _res, _var, _unit, window), group_needs in groups.items():
            assert window.bounds is not None
            consumers = tuple(group_needs)
            head_route = config.products[consumers[0].product].coordinates.value
            assert isinstance(head_route, SenamhiSourceCoordinates)
            targets = tuple(
                mapping.source_series("pe_senamhi", station, consumer.product)
                for consumer in consumers
                for route in (config.products[consumer.product].coordinates.value,)
                if isinstance(route, SenamhiSourceCoordinates)
                for mapping in series_mappings(route.subsystem, route.resolution, route.variable, route.unit).values()
            )
            requests.append(
                PlannedObservationRequest(
                    consumers=consumers,
                    request=_request(station, head_route, window),
                    source_coordinates=SourceCoordinates(head_route),
                    fetch_window=window.bounds,
                    failure_targets=targets,
                    interpret_group=interpret_planned_group,
                )
            )
        return ObservationPlan(requests=tuple(requests))


def fetch(
    stations: tuple[str, ...],
    coordinates: Mapping[ProductId, SenamhiSourceCoordinates],
    rendered_windows: Mapping[ProductId, tuple[RenderedWindow, ...]],
    transport: Transport,
    *,
    scope: SeriesScope | None = None,
    known_series: tuple[SourceSeries, ...] = (),
    config: ProviderConfig | None = None,
) -> SourceAcquisition:
    """Acquire every rendered partition using one already resolved transport.

    Bytes retain all returned rows, including the hourly prefix outside the
    disjoint planned interval in ``Payload.fetch_window``. That interval defines
    ownership for later shared integration; acquisition does not clip source
    bytes. Successful empty responses never stop traversal. No period-list or
    invented historical boundary restricts requests.
    """
    all_bounds: list[FetchWindow] = []
    for product, route in coordinates.items():
        if not isinstance(route, SenamhiSourceCoordinates) or not rendered_windows.get(product):
            raise FatalContractError("SENAMHI requires coordinates and planned windows for each product")
        for win in rendered_windows[product]:
            if win.bounds is None:
                raise FatalContractError("SENAMHI requires engine-established partition bounds")
            all_bounds.append(win.bounds)
    if not stations or not coordinates:
        return SourceAcquisition(value=())

    effective_config = (
        config
        if config is not None
        else ProviderConfig(
            zone=ZoneValue("unknown"),
            products={
                product: ProductConfig(
                    SourceCoordinates(route),
                    Unit.M3_S if route.variable == "FLOW" else Unit.M,
                    UnknownTemporalSupport(),
                )
                for product, route in coordinates.items()
            },
        )
    )
    fetch_window = _merge_fetch_windows(all_bounds)
    start = datetime.fromisoformat(fetch_window.start.isoformat())
    end = datetime.fromisoformat(fetch_window.end.isoformat())
    interval = RequestedInterval(start, end, axis=TimeAxis.NATIVE)
    window = SeriesWindow(start=start, end=end, axis=TimeAxis.NATIVE)
    needs = tuple(
        ConsumerNeed(
            station=station,
            product=product,
            scope=(
                scope.model_copy(
                    update={
                        "provider_ids": ("pe_senamhi",),
                        "station_ids": (station,),
                        "product_ids": (str(product),),
                    }
                )
                if scope is not None
                else SeriesScope(provider_ids=("pe_senamhi",), station_ids=(station,), product_ids=(str(product),))
            ),
            known_series=known_series,
            interval=interval,
            window=window,
            fetch_window=fetch_window,
            rendered=rendered_windows[product],
        )
        for station in stations
        for product in coordinates
    )
    acquisition = execute_planned_acquisition(PeSenamhiRequestPlanner(), needs, effective_config, transport)
    failed_outcomes = tuple(
        outcome
        for item in acquisition.interpretations
        for outcome in item.parsed.outcomes
        if outcome.status is OutcomeStatus.FAILED
    )
    failed_issues = tuple(
        issue
        for item in acquisition.interpretations
        for issue in item.parsed.issues
        if issue.code == "source.response_failed"
    )
    return SourceAcquisition(
        value=acquisition.value,
        series=acquisition.series,
        failed_requests=acquisition.failed_requests,
        outcomes=failed_outcomes,
        issues=failed_issues,
        interpretations=acquisition.interpretations if config is not None else (),
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

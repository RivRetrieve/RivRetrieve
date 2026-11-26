"""Acquire Austria eHYD historical CSV and live JSON payloads with bounded failures."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from datetime import datetime
from typing import Literal, cast

from rivretrieve._internal.coverage import RequestedInterval
from rivretrieve._internal.engine import (
    FetchWindow,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCoordinates,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.at_ehyd.config import (
    AtEhydInfoCoordinates,
    AtEhydOwfCoordinates,
    AtEhydPegelCoordinates,
    AtEhydPegelEndpointCoordinates,
)
from rivretrieve._internal.providers.at_ehyd.parse import (
    parse_group,
    resolve_info_group,
)
from rivretrieve._internal.providers.at_ehyd.parse import (
    resolve_messstellen_info_files as resolve_messstellen_info_files,
)
from rivretrieve._internal.request_planning import (
    ConsumerNeed,
    LookupResolution,
    ObservationPlan,
    PlannedLookup,
    PlannedObservationRequest,
    ResolvedLookup,
    _merge_fetch_windows,
    execute_planned_acquisition,
)
from rivretrieve._internal.source_acquisition import SourceRequestTarget
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries, TimeAxis
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportRequest,
)

_INFO_URL = "https://ehyd.gv.at/services/Messstellen/info"
_OWF_URL = "https://ehyd.gv.at/services/MessstellenExtraData/owf"
_PEGEL_URLS: dict[Literal["pegel_bgis", "pegel_longterm"], str] = {
    "pegel_bgis": "https://ehyd.gv.at/services/Diagram/pegelBgis",
    "pegel_longterm": "https://ehyd.gv.at/services/Diagram/pegelLongterm",
}


class AtEhydRequestPlanner:
    """Deduplicate ``Messstellen/info`` prerequisite lookups and share Pegel Aktuell endpoints."""

    def _partition_needs(
        self,
        needs: tuple[ConsumerNeed, ...],
        config: ProviderConfig,
    ) -> tuple[
        dict[str, list[ConsumerNeed]],
        dict[str, dict[Literal["pegel_bgis", "pegel_longterm"], list[ConsumerNeed]]],
    ]:
        owf_by_station: dict[str, list[ConsumerNeed]] = {}
        pegel_by_station: dict[str, dict[Literal["pegel_bgis", "pegel_longterm"], list[ConsumerNeed]]] = {}
        for need in needs:
            try:
                product_config = config.products[need.product]
            except KeyError as error:
                raise FatalContractError(f"at_ehyd product is absent from provider config: {need.product}") from error
            if need.rendered != ():
                raise FatalContractError(
                    f"at_ehyd source-fixed product received unexpected rendered windows: {need.product}"
                )
            coords = product_config.coordinates.value
            if isinstance(coords, AtEhydOwfCoordinates):
                owf_by_station.setdefault(need.station, []).append(need)
            elif isinstance(coords, AtEhydPegelCoordinates):
                pegel_by_station.setdefault(need.station, {}).setdefault(coords.subsystem, []).append(need)
            else:
                raise FatalContractError(f"at_ehyd product has invalid source coordinates: {need.product}")
        return owf_by_station, pegel_by_station

    def plan_lookups(
        self,
        needs: tuple[ConsumerNeed, ...],
        config: ProviderConfig,
    ) -> tuple[PlannedLookup, ...]:
        owf_by_station, _ = self._partition_needs(needs, config)
        return tuple(
            PlannedLookup(
                key=("at_ehyd_info", station),
                consumers=tuple(station_needs),
                request=TransportRequest(
                    method=HttpMethod.GET,
                    url=_INFO_URL,
                    params={"hzbnr": station},
                    headers={"Accept": "application/json"},
                ),
                source_coordinates=SourceCoordinates(AtEhydInfoCoordinates()),
                fetch_window=_merge_fetch_windows([item.fetch_window for item in station_needs]),
                window_in_identity=False,
                emit_payload=True,
                resolve_payload=resolve_info_group,
            )
            for station, station_needs in owf_by_station.items()
        )

    def plan_observations(
        self,
        needs: tuple[ConsumerNeed, ...],
        lookups: Mapping[tuple[Hashable, str, ProductId], LookupResolution],
        config: ProviderConfig,
    ) -> ObservationPlan:
        owf_by_station, pegel_by_station = self._partition_needs(needs, config)
        requests: list[PlannedObservationRequest] = []
        for station in tuple(dict.fromkeys(need.station for need in needs)):
            for need in owf_by_station.get(station, ()):
                resolution = lookups.get((("at_ehyd_info", station), station, need.product))
                if not isinstance(resolution, ResolvedLookup) or not isinstance(resolution.value, Mapping):
                    continue
                file_nr = cast("Mapping[ProductId, int]", resolution.value).get(need.product)
                if file_nr is None:
                    continue
                requests.append(
                    PlannedObservationRequest(
                        consumers=(need,),
                        request=TransportRequest(
                            method=HttpMethod.GET,
                            url=_OWF_URL,
                            params={"id": station, "file": str(file_nr)},
                        ),
                        source_coordinates=config.products[need.product].coordinates,
                        fetch_window=need.fetch_window,
                        prerequisite_acquisition_ids=(resolution.acquisition_id,),
                        failure_targets=(_request_target(station, need.product, need.known_series),),
                    )
                )

            for subsystem, group_needs in pegel_by_station.get(station, {}).items():
                consumers = tuple(group_needs)
                coordinates = (
                    config.products[consumers[0].product].coordinates
                    if len(consumers) == 1
                    else SourceCoordinates(AtEhydPegelEndpointCoordinates(subsystem))
                )
                requests.append(
                    PlannedObservationRequest(
                        consumers=consumers,
                        request=TransportRequest(
                            method=HttpMethod.GET,
                            url=_PEGEL_URLS[subsystem],
                            params={"hzbnr": station},
                            headers={"Accept": "application/json"},
                        ),
                        source_coordinates=coordinates,
                        fetch_window=_merge_fetch_windows([item.fetch_window for item in consumers]),
                        failure_targets=tuple(
                            _request_target(station, item.product, item.known_series) for item in consumers
                        ),
                        interpret_group=parse_group if len(consumers) > 1 else None,
                    )
                )
        return ObservationPlan(requests=tuple(requests))


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
    """Fetch source-fixed eHYD responses while isolating independent route and file failures."""
    if not stations or not products:
        raise FatalContractError("at_ehyd fetch requires at least one station and product")
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
                        "provider_ids": ("at_ehyd",),
                        "station_ids": (station,),
                        "product_ids": (str(product),),
                    }
                )
                if scope is not None
                else SeriesScope(provider_ids=("at_ehyd",), station_ids=(station,), product_ids=(str(product),))
            ),
            known_series=known_series,
            interval=interval,
            window=window,
            fetch_window=fetch_window,
            rendered=rendered_windows.get(product, ()),
        )
        for station in stations
        for product in products
    )
    return execute_planned_acquisition(AtEhydRequestPlanner(), needs, config, transport)


def _request_target(
    station: str, product: ProductId, known_series: tuple[SourceSeries, ...]
) -> SourceSeries | SourceRequestTarget:
    matching = tuple(item for item in known_series if item.station_id == station and item.product_id == str(product))
    if len(matching) == 1:
        return matching[0]
    return SourceRequestTarget(station, str(product))

"""Plan and acquire full-history OPW Hydro-Data ``year.json`` and ``*_complete.zip`` payloads."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from datetime import datetime
from typing import Literal

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
from rivretrieve._internal.providers.ie_opw.config import (
    OpwCompleteZipCoordinates,
    OpwDailyYearJsonCoordinates,
    OpwDailyYearJsonEndpointCoordinates,
)
from rivretrieve._internal.providers.ie_opw.config import (
    validate_station_id as validate_station_id,
)
from rivretrieve._internal.providers.ie_opw.parse import parse_group
from rivretrieve._internal.providers.ie_opw.series import (
    COMPLETE_ZIP_BY_PARAM,
    reused_series,
    source_series,
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
from rivretrieve._internal.source_acquisition import SourceRequestTarget
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries, TimeAxis
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest

OPW_STATIONS_BASE_URL = "https://waterlevel.ie/hydro-data/data/internet/stations/0"


def daily_year_json_url(station: str, parameter: Literal["Q", "S", "TWater"]) -> str:
    """Build anonymous OPW Hydro-Data ``year.json`` endpoint URL for ``(station, parameter)``."""
    validate_station_id(station)
    if parameter not in ("Q", "S", "TWater"):
        raise FatalContractError(f"Unsupported ie_opw parameter for year.json: {parameter!r}")
    return f"{OPW_STATIONS_BASE_URL}/{station}/{parameter}/year.json"


def complete_zip_url(
    station: str,
    parameter: Literal["Q", "S", "TWater"],
    route: str | None = None,
) -> str:
    """Build anonymous OPW Hydro-Data ``*_complete.zip`` URL for ``(station, parameter)``."""
    validate_station_id(station)
    spec = COMPLETE_ZIP_BY_PARAM.get(parameter)
    if spec is None or (route is not None and route != spec.route):
        raise FatalContractError(f"Unsupported ie_opw complete.zip selector: parameter={parameter!r}, route={route!r}")
    return f"{OPW_STATIONS_BASE_URL}/{station}/{parameter}/{spec.route}"


def _request_target(
    station: str, product: ProductId, known_series: tuple[SourceSeries, ...]
) -> SourceSeries | SourceRequestTarget:
    matching = tuple(item for item in known_series if item.station_id == station and item.product_id == str(product))
    if len(matching) == 1:
        return matching[0]
    try:
        return reused_series(source_series(station, str(product), origin="mapping"), known_series)
    except FatalContractError:
        return SourceRequestTarget(station, str(product))


def _validated_coordinates(
    product: ProductId,
    config: ProviderConfig,
) -> OpwDailyYearJsonCoordinates | OpwCompleteZipCoordinates:
    try:
        product_config = config.products[product]
    except KeyError as error:
        raise FatalContractError(f"ie_opw product is absent from provider config: {product}") from error
    coords = product_config.coordinates.value
    if not isinstance(coords, (OpwDailyYearJsonCoordinates, OpwCompleteZipCoordinates)):
        raise FatalContractError(f"ie_opw product has invalid source coordinates: {product}")
    return coords


class IeOpwRequestPlanner:
    """Coalesce ``{param}/year.json`` triplets per ``(station, parameter)`` and plan ``*_complete.zip`` files."""

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
        if not needs:
            return ObservationPlan()

        stations: list[str] = []
        seen_stations: set[str] = set()
        year_groups: dict[str, dict[Literal["Q", "S", "TWater"], list[ConsumerNeed]]] = {}
        zip_items: dict[str, list[tuple[ConsumerNeed, OpwCompleteZipCoordinates]]] = {}

        for need in needs:
            validate_station_id(need.station)
            if need.station not in seen_stations:
                seen_stations.add(need.station)
                stations.append(need.station)
                year_groups[need.station] = {}
                zip_items[need.station] = []
            coords = _validated_coordinates(need.product, config)
            if need.rendered != ():
                raise FatalContractError(
                    f"ie_opw source-fixed product received unexpected rendered windows: {need.product}"
                )
            if isinstance(coords, OpwDailyYearJsonCoordinates):
                year_groups[need.station].setdefault(coords.parameter, []).append(need)
            else:
                zip_items[need.station].append((need, coords))

        requests: list[PlannedObservationRequest] = []
        for station in stations:
            for param, group_needs in year_groups[station].items():
                consumers = tuple(group_needs)
                coords_box = (
                    config.products[consumers[0].product].coordinates
                    if len(consumers) == 1
                    else SourceCoordinates(OpwDailyYearJsonEndpointCoordinates(param))
                )
                requests.append(
                    PlannedObservationRequest(
                        consumers=consumers,
                        request=TransportRequest(
                            method=HttpMethod.GET,
                            url=daily_year_json_url(station, param),
                        ),
                        source_coordinates=coords_box,
                        fetch_window=_merge_fetch_windows([need.fetch_window for need in consumers]),
                        failure_targets=tuple(
                            _request_target(station, need.product, need.known_series) for need in consumers
                        ),
                        interpret_group=parse_group if len(consumers) > 1 else None,
                    )
                )

            for need, zip_coords in zip_items[station]:
                requests.append(
                    PlannedObservationRequest(
                        consumers=(need,),
                        request=TransportRequest(
                            method=HttpMethod.GET,
                            url=complete_zip_url(station, zip_coords.parameter, zip_coords.route),
                        ),
                        source_coordinates=config.products[need.product].coordinates,
                        fetch_window=need.fetch_window,
                        failure_targets=(_request_target(station, need.product, need.known_series),),
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
    """Acquire full-history OPW ``year.json`` (grouped per parameter) and ``*_complete.zip`` payloads."""
    if not stations or not products:
        raise FatalContractError("ie_opw fetch requires at least one station and product")
    for station in stations:
        validate_station_id(station)
    for product in products:
        _validated_coordinates(product, config)

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
                        "provider_ids": ("ie_opw",),
                        "station_ids": (station,),
                        "product_ids": (str(product),),
                    }
                )
                if scope is not None
                else SeriesScope(provider_ids=("ie_opw",), station_ids=(station,), product_ids=(str(product),))
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
    return execute_planned_acquisition(IeOpwRequestPlanner(), needs, config, transport)

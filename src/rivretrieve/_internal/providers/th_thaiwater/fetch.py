"""Acquire independent source spans and retain their bounded failures.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from datetime import datetime

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
from rivretrieve._internal.providers.th_thaiwater.config import (
    SERIES_MAPPINGS,
    ThThaiWaterSourceCoordinates,
)
from rivretrieve._internal.providers.th_thaiwater.config import (
    ThThaiWaterGraphRoute as ThThaiWaterGraphRoute,
)
from rivretrieve._internal.providers.th_thaiwater.parse import parse_group
from rivretrieve._internal.request_planning import (
    ConsumerNeed,
    LookupResolution,
    ObservationPlan,
    PlannedLookup,
    PlannedObservationRequest,
    execute_planned_acquisition,
)
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries, TimeAxis
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest

_GRAPH_URL = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph"


class ThThaiWaterRequestPlanner:
    """Coalesce compatible graph requests per station across stage and discharge."""

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
        groups: dict[tuple[str, RenderedWindow], list[ConsumerNeed]] = {}
        for need in needs:
            _coordinates(need.product, config)
            for window in need.rendered:
                if window.bounds is None:
                    raise FatalContractError("th_thaiwater requires engine-established acquisition bounds")
                groups.setdefault((need.station, window), []).append(need)

        requests: list[PlannedObservationRequest] = []
        for (station, window), group_needs in groups.items():
            assert window.bounds is not None
            consumers = tuple(group_needs)
            requests.append(
                PlannedObservationRequest(
                    consumers=consumers,
                    request=_request(station, window.start, window.stop),
                    source_coordinates=SourceCoordinates(ThThaiWaterGraphRoute()),
                    fetch_window=window.bounds,
                    failure_targets=tuple(
                        SERIES_MAPPINGS[need.product].source_series("th_thaiwater", station, need.product)
                        for need in consumers
                    ),
                    interpret_group=parse_group,
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
                        "provider_ids": ("th_thaiwater",),
                        "station_ids": (station,),
                        "product_ids": (str(product),),
                    }
                )
                if scope is not None
                else SeriesScope(provider_ids=("th_thaiwater",), station_ids=(station,), product_ids=(str(product),))
            ),
            known_series=known_series,
            interval=interval,
            window=window,
            fetch_window=fetch_window,
            rendered=rendered_windows[product],
        )
        for station in stations
        for product in products
    )
    return execute_planned_acquisition(ThThaiWaterRequestPlanner(), needs, config, transport)


def _coordinates(product: ProductId, config: ProviderConfig) -> ThThaiWaterSourceCoordinates:
    try:
        value = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"th_thaiwater product is absent from provider config: {product}") from error
    if not isinstance(value, ThThaiWaterSourceCoordinates):
        raise FatalContractError(f"th_thaiwater product has invalid source coordinates: {product}")
    return value


def _request(station: str, start: str, stop: str | None) -> TransportRequest:
    if stop is None:
        raise FatalContractError("th_thaiwater date windows require an end date")
    return TransportRequest(
        method=HttpMethod.GET,
        url=_GRAPH_URL,
        params={
            "station_type": "tele_waterlevel",
            "station_id": station,
            "start_date": start,
            "end_date": stop,
        },
    )

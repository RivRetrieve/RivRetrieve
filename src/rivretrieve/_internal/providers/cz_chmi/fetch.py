"""Acquire independent CHMI annual files and retain shared-product failures.

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
from rivretrieve._internal.providers.cz_chmi.config import (
    SERIES_MAPPINGS,
    CzChmiRequestCoordinates,
    CzChmiSourceCoordinates,
)
from rivretrieve._internal.providers.cz_chmi.parse import parse_group
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

_BASE = "https://opendata.chmi.cz/hydrology/historical/data"


def _chmi_coordinates(product_id: ProductId, config: ProviderConfig) -> CzChmiSourceCoordinates:
    try:
        product = config.products[product_id]
    except KeyError as error:
        raise FatalContractError(f"cz_chmi product is absent from provider config: {product_id}") from error
    coordinates = product.coordinates.value
    if not isinstance(coordinates, CzChmiSourceCoordinates):
        raise FatalContractError(f"cz_chmi product has invalid source coordinates: {product_id}")
    return coordinates


class CzChmiRequestPlanner:
    """Coalesce annual CHMI file downloads across same-file products at one station."""

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
        groups: dict[tuple[str, str, RenderedWindow], list[tuple[ConsumerNeed, CzChmiSourceCoordinates]]] = {}
        for need in needs:
            coordinates = _chmi_coordinates(need.product, config)
            for rendered in need.rendered:
                if rendered.stop is not None:
                    raise FatalContractError("cz_chmi annual window must have no rendered stop")
                if rendered.bounds is None:
                    raise FatalContractError("cz_chmi requires engine-established annual bounds")
                groups.setdefault((need.station, coordinates.file_code, rendered), []).append((need, coordinates))

        requests: list[PlannedObservationRequest] = []
        for (station_id, file_code, rendered), members in groups.items():
            bounds = rendered.bounds
            assert bounds is not None
            year = rendered.start
            cadence = "daily" if file_code == "DQ" else "hourly"
            url = f"{_BASE}/{cadence}/H_{station_id}_{file_code}_{year}.json"
            consumers = tuple(need for need, _ in members)
            ts_con_ids = tuple(dict.fromkeys(coord.ts_con_id for _, coord in members))
            requests.append(
                PlannedObservationRequest(
                    consumers=consumers,
                    request=TransportRequest(method=HttpMethod.GET, url=url, headers={"Accept": "application/json"}),
                    source_coordinates=SourceCoordinates(CzChmiRequestCoordinates(file_code, ts_con_ids)),
                    fetch_window=bounds,
                    failure_targets=tuple(
                        SERIES_MAPPINGS[need.product].source_series("cz_chmi", station_id, need.product)
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
    """Acquire independent CHMI annual files for a legacy caller."""
    start = datetime.fromisoformat(fetch_window.start.isoformat())
    end = datetime.fromisoformat(fetch_window.end.isoformat())
    interval = RequestedInterval(start, end, axis=TimeAxis.NATIVE)
    window = SeriesWindow(start=start, end=end, axis=TimeAxis.NATIVE)
    needs = tuple(
        ConsumerNeed(
            station=station_id,
            product=product_id,
            scope=(
                scope.model_copy(
                    update={
                        "provider_ids": ("cz_chmi",),
                        "station_ids": (station_id,),
                        "product_ids": (str(product_id),),
                    }
                )
                if scope is not None
                else SeriesScope(provider_ids=("cz_chmi",), station_ids=(station_id,), product_ids=(str(product_id),))
            ),
            known_series=known_series,
            interval=interval,
            window=window,
            fetch_window=fetch_window,
            rendered=rendered_windows[product_id],
        )
        for station_id in stations
        for product_id in products
    )
    return execute_planned_acquisition(CzChmiRequestPlanner(), needs, config, transport)

"""Acquire independently exhaustive historical months and retain bounded failures.

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
from rivretrieve._internal.providers.lt_lhmt.config import (
    SERIES_MAPPINGS,
    LtLhmtSourceCoordinates,
)
from rivretrieve._internal.providers.lt_lhmt.config import (
    LtLhmtHistoricalRoute as LtLhmtHistoricalRoute,
)
from rivretrieve._internal.providers.lt_lhmt.parse import parse_group
from rivretrieve._internal.request_planning import (
    ConsumerNeed,
    LookupResolution,
    ObservationPlan,
    PlannedLookup,
    PlannedObservationRequest,
    execute_planned_acquisition,
)
from rivretrieve._internal.source_acquisition import SourceResponseMeaning
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries, TimeAxis
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportRequest,
)

_BASE_URL = "https://api.meteo.lt/v1/hydro-stations"
# Meteo.lt historical-route documentation: no stored station measurements.
_HISTORICAL_RESPONSE_MEANINGS = {404: SourceResponseMeaning.NO_OBSERVATIONS}


class LtLhmtRequestPlanner:
    """Coalesce Meteo.lt monthly requests across products sharing a station and month."""

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
                    raise FatalContractError("lt_lhmt requires engine-established monthly bounds")
                groups.setdefault((need.station, window), []).append(need)

        requests: list[PlannedObservationRequest] = []
        for (station, window), group_needs in groups.items():
            assert window.bounds is not None
            consumers = tuple(group_needs)
            requests.append(
                PlannedObservationRequest(
                    consumers=consumers,
                    request=_request(station, window.start, window.stop),
                    source_coordinates=SourceCoordinates(LtLhmtHistoricalRoute()),
                    fetch_window=window.bounds,
                    response_meanings=_HISTORICAL_RESPONSE_MEANINGS,
                    failure_targets=tuple(
                        SERIES_MAPPINGS[need.product].source_series("lt_lhmt", station, need.product)
                        for need in consumers
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
    for product in products:
        _coordinates(product, config)
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
                        "provider_ids": ("lt_lhmt",),
                        "station_ids": (station,),
                        "product_ids": (str(product),),
                    }
                )
                if scope is not None
                else SeriesScope(provider_ids=("lt_lhmt",), station_ids=(station,), product_ids=(str(product),))
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
    return execute_planned_acquisition(LtLhmtRequestPlanner(), needs, config, transport)


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

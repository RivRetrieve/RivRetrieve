"""Acquire BoM KiWIS getTimeseriesList/getTimeseriesValues payloads with bounded failures."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

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
from rivretrieve._internal.providers.au_bom.config import (
    AuBomTimeseriesListCoordinates as AuBomTimeseriesListCoordinates,
)
from rivretrieve._internal.providers.au_bom.config import (
    AuBomTimeseriesValuesBatchCoordinates,
    AuBomTimeseriesValuesCoordinates,
)
from rivretrieve._internal.providers.au_bom.parse import (
    parse_values_group,
    resolve_timeseries_list_group,
)
from rivretrieve._internal.providers.au_bom.parse import (
    resolve_timeseries_list as resolve_timeseries_list,
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
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest

_URL = "https://www.bom.gov.au/waterdata/services"
_LIST_RETURNFIELDS = "ts_id,ts_name,parametertype_name,ts_unitsymbol,station_no"
_VALUES_RETURNFIELDS = "Timestamp,Value,Quality Code,Quality Code Name"
_LIST_BATCH_LIMIT = 25
_VALUES_TS_ID_LIMIT = 20


def _base_params(request: str) -> dict[str, str]:
    return {"service": "kisters", "type": "queryServices", "request": request, "datasource": "0", "format": "json"}


@dataclass(frozen=True, slots=True)
class _ResolvedValuesItem:
    need: ConsumerNeed
    ts_ids: tuple[str, ...]
    start: str
    stop: str
    prereq: str


class AuBomRequestPlanner:
    """Plan station-batched ``getTimeseriesList`` lookups and bounded ``getTimeseriesValues`` calls."""

    def plan_lookups(
        self,
        needs: tuple[ConsumerNeed, ...],
        config: ProviderConfig,
    ) -> tuple[PlannedLookup, ...]:
        if not needs:
            return ()
        for need in needs:
            if need.product not in config.products:
                raise FatalContractError(f"au_bom product is absent from provider config: {need.product}")
            if not isinstance(config.products[need.product].coordinates.value, AuBomTimeseriesValuesCoordinates):
                raise FatalContractError(f"au_bom product has invalid source coordinates: {need.product}")
            if len(need.rendered) != 1:
                raise FatalContractError(f"au_bom product requires exactly one rendered window: {need.product}")

        unique_stations = tuple(dict.fromkeys(need.station for need in needs))
        lookups: list[PlannedLookup] = []
        for offset in range(0, len(unique_stations), _LIST_BATCH_LIMIT):
            batch = unique_stations[offset : offset + _LIST_BATCH_LIMIT]
            batch_set = set(batch)
            consumers = tuple(need for need in needs if need.station in batch_set)
            station_param = batch[0] if len(batch) == 1 else ",".join(batch)
            lookups.append(
                PlannedLookup(
                    key=("au_bom_list", batch),
                    consumers=consumers,
                    request=TransportRequest(
                        method=HttpMethod.GET,
                        url=_URL,
                        params={
                            **_base_params("getTimeseriesList"),
                            "station_no": station_param,
                            "returnfields": _LIST_RETURNFIELDS,
                        },
                    ),
                    source_coordinates=SourceCoordinates(AuBomTimeseriesListCoordinates()),
                    fetch_window=_merge_fetch_windows([need.fetch_window for need in consumers]),
                    window_in_identity=False,
                    emit_payload=True,
                    resolve_payload=resolve_timeseries_list_group,
                )
            )
        return tuple(lookups)

    def plan_observations(
        self,
        needs: tuple[ConsumerNeed, ...],
        lookups: Mapping[tuple[Hashable, str, ProductId], LookupResolution],
        config: ProviderConfig,
    ) -> ObservationPlan:
        batch_index_by_station: dict[str, tuple[str, ...]] = {}
        unique_stations = tuple(dict.fromkeys(need.station for need in needs))
        for offset in range(0, len(unique_stations), _LIST_BATCH_LIMIT):
            batch = unique_stations[offset : offset + _LIST_BATCH_LIMIT]
            for st in batch:
                batch_index_by_station[st] = batch

        resolved_items: list[_ResolvedValuesItem] = []
        for need in needs:
            key = (("au_bom_list", batch_index_by_station[need.station]), need.station, need.product)
            resolution = lookups.get(key)
            if not isinstance(resolution, ResolvedLookup):
                continue
            valid_map = cast("Mapping[tuple[str, ProductId], tuple[str, ...]]", resolution.value)
            ts_ids = valid_map.get((need.station, need.product), ())
            if not ts_ids:
                continue
            rendered = need.rendered[0]
            resolved_items.append(
                _ResolvedValuesItem(
                    need=need,
                    ts_ids=ts_ids,
                    start=rendered.start,
                    stop=rendered.stop or "",
                    prereq=resolution.acquisition_id,
                )
            )

        if not resolved_items:
            return ObservationPlan()

        # Single-station calls keep one getTimeseriesValues call per product for exact recorded compatibility.
        if len(unique_stations) == 1:
            return ObservationPlan(requests=tuple(_singleton_values_request(item, config) for item in resolved_items))

        by_window: dict[tuple[str, str], list[_ResolvedValuesItem]] = {}
        for item in resolved_items:
            by_window.setdefault((item.start, item.stop), []).append(item)

        requests: list[PlannedObservationRequest] = []
        for (start, stop), window_items in by_window.items():
            batches: list[list[_ResolvedValuesItem]] = []
            current: list[_ResolvedValuesItem] = []
            current_ts_count = 0
            for item in window_items:
                item_count = len(item.ts_ids)
                if current and current_ts_count + item_count > _VALUES_TS_ID_LIMIT:
                    batches.append(current)
                    current = [item]
                    current_ts_count = item_count
                else:
                    current.append(item)
                    current_ts_count += item_count
            if current:
                batches.append(current)

            for batch in batches:
                if len(batch) == 1:
                    requests.append(_singleton_values_request(batch[0], config))
                    continue
                all_ts_ids = [ts_id for item in batch for ts_id in item.ts_ids]
                consumers = tuple(item.need for item in batch)
                prereqs = tuple(dict.fromkeys(item.prereq for item in batch))
                batch_coords = AuBomTimeseriesValuesBatchCoordinates(
                    tuple((item.need.station, item.need.product, item.ts_ids) for item in batch)
                )
                requests.append(
                    PlannedObservationRequest(
                        consumers=consumers,
                        request=TransportRequest(
                            method=HttpMethod.GET,
                            url=_URL,
                            params={
                                **_base_params("getTimeseriesValues"),
                                "ts_id": ",".join(all_ts_ids),
                                "from": start,
                                "to": stop,
                                "returnfields": _VALUES_RETURNFIELDS,
                            },
                        ),
                        source_coordinates=SourceCoordinates(batch_coords),
                        fetch_window=_merge_fetch_windows([item.need.fetch_window for item in batch]),
                        prerequisite_acquisition_ids=prereqs,
                        failure_targets=tuple(
                            _request_target(item.need.station, item.need.product, item.need.known_series)
                            for item in batch
                        ),
                        interpret_group=parse_values_group,
                    )
                )
        return ObservationPlan(requests=tuple(requests))


def _singleton_values_request(item: _ResolvedValuesItem, config: ProviderConfig) -> PlannedObservationRequest:
    return PlannedObservationRequest(
        consumers=(item.need,),
        request=TransportRequest(
            method=HttpMethod.GET,
            url=_URL,
            params={
                **_base_params("getTimeseriesValues"),
                "ts_id": ",".join(item.ts_ids),
                "from": item.start,
                "to": item.stop,
                "returnfields": _VALUES_RETURNFIELDS,
            },
        ),
        source_coordinates=config.products[item.need.product].coordinates,
        fetch_window=item.need.fetch_window,
        prerequisite_acquisition_ids=(item.prereq,),
        failure_targets=(_request_target(item.need.station, item.need.product, item.need.known_series),),
    )


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
    """Resolve each station's live ts_id per product, then fetch bounded observation windows."""
    if not stations or not products:
        raise FatalContractError("au_bom fetch requires at least one station and product")
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
                        "provider_ids": ("au_bom",),
                        "station_ids": (station,),
                        "product_ids": (str(product),),
                    }
                )
                if scope is not None
                else SeriesScope(provider_ids=("au_bom",), station_ids=(station,), product_ids=(str(product),))
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
    return execute_planned_acquisition(AuBomRequestPlanner(), needs, config, transport)


def _request_target(
    station: str, product: ProductId, known_series: tuple[SourceSeries, ...]
) -> SourceSeries | SourceRequestTarget:
    matching = tuple(item for item in known_series if item.station_id == station and item.product_id == str(product))
    if len(matching) == 1:
        return matching[0]
    return SourceRequestTarget(station, str(product))

"""ba_fhmzbih fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

from collections.abc import Hashable, Mapping
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
from rivretrieve._internal.providers.ba_fhmzbih.config import (
    BaFhmzbihMetadataCoordinates as BaFhmzbihMetadataCoordinates,
)
from rivretrieve._internal.providers.ba_fhmzbih.config import (
    BaFhmzbihSourceCoordinates,
)
from rivretrieve._internal.providers.ba_fhmzbih.parse import (
    interpret_metadata_group,
)
from rivretrieve._internal.providers.ba_fhmzbih.parse import (
    interpret_metadata_payload as interpret_metadata_payload,
)
from rivretrieve._internal.providers.ba_fhmzbih.parse import (
    metadata_groups as metadata_groups,
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
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries, TimeAxis
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest

_METADATA_URL = "https://vodostaji.voda.ba/data/internet/layers/20/index.json"
_WORKBOOK_ROOT = "https://vodostaji.voda.ba/data/internet/stations"


class BaFhmzbihRequestPlanner:
    """Plan one deduplicated metadata index lookup followed by per-pair workbook GETs."""

    def plan_lookups(
        self,
        needs: tuple[ConsumerNeed, ...],
        config: ProviderConfig,
    ) -> tuple[PlannedLookup, ...]:
        del config
        if not needs:
            return ()
        for need in needs:
            if need.rendered != ():
                raise FatalContractError("ba_fhmzbih source-fixed product received an unexpected rendered window")
        return (
            PlannedLookup(
                key="metadata_index",
                consumers=needs,
                request=TransportRequest(
                    HttpMethod.GET, _METADATA_URL, params=None, headers={"Accept": "application/json"}
                ),
                source_coordinates=SourceCoordinates(BaFhmzbihMetadataCoordinates()),
                fetch_window=_merge_fetch_windows([need.fetch_window for need in needs]),
                window_in_identity=False,
                emit_payload=True,
                resolve_payload=interpret_metadata_group,
            ),
        )

    def plan_observations(
        self,
        needs: tuple[ConsumerNeed, ...],
        lookups: Mapping[tuple[Hashable, str, ProductId], LookupResolution],
        config: ProviderConfig,
    ) -> ObservationPlan:
        requests: list[PlannedObservationRequest] = []
        for need in needs:
            res = lookups.get(("metadata_index", need.station, need.product))
            if not isinstance(res, ResolvedLookup):
                continue
            groups = cast("tuple[dict[str, str], dict[str, str]]", res.value)[0]
            if need.station not in groups:
                continue
            product_config = config.products[need.product]
            coordinates = product_config.coordinates.value
            if not isinstance(coordinates, BaFhmzbihSourceCoordinates):
                raise FatalContractError(f"ba_fhmzbih product has invalid source coordinates: {need.product}")
            url = f"{_WORKBOOK_ROOT}/{groups[need.station]}/{need.station}/{coordinates.code}/{coordinates.workbook}"
            requests.append(
                PlannedObservationRequest(
                    consumers=(need,),
                    request=TransportRequest(
                        HttpMethod.GET,
                        url,
                        params=None,
                        headers={"Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                    ),
                    source_coordinates=product_config.coordinates,
                    fetch_window=need.fetch_window,
                    prerequisite_acquisition_ids=(res.acquisition_id,),
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
    if len(stations) != 1 or len(products) != 1:
        raise FatalContractError("ba_fhmzbih fetch requires exactly one station-product pair")
    start = datetime.fromisoformat(fetch_window.start.isoformat())
    end = datetime.fromisoformat(fetch_window.end.isoformat())
    interval = RequestedInterval(start, end, axis=TimeAxis.NATIVE)
    window = SeriesWindow(start=start, end=end, axis=TimeAxis.NATIVE)
    needs = tuple(
        ConsumerNeed(
            station=station,
            product=product,
            scope=scope
            or SeriesScope(provider_ids=("ba_fhmzbih",), station_ids=(station,), product_ids=(str(product),)),
            known_series=known_series,
            interval=interval,
            window=window,
            fetch_window=fetch_window,
            rendered=rendered_windows[product],
        )
        for station in stations
        for product in products
    )
    return execute_planned_acquisition(BaFhmzbihRequestPlanner(), needs, config, transport)

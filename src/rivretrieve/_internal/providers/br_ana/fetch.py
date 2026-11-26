"""Acquire independent source spans and retain their bounded failures.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
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
from rivretrieve._internal.providers.br_ana.config import (
    BrAnaDailySourceCoordinates,
    BrAnaSharedDailyCoordinates,
    BrAnaSharedTelemetryCoordinates,
    BrAnaSourceCoordinates,
)
from rivretrieve._internal.providers.br_ana.parse import parse_group
from rivretrieve._internal.providers.br_ana.series import describe_series
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

_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1"


@dataclass(frozen=True, slots=True)
class _PlannedMember:
    need: ConsumerNeed
    source: BrAnaSourceCoordinates | BrAnaDailySourceCoordinates
    target: SourceSeries


class BrAnaRequestPlanner:
    """Coalesce ANA requests across products/variants sharing an endpoint, station, and window."""

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
        groups: dict[tuple[str, str, RenderedWindow], list[_PlannedMember]] = {}
        for need in needs:
            station = need.station
            if not station.isascii() or not station.isdecimal() or str(int(station)) != station:
                raise FatalContractError("ANA station id must be a canonical decimal source code")
            source = config.products[need.product].coordinates.value
            if not isinstance(source, (BrAnaSourceCoordinates, BrAnaDailySourceCoordinates)):
                raise FatalContractError("ANA product requires documented source coordinates")
            default_target = describe_series(station, need.product, source)
            target = next(
                (item for item in need.known_series if item.series_id == default_target.series_id),
                default_target,
            )
            route_key = source.endpoint if isinstance(source, BrAnaDailySourceCoordinates) else "telemetry"
            for window in need.rendered:
                if window.bounds is None:
                    raise FatalContractError("ANA requires engine-established acquisition bounds")
                if window.stop is None:
                    raise FatalContractError("ANA source requires an inclusive date stop")
                groups.setdefault((station, route_key, window), []).append(_PlannedMember(need, source, target))

        requests: list[PlannedObservationRequest] = []
        for (station, _route_key, window), members in groups.items():
            assert window.bounds is not None
            head_source = members[0].source
            if isinstance(head_source, BrAnaDailySourceCoordinates):
                url = f"https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/{head_source.endpoint}/v1"
                parameters: dict[str, str | int] = {
                    "Código da Estação": int(station),
                    "Tipo Filtro Data": "DATA_LEITURA",
                    "Data Inicial (yyyy-MM-dd)": window.start,
                    "Data Final (yyyy-MM-dd)": window.stop or "",
                }
                shared_coords = (
                    SourceCoordinates(head_source)
                    if len(members) == 1
                    else SourceCoordinates(BrAnaSharedDailyCoordinates(head_source.endpoint, head_source.field_prefix))
                )
            else:
                url = _URL
                parameters = {
                    "Código da Estação": int(station),
                    "Tipo Filtro Data": "DATA_LEITURA",
                    "Data de Busca (yyyy-MM-dd)": window.stop or "",
                    "Range Intervalo de busca": "DIAS_30",
                }
                shared_coords = (
                    SourceCoordinates(head_source)
                    if len(members) == 1
                    else SourceCoordinates(BrAnaSharedTelemetryCoordinates())
                )
            consumers = tuple(member.need for member in members)
            requests.append(
                PlannedObservationRequest(
                    consumers=consumers,
                    request=TransportRequest(method=HttpMethod.GET, url=url, params=parameters),
                    source_coordinates=shared_coords,
                    fetch_window=window.bounds,
                    failure_targets=tuple(member.target for member in members),
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
                        "provider_ids": ("br_ana",),
                        "station_ids": (station,),
                        "product_ids": (str(product),),
                    }
                )
                if scope is not None
                else SeriesScope(provider_ids=("br_ana",), station_ids=(station,), product_ids=(str(product),))
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
    return execute_planned_acquisition(BrAnaRequestPlanner(), needs, config, transport)

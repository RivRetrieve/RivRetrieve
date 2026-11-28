"""Acquire Slovenia ARSO hydrological archive CSVs and operational amp HTML tables."""

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
from rivretrieve._internal.providers.si_arso.config import (
    SiArsoAmpCoordinates,
    SiArsoArchiveCoordinates,
)
from rivretrieve._internal.providers.si_arso.config import (
    SiArsoRouteCoordinates as SiArsoRouteCoordinates,
)
from rivretrieve._internal.providers.si_arso.parse import parse_group
from rivretrieve._internal.providers.si_arso.series import validate_station_id
from rivretrieve._internal.request_planning import (
    ConsumerNeed,
    LookupResolution,
    ObservationPlan,
    PlannedLookup,
    PlannedObservationRequest,
    execute_planned_acquisition,
)
from rivretrieve._internal.source_acquisition import SourceRequestTarget
from rivretrieve._internal.source_series import SeriesScope, SeriesWindow, SourceSeries, TimeAxis
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportRequest,
)

ARCHIVE_URL = "https://vode.arso.gov.si/hidarhiv/pov_arhiv_tab.php"
AMP_BASE_URL = "https://www.arso.gov.si/vode/podatki/amp"


def _validate_archive_year_pair(rendered: RenderedWindow) -> tuple[str, str]:
    if rendered.stop is None or len(rendered.start) < 4 or len(rendered.stop) < 4:
        raise FatalContractError(f"si_arso archive rendered window must carry start and stop dates: {rendered!r}")
    start_year = rendered.start[:4]
    stop_year = rendered.stop[:4]
    if not (start_year.isascii() and start_year.isdigit() and stop_year.isascii() and stop_year.isdigit()):
        raise FatalContractError(f"si_arso archive rendered window has invalid year endpoints: {rendered!r}")
    if int(start_year) > int(stop_year):
        raise FatalContractError(f"si_arso archive start year exceeds stop year: {start_year}..{stop_year}")
    return start_year, stop_year


def _request_target(
    station: str, product: ProductId, known_series: tuple[SourceSeries, ...]
) -> SourceSeries | SourceRequestTarget:
    matching = tuple(item for item in known_series if item.station_id == station and item.product_id == str(product))
    if len(matching) == 1:
        return matching[0]
    return SourceRequestTarget(station, str(product))


def _build_request(station: str, route: SiArsoRouteCoordinates, years: tuple[str, str] | None) -> TransportRequest:
    if route.stream in ("archive_daily", "archive_monthly_extremes"):
        assert route.b_flag is not None and years is not None
        start_year, stop_year = years
        return TransportRequest(
            method=HttpMethod.GET,
            url=ARCHIVE_URL,
            params={
                "p_postaja": station,
                "p_od_leto": start_year,
                "p_do_leto": stop_year,
                route.b_flag: "1",
            },
            headers={"Accept": "text/csv,*/*"},
        )
    assert route.amp_cadence is not None
    return TransportRequest(
        method=HttpMethod.GET,
        url=f"{AMP_BASE_URL}/H{station}_{route.amp_cadence}.html",
        headers={"Accept": "text/html,*/*"},
    )


class SiArsoRequestPlanner:
    """Coalesce ARSO requests across co-published products sharing a station, route, and window.

    Archive requests omit ``p_vodotok`` intentionally so ARSO routes strictly by
    4-digit gauge ``p_postaja`` (empirically byte-identical across single-river
    and multi-river dropdown stations).
    """

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
        type _GroupKey = tuple[str, SiArsoRouteCoordinates, tuple[str, str] | None]
        groups: dict[_GroupKey, tuple[FetchWindow, list[ConsumerNeed]]] = {}

        for need in needs:
            clean_station = validate_station_id(need.station)
            try:
                configured = config.products[need.product]
            except KeyError as error:
                raise FatalContractError(f"si_arso product is absent from provider config: {need.product}") from error
            coords = configured.coordinates.value
            if isinstance(coords, SiArsoArchiveCoordinates):
                route = SiArsoRouteCoordinates(stream=coords.stream, b_flag=coords.b_flag)
                if not need.rendered:
                    raise FatalContractError(f"si_arso archive product requires rendered windows: {need.product}")
                for rendered in need.rendered:
                    years = _validate_archive_year_pair(rendered)
                    bounds = rendered.bounds if rendered.bounds is not None else need.fetch_window
                    key: _GroupKey = (clean_station, route, years)
                    entry = groups.get(key)
                    if entry is None:
                        groups[key] = (bounds, [need])
                    else:
                        if entry[0] != bounds:
                            raise FatalContractError("si_arso shared archive route received differing fetch bounds")
                        if need not in entry[1]:
                            entry[1].append(need)
            elif isinstance(coords, SiArsoAmpCoordinates):
                route = SiArsoRouteCoordinates(stream="amp", amp_cadence=coords.amp_cadence)
                key = (clean_station, route, None)
                entry = groups.get(key)
                if entry is None:
                    groups[key] = (need.fetch_window, [need])
                elif need not in entry[1]:
                    entry[1].append(need)
            else:
                raise FatalContractError(f"si_arso product has invalid source coordinates: {need.product}")

        requests: list[PlannedObservationRequest] = []
        for (station, route, years), (bounds, group_needs) in groups.items():
            consumers = tuple(group_needs)
            requests.append(
                PlannedObservationRequest(
                    consumers=consumers,
                    request=_build_request(station, route, years),
                    source_coordinates=SourceCoordinates(route),
                    fetch_window=bounds,
                    failure_targets=tuple(
                        _request_target(validate_station_id(need.station), need.product, need.known_series)
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
    """Acquire one HTTP response per ``(station, route[, years])`` and share across co-published products."""
    if not stations or not products:
        raise FatalContractError("si_arso fetch requires at least one station and product")

    start = datetime.fromisoformat(fetch_window.start.isoformat())
    end = datetime.fromisoformat(fetch_window.end.isoformat())
    interval = RequestedInterval(start, end, axis=TimeAxis.NATIVE)
    window = SeriesWindow(start=start, end=end, axis=TimeAxis.NATIVE)
    needs = tuple(
        ConsumerNeed(
            station=validate_station_id(station),
            product=product,
            scope=(
                scope.model_copy(
                    update={
                        "provider_ids": ("si_arso",),
                        "station_ids": (validate_station_id(station),),
                        "product_ids": (str(product),),
                    }
                )
                if scope is not None
                else SeriesScope(
                    provider_ids=("si_arso",),
                    station_ids=(validate_station_id(station),),
                    product_ids=(str(product),),
                )
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
    return execute_planned_acquisition(SiArsoRequestPlanner(), needs, config, transport)

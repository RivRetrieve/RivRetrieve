"""Acquire Rijkswaterstaat DDAPI 2.0 observations via POST OphalenWaarnemingen."""

from __future__ import annotations

import json
from collections.abc import Hashable, Mapping
from datetime import datetime

from rivretrieve._internal.coverage import RequestedInterval
from rivretrieve._internal.engine import (
    FetchWindow,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCoordinates,
    WindowEndpoint,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.nl_rws.config import NlRwsProductCoordinates
from rivretrieve._internal.providers.nl_rws.parse import parse_group
from rivretrieve._internal.providers.nl_rws.series import (
    PRODUCT_BY_ID,
    PROVIDER_ID,
    WAARNEMINGEN_EVIDENCE,
    build_physical_facts,
)
from rivretrieve._internal.request_planning import (
    ConsumerNeed,
    LookupResolution,
    ObservationPlan,
    PlannedLookup,
    PlannedObservationRequest,
    execute_planned_acquisition,
)
from rivretrieve._internal.source_series import (
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    TimeAxis,
    stable_id,
)
from rivretrieve._internal.transport import (
    HttpMethod,
    ReplaySafety,
    Transport,
    TransportRequest,
)

_OBSERVATIONS_URL = "https://ddapi20-waterwebservices.rijkswaterstaat.nl/ONLINEWAARNEMINGENSERVICES/OphalenWaarnemingen"


def _coordinates(product: ProductId, config: ProviderConfig) -> NlRwsProductCoordinates:
    value = config.products[product].coordinates.value
    if not isinstance(value, NlRwsProductCoordinates):
        raise FatalContractError(f"nl_rws product {product!r} has unexpected coordinates: {value!r}")
    return value


def _format_ddapi_instant(endpoint: WindowEndpoint) -> str:
    return (
        f"{endpoint.year:04d}-{endpoint.month:02d}-{endpoint.day:02d}"
        f"T{endpoint.hour:02d}:{endpoint.minute:02d}:{endpoint.second:02d}"
        f".{endpoint.microsecond // 1000:03d}+01:00"
    )


def _build_request(
    *,
    station: str,
    coords: NlRwsProductCoordinates,
    start: WindowEndpoint,
    stop: WindowEndpoint,
    include_wbw: bool,
) -> TransportRequest:
    aquo_metadata: dict[str, object] = {
        "Compartiment": {"Code": "OW"},
        "Grootheid": {"Code": coords.grootheid},
        "Eenheid": {"Code": coords.eenheid},
        "Hoedanigheid": {"Code": coords.hoedanigheid},
        "ProcesType": "meting",
    }
    if include_wbw:
        aquo_metadata["WaardeBewerkingsMethode"] = {"Code": coords.waarde_bewerkings_methode}
    payload = {
        "Locatie": {"Code": station},
        "AquoPlusWaarnemingMetadata": {"AquoMetadata": aquo_metadata},
        "Periode": {
            "Begindatumtijd": _format_ddapi_instant(start),
            "Einddatumtijd": _format_ddapi_instant(stop),
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return TransportRequest(
        method=HttpMethod.POST,
        url=_OBSERVATIONS_URL,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        body=body,
        replay_safety=ReplaySafety.SAFE,
    )


def _failure_series(station: str, product: ProductId, known_series: tuple[SourceSeries, ...]) -> SourceSeries:
    for item in known_series:
        if item.station_id == station and item.product_id == str(product):
            return item
    definition = PRODUCT_BY_ID[str(product)]
    facts = build_physical_facts(definition, time_zone_offset=None, facts_id=str(product))
    return SourceSeries(
        series_id=stable_id("nl_rws_failed_series", station, str(product)),
        provider_id=PROVIDER_ID,
        station_id=station,
        product_id=str(product),
        identity=SourceIdentity(
            namespace=f"nl_rws/{product}",
            origin="catalogue",
            description=f"Rijkswaterstaat DDAPI 2.0 request target {definition.native_id}",
            evidence=(WAARNEMINGEN_EVIDENCE,),
        ),
        facts=(facts,),
    )


class NlRwsRequestPlanner:
    """Coalesce DDAPI 2.0 POST requests across NVT and GEM24H products sharing station, coordinates, and window."""

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
        groups: dict[tuple[str, tuple[str, str, str], RenderedWindow], list[ConsumerNeed]] = {}
        for need in needs:
            coords = _coordinates(need.product, config)
            for window in need.rendered:
                if window.bounds is None:
                    raise FatalContractError("nl_rws requires engine-established window bounds")
                groups.setdefault((need.station, coords.shared_group_key, window), []).append(need)

        requests: list[PlannedObservationRequest] = []
        for (station, _, window), group_needs in groups.items():
            assert window.bounds is not None
            consumers = tuple(group_needs)
            primary_coords = _coordinates(consumers[0].product, config)
            include_wbw = len(consumers) == 1
            requests.append(
                PlannedObservationRequest(
                    consumers=consumers,
                    request=_build_request(
                        station=station,
                        coords=primary_coords,
                        start=window.bounds.start,
                        stop=window.bounds.end,
                        include_wbw=include_wbw,
                    ),
                    source_coordinates=SourceCoordinates(primary_coords),
                    fetch_window=window.bounds,
                    failure_targets=tuple(
                        _failure_series(need.station, need.product, need.known_series) for need in consumers
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
    """Fetch DDAPI 2.0 observations with ProcesType='meting' and adaptive NVT+GEM24H co-acquisition."""
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
                        "provider_ids": (str(PROVIDER_ID),),
                        "station_ids": (station,),
                        "product_ids": (str(product),),
                    }
                )
                if scope is not None
                else SeriesScope(
                    provider_ids=(str(PROVIDER_ID),),
                    station_ids=(station,),
                    product_ids=(str(product),),
                )
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
    return execute_planned_acquisition(NlRwsRequestPlanner(), needs, config, transport)

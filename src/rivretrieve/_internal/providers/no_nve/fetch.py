"""no_nve fetch : stations × products × rendered windows × FetchWindow × ProviderConfig × Transport → WithIssues[Payload[]].

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import json
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, replace
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
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.no_nve.config import (
    NoNveBatchCoordinates,
    NoNveSeriesLookupCoordinates,
    NoNveSourceCoordinates,
)
from rivretrieve._internal.providers.no_nve.metadata import (
    fail_series_lookup,
    resolve_series_lookup,
)
from rivretrieve._internal.providers.no_nve.parse import parse_batch_group
from rivretrieve._internal.request_planning import (
    ConsumerNeed,
    LookupFailureResult,
    LookupResolution,
    ObservationPlan,
    PlannedLookup,
    PlannedObservationRequest,
    ResolvedLookup,
    _merge_fetch_windows,
    execute_planned_acquisition,
)
from rivretrieve._internal.source_series import (
    PhysicalFacts,
    RestrictionKind,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    TimeAxis,
    stable_id,
)
from rivretrieve._internal.transport import HttpMethod, Transport, TransportRequest

_URL = "https://hydapi.nve.no/api/v1/Observations"
_SERIES_URL = "https://hydapi.nve.no/api/v1/Series"
_POST_BATCH_LIMIT = 25


@dataclass(frozen=True, slots=True)
class _ResolvedObservationTarget:
    need: ConsumerNeed
    coordinates: NoNveSourceCoordinates
    reference_time: str
    target: SourceSeries
    prereqs: tuple[str, ...]


def _target_series(
    station: str,
    product: ProductId,
    concrete: NoNveSourceCoordinates,
    version: int,
    matching: tuple[SourceSeries, ...],
) -> SourceSeries:
    existing = next((item for item in matching if item.identity.published_id == str(version)), None)
    if existing is not None:
        return existing
    identifier = stable_id(
        "no_nve",
        station,
        "HydAPI.requested_version",
        concrete.parameter,
        str(version),
        concrete.resolution_time,
    )
    return SourceSeries(
        series_id=identifier,
        provider_id="no_nve",
        station_id=station,
        product_id=str(product),
        identity=SourceIdentity(
            namespace="HydAPI.requested_version",
            published_id=None,
            origin="mapping",
            evidence=(
                f"Caller requested documented VersionNumber selector {version}; source identity remains unestablished",
            ),
        ),
        variant=str(version),
        facts=(PhysicalFacts(facts_id=stable_id(identifier, "unestablished")),),
    )


def _pack_observation_batches(
    items: list[_ResolvedObservationTarget],
) -> list[list[_ResolvedObservationTarget]]:
    batches: list[list[_ResolvedObservationTarget]] = []
    batch_keys: list[set[tuple[str, str, int | None]]] = []
    for item in items:
        # HydAPI ObservationSeries blocks lack a resolutionTime field, so items sharing
        # (stationId, parameter, versionNumber) across resolutions stay in separate requests.
        collision_key = (item.need.station, item.coordinates.parameter, item.coordinates.version_number)
        placed = False
        for idx, keys in enumerate(batch_keys):
            if len(batches[idx]) < _POST_BATCH_LIMIT and collision_key not in keys:
                batches[idx].append(item)
                keys.add(collision_key)
                placed = True
                break
        if not placed:
            batches.append([item])
            batch_keys.append({collision_key})
    return batches


class NoNveRequestPlanner:
    """Plan deduplicated GET /Series lookups and bounded POST /Observations batches."""

    def plan_lookups(
        self,
        needs: tuple[ConsumerNeed, ...],
        config: ProviderConfig,
    ) -> tuple[PlannedLookup, ...]:
        lookups: list[PlannedLookup] = []
        for need in needs:
            coordinates = _coordinates(need.product, config)
            if coordinates.version_number is None and need.scope.restriction is RestrictionKind.ALL:
                lookups.append(
                    PlannedLookup(
                        key=("no_nve_series", need.station, coordinates.parameter),
                        consumers=(need,),
                        request=TransportRequest(
                            HttpMethod.GET,
                            _SERIES_URL,
                            {"StationId": need.station, "Parameter": int(coordinates.parameter)},
                            {"Accept": "application/json"},
                        ),
                        source_coordinates=SourceCoordinates(NoNveSeriesLookupCoordinates(coordinates.parameter)),
                        fetch_window=need.fetch_window,
                        window_in_identity=False,
                        emit_payload=False,
                        record_auxiliary_call=True,
                        on_response=resolve_series_lookup,
                        on_failure=fail_series_lookup,
                    )
                )
        return tuple(lookups)

    def plan_observations(
        self,
        needs: tuple[ConsumerNeed, ...],
        lookups: Mapping[tuple[Hashable, str, ProductId], LookupResolution],
        config: ProviderConfig,
    ) -> ObservationPlan:
        resolved_items: list[_ResolvedObservationTarget] = []
        issues: list[Issue] = []
        for need in needs:
            coordinates = _coordinates(need.product, config)
            matching = tuple(
                item
                for item in need.known_series
                if item.station_id == need.station and item.product_id == need.product and need.scope.matches(item)
            )
            prereqs: tuple[str, ...] = ()
            lookup_failed = False
            lookup_complete = False
            if coordinates.version_number is None and need.scope.restriction is RestrictionKind.ALL:
                res = lookups.get((("no_nve_series", need.station, coordinates.parameter), need.station, need.product))
                if isinstance(res, ResolvedLookup):
                    version_map = cast(
                        "Mapping[tuple[str, ProductId], tuple[tuple[int, ...], tuple[SourceSeries, ...], bool]]",
                        res.value,
                    )
                    versions_tuple, matching, lookup_complete = version_map[(need.station, need.product)]
                    versions = set(versions_tuple)
                    prereqs = (res.acquisition_id,) if res.acquisition_id else ()
                elif isinstance(res, LookupFailureResult):
                    lookup_failed = True
                    prereqs = (res.call_id,) if res.call_id else ()
                    versions = {
                        int(item.identity.published_id)
                        for item in matching
                        if item.identity.namespace == "HydAPI.version"
                        and item.identity.published_id is not None
                        and item.identity.published_id.isdecimal()
                    }
                else:
                    versions = set()
            else:
                versions = {
                    int(item.identity.published_id)
                    for item in matching
                    if item.identity.namespace == "HydAPI.version"
                    and item.identity.published_id is not None
                    and item.identity.published_id.isdecimal()
                }
                if coordinates.version_number is not None:
                    versions.add(coordinates.version_number)
                if need.scope.restriction is RestrictionKind.EXPLICIT:
                    versions.update(
                        int(value) for value in need.scope.variants if value.isascii() and value.isdecimal()
                    )

            if not versions:
                if not lookup_failed and not lookup_complete:
                    issues.append(
                        Issue(
                            severity="warning",
                            code="source.inventory_unresolved",
                            message="No established HydAPI version selector is available; upstream default is not all-series retrieval",
                            details={"station_id": need.station, "product_id": str(need.product)},
                            provider_id=ProviderId("no_nve"),
                        )
                    )
                continue

            for version in sorted(versions):
                concrete = replace(coordinates, version_number=version)
                target = _target_series(need.station, need.product, concrete, version, matching)
                for window in need.rendered:
                    resolved_items.append(
                        _ResolvedObservationTarget(
                            need=need,
                            coordinates=concrete,
                            reference_time=_reference_time(window),
                            target=target,
                            prereqs=prereqs,
                        )
                    )

        if not resolved_items:
            return ObservationPlan(issues=tuple(issues))

        unique_pairs = {(item.need.station, item.need.product) for item in resolved_items}
        if len(unique_pairs) == 1:
            requests = tuple(
                PlannedObservationRequest(
                    consumers=(item.need,),
                    request=_request(item.need.station, item.coordinates, item.reference_time),
                    source_coordinates=SourceCoordinates(item.coordinates),
                    fetch_window=item.need.fetch_window,
                    prerequisite_acquisition_ids=item.prereqs,
                    failure_targets=(item.target,),
                )
                for item in resolved_items
            )
            return ObservationPlan(requests=requests, issues=tuple(issues))

        requests_list: list[PlannedObservationRequest] = []
        for batch in _pack_observation_batches(resolved_items):
            if len(batch) == 1:
                item = batch[0]
                requests_list.append(
                    PlannedObservationRequest(
                        consumers=(item.need,),
                        request=_request(item.need.station, item.coordinates, item.reference_time),
                        source_coordinates=SourceCoordinates(item.coordinates),
                        fetch_window=item.need.fetch_window,
                        prerequisite_acquisition_ids=item.prereqs,
                        failure_targets=(item.target,),
                    )
                )
                continue
            body = json.dumps(
                [
                    {
                        "stationId": item.need.station,
                        "parameter": item.coordinates.parameter,
                        "resolutionTime": item.coordinates.resolution_time,
                        "versionNumber": item.coordinates.version_number,
                        "referenceTime": item.reference_time,
                    }
                    for item in batch
                ]
            )
            consumers = tuple(dict.fromkeys(item.need for item in batch))
            prereqs = tuple(dict.fromkeys(pid for item in batch for pid in item.prereqs))
            batch_coords = NoNveBatchCoordinates(
                items=tuple((item.need.station, item.need.product, item.coordinates) for item in batch)
            )
            requests_list.append(
                PlannedObservationRequest(
                    consumers=consumers,
                    request=TransportRequest(
                        method=HttpMethod.POST,
                        url=_URL,
                        params=None,
                        headers={"Accept": "application/json", "Content-Type": "application/json"},
                        body=body,
                    ),
                    source_coordinates=SourceCoordinates(batch_coords),
                    fetch_window=_merge_fetch_windows([item.need.fetch_window for item in batch]),
                    prerequisite_acquisition_ids=prereqs,
                    failure_targets=tuple(item.target for item in batch),
                    interpret_group=parse_batch_group,
                )
            )
        return ObservationPlan(requests=tuple(requests_list), issues=tuple(issues))


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
                        "provider_ids": ("no_nve",),
                        "station_ids": (station,),
                        "product_ids": (str(product),),
                    }
                )
                if scope is not None
                else SeriesScope(provider_ids=("no_nve",), station_ids=(station,), product_ids=(str(product),))
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
    return execute_planned_acquisition(NoNveRequestPlanner(), needs, config, transport)


def _coordinates(product: ProductId, config: ProviderConfig) -> NoNveSourceCoordinates:
    try:
        value = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"no_nve product is absent from provider config: {product}") from error
    if not isinstance(value, NoNveSourceCoordinates):
        raise FatalContractError(f"no_nve product has invalid source coordinates: {product}")
    return value


def _reference_time(window: RenderedWindow) -> str:
    if window.stop is None:
        raise FatalContractError("no_nve requires a rendered window closed at both ends")
    return f"{window.start}/{window.stop}"


def _request(station: str, coordinates: NoNveSourceCoordinates, reference_time: str) -> TransportRequest:
    return TransportRequest(
        method=HttpMethod.GET,
        url=_URL,
        params={
            "StationId": station,
            "Parameter": coordinates.parameter,
            "ResolutionTime": coordinates.resolution_time,
            "ReferenceTime": reference_time,
            "VersionNumber": coordinates.version_number,
        },
        headers={"Accept": "application/json"},
    )

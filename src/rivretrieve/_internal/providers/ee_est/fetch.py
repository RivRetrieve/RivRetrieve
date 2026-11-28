"""Acquire Estonia (`ee_est`) EstModel daily and Keskkonnaandmed `f_hydroseire` hourly payloads."""

from __future__ import annotations

import json
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType

from rivretrieve._internal.coverage import RequestedInterval
from rivretrieve._internal.engine import (
    FetchWindow,
    InterpretedPayload,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCoordinates,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ee_est.config import (
    EstModelCoordinates,
    FHydroseireCoordinates,
    FSeirejaamadLookupCoordinates,
)
from rivretrieve._internal.providers.ee_est.parse import parse
from rivretrieve._internal.providers.ee_est.series import (
    FH_NAMESPACE,
    parse_jaam_kood,
    reused_series,
    source_series,
)
from rivretrieve._internal.request_planning import (
    ConsumerNeed,
    LookupFailureResult,
    LookupResolution,
    ObservationPlan,
    PlannedLookup,
    PlannedObservationRequest,
    ResolvedLookup,
    execute_planned_acquisition,
)
from rivretrieve._internal.source_acquisition import FailedSourceRequest
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    RestrictionKind,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    stable_id,
)
from rivretrieve._internal.time_axis import TimeAxis
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportRequest,
    TransportResponse,
)

__all__ = ["EeEstRequestPlanner", "fetch", "reused_series"]

_PROVIDER_ID = ProviderId("ee_est")
_ESTMODEL_BASE_URL = "https://estmodel.envir.ee/stations"
_FH_URL = "https://keskkonnaandmed.envir.ee/f_hydroseire"
_SEIREJAAMAD_URL = "https://keskkonnaandmed.envir.ee/f_seirejaamad"
_JSON_HEADERS = {"Accept": "application/json"}
_FH_HEADERS = {"Accept": "application/json", "Accept-Profile": "apijahiala"}
_SEIREJAAMAD_LOOKUP_KEY = "ee_est_seirejaamad"


def _validate_station_id(station: str) -> None:
    if (
        not station
        or not station.isascii()
        or station.strip() != station
        or any(ch in "/?#" or ch.isspace() for ch in station)
    ):
        raise FatalContractError(f"ee_est station_id must be a canonical nonblank identifier: {station!r}")


def _extract_jaam_kood(published_id: str | None, aegrida_nimi: str) -> int | None:
    if published_id is None:
        return None
    suffix = f":{aegrida_nimi}"
    if not published_id.endswith(suffix):
        return None
    code_part = published_id[: -len(suffix)]
    if code_part.isascii() and code_part.isdigit() and int(code_part) > 0:
        return int(code_part)
    return None


def _resolve_explicit_codes(need: ConsumerNeed, coords: FHydroseireCoordinates) -> tuple[int, ...]:
    """Extract explicitly requested ``jaam_kood`` codes when scope restriction is EXPLICIT."""
    if need.scope.restriction is not RestrictionKind.EXPLICIT:
        return ()
    codes: list[int] = []
    for item in need.known_series:
        if item.station_id != need.station or item.product_id != str(need.product):
            continue
        if item.identity.namespace != FH_NAMESPACE or not need.scope.matches(item):
            continue
        parsed_code = _extract_jaam_kood(item.identity.published_id, coords.aegrida_nimi)
        if parsed_code is not None:
            codes.append(parsed_code)
    for variant in need.scope.variants:
        parsed_code = _extract_jaam_kood(variant, coords.aegrida_nimi)
        if parsed_code is not None:
            codes.append(parsed_code)
    return tuple(dict.fromkeys(codes))


def _known_codes_for_pair(need: ConsumerNeed, coords: FHydroseireCoordinates) -> tuple[int, ...]:
    """Extract ``jaam_kood`` codes from caller-supplied ``known_series`` when no packaged table is present."""
    codes: list[int] = []
    for item in need.known_series:
        if item.station_id != need.station or item.product_id != str(need.product):
            continue
        if item.identity.namespace != FH_NAMESPACE or not need.scope.matches(item):
            continue
        parsed_code = _extract_jaam_kood(item.identity.published_id, coords.aegrida_nimi)
        if parsed_code is not None:
            codes.append(parsed_code)
    return tuple(dict.fromkeys(codes))


def _unrestricted_pair_scope(need: ConsumerNeed) -> SeriesScope:
    return SeriesScope(
        provider_ids=("ee_est",),
        station_ids=(need.station,),
        product_ids=(str(need.product),),
    )


def _validated_need(
    need: ConsumerNeed, config: ProviderConfig
) -> tuple[EstModelCoordinates | FHydroseireCoordinates, tuple[RenderedWindow, ...]]:
    _validate_station_id(need.station)
    try:
        product_config = config.products[need.product]
    except KeyError as error:
        raise FatalContractError(f"ee_est product is absent from provider config: {need.product}") from error
    coords = product_config.coordinates.value
    if not isinstance(coords, (EstModelCoordinates, FHydroseireCoordinates)):
        raise FatalContractError(f"ee_est product has invalid source coordinates: {need.product}")
    if not need.rendered:
        raise FatalContractError(f"ee_est product requires at least one rendered window: {need.product}")
    for window in need.rendered:
        if window.bounds is None or window.stop is None:
            raise FatalContractError(f"ee_est product requires closed bounds and stop: {need.product}")
    return coords, need.rendered


def _on_seirejaamad_response(
    response: TransportResponse,
    consumers: tuple[ConsumerNeed, ...],
    acquisition_id: str,
    config: ProviderConfig,
) -> ResolvedLookup:
    del config
    station = consumers[0].station
    if any(need.station != station for need in consumers):
        raise FatalContractError("ee_est /f_seirejaamad lookup cannot span multiple stations")
    codes: tuple[int, ...] = ()
    malformed_reason: str | None = None
    try:
        document = json.loads(response.content)
        if not isinstance(document, list):
            raise ValueError("f_seirejaamad lookup response must be a JSON list")
        if len(document) > 1:
            raise ValueError(f"f_seirejaamad lookup returned {len(document)} rows for {station!r}")
        if document:
            entry = document[0]
            if not isinstance(entry, dict) or entry.get("kkr_kood") != station:
                raise ValueError(f"f_seirejaamad lookup row contradicts station {station!r}")
            codes = parse_jaam_kood(entry.get("kood"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, FatalContractError) as error:
        malformed_reason = f"Malformed Keskkonnaandmed f_seirejaamad lookup response: {error}"

    evidence = (f"source-call:{acquisition_id}",)
    if malformed_reason is not None:
        outcomes: list[RetrievalOutcome] = []
        inventories: list[InventorySnapshot] = []
        issues: list[Issue] = []
        for need in consumers:
            outcome = RetrievalOutcome(
                outcome_id=stable_id(acquisition_id, need.station, str(need.product), "failed"),
                series_id=None,
                station_id=need.station,
                product_id=str(need.product),
                window=need.window,
                status=OutcomeStatus.FAILED,
                reason=malformed_reason,
                retrieved_at=response.retrieved_at,
                calls=(acquisition_id,),
            )
            outcomes.append(outcome)
            inventories.append(
                InventorySnapshot(
                    snapshot_id=stable_id(acquisition_id, need.station, str(need.product), "failed-inventory"),
                    scope=need.scope,
                    members=(),
                    completeness=InventoryCompleteness.INCOMPLETE,
                    access="Keskkonnaandmed /f_seirejaamad",
                    origin="response",
                    acquired_at=response.retrieved_at,
                    window=need.window,
                    evidence=evidence,
                    reason=malformed_reason,
                )
            )
            issues.append(
                Issue(
                    severity="error",
                    code="source.unsupported_structure",
                    message=malformed_reason,
                    details={
                        "station_id": need.station,
                        "product_id": str(need.product),
                        "outcome_id": outcome.outcome_id,
                    },
                    provider_id=_PROVIDER_ID,
                )
            )
        return ResolvedLookup(
            value=None,
            acquisition_id=acquisition_id,
            outcomes=tuple(outcomes),
            inventories=tuple(inventories),
            issues=tuple(issues),
        )

    if not codes:
        reason = f"Station {station} has no active Keskkonnaandmed f_hydroseire jaam_kood"
        outcomes = []
        inventories = []
        issues = []
        for need in consumers:
            outcome = RetrievalOutcome(
                outcome_id=stable_id(acquisition_id, need.station, str(need.product), "no-match"),
                series_id=None,
                station_id=need.station,
                product_id=str(need.product),
                window=need.window,
                status=OutcomeStatus.NO_MATCH,
                reason=reason,
                retrieved_at=response.retrieved_at,
                calls=(acquisition_id,),
            )
            outcomes.append(outcome)
            inventories.append(
                InventorySnapshot(
                    snapshot_id=stable_id(acquisition_id, need.station, str(need.product), "no-match-inventory"),
                    scope=need.scope,
                    members=(),
                    completeness=InventoryCompleteness.COMPLETE,
                    access="Keskkonnaandmed /f_seirejaamad",
                    origin="response",
                    acquired_at=response.retrieved_at,
                    window=need.window,
                    evidence=evidence,
                )
            )
            issues.append(
                Issue(
                    severity="warning",
                    code="source.no_match",
                    message=reason,
                    details={
                        "station_id": need.station,
                        "product_id": str(need.product),
                        "outcome_id": outcome.outcome_id,
                    },
                    provider_id=_PROVIDER_ID,
                )
            )
        return ResolvedLookup(
            value=(),
            acquisition_id=acquisition_id,
            outcomes=tuple(outcomes),
            inventories=tuple(inventories),
            issues=tuple(issues),
        )

    return ResolvedLookup(value=codes, acquisition_id=acquisition_id)


@dataclass(frozen=True, slots=True)
class _PlannedPairSpec:
    need: ConsumerNeed
    expected_requests: int
    expected_per_code: int
    candidate_codes: tuple[int, ...]
    protected_series_ids: frozenset[str]
    access: str
    inventory_scope: SeriesScope
    kind: str


def _interp_code(interp: InterpretedPayload) -> int | None:
    coords = interp.context.source_coordinates.value
    if isinstance(coords, FHydroseireCoordinates):
        return coords.jaam_kood
    return None


def _failure_code(failure: FailedSourceRequest) -> int | None:
    params = failure.request.params or {}
    raw = params.get("jaam_kood")
    if isinstance(raw, str) and raw.startswith("eq.") and raw[3:].isdigit():
        return int(raw[3:])
    return None


def _finalize_acquisition(
    acquisition: SourceAcquisition,
    pair_specs: Mapping[tuple[str, str], _PlannedPairSpec],
) -> SourceAcquisition:
    interps_by_pair: dict[tuple[str, str], list[InterpretedPayload]] = {}
    for interp in acquisition.interpretations:
        if len(interp.context.station_products) != 1:
            raise FatalContractError("ee_est interpretation requires a single station-product pair")
        station, product = interp.context.station_products[0]
        interps_by_pair.setdefault((station, str(product)), []).append(interp)

    failures_by_pair: dict[tuple[str, str], list[FailedSourceRequest]] = {}
    for failure in acquisition.failed_requests:
        failures_by_pair.setdefault((failure.series.station_id, failure.series.product_id), []).append(failure)

    dropped_by_acq_id: set[str] = set()
    kept_series: dict[str, SourceSeries] = {}
    inventories: list[InventorySnapshot] = list(acquisition.inventories)

    for pair_key, spec in pair_specs.items():
        station, product = pair_key
        pair_interps = interps_by_pair.get(pair_key, [])
        pair_failures = failures_by_pair.get(pair_key, [])
        dropped_codes: set[int] = set()

        if spec.candidate_codes:
            for code in spec.candidate_codes:
                code_interps = [ip for ip in pair_interps if _interp_code(ip) == code]
                code_failures = [f for f in pair_failures if _failure_code(f) == code]
                if (
                    not code_failures
                    and code_interps
                    and len(code_interps) == spec.expected_per_code
                    and all(
                        not ip.parsed.issues
                        and ip.parsed.rows.is_empty()
                        and ip.parsed.outcomes
                        and all(out.status is OutcomeStatus.EMPTY for out in ip.parsed.outcomes)
                        and all(s.series_id not in spec.protected_series_ids for s in ip.parsed.series)
                        for ip in code_interps
                    )
                ):
                    dropped_codes.add(code)
                    dropped_by_acq_id.update(ip.context.acquisition_id for ip in code_interps)

        kept_pair_interps = [ip for ip in pair_interps if _interp_code(ip) not in dropped_codes]
        pair_members: dict[str, SourceSeries] = {}
        for ip in kept_pair_interps:
            for sdef in ip.parsed.series:
                pair_members[sdef.series_id] = sdef
                kept_series[sdef.series_id] = sdef

        if pair_interps:
            instants = tuple(
                ip.context.origin.retrieved_at
                for ip in pair_interps
                if isinstance(ip.context.origin.retrieved_at, datetime)
            )
            evidence = tuple(f"source-call:{ip.context.acquisition_id}" for ip in pair_interps)
            has_failed_outcome = any(
                out.status in (OutcomeStatus.FAILED, OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED)
                for ip in pair_interps
                for out in ip.parsed.outcomes
            )
            all_interpreted = len(pair_interps) == spec.expected_requests
            is_complete = not pair_failures and not has_failed_outcome and all_interpreted
            reason: str | None = None
            if not is_complete:
                reason = (
                    f"Incomplete Keskkonnaagentuur acquisition for {station}/{product}: "
                    f"{len(pair_interps)} of {spec.expected_requests} request(s) interpreted, "
                    f"{len(pair_failures)} request(s) failed"
                )
            inventories.append(
                InventorySnapshot(
                    snapshot_id=stable_id(
                        "ee_est",
                        spec.kind,
                        station,
                        product,
                        spec.need.window.model_dump_json(),
                        *(ip.context.acquisition_id for ip in pair_interps),
                    ),
                    scope=spec.inventory_scope,
                    members=tuple(pair_members.keys()),
                    member_facts=tuple(
                        (sid, tuple(fact.facts_id for fact in sdef.facts)) for sid, sdef in pair_members.items()
                    ),
                    completeness=InventoryCompleteness.COMPLETE if is_complete else InventoryCompleteness.INCOMPLETE,
                    access=spec.access,
                    origin="response",
                    acquired_at=max(instants) if instants else None,
                    window=spec.need.window,
                    evidence=evidence,
                    reason=reason,
                )
            )

    final_interpretations: list[InterpretedPayload] = []
    for ip in acquisition.interpretations:
        if ip.context.acquisition_id in dropped_by_acq_id:
            stripped = ParsedSeries(
                ip.parsed.rows,
                (),
                (),
                (),
                ip.parsed.issues,
                ip.parsed.annotations,
            )
            final_interpretations.append(replace(ip, parsed=stripped))
        else:
            stripped = ParsedSeries(
                ip.parsed.rows,
                ip.parsed.series,
                (),
                ip.parsed.outcomes,
                ip.parsed.issues,
                ip.parsed.annotations,
            )
            final_interpretations.append(replace(ip, parsed=stripped))

    planned_pairs = set(pair_specs)
    preserved_series = tuple(
        sdef for sdef in acquisition.series if (sdef.station_id, sdef.product_id) not in planned_pairs
    )
    merged_series = {sdef.series_id: sdef for sdef in preserved_series}
    merged_series.update(kept_series)

    return replace(
        acquisition,
        series=tuple(merged_series.values()),
        inventories=tuple(inventories),
        interpretations=tuple(final_interpretations),
    )


class EeEstRequestPlanner:
    """Shared-acquisition request planner for Estonia EstModel daily and ``f_hydroseire`` hourly APIs."""

    def __init__(self, station_codes: Mapping[str, tuple[int, ...]] = MappingProxyType({})) -> None:
        validated: dict[str, tuple[int, ...]] = {}
        for station_id, codes in station_codes.items():
            _validate_station_id(station_id)
            for code in codes:
                if type(code) is not int or code <= 0:
                    raise FatalContractError(f"ee_est station_codes invalid jaam_kood {code!r} on {station_id!r}")
            validated[station_id] = tuple(codes)
        self._station_codes: Mapping[str, tuple[int, ...]] = MappingProxyType(validated)

    def _synchronous_codes(
        self, need: ConsumerNeed, coords: FHydroseireCoordinates
    ) -> tuple[tuple[int, ...], bool] | None:
        explicit_codes = _resolve_explicit_codes(need, coords)
        if explicit_codes:
            return explicit_codes, True
        if need.station in self._station_codes:
            return self._station_codes[need.station], False
        if not self._station_codes:
            known_codes = _known_codes_for_pair(need, coords)
            if known_codes:
                return known_codes, False
        return None

    def plan_lookups(
        self,
        needs: tuple[ConsumerNeed, ...],
        config: ProviderConfig,
    ) -> tuple[PlannedLookup, ...]:
        lookups: list[PlannedLookup] = []
        for need in needs:
            coords, _ = _validated_need(need, config)
            if not isinstance(coords, FHydroseireCoordinates):
                continue
            if self._synchronous_codes(need, coords) is not None:
                continue
            lookups.append(
                PlannedLookup(
                    key=(_SEIREJAAMAD_LOOKUP_KEY, need.station),
                    consumers=(need,),
                    request=TransportRequest(
                        method=HttpMethod.GET,
                        url=_SEIREJAAMAD_URL,
                        params={
                            "kkr_kood": f"eq.{need.station}",
                            "seiretyyp": "eq.HJ",
                            "select": "kkr_kood,kood",
                        },
                        headers=_JSON_HEADERS,
                    ),
                    source_coordinates=SourceCoordinates(FSeirejaamadLookupCoordinates(station_id=need.station)),
                    fetch_window=need.fetch_window,
                    on_response=_on_seirejaamad_response,
                    on_failure=None,
                )
            )
        return tuple(lookups)

    def plan_observations(
        self,
        needs: tuple[ConsumerNeed, ...],
        lookups: Mapping[tuple[Hashable, str, ProductId], LookupResolution],
        config: ProviderConfig,
    ) -> ObservationPlan:
        requests: list[PlannedObservationRequest] = []
        outcomes: list[RetrievalOutcome] = []
        inventories: list[InventorySnapshot] = []
        issues: list[Issue] = []
        pair_specs: dict[tuple[str, str], _PlannedPairSpec] = {}

        for need in needs:
            coords, windows = _validated_need(need, config)
            unrestricted = _unrestricted_pair_scope(need)
            inventory_scope = unrestricted if need.scope.restriction is RestrictionKind.ALL else need.scope

            if isinstance(coords, EstModelCoordinates):
                target = reused_series(
                    source_series(need.station, str(need.product), origin="mapping"), need.known_series
                )
                for window in windows:
                    assert window.bounds is not None and window.stop is not None
                    requests.append(
                        PlannedObservationRequest(
                            consumers=(need,),
                            request=TransportRequest(
                                method=HttpMethod.GET,
                                url=f"{_ESTMODEL_BASE_URL}/{need.station}/measurements",
                                params={
                                    "parameter": coords.parameter,
                                    "type": coords.aggregation_type,
                                    "start-year": window.start,
                                    "end-year": window.stop,
                                },
                                headers=_JSON_HEADERS,
                            ),
                            source_coordinates=config.products[need.product].coordinates,
                            fetch_window=window.bounds,
                            failure_targets=(target,),
                            interpret_payload=parse,
                        )
                    )
                pair_specs[(need.station, str(need.product))] = _PlannedPairSpec(
                    need=need,
                    expected_requests=len(windows),
                    expected_per_code=len(windows),
                    candidate_codes=(),
                    protected_series_ids=frozenset(),
                    access=f"EstModel /{need.station}/measurements {coords.parameter}:{coords.aggregation_type}",
                    inventory_scope=inventory_scope,
                    kind="estmodel-pair-inventory",
                )
                continue

            sync = self._synchronous_codes(need, coords)
            prereq_ids: tuple[str, ...] = ()
            from_explicit = False
            if sync is not None:
                codes, from_explicit = sync
                if not codes:
                    reason = f"Station {need.station} has no active Keskkonnaandmed f_hydroseire jaam_kood"
                    outcome_id = stable_id(
                        "ee_est", "station_codes", need.station, str(need.product), need.window.model_dump_json()
                    )
                    outcomes.append(
                        RetrievalOutcome(
                            outcome_id=outcome_id,
                            series_id=None,
                            station_id=need.station,
                            product_id=str(need.product),
                            window=need.window,
                            status=OutcomeStatus.NO_MATCH,
                            reason=reason,
                        )
                    )
                    inventories.append(
                        InventorySnapshot(
                            snapshot_id=stable_id(
                                "ee_est",
                                "station_codes-no-match",
                                need.station,
                                str(need.product),
                                need.window.model_dump_json(),
                            ),
                            scope=need.scope,
                            members=(),
                            completeness=InventoryCompleteness.COMPLETE,
                            access="Packaged ee_est station_codes.json",
                            origin="catalogue",
                            window=need.window,
                            evidence=("catalogue:ee_est:station_codes.json",),
                        )
                    )
                    issues.append(
                        Issue(
                            severity="warning",
                            code="source.no_match",
                            message=reason,
                            details={
                                "station_id": need.station,
                                "product_id": str(need.product),
                                "outcome_id": outcome_id,
                            },
                            provider_id=_PROVIDER_ID,
                        )
                    )
                    continue
            else:
                resolution = lookups.get(((_SEIREJAAMAD_LOOKUP_KEY, need.station), need.station, need.product))
                if resolution is None:
                    raise FatalContractError(f"Missing ee_est /f_seirejaamad resolution for {need.station}")
                if isinstance(resolution, LookupFailureResult):
                    continue
                if resolution.value is None or resolution.value == ():
                    continue
                raw_codes = resolution.value
                if not isinstance(raw_codes, tuple) or not all(isinstance(code, int) for code in raw_codes):
                    raise FatalContractError(f"Invalid ee_est /f_seirejaamad resolution for {need.station}")
                codes = tuple(code for code in raw_codes if isinstance(code, int))
                prereq_ids = (resolution.acquisition_id,)

            protected_ids: set[str] = {
                item.series_id
                for item in need.known_series
                if item.station_id == need.station and item.product_id == str(need.product) and need.scope.matches(item)
            }
            if from_explicit:
                for code in codes:
                    protected_ids.add(
                        source_series(need.station, str(need.product), jaam_kood=code, origin="mapping").series_id
                    )

            for code in codes:
                obs_coords = replace(coords, jaam_kood=code)
                target = reused_series(
                    source_series(need.station, str(need.product), jaam_kood=code, origin="mapping"),
                    need.known_series,
                )
                for window in windows:
                    assert window.bounds is not None and window.stop is not None
                    requests.append(
                        PlannedObservationRequest(
                            consumers=(need,),
                            request=TransportRequest(
                                method=HttpMethod.GET,
                                url=_FH_URL,
                                params={
                                    "jaam_kood": f"eq.{code}",
                                    "aegrida_nimi": f"eq.{coords.aegrida_nimi}",
                                    "and": f"(timeline_ts_utc.gte.{window.start},timeline_ts_utc.lte.{window.stop})",
                                    "select": "jaam_kood,aegrida_nimi,timeline_ts_utc,vaartus",
                                    "order": "timeline_ts_utc.asc",
                                },
                                headers=_FH_HEADERS,
                            ),
                            source_coordinates=SourceCoordinates(obs_coords),
                            fetch_window=window.bounds,
                            prerequisite_acquisition_ids=prereq_ids,
                            failure_targets=(target,),
                            interpret_payload=parse,
                        )
                    )

            codes_desc = ",".join(str(code) for code in codes)
            pair_specs[(need.station, str(need.product))] = _PlannedPairSpec(
                need=need,
                expected_requests=len(codes) * len(windows),
                expected_per_code=len(windows),
                candidate_codes=codes,
                protected_series_ids=frozenset(protected_ids),
                access=f"Keskkonnaandmed /f_hydroseire {codes_desc}:{coords.aegrida_nimi}",
                inventory_scope=inventory_scope,
                kind="f-hydroseire-pair-inventory",
            )

        return ObservationPlan(
            requests=tuple(requests),
            inventories=tuple(inventories),
            outcomes=tuple(outcomes),
            issues=tuple(issues),
            finalize=lambda acq: _finalize_acquisition(acq, pair_specs),
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
    station_codes: Mapping[str, tuple[int, ...]] = MappingProxyType({}),
) -> SourceAcquisition:
    """Acquire bounded EstModel daily chunks and `f_hydroseire` UTC spans."""
    if not stations or not products:
        raise FatalContractError("ee_est fetch requires at least one station and product")
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
                        "provider_ids": ("ee_est",),
                        "station_ids": (station,),
                        "product_ids": (str(product),),
                    }
                )
                if scope is not None
                else SeriesScope(
                    provider_ids=("ee_est",),
                    station_ids=(station,),
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
    return execute_planned_acquisition(EeEstRequestPlanner(station_codes=station_codes), needs, config, transport)

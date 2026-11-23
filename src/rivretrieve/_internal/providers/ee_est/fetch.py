"""Acquire Estonia (`ee_est`) EstModel daily and Keskkonnaandmed `f_hydroseire` hourly payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import uuid4

from rivretrieve._internal.authentication import CredentialExchangeError
from rivretrieve._internal.engine import (
    FetchWindow,
    Payload,
    ProviderConfig,
    RenderedWindow,
    SourceAcquisition,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ee_est.config import EstModelCoordinates, FHydroseireCoordinates
from rivretrieve._internal.providers.ee_est.series import FH_NAMESPACE, parse_jaam_kood, source_series
from rivretrieve._internal.source_acquisition import (
    FailedSourceRequest,
    SourceRequestTarget,
    attempt_request,
    attempt_series_request,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    stable_id,
)
from rivretrieve._internal.transport import (
    HttpMethod,
    Transport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
)

_PROVIDER_ID = ProviderId("ee_est")
_ESTMODEL_BASE_URL = "https://estmodel.envir.ee/stations"
_FH_URL = "https://keskkonnaandmed.envir.ee/f_hydroseire"
_SEIREJAAMAD_URL = "https://keskkonnaandmed.envir.ee/f_seirejaamad"
_JSON_HEADERS = {"Accept": "application/json"}
_FH_HEADERS = {"Accept": "application/json", "Accept-Profile": "apijahiala"}


def _validate_station_id(station: str) -> None:
    if (
        not station
        or not station.isascii()
        or station.strip() != station
        or any(ch in "/?#" or ch.isspace() for ch in station)
    ):
        raise FatalContractError(f"ee_est station_id must be a canonical nonblank identifier: {station!r}")


def reused_series(definition: SourceSeries, known_series: tuple[SourceSeries, ...]) -> SourceSeries:
    """Preserve prior established identity and matching fact IDs when available."""
    candidate = next((item for item in known_series if item.series_id == definition.series_id), None)
    if candidate is None:
        return definition
    retained = {_fact_signature(fact): fact for fact in candidate.facts}
    return definition.model_copy(
        update={
            "identity": candidate.identity,
            "facts": tuple(retained.get(_fact_signature(fact), fact) for fact in definition.facts),
        }
    )


def _fact_signature(fact: PhysicalFacts) -> tuple[object, ...]:
    return (
        fact.quantity.value,
        fact.source_unit.value,
        fact.normalized_unit,
        fact.frequency.value,
        fact.statistic.value,
        fact.temporal_support.value,
        fact.day_definition.value,
        fact.timestamp_anchor.value,
        fact.time_zone.value,
        fact.vertical_reference.value,
        fact.vertical_datum.value,
        fact.clipping_axis,
        fact.label_time,
    )


def _jaam_kood_from_known(
    station: str,
    product: ProductId,
    aegrida_nimi: str,
    known_series: tuple[SourceSeries, ...],
) -> int | None:
    suffix = f":{aegrida_nimi}"
    for item in known_series:
        if item.station_id != station or item.product_id != str(product):
            continue
        if item.identity.namespace != FH_NAMESPACE or item.identity.published_id is None:
            continue
        published = item.identity.published_id
        if not published.endswith(suffix):
            continue
        code_part = published[: -len(suffix)]
        if code_part.isascii() and code_part.isdigit() and int(code_part) > 0:
            return int(code_part)
    return None


def _origin(response: TransportResponse, *, acquisition_id: str | None = None) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=response.url,
        request_parameters=response.request_parameters,
        status_code=response.status_code,
        retrieved_at=response.retrieved_at,
        content_type=response.content_type if response.content_type is not None else UnknownOriginFact(),
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
        attempts=response.attempts,
        attempt_traces=response.attempt_traces,
        acquisition_id=acquisition_id,
    )


def _request_target(
    station: str,
    product: ProductId,
    known_series: tuple[SourceSeries, ...],
    *,
    jaam_kood: int | None = None,
) -> SourceSeries | SourceRequestTarget:
    matching = tuple(item for item in known_series if item.station_id == station and item.product_id == str(product))
    if len(matching) == 1:
        return matching[0]
    if jaam_kood is not None:
        return reused_series(source_series(station, str(product), jaam_kood=jaam_kood, origin="mapping"), known_series)
    return SourceRequestTarget(station, str(product))


@dataclass(frozen=True, slots=True)
class _StationCodeLookup:
    codes: tuple[int, ...] = ()
    lookup_id: str | None = None
    retrieved_at: datetime | None = None
    transport_request: TransportRequest | None = None
    transport_failure: TransportFailure | CredentialExchangeError | None = None
    malformed_reason: str | None = None


def _lookup_station_codes(
    station: str,
    transport: Transport,
    calls: list[SourceCallOrigin],
) -> _StationCodeLookup:
    """Look up `f_seirejaamad` `kood` integers once per station across hourly products."""
    request = TransportRequest(
        method=HttpMethod.GET,
        url=_SEIREJAAMAD_URL,
        params={"kkr_kood": f"eq.{station}", "seiretyyp": "eq.HJ", "select": "kkr_kood,kood"},
        headers=_JSON_HEADERS,
    )
    response = attempt_request(transport, request)
    if isinstance(response, (TransportFailure, CredentialExchangeError)):
        return _StationCodeLookup(transport_request=request, transport_failure=response)

    lookup_id = uuid4().hex
    calls.append(_origin(response, acquisition_id=lookup_id))
    try:
        document = json.loads(response.content)
        if not isinstance(document, list):
            raise ValueError("f_seirejaamad lookup response must be a JSON list")
        if len(document) > 1:
            raise ValueError(f"f_seirejaamad lookup returned {len(document)} rows for {station!r}")
        if not document:
            codes: tuple[int, ...] = ()
        else:
            entry = document[0]
            if not isinstance(entry, dict) or entry.get("kkr_kood") != station:
                raise ValueError(f"f_seirejaamad lookup row contradicts station {station!r}")
            codes = parse_jaam_kood(entry.get("kood"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, FatalContractError) as error:
        return _StationCodeLookup(
            lookup_id=lookup_id,
            retrieved_at=response.retrieved_at,
            malformed_reason=f"Malformed Keskkonnaandmed f_seirejaamad lookup response: {error}",
        )
    return _StationCodeLookup(codes=codes, lookup_id=lookup_id, retrieved_at=response.retrieved_at)


def _materialize_station_code_outcome(
    station: str,
    product: ProductId,
    lookup: _StationCodeLookup,
    *,
    known_series: tuple[SourceSeries, ...],
    requested_window: SeriesWindow,
    pair_scope: SeriesScope,
) -> tuple[
    FailedSourceRequest | None,
    InventorySnapshot | None,
    RetrievalOutcome | None,
    Issue | None,
]:
    if lookup.transport_failure is not None:
        assert lookup.transport_request is not None
        failure = FailedSourceRequest(
            uuid4().hex,
            _request_target(station, product, known_series),
            requested_window,
            lookup.transport_request,
            lookup.transport_failure,
        )
        return failure, None, None, None

    assert lookup.lookup_id is not None
    lookup_id = lookup.lookup_id
    evidence = (f"source-call:{lookup_id}",)
    if lookup.malformed_reason is not None:
        reason = lookup.malformed_reason
        outcome = RetrievalOutcome(
            outcome_id=stable_id(lookup_id, station, str(product), "failed"),
            series_id=None,
            station_id=station,
            product_id=str(product),
            window=requested_window,
            status=OutcomeStatus.FAILED,
            reason=reason,
            retrieved_at=lookup.retrieved_at,
            calls=(lookup_id,),
        )
        inventory = InventorySnapshot(
            snapshot_id=stable_id(lookup_id, station, str(product), "failed-inventory"),
            scope=pair_scope,
            members=(),
            completeness=InventoryCompleteness.INCOMPLETE,
            access="Keskkonnaandmed /f_seirejaamad",
            origin="response",
            acquired_at=lookup.retrieved_at,
            window=requested_window,
            evidence=evidence,
            reason=reason,
        )
        issue = Issue(
            severity="error",
            code="source.unsupported_structure",
            message=reason,
            details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
            provider_id=_PROVIDER_ID,
        )
        return None, inventory, outcome, issue

    if not lookup.codes:
        reason = f"Station {station} has no active Keskkonnaandmed f_hydroseire jaam_kood"
        outcome = RetrievalOutcome(
            outcome_id=stable_id(lookup_id, station, str(product), "no-match"),
            series_id=None,
            station_id=station,
            product_id=str(product),
            window=requested_window,
            status=OutcomeStatus.NO_MATCH,
            reason=reason,
            retrieved_at=lookup.retrieved_at,
            calls=(lookup_id,),
        )
        inventory = InventorySnapshot(
            snapshot_id=stable_id(lookup_id, station, str(product), "no-match-inventory"),
            scope=pair_scope,
            members=(),
            completeness=InventoryCompleteness.COMPLETE,
            access="Keskkonnaandmed /f_seirejaamad",
            origin="response",
            acquired_at=lookup.retrieved_at,
            window=requested_window,
            evidence=evidence,
        )
        issue = Issue(
            severity="warning",
            code="source.no_match",
            message=reason,
            details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
            provider_id=_PROVIDER_ID,
        )
        return None, inventory, outcome, issue

    return None, None, None, None


def _select_active_jaam_kood(
    station: str,
    product: ProductId,
    coords: FHydroseireCoordinates,
    codes: tuple[int, ...],
    lookup_id: str,
    transport: Transport,
    *,
    known_series: tuple[SourceSeries, ...],
    requested_window: SeriesWindow,
    pair_scope: SeriesScope,
    calls: list[SourceCallOrigin],
) -> tuple[
    int | None,
    tuple[str, ...],
    FailedSourceRequest | None,
    InventorySnapshot | None,
    RetrievalOutcome | None,
    Issue | None,
]:
    if len(codes) == 1:
        return codes[0], (lookup_id,), None, None, None, None

    prereq_ids: list[str] = [lookup_id]
    for code in codes:
        probe_req = TransportRequest(
            method=HttpMethod.GET,
            url=_FH_URL,
            params={
                "jaam_kood": f"eq.{code}",
                "aegrida_nimi": f"eq.{coords.aegrida_nimi}",
                "select": "jaam_kood",
                "limit": "1",
            },
            headers=_FH_HEADERS,
        )
        probe_resp = attempt_request(transport, probe_req)
        if isinstance(probe_resp, (TransportFailure, CredentialExchangeError)):
            failure = FailedSourceRequest(
                uuid4().hex,
                _request_target(station, product, known_series),
                requested_window,
                probe_req,
                probe_resp,
                prerequisite_acquisition_ids=tuple(prereq_ids),
            )
            return None, tuple(prereq_ids), failure, None, None, None
        probe_id = uuid4().hex
        calls.append(
            SourceCallOrigin(
                url=probe_resp.url,
                request_parameters=probe_resp.request_parameters,
                status_code=probe_resp.status_code,
                retrieved_at=probe_resp.retrieved_at,
                content_type=probe_resp.content_type if probe_resp.content_type is not None else UnknownOriginFact(),
                source_path=UnknownOriginFact(),
                query=UnknownOriginFact(),
                attempts=probe_resp.attempts,
                attempt_traces=probe_resp.attempt_traces,
                acquisition_id=probe_id,
                prerequisite_acquisition_ids=tuple(prereq_ids),
            )
        )
        prereq_ids.append(probe_id)
        try:
            probe_rows = json.loads(probe_resp.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            reason = f"Malformed Keskkonnaandmed probe response for jaam_kood {code}: {error}"
            outcome = RetrievalOutcome(
                outcome_id=stable_id(probe_id, station, str(product), "failed"),
                series_id=None,
                station_id=station,
                product_id=str(product),
                window=requested_window,
                status=OutcomeStatus.FAILED,
                reason=reason,
                retrieved_at=probe_resp.retrieved_at,
                calls=tuple(prereq_ids),
            )
            inventory = InventorySnapshot(
                snapshot_id=stable_id(probe_id, station, str(product), "failed-inventory"),
                scope=pair_scope,
                members=(),
                completeness=InventoryCompleteness.INCOMPLETE,
                access="Keskkonnaandmed /f_hydroseire",
                origin="response",
                acquired_at=probe_resp.retrieved_at,
                window=requested_window,
                evidence=tuple(f"source-call:{cid}" for cid in prereq_ids),
                reason=reason,
            )
            issue = Issue(
                severity="error",
                code="source.unsupported_structure",
                message=reason,
                details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
                provider_id=_PROVIDER_ID,
            )
            return None, tuple(prereq_ids), None, inventory, outcome, issue
        if isinstance(probe_rows, list) and probe_rows:
            return code, tuple(prereq_ids), None, None, None, None

    reason = f"No candidate jaam_kood {codes!r} publishes {coords.aegrida_nimi!r} in f_hydroseire"
    outcome = RetrievalOutcome(
        outcome_id=stable_id(prereq_ids[-1], station, str(product), "no-match"),
        series_id=None,
        station_id=station,
        product_id=str(product),
        window=requested_window,
        status=OutcomeStatus.NO_MATCH,
        reason=reason,
        calls=tuple(prereq_ids),
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(prereq_ids[-1], station, str(product), "no-match-inventory"),
        scope=pair_scope,
        members=(),
        completeness=InventoryCompleteness.COMPLETE,
        access="Keskkonnaandmed /f_hydroseire",
        origin="response",
        window=requested_window,
        evidence=tuple(f"source-call:{cid}" for cid in prereq_ids),
    )
    issue = Issue(
        severity="warning",
        code="source.no_match",
        message=reason,
        details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
        provider_id=_PROVIDER_ID,
    )
    return None, tuple(prereq_ids), None, inventory, outcome, issue


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
    """Acquire bounded EstModel daily chunks and `f_hydroseire` UTC spans."""
    if not stations or not products:
        raise FatalContractError("ee_est fetch requires at least one station and product")
    for station in stations:
        _validate_station_id(station)

    validated_products: list[
        tuple[ProductId, EstModelCoordinates | FHydroseireCoordinates, tuple[RenderedWindow, ...]]
    ] = []
    for product in products:
        try:
            product_config = config.products[product]
        except KeyError as error:
            raise FatalContractError(f"ee_est product is absent from provider config: {product}") from error
        coords = product_config.coordinates.value
        if not isinstance(coords, (EstModelCoordinates, FHydroseireCoordinates)):
            raise FatalContractError(f"ee_est product has invalid source coordinates: {product}")
        windows = rendered_windows.get(product, ())
        if not windows:
            raise FatalContractError(f"ee_est product requires at least one rendered window: {product}")
        for window in windows:
            if window.bounds is None or window.stop is None:
                raise FatalContractError(f"ee_est product requires closed bounds and stop: {product}")
        validated_products.append((product, coords, windows))

    requested_window = SeriesWindow(
        start=datetime.fromisoformat(fetch_window.start.isoformat()),
        end=datetime.fromisoformat(fetch_window.end.isoformat()),
    )
    payloads: list[Payload] = []
    failures: list[FailedSourceRequest] = []
    definitions: dict[str, SourceSeries] = {}
    inventories: list[InventorySnapshot] = []
    outcomes: list[RetrievalOutcome] = []
    issues: list[Issue] = []
    calls: list[SourceCallOrigin] = []
    station_codes_cache: dict[str, _StationCodeLookup] = {}

    for station in stations:
        for product, coords, windows in validated_products:
            unrestricted_scope = SeriesScope(
                provider_ids=("ee_est",),
                station_ids=(station,),
                product_ids=(str(product),),
            )
            pair_scope = (scope or unrestricted_scope).model_copy(
                update={"station_ids": (station,), "product_ids": (str(product),)}
            )
            if isinstance(coords, EstModelCoordinates):
                target = reused_series(source_series(station, str(product), origin="mapping"), known_series)
                pair_payloads: list[Payload] = []
                for window in windows:
                    assert window.bounds is not None and window.stop is not None
                    chunk_window = SeriesWindow(
                        start=datetime.fromisoformat(window.bounds.start.isoformat()),
                        end=datetime.fromisoformat(window.bounds.end.isoformat()),
                    )
                    request = TransportRequest(
                        method=HttpMethod.GET,
                        url=f"{_ESTMODEL_BASE_URL}/{station}/measurements",
                        params={
                            "parameter": coords.parameter,
                            "type": coords.aggregation_type,
                            "start-year": window.start,
                            "end-year": window.stop,
                        },
                        headers=_JSON_HEADERS,
                    )
                    response = attempt_series_request(transport, request, target, chunk_window)
                    if isinstance(response, FailedSourceRequest):
                        failures.append(response)
                        continue
                    item_payload = Payload(
                        source_coordinates=config.products[product].coordinates,
                        station_products=((station, product),),
                        fetch_window=window.bounds,
                        content=response.content,
                        origin=_origin(response),
                        prerequisite_calls=response.prerequisite_calls,
                        scope=pair_scope,
                        known_series=known_series,
                        attempt_traces=response.attempt_traces,
                    )
                    payloads.append(item_payload)
                    pair_payloads.append(item_payload)
                if pair_payloads:
                    definitions[target.series_id] = target
                    instants = tuple(
                        item.origin.retrieved_at
                        for item in pair_payloads
                        if isinstance(item.origin.retrieved_at, datetime)
                    )
                    inventories.append(
                        InventorySnapshot(
                            snapshot_id=stable_id(
                                "ee_est",
                                "estmodel-pair-inventory",
                                station,
                                str(product),
                                requested_window.model_dump_json(),
                                *(item.acquisition_id for item in pair_payloads),
                            ),
                            scope=unrestricted_scope,
                            members=(target.series_id,),
                            member_facts=((target.series_id, tuple(fact.facts_id for fact in target.facts)),),
                            completeness=InventoryCompleteness.COMPLETE,
                            access=f"EstModel /{station}/measurements {coords.parameter}:{coords.aggregation_type}",
                            origin="response",
                            acquired_at=max(instants) if instants else None,
                            window=requested_window,
                            evidence=tuple(f"source-call:{item.acquisition_id}" for item in pair_payloads),
                        )
                    )
                continue

            jaam_kood = _jaam_kood_from_known(station, product, coords.aegrida_nimi, known_series)
            prereq_ids: tuple[str, ...] = ()
            if jaam_kood is None:
                lookup = station_codes_cache.get(station)
                if lookup is None:
                    lookup = _lookup_station_codes(station, transport, calls)
                    station_codes_cache[station] = lookup
                fail, inv, out, iss = _materialize_station_code_outcome(
                    station,
                    product,
                    lookup,
                    known_series=known_series,
                    requested_window=requested_window,
                    pair_scope=pair_scope,
                )
                if fail is not None:
                    failures.append(fail)
                    continue
                if inv is not None or out is not None or iss is not None:
                    if inv is not None:
                        inventories.append(inv)
                    if out is not None:
                        outcomes.append(out)
                    if iss is not None:
                        issues.append(iss)
                    continue
                assert lookup.codes and lookup.lookup_id is not None
                jaam_kood, prereq_ids, fail, inv, out, iss = _select_active_jaam_kood(
                    station,
                    product,
                    coords,
                    lookup.codes,
                    lookup.lookup_id,
                    transport,
                    known_series=known_series,
                    requested_window=requested_window,
                    pair_scope=pair_scope,
                    calls=calls,
                )
                if fail is not None:
                    failures.append(fail)
                    continue
                if jaam_kood is None:
                    if inv is not None:
                        inventories.append(inv)
                    if out is not None:
                        outcomes.append(out)
                    if iss is not None:
                        issues.append(iss)
                    continue

            obs_coords = replace(coords, jaam_kood=jaam_kood)
            target = reused_series(
                source_series(station, str(product), jaam_kood=jaam_kood, origin="mapping"), known_series
            )
            fh_payloads: list[Payload] = []
            for window in windows:
                assert window.bounds is not None and window.stop is not None
                chunk_window = SeriesWindow(
                    start=datetime.fromisoformat(window.bounds.start.isoformat()),
                    end=datetime.fromisoformat(window.bounds.end.isoformat()),
                )
                request = TransportRequest(
                    method=HttpMethod.GET,
                    url=_FH_URL,
                    params={
                        "jaam_kood": f"eq.{jaam_kood}",
                        "aegrida_nimi": f"eq.{coords.aegrida_nimi}",
                        "and": f"(timeline_ts_utc.gte.{window.start},timeline_ts_utc.lte.{window.stop})",
                        "select": "jaam_kood,aegrida_nimi,timeline_ts_utc,vaartus",
                        "order": "timeline_ts_utc.asc",
                    },
                    headers=_FH_HEADERS,
                )
                attempted = attempt_request(transport, request)
                if isinstance(attempted, (TransportFailure, CredentialExchangeError)):
                    failures.append(
                        FailedSourceRequest(
                            uuid4().hex,
                            target,
                            chunk_window,
                            request,
                            attempted,
                            prerequisite_acquisition_ids=prereq_ids,
                        )
                    )
                    continue
                item_payload = Payload(
                    source_coordinates=SourceCoordinates(obs_coords),
                    station_products=((station, product),),
                    fetch_window=window.bounds,
                    content=attempted.content,
                    origin=_origin(attempted),
                    prerequisite_calls=attempted.prerequisite_calls,
                    scope=pair_scope,
                    known_series=known_series,
                    attempt_traces=attempted.attempt_traces,
                    prerequisite_acquisition_ids=prereq_ids,
                )
                payloads.append(item_payload)
                fh_payloads.append(item_payload)
            if fh_payloads:
                definitions[target.series_id] = target
                instants = tuple(
                    item.origin.retrieved_at for item in fh_payloads if isinstance(item.origin.retrieved_at, datetime)
                )
                inventories.append(
                    InventorySnapshot(
                        snapshot_id=stable_id(
                            "ee_est",
                            "f-hydroseire-pair-inventory",
                            station,
                            str(product),
                            target.series_id,
                            requested_window.model_dump_json(),
                            *(item.acquisition_id for item in fh_payloads),
                        ),
                        scope=unrestricted_scope,
                        members=(target.series_id,),
                        member_facts=((target.series_id, tuple(fact.facts_id for fact in target.facts)),),
                        completeness=InventoryCompleteness.COMPLETE,
                        access=f"Keskkonnaandmed /f_hydroseire {jaam_kood}:{coords.aegrida_nimi}",
                        origin="response",
                        acquired_at=max(instants) if instants else None,
                        window=requested_window,
                        evidence=tuple(f"source-call:{item.acquisition_id}" for item in fh_payloads),
                    )
                )

    return SourceAcquisition(
        value=tuple(payloads),
        issues=tuple(issues),
        series=tuple(definitions.values()),
        inventories=tuple(inventories),
        outcomes=tuple(outcomes),
        calls=tuple(calls),
        failed_requests=tuple(failures),
    )

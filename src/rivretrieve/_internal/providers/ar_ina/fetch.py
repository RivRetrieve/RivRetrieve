"""Acquire Argentina INA Alerta5 series lookups and punctual observation chunks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast
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
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.ar_ina.config import (
    ArInaSeriesLookupCoordinates,
    ArInaSourceCoordinates,
)
from rivretrieve._internal.providers.ar_ina.series import (
    CATALOGUE_IDENTITY_EVIDENCE,
    NAMESPACE,
    SPECS_BY_PRODUCT_ID,
    source_series,
    validate_series_record_metadata,
)
from rivretrieve._internal.source_acquisition import (
    FailedSourceRequest,
    SourceRequestTarget,
    attempt_request,
)
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    PhysicalFacts,
    RestrictionKind,
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

_PROVIDER_ID = ProviderId("ar_ina")
_SERIES_URL = "https://alerta.ina.gob.ar/a5/obs/puntual/series"


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


def resolve_series_lookup(
    content: bytes,
    station: str,
    product: ProductId,
    *,
    evidence: str,
    known_series: tuple[SourceSeries, ...] = (),
) -> tuple[SourceSeries, ...]:
    """Validate an INA ``/obs/puntual/series`` JSON response for one station and product."""
    spec = SPECS_BY_PRODUCT_ID.get(str(product))
    if spec is None:
        raise FatalContractError(f"Unsupported INA Alerta5 product_id: {product!r}")

    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("INA /obs/puntual/series response is not valid JSON") from error

    if not isinstance(document, dict) or not isinstance(document.get("rows"), list):
        raise UnsupportedSourceStructureError("INA /obs/puntual/series response must contain a JSON rows array")

    if "is_last_page" in document and document["is_last_page"] is not True:
        raise UnsupportedSourceStructureError(
            "INA /obs/puntual/series response is paginated (is_last_page != true); complete inventory is not established"
        )

    raw_rows = cast("list[object]", document["rows"])
    if "total" in document:
        raw_total = document["total"]
        if isinstance(raw_total, bool) or not isinstance(raw_total, int | str):
            raise UnsupportedSourceStructureError(f"INA /obs/puntual/series total field is malformed: {raw_total!r}")
        if isinstance(raw_total, str):
            stripped = raw_total.strip()
            if not stripped.isascii() or not stripped.isdigit():
                raise UnsupportedSourceStructureError(
                    f"INA /obs/puntual/series total field is not an integer: {raw_total!r}"
                )
            total_count = int(stripped)
        else:
            total_count = raw_total
        if total_count != len(raw_rows):
            raise UnsupportedSourceStructureError(
                f"INA /obs/puntual/series total {total_count} contradicts {len(raw_rows)} returned rows"
            )

    resolved: list[SourceSeries] = []
    seen_ids: set[int] = set()
    for index, entry in enumerate(raw_rows):
        if not isinstance(entry, dict):
            raise UnsupportedSourceStructureError(f"INA /obs/puntual/series row {index} must be a JSON object")
        row_map = cast("dict[str, object]", entry)
        if "tipo" in row_map and row_map["tipo"] != "puntual":
            raise UnsupportedSourceStructureError(
                f"INA /obs/puntual/series row {index} has non-puntual tipo {row_map['tipo']!r}"
            )
        raw_id = row_map.get("id")
        if type(raw_id) is not int or raw_id <= 0:
            raise UnsupportedSourceStructureError(
                f"INA /obs/puntual/series row {index} lacks a positive integer series id: {raw_id!r}"
            )
        if raw_id in seen_ids:
            raise UnsupportedSourceStructureError(f"INA /obs/puntual/series repeats published series_id {raw_id}")
        seen_ids.add(raw_id)

        estacion = row_map.get("estacion")
        if not isinstance(estacion, dict):
            raise UnsupportedSourceStructureError(
                f"INA /obs/puntual/series series {raw_id} lacks embedded estacion metadata"
            )
        est_id = cast("dict[str, object]", estacion).get("id")
        if type(est_id) is not int or str(est_id) != station:
            raise UnsupportedSourceStructureError(
                f"INA /obs/puntual/series series {raw_id} estacion.id {est_id!r} contradicts requested station {station!r}"
            )

        proc_obj = row_map.get("procedimiento")
        if not isinstance(proc_obj, dict):
            raise UnsupportedSourceStructureError(
                f"INA /obs/puntual/series series {raw_id} lacks embedded procedimiento metadata"
            )
        proc_id = cast("dict[str, object]", proc_obj).get("id")
        if type(proc_id) is not int:
            raise UnsupportedSourceStructureError(
                f"INA /obs/puntual/series series {raw_id} procedimiento.id {proc_id!r} must be an integer"
            )

        try:
            unit_abrev = validate_series_record_metadata(
                row_map,
                spec,
                series_id=raw_id,
                proc_id=proc_id,
            )
            definition = source_series(
                station,
                str(product),
                published_series_id=raw_id,
                source_unit=unit_abrev,
                origin="response",
                identity_evidence=evidence,
            )
        except FatalContractError as error:
            raise UnsupportedSourceStructureError(str(error)) from error

        resolved.append(reused_series(definition, known_series))

    return tuple(sorted(resolved, key=lambda item: int(item.identity.published_id or "0")))


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
    """Fetch INA Alerta5 punctual observation spans while verifying unestablished series first.

    ``GET /obs/puntual/series/{series_id}/observaciones`` with ``skip_nulls=true``
    avoids upstream ``generateRegularSeries`` boundary-null corruption, but
    bypasses INA's server-side series existence check (returning ``200 []`` even
    for nonexistent ``series_id`` values) and omits ``estacion_id`` on
    observation rows. Consequently, whenever ``known_series`` does not already
    establish the concrete ``INA.Alerta5.series_id`` for a station-product pair
    or an explicit caller selector, ``fetch`` first queries
    ``GET /obs/puntual/series?estacion_id=...&var_id=...&proc_id=...&format=json``
    to verify station ownership and series existence before requesting
    observation chunks.
    """
    if not stations or not products:
        raise FatalContractError("ar_ina fetch requires at least one station and product")

    resolved_products: list[tuple[ProductId, ArInaSourceCoordinates, tuple[RenderedWindow, ...]]] = []
    for product in products:
        coords = _coordinates(product, config)
        windows = rendered_windows.get(product, ())
        if not windows:
            raise FatalContractError(f"ar_ina fetch requires at least one rendered window for {product}")
        for window in windows:
            if window.stop is None or window.bounds is None:
                raise FatalContractError(
                    f"ar_ina rendered windows for {product} require closed endpoints and engine bounds"
                )
        resolved_products.append((product, coords, windows))

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

    for station in stations:
        if not station or station.strip() != station:
            raise FatalContractError(f"ar_ina station identifier must be a nonblank canonical string: {station!r}")
        for product, coords, windows in resolved_products:
            pair_scope = (scope or SeriesScope(provider_ids=("ar_ina",))).model_copy(
                update={"station_ids": (station,), "product_ids": (str(product),)}
            )
            pair_known = tuple(
                item
                for item in known_series
                if item.station_id == station
                and item.product_id == str(product)
                and item.identity.namespace == NAMESPACE
                and item.identity.published_id is not None
                and item.identity.published_id.isascii()
                and item.identity.published_id.isdigit()
            )
            known_ids = {item.series_id for item in pair_known}
            known_variants = {
                value
                for item in pair_known
                for value in (item.variant, item.identity.published_id)
                if value is not None
            }
            explicit_satisfied = pair_scope.restriction is not RestrictionKind.EXPLICIT or (
                set(pair_scope.series_ids).issubset(known_ids) and set(pair_scope.variants).issubset(known_variants)
            )

            lookup_payload: Payload | None = None
            lookup_retrieved_at: datetime | None = None
            inventory_incomplete_reason: str | None = None

            if coords.published_series_id is not None:
                fixed = reused_series(
                    source_series(
                        station,
                        str(product),
                        published_series_id=coords.published_series_id,
                        origin="catalogue",
                        identity_evidence=CATALOGUE_IDENTITY_EVIDENCE,
                    ),
                    pair_known,
                )
                established_series: tuple[SourceSeries, ...] = (fixed,)
                prerequisite_ids: tuple[str, ...] = ()
            elif not pair_known or not explicit_satisfied:
                lookup_request = TransportRequest(
                    method=HttpMethod.GET,
                    url=_SERIES_URL,
                    params={
                        "estacion_id": station,
                        "var_id": str(coords.var_id),
                        "proc_id": str(coords.proc_id),
                        "format": "json",
                    },
                    headers={"Accept": "application/json"},
                )
                lookup_response = attempt_request(transport, lookup_request)
                if isinstance(lookup_response, (TransportFailure, CredentialExchangeError)):
                    failures.append(
                        FailedSourceRequest(
                            uuid4().hex,
                            _request_target(station, product, pair_known),
                            requested_window,
                            lookup_request,
                            lookup_response,
                        )
                    )
                    continue

                lookup_retrieved_at = lookup_response.retrieved_at
                lookup_payload = Payload(
                    source_coordinates=SourceCoordinates(ArInaSeriesLookupCoordinates(coords.var_id, coords.proc_id)),
                    station_products=((station, product),),
                    fetch_window=fetch_window,
                    content=lookup_response.content,
                    origin=_origin(lookup_response),
                    prerequisite_calls=lookup_response.prerequisite_calls,
                    scope=pair_scope,
                    known_series=pair_known,
                    attempt_traces=lookup_response.attempt_traces,
                )
                payloads.append(lookup_payload)
                try:
                    discovered = resolve_series_lookup(
                        lookup_response.content,
                        station,
                        product,
                        evidence=f"source-call:{lookup_payload.acquisition_id}",
                        known_series=pair_known,
                    )
                except UnsupportedSourceStructureError:
                    # parse(lookup_payload) records the bounded structural failure.
                    continue

                if not discovered and not pair_known:
                    # parse(lookup_payload) records the complete empty inventory and NO_MATCH outcome.
                    continue

                discovered_by_id = {item.series_id: item for item in discovered}
                historical = {item.series_id: item for item in pair_known if item.series_id not in discovered_by_id}
                if historical:
                    inventory_incomplete_reason = (
                        "Previously known INA series is absent from current /obs/puntual/series metadata; "
                        "historical inventory remains unresolved"
                    )
                    issues.append(
                        Issue(
                            severity="warning",
                            code="source.inventory_unresolved",
                            message=inventory_incomplete_reason,
                            details={"station_id": station, "product_id": str(product)},
                            provider_id=_PROVIDER_ID,
                        )
                    )
                merged = {**historical, **discovered_by_id}
                established_series = tuple(
                    sorted(merged.values(), key=lambda item: int(item.identity.published_id or "0"))
                )
                prerequisite_ids = (lookup_payload.acquisition_id,)
            else:
                established_series = tuple(sorted(pair_known, key=lambda item: int(item.identity.published_id or "0")))
                prerequisite_ids = ()

            for item in established_series:
                definitions[item.series_id] = item

            targets = tuple(item for item in established_series if pair_scope.matches(item))
            identity_only = pair_scope.model_copy(update={"predicates": ()})
            unresolved_predicate = not targets and any(
                getattr(fact, predicate.field).value is None
                for item in established_series
                if identity_only.matches(item)
                for fact in item.facts
                for predicate in pair_scope.predicates
            )
            incomplete_reason = inventory_incomplete_reason or (
                "INA Alerta5 metadata does not establish the requested physical fact predicate"
                if unresolved_predicate
                else None
            )

            unrestricted_scope = SeriesScope(
                provider_ids=("ar_ina",),
                station_ids=(station,),
                product_ids=(str(product),),
            )
            pair_inventory = InventorySnapshot(
                snapshot_id=stable_id(
                    "ar_ina",
                    "pair-series-inventory",
                    station,
                    str(product),
                    requested_window.model_dump_json(),
                    lookup_payload.acquisition_id if lookup_payload is not None else "known-series",
                    incomplete_reason,
                    *(item.series_id for item in established_series),
                ),
                scope=unrestricted_scope,
                members=tuple(item.series_id for item in established_series),
                member_facts=tuple(
                    (item.series_id, tuple(fact.facts_id for fact in item.facts)) for item in established_series
                ),
                completeness=(
                    InventoryCompleteness.INCOMPLETE
                    if incomplete_reason is not None
                    else InventoryCompleteness.COMPLETE
                ),
                access=(
                    "INA Alerta5 /obs/puntual/series station-variable-procedure inventory"
                    if lookup_payload is not None
                    else "INA Alerta5 catalogue-established station-variable-procedure inventory"
                ),
                origin="response",
                acquired_at=lookup_retrieved_at,
                window=requested_window,
                evidence=(
                    (f"source-call:{lookup_payload.acquisition_id}",)
                    if lookup_payload is not None
                    else (CATALOGUE_IDENTITY_EVIDENCE,)
                ),
                reason=incomplete_reason,
            )
            inventories.append(pair_inventory)

            if not targets:
                if pair_scope.restriction is RestrictionKind.ALL:
                    status = OutcomeStatus.UNRESOLVED if incomplete_reason is not None else OutcomeStatus.NO_MATCH
                    reason = incomplete_reason or (
                        "INA Alerta5 publishes no series matching the requested physical facts"
                    )
                    outcome = RetrievalOutcome(
                        outcome_id=stable_id(
                            pair_inventory.snapshot_id,
                            pair_scope.model_dump_json(),
                            status,
                            reason,
                        ),
                        series_id=None,
                        station_id=station,
                        product_id=str(product),
                        window=requested_window,
                        status=status,
                        reason=reason,
                        retrieved_at=lookup_retrieved_at,
                    )
                    outcomes.append(outcome)
                    issues.append(
                        Issue(
                            severity="warning",
                            code="source.inventory_unresolved"
                            if status is OutcomeStatus.UNRESOLVED
                            else "source.no_match",
                            message=reason,
                            details={
                                "station_id": station,
                                "product_id": str(product),
                                "outcome_id": outcome.outcome_id,
                            },
                            provider_id=_PROVIDER_ID,
                        )
                    )
                continue

            for target in targets:
                published_id = target.identity.published_id
                assert published_id is not None
                pub_id_int = int(published_id)
                obs_coords = ArInaSourceCoordinates(coords.var_id, coords.proc_id, pub_id_int)
                for window in windows:
                    assert window.stop is not None and window.bounds is not None
                    chunk_window = SeriesWindow(
                        start=datetime.fromisoformat(window.bounds.start.isoformat()),
                        end=datetime.fromisoformat(window.bounds.end.isoformat()),
                    )
                    obs_request = TransportRequest(
                        method=HttpMethod.GET,
                        url=f"{_SERIES_URL}/{pub_id_int}/observaciones",
                        params={
                            "timestart": window.start,
                            "timeend": window.stop,
                            "skip_nulls": "true",
                        },
                        headers={"Accept": "application/json"},
                    )
                    obs_response = attempt_request(transport, obs_request)
                    if isinstance(obs_response, (TransportFailure, CredentialExchangeError)):
                        failures.append(
                            FailedSourceRequest(
                                uuid4().hex,
                                target,
                                chunk_window,
                                obs_request,
                                obs_response,
                                prerequisite_acquisition_ids=prerequisite_ids,
                            )
                        )
                        continue
                    payloads.append(
                        Payload(
                            source_coordinates=SourceCoordinates(obs_coords),
                            station_products=((station, product),),
                            fetch_window=window.bounds,
                            content=obs_response.content,
                            origin=_origin(obs_response),
                            prerequisite_calls=obs_response.prerequisite_calls,
                            scope=pair_scope,
                            known_series=(target,),
                            attempt_traces=obs_response.attempt_traces,
                            prerequisite_acquisition_ids=prerequisite_ids,
                        )
                    )

    return SourceAcquisition(
        value=tuple(payloads),
        issues=tuple(issues),
        failed_requests=tuple(failures),
        series=tuple(definitions.values()),
        inventories=tuple(inventories),
        outcomes=tuple(outcomes),
    )


def _coordinates(product: ProductId, config: ProviderConfig) -> ArInaSourceCoordinates:
    try:
        value = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"ar_ina product is absent from provider config: {product}") from error
    if not isinstance(value, ArInaSourceCoordinates):
        raise FatalContractError(f"ar_ina product has invalid source coordinates: {product}")
    return value


def _request_target(
    station: str,
    product: ProductId,
    known_series: tuple[SourceSeries, ...],
) -> SourceSeries | SourceRequestTarget:
    if len(known_series) == 1:
        return known_series[0]
    return SourceRequestTarget(station, str(product))


def _origin(response: TransportResponse) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=response.url,
        request_parameters=response.request_parameters,
        status_code=response.status_code,
        retrieved_at=response.retrieved_at,
        content_type=response.content_type if response.content_type is not None else UnknownOriginFact(),
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
        attempts=response.attempts,
    )

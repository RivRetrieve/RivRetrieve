"""Normalize Argentina INA Alerta5 series lookups and punctual observation chunks."""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.ar_ina.config import (
    ArInaSeriesLookupCoordinates,
    ArInaSourceCoordinates,
)
from rivretrieve._internal.providers.ar_ina.fetch import resolve_series_lookup, reused_series
from rivretrieve._internal.providers.ar_ina.series import (
    SPECS_BY_PRODUCT_ID,
    SeriesProductSpec,
    source_series,
    validate_observation_row,
)
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
    validate_series_rows,
)

_PROVIDER_ID = ProviderId("ar_ina")
_SOURCE_ZONE = "+00:00"


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Parse one INA Alerta5 series-lookup or observation payload with bounded failure scope."""
    if len(payload.station_products) != 1:
        raise FatalContractError("ar_ina payload must identify exactly one station-product pair")
    station, product = payload.station_products[0]
    configured = _validated_configured_coordinates(product, provider_config)
    payload_coords = payload.source_coordinates.value

    if isinstance(payload_coords, ArInaSeriesLookupCoordinates):
        if (payload_coords.var_id, payload_coords.proc_id) != (configured.var_id, configured.proc_id):
            raise FatalContractError("ar_ina lookup payload coordinates contradict configured product")
    elif isinstance(payload_coords, ArInaSourceCoordinates):
        if (payload_coords.var_id, payload_coords.proc_id) != (configured.var_id, configured.proc_id):
            raise FatalContractError("ar_ina observation payload coordinates contradict configured product")
        if payload_coords.published_series_id is None:
            raise FatalContractError("ar_ina observation payload requires a resolved published_series_id")
    else:
        raise FatalContractError(f"ar_ina payload has unsupported coordinate type: {type(payload_coords)!r}")

    spec = SPECS_BY_PRODUCT_ID.get(str(product))
    if spec is None:
        raise FatalContractError(f"ar_ina product lacks series specification: {product}")

    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
        axis=payload.acquisition_axis,
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    scope = payload.scope or SeriesScope(
        provider_ids=("ar_ina",),
        station_ids=(station,),
        product_ids=(str(product),),
    )

    if isinstance(payload_coords, ArInaSeriesLookupCoordinates):
        return _parse_series_lookup(payload, station, product, window, retrieved, scope)
    return _parse_observations(payload, station, product, payload_coords, spec, window, retrieved, scope)


def _validated_configured_coordinates(product: ProductId, provider_config: ProviderConfig) -> ArInaSourceCoordinates:
    try:
        configured = provider_config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"ar_ina product is absent from provider config: {product}") from error
    if not isinstance(configured, ArInaSourceCoordinates):
        raise FatalContractError(f"ar_ina product has invalid configured coordinates: {product}")
    return configured


def _parse_series_lookup(
    payload: Payload,
    station: str,
    product: ProductId,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    evidence = f"source-call:{payload.acquisition_id}"
    unrestricted_scope = SeriesScope(
        provider_ids=("ar_ina",),
        station_ids=(station,),
        product_ids=(str(product),),
    )
    try:
        discovered = resolve_series_lookup(
            payload.content,
            station,
            product,
            evidence=evidence,
            known_series=payload.known_series,
        )
    except UnsupportedSourceStructureError as error:
        return _failed_result(
            payload,
            None,
            station,
            product,
            window,
            retrieved,
            unrestricted_scope,
            access="INA Alerta5 /obs/puntual/series lookup",
            reason=str(error),
        )

    if discovered:
        # Child /observaciones payloads or FailedSourceRequest records own observation outcomes.
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), discovered, (), (), ())

    reason = (
        f"INA Alerta5 /obs/puntual/series publishes no observational series for station {station} product {product}"
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, station, str(product), "series-lookup-no-match"),
        scope=unrestricted_scope,
        members=(),
        completeness=InventoryCompleteness.COMPLETE,
        access="INA Alerta5 /obs/puntual/series station-variable-procedure inventory",
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
    )
    if scope.restriction is not RestrictionKind.ALL:
        # _finite_selector_assessments generates per-selector NO_MATCH outcomes and issues.
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (inventory,), (), ())

    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, station, str(product), "lookup-no-match"),
        series_id=None,
        station_id=station,
        product_id=str(product),
        window=window,
        status=OutcomeStatus.NO_MATCH,
        reason=reason,
        retrieved_at=retrieved,
    )
    issue = Issue(
        severity="warning",
        code="source.no_match",
        message=reason,
        details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
        provider_id=_PROVIDER_ID,
    )
    return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (inventory,), (outcome,), (issue,))


def _parse_observations(
    payload: Payload,
    station: str,
    product: ProductId,
    coords: ArInaSourceCoordinates,
    spec: SeriesProductSpec,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    assert coords.published_series_id is not None
    evidence = f"source-call:{payload.acquisition_id}"
    definition = reused_series(
        source_series(
            station,
            str(product),
            published_series_id=coords.published_series_id,
            origin="response",
            identity_evidence=evidence,
        ),
        payload.known_series,
    )
    fact = definition.facts[0]
    source_unit = fact.source_unit.value
    assert source_unit is not None

    try:
        identity_scope = scope.model_copy(update={"predicates": ()})
        if not identity_scope.matches(definition):
            raise UnsupportedSourceStructureError(
                f"INA observation series {coords.published_series_id} contradicts requested selector scope"
            )

        try:
            raw_document = json.loads(payload.content)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise UnsupportedSourceStructureError(
                f"INA /observaciones response for series {coords.published_series_id} is not valid JSON"
            ) from error

        if not isinstance(raw_document, list):
            raise UnsupportedSourceStructureError(
                f"INA /observaciones response for series {coords.published_series_id} must be a JSON array"
            )

        deduped_rows: dict[datetime, tuple[datetime, float | None, dict[str, object]]] = {}
        synthesized_null_times: list[str] = []

        for index, raw_entry in enumerate(cast("list[object]", raw_document)):
            if not isinstance(raw_entry, dict):
                raise UnsupportedSourceStructureError(
                    f"INA observation row {index} on series {coords.published_series_id} must be a JSON object"
                )
            row_map = cast("dict[str, object]", raw_entry)
            if "tipo" in row_map and row_map["tipo"] != "puntual":
                raise UnsupportedSourceStructureError(
                    f"INA observation row {index} on series {coords.published_series_id} has non-puntual tipo {row_map['tipo']!r}"
                )

            try:
                start_utc, end_utc, numeric_value = validate_observation_row(
                    row_map,
                    spec,
                    expected_series_id=coords.published_series_id,
                )
            except FatalContractError as error:
                raise UnsupportedSourceStructureError(str(error)) from error

            raw_id = row_map.get("id")
            if raw_id is None:
                if numeric_value is not None:
                    raise UnsupportedSourceStructureError(
                        f"INA observation row on series {coords.published_series_id} at {start_utc.isoformat()} "
                        "carries a numeric value without a stored observation id"
                    )
                # Omit server-synthesized generateRegularSeries grid-padding slots (id: null, valor: null).
                synthesized_null_times.append(start_utc.isoformat())
                continue
            if type(raw_id) is not int or raw_id <= 0:
                raise UnsupportedSourceStructureError(
                    f"INA observation row on series {coords.published_series_id} has invalid id {raw_id!r}"
                )

            naive_time = start_utc.replace(tzinfo=None)
            row_dict: dict[str, object] = {
                "station_id": station,
                "product_id": str(product),
                "time": naive_time,
                "value": numeric_value,
                "time_zone": _SOURCE_ZONE,
                "series_id": definition.series_id,
                "facts_id": fact.facts_id,
                "source_unit": source_unit,
            }
            existing = deduped_rows.get(naive_time)
            if existing is not None:
                prev_end, prev_val, _ = existing
                if prev_end != end_utc or prev_val != numeric_value:
                    raise UnsupportedSourceStructureError(
                        f"INA series {coords.published_series_id} publishes conflicting observations at {start_utc.isoformat()}"
                    )
                continue
            deduped_rows[naive_time] = (end_utc, numeric_value, row_dict)

        # Clip validated rows to the chunk's partition bounds so stop_extension lookahead
        # across adjacent chunks never emits cross-chunk duplicates.
        clipped_records = [
            record
            for naive_time, (_, _, record) in sorted(deduped_rows.items(), key=lambda item: item[0])
            if window.start <= naive_time <= window.end
        ]
        frame = pl.DataFrame(clipped_records, schema=RowsSchema.polars_schema)
        validate_series_rows(frame, (definition,))

        issues: list[Issue] = []
        if synthesized_null_times:
            issues.append(
                Issue(
                    severity="info",
                    code="source.synthesized_grid_null",
                    message=(
                        f"Omitted {len(synthesized_null_times)} unstored INA generateRegularSeries "
                        f"grid-padding null slot(s) on series {coords.published_series_id}"
                    ),
                    details={
                        "station_id": station,
                        "product_id": str(product),
                        "series_id": definition.series_id,
                        "count": len(synthesized_null_times),
                    },
                    provider_id=_PROVIDER_ID,
                )
            )

        status = OutcomeStatus.EMPTY if frame.is_empty() else OutcomeStatus.SUCCESS
        outcome = RetrievalOutcome(
            outcome_id=stable_id(
                payload.acquisition_id,
                definition.series_id,
                fact.facts_id,
                window.model_dump_json(),
                status,
            ),
            series_id=definition.series_id,
            station_id=station,
            product_id=str(product),
            window=window,
            status=status,
            facts_ids=(fact.facts_id,),
            retrieved_at=retrieved,
        )
        chunk_inventory = InventorySnapshot(
            snapshot_id=stable_id(
                payload.acquisition_id,
                definition.series_id,
                window.model_dump_json(),
                "chunk-inventory",
            ),
            scope=scope,
            members=(definition.series_id,),
            member_facts=((definition.series_id, (fact.facts_id,)),),
            completeness=InventoryCompleteness.INCOMPLETE,
            access=f"INA Alerta5 /obs/puntual/series/{coords.published_series_id}/observaciones chunk",
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(evidence,),
            reason="A single /observaciones response establishes only its requested series_id, not the full station-product inventory",
        )
        return ParsedSeries(frame, (definition,), (chunk_inventory,), (outcome,), tuple(issues))

    except UnsupportedSourceStructureError as error:
        return _failed_result(
            payload,
            definition,
            station,
            product,
            window,
            retrieved,
            scope,
            access=f"INA Alerta5 /obs/puntual/series/{coords.published_series_id}/observaciones chunk",
            reason=str(error),
        )


def _failed_result(
    payload: Payload,
    definition: SourceSeries | None,
    station: str,
    product: ProductId,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
    *,
    access: str,
    reason: str,
) -> ParsedSeries:
    evidence = f"source-call:{payload.acquisition_id}"
    series_id = definition.series_id if definition is not None else None
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, station, str(product), series_id, "failed", reason),
        series_id=series_id,
        station_id=station,
        product_id=str(product),
        window=window,
        status=OutcomeStatus.FAILED,
        reason=reason,
        retrieved_at=retrieved,
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, station, str(product), series_id, "failed-inventory"),
        scope=scope,
        members=(series_id,) if series_id is not None else (),
        completeness=InventoryCompleteness.INCOMPLETE,
        access=access,
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
        reason=reason,
    )
    details: dict[str, object] = {
        "station_id": station,
        "product_id": str(product),
        "outcome_id": outcome.outcome_id,
    }
    if series_id is not None:
        details["series_id"] = series_id
    issue = Issue(
        severity="error",
        code="source.unsupported_structure",
        message=reason,
        details=details,
        provider_id=_PROVIDER_ID,
    )
    return ParsedSeries(
        pl.DataFrame(schema=RowsSchema.polars_schema),
        (definition,) if definition is not None else (),
        (inventory,),
        (outcome,),
        (issue,),
    )

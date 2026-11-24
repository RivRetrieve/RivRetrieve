"""Normalize Belgium - Wallonia (`be_wal`) KiWIS lookups and ``getTimeseriesValues`` payloads."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.be_wal.annotations import BE_WAL_QUALITY_SCHEMA
from rivretrieve._internal.providers.be_wal.config import (
    BeWalTimeseriesListCoordinates,
    BeWalTimeseriesValuesCoordinates,
)
from rivretrieve._internal.providers.be_wal.series import (
    PRODUCT_BY_ID,
    ProductSpec,
    reused_series,
    source_series,
    validate_ts_id,
)
from rivretrieve._internal.source_annotations import (
    OBSERVATION_STRUCTURAL_SCHEMA,
    AnnotationBundle,
    ObservationAnnotationTable,
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
)

_PROVIDER_ID = ProviderId("be_wal")
_FIXED_CET_OFFSET = timedelta(hours=1)
_SOURCE_ZONE = "+01:00"
_EXPECTED_COLUMNS = ["Timestamp", "Value", "Quality Code", "Quality Code Name"]


def _validated_coordinates(
    payload_coords: object,
    product: ProductId,
    provider_config: ProviderConfig,
    spec: ProductSpec,
) -> BeWalTimeseriesListCoordinates | BeWalTimeseriesValuesCoordinates:
    try:
        configured = provider_config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"be_wal product is absent from provider config: {product}") from error
    if not isinstance(configured, BeWalTimeseriesValuesCoordinates):
        raise FatalContractError(f"be_wal configured coordinates have invalid type: {product}")
    if isinstance(payload_coords, BeWalTimeseriesListCoordinates):
        if payload_coords.product_id != str(product) or payload_coords.native_id != spec.native_id:
            raise FatalContractError("be_wal lookup payload coordinates contradict requested product")
        return payload_coords
    if isinstance(payload_coords, BeWalTimeseriesValuesCoordinates):
        if payload_coords.product_id != str(product) or payload_coords.product_id != configured.product_id:
            raise FatalContractError("be_wal payload coordinates contradict requested product")
        return payload_coords
    raise FatalContractError(f"be_wal payload coordinates have invalid type: {type(payload_coords)!r}")


def _parse_columns(raw_columns: object) -> list[str]:
    if isinstance(raw_columns, str):
        return [part.strip() for part in raw_columns.split(",") if part.strip()]
    if isinstance(raw_columns, list) and all(isinstance(part, str) for part in raw_columns):
        return [str(part) for part in raw_columns]
    raise UnsupportedSourceStructureError(f"KiWIS columns field has unsupported shape: {raw_columns!r}")


def _parse_utc_timestamp(raw_value: object, *, index: int) -> datetime:
    if not isinstance(raw_value, str) or not raw_value:
        raise UnsupportedSourceStructureError(f"KiWIS row {index} Timestamp must be a non-empty string")
    text = raw_value.strip()
    if text.endswith("Z"):
        normalized = text[:-1] + "+00:00"
    elif text.endswith("+00:00"):
        normalized = text
    else:
        raise UnsupportedSourceStructureError(
            f"KiWIS row {index} Timestamp {raw_value!r} must carry an explicit UTC Z/+00:00 designator"
        )
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise UnsupportedSourceStructureError(
            f"KiWIS row {index} has invalid ISO-8601 Timestamp {raw_value!r}"
        ) from error
    if parsed.utcoffset() != timedelta(0):
        raise UnsupportedSourceStructureError(f"KiWIS row {index} Timestamp {raw_value!r} must carry zero UTC offset")
    # Express UTC observation instants on Wallonia's fixed CET (+01:00) grid (station_utcoffset="-60").
    return (parsed + _FIXED_CET_OFFSET).replace(tzinfo=None)


def _finite_float_or_none(raw_value: object, *, index: int) -> float | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise UnsupportedSourceStructureError(
            f"KiWIS row {index} Value must be numeric or null, got {type(raw_value).__name__}"
        )
    try:
        numeric = float(raw_value)
    except OverflowError as error:
        raise UnsupportedSourceStructureError(f"KiWIS row {index} Value overflows float64") from error
    if not math.isfinite(numeric):
        raise UnsupportedSourceStructureError(f"KiWIS row {index} Value must be finite, got {raw_value!r}")
    return numeric


def _optional_int(raw_value: object, *, index: int) -> int | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or type(raw_value) is not int:
        raise UnsupportedSourceStructureError(
            f"KiWIS row {index} Quality Code must be an integer or null, got {type(raw_value).__name__}"
        )
    return raw_value


def _optional_str(raw_value: object, *, index: int) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise UnsupportedSourceStructureError(
            f"KiWIS row {index} Quality Code Name must be a string or null, got {type(raw_value).__name__}"
        )
    return raw_value


def _validate_block(
    payload_content: bytes,
    station: str,
    spec: ProductSpec,
    expected_ts_id: str | None,
) -> tuple[str, list[object]]:
    try:
        document = json.loads(payload_content)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise UnsupportedSourceStructureError(f"Invalid KiWIS getTimeseriesValues JSON: {error}") from error

    if isinstance(document, dict) and document.get("type") == "error":
        raise UnsupportedSourceStructureError(
            f"KiWIS getTimeseriesValues error ({document.get('code')!r}): {document.get('message')!r}"
        )
    if not isinstance(document, list) or len(document) != 1 or not isinstance(document[0], dict):
        raise UnsupportedSourceStructureError(
            "KiWIS getTimeseriesValues response must be a JSON list containing one series block"
        )

    block = cast("Mapping[str, object]", document[0])
    try:
        resolved_ts_id = validate_ts_id(str(block.get("ts_id", "")))
    except FatalContractError as error:
        raise UnsupportedSourceStructureError(f"KiWIS block lacks valid ts_id: {block.get('ts_id')!r}") from error
    if expected_ts_id is not None and resolved_ts_id != expected_ts_id:
        raise UnsupportedSourceStructureError(
            f"KiWIS block ts_id {resolved_ts_id!r} contradicts requested ts_id {expected_ts_id!r}"
        )

    if block.get("ts_name") != spec.native_id:
        raise UnsupportedSourceStructureError(
            f"KiWIS block ts_name {block.get('ts_name')!r} contradicts expected {spec.native_id!r}"
        )
    if str(block.get("station_no")) != station:
        raise UnsupportedSourceStructureError(
            f"KiWIS block station_no {block.get('station_no')!r} contradicts requested station {station!r}"
        )
    if block.get("stationparameter_name") not in spec.stationparameter_names:
        raise UnsupportedSourceStructureError(
            f"KiWIS block stationparameter_name {block.get('stationparameter_name')!r} contradicts expected {spec.stationparameter_names!r}"
        )
    if block.get("ts_unitsymbol") != spec.source_unit:
        raise UnsupportedSourceStructureError(
            f"KiWIS block ts_unitsymbol {block.get('ts_unitsymbol')!r} contradicts expected {spec.source_unit!r}"
        )

    columns = _parse_columns(block.get("columns"))
    if columns != _EXPECTED_COLUMNS:
        raise UnsupportedSourceStructureError(f"KiWIS columns {columns!r} contradict {_EXPECTED_COLUMNS!r}")

    data = block.get("data")
    if not isinstance(data, list):
        raise UnsupportedSourceStructureError("KiWIS block data field must be a JSON list")

    raw_rows = block.get("rows")
    if raw_rows is not None:
        if isinstance(raw_rows, int):
            expected_count = raw_rows
        elif isinstance(raw_rows, str) and raw_rows.isascii() and raw_rows.isdigit():
            expected_count = int(raw_rows)
        else:
            raise UnsupportedSourceStructureError(f"KiWIS block rows field has invalid shape: {raw_rows!r}")
        if expected_count != len(data):
            raise UnsupportedSourceStructureError(
                f"KiWIS block rows count {expected_count} disagrees with len(data) {len(data)}"
            )

    return resolved_ts_id, cast("list[object]", data)


def _failed_parse_result(
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
        outcome_id=stable_id(payload.acquisition_id, station, str(product), series_id, "failed"),
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
        AnnotationBundle.empty(),
    )


@dataclass(frozen=True, slots=True)
class TimeseriesListInterpretation:
    """Decoded KiWIS ``getTimeseriesList`` resolution and its engine ``ParsedSeries`` output."""

    resolved_ts_id: str | None
    scope_matched: bool
    parsed: ParsedSeries


def resolve_timeseries_list(
    content: bytes,
    station: str,
    spec: ProductSpec,
) -> str | None:
    """Validate KiWIS ``getTimeseriesList`` JSON and return unique matching ``ts_id``, or ``None``."""
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise UnsupportedSourceStructureError(f"Invalid KiWIS getTimeseriesList JSON: {error}") from error

    if isinstance(document, dict) and document.get("type") == "error":
        raise UnsupportedSourceStructureError(
            f"KiWIS getTimeseriesList error ({document.get('code')!r}): {document.get('message')!r}"
        )
    if not isinstance(document, list) or not document or not isinstance(document[0], list):
        raise UnsupportedSourceStructureError("KiWIS getTimeseriesList response must be a JSON header-plus-rows list")

    header = document[0]
    required = ("ts_id", "ts_name", "station_no", "stationparameter_name", "parametertype_name", "ts_unitsymbol")
    try:
        indices = {name: header.index(name) for name in required}
    except ValueError as error:
        raise UnsupportedSourceStructureError("KiWIS getTimeseriesList header lacks a required column") from error

    if header[0] == "error":
        raise UnsupportedSourceStructureError("KiWIS getTimeseriesList returned an error header")

    matches: list[str] = []
    for row_idx, row in enumerate(document[1:], start=1):
        if not isinstance(row, list) or len(row) != len(header):
            raise UnsupportedSourceStructureError(f"KiWIS getTimeseriesList row {row_idx} width does not match header")
        row_station = str(row[indices["station_no"]])
        row_name = str(row[indices["ts_name"]])
        row_param = str(row[indices["stationparameter_name"]])
        if row_station != station or row_name != spec.native_id or row_param not in spec.stationparameter_names:
            continue
        row_unit = str(row[indices["ts_unitsymbol"]])
        if row_unit != spec.source_unit:
            raise UnsupportedSourceStructureError(
                f"KiWIS getTimeseriesList unit {row_unit!r} contradicts expected {spec.source_unit!r} for {station}/{spec.product_id}"
            )
        matches.append(validate_ts_id(str(row[indices["ts_id"]])))

    if not matches:
        return None
    if len(matches) > 1:
        raise UnsupportedSourceStructureError(
            f"KiWIS getTimeseriesList returned multiple matching ts_id values for {station}/{spec.product_id}: {matches!r}"
        )
    return matches[0]


def _interpret_timeseries_list(
    payload: Payload,
    station: str,
    product: ProductId,
    spec: ProductSpec,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> TimeseriesListInterpretation:
    evidence = f"source-call:{payload.acquisition_id}"
    unrestricted_scope = SeriesScope(
        provider_ids=("be_wal",),
        station_ids=(station,),
        product_ids=(str(product),),
    )
    try:
        resolved = resolve_timeseries_list(payload.content, station, spec)
    except UnsupportedSourceStructureError as error:
        return TimeseriesListInterpretation(
            resolved_ts_id=None,
            scope_matched=False,
            parsed=_failed_parse_result(
                payload,
                None,
                station,
                product,
                window,
                retrieved,
                unrestricted_scope,
                access="KiWIS getTimeseriesList",
                reason=str(error),
            ),
        )

    if resolved is not None:
        definition = reused_series(
            source_series(station, str(product), ts_id=resolved, origin="response"),
            payload.known_series,
        )
        scope_matches = scope.matches(definition) and (
            scope.restriction is not RestrictionKind.EXPLICIT or not scope.variants or resolved in scope.variants
        )
        if scope_matches:
            # Child getTimeseriesValues payloads own observation outcomes and inventory coverage.
            return TimeseriesListInterpretation(
                resolved_ts_id=resolved,
                scope_matched=True,
                parsed=ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (definition,), (), (), ()),
            )

        inventory = InventorySnapshot(
            snapshot_id=stable_id(payload.acquisition_id, station, str(product), resolved, "lookup-scope-no-match"),
            scope=unrestricted_scope,
            members=(definition.series_id,),
            member_facts=((definition.series_id, tuple(fact.facts_id for fact in definition.facts)),),
            completeness=InventoryCompleteness.COMPLETE,
            access="KiWIS getTimeseriesList",
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(evidence,),
        )
        if scope.restriction is not RestrictionKind.ALL:
            return TimeseriesListInterpretation(
                resolved_ts_id=resolved,
                scope_matched=False,
                parsed=ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (definition,), (inventory,), (), ()),
            )
        reason = f"Resolved KiWIS ts_id {resolved!r} for {station}/{product} does not match requested scope"
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, station, str(product), "lookup-scope-no-match-outcome"),
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
        return TimeseriesListInterpretation(
            resolved_ts_id=resolved,
            scope_matched=False,
            parsed=ParsedSeries(
                pl.DataFrame(schema=RowsSchema.polars_schema),
                (definition,),
                (inventory,),
                (outcome,),
                (issue,),
            ),
        )

    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, station, str(product), "lookup-no-match"),
        scope=unrestricted_scope,
        members=(),
        completeness=InventoryCompleteness.COMPLETE,
        access="KiWIS getTimeseriesList",
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
    )
    if scope.restriction is not RestrictionKind.ALL:
        return TimeseriesListInterpretation(
            resolved_ts_id=None,
            scope_matched=False,
            parsed=ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (inventory,), (), ()),
        )
    reason = f"Station {station} has no KiWIS series for {spec.native_id!r} ({spec.stationparameter_names!r})"
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, station, str(product), "lookup-no-match-outcome"),
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
    return TimeseriesListInterpretation(
        resolved_ts_id=None,
        scope_matched=False,
        parsed=ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (inventory,), (outcome,), (issue,)),
    )


def _payload_context(
    payload: Payload,
    provider_config: ProviderConfig,
) -> tuple[
    str,
    ProductId,
    ProductSpec,
    BeWalTimeseriesListCoordinates | BeWalTimeseriesValuesCoordinates,
    SeriesWindow,
    datetime | None,
    SeriesScope,
]:
    if len(payload.station_products) != 1:
        raise FatalContractError("be_wal payload requires exactly one station-product pair")
    station, product = payload.station_products[0]
    spec = PRODUCT_BY_ID.get(str(product))
    if spec is None:
        raise FatalContractError(f"be_wal product lacks series specification: {product}")
    coords = _validated_coordinates(payload.source_coordinates.value, product, provider_config, spec)
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
        axis=payload.acquisition_axis,
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    scope = payload.scope or SeriesScope(
        provider_ids=("be_wal",),
        station_ids=(station,),
        product_ids=(str(product),),
    )
    return station, product, spec, coords, window, retrieved, scope


def interpret_timeseries_list_payload(
    payload: Payload,
    provider_config: ProviderConfig,
) -> TimeseriesListInterpretation:
    """Validate and interpret one KiWIS ``getTimeseriesList`` payload once for ``fetch`` and ``parse``."""
    station, product, spec, coords, window, retrieved, scope = _payload_context(payload, provider_config)
    if not isinstance(coords, BeWalTimeseriesListCoordinates):
        raise FatalContractError("be_wal getTimeseriesList interpretation requires lookup coordinates")
    return _interpret_timeseries_list(payload, station, product, spec, window, retrieved, scope)


def _parse_timeseries_values(
    payload: Payload,
    station: str,
    product: ProductId,
    coords: BeWalTimeseriesValuesCoordinates,
    spec: ProductSpec,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    evidence = f"source-call:{payload.acquisition_id}"
    try:
        resolved_ts_id, data = _validate_block(payload.content, station, spec, coords.ts_id)
        definition = reused_series(
            source_series(station, str(product), ts_id=resolved_ts_id, origin="response"),
            payload.known_series,
        )
        fact = definition.facts[0]

        times: list[datetime] = []
        values: list[float | None] = []
        quality_codes: list[int | None] = []
        quality_names: list[str | None] = []
        seen_times: set[datetime] = set()
        prev_dt: datetime | None = None
        monotonic = True

        for index, raw_row in enumerate(data):
            if not isinstance(raw_row, list) or len(raw_row) != 4:
                raise UnsupportedSourceStructureError(
                    f"KiWIS row {index} must be a 4-element [Timestamp, Value, Quality Code, Quality Code Name] array"
                )
            naive_time = _parse_utc_timestamp(raw_row[0], index=index)
            if naive_time in seen_times:
                raise UnsupportedSourceStructureError(
                    f"KiWIS ts_id {resolved_ts_id} duplicates timestamp {naive_time.isoformat()}"
                )
            if fact.label_time is not None and (
                naive_time.hour,
                naive_time.minute,
                naive_time.second,
                naive_time.microsecond,
            ) != (0, 0, 0, 0):
                raise UnsupportedSourceStructureError(
                    f"KiWIS {spec.product_id} ts_id {resolved_ts_id} row {index} timestamp {naive_time.isoformat()} violates expected 00:00+01:00 anchor"
                )
            if spec.frequency == "hourly" and (naive_time.minute, naive_time.second, naive_time.microsecond) != (
                0,
                0,
                0,
            ):
                raise UnsupportedSourceStructureError(
                    f"KiWIS {spec.product_id} ts_id {resolved_ts_id} row {index} hourly timestamp {naive_time.isoformat()} is not on the hour"
                )
            seen_times.add(naive_time)
            if prev_dt is not None and naive_time < prev_dt:
                monotonic = False
            prev_dt = naive_time

            times.append(naive_time)
            values.append(_finite_float_or_none(raw_row[1], index=index))
            quality_codes.append(_optional_int(raw_row[2], index=index))
            quality_names.append(_optional_str(raw_row[3], index=index))

        n = len(times)
        if not monotonic:
            order = sorted(range(n), key=lambda i: times[i])
            times = [times[i] for i in order]
            values = [values[i] for i in order]
            quality_codes = [quality_codes[i] for i in order]
            quality_names = [quality_names[i] for i in order]

        rows_df = (
            pl.DataFrame(
                {
                    "station_id": pl.repeat(station, n, dtype=pl.String, eager=True),
                    "product_id": pl.repeat(str(product), n, dtype=pl.String, eager=True),
                    "time": pl.Series("time", times, dtype=pl.Datetime("us")),
                    "value": pl.Series("value", values, dtype=pl.Float64),
                    "time_zone": pl.repeat(_SOURCE_ZONE, n, dtype=pl.String, eager=True),
                    "series_id": pl.repeat(definition.series_id, n, dtype=pl.String, eager=True),
                    "facts_id": pl.repeat(fact.facts_id, n, dtype=pl.String, eager=True),
                    "source_unit": pl.repeat(fact.source_unit.value, n, dtype=pl.String, eager=True),
                },
                schema=RowsSchema.polars_schema,
            )
            if n > 0
            else pl.DataFrame(schema=RowsSchema.polars_schema)
        )

        if n > 0:
            ann_frame = pl.DataFrame(
                {
                    "series_id": rows_df["series_id"],
                    "facts_id": rows_df["facts_id"],
                    "station_id": rows_df["station_id"],
                    "product_id": rows_df["product_id"],
                    "time": rows_df["time"],
                    "time_zone": rows_df["time_zone"],
                    "measured": pl.repeat(True, n, dtype=pl.Boolean, eager=True),
                    "quality_code": pl.Series("quality_code", quality_codes, dtype=pl.Int64),
                    "quality_code_name": pl.Series("quality_code_name", quality_names, dtype=pl.String),
                },
                schema={**OBSERVATION_STRUCTURAL_SCHEMA, **BE_WAL_QUALITY_SCHEMA.polars_schema()},
            )
            ann_table = ObservationAnnotationTable.from_rows(
                schema=BE_WAL_QUALITY_SCHEMA,
                rows=ann_frame,
                measurement_indices=list(range(n)),
            )
            annotations = AnnotationBundle(observation_tables={BE_WAL_QUALITY_SCHEMA.schema_id: ann_table})
        else:
            annotations = AnnotationBundle.empty()

        status = OutcomeStatus.EMPTY if n == 0 else OutcomeStatus.SUCCESS
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
        inventory = InventorySnapshot(
            snapshot_id=stable_id(
                payload.acquisition_id,
                definition.series_id,
                window.model_dump_json(),
                "kiwis-values-inventory",
            ),
            scope=scope,
            members=(definition.series_id,),
            member_facts=((definition.series_id, (fact.facts_id,)),),
            completeness=InventoryCompleteness.COMPLETE,
            access=f"KiWIS getTimeseriesValues ts_id={resolved_ts_id}",
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(evidence,),
        )
        return ParsedSeries(rows_df, (definition,), (inventory,), (outcome,), (), annotations)

    except UnsupportedSourceStructureError as error:
        fallback_ts_id = coords.ts_id
        fallback_definition: SourceSeries | None = None
        if fallback_ts_id is not None:
            fallback_definition = reused_series(
                source_series(station, str(product), ts_id=fallback_ts_id, origin="mapping"),
                payload.known_series,
            )
        return _failed_parse_result(
            payload,
            fallback_definition,
            station,
            product,
            window,
            retrieved,
            scope,
            access=f"KiWIS getTimeseriesValues ts_id={fallback_ts_id or 'unknown'}",
            reason=str(error),
        )


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Parse one SPW KiWIS lookup or observation payload into native ``+01:00`` rows and quality annotations."""
    station, product, spec, coords, window, retrieved, scope = _payload_context(payload, provider_config)
    if isinstance(coords, BeWalTimeseriesListCoordinates):
        return _interpret_timeseries_list(payload, station, product, spec, window, retrieved, scope).parsed
    return _parse_timeseries_values(payload, station, product, coords, spec, window, retrieved, scope)


__all__ = [
    "TimeseriesListInterpretation",
    "interpret_timeseries_list_payload",
    "parse",
    "resolve_timeseries_list",
]

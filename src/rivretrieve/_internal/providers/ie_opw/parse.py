"""Parse OPW Hydro-Data ``year.json`` and ``*_complete.zip`` payloads into native series and annotations."""

from __future__ import annotations

import io
import json
import re
import zipfile
import zlib
from collections.abc import Mapping
from datetime import datetime, time, timedelta
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import (
    Payload,
    ProviderConfig,
    RowsSchema,
    narrow_payload_for_pair,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.ie_opw.annotations import (
    IE_OPW_DAILY_STAGE_SCHEMA,
    IE_OPW_SERIES_SCHEMA,
)
from rivretrieve._internal.providers.ie_opw.config import (
    OpwCompleteZipCoordinates,
    OpwDailyYearJsonCoordinates,
    OpwDailyYearJsonEndpointCoordinates,
    validate_station_id,
)
from rivretrieve._internal.providers.ie_opw.series import PRODUCT_BY_ID, reused_series, source_series
from rivretrieve._internal.source_annotations import (
    OBSERVATION_STRUCTURAL_SCHEMA,
    AnnotationBundle,
    AnnotationSchema,
    ObservationAnnotationTable,
)
from rivretrieve._internal.source_series import (
    ClippingAxis,
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    stable_id,
)

_PROVIDER_ID = ProviderId("ie_opw")
_UTC_DAILY_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00:00\.000Z$")
_UTC_ZIP_TS_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.000Z$"
_FLOAT_TOKEN_RE = r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
_INT64_TOKEN_RE = r"^-?\d+$"
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_ZIP_CSV_HEADER = "#Timestamp;Value;Quality Code"
_YEAR_COLUMNS_DEFAULT = "Timestamp,Value,Quality Code"
_YEAR_COLUMNS_DAILY_STAGE = "Timestamp,Value,Quality Code,Aggregation Accuracy %"


def _validated_product_coordinates(
    payload_coords: object,
    product: ProductId,
    provider_config: ProviderConfig,
) -> OpwDailyYearJsonCoordinates | OpwCompleteZipCoordinates:
    try:
        configured = provider_config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"ie_opw product is absent from provider config: {product}") from error

    if isinstance(payload_coords, OpwDailyYearJsonCoordinates):
        if not isinstance(configured, OpwDailyYearJsonCoordinates) or payload_coords != configured:
            raise FatalContractError("ie_opw year.json payload coordinates contradict configured product")
        return configured
    if isinstance(payload_coords, OpwDailyYearJsonEndpointCoordinates):
        if not isinstance(configured, OpwDailyYearJsonCoordinates) or configured.parameter != payload_coords.parameter:
            raise FatalContractError("ie_opw shared year.json endpoint coordinates contradict configured product")
        return configured
    if isinstance(payload_coords, OpwCompleteZipCoordinates):
        if not isinstance(configured, OpwCompleteZipCoordinates) or payload_coords != configured:
            raise FatalContractError("ie_opw complete.zip payload coordinates contradict configured product")
        return configured
    raise FatalContractError(f"ie_opw payload has unsupported coordinate type: {type(payload_coords)!r}")


def _finite_float_or_none(raw: object, *, context: str, field_name: str) -> float | None:
    if raw is None:
        return None
    if type(raw) not in (int, float):
        raise UnsupportedSourceStructureError(f"{context} field {field_name} must be numeric or null, got {raw!r}")
    try:
        value = float(cast("int | float", raw))
    except OverflowError as error:
        raise UnsupportedSourceStructureError(f"{context} field {field_name} overflows float64") from error
    if not isfinite(value):
        raise UnsupportedSourceStructureError(f"{context} field {field_name} must be finite, got {raw!r}")
    return value


def _strict_int64(raw: object, *, context: str, field_name: str) -> int:
    if type(raw) is not int or not (_INT64_MIN <= raw <= _INT64_MAX):
        raise UnsupportedSourceStructureError(f"{context} field {field_name} must be a 64-bit integer, got {raw!r}")
    return raw


def _verify_origin_url(
    origin_url: object,
    *,
    station: str,
    parameter: str,
    route: str,
) -> None:
    if not isinstance(origin_url, str) or "/hydro-data/data/internet/stations/" not in origin_url:
        return
    clean_path = origin_url.split("?", 1)[0].split("#", 1)[0]
    expected_suffix = f"/stations/0/{station}/{parameter}/{route}"
    if not clean_path.endswith(expected_suffix):
        raise UnsupportedSourceStructureError(
            f"OPW origin URL {clean_path!r} contradicts requested ({station!r}, {parameter!r}, {route!r})"
        )


def _append_disjoint_unresolved_bounds(
    outcomes: list[RetrievalOutcome],
    *,
    acquisition_id: str,
    series_id: str,
    station: str,
    product: str,
    facts_id: str,
    window: SeriesWindow,
    active_start: datetime,
    active_end: datetime,
    retrieved_at: datetime | None,
    pre_reason: str,
    post_reason: str,
) -> None:
    if window.start < active_start:
        pre_end = min(window.end, active_start - timedelta(microseconds=1))
        if window.start <= pre_end:
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(acquisition_id, series_id, facts_id, "pre"),
                    series_id=series_id,
                    station_id=station,
                    product_id=product,
                    window=SeriesWindow(start=window.start, end=pre_end, axis=window.axis),
                    status=OutcomeStatus.UNRESOLVED,
                    facts_ids=(facts_id,),
                    reason=pre_reason,
                    retrieved_at=retrieved_at,
                )
            )
    if window.end > active_end:
        post_start = max(window.start, active_end + timedelta(microseconds=1))
        if post_start <= window.end:
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(acquisition_id, series_id, facts_id, "post"),
                    series_id=series_id,
                    station_id=station,
                    product_id=product,
                    window=SeriesWindow(start=post_start, end=window.end, axis=window.axis),
                    status=OutcomeStatus.UNRESOLVED,
                    facts_ids=(facts_id,),
                    reason=post_reason,
                    retrieved_at=retrieved_at,
                )
            )


def _failed_result(
    payload: Payload,
    station: str,
    product: ProductId,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
    *,
    access: str,
    reason: str,
) -> ParsedSeries:
    definition = reused_series(source_series(station, str(product), origin="response"), payload.known_series)
    fact = definition.facts[0]
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, station, str(product), "failed"),
        series_id=definition.series_id,
        station_id=station,
        product_id=str(product),
        window=window,
        status=OutcomeStatus.FAILED,
        facts_ids=(fact.facts_id,),
        reason=reason,
        retrieved_at=retrieved,
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, station, str(product), "failed-inventory"),
        scope=scope,
        members=(definition.series_id,),
        member_facts=((definition.series_id, (fact.facts_id,)),),
        completeness=InventoryCompleteness.INCOMPLETE,
        access=access,
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(f"source-call:{payload.acquisition_id}",),
        reason=reason,
    )
    issue = Issue(
        severity="error",
        code="source.unsupported_structure",
        message=reason,
        details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
        provider_id=_PROVIDER_ID,
    )
    return ParsedSeries(
        pl.DataFrame(schema=RowsSchema.polars_schema),
        (definition,),
        (inventory,),
        (outcome,),
        (issue,),
    )


def _no_match_result(
    payload: Payload,
    station: str,
    product: ProductId,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
    *,
    access: str,
    reason: str,
) -> ParsedSeries:
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, station, str(product), "no-match"),
        series_id=None,
        station_id=station,
        product_id=str(product),
        window=window,
        status=OutcomeStatus.NO_MATCH,
        reason=reason,
        retrieved_at=retrieved,
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, station, str(product), "no-match-inventory"),
        scope=scope,
        members=(),
        completeness=InventoryCompleteness.COMPLETE,
        access=access,
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(f"source-call:{payload.acquisition_id}",),
    )
    issue = Issue(
        severity="warning",
        code="source.no_match",
        message=reason,
        details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
        provider_id=_PROVIDER_ID,
    )
    return ParsedSeries(
        pl.DataFrame(schema=RowsSchema.polars_schema),
        (),
        (inventory,),
        (outcome,),
        (issue,),
    )


def _unresolved_empty_result(
    payload: Payload,
    definition: SourceSeries,
    station: str,
    product: ProductId,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
    *,
    access: str,
    reason: str,
) -> ParsedSeries:
    fact = definition.facts[0]
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id, "empty-unresolved"),
        series_id=definition.series_id,
        station_id=station,
        product_id=str(product),
        window=window,
        status=OutcomeStatus.UNRESOLVED,
        facts_ids=(fact.facts_id,),
        reason=reason,
        retrieved_at=retrieved,
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, definition.series_id, "empty-inventory"),
        scope=scope,
        members=(definition.series_id,),
        member_facts=((definition.series_id, (fact.facts_id,)),),
        completeness=InventoryCompleteness.INCOMPLETE,
        access=access,
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(f"source-call:{payload.acquisition_id}",),
        reason=reason,
    )
    return ParsedSeries(
        pl.DataFrame(schema=RowsSchema.polars_schema),
        (definition,),
        (inventory,),
        (outcome,),
    )


def _build_rows_frame(
    *,
    station: str,
    product: ProductId,
    definition: SourceSeries,
    times: pl.Series,
    values: pl.Series,
) -> pl.DataFrame:
    n = times.len()
    if n == 0:
        return pl.DataFrame(schema=RowsSchema.polars_schema)
    fact = definition.facts[0]
    source_unit = fact.source_unit.value
    assert source_unit is not None
    return pl.DataFrame(
        {
            "station_id": pl.repeat(station, n, dtype=pl.String, eager=True),
            "product_id": pl.repeat(str(product), n, dtype=pl.String, eager=True),
            "time": times,
            "value": values,
            "time_zone": pl.repeat("+00:00", n, dtype=pl.String, eager=True),
            "series_id": pl.repeat(definition.series_id, n, dtype=pl.String, eager=True),
            "facts_id": pl.repeat(fact.facts_id, n, dtype=pl.String, eager=True),
            "source_unit": pl.repeat(source_unit, n, dtype=pl.String, eager=True),
        },
        schema=RowsSchema.polars_schema,
    )


def _build_interval_result(
    *,
    payload: Payload,
    definition: SourceSeries,
    station: str,
    product: ProductId,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
    access: str,
    rows_df: pl.DataFrame,
    ann_table: ObservationAnnotationTable | None,
    schema: AnnotationSchema,
    first_slot: datetime,
    last_slot: datetime,
) -> ParsedSeries:
    fact = definition.facts[0]
    if fact.clipping_axis is ClippingAxis.CALENDAR_DATE:
        covered_start = datetime.combine(first_slot.date(), time.min)
        covered_end = datetime.combine(last_slot.date(), time.max)
    else:
        covered_start = first_slot
        covered_end = last_slot
    covered_window = SeriesWindow(start=covered_start, end=covered_end, axis=window.axis)
    status = OutcomeStatus.EMPTY if rows_df.is_empty() else OutcomeStatus.SUCCESS
    outcomes: list[RetrievalOutcome] = [
        RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id, "interval", status),
            series_id=definition.series_id,
            station_id=station,
            product_id=str(product),
            window=covered_window,
            status=status,
            facts_ids=(fact.facts_id,),
            retrieved_at=retrieved,
            coverage="interval",
        )
    ]
    _append_disjoint_unresolved_bounds(
        outcomes,
        acquisition_id=payload.acquisition_id,
        series_id=definition.series_id,
        station=station,
        product=str(product),
        facts_id=fact.facts_id,
        window=window,
        active_start=covered_start,
        active_end=covered_end,
        retrieved_at=retrieved,
        pre_reason="Requested interval precedes first published OPW Hydro-Data slot",
        post_reason="Requested interval extends beyond latest published OPW Hydro-Data slot",
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, definition.series_id, "interval-inventory"),
        scope=scope,
        members=(definition.series_id,),
        member_facts=((definition.series_id, (fact.facts_id,)),),
        completeness=InventoryCompleteness.COMPLETE,
        access=access,
        origin="response",
        acquired_at=retrieved,
        window=covered_window,
        evidence=(f"source-call:{payload.acquisition_id}",),
    )
    annotations = (
        AnnotationBundle(observation_tables={schema.schema_id: ann_table})
        if ann_table is not None and ann_table.row_count > 0
        else AnnotationBundle.empty()
    )
    return ParsedSeries(
        rows_df,
        (definition,),
        (inventory,),
        tuple(outcomes),
        (),
        annotations=annotations,
    )


def _decode_year_json_blocks(
    content: bytes,
    *,
    allowed_shortnames: frozenset[str] | set[str] | None = None,
) -> tuple[dict[str, dict[str, object]], set[str]]:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise UnsupportedSourceStructureError("OPW Hydro-Data year.json response is not valid JSON") from error
    if not isinstance(document, list):
        raise UnsupportedSourceStructureError("OPW Hydro-Data year.json response must be a JSON array")

    blocks: dict[str, dict[str, object]] = {}
    seen_shortnames: set[str] = set()
    duplicates: set[str] = set()
    for index, raw_entry in enumerate(document):
        if not isinstance(raw_entry, dict):
            raise UnsupportedSourceStructureError(f"OPW year.json entry {index} must be a JSON object")
        entry = cast("dict[str, object]", raw_entry)
        shortname = entry.get("ts_shortname")
        if not isinstance(shortname, str) or not shortname:
            raise UnsupportedSourceStructureError(f"OPW year.json entry {index} lacks non-empty string ts_shortname")
        if shortname in seen_shortnames:
            duplicates.add(shortname)
            blocks.pop(shortname, None)
        else:
            seen_shortnames.add(shortname)
            if allowed_shortnames is None or shortname in allowed_shortnames:
                blocks[shortname] = entry
    return blocks, duplicates


def _interpret_year_block(
    payload: Payload,
    blocks: dict[str, dict[str, object]],
    duplicates: set[str],
    station: str,
    product: ProductId,
    coords: OpwDailyYearJsonCoordinates,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    access = f"Hydro-Data {coords.parameter}/year.json {coords.ts_shortname}"
    _verify_origin_url(payload.origin.url, station=station, parameter=coords.parameter, route="year.json")
    if coords.ts_shortname in duplicates:
        raise UnsupportedSourceStructureError(f"OPW year.json duplicates ts_shortname block {coords.ts_shortname!r}")
    block = blocks.get(coords.ts_shortname)
    if block is None:
        return _no_match_result(
            payload,
            station,
            product,
            window,
            retrieved,
            scope,
            access=access,
            reason=f"OPW {coords.parameter}/year.json omits series {coords.ts_shortname!r}",
        )

    spec = PRODUCT_BY_ID[coords.product_id]
    if block.get("stationparameter_name") != coords.parameter:
        raise UnsupportedSourceStructureError(
            f"OPW year.json block {coords.ts_shortname!r} parameter {block.get('stationparameter_name')!r} "
            f"contradicts {coords.parameter!r}"
        )
    if block.get("ts_unitsymbol") != spec.source_unit:
        raise UnsupportedSourceStructureError(
            f"OPW year.json block {coords.ts_shortname!r} unit {block.get('ts_unitsymbol')!r} "
            f"contradicts {spec.source_unit!r}"
        )
    expected_columns = _YEAR_COLUMNS_DAILY_STAGE if coords.parameter == "S" else _YEAR_COLUMNS_DEFAULT
    if block.get("columns") != expected_columns:
        raise UnsupportedSourceStructureError(
            f"OPW year.json block {coords.ts_shortname!r} columns {block.get('columns')!r} "
            f"contradicts expected {expected_columns!r}"
        )

    raw_data = block.get("data")
    if not isinstance(raw_data, list):
        raise UnsupportedSourceStructureError(f"OPW year.json block {coords.ts_shortname!r} data must be a JSON array")
    if "rows" in block:
        raw_rows_count = block["rows"]
        if str(raw_rows_count) != str(len(raw_data)):
            raise UnsupportedSourceStructureError(
                f"OPW year.json block {coords.ts_shortname!r} row metadata {raw_rows_count!r} "
                f"contradicts data length {len(raw_data)}"
            )

    definition = reused_series(source_series(station, str(product), origin="response"), payload.known_series)
    fact = definition.facts[0]
    if not raw_data:
        return _unresolved_empty_result(
            payload,
            definition,
            station,
            product,
            window,
            retrieved,
            scope,
            access=access,
            reason=f"OPW {coords.parameter}/year.json block {coords.ts_shortname!r} contains zero rows",
        )

    is_stage = coords.parameter == "S"
    expected_width = 4 if is_stage else 3
    all_times: list[datetime] = []
    values: list[float | None] = []
    qcodes: list[int] = []
    accs: list[float | None] = []
    seen_times: set[datetime] = set()
    prev_dt: datetime | None = None
    monotonic = True

    for index, raw_row in enumerate(raw_data):
        if not isinstance(raw_row, list) or len(raw_row) != expected_width:
            raise UnsupportedSourceStructureError(
                f"OPW year.json {coords.ts_shortname!r} row {index} must be a {expected_width}-element array"
            )
        ts_raw = raw_row[0]
        if not isinstance(ts_raw, str) or _UTC_DAILY_TS_RE.fullmatch(ts_raw) is None:
            raise UnsupportedSourceStructureError(
                f"OPW year.json {coords.ts_shortname!r} row {index} lacks valid YYYY-MM-DDT00:00:00.000Z timestamp: {ts_raw!r}"
            )
        try:
            obs_dt = datetime.fromisoformat(ts_raw[:-1])
        except ValueError as error:
            raise UnsupportedSourceStructureError(
                f"OPW year.json {coords.ts_shortname!r} row {index} invalid date {ts_raw!r}"
            ) from error
        if obs_dt in seen_times:
            raise UnsupportedSourceStructureError(
                f"OPW year.json {station}/{coords.ts_shortname} duplicates UTC timestamp {ts_raw}"
            )
        seen_times.add(obs_dt)
        val = _finite_float_or_none(
            raw_row[1], context=f"OPW year.json {coords.ts_shortname!r} row {index}", field_name="Value"
        )
        qc = _strict_int64(
            raw_row[2], context=f"OPW year.json {coords.ts_shortname!r} row {index}", field_name="Quality Code"
        )
        if is_stage:
            acc = _finite_float_or_none(
                raw_row[3],
                context=f"OPW year.json {coords.ts_shortname!r} row {index}",
                field_name="Aggregation Accuracy %",
            )
            accs.append(acc)
        if prev_dt is not None and obs_dt < prev_dt:
            monotonic = False
        prev_dt = obs_dt
        all_times.append(obs_dt)
        values.append(val)
        qcodes.append(qc)

    total_slots = len(all_times)
    del raw_data, seen_times
    if not monotonic:
        order = [idx for _, idx in sorted((dt, idx) for idx, dt in enumerate(all_times))]
        all_times = [all_times[i] for i in order]
        values = [values[i] for i in order]
        qcodes = [qcodes[i] for i in order]
        if is_stage:
            accs = [accs[i] for i in order]

    meas_times: list[datetime] = []
    meas_values: list[float] = []
    measured_flags: list[bool] = []
    measurement_indices: list[int | None] = []
    for dt, val in zip(all_times, values, strict=True):
        if val is None:
            measured_flags.append(False)
            measurement_indices.append(None)
        else:
            measurement_indices.append(len(meas_times))
            meas_times.append(dt)
            meas_values.append(val)
            measured_flags.append(True)

    rows_df = _build_rows_frame(
        station=station,
        product=product,
        definition=definition,
        times=pl.Series("time", meas_times, dtype=pl.Datetime("us")),
        values=pl.Series("value", meas_values, dtype=pl.Float64),
    )
    schema = IE_OPW_DAILY_STAGE_SCHEMA if is_stage else IE_OPW_SERIES_SCHEMA
    ann_columns: dict[str, pl.Series] = {
        "series_id": pl.repeat(definition.series_id, total_slots, dtype=pl.String, eager=True),
        "facts_id": pl.repeat(fact.facts_id, total_slots, dtype=pl.String, eager=True),
        "station_id": pl.repeat(station, total_slots, dtype=pl.String, eager=True),
        "product_id": pl.repeat(str(product), total_slots, dtype=pl.String, eager=True),
        "time": pl.Series("time", all_times, dtype=pl.Datetime("us")),
        "time_zone": pl.repeat("+00:00", total_slots, dtype=pl.String, eager=True),
        "measured": pl.Series("measured", measured_flags, dtype=pl.Boolean),
        "quality_code": pl.Series("quality_code", qcodes, dtype=pl.Int64),
    }
    if is_stage:
        ann_columns["aggregation_accuracy_pct"] = pl.Series("aggregation_accuracy_pct", accs, dtype=pl.Float64)
    ann_frame = pl.DataFrame(
        ann_columns,
        schema={**OBSERVATION_STRUCTURAL_SCHEMA, **schema.polars_schema()},
    )
    ann_table = ObservationAnnotationTable.from_rows(
        schema=schema,
        rows=ann_frame,
        measurement_indices=measurement_indices,
    )
    first_slot = all_times[0]
    last_slot = all_times[-1]
    del (
        all_times,
        values,
        qcodes,
        accs,
        meas_times,
        meas_values,
        measured_flags,
        measurement_indices,
        ann_columns,
        ann_frame,
    )
    return _build_interval_result(
        payload=payload,
        definition=definition,
        station=station,
        product=product,
        window=window,
        retrieved=retrieved,
        scope=scope,
        access=access,
        rows_df=rows_df,
        ann_table=ann_table,
        schema=schema,
        first_slot=first_slot,
        last_slot=last_slot,
    )


def _extract_zip_csv_header(raw_csv: bytes) -> tuple[dict[str, str], int, bytes]:
    pos = 0
    headers: dict[str, str] = {}
    seen_col_header = False
    while pos < len(raw_csv):
        nl = raw_csv.find(b"\n", pos)
        line_bytes = raw_csv[pos:] if nl == -1 else raw_csv[pos:nl]
        pos = len(raw_csv) if nl == -1 else nl + 1
        try:
            line = line_bytes.rstrip(b"\r").decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise UnsupportedSourceStructureError("OPW ZIP tsvalues.csv header is not valid UTF-8") from error
        if not line.startswith("#"):
            raise UnsupportedSourceStructureError("OPW ZIP tsvalues.csv lacks #Timestamp;Value;Quality Code header")
        if line == _ZIP_CSV_HEADER:
            seen_col_header = True
            break
        key_raw, sep, val_raw = line[1:].partition(";")
        if not sep or not key_raw:
            raise UnsupportedSourceStructureError(f"OPW ZIP tsvalues.csv malformed metadata header line: {line!r}")
        headers[key_raw] = val_raw

    if not seen_col_header:
        raise UnsupportedSourceStructureError("OPW ZIP tsvalues.csv lacks expected #Timestamp;Value;Quality Code line")
    return headers, pos, raw_csv[pos:]


def _parse_complete_zip(
    payload: Payload,
    station: str,
    product: ProductId,
    coords: OpwCompleteZipCoordinates,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    access = f"Hydro-Data {coords.parameter}/{coords.route}"
    _verify_origin_url(payload.origin.url, station=station, parameter=coords.parameter, route=coords.route)
    try:
        with zipfile.ZipFile(io.BytesIO(payload.content)) as archive:
            names = archive.namelist()
            if names != ["tsvalues.csv"]:
                raise UnsupportedSourceStructureError(
                    f"OPW ZIP {coords.route} must contain only tsvalues.csv, got {names!r}"
                )
            raw_csv = archive.read("tsvalues.csv")
    except (zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error, EOFError, KeyError, RuntimeError) as error:
        raise UnsupportedSourceStructureError(f"OPW ZIP {coords.route} archive is unreadable or corrupt") from error

    headers, _, body_bytes = _extract_zip_csv_header(raw_csv)
    del raw_csv

    if headers.get("station_no") != station:
        raise UnsupportedSourceStructureError(
            f"OPW ZIP header station_no {headers.get('station_no')!r} contradicts requested {station!r}"
        )
    if headers.get("stationparameter_name") != coords.parameter:
        raise UnsupportedSourceStructureError(
            f"OPW ZIP header stationparameter_name {headers.get('stationparameter_name')!r} "
            f"contradicts {coords.parameter!r}"
        )
    if headers.get("ts_shortname") != coords.ts_shortname:
        raise UnsupportedSourceStructureError(
            f"OPW ZIP header ts_shortname {headers.get('ts_shortname')!r} contradicts {coords.ts_shortname!r}"
        )
    spec = PRODUCT_BY_ID[coords.product_id]
    if headers.get("ts_unitsymbol") != spec.source_unit:
        raise UnsupportedSourceStructureError(
            f"OPW ZIP header ts_unitsymbol {headers.get('ts_unitsymbol')!r} contradicts {spec.source_unit!r}"
        )
    if headers.get("tz", "UTC0") != "UTC0":
        raise UnsupportedSourceStructureError(f"OPW ZIP header tz {headers.get('tz')!r} contradicts UTC0")

    rows_decl = headers.get("rows")
    if rows_decl is None or not rows_decl.isascii() or not rows_decl.isdigit():
        raise UnsupportedSourceStructureError(f"OPW ZIP header rows {rows_decl!r} must be a non-negative integer")
    declared_rows = int(rows_decl)

    definition = reused_series(source_series(station, str(product), origin="response"), payload.known_series)
    if body_bytes.strip() == b"":
        if declared_rows != 0:
            raise UnsupportedSourceStructureError(
                f"OPW ZIP {coords.route} declares #rows;{declared_rows} but body is empty"
            )
        return _unresolved_empty_result(
            payload,
            definition,
            station,
            product,
            window,
            retrieved,
            scope,
            access=access,
            reason=f"OPW {coords.parameter}/{coords.route} declares #rows;0 with zero observations",
        )

    try:
        raw_df = pl.read_csv(
            io.BytesIO(body_bytes),
            has_header=False,
            separator=";",
            new_columns=["ts", "val", "qc"],
            schema_overrides={"ts": pl.String, "val": pl.String, "qc": pl.String},
            null_values=[],
            truncate_ragged_lines=False,
            quote_char=None,
        )
    except pl.exceptions.PolarsError as error:
        raise UnsupportedSourceStructureError(f"OPW ZIP {coords.route} CSV body is malformed: {error}") from error
    del body_bytes

    if raw_df.height != declared_rows:
        raise UnsupportedSourceStructureError(
            f"OPW ZIP {coords.route} row count {raw_df.height} contradicts #rows;{declared_rows}"
        )

    ts_col = raw_df["ts"]
    if ts_col.null_count() > 0 or bool((~ts_col.str.contains(_UTC_ZIP_TS_RE)).any()):
        raise UnsupportedSourceStructureError(
            f"OPW ZIP {coords.route} contains timestamp outside YYYY-MM-DDTHH:MM:SS.000Z"
        )
    dt = ts_col.str.strptime(pl.Datetime("us"), "%Y-%m-%dT%H:%M:%S%.3fZ", strict=False)
    if dt.null_count() > 0:
        raise UnsupportedSourceStructureError(f"OPW ZIP {coords.route} contains invalid calendar UTC timestamp")

    val_str = raw_df["val"]
    non_null_vals = val_str.filter(val_str.is_not_null())
    if non_null_vals.len() > 0 and bool((~non_null_vals.str.contains(_FLOAT_TOKEN_RE)).any()):
        raise UnsupportedSourceStructureError(f"OPW ZIP {coords.route} contains invalid numeric Value token")
    vals = val_str.cast(pl.Float64, strict=False)
    if vals.null_count() != val_str.null_count() or bool((~vals.drop_nulls().is_finite()).any()):
        raise UnsupportedSourceStructureError(f"OPW ZIP {coords.route} contains non-finite or overflow Value")

    qc_str = raw_df["qc"]
    if qc_str.null_count() > 0 or bool((~qc_str.str.contains(_INT64_TOKEN_RE)).any()):
        raise UnsupportedSourceStructureError(f"OPW ZIP {coords.route} contains invalid integer Quality Code")
    qcodes = qc_str.cast(pl.Int64, strict=False)
    if qcodes.null_count() > 0:
        raise UnsupportedSourceStructureError(f"OPW ZIP {coords.route} Quality Code overflows Int64")

    df = pl.DataFrame({"time": dt, "value": vals, "quality_code": qcodes})
    del raw_df

    if df.height > 1:
        diffs = df["time"].diff().drop_nulls()
        if bool((diffs == timedelta(0)).any()):
            raise UnsupportedSourceStructureError(f"OPW ZIP {coords.route} contains duplicate timestamps")
        if bool((diffs < timedelta(0)).any()):
            df = df.sort("time")
            if df["time"].n_unique() != df.height:
                raise UnsupportedSourceStructureError(f"OPW ZIP {coords.route} contains duplicate timestamps")

    fact = definition.facts[0]
    n_total = df.height
    meas_mask = df["value"].is_not_null()
    measured_df = df.filter(meas_mask)
    rows_df = _build_rows_frame(
        station=station,
        product=product,
        definition=definition,
        times=measured_df["time"],
        values=measured_df["value"],
    )
    measurement_indices = df.select(
        pl.when(meas_mask).then(meas_mask.cast(pl.Int64).cum_sum() - 1).otherwise(None).alias("_mi")
    )["_mi"].to_list()
    ann_frame = pl.DataFrame(
        {
            "series_id": pl.repeat(definition.series_id, n_total, dtype=pl.String, eager=True),
            "facts_id": pl.repeat(fact.facts_id, n_total, dtype=pl.String, eager=True),
            "station_id": pl.repeat(station, n_total, dtype=pl.String, eager=True),
            "product_id": pl.repeat(str(product), n_total, dtype=pl.String, eager=True),
            "time": df["time"],
            "time_zone": pl.repeat("+00:00", n_total, dtype=pl.String, eager=True),
            "measured": meas_mask,
            "quality_code": df["quality_code"],
        },
        schema={**OBSERVATION_STRUCTURAL_SCHEMA, **IE_OPW_SERIES_SCHEMA.polars_schema()},
    )
    ann_table = ObservationAnnotationTable.from_rows(
        schema=IE_OPW_SERIES_SCHEMA,
        rows=ann_frame,
        measurement_indices=measurement_indices,
    )
    first_slot = cast("datetime", df["time"][0])
    last_slot = cast("datetime", df["time"][-1])
    del df, measured_df
    return _build_interval_result(
        payload=payload,
        definition=definition,
        station=station,
        product=product,
        window=window,
        retrieved=retrieved,
        scope=scope,
        access=access,
        rows_df=rows_df,
        ann_table=ann_table,
        schema=IE_OPW_SERIES_SCHEMA,
        first_slot=first_slot,
        last_slot=last_slot,
    )


def parse_group(
    payload: Payload,
    pair_payloads: Mapping[tuple[str, ProductId], Payload],
    provider_config: ProviderConfig,
) -> dict[tuple[str, ProductId], ParsedSeries]:
    """Decode one shared OPW payload once and project independent per-pair ``ParsedSeries`` results."""
    if not pair_payloads:
        raise FatalContractError("ie_opw group parse requires at least one pair payload")
    stations = {station for station, _ in pair_payloads}
    if len(stations) != 1:
        raise FatalContractError("ie_opw payload must identify a single station")
    validate_station_id(next(iter(stations)))

    coords_by_pair: dict[tuple[str, ProductId], OpwDailyYearJsonCoordinates | OpwCompleteZipCoordinates] = {}
    meta_by_pair: dict[tuple[str, ProductId], tuple[Payload, SeriesWindow, datetime | None, SeriesScope]] = {}
    for key, pair_payload in pair_payloads.items():
        station, product = key
        if pair_payload.station_products != ((station, product),):
            raise FatalContractError("ie_opw pair payload station_products does not match its group key")
        _validated_product_coordinates(payload.source_coordinates.value, product, provider_config)
        coords_by_pair[key] = _validated_product_coordinates(
            pair_payload.source_coordinates.value, product, provider_config
        )
        window = SeriesWindow(
            start=datetime.fromisoformat(pair_payload.fetch_window.start.isoformat()),
            end=datetime.fromisoformat(pair_payload.fetch_window.end.isoformat()),
            axis=pair_payload.acquisition_axis,
        )
        retrieved = pair_payload.origin.retrieved_at if isinstance(pair_payload.origin.retrieved_at, datetime) else None
        scope = pair_payload.scope or SeriesScope(
            provider_ids=("ie_opw",),
            station_ids=(station,),
            product_ids=(str(product),),
        )
        meta_by_pair[key] = (pair_payload, window, retrieved, scope)

    first_coords = next(iter(coords_by_pair.values()))
    if isinstance(first_coords, OpwCompleteZipCoordinates):
        if len(pair_payloads) != 1:
            raise FatalContractError("ie_opw complete.zip payload requires exactly one station-product pair")
        key = next(iter(pair_payloads))
        pair_payload, window, retrieved, scope = meta_by_pair[key]
        try:
            return {key: _parse_complete_zip(pair_payload, key[0], key[1], first_coords, window, retrieved, scope)}
        except UnsupportedSourceStructureError as error:
            return {
                key: _failed_result(
                    pair_payload,
                    key[0],
                    key[1],
                    window,
                    retrieved,
                    scope,
                    access=f"Hydro-Data {first_coords.parameter}/{first_coords.route}",
                    reason=str(error),
                )
            }

    daily_coords_by_pair = {key: cast("OpwDailyYearJsonCoordinates", coords) for key, coords in coords_by_pair.items()}
    allowed_shortnames = {coords.ts_shortname for coords in daily_coords_by_pair.values()}
    try:
        blocks, duplicates = _decode_year_json_blocks(payload.content, allowed_shortnames=allowed_shortnames)
    except UnsupportedSourceStructureError as error:
        reason = str(error)
        return {
            key: _failed_result(
                pair_payload,
                key[0],
                key[1],
                window,
                retrieved,
                scope,
                access=f"Hydro-Data {daily_coords_by_pair[key].parameter}/year.json",
                reason=reason,
            )
            for key, (pair_payload, window, retrieved, scope) in meta_by_pair.items()
        }

    remaining_uses: dict[str, int] = {}
    for pair_coords in daily_coords_by_pair.values():
        remaining_uses[pair_coords.ts_shortname] = remaining_uses.get(pair_coords.ts_shortname, 0) + 1

    results: dict[tuple[str, ProductId], ParsedSeries] = {}
    for key, (pair_payload, window, retrieved, scope) in meta_by_pair.items():
        pair_coords = daily_coords_by_pair[key]
        try:
            results[key] = _interpret_year_block(
                pair_payload,
                blocks,
                duplicates,
                key[0],
                key[1],
                pair_coords,
                window,
                retrieved,
                scope,
            )
        except UnsupportedSourceStructureError as error:
            results[key] = _failed_result(
                pair_payload,
                key[0],
                key[1],
                window,
                retrieved,
                scope,
                access=f"Hydro-Data {pair_coords.parameter}/year.json {pair_coords.ts_shortname}",
                reason=str(error),
            )
        remaining_uses[pair_coords.ts_shortname] -= 1
        if remaining_uses[pair_coords.ts_shortname] == 0:
            blocks.pop(pair_coords.ts_shortname, None)
    del blocks, duplicates
    return results


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Parse one Ireland OPW Hydro-Data ``year.json`` or ``*_complete.zip`` payload."""
    if not payload.station_products:
        raise FatalContractError("ie_opw payload requires at least one station-product pair")
    stations = {station for station, _ in payload.station_products}
    if len(stations) != 1:
        raise FatalContractError("ie_opw payload must identify a single station")
    validate_station_id(next(iter(stations)))

    for _, product in payload.station_products:
        _validated_product_coordinates(payload.source_coordinates.value, product, provider_config)

    if len(payload.station_products) == 1:
        pair = payload.station_products[0]
        return parse_group(payload, {pair: payload}, provider_config)[pair]

    if not isinstance(
        payload.source_coordinates.value,
        (OpwDailyYearJsonCoordinates, OpwDailyYearJsonEndpointCoordinates),
    ):
        raise FatalContractError("ie_opw multi-product payload must target a shared year.json endpoint")

    pair_payloads = {
        (station, product): narrow_payload_for_pair(payload, station, product)
        for station, product in payload.station_products
    }
    grouped = parse_group(payload, pair_payloads, provider_config)

    frames: list[pl.DataFrame] = []
    definitions: dict[str, SourceSeries] = {}
    inventories: list[InventorySnapshot] = []
    outcomes: list[RetrievalOutcome] = []
    issues: list[Issue] = []
    annotation_bundles: list[AnnotationBundle] = []
    annotation_offsets: list[int] = []
    offset = 0
    for pair in payload.station_products:
        part = grouped[pair]
        if not part.annotations.is_empty:
            annotation_bundles.append(part.annotations)
            annotation_offsets.append(offset)
        if not part.rows.is_empty():
            frames.append(part.rows)
            offset += part.rows.height
        for item in part.series:
            definitions[item.series_id] = item
        inventories.extend(part.inventories)
        outcomes.extend(part.outcomes)
        issues.extend(part.issues)
    combined = pl.concat(frames) if frames else pl.DataFrame(schema=RowsSchema.polars_schema)
    annotations = (
        AnnotationBundle.merge_sorted(
            annotation_bundles,
            row_offsets=annotation_offsets,
            old_to_new={i: i for i in range(combined.height)},
        )
        if annotation_bundles
        else AnnotationBundle.empty()
    )
    return ParsedSeries(
        combined,
        tuple(definitions.values()),
        tuple(inventories),
        tuple(outcomes),
        tuple(issues),
        annotations=annotations,
    )

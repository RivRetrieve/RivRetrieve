"""Normalize Estonia (`ee_est`) EstModel daily JSON and `f_hydroseire` UTC hourly JSON."""

from __future__ import annotations

import json
import re
from datetime import datetime
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.ee_est.annotations import EE_EST_ESTMODEL_SCHEMA
from rivretrieve._internal.providers.ee_est.config import EstModelCoordinates, FHydroseireCoordinates
from rivretrieve._internal.providers.ee_est.fetch import reused_series
from rivretrieve._internal.providers.ee_est.series import FH_NAMESPACE, source_series
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
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    stable_id,
)

_PROVIDER_ID = ProviderId("ee_est")
_EM_EXPECTED_UNITS: dict[str, str] = {"Q": "m³/s", "H": "m", "T": "°C"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UTC_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)?$")
_FH_ROW_CAP = 20_000


def _validated_coordinates(
    payload_coords: object,
    product: ProductId,
    provider_config: ProviderConfig,
) -> EstModelCoordinates | FHydroseireCoordinates:
    try:
        configured = provider_config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"ee_est product is absent from provider config: {product}") from error
    if isinstance(configured, EstModelCoordinates):
        if payload_coords != configured:
            raise FatalContractError(f"ee_est payload coordinates contradict EstModel product {product}")
        return configured
    if isinstance(configured, FHydroseireCoordinates):
        if (
            not isinstance(payload_coords, FHydroseireCoordinates)
            or payload_coords.aegrida_nimi != configured.aegrida_nimi
            or payload_coords.product_id != configured.product_id
        ):
            raise FatalContractError(f"ee_est payload coordinates contradict f_hydroseire product {product}")
        return payload_coords
    raise FatalContractError(f"ee_est product lacks supported coordinate type: {product}")


def _parse_json_list(content: bytes, *, context: str) -> list[object]:
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise UnsupportedSourceStructureError(f"{context} response is not valid JSON") from error
    if not isinstance(document, list):
        raise UnsupportedSourceStructureError(f"{context} response must be a JSON array")
    return cast("list[object]", document)


def _finite_float_or_none(raw: object, *, context: str, field_name: str) -> float | None:
    if raw is None:
        return None
    if type(raw) not in (int, float):
        raise UnsupportedSourceStructureError(f"{context} field {field_name} must be numeric or null, got {raw!r}")
    try:
        num = float(cast("int | float", raw))
    except OverflowError as error:
        raise UnsupportedSourceStructureError(f"{context} field {field_name} overflows float64") from error
    if not isfinite(num):
        raise UnsupportedSourceStructureError(f"{context} field {field_name} must be finite, got {raw!r}")
    return num


def _resolve_parse_jaam_kood(
    payload: Payload,
    station: str,
    product: ProductId,
    coords: FHydroseireCoordinates,
) -> int:
    if coords.jaam_kood is not None:
        return coords.jaam_kood
    suffix = f":{coords.aegrida_nimi}"
    for item in payload.known_series:
        if item.station_id == station and item.product_id == str(product) and item.identity.namespace == FH_NAMESPACE:
            published = item.identity.published_id or ""
            if published.endswith(suffix):
                head = published[: -len(suffix)]
                if head.isascii() and head.isdigit() and int(head) > 0:
                    return int(head)
    raise FatalContractError(f"ee_est f_hydroseire payload lacks jaam_kood for {station}/{product}")


def _parse_estmodel(
    payload: Payload,
    station: str,
    product: ProductId,
    coords: EstModelCoordinates,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    raw_rows = _parse_json_list(payload.content, context="EstModel")
    expected_unit = _EM_EXPECTED_UNITS[coords.parameter]
    seen_dates: set[datetime] = set()
    times: list[datetime] = []
    values: list[float | None] = []
    qflags: list[str | None] = []
    prev_dt: datetime | None = None
    monotonic = True

    for index, entry in enumerate(raw_rows):
        if not isinstance(entry, dict):
            raise UnsupportedSourceStructureError(f"EstModel observation row {index} must be a JSON object")
        row = cast("dict[str, object]", entry)
        if row.get("parameter") != coords.parameter:
            raise UnsupportedSourceStructureError(
                f"EstModel row {index} parameter {row.get('parameter')!r} contradicts {coords.parameter!r}"
            )
        if row.get("unit") != expected_unit:
            raise UnsupportedSourceStructureError(
                f"EstModel row {index} unit {row.get('unit')!r} contradicts {expected_unit!r}"
            )
        start_str = row.get("startDate")
        end_str = row.get("endDate")
        if (
            not isinstance(start_str, str)
            or not isinstance(end_str, str)
            or _DATE_RE.fullmatch(start_str) is None
            or start_str != end_str
        ):
            raise UnsupportedSourceStructureError(
                f"EstModel row {index} requires matching YYYY-MM-DD startDate/endDate: {start_str!r}, {end_str!r}"
            )
        try:
            obs_dt = datetime.fromisoformat(start_str)
        except ValueError as error:
            raise UnsupportedSourceStructureError(
                f"EstModel row {index} invalid calendar date {start_str!r}"
            ) from error
        if obs_dt in seen_dates:
            raise UnsupportedSourceStructureError(
                f"EstModel {station}/{coords.product_id} duplicates observation date {start_str}"
            )
        seen_dates.add(obs_dt)

        value = _finite_float_or_none(row.get("value"), context=f"EstModel row {index}", field_name="value")
        qflag = row.get("qualityFlag")
        if qflag is not None and not isinstance(qflag, str):
            raise UnsupportedSourceStructureError(
                f"EstModel row {index} qualityFlag must be string or null, got {type(qflag).__name__}"
            )
        if prev_dt is not None and obs_dt < prev_dt:
            monotonic = False
        prev_dt = obs_dt
        times.append(obs_dt)
        values.append(value)
        qflags.append(qflag)

    n = len(times)
    if not monotonic:
        order = sorted(range(n), key=lambda i: times[i])
        times = [times[i] for i in order]
        values = [values[i] for i in order]
        qflags = [qflags[i] for i in order]
    definition = reused_series(source_series(station, str(product), origin="response"), payload.known_series)
    fact = definition.facts[0]
    evidence = f"source-call:{payload.acquisition_id}"

    rows_df = (
        pl.DataFrame(
            {
                "station_id": pl.repeat(station, n, dtype=pl.String, eager=True),
                "product_id": pl.repeat(str(product), n, dtype=pl.String, eager=True),
                "time": pl.Series("time", times, dtype=pl.Datetime("us")),
                "value": pl.Series("value", values, dtype=pl.Float64),
                "time_zone": pl.repeat("unknown", n, dtype=pl.String, eager=True),
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
        ann_frame = rows_df.select(
            "series_id", "facts_id", "station_id", "product_id", "time", "time_zone"
        ).with_columns(
            pl.lit(True).cast(pl.Boolean()).alias("measured"),
            pl.Series("qualityFlag", qflags, dtype=pl.String),
        )
        ann_table = ObservationAnnotationTable.from_rows(
            schema=EE_EST_ESTMODEL_SCHEMA,
            rows=ann_frame.select(*OBSERVATION_STRUCTURAL_SCHEMA, *EE_EST_ESTMODEL_SCHEMA.polars_schema()),
            measurement_indices=list(range(n)),
        )
        annotations = AnnotationBundle(observation_tables={EE_EST_ESTMODEL_SCHEMA.schema_id: ann_table})
    else:
        annotations = AnnotationBundle.empty()

    status = OutcomeStatus.EMPTY if n == 0 else OutcomeStatus.SUCCESS
    outcome = RetrievalOutcome(
        outcome_id=stable_id(
            payload.acquisition_id, definition.series_id, fact.facts_id, window.model_dump_json(), status
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
        snapshot_id=stable_id(payload.acquisition_id, definition.series_id, window.model_dump_json(), "em-inventory"),
        scope=scope,
        members=(definition.series_id,),
        member_facts=((definition.series_id, (fact.facts_id,)),),
        completeness=InventoryCompleteness.COMPLETE,
        access=f"EstModel /{station}/measurements {coords.parameter}:{coords.aggregation_type}",
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
    )
    return ParsedSeries(rows_df, (definition,), (inventory,), (outcome,), (), annotations)


def _parse_f_hydroseire(
    payload: Payload,
    station: str,
    product: ProductId,
    coords: FHydroseireCoordinates,
    jaam_kood: int,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    raw_rows = _parse_json_list(payload.content, context="Keskkonnaandmed f_hydroseire")
    if len(raw_rows) >= _FH_ROW_CAP:
        raise UnsupportedSourceStructureError(
            f"Keskkonnaandmed f_hydroseire response returned {len(raw_rows)} rows (>= {_FH_ROW_CAP} PostgREST cap)"
        )

    seen_times: set[datetime] = set()
    times: list[datetime] = []
    values: list[float | None] = []
    prev_dt: datetime | None = None
    monotonic = True

    for index, entry in enumerate(raw_rows):
        if not isinstance(entry, dict):
            raise UnsupportedSourceStructureError(f"f_hydroseire observation row {index} must be a JSON object")
        row = cast("dict[str, object]", entry)
        row_code = row.get("jaam_kood")
        if type(row_code) is not int or row_code != jaam_kood:
            raise UnsupportedSourceStructureError(
                f"f_hydroseire row {index} jaam_kood {row_code!r} contradicts requested {jaam_kood}"
            )
        if row.get("aegrida_nimi") != coords.aegrida_nimi:
            raise UnsupportedSourceStructureError(
                f"f_hydroseire row {index} aegrida_nimi {row.get('aegrida_nimi')!r} contradicts {coords.aegrida_nimi!r}"
            )
        ts_raw = row.get("timeline_ts_utc")
        if not isinstance(ts_raw, str) or _UTC_TS_RE.fullmatch(ts_raw) is None:
            raise UnsupportedSourceStructureError(
                f"f_hydroseire row {index} lacks valid UTC timeline_ts_utc timestamp: {ts_raw!r}"
            )
        try:
            obs_dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError as error:
            raise UnsupportedSourceStructureError(f"f_hydroseire row {index} invalid timestamp {ts_raw!r}") from error
        if obs_dt in seen_times:
            raise UnsupportedSourceStructureError(
                f"f_hydroseire {jaam_kood}/{coords.aegrida_nimi} duplicates UTC timestamp {ts_raw}"
            )
        seen_times.add(obs_dt)
        value = _finite_float_or_none(row.get("vaartus"), context=f"f_hydroseire row {index}", field_name="vaartus")
        if prev_dt is not None and obs_dt < prev_dt:
            monotonic = False
        prev_dt = obs_dt
        times.append(obs_dt)
        values.append(value)

    n = len(times)
    if not monotonic:
        order = sorted(range(n), key=lambda i: times[i])
        times = [times[i] for i in order]
        values = [values[i] for i in order]
    definition = reused_series(
        source_series(station, str(product), jaam_kood=jaam_kood, origin="response"),
        payload.known_series,
    )
    fact = definition.facts[0]
    evidence = f"source-call:{payload.acquisition_id}"

    rows_df = (
        pl.DataFrame(
            {
                "station_id": pl.repeat(station, n, dtype=pl.String, eager=True),
                "product_id": pl.repeat(str(product), n, dtype=pl.String, eager=True),
                "time": pl.Series("time", times, dtype=pl.Datetime("us")),
                "value": pl.Series("value", values, dtype=pl.Float64),
                "time_zone": pl.repeat("+00:00", n, dtype=pl.String, eager=True),
                "series_id": pl.repeat(definition.series_id, n, dtype=pl.String, eager=True),
                "facts_id": pl.repeat(fact.facts_id, n, dtype=pl.String, eager=True),
                "source_unit": pl.repeat(fact.source_unit.value, n, dtype=pl.String, eager=True),
            },
            schema=RowsSchema.polars_schema,
        )
        if n > 0
        else pl.DataFrame(schema=RowsSchema.polars_schema)
    )

    status = OutcomeStatus.EMPTY if n == 0 else OutcomeStatus.SUCCESS
    outcome = RetrievalOutcome(
        outcome_id=stable_id(
            payload.acquisition_id, definition.series_id, fact.facts_id, window.model_dump_json(), status
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
        snapshot_id=stable_id(payload.acquisition_id, definition.series_id, window.model_dump_json(), "fh-inventory"),
        scope=scope,
        members=(definition.series_id,),
        member_facts=((definition.series_id, (fact.facts_id,)),),
        completeness=InventoryCompleteness.COMPLETE,
        access=f"Keskkonnaandmed /f_hydroseire {jaam_kood}:{coords.aegrida_nimi}",
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
    )
    return ParsedSeries(rows_df, (definition,), (inventory,), (outcome,), (), AnnotationBundle.empty())


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Parse one Estonia (`ee_est`) EstModel daily or `f_hydroseire` hourly payload."""
    if len(payload.station_products) != 1:
        raise FatalContractError("ee_est payload requires exactly one station-product pair")
    station, product = payload.station_products[0]
    coords = _validated_coordinates(payload.source_coordinates.value, product, provider_config)
    jaam_kood = (
        _resolve_parse_jaam_kood(payload, station, product, coords)
        if isinstance(coords, FHydroseireCoordinates)
        else None
    )
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
        axis=payload.acquisition_axis,
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    scope = payload.scope or SeriesScope(provider_ids=("ee_est",), station_ids=(station,), product_ids=(str(product),))

    try:
        if isinstance(coords, EstModelCoordinates):
            return _parse_estmodel(payload, station, product, coords, window, retrieved, scope)
        assert jaam_kood is not None
        return _parse_f_hydroseire(payload, station, product, coords, jaam_kood, window, retrieved, scope)
    except UnsupportedSourceStructureError as error:
        reason = str(error)
        definition = reused_series(
            source_series(station, str(product), jaam_kood=jaam_kood, origin="response"),
            payload.known_series,
        )
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, definition.series_id, "failed"),
            series_id=definition.series_id,
            station_id=station,
            product_id=str(product),
            window=window,
            status=OutcomeStatus.FAILED,
            reason=reason,
            retrieved_at=retrieved,
        )
        inventory = InventorySnapshot(
            snapshot_id=stable_id(payload.acquisition_id, definition.series_id, "failed-inventory"),
            scope=scope,
            members=(definition.series_id,),
            completeness=InventoryCompleteness.INCOMPLETE,
            access="EstModel" if isinstance(coords, EstModelCoordinates) else "Keskkonnaandmed /f_hydroseire",
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
            pl.DataFrame(schema=RowsSchema.polars_schema), (definition,), (inventory,), (outcome,), (issue,)
        )

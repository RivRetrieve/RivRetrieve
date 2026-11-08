"""Normalize Colombia IDEAM S3 CSV observations with bounded [first_obs, last_obs] coverage."""

from __future__ import annotations

import csv
import io
from dataclasses import replace
from datetime import datetime, time, timedelta
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.co_ideam.config import CoIdeamS3CsvCoordinates
from rivretrieve._internal.providers.co_ideam.series import (
    CSV_HEADER,
    SPECS_BY_ETIQUETA,
    source_series,
)
from rivretrieve._internal.source_series import (
    ClippingAxis,
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    stable_id,
)

_PROVIDER_ID = ProviderId("co_ideam")
_TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Parse one IDEAM S3 CSV payload while confining malformed publisher bytes to bounded failures."""
    if not payload.station_products:
        raise FatalContractError("co_ideam payload requires at least one station-product pair")
    stations = {station for station, _ in payload.station_products}
    if len(stations) != 1:
        raise FatalContractError("co_ideam payload must identify a single station")
    station_only = next(iter(stations))
    if len(station_only) != 10 or not station_only.isascii() or not station_only.isdigit():
        raise FatalContractError(f"co_ideam station_id must be a canonical 10-digit ASCII code: {station_only!r}")

    for _, product in payload.station_products:
        _validated_product_coordinates(payload.source_coordinates.value, product, provider_config)

    if len(payload.station_products) > 1:
        frames: list[pl.DataFrame] = []
        definitions: dict[str, SourceSeries] = {}
        inventories: list[InventorySnapshot] = []
        outcomes: list[RetrievalOutcome] = []
        issues: list[Issue] = []
        for station, product in payload.station_products:
            pair_scope = (
                payload.scope.model_copy(update={"station_ids": (station,), "product_ids": (str(product),)})
                if payload.scope is not None
                else None
            )
            narrowed = replace(payload, station_products=((station, product),), scope=pair_scope)
            part = _parse_single_pair(narrowed, provider_config)
            if not part.rows.is_empty():
                frames.append(part.rows)
            for item in part.series:
                definitions[item.series_id] = item
            inventories.extend(part.inventories)
            outcomes.extend(part.outcomes)
            issues.extend(part.issues)
        combined = pl.concat(frames) if frames else pl.DataFrame(schema=RowsSchema.polars_schema)
        return ParsedSeries(
            combined,
            tuple(definitions.values()),
            tuple(inventories),
            tuple(outcomes),
            tuple(issues),
        )

    return _parse_single_pair(payload, provider_config)


def _parse_single_pair(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    station, product = payload.station_products[0]
    coords = _validated_product_coordinates(payload.source_coordinates.value, product, provider_config)
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    scope = payload.scope or SeriesScope(
        provider_ids=("co_ideam",),
        station_ids=(station,),
        product_ids=(str(product),),
    )
    try:
        return _parse_s3_csv(payload, station, product, coords, window, retrieved, scope)
    except UnsupportedSourceStructureError as error:
        reason = str(error)
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, station, str(product), "failed"),
            series_id=None,
            station_id=station,
            product_id=str(product),
            window=window,
            status=OutcomeStatus.FAILED,
            reason=reason,
            retrieved_at=retrieved,
        )
        issue = Issue(
            severity="error",
            code="source.unsupported_structure",
            message=reason,
            details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
            provider_id=_PROVIDER_ID,
        )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), (outcome,), (issue,))


def _validated_product_coordinates(
    payload_coords: object,
    product: ProductId,
    provider_config: ProviderConfig,
) -> CoIdeamS3CsvCoordinates:
    try:
        configured = provider_config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"co_ideam product is absent from provider config: {product}") from error
    if not isinstance(configured, CoIdeamS3CsvCoordinates):
        raise FatalContractError(f"co_ideam configured product lacks CoIdeamS3CsvCoordinates: {product}")
    if not isinstance(payload_coords, CoIdeamS3CsvCoordinates):
        raise FatalContractError(f"co_ideam payload has unsupported coordinate type: {type(payload_coords)!r}")
    if payload_coords != configured:
        raise FatalContractError("co_ideam payload coordinates contradict configured product")
    return configured


def _verify_origin_url_if_s3(origin_url: object, *, station: str, etiqueta: str) -> None:
    if not isinstance(origin_url, str) or "/observaciones/historicos/csv/" not in origin_url:
        return
    clean_path = origin_url.split("?", 1)[0].split("#", 1)[0]
    expected_suffix = f"/observaciones/historicos/csv/{etiqueta}/{station}-{etiqueta}.csv"
    if not clean_path.endswith(expected_suffix):
        raise UnsupportedSourceStructureError(
            f"IDEAM S3 response URL {clean_path!r} contradicts requested ({station!r}, {etiqueta!r})"
        )


def _read_strict_three_column_csv(raw_bytes: bytes, *, station: str, etiqueta: str) -> pl.DataFrame:
    if raw_bytes == b"":
        raise UnsupportedSourceStructureError(f"IDEAM S3 CSV response for {station} {etiqueta} is empty (0 bytes)")
    try:
        text = raw_bytes.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise UnsupportedSourceStructureError(f"IDEAM S3 {etiqueta} CSV is not valid UTF-8 text") from error

    lines = text.splitlines()
    if not lines:
        raise UnsupportedSourceStructureError(f"IDEAM S3 {etiqueta} CSV contains no header line")

    if '"' not in text:
        header = tuple(lines[0].split(","))
        if header != CSV_HEADER:
            raise UnsupportedSourceStructureError(
                f"IDEAM S3 {etiqueta} CSV lacks expected header {CSV_HEADER!r}: {header!r}"
            )
        for line_no, raw_line in enumerate(lines[1:], start=2):
            if not raw_line.strip():
                raise UnsupportedSourceStructureError(f"IDEAM S3 {etiqueta} CSV contains blank line at line {line_no}")
            if raw_line.count(",") != 2:
                raise UnsupportedSourceStructureError(
                    f"IDEAM S3 {etiqueta} CSV line {line_no} does not have exactly 3 columns"
                )
        if len(lines) == 1:
            return pl.DataFrame(schema=dict.fromkeys(CSV_HEADER, pl.String))
        try:
            return pl.read_csv(
                text.encode("utf-8"),
                has_header=True,
                infer_schema=False,
                null_values=[],
                truncate_ragged_lines=False,
                quote_char=None,
            )
        except pl.exceptions.PolarsError as error:
            raise UnsupportedSourceStructureError(f"Malformed IDEAM S3 {etiqueta} CSV structure: {error}") from error

    try:
        reader = csv.reader(io.StringIO(text))
        parsed_header = next(reader, None)
        if parsed_header is None or tuple(parsed_header) != CSV_HEADER:
            raise UnsupportedSourceStructureError(
                f"IDEAM S3 {etiqueta} CSV lacks expected header {CSV_HEADER!r}: {parsed_header!r}"
            )
        rows_ts: list[str] = []
        rows_val: list[str] = []
        rows_app: list[str] = []
        for line_no, row in enumerate(reader, start=2):
            if len(row) != 3:
                raise UnsupportedSourceStructureError(
                    f"IDEAM S3 {etiqueta} CSV line {line_no} has {len(row)} columns; expected 3"
                )
            rows_ts.append(row[0])
            rows_val.append(row[1])
            rows_app.append(row[2])
    except csv.Error as error:
        raise UnsupportedSourceStructureError(f"Malformed quoted IDEAM S3 {etiqueta} CSV: {error}") from error

    return pl.DataFrame(
        {
            "fechaObservacion": pl.Series("fechaObservacion", rows_ts, dtype=pl.String),
            "valorObservado": pl.Series("valorObservado", rows_val, dtype=pl.String),
            "nivelAprobacion": pl.Series("nivelAprobacion", rows_app, dtype=pl.String),
        }
    )


def _parse_s3_csv(
    payload: Payload,
    station: str,
    product: ProductId,
    coords: CoIdeamS3CsvCoordinates,
    window: SeriesWindow,
    retrieved: datetime | None,
    scope: SeriesScope,
) -> ParsedSeries:
    _verify_origin_url_if_s3(payload.origin.url, station=station, etiqueta=coords.etiqueta)
    raw_df = _read_strict_three_column_csv(payload.content, station=station, etiqueta=coords.etiqueta)
    spec = SPECS_BY_ETIQUETA[coords.etiqueta]

    evidence = f"source-call:{payload.acquisition_id}"
    definition = _reused_series(
        source_series(
            station,
            coords.etiqueta,
            origin="response",
            identity_evidence=(evidence,),
        ),
        payload.known_series,
    )
    fact = definition.facts[0]

    if raw_df.height == 0:
        reason = "Header-only IDEAM S3 CSV contains zero observation rows and establishes no covered interval"
        unresolved_outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id, "header-only-unresolved"),
            series_id=definition.series_id,
            station_id=station,
            product_id=str(product),
            window=window,
            status=OutcomeStatus.UNRESOLVED,
            facts_ids=(fact.facts_id,),
            reason=reason,
            retrieved_at=retrieved,
        )
        incomplete_inventory = InventorySnapshot(
            snapshot_id=stable_id(payload.acquisition_id, definition.series_id, "header-only-inventory"),
            scope=scope,
            members=(definition.series_id,),
            member_facts=((definition.series_id, (fact.facts_id,)),),
            completeness=InventoryCompleteness.INCOMPLETE,
            access=coords.etiqueta,
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(evidence,),
            reason=reason,
        )
        return ParsedSeries(
            pl.DataFrame(schema=RowsSchema.polars_schema),
            (definition,),
            (incomplete_inventory,),
            (unresolved_outcome,),
        )

    ts_col = raw_df["fechaObservacion"]
    if (~ts_col.str.contains(_TIMESTAMP_PATTERN)).any():
        raise UnsupportedSourceStructureError(
            f"IDEAM S3 {coords.etiqueta} CSV contains timestamp outside YYYY-MM-DD HH:MM:SS format"
        )
    ts = ts_col.str.strptime(pl.Datetime("us"), "%Y-%m-%d %H:%M:%S", strict=False)
    if ts.null_count() > 0:
        raise UnsupportedSourceStructureError(f"IDEAM S3 {coords.etiqueta} CSV contains invalid calendar timestamp")

    if ts.len() > 1 and bool((ts.diff().drop_nulls() < timedelta(0)).any()):
        raise UnsupportedSourceStructureError(f"IDEAM S3 {coords.etiqueta} CSV contains decreasing timestamps")

    if spec.frequency == "monthly" and bool((ts.dt.day() != 1).any()):
        raise UnsupportedSourceStructureError(
            f"IDEAM S3 monthly {coords.etiqueta} CSV contains non-first-of-month timestamp"
        )
    if spec.frequency == "yearly" and bool(((ts.dt.month() != 1) | (ts.dt.day() != 1)).any()):
        raise UnsupportedSourceStructureError(f"IDEAM S3 yearly {coords.etiqueta} CSV contains non-Jan-1 timestamp")

    vals = raw_df["valorObservado"].str.strip_chars().cast(pl.Float64, strict=False)
    if vals.null_count() > 0 or bool((~vals.is_finite()).any()):
        raise UnsupportedSourceStructureError(
            f"IDEAM S3 {coords.etiqueta} CSV contains blank, non-numeric, or non-finite valorObservado"
        )

    rows_df = pl.DataFrame(
        {
            "station_id": pl.repeat(station, raw_df.height, dtype=pl.String, eager=True),
            "product_id": pl.repeat(str(product), raw_df.height, dtype=pl.String, eager=True),
            "time": ts,
            "value": vals,
            "time_zone": pl.repeat("unknown", raw_df.height, dtype=pl.String, eager=True),
            "series_id": pl.repeat(definition.series_id, raw_df.height, dtype=pl.String, eager=True),
            "facts_id": pl.repeat(fact.facts_id, raw_df.height, dtype=pl.String, eager=True),
            "source_unit": pl.repeat(fact.source_unit.value, raw_df.height, dtype=pl.String, eager=True),
        },
        schema=RowsSchema.polars_schema,
    )

    first_ts = cast("datetime", ts[0])
    last_ts = cast("datetime", ts[-1])
    if fact.clipping_axis is ClippingAxis.CALENDAR_DATE:
        covered_start = datetime.combine(first_ts.date(), time.min)
        covered_end = datetime.combine(last_ts.date(), time.max)
    else:
        covered_start = first_ts
        covered_end = last_ts

    covered_window = SeriesWindow(start=covered_start, end=covered_end)
    positive_outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, definition.series_id, fact.facts_id, "interval"),
        series_id=definition.series_id,
        station_id=station,
        product_id=str(product),
        window=covered_window,
        status=OutcomeStatus.SUCCESS,
        facts_ids=(fact.facts_id,),
        retrieved_at=retrieved,
        coverage="interval",
    )
    outcomes: list[RetrievalOutcome] = [positive_outcome]
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
        pre_reason="Requested interval precedes first published IDEAM S3 observation",
        post_reason="Requested interval extends beyond latest published IDEAM S3 observation",
    )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, definition.series_id, "s3-csv-inventory"),
        scope=scope,
        members=(definition.series_id,),
        member_facts=((definition.series_id, (fact.facts_id,)),),
        completeness=InventoryCompleteness.COMPLETE,
        access=coords.etiqueta,
        origin="response",
        acquired_at=retrieved,
        window=covered_window,
        evidence=(evidence,),
    )
    return ParsedSeries(
        rows_df,
        (definition,),
        (inventory,),
        tuple(outcomes),
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
                    window=SeriesWindow(start=window.start, end=pre_end),
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
                    window=SeriesWindow(start=post_start, end=window.end),
                    status=OutcomeStatus.UNRESOLVED,
                    facts_ids=(facts_id,),
                    reason=post_reason,
                    retrieved_at=retrieved_at,
                )
            )


def _reused_series(definition: SourceSeries, known_series: tuple[SourceSeries, ...]) -> SourceSeries:
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

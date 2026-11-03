"""Normalize BoM KiWIS JSON observations, surfacing every live ts_id and quality code."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.au_bom.config import (
    NATIVE_UNIT_SYMBOLS,
    AuBomTimeseriesListCoordinates,
    AuBomTimeseriesValuesCoordinates,
)
from rivretrieve._internal.providers.au_bom.fetch import resolve_timeseries_list
from rivretrieve._internal.providers.au_bom.series import PRODUCT_DEFINITIONS, describe_series
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    admission,
    stable_id,
)

_PROVIDER_ID = ProviderId("au_bom")
_QUANTITY_BY_PRODUCT_ID = {d.product_id: d.quantity for d in PRODUCT_DEFINITIONS}
_PLUS_TEN_HOURS = timedelta(hours=10)


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Parse one au_bom payload: a shared ts_id lookup or one product's observation values."""
    if not payload.station_products:
        raise FatalContractError("au_bom payload requires at least one station-product pair")
    stations = {station for station, _ in payload.station_products}
    if len(stations) != 1:
        raise FatalContractError("au_bom payload must identify a single station")

    if isinstance(payload.source_coordinates.value, AuBomTimeseriesListCoordinates):
        return _parse_list_prerequisite(payload, provider_config)

    if len(payload.station_products) != 1:
        raise FatalContractError("au_bom values payload must identify exactly one station-product pair")
    station, product = payload.station_products[0]
    coords = provider_config.products[product].coordinates.value
    if not isinstance(coords, AuBomTimeseriesValuesCoordinates):
        raise FatalContractError(f"au_bom product has invalid source coordinates: {product}")
    return _parse_values(payload, station, product)


def _parse_list_prerequisite(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Resolve NO_MATCH for any product this station's ts_id lookup did not resolve.

    A product the lookup *did* resolve has its own values Payload (or
    FailedSourceRequest) owning the real outcome; this never double-reports it.
    """
    station = payload.station_products[0][0]
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    evidence = f"source-call:{payload.acquisition_id}"
    try:
        ts_id_map = resolve_timeseries_list(payload.content, station)
    except UnsupportedSourceStructureError as error:
        reason = str(error)
        outcomes = tuple(
            RetrievalOutcome(
                outcome_id=stable_id(payload.acquisition_id, station, str(product), "list-failed"),
                series_id=None,
                station_id=station,
                product_id=str(product),
                window=window,
                status=OutcomeStatus.FAILED,
                reason=reason,
                retrieved_at=retrieved,
            )
            for _, product in payload.station_products
        )
        issue = Issue(
            severity="error",
            code="source.unsupported_structure",
            message=reason,
            details={"station_id": station},
            provider_id=_PROVIDER_ID,
        )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), outcomes, (issue,))

    outcomes: list[RetrievalOutcome] = []
    inventories: list[InventorySnapshot] = []
    issues: list[Issue] = []
    for _, product in payload.station_products:
        coords = provider_config.products[product].coordinates.value
        if not isinstance(coords, AuBomTimeseriesValuesCoordinates):
            raise FatalContractError(f"au_bom product has invalid source coordinates: {product}")
        if ts_id_map.get((coords.native_id, coords.parametertype_name), ()):
            # The matching values Payload (or its FailedSourceRequest) owns this product's outcome.
            continue
        reason = (
            f"BoM getTimeseriesList lists no ts_id for station {station} series "
            f"{coords.native_id!r} ({coords.parametertype_name})"
        )
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, station, str(product), "list-no-match"),
            series_id=None,
            station_id=station,
            product_id=str(product),
            window=window,
            status=OutcomeStatus.NO_MATCH,
            reason=reason,
            retrieved_at=retrieved,
        )
        outcomes.append(outcome)
        inventories.append(
            InventorySnapshot(
                snapshot_id=stable_id(payload.acquisition_id, station, str(product), "list-no-match-inventory"),
                scope=SeriesScope(provider_ids=("au_bom",), station_ids=(station,), product_ids=(str(product),)),
                members=(),
                completeness=InventoryCompleteness.COMPLETE,
                access="getTimeseriesList",
                origin="response",
                acquired_at=retrieved,
                window=window,
                evidence=(evidence,),
            )
        )
        issues.append(
            Issue(
                severity="warning",
                code="source.no_match",
                message=reason,
                details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
                provider_id=_PROVIDER_ID,
            )
        )

    return ParsedSeries(
        pl.DataFrame(schema=RowsSchema.polars_schema), (), tuple(inventories), tuple(outcomes), tuple(issues)
    )


def _parse_values(payload: Payload, station: str, product: ProductId) -> ParsedSeries:
    if payload.content == b"":
        raise UnsupportedSourceStructureError(f"BoM getTimeseriesValues response for {station} {product} is empty")
    try:
        blocks = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("BoM getTimeseriesValues response is not valid JSON") from error
    if not isinstance(blocks, list) or not blocks:
        raise UnsupportedSourceStructureError("BoM getTimeseriesValues response must be a nonempty JSON array")

    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    scope = payload.scope or SeriesScope(provider_ids=("au_bom",), station_ids=(station,), product_ids=(str(product),))
    evidence = f"source-call:{payload.acquisition_id}"

    frames: list[pl.DataFrame] = []
    definitions: dict[str, SourceSeries] = {}
    inventories: list[InventorySnapshot] = []
    outcomes: list[RetrievalOutcome] = []
    issues: list[Issue] = []

    for block in blocks:
        if not isinstance(block, dict) or "ts_id" not in block or "columns" not in block or "data" not in block:
            raise UnsupportedSourceStructureError("BoM getTimeseriesValues block lacks ts_id, columns or data")
        ts_id = str(block["ts_id"])
        columns = [name.strip() for name in str(block["columns"]).split(",")]
        try:
            time_index = columns.index("Timestamp")
            value_index = columns.index("Value")
        except ValueError as error:
            raise UnsupportedSourceStructureError("BoM getTimeseriesValues block lacks Timestamp or Value") from error
        quality_index = columns.index("Quality Code") if "Quality Code" in columns else None
        quality_name_index = columns.index("Quality Code Name") if "Quality Code Name" in columns else None
        rows = block["data"]
        if not isinstance(rows, list):
            raise UnsupportedSourceStructureError("BoM getTimeseriesValues block data must be a list")

        series = describe_series(
            station, ts_id, str(product), NATIVE_UNIT_SYMBOLS[_QUANTITY_BY_PRODUCT_ID[str(product)]]
        )
        fact = series.facts[0]
        definitions[series.series_id] = series

        if admission(fact).status != "supported":
            outcome = RetrievalOutcome(
                outcome_id=stable_id(payload.acquisition_id, series.series_id, fact.facts_id, "unsupported"),
                series_id=series.series_id,
                station_id=station,
                product_id=str(product),
                window=window,
                status=OutcomeStatus.UNSUPPORTED,
                facts_ids=(fact.facts_id,),
                reason=f"Source unit {fact.source_unit.value!r} is not supported",
                retrieved_at=retrieved,
            )
            outcomes.append(outcome)
            inventories.append(
                InventorySnapshot(
                    snapshot_id=stable_id(payload.acquisition_id, series.series_id, "unsupported-inventory"),
                    scope=scope,
                    members=(series.series_id,),
                    member_facts=((series.series_id, (fact.facts_id,)),),
                    completeness=InventoryCompleteness.COMPLETE,
                    access="getTimeseriesValues",
                    origin="response",
                    acquired_at=retrieved,
                    window=window,
                    evidence=(evidence,),
                )
            )
            continue

        numeric_rows: list[dict[str, object]] = []
        quality_occurrences: list[tuple[datetime, object, str]] = []
        for raw_row in rows:
            if not isinstance(raw_row, list) or len(raw_row) != len(columns):
                raise UnsupportedSourceStructureError(f"BoM getTimeseriesValues row for ts_id {ts_id} is malformed")
            label = raw_row[time_index]
            if not isinstance(label, str):
                raise UnsupportedSourceStructureError(
                    f"BoM getTimeseriesValues timestamp for ts_id {ts_id} is not a string"
                )
            try:
                timestamp = datetime.fromisoformat(label)
            except ValueError as error:
                raise UnsupportedSourceStructureError(
                    f"Malformed BoM getTimeseriesValues timestamp {label!r} for ts_id {ts_id}"
                ) from error
            # Confirmed live, 2026-11-03: every admitted series labels +10:00 explicitly;
            # a disagreement here is a genuine surprise, not a formatting variant to absorb.
            if timestamp.utcoffset() != _PLUS_TEN_HOURS:
                raise UnsupportedSourceStructureError(
                    f"BoM getTimeseriesValues timestamp {label!r} for ts_id {ts_id} does not carry +10:00"
                )
            naive_time = timestamp.replace(tzinfo=None)
            value = raw_row[value_index]
            if value is not None and not isinstance(value, (int, float)):
                raise UnsupportedSourceStructureError(f"BoM getTimeseriesValues value for ts_id {ts_id} is not numeric")
            numeric_rows.append(
                {
                    "station_id": station,
                    "product_id": str(product),
                    "time": naive_time,
                    "value": float(value) if value is not None else None,
                    "time_zone": "+10:00",
                    "series_id": series.series_id,
                    "facts_id": fact.facts_id,
                    "source_unit": fact.source_unit.value,
                }
            )
            if quality_index is not None:
                code = raw_row[quality_index]
                name = str(raw_row[quality_name_index]) if quality_name_index is not None else str(code)
                if name != "quality-A":
                    quality_occurrences.append((naive_time, code, name))

        if numeric_rows:
            frames.append(pl.DataFrame(numeric_rows, schema=RowsSchema.polars_schema))
        outcomes.append(
            RetrievalOutcome(
                outcome_id=stable_id(payload.acquisition_id, series.series_id, fact.facts_id, "interval"),
                series_id=series.series_id,
                station_id=station,
                product_id=str(product),
                window=window,
                status=OutcomeStatus.SUCCESS if numeric_rows else OutcomeStatus.EMPTY,
                facts_ids=(fact.facts_id,),
                retrieved_at=retrieved,
                coverage="interval",
            )
        )
        inventories.append(
            InventorySnapshot(
                snapshot_id=stable_id(payload.acquisition_id, series.series_id, "values-inventory"),
                scope=scope,
                members=(series.series_id,),
                member_facts=((series.series_id, (fact.facts_id,)),),
                completeness=InventoryCompleteness.COMPLETE,
                access="getTimeseriesValues",
                origin="response",
                acquired_at=retrieved,
                window=window,
                evidence=(evidence,),
            )
        )
        for occurred_at, code, name in quality_occurrences:
            issues.append(
                Issue(
                    severity="info",
                    code="source.quality_code",
                    message=f"BoM reports quality code {code} ({name}) for {station} {product} at {occurred_at.isoformat()}",
                    details={
                        "station_id": station,
                        "product_id": str(product),
                        "series_id": series.series_id,
                        "source_quality_code": code,
                        "source_quality_code_name": name,
                        "source_time": occurred_at.isoformat(),
                    },
                    provider_id=_PROVIDER_ID,
                )
            )

    combined = pl.concat(frames) if frames else pl.DataFrame(schema=RowsSchema.polars_schema)
    return ParsedSeries(combined, tuple(definitions.values()), tuple(inventories), tuple(outcomes), tuple(issues))

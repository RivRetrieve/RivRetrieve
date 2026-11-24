"""Normalize BoM KiWIS JSON observations, surfacing every live ts_id and quality code."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.au_bom.annotations import AU_BOM_QUALITY_SCHEMA
from rivretrieve._internal.providers.au_bom.config import (
    NATIVE_UNIT_SYMBOLS,
    AuBomTimeseriesListCoordinates,
    AuBomTimeseriesValuesCoordinates,
)
from rivretrieve._internal.providers.au_bom.series import PRODUCT_DEFINITIONS, describe_series
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
    SourceSeries,
    admission,
    stable_id,
)

_PROVIDER_ID = ProviderId("au_bom")
_QUANTITY_BY_PRODUCT_ID = {d.product_id: d.quantity for d in PRODUCT_DEFINITIONS}
_PLUS_TEN_HOURS = timedelta(hours=10)


def resolve_timeseries_list(content: bytes, station: str) -> dict[tuple[str, str], tuple[tuple[str, str], ...]]:
    """Map each ``(ts_name, parametertype_name)`` at ``station`` to its ``(ts_id, ts_unitsymbol)`` pairs.

    ``ts_name`` alone is ambiguous (confirmed live, 2026-11-03: station 410730's
    ``DMQaQc.Merged.DailyMean.24HR`` is shared by discharge, stage, pH,
    turbidity, conductivity and water temperature alike); ``parametertype_name``
    disambiguates it. A resolved pair can still map to more than one ``ts_id``
    (confirmed live, 2026-11-03: 74 discharge, 79 stage and 4 water-temperature
    stations each carry two ``ts_id`` for one admitted series, with no field
    distinguishing them). This returns every pair found, never collapsing them.
    """
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("BoM getTimeseriesList response is not valid JSON") from error
    if not isinstance(document, list) or not document or not isinstance(document[0], list):
        raise UnsupportedSourceStructureError("BoM getTimeseriesList response must be a JSON array of arrays")
    header = document[0]
    try:
        name_index = header.index("ts_name")
        parameter_index = header.index("parametertype_name")
        id_index = header.index("ts_id")
        unit_index = header.index("ts_unitsymbol")
        station_index = header.index("station_no")
    except ValueError as error:
        raise UnsupportedSourceStructureError("BoM getTimeseriesList header lacks a required column") from error

    resolved: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for row in document[1:]:
        if not isinstance(row, list) or len(row) != len(header):
            raise UnsupportedSourceStructureError("BoM getTimeseriesList row does not match its header width")
        if str(row[station_index]) != station:
            raise UnsupportedSourceStructureError(
                f"BoM getTimeseriesList row station_no {row[station_index]!r} contradicts requested station {station!r}"
            )
        key = (str(row[name_index]), str(row[parameter_index]))
        resolved.setdefault(key, []).append((str(row[id_index]), str(row[unit_index])))
    return {key: tuple(pairs) for key, pairs in resolved.items()}


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
    try:
        return _parse_values(payload, station, product)
    except UnsupportedSourceStructureError as error:
        return _failed_values(payload, station, product, str(error))


def _parse_list_prerequisite(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Decode the getTimeseriesList response and interpret it (the driver's fallback path
    when fetch.py's own acquisition-time interpretation was not handed off for reuse; see
    interpret_timeseries_list below).
    """
    station = payload.station_products[0][0]
    try:
        ts_id_map = resolve_timeseries_list(payload.content, station)
    except UnsupportedSourceStructureError as error:
        return interpret_timeseries_list_failure(payload, str(error))
    return interpret_timeseries_list(payload, provider_config, ts_id_map)


def interpret_timeseries_list_failure(payload: Payload, reason: str) -> ParsedSeries:
    """Isolate a malformed getTimeseriesList response as a FAILED outcome per product."""
    station = payload.station_products[0][0]
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
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


def interpret_timeseries_list(
    payload: Payload,
    provider_config: ProviderConfig,
    ts_id_map: dict[tuple[str, str], tuple[tuple[str, str], ...]],
) -> ParsedSeries:
    """Resolve NO_MATCH, or UNSUPPORTED for a reported-but-wrong-unit series, for any product
    this station's already-decoded ts_id lookup did not resolve into a genuine values request.

    A product the lookup *did* resolve has its own values Payload (or FailedSourceRequest)
    owning the real outcome; this never double-reports it. Takes the already-decoded
    ts_id_map rather than payload.content so fetch.py can hand off its own acquisition-time
    interpretation (built from the one resolve_timeseries_list call it already makes to
    decide which values calls to issue) instead of the driver decoding the same JSON again.
    """
    station = payload.station_products[0][0]
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    evidence = f"source-call:{payload.acquisition_id}"
    outcomes: list[RetrievalOutcome] = []
    inventories: list[InventorySnapshot] = []
    issues: list[Issue] = []
    for _, product in payload.station_products:
        coords = provider_config.products[product].coordinates.value
        if not isinstance(coords, AuBomTimeseriesValuesCoordinates):
            raise FatalContractError(f"au_bom product has invalid source coordinates: {product}")
        pairs = ts_id_map.get((coords.native_id, coords.parametertype_name), ())
        # fetch.py applies this exact same unit filter before deciding whether to issue a
        # values call; a series excluded there never reaches _parse_values at all, so this
        # path -- not the (now unreachable) admission() check inside _parse_values -- is
        # where a reported-but-wrong-unit series must be told apart from a genuinely absent
        # one and given its own clear reason instead of a generic unresolved-scope fallback.
        expected_unit = NATIVE_UNIT_SYMBOLS[_QUANTITY_BY_PRODUCT_ID[str(product)]]
        if any(unit == expected_unit for _, unit in pairs):
            # The matching values Payload (or its FailedSourceRequest) owns this product's outcome.
            continue
        if pairs:
            reported_units = sorted({unit for _, unit in pairs})
            reason = (
                f"BoM getTimeseriesList reports station {station} series {coords.native_id!r} "
                f"({coords.parametertype_name}) in {reported_units!r}, not the expected {expected_unit!r}"
            )
            status = OutcomeStatus.UNSUPPORTED
            issue_code = "source.unsupported_unit"
        else:
            reason = (
                f"BoM getTimeseriesList lists no ts_id for station {station} series "
                f"{coords.native_id!r} ({coords.parametertype_name})"
            )
            status = OutcomeStatus.NO_MATCH
            issue_code = "source.no_match"
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, station, str(product), "list-no-match"),
            series_id=None,
            station_id=station,
            product_id=str(product),
            window=window,
            status=status,
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
                code=issue_code,
                message=reason,
                details={"station_id": station, "product_id": str(product), "outcome_id": outcome.outcome_id},
                provider_id=_PROVIDER_ID,
            )
        )

    return ParsedSeries(
        pl.DataFrame(schema=RowsSchema.polars_schema), (), tuple(inventories), tuple(outcomes), tuple(issues)
    )


def _failed_values(payload: Payload, station: str, product: ProductId, reason: str) -> ParsedSeries:
    """Isolate a malformed getTimeseriesValues response as a FAILED outcome instead of crashing the batch.

    Mirrors _parse_list_prerequisite's own UnsupportedSourceStructureError handling so a single
    malformed values response cannot abort healthy stations/products sharing the same request.
    """
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    outcome = RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, station, str(product), "values-failed"),
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
        details={"station_id": station, "product_id": str(product)},
        provider_id=_PROVIDER_ID,
    )
    return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), (outcome,), (issue,))


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
    outcomes: list[RetrievalOutcome] = []
    ann_rows: list[dict[str, object]] = []
    ann_measurement_indices: list[int] = []
    row_offset = 0
    # Every block in one getTimeseriesValues response is part of the SAME acquisition
    # and the SAME scope (duplicate ts_id at one station publishes more than one block
    # here, #645/#646). One combined InventorySnapshot below -- not one per block -- so
    # a later cache="reuse" lookup sees every resolved series as a member of this scope,
    # instead of only whichever block's snapshot a reversed scan happens to see first.
    all_members: list[str] = []
    all_member_facts: list[tuple[str, tuple[str, ...]]] = []

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
        if (quality_index is None) != (quality_name_index is None):
            raise UnsupportedSourceStructureError(
                f"BoM getTimeseriesValues block for ts_id {ts_id} has Quality Code without Quality Code Name, or vice versa"
            )
        has_quality = quality_index is not None
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
            all_members.append(series.series_id)
            all_member_facts.append((series.series_id, (fact.facts_id,)))
            continue

        numeric_rows: list[dict[str, object]] = []
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
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
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
            if has_quality:
                code = raw_row[quality_index]
                if code is not None and type(code) is not int:
                    raise UnsupportedSourceStructureError(
                        f"BoM getTimeseriesValues Quality Code for ts_id {ts_id} is not an integer or null"
                    )
                name = raw_row[quality_name_index]
                if name is not None and not isinstance(name, str):
                    raise UnsupportedSourceStructureError(
                        f"BoM getTimeseriesValues Quality Code Name for ts_id {ts_id} is not a string or null"
                    )
                ann_rows.append(
                    {
                        "series_id": series.series_id,
                        "facts_id": fact.facts_id,
                        "station_id": station,
                        "product_id": str(product),
                        "time": naive_time,
                        "time_zone": "+10:00",
                        "measured": True,
                        "Quality_Code": code,
                        "Quality_Code_Name": name,
                    }
                )
                ann_measurement_indices.append(row_offset + len(numeric_rows) - 1)

        if numeric_rows:
            frames.append(pl.DataFrame(numeric_rows, schema=RowsSchema.polars_schema))
            row_offset += len(numeric_rows)
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
        all_members.append(series.series_id)
        all_member_facts.append((series.series_id, (fact.facts_id,)))
    inventories = (
        InventorySnapshot(
            snapshot_id=stable_id(payload.acquisition_id, station, str(product), "values-inventory"),
            scope=scope,
            members=tuple(all_members),
            member_facts=tuple(all_member_facts),
            completeness=InventoryCompleteness.COMPLETE,
            access="getTimeseriesValues",
            origin="response",
            acquired_at=retrieved,
            window=window,
            evidence=(evidence,),
        ),
    )
    combined = pl.concat(frames) if frames else pl.DataFrame(schema=RowsSchema.polars_schema)
    if ann_rows:
        ann_frame = pl.DataFrame(
            ann_rows,
            schema={**OBSERVATION_STRUCTURAL_SCHEMA, **AU_BOM_QUALITY_SCHEMA.polars_schema()},
        )
        ann_table = ObservationAnnotationTable.from_rows(
            schema=AU_BOM_QUALITY_SCHEMA,
            rows=ann_frame,
            measurement_indices=ann_measurement_indices,
        )
        annotations = AnnotationBundle(observation_tables={AU_BOM_QUALITY_SCHEMA.schema_id: ann_table})
    else:
        annotations = AnnotationBundle.empty()
    return ParsedSeries(
        combined,
        tuple(definitions.values()),
        tuple(inventories),
        tuple(outcomes),
        annotations=annotations,
    )

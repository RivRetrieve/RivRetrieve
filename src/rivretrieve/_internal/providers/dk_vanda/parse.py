"""Normalize VandA water-flows/water-levels/measurements-results-current pages.

Stage (examinationTypeSc 25) is parsed by hand into two distinct source
series per `series.py`'s `result`/`resultElevationCorrected`
identities; discharge and temperature go through the shared
`parse_mapped_series` machinery with `config.py`'s single-field
`SeriesMapping`, matching `lt_lhmt`'s precedent.

Multi-version-results tolerance (research/dk-vanda-source-access.md): more
than one result per native timestamp has never been reproduced for this port
across four probing rounds, but this parser does not assert or rely on
per-timestamp uniqueness anywhere -- every row VandA returns becomes its own
observation row, so a future doubling would be preserved, not silently
collapsed or rejected.

`reasonSc`/`reason` are published only on `/measurements/results/current`'s
richer response shape (`ResultResponse`), not on `/water-flows`'s or
`/water-levels`'s streamline shape (`ResultStreamlineResponse` /
`WaterLevelResultStreamlineResponse` -- checked directly against
`swagger.json` and real retained bytes in step 4; discharge and stage simply
carry no such field to surface. When present (temperature, via
`/measurements/results/current`), a non-null `reasonSc`/`reason` becomes an
`info`-severity `Issue` carrying VandA's own published `reason` text verbatim
-- `/config/examination-types`' `reasonCodesSc` vocabulary has no published
textual meaning for any code (every `description` is `null`), so this port
does not invent one.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.provider_series import NATIVE_SCHEMA, UnsupportedSourceStructureError, parse_mapped_series
from rivretrieve._internal.providers.dk_vanda.config import DkVandaSourceCoordinates, series_mapping
from rivretrieve._internal.providers.dk_vanda.series import STAGE_FIELDS, stage_facts, stage_identity
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    admission,
    stable_id,
)

_PROVIDER_ID = ProviderId("dk_vanda")
_INSTANT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z$")


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Dispatch one payload's single station-product pair to its parser."""
    if len(payload.station_products) != 1:
        raise FatalContractError("dk_vanda payload must identify exactly one station-product pair")
    station, product = payload.station_products[0]
    configured = provider_config.products.get(product)
    if configured is None:
        raise FatalContractError(f"dk_vanda product is absent from provider config: {product}")
    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, DkVandaSourceCoordinates) or coordinates != configured.coordinates.value:
        raise FatalContractError("dk_vanda payload coordinates contradict configured product")

    if product == "stage":
        return _parse_stage(payload, station, coordinates)
    return parse_mapped_series(
        payload,
        provider_config,
        provider="dk_vanda",
        mappings={product: series_mapping(product)},
        native_parse=_native_parse_single_field,
    )


def _native_parse_single_field(payload: Payload, provider_config: ProviderConfig) -> WithIssues[pl.DataFrame]:
    del provider_config
    if len(payload.station_products) != 1:
        raise FatalContractError("dk_vanda mapped payload must identify exactly one station-product pair")
    station, product = payload.station_products[0]
    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, DkVandaSourceCoordinates):
        raise FatalContractError("dk_vanda payload requires source coordinates")

    raw_rows = _station_results(payload.content, station)
    rows: list[dict[str, object]] = []
    issues: list[Issue] = []
    for index, raw_row in enumerate(raw_rows):
        timestamp, number = _validated_result_row(raw_row, coordinates.examination_type_sc, "result", index)
        if number is None:
            raise UnsupportedSourceStructureError(f"dk_vanda result {index} result must not be null")
        rows.append(
            {
                "station_id": station,
                "product_id": str(product),
                "time": timestamp,
                "value": number,
                "time_zone": "+00:00",
            }
        )
        reason_issue = _reason_issue(raw_row, station, str(product), timestamp, index)
        if reason_issue is not None:
            issues.append(reason_issue)
    frame = pl.DataFrame(rows, schema=NATIVE_SCHEMA) if rows else pl.DataFrame(schema=NATIVE_SCHEMA)
    return WithIssues(value=frame, issues=tuple(issues))


def _parse_stage(payload: Payload, station: str, coordinates: object) -> ParsedSeries:
    if not isinstance(coordinates, DkVandaSourceCoordinates) or coordinates.examination_type_sc != 25:
        raise FatalContractError("dk_vanda stage payload requires sc-25 source coordinates")

    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    scope = payload.scope or SeriesScope(provider_ids=("dk_vanda",), station_ids=(station,), product_ids=("stage",))
    evidence = f"source-call:{payload.acquisition_id}"

    try:
        parsed_rows = _validated_stage_rows(payload.content, station)
    except UnsupportedSourceStructureError as error:
        reason = str(error)
        outcome = RetrievalOutcome(
            outcome_id=stable_id(payload.acquisition_id, station, "stage", "failed"),
            series_id=None,
            station_id=station,
            product_id="stage",
            window=window,
            status=OutcomeStatus.FAILED,
            reason=reason,
            retrieved_at=retrieved,
        )
        issue = Issue(
            severity="error",
            code="source.unsupported_structure",
            message=reason,
            details={"station_id": station, "product_id": "stage", "outcome_id": outcome.outcome_id},
            provider_id=_PROVIDER_ID,
        )
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), (outcome,), (issue,))

    definitions: list[SourceSeries] = []
    frames: list[pl.DataFrame] = []
    outcomes: list[RetrievalOutcome] = []
    inventories: list[InventorySnapshot] = []
    issues: list[Issue] = []

    for field in STAGE_FIELDS:
        identity = stage_identity(field)
        facts = stage_facts(field)
        series = SourceSeries(
            series_id=stable_id("dk_vanda", station, identity.namespace, field),
            provider_id="dk_vanda",
            station_id=station,
            product_id="stage",
            identity=identity,
            facts=(facts,),
        )
        definitions.append(series)
        if not scope.matches(series):
            continue

        if admission(facts).status != "supported":
            reason = f"Stage field {field!r} is not admitted for numeric conversion"
            outcomes.append(_unsupported_outcome(payload, series, facts, station, window, retrieved, reason))
            inventories.append(
                _unsupported_inventory(payload, series, facts, station, scope, window, retrieved, reason, evidence)
            )
            issues.append(_unsupported_issue(station, series, reason))
            continue

        field_rows: list[dict[str, object]] = [
            {
                "station_id": station,
                "product_id": "stage",
                "time": timestamp,
                "value": result if field == "result" else corrected,
                "time_zone": "+00:00",
                "series_id": series.series_id,
                "facts_id": facts.facts_id,
                "source_unit": facts.source_unit.value,
            }
            for timestamp, result, corrected in parsed_rows
        ]
        # /water-levels never carries reasonSc/reason at all (checked against swagger.json
        # and real retained bytes, step 4 -- see the module docstring): no per-row flag to
        # surface here, unlike temperature's /measurements/results/current.
        frame = (
            pl.DataFrame(field_rows, schema=RowsSchema.polars_schema)
            if field_rows
            else pl.DataFrame(schema=RowsSchema.polars_schema)
        )
        frames.append(frame)
        outcomes.append(
            RetrievalOutcome(
                outcome_id=stable_id(payload.acquisition_id, series.series_id, facts.facts_id, "interval"),
                series_id=series.series_id,
                station_id=station,
                product_id="stage",
                window=window,
                status=OutcomeStatus.SUCCESS if field_rows else OutcomeStatus.EMPTY,
                facts_ids=(facts.facts_id,),
                retrieved_at=retrieved,
                coverage="interval",
            )
        )
        inventories.append(
            InventorySnapshot(
                snapshot_id=stable_id(payload.acquisition_id, series.series_id, "stage-inventory"),
                scope=scope,
                members=(series.series_id,),
                member_facts=((series.series_id, (facts.facts_id,)),),
                completeness=InventoryCompleteness.COMPLETE,
                access="water-levels",
                origin="response",
                acquired_at=retrieved,
                window=window,
                evidence=(evidence,),
            )
        )

    combined = pl.concat(frames) if frames else pl.DataFrame(schema=RowsSchema.polars_schema)
    return ParsedSeries(combined, tuple(definitions), tuple(inventories), tuple(outcomes), tuple(issues))


def _validated_stage_rows(content: bytes, station: str) -> list[tuple[datetime, float, float | None]]:
    """Validate every row's both fields eagerly, before any series is built.

    Raising here (rather than partway through the per-field loop in
    `_parse_stage`) keeps exactly one place that can fail the whole payload,
    so the caller can convert it to one `FAILED` outcome with no concrete
    series identity -- matching `at_ehyd`'s established per-payload
    unsupported-structure handling, instead of a crash reaching the engine.
    """
    raw_rows = _station_results(content, station)
    rows: list[tuple[datetime, float, float | None]] = []
    for index, raw_row in enumerate(raw_rows):
        timestamp, result = _validated_result_row(raw_row, 25, "result", index)
        if result is None:
            raise UnsupportedSourceStructureError(f"dk_vanda stage result {index} field result must not be null")
        _, corrected = _validated_result_row(raw_row, 25, "resultElevationCorrected", index)
        rows.append((timestamp, result, corrected))
    return rows


def _finite(value: float, index: int, field: str) -> float:
    if not isfinite(value):
        raise UnsupportedSourceStructureError(f"dk_vanda stage result {index} field {field} must be finite")
    return value


def _unsupported_outcome(
    payload: Payload,
    series: SourceSeries,
    facts: PhysicalFacts,
    station: str,
    window: SeriesWindow,
    retrieved: datetime | None,
    reason: str,
) -> RetrievalOutcome:
    return RetrievalOutcome(
        outcome_id=stable_id(payload.acquisition_id, series.series_id, facts.facts_id, "unsupported"),
        series_id=series.series_id,
        station_id=station,
        product_id="stage",
        window=window,
        status=OutcomeStatus.UNSUPPORTED,
        facts_ids=(facts.facts_id,),
        reason=reason,
        retrieved_at=retrieved,
    )


def _unsupported_inventory(
    payload: Payload,
    series: SourceSeries,
    facts: PhysicalFacts,
    station: str,
    scope: SeriesScope,
    window: SeriesWindow,
    retrieved: datetime | None,
    reason: str,
    evidence: str,
) -> InventorySnapshot:
    return InventorySnapshot(
        snapshot_id=stable_id(payload.acquisition_id, series.series_id, "stage-unsupported-inventory"),
        scope=scope,
        members=(series.series_id,),
        member_facts=((series.series_id, (facts.facts_id,)),),
        completeness=InventoryCompleteness.INCOMPLETE,
        access="water-levels",
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(evidence,),
        reason=reason,
    )


def _unsupported_issue(station: str, series: SourceSeries, reason: str) -> Issue:
    return Issue(
        severity="warning",
        code="source.unsupported_series",
        message=reason,
        details={"station_id": station, "product_id": "stage", "series_id": series.series_id},
        provider_id=_PROVIDER_ID,
    )


def _station_results(content: bytes, station: str) -> list[dict[str, object]]:
    """Validate the one-measurement-point response envelope and return its rows.

    More than one entry in the top-level array would mean the station has
    more than one measurement point for this examination (`measurementPointNumber`
    is never selected here, so VandA returns all of them); no response checked
    in this port's research shows that shape, so it is treated as an
    unsupported structure rather than guessed at.
    """
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("dk_vanda response is not valid JSON") from error
    if not isinstance(document, list):
        raise UnsupportedSourceStructureError("dk_vanda response must be a JSON array")
    if len(document) == 0:
        return []
    if len(document) > 1:
        raise UnsupportedSourceStructureError(
            "dk_vanda response carries more than one measurement-point entry; unsupported by this port"
        )
    envelope = document[0]
    if not isinstance(envelope, dict):
        raise UnsupportedSourceStructureError("dk_vanda response entry must be a JSON object")
    if envelope.get("stationId") != station:
        raise UnsupportedSourceStructureError("dk_vanda response stationId contradicts the requested station")
    results = envelope.get("results")
    if results is None:
        return []
    if not isinstance(results, list):
        raise UnsupportedSourceStructureError("dk_vanda response results must be a JSON array")
    return cast("list[dict[str, object]]", results)


def _validated_result_row(raw_row: object, expected_sc: int, field: str, index: int) -> tuple[datetime, float | None]:
    if not isinstance(raw_row, dict):
        raise UnsupportedSourceStructureError(f"dk_vanda result {index} must be a JSON object")
    row = cast("dict[str, object]", raw_row)
    sc = row.get("examinationTypeSc")
    if sc != expected_sc:
        raise UnsupportedSourceStructureError(
            f"dk_vanda result {index} examinationTypeSc {sc!r} contradicts requested {expected_sc}"
        )
    label = row.get("measurementDateTime")
    if not isinstance(label, str):
        raise UnsupportedSourceStructureError(f"dk_vanda result {index} measurementDateTime must be a string")
    timestamp = _parse_instant(label, index)
    value = row.get(field)
    if value is None:
        return timestamp, None
    if type(value) not in (int, float):
        raise UnsupportedSourceStructureError(f"dk_vanda result {index} field {field} must be numeric or null")
    number = _finite(float(cast("int | float", value)), index, field)
    return timestamp, number


def _parse_instant(label: str, index: int) -> datetime:
    match = _INSTANT_RE.fullmatch(label)
    if match is None:
        raise UnsupportedSourceStructureError(
            f"dk_vanda result {index} measurementDateTime {label!r} is not a strict UTC instant"
        )
    base, fraction = match.groups()
    microsecond = int(fraction.ljust(6, "0")[:6]) if fraction else 0
    try:
        return datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(microsecond=microsecond)
    except ValueError as error:
        raise UnsupportedSourceStructureError(
            f"dk_vanda result {index} measurementDateTime {label!r} is invalid"
        ) from error


def _reason_issue(
    raw_row: dict[str, object], station: str, product: str, timestamp: datetime, index: int
) -> Issue | None:
    """Surface a non-null published `reasonSc`/`reason` verbatim, never interpreted.

    Only `/measurements/results/current` (temperature) carries these fields;
    `/water-flows` and `/water-levels` never do (checked against swagger.json
    and real retained bytes, step 4), so `raw_row.get(...)` safely no-ops for
    discharge and stage.
    """
    reason_sc = raw_row.get("reasonSc")
    reason = raw_row.get("reason")
    if reason_sc is None and reason is None:
        return None
    return Issue(
        severity="info",
        code="source.reason_flag",
        message=f"VandA reports reasonSc {reason_sc!r} ({reason!r}) for {station} {product} at {timestamp.isoformat()}",
        details={
            "station_id": station,
            "product_id": product,
            "source_reason_sc": reason_sc,
            "source_reason": reason,
            "source_time": timestamp.isoformat(),
            "source_row_index": index,
        },
        provider_id=_PROVIDER_ID,
    )

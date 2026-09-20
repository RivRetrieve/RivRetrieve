"""Decode every identifiable HydAPI version with its own source physical facts.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import IssueSeverity, ProviderId
from rivretrieve._internal.providers.no_nve.config import NoNveSourceCoordinates
from rivretrieve._internal.providers.no_nve.issue_codes import NoNveObservationIssueCodes
from rivretrieve._internal.providers.no_nve.series import NVE_EVIDENCE, describe_series
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    admission,
    stable_id,
)

PROVIDER_ID = ProviderId("no_nve")
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_SOURCE_ZONE = "+00:00"


class SourceStructureError(ValueError):
    """A source series cannot be decoded faithfully."""


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    if len(payload.station_products) != 1:
        raise FatalContractError("no_nve payload must contain exactly one station-product pair")
    station, product = payload.station_products[0]
    if product not in provider_config.products:
        raise FatalContractError("no_nve payload product is undeclared")
    coordinates = payload.source_coordinates.value
    configured = provider_config.products[product].coordinates.value
    if not isinstance(coordinates, NoNveSourceCoordinates) or not isinstance(configured, NoNveSourceCoordinates):
        raise FatalContractError("no_nve payload source coordinates have invalid type")
    if (coordinates.parameter, coordinates.resolution_time) != (configured.parameter, configured.resolution_time):
        raise FatalContractError("no_nve payload coordinates contradict product request")
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    retrieved = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    definitions = []
    rows = []
    outcomes = []
    issues = []

    def unsupported(reason, definition=None):
        series_id = definition.series_id if definition else None
        facts_ids = tuple(f.facts_id for f in definition.facts) if definition else ()
        outcomes.append(
            RetrievalOutcome(
                outcome_id=stable_id(
                    hashlib.sha256(payload.content).hexdigest(),
                    str(payload.origin.retrieved_at),
                    station,
                    product,
                    series_id,
                    reason,
                    str(window),
                ),
                series_id=series_id,
                station_id=station,
                product_id=product,
                window=window,
                status=OutcomeStatus.UNSUPPORTED,
                facts_ids=facts_ids,
                reason=reason,
                retrieved_at=retrieved,
            )
        )
        issues.append(
            Issue(
                severity="warning",
                code="source.unsupported_series",
                message=reason,
                details={"station_id": station, "product_id": product, "series_id": series_id},
                provider_id=PROVIDER_ID,
            )
        )

    try:
        document = json.loads(payload.content)
        if not isinstance(document, dict) or not isinstance(document.get("data"), list):
            raise SourceStructureError("HydAPI response lacks data series array")
        data = document["data"]
    except (ValueError, UnicodeDecodeError) as exc:
        unsupported("HydAPI response is unreadable: " + str(exc))
        data = []
    for raw in data:
        definition = None
        try:
            if not isinstance(raw, dict):
                raise SourceStructureError("HydAPI series is not an object")
            if raw.get("stationId") != station:
                raise SourceStructureError("HydAPI returned station differs from requested station")
            if raw.get("parameter") != int(coordinates.parameter):
                raise SourceStructureError("HydAPI returned parameter differs from requested parameter")
            version = raw.get("serieVersionNo")
            if type(version) is not int:
                raise SourceStructureError("HydAPI series version identifier is absent or malformed")
            if coordinates.version_number is not None and version != coordinates.version_number:
                raise SourceStructureError("HydAPI returned version differs from explicitly requested version")
            method = raw.get("method")
            if method is not None and not isinstance(method, str):
                raise SourceStructureError("HydAPI series method is malformed")
            unit = raw.get("unit")
            if unit == "" or (unit is not None and not isinstance(unit, str)):
                definition = describe_series(
                    station, int(coordinates.parameter), version, int(coordinates.resolution_time), method, None
                )
                definitions.append(definition)
                raise SourceStructureError(
                    "HydAPI source unit label is an empty string"
                    if unit == ""
                    else "HydAPI source unit label is malformed"
                )
            definition = describe_series(
                station, int(coordinates.parameter), version, int(coordinates.resolution_time), method, unit
            )
            if any(s.series_id == definition.series_id for s in definitions):
                raise SourceStructureError(
                    "HydAPI response repeats a version identity without an established segment distinction"
                )
            definitions.append(definition)
            decision = admission(definition.facts[0])
            if decision.status != "supported":
                raise SourceStructureError(decision.reason or "HydAPI series is below admission")
            observations = _observations(raw)
            if type(raw.get("observationCount")) is not int or raw["observationCount"] != len(observations):
                raise SourceStructureError("HydAPI observationCount differs from its observations")
            native = []
            quality_codes = {}
            correction_codes = {}
            for index, observation in enumerate(observations):
                if not isinstance(observation, dict):
                    raise SourceStructureError("HydAPI observation is not an object")
                observation = cast("dict[str, object]", observation)
                label = _time(observation, index)
                quality = _code(observation, "quality", index)
                correction = _code(observation, "correction", index)
                quality_codes.setdefault(quality, []).append(label.isoformat())
                correction_codes.setdefault(correction, []).append(label.isoformat())
                facts = definition.facts[0]
                native.append(
                    {
                        "station_id": station,
                        "product_id": product,
                        "time": label,
                        "value": _value(observation, index),
                        "time_zone": _SOURCE_ZONE,
                        "series_id": definition.series_id,
                        "facts_id": facts.facts_id,
                        "source_unit": unit,
                    }
                )
            rows.extend(native)
            outcomes.append(
                RetrievalOutcome(
                    outcome_id=stable_id(
                        hashlib.sha256(payload.content).hexdigest(),
                        str(payload.origin.retrieved_at),
                        definition.series_id,
                        str(window),
                        "response",
                    ),
                    series_id=definition.series_id,
                    station_id=station,
                    product_id=product,
                    window=window,
                    status=OutcomeStatus.SUCCESS if native else OutcomeStatus.EMPTY,
                    facts_ids=(definition.facts[0].facts_id,),
                    retrieved_at=retrieved,
                )
            )
            issues.extend(
                _code_issues(NoNveObservationIssueCodes.SOURCE_QUALITY_CODE, "quality", quality_codes, station)
            )
            issues.extend(
                _code_issues(NoNveObservationIssueCodes.SOURCE_CORRECTION_CODE, "correction", correction_codes, station)
            )
        except SourceStructureError as exc:
            unsupported(str(exc), definition)
    if not data and not outcomes:
        reason = "HydAPI response contains no concrete series identity; inventory remains unresolved"
        outcomes.append(
            RetrievalOutcome(
                outcome_id=stable_id(
                    hashlib.sha256(payload.content).hexdigest(),
                    str(payload.origin.retrieved_at),
                    station,
                    product,
                    str(window),
                    reason,
                ),
                series_id=None,
                station_id=station,
                product_id=product,
                window=window,
                status=OutcomeStatus.UNRESOLVED,
                reason=reason,
                retrieved_at=retrieved,
            )
        )
    scope = payload.scope or SeriesScope(provider_ids=("no_nve",), station_ids=(station,), product_ids=(product,))
    inventory = InventorySnapshot(
        snapshot_id=stable_id(
            hashlib.sha256(payload.content).hexdigest(),
            str(payload.origin.retrieved_at),
            "no_nve",
            station,
            product,
            str(window),
            str(retrieved),
            str(coordinates.version_number),
        ),
        scope=scope,
        members=tuple(s.series_id for s in definitions),
        completeness=InventoryCompleteness.INCOMPLETE,
        access="HydAPI explicit version"
        if coordinates.version_number is not None
        else "HydAPI source-selected version",
        origin="response",
        acquired_at=retrieved,
        window=window,
        evidence=(NVE_EVIDENCE,),
        reason="An observation response establishes its requested versions, not a complete current or historical version inventory",
    )
    return ParsedSeries(
        pl.DataFrame(rows, schema=RowsSchema.polars_schema),
        tuple(definitions),
        (inventory,),
        tuple(outcomes),
        tuple(issues),
    )


def _observations(series: dict[str, object]) -> list[object]:
    observations = series.get("observations")
    if not isinstance(observations, list):
        raise SourceStructureError("no_nve series observations must be a list")
    return cast("list[object]", observations)


def _time(observation: dict[str, object], index: int) -> datetime:
    value = observation.get("time")
    if not isinstance(value, str):
        raise SourceStructureError(f"no_nve observation {index} time must be a string")
    try:
        return datetime.strptime(value, _TIME_FORMAT)
    except ValueError as error:
        raise SourceStructureError(f"no_nve observation {index} time must be a strict UTC instant label") from error


def _value(observation: dict[str, object], index: int) -> float | None:
    if "value" not in observation:
        raise SourceStructureError(f"no_nve observation {index} is missing its value")
    value = observation["value"]
    if value is None:
        return None
    if type(value) not in (int, float):
        raise SourceStructureError(f"no_nve observation {index} value must be numeric or null")
    try:
        number = float(cast("int | float", value))
    except OverflowError as error:
        raise SourceStructureError(
            f"no_nve observation {index} value is not representable as a finite number"
        ) from error
    if not isfinite(number):
        raise SourceStructureError(f"no_nve observation {index} value must be finite")
    return number


def _code(observation: dict[str, object], name: str, index: int) -> int:
    value = observation.get(name)
    if type(value) is not int:
        raise SourceStructureError(f"no_nve observation {index} {name} must be an integer source code")
    return value


def _code_issues(
    code: NoNveObservationIssueCodes,
    name: str,
    labels_by_code: dict[int, list[str]],
    station_id: str,
) -> list[Issue]:
    return [
        _issue(
            code,
            "info",
            f"no_nve published source {name} code {source_code} without RivRetrieve interpretation",
            {
                "station_id": station_id,
                f"source_{name}_code": source_code,
                "count": len(labels),
                "first_source_time": labels[0],
                "last_source_time": labels[-1],
            },
        )
        for source_code, labels in sorted(labels_by_code.items())
    ]


def _issue(
    code: NoNveObservationIssueCodes,
    severity: IssueSeverity,
    message: str,
    details: dict[str, object],
) -> Issue:
    return Issue(
        severity=severity,
        code=code,
        message=message,
        details=details,
        provider_id=PROVIDER_ID,
    )

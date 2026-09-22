"""Decode modern USGS features without conflating record and series identities.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime

import polars as pl
from pydantic import ValidationError

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema, ZoneValue
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.usgs_nwis.config import UsgsNwisSourceCoordinates
from rivretrieve._internal.providers.usgs_nwis.metadata import NAMESPACE, source_series
from rivretrieve._internal.source_series import (
    OutcomeStatus,
    ParsedSeries,
    RetrievalOutcome,
    SeriesWindow,
    SourceSeries,
    stable_id,
    validate_series_rows,
)

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIMESTAMP = re.compile(
    r"(?P<wall>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?)(?P<zone>Z|[+-][0-9]{2}:[0-9]{2})"
)
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?")


def parse_time_label(value: object, daily: bool) -> tuple[datetime, str]:
    if not isinstance(value, str):
        raise ValueError("Observation time must be a string")
    if daily:
        if _DATE.fullmatch(value) is None:
            raise ValueError("Daily observation must publish a date-only label")
        return datetime.fromisoformat(value), "unknown"
    match = _TIMESTAMP.fullmatch(value)
    if match is None:
        raise ValueError("Continuous observation must publish an offset-bearing timestamp")
    zone = ZoneValue("+00:00" if match["zone"] == "Z" else match["zone"])
    return datetime.fromisoformat(match["wall"]), zone.value


def _value(properties: Mapping[str, object]) -> float | None:
    if "value" not in properties:
        raise ValueError("Missing mandatory observation value")
    value = properties["value"]
    if value is None:
        return None
    if not isinstance(value, str) or _NUMBER.fullmatch(value) is None:
        raise ValueError("Observation value must be a decimal string or present null")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Observation value is outside the finite numeric range")
    return number


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Parse one exact publisher page; acquisition establishes chain completeness."""
    if len(payload.station_products) != 1:
        raise FatalContractError("USGS payload requires exactly one station-product pair")
    station, product = payload.station_products[0]
    coordinates = payload.source_coordinates.value
    try:
        configured = provider_config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"USGS product is absent from provider configuration: {product}") from error
    if not isinstance(coordinates, UsgsNwisSourceCoordinates) or not isinstance(configured, UsgsNwisSourceCoordinates):
        raise FatalContractError("USGS payload has invalid source coordinates")
    if (coordinates.endpoint, coordinates.parameter_code, coordinates.statistic_code) != (
        configured.endpoint,
        configured.parameter_code,
        configured.statistic_code,
    ):
        raise FatalContractError("USGS payload coordinates contradict the configured route")
    location = coordinates.monitoring_location_id
    if not location:
        raise FatalContractError("USGS payload lacks its resolved source monitoring location")
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    acquired = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    capture = stable_id(
        hashlib.sha256(payload.content).hexdigest(),
        acquired.isoformat() if acquired is not None else None,
        window.model_dump_json(),
    )
    definitions: dict[str, SourceSeries] = {}
    rows: dict[tuple[str, datetime], dict[str, object]] = {}
    failures: dict[str | None, list[str]] = {}
    known = {item.series_id: item for item in payload.known_series}
    try:
        document = json.loads(payload.content)
        if (
            not isinstance(document, dict)
            or document.get("type") != "FeatureCollection"
            or not isinstance(document.get("features"), list)
        ):
            raise ValueError("Expected a GeoJSON FeatureCollection with a features array")
        features = document["features"]
    except (ValueError, UnicodeDecodeError) as error:
        failures[None] = [f"Unreadable modern USGS response: {error}"]
        features = []
    for feature in features:
        sid = None
        try:
            if (
                not isinstance(feature, dict)
                or feature.get("type") != "Feature"
                or not isinstance(feature.get("properties"), dict)
            ):
                raise ValueError("Expected a GeoJSON Feature with properties")
            properties = feature["properties"]
            identifier = properties.get("time_series_id")
            if isinstance(identifier, str) and identifier.strip():
                candidate = stable_id("usgs_nwis", station, NAMESPACE, identifier)
                sid = candidate
            series = source_series(
                properties,
                station,
                product,
                coordinates,
                metadata=False,
                monitoring_location_id=location,
                known_series=payload.known_series,
            )
            sid = series.series_id
            prior = definitions.get(sid)
            if prior is not None:
                facts = {fact.facts_id: fact for fact in prior.facts}
                for fact in series.facts:
                    if fact.facts_id in facts and fact != facts[fact.facts_id]:
                        raise FatalContractError("USGS fact identity reinterprets physical facts")
                    facts[fact.facts_id] = fact
                series = series.model_copy(update={"facts": tuple(facts.values())})
            definitions[sid] = series
            if payload.scope is not None:
                identity_scope = payload.scope.model_copy(update={"predicates": ()})
                if not identity_scope.matches(series):
                    raise ValueError("Returned series identity contradicts the requested selector")
            current_facts = source_series(
                properties, station, product, coordinates, metadata=False, monitoring_location_id=location
            ).facts[0]
            stamp, zone = parse_time_label(properties.get("time"), coordinates.endpoint == "daily")
            number = _value(properties)
            qualifier = properties.get("qualifier")
            if (
                qualifier is not None
                and not isinstance(qualifier, str)
                and not (isinstance(qualifier, list) and all(isinstance(item, str) for item in qualifier))
            ):
                raise ValueError("Qualifier must be a source string, string array or null")
            approval = properties.get("approval_status")
            if approval is not None and not isinstance(approval, str):
                raise ValueError("Approval status must be a source string or null")
            row: dict[str, object] = {
                "station_id": station,
                "product_id": product,
                "time": stamp,
                "value": number,
                "time_zone": zone,
                "series_id": sid,
                "facts_id": current_facts.facts_id,
                "source_unit": current_facts.source_unit.value,
            }
            identity_time = stamp if zone == "unknown" else datetime.fromisoformat(f"{stamp.isoformat()}{zone}")
            key = (sid, identity_time)
            if key in rows and rows[key] != row:
                raise ValueError("Conflicting observations for the same series and time")
            rows[key] = row
        except ValidationError as error:
            raise FatalContractError("Invalid internal USGS source-series definition") from error
        except (KeyError, TypeError, ValueError) as error:
            if sid is not None and sid in known:
                definitions.setdefault(sid, known[sid])
            failures.setdefault(sid, []).append(str(error))
    outcomes = []
    issues = []
    for sid in dict.fromkeys((*definitions, *failures)):
        definition = definitions.get(sid) if sid is not None else None
        reasons = failures.get(sid)
        status = OutcomeStatus.UNSUPPORTED if reasons else OutcomeStatus.SUCCESS
        reason = "; ".join(sorted(set(reasons))) if reasons else None
        outcomes.append(
            RetrievalOutcome(
                outcome_id=stable_id(capture, sid, status, reason),
                series_id=sid,
                station_id=station,
                product_id=product,
                window=window,
                status=status,
                facts_ids=tuple(f.facts_id for f in definition.facts) if definition else (),
                reason=reason,
                retrieved_at=acquired,
            )
        )
        if reason:
            issues.append(
                Issue(
                    severity="warning",
                    code="unsupported_source_series",
                    message=reason,
                    provider_id=ProviderId("usgs_nwis"),
                    details={"station_id": station, "product_id": product, "series_id": sid},
                )
            )
    # Invalid rows cannot establish success for that concrete series. Valid siblings survive.
    frame = pl.DataFrame(
        [row for (sid, _), row in rows.items() if sid not in failures], schema=RowsSchema.polars_schema
    )
    validate_series_rows(frame, tuple(definitions.values()))
    return ParsedSeries(frame, tuple(definitions.values()), (), tuple(outcomes), tuple(issues))

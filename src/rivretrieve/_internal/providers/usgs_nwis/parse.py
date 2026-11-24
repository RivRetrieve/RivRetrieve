"""Decode modern USGS features without conflating record and series identities.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, tzinfo
from functools import lru_cache
from typing import Any

import polars as pl
from pydantic import ValidationError

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema, ZoneValue
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.usgs_nwis.annotations import (
    USGS_NWIS_CONTINUOUS_SCHEMA,
    USGS_NWIS_DAILY_SCHEMA,
)
from rivretrieve._internal.providers.usgs_nwis.config import UsgsNwisSourceCoordinates
from rivretrieve._internal.providers.usgs_nwis.metadata import NAMESPACE, source_series
from rivretrieve._internal.source_annotations import (
    OBSERVATION_STRUCTURAL_SCHEMA,
    AnnotationBundle,
    ObservationAnnotationTable,
)
from rivretrieve._internal.source_series import (
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
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
_MISSING = object()


@dataclass(frozen=True, slots=True)
class UsgsPageInterpretation:
    """Single-pass decoded USGS page together with acquisition pagination details."""

    parsed: ParsedSeries
    observation_keys: frozenset[tuple[str, datetime]]
    next_href: str | None = None
    document_error: str | None = None
    links_error: str | None = None


@lru_cache(maxsize=64)
def _validated_offset(raw_zone: str) -> str:
    return ZoneValue("+00:00" if raw_zone == "Z" else raw_zone).value


@lru_cache(maxsize=64)
def _zone_tzinfo(zone: str) -> tzinfo:
    tz = datetime.fromisoformat(f"2000-01-01T00:00:00{zone}").tzinfo
    assert tz is not None
    return tz


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
    zone = _validated_offset(match["zone"])
    return datetime.fromisoformat(match["wall"]), zone


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


def _next_href_from_document(document: Mapping[str, Any]) -> str | None:
    links = document.get("links")
    if not isinstance(links, list) or any(
        not isinstance(link, dict) or not isinstance(link.get("rel"), str) for link in links
    ):
        raise ValueError("USGS observation page has malformed links")
    following = [link for link in links if link["rel"] == "next"]
    if not following:
        return None
    if len(following) != 1 or not isinstance(following[0].get("href"), str):
        raise ValueError("USGS observation page requires one valid next link")
    return following[0]["href"]


def interpret_page(
    payload: Payload,
    provider_config: ProviderConfig,
    *,
    collect_acquisition_details: bool = True,
) -> UsgsPageInterpretation:
    """Parse one exact publisher page once, optionally extracting pagination details."""
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
        axis=payload.acquisition_axis,
    )
    acquired = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    capture = stable_id(
        payload.acquisition_id,
        hashlib.sha256(payload.content).hexdigest(),
        acquired.isoformat() if acquired is not None else None,
        window.model_dump_json(),
    )
    definitions: dict[str, SourceSeries] = {}
    rows: dict[tuple[str, datetime], dict[str, object]] = {}
    ann_rows: dict[tuple[str, datetime], dict[str, object]] = {}
    daily = coordinates.endpoint == "daily"
    schema = USGS_NWIS_DAILY_SCHEMA if daily else USGS_NWIS_CONTINUOUS_SCHEMA
    failures: dict[str | None, list[str]] = {}
    known: dict[str, SourceSeries] = {}
    for item in payload.known_series:
        known.setdefault(item.series_id, item)

    raw_id_to_sid: dict[str, str] = {}
    series_cache: dict[tuple[object, ...], SourceSeries] = {}
    facts_cache: dict[tuple[str, str | None, str, bool], PhysicalFacts] = {}
    seen_series_facts: dict[str, dict[str, PhysicalFacts]] = {}
    identity_scope = payload.scope.model_copy(update={"predicates": ()}) if payload.scope is not None else None
    scope_matched: set[str] = set()
    observation_keys: set[tuple[str, datetime]] = set()
    next_href: str | None = None
    document_error: str | None = None
    links_error: str | None = None

    features: list[Any]
    try:
        document = json.loads(payload.content)
    except (ValueError, UnicodeDecodeError) as error:
        failures[None] = [f"Unreadable modern USGS response: {error}"]
        if collect_acquisition_details:
            document_error = "USGS observation response is not valid JSON"
        features = []
    else:
        if (
            not isinstance(document, dict)
            or document.get("type") != "FeatureCollection"
            or not isinstance(document.get("features"), list)
        ):
            failures[None] = [
                "Unreadable modern USGS response: Expected a GeoJSON FeatureCollection with a features array"
            ]
            if collect_acquisition_details:
                document_error = "USGS observation response must be a FeatureCollection"
            features = []
        else:
            features = document["features"]
            if collect_acquisition_details:
                try:
                    next_href = _next_href_from_document(document)
                except ValueError as error:
                    links_error = str(error)

    for feature in features:
        sid = None
        recorded_key = False
        try:
            if (
                not isinstance(feature, dict)
                or feature.get("type") != "Feature"
                or not isinstance(feature.get("properties"), dict)
            ):
                raise ValueError("Expected a GeoJSON Feature with properties")
            properties = feature["properties"]
            raw_identifier = properties.get("time_series_id")
            if isinstance(raw_identifier, str) and raw_identifier.strip():
                sid = raw_id_to_sid.get(raw_identifier)
                if sid is None:
                    sid = stable_id("usgs_nwis", station, NAMESPACE, raw_identifier)
                    raw_id_to_sid[raw_identifier] = sid

            raw_loc = properties.get("monitoring_location_id")
            raw_param = properties.get("parameter_code")
            raw_stat = properties.get("statistic_id", _MISSING)
            raw_unit = properties.get("unit_of_measure")
            cache_key: tuple[object, ...] | None = None
            if (
                isinstance(raw_identifier, str)
                and isinstance(raw_loc, str)
                and isinstance(raw_param, str)
                and (raw_stat is _MISSING or isinstance(raw_stat, str) or raw_stat is None)
                and isinstance(raw_unit, str)
            ):
                cache_key = (raw_identifier, raw_loc, raw_param, raw_stat, raw_unit)

            series = series_cache.get(cache_key) if cache_key is not None else None
            if series is None:
                series = source_series(
                    properties,
                    station,
                    product,
                    coordinates,
                    metadata=False,
                    monitoring_location_id=location,
                    known_series=payload.known_series,
                    known_by_id=known,
                    facts_cache=facts_cache,
                )
                if cache_key is not None:
                    series_cache[cache_key] = series

            sid = series.series_id
            current_facts = series.facts[0]
            prior = definitions.get(sid)
            if prior is None:
                definitions[sid] = series
                seen_series_facts[sid] = {current_facts.facts_id: current_facts}
            else:
                facts_map = seen_series_facts.setdefault(sid, {f.facts_id: f for f in prior.facts})
                existing_fact = facts_map.get(current_facts.facts_id)
                if existing_fact is None:
                    facts_map[current_facts.facts_id] = current_facts
                    definitions[sid] = prior.model_copy(update={"facts": (*prior.facts, current_facts)})
                elif existing_fact != current_facts:
                    raise FatalContractError("USGS fact identity reinterprets physical facts")

            if identity_scope is not None and sid not in scope_matched:
                if not identity_scope.matches(definitions[sid]):
                    raise ValueError("Returned series identity contradicts the requested selector")
                scope_matched.add(sid)

            stamp, zone = parse_time_label(properties.get("time"), daily)
            identity_time = stamp if zone == "unknown" else stamp.replace(tzinfo=_zone_tzinfo(zone))
            if collect_acquisition_details and isinstance(raw_identifier, str) and raw_identifier:
                observation_keys.add((raw_identifier, identity_time))
                recorded_key = True

            number = _value(properties)
            qualifier = properties.get("qualifier")
            if qualifier is None:
                norm_qualifier: list[str] | None = None
            elif isinstance(qualifier, str):
                norm_qualifier = [qualifier]
            elif isinstance(qualifier, list) and all(isinstance(item, str) for item in qualifier):
                norm_qualifier = list(qualifier)
            else:
                raise ValueError("Qualifier must be a source string, string array or null")
            approval = properties.get("approval_status")
            if approval is not None and not isinstance(approval, str):
                raise ValueError("Approval status must be a source string or null")
            method_category: object = None
            if not daily:
                method_category = properties.get("method_category")
                if method_category is not None and not isinstance(method_category, str):
                    raise ValueError("Method category must be a source string or null")
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
            ann_row: dict[str, object] = {
                "series_id": sid,
                "facts_id": current_facts.facts_id,
                "station_id": station,
                "product_id": str(product),
                "time": stamp,
                "time_zone": zone,
                "measured": True,
                "approval_status": approval,
                "qualifier": norm_qualifier,
            }
            if not daily:
                ann_row["method_category"] = method_category
            key = (sid, identity_time)
            if key in rows and (rows[key] != row or ann_rows[key] != ann_row):
                raise ValueError("Conflicting observations for the same series and time")
            rows[key] = row
            ann_rows[key] = ann_row
        except ValidationError as error:
            raise FatalContractError("Invalid internal USGS source-series definition") from error
        except (KeyError, TypeError, ValueError) as error:
            if (
                collect_acquisition_details
                and not recorded_key
                and isinstance(feature, dict)
                and isinstance(feature.get("properties"), dict)
            ):
                err_props = feature["properties"]
                err_id = err_props.get("time_series_id")
                if isinstance(err_id, str) and err_id:
                    try:
                        err_stamp, err_zone = parse_time_label(err_props.get("time"), daily)
                    except ValueError:
                        pass
                    else:
                        observation_keys.add(
                            (
                                err_id,
                                err_stamp
                                if err_zone == "unknown"
                                else err_stamp.replace(tzinfo=_zone_tzinfo(err_zone)),
                            )
                        )
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
                calls=tuple(item.attempt_id for item in payload.attempt_traces) or (payload.acquisition_id,),
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
    surviving_rows: list[dict[str, object]] = []
    surviving_ann: list[dict[str, object]] = []
    for row_key, item_row in rows.items():
        if row_key[0] not in failures:
            surviving_rows.append(item_row)
            surviving_ann.append(ann_rows[row_key])
    frame = pl.DataFrame(surviving_rows, schema=RowsSchema.polars_schema)
    validate_series_rows(frame, tuple(definitions.values()))
    if surviving_ann:
        ann_frame = pl.DataFrame(
            surviving_ann,
            schema={**OBSERVATION_STRUCTURAL_SCHEMA, **schema.polars_schema()},
        )
        ann_table = ObservationAnnotationTable.from_rows(
            schema=schema,
            rows=ann_frame,
            measurement_indices=list(range(frame.height)),
        )
        annotations = AnnotationBundle(observation_tables={schema.schema_id: ann_table})
    else:
        annotations = AnnotationBundle.empty()
    parsed = ParsedSeries(
        frame, tuple(definitions.values()), (), tuple(outcomes), tuple(issues), annotations=annotations
    )
    return UsgsPageInterpretation(
        parsed=parsed,
        observation_keys=frozenset(observation_keys),
        next_href=next_href,
        document_error=document_error,
        links_error=links_error,
    )


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Parse one exact publisher page; acquisition establishes chain completeness."""
    return interpret_page(payload, provider_config, collect_acquisition_details=False).parsed

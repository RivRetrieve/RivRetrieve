"""Decode USGS response-owned method identities and physical evidence.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, time
from typing import Any

import polars as pl
from pydantic import ValidationError

from rivretrieve._internal.engine import Daily, Instant, Payload, ProviderConfig, RowsSchema, ZoneValue
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.usgs_nwis.config import UsgsNwisSourceCoordinates
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    EvidenceState,
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    admission,
    known,
    stable_id,
    validate_series_rows,
)

_WALL_CLOCK_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?"
_OFFSET_TIMESTAMP_PATTERN = re.compile(rf"(?P<wall_clock>{_WALL_CLOCK_PATTERN})(?P<offset>Z|[+-][0-9]{{2}}:[0-9]{{2}})")
_NAIVE_TIMESTAMP_PATTERN = re.compile(rf"(?P<wall_clock>{_WALL_CLOCK_PATTERN})")
_EVIDENCE = "USGS Water Services WaterML 1.1 response"
_IV_DEFINITION = "https://waterservices.usgs.gov/docs/instantaneous-values/instantaneous-values-details/"


def _method_id(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return str(int(value))
    return None


def _method_identity(method: dict[str, Any]) -> tuple[str, str]:
    identifier = _method_id(method.get("methodID"))
    if identifier is not None:
        return "methodID", identifier
    code = method.get("methodCode")
    if "methodID" not in method and isinstance(code, str) and code.strip():
        return "methodCode", code
    raise ValueError("Missing or malformed published method identity")


def _no_data_value(variable: dict[str, Any]) -> tuple[float | None, str | None]:
    """Validate a declared source marker; absence does not define a default marker."""
    if "noDataValue" not in variable:
        return None, None
    raw = variable["noDataValue"]
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None, "Declared noDataValue must be a finite non-boolean number"
    try:
        value = float(raw)
    except OverflowError:
        return None, "Declared noDataValue is outside the supported finite numeric range"
    if not math.isfinite(value):
        return None, "Declared noDataValue must be finite"
    return value, None


def _facts(variable: dict[str, Any], coordinates: UsgsNwisSourceCoordinates) -> PhysicalFacts:
    parameter = variable.get("variableCode", [])
    code = parameter[0].get("value") if len(parameter) == 1 else None
    quantity = {"00060": "discharge", "00065": "stage"}.get(code) if isinstance(code, str) else None
    raw_unit = variable.get("unit", {}).get("unitCode")
    unit = (
        known(raw_unit, _EVIDENCE)
        if isinstance(raw_unit, str) and raw_unit
        else EvidenceFact(state=EvidenceState.SOURCE_SILENT)
    )
    daily = coordinates.endpoint == "dv"
    statistics = [
        v.get("optionCode") for v in variable.get("options", {}).get("option", []) if v.get("name") == "Statistic"
    ]
    statistic = {"00003": "mean", "00001": "max", "00002": "min"}.get(statistics[0]) if len(statistics) == 1 else None
    if not daily and statistics in ([], ["00000"]):
        statistic = "instantaneous"
    frequency = "daily" if daily else None
    temporal_support = "interval" if daily else "instantaneous" if statistic == "instantaneous" else None
    return PhysicalFacts(
        facts_id=stable_id("usgs_nwis", code, raw_unit, coordinates.endpoint, statistic, frequency, temporal_support),
        quantity=known(quantity, _EVIDENCE) if quantity else EvidenceFact(),
        source_unit=unit,
        normalized_unit=raw_unit if raw_unit in ("ft3/s", "ft", "m3/s", "m") else None,
        frequency=known(frequency, "USGS daily values definition") if frequency else EvidenceFact(),
        statistic=known(statistic, _IV_DEFINITION if statistic == "instantaneous" else _EVIDENCE)
        if statistic
        else EvidenceFact(),
        temporal_support=known(temporal_support, "USGS daily values definition" if daily else _IV_DEFINITION)
        if temporal_support
        else EvidenceFact(),
        timestamp_anchor=known("00:00", "USGS daily value label") if daily else EvidenceFact(),
        clipping_axis=ClippingAxis.CALENDAR_DATE if daily else ClippingAxis.SOURCE_TIMESTAMP,
        label_time="00:00" if daily else None,
    )


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    if len(payload.station_products) != 1:
        raise FatalContractError("usgs_nwis payload must contain exactly one station-product pair")
    station_id, product_id = payload.station_products[0]
    try:
        product = provider_config.products[product_id]
    except KeyError as error:
        raise FatalContractError(f"usgs_nwis product is absent from provider config: {product_id}") from error
    coordinates = product.coordinates.value
    if not isinstance(coordinates, UsgsNwisSourceCoordinates) or not isinstance(product.semantics, Daily | Instant):
        raise FatalContractError("Invalid USGS product contract")
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
    )
    scope = SeriesScope(provider_ids=("usgs_nwis",), station_ids=(station_id,), product_ids=(product_id,))
    acquired = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    capture_id = stable_id(hashlib.sha256(payload.content).hexdigest(), acquired.isoformat() if acquired else None)
    rows: list[dict[str, object]] = []
    definitions: dict[str, SourceSeries] = {}
    outcomes: dict[tuple[str | None, str | None], RetrievalOutcome] = {}
    outcome_reasons: dict[tuple[str | None, str | None], set[str]] = {}
    issues: list[Issue] = []
    members: set[str] = set()

    def outcome(
        series: SourceSeries | None,
        status: OutcomeStatus,
        reason: str | None = None,
        *,
        facts_id: str | None = None,
    ) -> None:
        # Blocks contribute native rows, not separate claims over the same window.
        # One unsupported block prevents full-window coverage for its own fact segment.
        sid = series.series_id if series else None
        if (sid is None) != (facts_id is None):
            raise FatalContractError("A concrete USGS outcome must identify its assessed physical facts")
        key = (sid, facts_id)
        reasons = outcome_reasons.setdefault(key, set())
        if reason:
            reasons.add(reason)
        previous = outcomes.get(key)
        if previous is not None:
            statuses = {previous.status, status}
            if OutcomeStatus.UNSUPPORTED in statuses:
                status = OutcomeStatus.UNSUPPORTED
            elif OutcomeStatus.UNRESOLVED in statuses:
                status = OutcomeStatus.UNRESOLVED
            elif OutcomeStatus.SUCCESS in statuses:
                status = OutcomeStatus.SUCCESS
        combined_reason = "; ".join(sorted(reasons)) if reasons else None
        outcomes[key] = RetrievalOutcome(
            outcome_id=stable_id(capture_id, sid, facts_id, status, combined_reason, window.model_dump_json()),
            series_id=sid,
            station_id=station_id,
            product_id=product_id,
            window=window,
            status=status,
            facts_ids=(facts_id,) if facts_id is not None else (),
            reason=combined_reason,
            retrieved_at=acquired,
        )
        if reason:
            issues.append(
                Issue(
                    severity="warning",
                    code="unsupported_source_series",
                    message=reason,
                    provider_id=ProviderId("usgs_nwis"),
                    details={"station_id": station_id, "product_id": product_id, "series_id": sid},
                )
            )

    try:
        document = json.loads(payload.content)
        source = document["value"]
        time_series = source["timeSeries"]
        if not isinstance(time_series, list):
            raise ValueError("timeSeries is not a list")
    except (ValueError, KeyError, TypeError) as error:
        source = {}
        time_series = []
        outcome(None, OutcomeStatus.UNSUPPORTED, f"Unreadable USGS response: {error}")
    for item in time_series:
        try:
            variable = item["variable"]
            facts = _facts(variable, coordinates)
            sites = [s.get("value") for s in item["sourceInfo"]["siteCode"]]
            parameters = [v.get("value") for v in variable["variableCode"]]
            statistics = [
                v.get("optionCode")
                for v in variable.get("options", {}).get("option", [])
                if v.get("name") == "Statistic"
            ]
            mismatch = None
            if sites != [station_id] or parameters != [coordinates.parameter_code]:
                mismatch = "Returned station or parameter contradicts requested coordinates"
            if coordinates.statistic_code is not None and statistics != [coordinates.statistic_code]:
                mismatch = "Returned statistic contradicts requested coordinates"
            if coordinates.endpoint == "iv" and statistics not in ([], ["00000"]):
                mismatch = "Returned statistic contradicts the instantaneous-values service"
            no_data_value, sentinel_reason = _no_data_value(variable)
            decision = admission(facts)
            reason = mismatch or decision.reason or sentinel_reason
            blocks = item["values"]
            if not isinstance(blocks, list):
                raise ValueError("values is not a list")
        except ValidationError as error:
            raise FatalContractError("Invalid internal USGS physical facts") from error
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            outcome(None, OutcomeStatus.UNSUPPORTED, f"Unsupported USGS timeSeries structure: {error}")
            continue
        for block in blocks:
            try:
                methods = block.get("method", [])
                method_map = {_method_identity(m): m.get("methodDescription") for m in methods}
                if not method_map or len(method_map) != len(methods):
                    raise ValueError("Missing or ambiguous published method identity")
                if any(
                    description is not None and not isinstance(description, str) for description in method_map.values()
                ):
                    raise ValueError("Published method description is not a string")
                entries = block["value"]
                if not isinstance(entries, list):
                    raise ValueError("Observation values are not a list")
                grouped: dict[tuple[str, str], list[dict[str, Any]]] = {identity: [] for identity in method_map}
                ambiguous = False
                for entry in entries:
                    matches = [
                        _method_identity(method)
                        for method in methods
                        if (
                            "methodID" not in entry
                            or (
                                _method_id(entry["methodID"]) is not None
                                and _method_id(entry["methodID"]) == _method_id(method.get("methodID"))
                            )
                        )
                        and (
                            "methodCode" not in entry
                            or (
                                isinstance(entry["methodCode"], str) and entry["methodCode"] == method.get("methodCode")
                            )
                        )
                    ]
                    if len(matches) != 1:
                        ambiguous = True
                    else:
                        grouped[matches[0]].append(entry)
                if ambiguous:
                    outcome(
                        None,
                        OutcomeStatus.UNSUPPORTED,
                        "Observations lack an unambiguous association with a published method",
                    )
                for identity, observations in grouped.items():
                    namespace, mid = identity
                    sid = stable_id("usgs_nwis", station_id, product_id, namespace, mid)
                    series = SourceSeries(
                        series_id=sid,
                        provider_id="usgs_nwis",
                        station_id=station_id,
                        product_id=product_id,
                        identity=SourceIdentity(
                            namespace=namespace,
                            published_id=mid,
                            description=method_map[identity],
                            origin="response",
                            evidence=(_EVIDENCE,),
                        ),
                        variant=mid,
                        facts=(facts,),
                    )
                    members.add(sid)
                    previous = definitions.get(sid)
                    if previous:
                        established = {f.facts_id: f for f in previous.facts}
                        if facts.facts_id in established and established[facts.facts_id] != facts:
                            raise FatalContractError("USGS fact identity reinterprets existing physical facts")
                        established[facts.facts_id] = facts
                        series = series.model_copy(update={"facts": tuple(established.values())})
                    definitions[sid] = series
                    if reason:
                        outcome(series, OutcomeStatus.UNSUPPORTED, reason, facts_id=facts.facts_id)
                        continue
                    if ambiguous and not observations:
                        outcome(
                            series,
                            OutcomeStatus.UNSUPPORTED,
                            "Method association is unresolved",
                            facts_id=facts.facts_id,
                        )
                        continue
                    native_rows = []
                    try:
                        for entry in observations:
                            stamp, zone = _parse_timestamp(entry["dateTime"], product.semantics)
                            if "value" not in entry:
                                raise ValueError("Observation entry is missing mandatory value")
                            raw = entry["value"]
                            if isinstance(raw, bool):
                                raise ValueError("Boolean observation value is not a numeric measurement")
                            number = None if raw is None else float(raw)
                            if no_data_value is not None and number == no_data_value:
                                number = None
                            if number is not None and not math.isfinite(number):
                                raise ValueError("Non-finite observation value")
                            native_rows.append(
                                {
                                    "station_id": station_id,
                                    "product_id": product_id,
                                    "time": stamp,
                                    "value": number,
                                    "time_zone": zone.value,
                                    "series_id": sid,
                                    "facts_id": facts.facts_id,
                                    "source_unit": facts.source_unit.value,
                                }
                            )
                    except (KeyError, TypeError, ValueError) as error:
                        outcome(
                            series,
                            OutcomeStatus.UNSUPPORTED,
                            f"Unrepresentable method observations: {error}",
                            facts_id=facts.facts_id,
                        )
                        continue
                    rows.extend(native_rows)
                    if ambiguous:
                        outcome(
                            series,
                            OutcomeStatus.UNSUPPORTED,
                            "Method association is partially unresolved",
                            facts_id=facts.facts_id,
                        )
                    else:
                        outcome(
                            series,
                            OutcomeStatus.SUCCESS if native_rows else OutcomeStatus.EMPTY,
                            facts_id=facts.facts_id,
                        )
            except ValidationError as error:
                raise FatalContractError("Invalid internal USGS series definition") from error
            except (KeyError, TypeError, ValueError, AttributeError) as error:
                outcome(None, OutcomeStatus.UNSUPPORTED, f"Unsupported USGS values block: {error}")
    if not time_series and not outcomes:
        outcome(
            None,
            OutcomeStatus.UNRESOLVED,
            "Response contains no concrete method identity; empty window does not establish series absence",
        )
    query_info = source.get("queryInfo")
    notes = query_info.get("note") if isinstance(query_info, dict) else None
    all_methods = isinstance(notes, list) and any(
        isinstance(n, dict) and n.get("title") == "filter:methodId" and n.get("value") == "methodIds=[ALL]"
        for n in notes
    )
    complete = all_methods and not issues
    inventory = InventorySnapshot(
        snapshot_id=stable_id("usgs_nwis", capture_id, scope.model_dump_json(), window.model_dump_json()),
        scope=scope,
        members=tuple(sorted(members)),
        completeness=InventoryCompleteness.COMPLETE if complete else InventoryCompleteness.INCOMPLETE,
        access="USGS Water Services methodIds=[ALL]" if all_methods else "USGS Water Services response",
        origin="response",
        acquired_at=acquired,
        window=window,
        evidence=(_EVIDENCE,),
        reason=None if complete else "Response does not establish a complete representable method inventory",
    )
    frame = pl.DataFrame(rows, schema=RowsSchema.polars_schema)
    validate_series_rows(frame, tuple(definitions.values()))
    return ParsedSeries(frame, tuple(definitions.values()), (inventory,), tuple(outcomes.values()), tuple(issues))


def _parse_timestamp(raw_timestamp: str, semantics: Daily | Instant) -> tuple[datetime, ZoneValue]:
    match = _OFFSET_TIMESTAMP_PATTERN.fullmatch(raw_timestamp)
    try:
        if match is not None:
            normalized_offset = "+00:00" if match["offset"] == "Z" else match["offset"]
            zone = ZoneValue(normalized_offset)
        elif isinstance(semantics, Daily):
            match = _NAIVE_TIMESTAMP_PATTERN.fullmatch(raw_timestamp)
            if match is None:
                raise ValueError("usgs_nwis daily observation timestamp must be strict ISO wall-clock time")
            zone = ZoneValue("unknown")
        else:
            raise ValueError("usgs_nwis instantaneous observation timestamp must contain a strict ISO offset")

        wall_clock = datetime.fromisoformat(match["wall_clock"])
        if isinstance(semantics, Daily) and zone == ZoneValue("unknown") and wall_clock.time() != time.min:
            raise ValueError("usgs_nwis naive daily observation timestamp must label midnight")
    except ValueError as error:
        raise ValueError(f"usgs_nwis observation timestamp is unrepresentable: {error}") from error
    return wall_clock, zone

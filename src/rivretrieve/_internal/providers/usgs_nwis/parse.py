"""usgs_nwis parse : Payload × ProviderConfig → WithIssues[Rows]

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import json
import re
from datetime import datetime, time
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import (
    Daily,
    Hourly,
    Instant,
    Payload,
    ProviderConfig,
    Rows,
    RowsSchema,
    UnknownTemporalSupport,
    WithIssues,
    ZoneValue,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.usgs_nwis.issue_codes import UsgsNwisObservationIssueCodes

PROVIDER_ID = ProviderId("usgs_nwis")

_NO_DATA_VALUE: float = -999999.0
_WALL_CLOCK_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?"
_OFFSET_TIMESTAMP_PATTERN = re.compile(rf"(?P<wall_clock>{_WALL_CLOCK_PATTERN})(?P<offset>Z|[+-][0-9]{{2}}:[0-9]{{2}})")
_NAIVE_TIMESTAMP_PATTERN = re.compile(rf"(?P<wall_clock>{_WALL_CLOCK_PATTERN})")


def parse(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    if len(payload.station_products) != 1:
        raise FatalContractError("usgs_nwis payload must contain exactly one station-product pair")
    station_id, product_id = payload.station_products[0]
    try:
        semantics = provider_config.products[product_id].semantics
    except KeyError as error:
        raise FatalContractError(f"usgs_nwis product is absent from provider config: {product_id}") from error
    if isinstance(semantics, Hourly):
        raise FatalContractError("usgs_nwis does not declare hourly interval product semantics")
    if isinstance(semantics, UnknownTemporalSupport):
        raise FatalContractError("usgs_nwis does not declare unknown temporal support")

    if not payload.content.strip():
        return _result(_empty_rows(), [_missing_data_issue(station_id)])

    try:
        document = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FatalContractError("usgs_nwis payload content is not valid JSON") from error
    if not isinstance(document, dict):
        raise FatalContractError("usgs_nwis payload content must be a JSON object")

    entries_and_sentinel = _observation_entries(document)
    if entries_and_sentinel is None:
        return _result(_empty_rows(), [_missing_data_issue(station_id)])
    entries, no_data_value = entries_and_sentinel

    row_data: list[dict[str, object]] = []
    invalid_count = 0
    no_data_count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise FatalContractError("usgs_nwis observation entry must be a JSON object")
        entry = cast("dict[str, object]", entry)

        raw_timestamp = entry.get("dateTime")
        if not isinstance(raw_timestamp, str):
            raise FatalContractError("usgs_nwis observation dateTime must be a string")
        wall_clock, zone = _parse_timestamp(raw_timestamp, semantics)

        raw_value = entry.get("value")
        if not isinstance(raw_value, str | int | float) or isinstance(raw_value, bool):
            invalid_count += 1
            continue
        try:
            native_value = float(raw_value)
        except (TypeError, ValueError):
            invalid_count += 1
            continue
        if abs(native_value - no_data_value) < 1e-3:
            no_data_count += 1
            continue

        row_data.append(
            {
                "station_id": station_id,
                "product_id": product_id,
                "time": wall_clock,
                "value": native_value,
                "time_zone": zone.value,
            }
        )

    rows = pl.DataFrame(row_data, schema=RowsSchema.polars_schema)
    issues: list[Issue] = []
    if invalid_count:
        issues.append(
            _issue(
                UsgsNwisObservationIssueCodes.INVALID_NUMERIC_VALUE,
                "Dropped observation entries with missing, non-numeric, or unparseable fields",
                {"dropped_entries": invalid_count, "station_id": station_id},
            )
        )
    if no_data_count:
        issues.append(
            _issue(
                UsgsNwisObservationIssueCodes.NO_DATA_VALUE,
                "Dropped observation entries with no-data sentinel value",
                {"dropped_entries": no_data_count, "station_id": station_id},
            )
        )
    if rows.is_empty():
        issues.append(_missing_data_issue(station_id))

    return _result(rows, issues)


def _observation_entries(document: dict[str, object]) -> tuple[list[object], float] | None:
    value = document.get("value")
    if not isinstance(value, dict):
        return None
    value = cast("dict[str, object]", value)

    time_series = value.get("timeSeries")
    if not isinstance(time_series, list) or not time_series:
        return None
    if len(time_series) != 1 or not isinstance(time_series[0], dict):
        raise FatalContractError("usgs_nwis payload must contain exactly one timeSeries object")
    series = cast("dict[str, object]", time_series[0])

    values = series.get("values")
    if not isinstance(values, list) or not values:
        return None
    if len(values) != 1 or not isinstance(values[0], dict):
        raise FatalContractError("usgs_nwis timeSeries must contain exactly one values object")
    values_block = cast("dict[str, object]", values[0])

    entries = values_block.get("value")
    if not isinstance(entries, list):
        return None
    entries = cast("list[object]", entries)

    no_data_value = _NO_DATA_VALUE
    variable = series.get("variable")
    if isinstance(variable, dict):
        variable = cast("dict[str, object]", variable)
        raw_no_data_value = variable.get("noDataValue")
        if isinstance(raw_no_data_value, int | float) and not isinstance(raw_no_data_value, bool):
            no_data_value = float(raw_no_data_value)
    return entries, no_data_value


def _parse_timestamp(raw_timestamp: str, semantics: Daily | Instant) -> tuple[datetime, ZoneValue]:
    match = _OFFSET_TIMESTAMP_PATTERN.fullmatch(raw_timestamp)
    try:
        if match is not None:
            normalized_offset = "+00:00" if match["offset"] == "Z" else match["offset"]
            zone = ZoneValue(normalized_offset)
        elif isinstance(semantics, Daily):
            match = _NAIVE_TIMESTAMP_PATTERN.fullmatch(raw_timestamp)
            if match is None:
                raise FatalContractError("usgs_nwis daily observation timestamp must be strict ISO wall-clock time")
            zone = ZoneValue("unknown")
        else:
            raise FatalContractError("usgs_nwis instantaneous observation timestamp must contain a strict ISO offset")

        wall_clock = datetime.fromisoformat(match["wall_clock"])
        if isinstance(semantics, Daily) and zone == ZoneValue("unknown") and wall_clock.time() != time.min:
            raise FatalContractError("usgs_nwis naive daily observation timestamp must label midnight")
    except ValueError as error:
        raise FatalContractError("usgs_nwis observation timestamp is unrepresentable") from error
    return wall_clock, zone


def _empty_rows() -> Rows:
    return pl.DataFrame(schema=RowsSchema.polars_schema)


def _missing_data_issue(station_id: str) -> Issue:
    return _issue(
        UsgsNwisObservationIssueCodes.MISSING_DATA,
        "No observation rows found",
        {"station_id": station_id},
    )


def _issue(code: UsgsNwisObservationIssueCodes, message: str, details: dict[str, object]) -> Issue:
    return Issue(
        severity="warning",
        code=code,
        message=message,
        details=details,
        provider_id=PROVIDER_ID,
    )


def _result(rows: Rows, issues: list[Issue]) -> WithIssues[Rows]:
    validate_catalogue(rows, RowsSchema, on_issue="raise")
    return WithIssues(value=rows, issues=tuple(issues))

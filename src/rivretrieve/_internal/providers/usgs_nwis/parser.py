from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.usgs_nwis.issue_codes import UsgsNwisObservationIssueCodes

PROVIDER_ID = ProviderId("usgs_nwis")

_RECORDS_SCHEMA = pl.Schema(
    {
        "time": pl.Datetime(time_unit="us", time_zone="UTC"),
        "station_id": pl.Utf8,
        "native_value": pl.Float64,
        "qualifier": pl.Utf8,
    }
)

_NO_DATA_VALUE = -999999.0


class UsgsNwisObservationParserError(FatalContractError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class UsgsNwisParsedPayload:
    records: pl.DataFrame
    issues: tuple[Issue, ...]


def parse_usgs_nwis_observation_json(
    content: bytes,
    *,
    station_id: str,
) -> UsgsNwisParsedPayload:
    if not content.strip():
        return UsgsNwisParsedPayload(
            records=_empty_records(),
            issues=(_missing_data_issue(station_id),),
        )

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UsgsNwisObservationParserError(f"usgs_nwis observation response is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise UsgsNwisObservationParserError("usgs_nwis observation response must be a JSON object")

    value_obj = payload.get("value")
    if not isinstance(value_obj, dict):
        return UsgsNwisParsedPayload(
            records=_empty_records(),
            issues=(_missing_data_issue(station_id),),
        )

    time_series = value_obj.get("timeSeries")
    if not isinstance(time_series, list) or not time_series:
        return UsgsNwisParsedPayload(
            records=_empty_records(),
            issues=(_missing_data_issue(station_id),),
        )

    ts = time_series[0]
    if not isinstance(ts, dict):
        raise UsgsNwisObservationParserError("usgs_nwis timeSeries entry must be a JSON object")

    variable = ts.get("variable", {})
    no_data_value = _NO_DATA_VALUE
    if isinstance(variable, dict):
        raw_ndv = variable.get("noDataValue")
        if isinstance(raw_ndv, int | float):
            no_data_value = float(raw_ndv)

    values_list = ts.get("values")
    if not isinstance(values_list, list) or not values_list:
        return UsgsNwisParsedPayload(
            records=_empty_records(),
            issues=(_missing_data_issue(station_id),),
        )

    values_block = values_list[0]
    if not isinstance(values_block, dict):
        raise UsgsNwisObservationParserError("usgs_nwis values block must be a JSON object")

    raw_values = values_block.get("value")
    if not isinstance(raw_values, list):
        return UsgsNwisParsedPayload(
            records=_empty_records(),
            issues=(_missing_data_issue(station_id),),
        )

    times: list[datetime] = []
    native_values: list[float] = []
    qualifiers: list[str] = []
    invalid_count = 0
    no_data_count = 0

    for entry in raw_values:
        if not isinstance(entry, dict):
            invalid_count += 1
            continue

        date_str = entry.get("dateTime")
        value_str = entry.get("value")
        entry_qualifiers = entry.get("qualifiers", [])

        if not isinstance(date_str, str):
            invalid_count += 1
            continue

        if value_str is None:
            invalid_count += 1
            continue

        try:
            float_val = float(value_str)
        except (ValueError, TypeError):
            invalid_count += 1
            continue

        if abs(float_val - no_data_value) < 1e-3:
            no_data_count += 1
            continue

        utc_time = _parse_nwis_datetime(date_str)
        if utc_time is None:
            invalid_count += 1
            continue

        qualifier_str = ",".join(str(q) for q in entry_qualifiers) if isinstance(entry_qualifiers, list) else ""
        times.append(utc_time)
        native_values.append(float_val)
        qualifiers.append(qualifier_str)

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

    if not times:
        return UsgsNwisParsedPayload(
            records=_empty_records(),
            issues=tuple(issues) + (_missing_data_issue(station_id),),
        )

    records = pl.DataFrame(
        {
            "time": pl.Series(times).dt.cast_time_unit("us"),
            "station_id": pl.Series([station_id] * len(times), dtype=pl.Utf8),
            "native_value": pl.Series(native_values, dtype=pl.Float64),
            "qualifier": pl.Series(qualifiers, dtype=pl.Utf8),
        }
    ).cast(_RECORDS_SCHEMA)

    return UsgsNwisParsedPayload(records=records, issues=tuple(issues))


def _parse_nwis_datetime(date_str: str) -> datetime | None:
    """Parse USGS NWIS ISO 8601 datetime string to UTC-aware datetime.

    NWIS returns timestamps like '2023-01-01T00:00:00.000-06:00'.
    Strips milliseconds, parses with timezone offset, converts to UTC.
    """
    s = date_str.strip()

    # Strip sub-second precision before timezone
    if "." in s:
        dot_idx = s.index(".")
        # Find timezone start ('+' or '-' after dot, or 'Z')
        tz_idx = -1
        for i in range(dot_idx + 1, len(s)):
            if s[i] == "Z":
                tz_idx = i
                break
            if s[i] in ("+", "-"):
                tz_idx = i
                break
        s = s[:dot_idx] + s[tz_idx:] if tz_idx > dot_idx else s[:dot_idx]

    # Normalize 'Z' to '+00:00'
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
        return dt.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def _empty_records() -> pl.DataFrame:
    return pl.DataFrame(schema=_RECORDS_SCHEMA)


def _missing_data_issue(station_id: str) -> Issue:
    return _issue(
        UsgsNwisObservationIssueCodes.MISSING_DATA,
        "No observation rows found",
        {"station_id": station_id},
    )


def _issue(
    code: UsgsNwisObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

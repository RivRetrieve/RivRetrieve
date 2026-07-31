from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import polars as pl

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.no_nve.issue_codes import NoNveObservationIssueCodes

PROVIDER_ID = ProviderId("no_nve")
UTC_DTYPE = pl.Datetime(time_unit="us", time_zone="UTC")

# Parsed records schema (pre-transform): time is UTC-aware, raw_value float.
PARSED_RECORDS_SCHEMA = {
    "time": UTC_DTYPE,
    "station_id": pl.Utf8,
    "raw_value": pl.Float64,
}


@dataclass(frozen=True)
class NoNveParsedPayload:
    records: pl.DataFrame  # columns: time (UTC), station_id, raw_value
    issues: tuple[Issue, ...]


def parse_nve_response(
    content: bytes,
    *,
    station_id: str,
    resolution_time: int,
) -> NoNveParsedPayload:
    """Parse the JSON response from NVE HydAPI Observations endpoint.

    Resolution time:
    - 1440 (daily): timestamps parsed as UTC then stripped to date → UTC midnight.
    - 60/0 (hourly/instant): timestamps carry explicit offset → converted to UTC.

    Returns a NoNveParsedPayload with UTC-aware time column.
    """
    issues: list[Issue] = []

    if not content:
        issues.append(
            _issue(
                NoNveObservationIssueCodes.MISSING_DATA,
                "Empty response from NVE HydAPI",
                {"station_id": station_id},
            )
        )
        return NoNveParsedPayload(
            records=pl.DataFrame(schema=PARSED_RECORDS_SCHEMA),
            issues=tuple(issues),
        )

    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, ValueError) as exc:
        issues.append(
            _issue(
                NoNveObservationIssueCodes.PARSE_ERROR,
                f"NVE API response is not valid JSON: {exc}",
                {"station_id": station_id},
            )
        )
        return NoNveParsedPayload(
            records=pl.DataFrame(schema=PARSED_RECORDS_SCHEMA),
            issues=tuple(issues),
        )

    if not isinstance(payload, dict):
        issues.append(
            _issue(
                NoNveObservationIssueCodes.PARSE_ERROR,
                "NVE API response is not a JSON object",
                {"station_id": station_id},
            )
        )
        return NoNveParsedPayload(
            records=pl.DataFrame(schema=PARSED_RECORDS_SCHEMA),
            issues=tuple(issues),
        )

    data = payload.get("data", [])
    if not isinstance(data, list) or not data:
        issues.append(
            _issue(
                NoNveObservationIssueCodes.MISSING_DATA,
                "NVE API response contains no data items",
                {"station_id": station_id},
            )
        )
        return NoNveParsedPayload(
            records=pl.DataFrame(schema=PARSED_RECORDS_SCHEMA),
            issues=tuple(issues),
        )

    rows: list[dict[str, object]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        observations = item.get("observations", [])
        if not isinstance(observations, list):
            continue
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            time_str = obs.get("time")
            value = obs.get("value")
            if time_str is None or value is None:
                continue
            try:
                val = float(value)
            except (TypeError, ValueError):
                continue
            # NVE uses -9999 or very negative values as missing sentinel.
            if val <= -9999:
                continue
            try:
                ts = _parse_timestamp(time_str, resolution_time)
            except (ValueError, OverflowError):
                continue
            if ts is None:
                continue
            rows.append({"time": ts, "station_id": station_id, "raw_value": val})

    if not rows:
        issues.append(
            _issue(
                NoNveObservationIssueCodes.MISSING_DATA,
                "NVE API response contained no valid observation rows",
                {"station_id": station_id},
            )
        )
        return NoNveParsedPayload(
            records=pl.DataFrame(schema=PARSED_RECORDS_SCHEMA),
            issues=tuple(issues),
        )

    if resolution_time == 1440:
        # Daily: interpret as UTC midnight — emit date_only_timestamp warning.
        issues.append(
            _issue(
                NoNveObservationIssueCodes.DATE_ONLY_TIMESTAMP,
                (
                    "NVE daily timestamps (resTime=1440) are date-only; "
                    "interpreted as UTC midnight (T00:00:00Z). "
                    "True period semantics are provider-defined."
                ),
                {"station_id": station_id, "resolution_time": resolution_time},
                severity="warning",
            )
        )
    else:
        # Hourly/instantaneous: timestamps carry explicit offset, converted to UTC.
        issues.append(
            _issue(
                NoNveObservationIssueCodes.TIMEZONE_LOCAL_TO_UTC,
                ("NVE hourly/instantaneous timestamps carry explicit ISO 8601 timezone offset; converted to UTC."),
                {"station_id": station_id, "resolution_time": resolution_time},
                severity="info",
            )
        )

    df = pl.DataFrame(rows, schema=PARSED_RECORDS_SCHEMA)
    return NoNveParsedPayload(records=df, issues=tuple(issues))


def _parse_timestamp(time_str: object, resolution_time: int) -> datetime | None:
    """Parse an NVE API timestamp string to a UTC-aware datetime.

    For daily (resTime=1440): parse to date-only then return UTC midnight.
    For hourly/instantaneous: parse ISO 8601 with offset, convert to UTC.
    """
    if not isinstance(time_str, str):
        return None
    text = time_str.strip()
    if not text:
        return None

    if resolution_time == 1440:
        # NVE daily timestamps carry a timezone offset (e.g. '+01:00' for CET) but the
        # DATE portion is the Norwegian calendar day. We extract the date part directly
        # from the string and produce UTC midnight for that date.
        # '2023-01-01T00:00:00+01:00' → 2023-01-01T00:00:00Z (not 2022-12-31Z).
        if len(text) >= 10:
            date_str = text[:10]  # 'YYYY-MM-DD'
            try:
                from datetime import date as _date

                d = _date.fromisoformat(date_str)
                return datetime(d.year, d.month, d.day, tzinfo=UTC)
            except ValueError:
                pass
        dt = _parse_iso8601(text)
        if dt is None:
            return None
        dt_utc = dt.astimezone(UTC)
        return datetime(dt_utc.year, dt_utc.month, dt_utc.day, tzinfo=UTC)
    else:
        dt = _parse_iso8601(text)
        if dt is None:
            return None
        return dt.astimezone(UTC)


def _parse_iso8601(text: str) -> datetime | None:
    """Parse ISO 8601 string to a datetime.  Handles:
    - '2023-01-01T00:00:00+01:00'  (offset aware)
    - '2023-01-01T00:00:00Z'        (UTC)
    - '2023-01-01T00:00:00'         (naive — assume UTC)
    """
    # Replace Z with +00:00 for fromisoformat compatibility.
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _issue(
    code: NoNveObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
    *,
    severity: Literal["info", "warning", "error"] = "warning",
) -> Issue:
    return Issue(severity=severity, code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

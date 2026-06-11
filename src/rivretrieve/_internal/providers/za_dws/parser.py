from __future__ import annotations

import re
from dataclasses import dataclass

import polars as pl

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.za_dws.issue_codes import ZaDwsObservationIssueCodes

PROVIDER_ID = ProviderId("za_dws")

_PRE_PATTERN = re.compile(r"<pre[^>]*>(.*?)</pre>", re.DOTALL | re.IGNORECASE)
_DATA_ROW_PATTERN = re.compile(r"^\d{8}\s")

# Sentinel value used by DWS to mark missing daily discharge.
_DAILY_SENTINEL = 99999.0

_DAILY_SCHEMA = {"date_str": pl.Utf8, "d_avg_fr": pl.Float64}
_POINT_SCHEMA = {
    "date_str": pl.Utf8,
    "time_str": pl.Utf8,
    "cor_level": pl.Float64,
    "cor_flow": pl.Float64,
}


@dataclass(frozen=True)
class ZaDwsParsedDaily:
    records: pl.DataFrame  # columns: date_str, d_avg_fr
    issues: tuple[Issue, ...]
    has_no_data: bool


@dataclass(frozen=True)
class ZaDwsParsedPoint:
    records: pl.DataFrame  # columns: date_str, time_str, cor_level, cor_flow
    issues: tuple[Issue, ...]
    has_no_data: bool


def parse_daily_response(content: str, *, station_id: str) -> ZaDwsParsedDaily:
    """Parse the HTML response for DataType=Daily into (date_str, d_avg_fr) records.

    The DWS response wraps data in a ``<pre>`` block. Each data row starts with
    an 8-digit date (YYYYMMDD), followed by the daily average flow rate and a
    quality code. Rows with the sentinel value 99999.999 are dropped.
    """
    pre_match = _PRE_PATTERN.search(content)
    if not pre_match:
        return ZaDwsParsedDaily(
            records=pl.DataFrame(schema=_DAILY_SCHEMA),
            issues=(),
            has_no_data=True,
        )

    rows: list[dict[str, object]] = []
    invalid_count = 0

    for line in pre_match.group(1).split("\n"):
        line = line.strip()
        if not _DATA_ROW_PATTERN.match(line):
            continue
        tokens = line.split()
        if len(tokens) < 2:
            invalid_count += 1
            continue
        try:
            value = float(tokens[1])
        except ValueError:
            invalid_count += 1
            continue
        if value >= _DAILY_SENTINEL:
            continue
        rows.append({"date_str": tokens[0], "d_avg_fr": value})

    issues: list[Issue] = []
    if invalid_count:
        issues.append(
            Issue(
                severity="warning",
                code=str(ZaDwsObservationIssueCodes.INVALID_ROW),
                message=f"{invalid_count} daily row(s) could not be parsed and were skipped",
                details={"station_id": station_id, "skipped_rows": invalid_count},
                provider_id=PROVIDER_ID,
            )
        )

    records = pl.DataFrame(rows, schema=_DAILY_SCHEMA) if rows else pl.DataFrame(schema=_DAILY_SCHEMA)
    return ZaDwsParsedDaily(records=records, issues=tuple(issues), has_no_data=not rows)


def parse_point_response(content: str, *, station_id: str) -> ZaDwsParsedPoint:
    """Parse the HTML response for DataType=Point into (date_str, time_str, cor_level, cor_flow).

    The DWS Point endpoint provides sub-daily observations. Each data row contains:
    DATE (YYYYMMDD), TIME (HHMMSS), corrected level (m), level quality code,
    corrected flow (m³/s), and flow quality code. Either COR_LEVEL or COR_FLOW
    may be absent or contain a sentinel value (99999.999).
    """
    pre_match = _PRE_PATTERN.search(content)
    if not pre_match:
        return ZaDwsParsedPoint(
            records=pl.DataFrame(schema=_POINT_SCHEMA),
            issues=(),
            has_no_data=True,
        )

    rows: list[dict[str, object]] = []
    invalid_count = 0

    for line in pre_match.group(1).split("\n"):
        line = line.strip()
        if not _DATA_ROW_PATTERN.match(line):
            continue
        tokens = line.split()
        if len(tokens) < 3:
            invalid_count += 1
            continue
        try:
            date_str = tokens[0]
            time_str = tokens[1]
            cor_level: float | None = float(tokens[2]) if len(tokens) > 2 else None
            cor_flow: float | None = float(tokens[4]) if len(tokens) > 4 else None
        except (ValueError, IndexError):
            invalid_count += 1
            continue

        if cor_level is not None and cor_level >= _DAILY_SENTINEL:
            cor_level = None
        if cor_flow is not None and cor_flow >= _DAILY_SENTINEL:
            cor_flow = None

        rows.append(
            {
                "date_str": date_str,
                "time_str": time_str,
                "cor_level": cor_level,
                "cor_flow": cor_flow,
            }
        )

    issues: list[Issue] = []
    if invalid_count:
        issues.append(
            Issue(
                severity="warning",
                code=str(ZaDwsObservationIssueCodes.INVALID_ROW),
                message=f"{invalid_count} point row(s) could not be parsed and were skipped",
                details={"station_id": station_id, "skipped_rows": invalid_count},
                provider_id=PROVIDER_ID,
            )
        )

    records = pl.DataFrame(rows, schema=_POINT_SCHEMA) if rows else pl.DataFrame(schema=_POINT_SCHEMA)
    return ZaDwsParsedPoint(records=records, issues=tuple(issues), has_no_data=not rows)

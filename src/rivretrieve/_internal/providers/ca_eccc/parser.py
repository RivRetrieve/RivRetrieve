"""HYDAT wide-to-long parser for ca_eccc daily observations.

HYDAT DLY_FLOWS / DLY_LEVELS tables store one row per (STATION, YEAR, MONTH)
with 31 value columns (FLOW1..FLOW31 or LEVEL1..LEVEL31) and 31 symbol columns.
This module unpivots them into a long-form Polars DataFrame.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ca_eccc.issue_codes import CaEcccObservationIssueCodes

PROVIDER_ID = ProviderId("ca_eccc")
UTC_DTYPE = pl.Datetime(time_unit="us", time_zone="UTC")

PARSED_RECORDS_SCHEMA = {
    "time": UTC_DTYPE,
    "station_id": pl.Utf8,
    "raw_value": pl.Float64,
    "symbol": pl.Utf8,
}


@dataclass(frozen=True)
class CaEcccParsedPayload:
    records: pl.DataFrame  # columns: PARSED_RECORDS_SCHEMA
    issues: tuple[Issue, ...]


def parse_hydat_rows(
    rows: list[dict[str, object]],
    *,
    station_id: str,
    value_prefix: str,
    symbol_prefix: str,
) -> CaEcccParsedPayload:
    """Unpivot HYDAT monthly rows into long-form daily records.

    Parameters
    ----------
    rows:
        Raw dicts from DLY_FLOWS or DLY_LEVELS for one station, year range.
    station_id:
        Station identifier (for error context).
    value_prefix:
        Column prefix for values: ``"FLOW"`` or ``"LEVEL"``.
    symbol_prefix:
        Column prefix for quality symbols: ``"FLOW_SYMBOL"`` or ``"LEVEL_SYMBOL"``.

    Timestamps are UTC midnight — DATE field semantics are date-only.
    A ``date_only_timestamp`` warning issue is emitted when at least one row
    is parsed successfully.
    """
    issues: list[Issue] = []

    if not rows:
        issues.append(
            _issue(
                CaEcccObservationIssueCodes.MISSING_DATA,
                "HYDAT returned no rows for station/year range",
                {"station_id": station_id},
            )
        )
        return CaEcccParsedPayload(
            records=pl.DataFrame(schema=PARSED_RECORDS_SCHEMA),
            issues=tuple(issues),
        )

    long_rows: list[dict[str, object]] = []
    for row in rows:
        year = row.get("YEAR")
        month = row.get("MONTH")
        no_days = row.get("NO_DAYS")
        if year is None or month is None:
            continue
        try:
            year_i = int(str(year))
            month_i = int(str(month))
        except (TypeError, ValueError):
            continue
        max_day = int(str(no_days)) if no_days is not None else 31

        for day in range(1, max_day + 1):
            raw_val = row.get(f"{value_prefix}{day}")
            if raw_val is None:
                continue
            try:
                val = float(str(raw_val))
            except (TypeError, ValueError):
                continue
            try:
                ts = datetime(year_i, month_i, day, tzinfo=UTC)
            except ValueError:
                continue  # invalid date (e.g. Feb 30 in a leap-year-unaware table)
            symbol_raw = row.get(f"{symbol_prefix}{day}")
            symbol = str(symbol_raw).strip() if symbol_raw is not None else ""
            long_rows.append(
                {
                    "time": ts,
                    "station_id": station_id,
                    "raw_value": val,
                    "symbol": symbol,
                }
            )

    if not long_rows:
        issues.append(
            _issue(
                CaEcccObservationIssueCodes.MISSING_DATA,
                "HYDAT rows contained no valid day-level observations",
                {"station_id": station_id},
            )
        )
        return CaEcccParsedPayload(
            records=pl.DataFrame(schema=PARSED_RECORDS_SCHEMA),
            issues=tuple(issues),
        )

    # Emit date-only timestamp warning once per parse call.
    issues.append(
        _issue(
            CaEcccObservationIssueCodes.DATE_ONLY_TIMESTAMP,
            (
                "HYDAT daily observations carry date-only timestamps (YEAR, MONTH, DAY). "
                "Interpreted as UTC midnight (T00:00:00Z). "
                "True period anchor is provider_defined."
            ),
            {"station_id": station_id},
        )
    )

    df = pl.DataFrame(long_rows, schema=PARSED_RECORDS_SCHEMA)
    return CaEcccParsedPayload(records=df, issues=tuple(issues))


def _issue(
    code: CaEcccObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

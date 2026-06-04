from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.br_ana.issue_codes import BrAnaObservationIssueCodes

PROVIDER_ID = ProviderId("br_ana")

UTC_DTYPE = pl.Datetime(time_unit="us", time_zone="UTC")

# Schema for parsed records before transformation.
# 'raw_value' holds the native value (m³/s for discharge, cm for stage).
_PARSED_SCHEMA = {
    "time": UTC_DTYPE,
    "raw_value": pl.Float64,
}


class BrAnaObservationParserError(Exception):
    pass


@dataclass(frozen=True)
class BrAnaParsedPayload:
    records: pl.DataFrame  # columns: time (UTC), raw_value
    issues: tuple[Issue, ...]


def parse_br_ana_json(
    content: bytes,
    *,
    station_id: str,
    product_id: str,
) -> BrAnaParsedPayload:
    """Parse ANA Hidroweb monthly JSON response into daily records.

    ANA returns a list of monthly objects.  Each object has a
    ``Data_Hora_Dado`` field (``YYYY-MM-...``) and per-day value columns
    (``Vazao_01``..``Vazao_31`` for discharge, ``Cota_01``..``Cota_31``
    for stage).  Day values are strings or numbers and may be null.

    Timestamps are reconstructed as UTC midnight (date-only pattern).  A
    ``date_only_timestamp`` warning issue is always emitted because the ANA
    API provides no explicit timezone and daily values represent calendar
    days whose true local timezone is undocumented.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise BrAnaObservationParserError(f"br_ana response is not valid JSON: {exc}") from exc

    # The API may return a bare list or a {"status":"OK","items":[...]} wrapper.
    if isinstance(data, list):
        monthly_records = data
    elif isinstance(data, dict):
        items = data.get("items")
        monthly_records = items if isinstance(items, list) else []
    else:
        raise BrAnaObservationParserError("br_ana response must be a JSON array or object")

    val_prefix = "Vazao_" if product_id == "discharge_daily_mean" else "Cota_"

    rows: list[dict[str, object]] = []
    for month_data in monthly_records:
        if not isinstance(month_data, dict):
            continue

        date_str = month_data.get("Data_Hora_Dado")
        if not isinstance(date_str, str) or len(date_str) < 7:
            continue

        try:
            year = int(date_str[:4])
            month = int(date_str[5:7])
        except ValueError:
            continue

        for day in range(1, 32):
            col = f"{val_prefix}{day:02d}"
            raw = month_data.get(col)
            if raw is None:
                continue
            try:
                fval = float(raw)
            except (TypeError, ValueError):
                continue
            try:
                ts = datetime(year, month, day, tzinfo=UTC)
            except ValueError:
                # Invalid date (e.g. Feb 30).
                continue
            rows.append({"time": ts, "raw_value": fval})

    records_df = pl.DataFrame(rows, schema=_PARSED_SCHEMA).sort("time") if rows else pl.DataFrame(schema=_PARSED_SCHEMA)

    issue = _date_only_issue(station_id, product_id)
    return BrAnaParsedPayload(records=records_df, issues=(issue,))


def _date_only_issue(station_id: str, product_id: str) -> Issue:
    return Issue(
        severity="warning",
        code=str(BrAnaObservationIssueCodes.DATE_ONLY_TIMESTAMP),
        message=(
            "br_ana daily timestamps are reconstructed from calendar year/month/day "
            "and interpreted as UTC midnight (T00:00:00Z). "
            "The ANA Hidroweb API provides no explicit timezone; "
            "values likely represent Brasília Standard Time (UTC-3) calendar days."
        ),
        details={"station_id": station_id, "product_id": product_id},
        provider_id=PROVIDER_ID,
    )

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
NAIVE_DTYPE = pl.Datetime(time_unit="us")

# Schema for parsed records before transformation.
# 'raw_value' holds the native value (m³/s for discharge, cm for stage).
_PARSED_SCHEMA = {
    "time": UTC_DTYPE,
    "raw_value": pl.Float64,
}

# Schema for parsed telemetric ("instantaneous", quality-flagged) records.
# 'time' is the naive local timestamp as reported (Data_Hora_Medicao); 'quality_flag'
# is the raw ANA status code string ("0"/"1"/"2") preserved for downstream mapping.
_TELEMETRIC_PARSED_SCHEMA = {
    "time": NAIVE_DTYPE,
    "raw_value": pl.Float64,
    "quality_flag": pl.Utf8,
}

# Native field name (and its companion *_Status field) per telemetric product.
# Confirmed against the official ANA HidroWebService manual sample responses
# (manual-hidrowebservice_publica.pdf) and the live OpenAPI spec.
_TELEMETRIC_FIELD_BY_PRODUCT: dict[str, str] = {
    "discharge_instantaneous": "Vazao_Adotada",
    "stage_instantaneous": "Cota_Adotada",
    "water_temperature_instantaneous": "Temperatura_Agua",
}

# ANA quality-flag semantics (manual: "0 = ok, 1 = suspeito, 2 = ruim").
TELEMETRIC_QUALITY_FLAG_MAP: dict[str, str] = {
    "0": "ok",
    "1": "suspect",
    "2": "poor",
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


@dataclass(frozen=True)
class BrAnaTelemetricParsedPayload:
    records: pl.DataFrame  # columns: time (naive local), raw_value, quality_flag (raw "0"/"1"/"2"/"" )
    issues: tuple[Issue, ...]


def parse_br_ana_telemetric_json(
    content: bytes,
    *,
    station_id: str,
    product_id: str,
) -> BrAnaTelemetricParsedPayload:
    """Parse a HidroinfoanaSerieTelemetricaAdotada/Detalhada JSON response.

    Unlike the legacy daily columnar series, telemetric responses are a flat
    array of per-reading records, each carrying its own ``Data_Hora_Medicao``
    timestamp (with time-of-day, at the station's native telemetry cadence —
    commonly ~15 minutes) plus a native value field and a companion
    ``<Field>_Status`` quality-flag field ("0"=ok, "1"=suspeito, "2"=ruim).

    Returned timestamps are naive local (Brasília Standard Time, UTC-3,
    per ANA's documented operating timezone) — converted to UTC by the
    transform layer. A ``naive_local_timestamp`` info-severity issue is
    emitted to document this provider behaviour (distinct from the
    ``date_only_timestamp`` issue used for the daily columnar series, since
    these timestamps do carry genuine time-of-day information).
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise BrAnaObservationParserError(f"br_ana telemetric response is not valid JSON: {exc}") from exc

    if isinstance(data, list):
        records_raw = data
    elif isinstance(data, dict):
        items = data.get("items")
        records_raw = items if isinstance(items, list) else []
    else:
        raise BrAnaObservationParserError("br_ana telemetric response must be a JSON array or object")

    field = _TELEMETRIC_FIELD_BY_PRODUCT.get(product_id)
    if field is None:
        raise BrAnaObservationParserError(f"Unsupported br_ana telemetric product: {product_id}")
    status_field = f"{field}_Status"

    rows: list[dict[str, object]] = []
    for entry in records_raw:
        if not isinstance(entry, dict):
            continue

        ts_str = entry.get("Data_Hora_Medicao")
        ts = _parse_telemetric_timestamp(ts_str)
        if ts is None:
            continue

        raw = entry.get(field)
        if raw is None:
            continue
        try:
            fval = float(raw)
        except (TypeError, ValueError):
            continue

        flag_raw = entry.get(status_field)
        flag_str = "" if flag_raw is None else str(flag_raw).strip()

        rows.append({"time": ts, "raw_value": fval, "quality_flag": flag_str})

    records_df = (
        pl.DataFrame(rows, schema=_TELEMETRIC_PARSED_SCHEMA).sort("time")
        if rows
        else pl.DataFrame(schema=_TELEMETRIC_PARSED_SCHEMA)
    )

    issue = _naive_local_timestamp_issue(station_id, product_id)
    return BrAnaTelemetricParsedPayload(records=records_df, issues=(issue,))


def _parse_telemetric_timestamp(value: object) -> datetime | None:
    """Parse ``Data_Hora_Medicao`` strings like ``"2024-01-01 23:00:00.0"``."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    text = text.replace("T", " ")
    # Trim sub-second fractional component if present (e.g. trailing ".0").
    if "." in text:
        text = text.split(".", 1)[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)  # noqa: DTZ007 — intentionally naive (local time)
        except ValueError:
            continue
    return None


def _naive_local_timestamp_issue(station_id: str, product_id: str) -> Issue:
    return Issue(
        severity="info",
        code=str(BrAnaObservationIssueCodes.NAIVE_LOCAL_TIMESTAMP),
        message=(
            "br_ana telemetric timestamps (Data_Hora_Medicao) carry genuine time-of-day "
            "information at the station's native telemetry cadence, but the API provides "
            "no explicit timezone. They are interpreted as Brasília Standard Time "
            "(UTC-3, ANA's documented operating timezone) and converted to UTC."
        ),
        details={"station_id": station_id, "product_id": product_id},
        provider_id=PROVIDER_ID,
    )


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

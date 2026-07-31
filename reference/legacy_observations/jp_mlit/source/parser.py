from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

import polars as pl

from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.jp_mlit.issue_codes import JpMlitObservationIssueCodes

PROVIDER_ID = ProviderId("jp_mlit")
_JST = ZoneInfo("Asia/Tokyo")

# Missing-value sentinel: values <= -9999 are treated as NaN.
_MISSING_SENTINEL = -9999.0

# Shared intermediate schemas before product-specific transform.
_HOURLY_RECORDS_SCHEMA = pl.Schema(
    {
        "time": pl.Datetime(time_unit="us", time_zone="UTC"),
        "station_id": pl.Utf8,
        "raw_value": pl.Float64,
    }
)

_DAILY_RECORDS_SCHEMA = pl.Schema(
    {
        "time": pl.Datetime(time_unit="us", time_zone="UTC"),
        "station_id": pl.Utf8,
        "raw_value": pl.Float64,
    }
)

_YEAR_PATTERN = re.compile(r"(\d{4})年")
_MONTH_MAP = {f"{i}月": i for i in range(1, 13)}


class JpMlitParserError(FatalContractError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class JpMlitParsedPayload:
    records: pl.DataFrame
    issues: tuple[Issue, ...]


def parse_jp_mlit_hourly_dat(
    dat_content: str,
    *,
    station_id: str,
) -> JpMlitParsedPayload:
    """Parse a MLIT hourly .dat file (KIND 2 or 6).

    Timestamps are in Japan Standard Time (JST = UTC+9) and are converted to UTC.
    Hour column labels are 1時..24時 where 1時 = 00:00 JST on that date,
    24時 = 23:00 JST on that date.

    An info-severity timezone_local_to_utc issue is always emitted to document the conversion.
    """
    if not dat_content.strip():
        return JpMlitParsedPayload(
            records=pl.DataFrame(schema=_HOURLY_RECORDS_SCHEMA),
            issues=(_missing_data_issue(station_id),),
        )

    lines = dat_content.strip().splitlines()
    data_lines = _extract_data_lines(lines)
    if not data_lines:
        return JpMlitParsedPayload(
            records=pl.DataFrame(schema=_HOURLY_RECORDS_SCHEMA),
            issues=(_missing_data_issue(station_id),),
        )

    # Build column names: date + 24 * (value, flag)
    col_names = ["_date"]
    for i in range(1, 25):
        col_names.append(f"v{i}")
        col_names.append(f"f{i}")

    try:
        df = _read_csv_lines(data_lines, col_names)
    except Exception as exc:
        raise JpMlitParserError(f"jp_mlit hourly .dat CSV parse failed for {station_id}: {exc}") from exc

    # Parse the date column as YYYY/MM/DD.
    df = df.with_columns(
        pl.col("_date").str.strip_chars().str.to_date(format="%Y/%m/%d", strict=False).alias("_date_parsed")
    ).filter(pl.col("_date_parsed").is_not_null())

    if df.is_empty():
        return JpMlitParsedPayload(
            records=pl.DataFrame(schema=_HOURLY_RECORDS_SCHEMA),
            issues=(_missing_data_issue(station_id),),
        )

    # Unpivot the 24 value columns.
    value_cols = [f"v{i}" for i in range(1, 25)]
    df_long = df.select(["_date_parsed"] + value_cols).unpivot(
        index=["_date_parsed"], on=value_cols, variable_name="hour_col", value_name="raw_value"
    )

    # Map vN → hour index (0-based: v1=hour 1 in legacy → offset 0h, so hour-1 hours after midnight).
    df_long = df_long.with_columns(pl.col("hour_col").str.slice(1).cast(pl.Int32).alias("_hour_offset"))

    # Strip whitespace then cast to float; filter missing sentinels.
    df_long = df_long.with_columns(pl.col("raw_value").str.strip_chars().cast(pl.Float64, strict=False)).filter(
        pl.col("raw_value").is_not_null() & (pl.col("raw_value") > _MISSING_SENTINEL)
    )

    if df_long.is_empty():
        return JpMlitParsedPayload(
            records=pl.DataFrame(schema=_HOURLY_RECORDS_SCHEMA),
            issues=(_missing_data_issue(station_id),),
        )

    # Build UTC timestamps: date + (hour-1) hours JST → UTC.
    rows: list[dict[str, object]] = []
    for row in df_long.iter_rows(named=True):
        d = row["_date_parsed"]
        hour_offset: int = row["_hour_offset"]  # 1..24 → 0..23 hours after midnight JST
        raw: float = row["raw_value"]
        jst_dt = datetime(d.year, d.month, d.day, hour_offset - 1, 0, 0, tzinfo=_JST)
        utc_dt = jst_dt.astimezone(UTC)
        rows.append(
            {
                "time": utc_dt.replace(tzinfo=UTC),
                "station_id": station_id,
                "raw_value": raw,
            }
        )

    if not rows:
        return JpMlitParsedPayload(
            records=pl.DataFrame(schema=_HOURLY_RECORDS_SCHEMA),
            issues=(_missing_data_issue(station_id),),
        )

    records = pl.DataFrame(rows, schema=_HOURLY_RECORDS_SCHEMA)
    tz_issue = _issue(
        JpMlitObservationIssueCodes.TIMEZONE_LOCAL_TO_UTC,
        "Hourly timestamps are in Japan Standard Time (JST = UTC+9); converted to UTC",
        {"station_id": station_id, "local_timezone": "Asia/Tokyo"},
        severity="info",
    )
    return JpMlitParsedPayload(records=records, issues=(tz_issue,))


def parse_jp_mlit_daily_dat(
    dat_content: str,
    *,
    station_id: str,
) -> JpMlitParsedPayload:
    """Parse a MLIT daily .dat file (KIND 3 or 7).

    Timestamps are date-only for a Japan Standard Time calendar day.
    Following the established pattern (lt_lhmt, fr_hubeau), they are
    interpreted as UTC midnight (T00:00:00Z). A date_only_timestamp
    warning issue is emitted to document this convention.
    """
    if not dat_content.strip():
        return JpMlitParsedPayload(
            records=pl.DataFrame(schema=_DAILY_RECORDS_SCHEMA),
            issues=(_missing_data_issue(station_id),),
        )

    lines = dat_content.strip().splitlines()

    # Extract year from a line containing "年".
    year: int | None = None
    for line in lines:
        m = _YEAR_PATTERN.search(line)
        if m:
            year = int(m.group(1))
            break

    if year is None:
        return JpMlitParsedPayload(
            records=pl.DataFrame(schema=_DAILY_RECORDS_SCHEMA),
            issues=(
                _issue(
                    JpMlitObservationIssueCodes.INVALID_DAT_CONTENT,
                    "jp_mlit daily .dat: could not extract year from header",
                    {"station_id": station_id},
                ),
            ),
        )

    data_lines = _extract_data_lines(lines)
    # Filter out year-marker lines ("2023年") which appear between the header
    # and data rows in the real MLIT .dat format.
    data_lines = [ln for ln in data_lines if not _YEAR_PATTERN.search(ln)]
    if not data_lines:
        return JpMlitParsedPayload(
            records=pl.DataFrame(schema=_DAILY_RECORDS_SCHEMA),
            issues=(_missing_data_issue(station_id),),
        )

    # Build column names: month + 31 * (value, flag)
    col_names = ["_month"]
    for i in range(1, 32):
        col_names.append(f"v{i}")
        col_names.append(f"f{i}")

    try:
        df = _read_csv_lines(data_lines, col_names)
    except Exception as exc:
        raise JpMlitParserError(f"jp_mlit daily .dat CSV parse failed for {station_id}: {exc}") from exc

    # Map Japanese month labels → integers.
    df = df.with_columns(
        pl.col("_month").str.strip_chars().replace_strict(_MONTH_MAP, default=None).alias("_month_int")
    ).filter(pl.col("_month_int").is_not_null())

    if df.is_empty():
        return JpMlitParsedPayload(
            records=pl.DataFrame(schema=_DAILY_RECORDS_SCHEMA),
            issues=(_missing_data_issue(station_id),),
        )

    # Unpivot the 31 day columns.
    value_cols = [f"v{i}" for i in range(1, 32)]
    df_long = df.select(["_month_int"] + value_cols).unpivot(
        index=["_month_int"], on=value_cols, variable_name="day_col", value_name="raw_value"
    )
    df_long = df_long.with_columns(
        pl.col("day_col").str.slice(1).cast(pl.Int32).alias("_day"),
        pl.col("raw_value").str.strip_chars().cast(pl.Float64, strict=False),
    ).filter(pl.col("raw_value").is_not_null() & (pl.col("raw_value") > _MISSING_SENTINEL))

    if df_long.is_empty():
        return JpMlitParsedPayload(
            records=pl.DataFrame(schema=_DAILY_RECORDS_SCHEMA),
            issues=(_missing_data_issue(station_id),),
        )

    # Build UTC midnight timestamps.
    rows: list[dict[str, object]] = []
    for row in df_long.iter_rows(named=True):
        month: int = int(row["_month_int"])
        day: int = int(row["_day"])
        raw: float = row["raw_value"]
        try:
            utc_dt = datetime(year, month, day, 0, 0, 0, tzinfo=UTC)
        except ValueError:
            continue  # invalid date (e.g., Feb 30) → skip
        rows.append(
            {
                "time": utc_dt,
                "station_id": station_id,
                "raw_value": raw,
            }
        )

    if not rows:
        return JpMlitParsedPayload(
            records=pl.DataFrame(schema=_DAILY_RECORDS_SCHEMA),
            issues=(_missing_data_issue(station_id),),
        )

    records = pl.DataFrame(rows, schema=_DAILY_RECORDS_SCHEMA)
    date_issue = _issue(
        JpMlitObservationIssueCodes.DATE_ONLY_TIMESTAMP,
        (
            "jp_mlit daily data has date-only timestamps representing a JST calendar day; "
            "interpreted as UTC midnight (T00:00:00Z)"
        ),
        {"station_id": station_id, "year": year},
    )
    return JpMlitParsedPayload(records=records, issues=(date_issue,))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_data_lines(lines: list[str]) -> list[str]:
    """Return non-comment, non-empty lines after the header line (starts with ',')."""
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith(","):
            header_idx = i
            break
    if header_idx is None:
        return [line for line in lines if not line.startswith("#") and line.strip()]
    data = lines[header_idx + 1 :]
    return [line for line in data if not line.startswith("#") and line.strip()]


def _read_csv_lines(lines: list[str], col_names: list[str]) -> pl.DataFrame:
    csv_text = "\n".join(lines)
    return pl.read_csv(
        io.StringIO(csv_text).read().encode(),
        has_header=False,
        new_columns=col_names,
        infer_schema=False,
        ignore_errors=True,
        truncate_ragged_lines=True,  # real files may have extra monthly-average columns
    )


def _missing_data_issue(station_id: str) -> Issue:
    return _issue(JpMlitObservationIssueCodes.MISSING_DATA, "No observation rows found", {"station_id": station_id})


def _issue(
    code: JpMlitObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
    severity: Literal["info", "warning", "error"] = "warning",
) -> Issue:
    return Issue(severity=severity, code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

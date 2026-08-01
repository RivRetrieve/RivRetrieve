from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.pl_imgw.issue_codes import PlImgwObservationIssueCodes

PROVIDER_ID = ProviderId("pl_imgw")

# Sentinel values that represent missing data in IMGW files.
_SENTINEL_LEVEL_CM = {9999.0}
_SENTINEL_FLOW_M3S = {99999.999, 999.0}
_SENTINEL_TEMP_C = {99.9}

_RECORDS_SCHEMA = pl.Schema(
    {
        "time": pl.Datetime(time_unit="us", time_zone="UTC"),
        "station_id": pl.Utf8,
        "level_cm": pl.Float64,
        "flow_m3s": pl.Float64,
        "temp_c": pl.Float64,
    }
)

# Column indices (0-based) in the 10-column IMGW daily CSV.
_COL_STATION_ID = 0
_COL_HYDRO_YEAR = 3
_COL_MONTH_INDICATOR = 4
_COL_DAY = 5
_COL_LEVEL_CM = 6
_COL_FLOW_M3S = 7
_COL_TEMP_C = 8
_COL_CALENDAR_MONTH = 9


@dataclass(frozen=True)
class PlImgwParsedPayload:
    records: pl.DataFrame  # schema = _RECORDS_SCHEMA, filtered to requested stations
    issues: tuple[Issue, ...]


class PlImgwParserError(FatalContractError):
    pass


def parse_imgw_zip(
    zip_bytes: bytes,
    *,
    station_ids: frozenset[str],
) -> PlImgwParsedPayload:
    """Decompress a IMGW daily ZIP archive and parse the embedded CSV.

    The ZIP contains exactly one CSV file (codz_YYYY.csv or codz_YYYY_MM.csv).
    Results are filtered to the requested station IDs.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            if not names:
                raise PlImgwParserError("pl_imgw ZIP archive is empty")
            csv_bytes = zf.read(names[0])
    except zipfile.BadZipFile as exc:
        raise PlImgwParserError(f"pl_imgw response is not a valid ZIP: {exc}") from exc

    return parse_imgw_csv_bytes(csv_bytes, station_ids=station_ids)


def parse_imgw_csv_bytes(
    csv_bytes: bytes,
    *,
    station_ids: frozenset[str],
) -> PlImgwParsedPayload:
    """Parse raw IMGW daily CSV bytes (already decompressed from ZIP).

    Handles two format eras:
    - 2023+: UTF-8 with BOM, semicolon-separated, unquoted
    - pre-2023: CP1250, comma-separated, quoted values
    """
    text = _decode_csv(csv_bytes)
    rows, invalid_count = _parse_rows(text, station_ids=station_ids)

    issues: list[Issue] = []

    if invalid_count:
        issues.append(
            Issue(
                severity="warning",
                code=str(PlImgwObservationIssueCodes.INVALID_ROW),
                message="Dropped rows with invalid or unparseable fields",
                details={"dropped_rows": invalid_count},
                provider_id=PROVIDER_ID,
            )
        )

    if not rows:
        return PlImgwParsedPayload(records=_empty_records(), issues=tuple(issues))

    # Emit the date_only_timestamp warning: IMGW provides year/month/day only.
    issues.append(
        Issue(
            severity="warning",
            code=str(PlImgwObservationIssueCodes.DATE_ONLY_TIMESTAMP),
            message=(
                "IMGW daily timestamps are date-only (reconstructed from hydrological year + "
                "month indicator + day). Interpreted as UTC midnight (T00:00:00Z). "
                "True local timezone undocumented; likely Central European Time."
            ),
            details={"row_count": len(rows)},
            provider_id=PROVIDER_ID,
        )
    )

    df = pl.DataFrame(rows, schema=_RECORDS_SCHEMA)
    return PlImgwParsedPayload(records=df, issues=tuple(issues))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _decode_csv(raw: bytes) -> str:
    # 2023 annual ZIP: UTF-8 with BOM.
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig")
    # Pre-2023 and 2024 files: CP1250 (Polish charset).
    try:
        return raw.decode("cp1250")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _unwrap_fully_quoted(text: str) -> str:
    # 2024-style: each line is one outer-quoted field with doubled inner quotes.
    # Strip the outer quotes and unescape, matching R adapter_PL_IMGW strategy.
    lines = text.splitlines()
    fixed: list[str] = []
    for line in lines:
        stripped = line
        if stripped.startswith('"'):
            stripped = stripped[1:]
        if stripped.endswith('"'):
            stripped = stripped[:-1]
        stripped = stripped.replace('""', '"')
        fixed.append(stripped)
    return "\n".join(fixed)


def _parse_rows(
    text: str,
    *,
    station_ids: frozenset[str],
) -> tuple[list[dict[str, object]], int]:
    """Return (valid_rows, invalid_count).

    IMGW CSVs have no header. Three format eras:
    - Semicolon (2023 annual): no quoting, values plain
    - Comma, fully outer-quoted (2024 annual): each row wrapped in outer quotes with doubled inner quotes
    - Comma (pre-2023 monthly): fields may be quoted, station IDs padded with spaces
    """
    # Detect delimiter from first non-empty line.
    first_line = text.lstrip("\r\n").split("\n")[0] if text.strip() else ""
    delimiter = ";" if ";" in first_line else ","

    # 2024-style: every row is a single outer-quoted field.
    # Detect by checking if the CSV reader yields only 1 column on the first data row.
    if delimiter == ",":
        probe = list(csv.reader(io.StringIO(first_line), delimiter=","))
        if probe and len(probe[0]) == 1 and first_line.startswith('"'):
            text = _unwrap_fully_quoted(text)
            # Re-detect delimiter after unwrapping (still comma).
            first_line = text.lstrip("\r\n").split("\n")[0] if text.strip() else ""

    rows: list[dict[str, object]] = []
    invalid_count = 0

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    for raw_row in reader:
        if len(raw_row) < 10:
            if any(cell.strip() for cell in raw_row):
                invalid_count += 1
            continue

        station_id = raw_row[_COL_STATION_ID].strip()
        if not station_id:
            invalid_count += 1
            continue

        # Filter early — IMGW ZIPs contain all stations; skip unrequested ones.
        if station_ids and station_id not in station_ids:
            continue

        try:
            hydro_year = int(raw_row[_COL_HYDRO_YEAR].strip())
            day = int(raw_row[_COL_DAY].strip())
            calendar_month_col = int(raw_row[_COL_CALENDAR_MONTH].strip())
        except (ValueError, IndexError):
            invalid_count += 1
            continue

        # Reconstruct calendar date. Use the calendar month column (col 10) directly.
        # If calendar month >= 11 (Nov/Dec), the calendar year is hydro_year - 1.
        calendar_month = calendar_month_col
        calendar_year = hydro_year - 1 if calendar_month >= 11 else hydro_year

        try:
            ts = datetime(calendar_year, calendar_month, day, tzinfo=UTC)
        except ValueError:
            # Invalid date (e.g. day=31 in a 30-day month).
            invalid_count += 1
            continue

        level_cm = _parse_sentinel(raw_row[_COL_LEVEL_CM], _SENTINEL_LEVEL_CM)
        flow_m3s = _parse_sentinel(raw_row[_COL_FLOW_M3S], _SENTINEL_FLOW_M3S)
        temp_c = _parse_sentinel(raw_row[_COL_TEMP_C], _SENTINEL_TEMP_C)

        rows.append(
            {
                "time": ts,
                "station_id": station_id,
                "level_cm": level_cm,
                "flow_m3s": flow_m3s,
                "temp_c": temp_c,
            }
        )

    return rows, invalid_count


def _parse_sentinel(raw: str, sentinels: set[float]) -> float | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    # Round to avoid floating-point near-miss (e.g. 99.90000000001).
    if round(value, 3) in sentinels:
        return None
    return value


def _empty_records() -> pl.DataFrame:
    return pl.DataFrame(schema=_RECORDS_SCHEMA)

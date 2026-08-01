from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

import openpyxl
import polars as pl

from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ba_fhmzbih.issue_codes import BaFhmzbihObservationIssueCodes

PROVIDER_ID = ProviderId("ba_fhmzbih")

# Workbook layout: 8 metadata rows (#Station Name ... #Rows ... blank ...
# #Timestamp/Value header), then one (timestamp, value) row per observation.
_HEADER_ROW_COUNT = 8

_PARSED_SCHEMA = {
    "time_local": pl.Datetime(time_unit="us"),
    "raw_value": pl.Float64,
}


class BaFhmzbihObservationParserError(FatalContractError):
    pass


@dataclass(frozen=True)
class BaFhmzbihParsedPayload:
    records: pl.DataFrame  # columns: time_local (naive Sarajevo local time), raw_value
    issues: tuple[Issue, ...]


def parse_ba_fhmzbih_workbook(
    content: bytes,
    *,
    station_id: str,
    product_id: str,
) -> BaFhmzbihParsedPayload:
    """Parse a vodostaji.voda.ba ``*_1Y.xlsx`` workbook into local-time records.

    The workbook's first worksheet has eight descriptive header rows
    (station name, parameter, unit, row count, a blank separator, and the
    ``#Timestamp``/``Value`` column header), followed by one row per hourly
    observation. Timestamps are naive — the portal does not publish an
    explicit UTC offset — and are interpreted as ``Europe/Sarajevo`` local
    time before conversion to UTC by the caller.
    """
    try:
        workbook = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
        worksheet = workbook.worksheets[0]
        rows = list(worksheet.iter_rows(min_row=_HEADER_ROW_COUNT + 1, values_only=True))
        workbook.close()
    except Exception as exc:
        raise BaFhmzbihObservationParserError(
            f"ba_fhmzbih workbook for station {station_id} / {product_id} could not be parsed as xlsx: {exc}"
        ) from exc

    parsed_rows: list[dict[str, object]] = []
    invalid_count = 0

    for row in rows:
        if not row or len(row) < 2:
            invalid_count += 1
            continue
        timestamp, raw_value = row[0], row[1]
        if not isinstance(timestamp, datetime) or raw_value is None:
            invalid_count += 1
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            invalid_count += 1
            continue
        parsed_rows.append({"time_local": timestamp.replace(tzinfo=None), "raw_value": value})

    records = (
        pl.DataFrame(parsed_rows, schema=_PARSED_SCHEMA).sort("time_local")
        if parsed_rows
        else pl.DataFrame(schema=_PARSED_SCHEMA)
    )

    issues: list[Issue] = []
    if invalid_count:
        issues.append(
            Issue(
                severity="warning",
                code=str(BaFhmzbihObservationIssueCodes.INVALID_ROW),
                message=f"{invalid_count} row(s) in the ba_fhmzbih workbook could not be parsed and were skipped",
                details={"station_id": station_id, "product_id": product_id, "skipped_rows": invalid_count},
                provider_id=PROVIDER_ID,
            )
        )

    return BaFhmzbihParsedPayload(records=records, issues=tuple(issues))

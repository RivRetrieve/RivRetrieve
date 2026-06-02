from __future__ import annotations

import json
from dataclasses import dataclass

import polars as pl

from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.cz_chmi.issue_codes import CzChmiObservationIssueCodes

PROVIDER_ID = ProviderId("cz_chmi")

_RECORDS_SCHEMA = pl.Schema(
    {
        "time": pl.Datetime(time_unit="us", time_zone="UTC"),
        "station_id": pl.Utf8,
        "ts_con_id": pl.Utf8,
        "native_value": pl.Float64,
    }
)


class CzChmiObservationParserError(FatalContractError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class CzChmiParsedPayload:
    records: pl.DataFrame
    issues: tuple[Issue, ...]


def parse_cz_chmi_observation_json(
    content: bytes,
    *,
    station_id: str,
    ts_con_id: str,
) -> CzChmiParsedPayload:
    if not content.strip():
        return CzChmiParsedPayload(records=_empty_records(), issues=(_missing_data_issue(station_id),))

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CzChmiObservationParserError(f"cz_chmi observation response is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise CzChmiObservationParserError("cz_chmi observation response must be a JSON object")

    ts_list = payload.get("tsList", [])
    if not isinstance(ts_list, list):
        raise CzChmiObservationParserError("cz_chmi 'tsList' field must be a list")

    if not ts_list:
        return CzChmiParsedPayload(records=_empty_records(), issues=(_missing_data_issue(station_id),))

    matching = [
        entry
        for entry in ts_list
        if isinstance(entry, dict)
        and isinstance(entry.get("tsConID"), str)
        and entry["tsConID"].upper() == ts_con_id.upper()
    ]
    if not matching:
        return CzChmiParsedPayload(records=_empty_records(), issues=(_missing_data_issue(station_id),))

    rows: list[dict[str, object]] = []
    invalid_count = 0

    for ts_entry in matching:
        ts_data = ts_entry.get("tsData", {})
        if not isinstance(ts_data, dict):
            continue
        data_block = ts_data.get("data", {})
        if not isinstance(data_block, dict):
            continue
        header_str = data_block.get("header", "")
        values_raw = data_block.get("values", [])
        if not isinstance(header_str, str) or not isinstance(values_raw, list):
            continue
        columns = [c.strip() for c in header_str.split(",")]
        if "DT" not in columns or "VAL" not in columns:
            continue
        dt_idx = columns.index("DT")
        val_idx = columns.index("VAL")

        for row in values_raw:
            if not isinstance(row, list) or len(row) <= max(dt_idx, val_idx):
                invalid_count += 1
                continue
            date_str = row[dt_idx]
            raw_value = row[val_idx]

            if not isinstance(date_str, str):
                invalid_count += 1
                continue
            if raw_value is None:
                invalid_count += 1
                continue
            if not isinstance(raw_value, int | float):
                invalid_count += 1
                continue

            # Normalise Z suffix to +00:00 for consistent Polars parsing
            ts_str = date_str.replace("Z", "+00:00") if date_str.endswith("Z") else date_str

            rows.append(
                {
                    "time": ts_str,
                    "station_id": station_id,
                    "ts_con_id": ts_con_id,
                    "native_value": float(raw_value),
                }
            )

    issues: list[Issue] = []
    if invalid_count:
        issues.append(
            _issue(
                CzChmiObservationIssueCodes.INVALID_NUMERIC_VALUE,
                "Dropped observation entries with missing or invalid values",
                {"dropped_entries": invalid_count, "station_id": station_id, "ts_con_id": ts_con_id},
            )
        )

    if not rows:
        return CzChmiParsedPayload(records=_empty_records(), issues=tuple(issues) + (_missing_data_issue(station_id),))

    parsed = pl.DataFrame(rows)
    records = parsed.with_columns(
        pl.col("time").str.to_datetime(time_zone="UTC", strict=False).alias("time"),
    ).select(
        pl.col("time").cast(pl.Datetime(time_unit="us", time_zone="UTC")),
        pl.col("station_id").cast(pl.Utf8),
        pl.col("ts_con_id").cast(pl.Utf8),
        pl.col("native_value").cast(pl.Float64),
    )

    null_times = records.filter(pl.col("time").is_null()).height
    records = records.filter(pl.col("time").is_not_null())
    if null_times:
        issues.append(
            _issue(
                CzChmiObservationIssueCodes.TIMEZONE_AMBIGUITY,
                "Dropped rows with unparseable timestamps",
                {"dropped_rows": null_times, "station_id": station_id},
            )
        )

    if records.is_empty():
        return CzChmiParsedPayload(records=_empty_records(), issues=tuple(issues) + (_missing_data_issue(station_id),))

    return CzChmiParsedPayload(records=records.cast(_RECORDS_SCHEMA), issues=tuple(issues))


def _empty_records() -> pl.DataFrame:
    return pl.DataFrame(schema=_RECORDS_SCHEMA)


def _missing_data_issue(station_id: str) -> Issue:
    return _issue(
        CzChmiObservationIssueCodes.MISSING_DATA,
        "No observation rows found",
        {"station_id": station_id},
    )


def _issue(
    code: CzChmiObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

from __future__ import annotations

import json
from dataclasses import dataclass

import polars as pl

from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.lt_lhmt.issue_codes import LtLhmtObservationIssueCodes

PROVIDER_ID = ProviderId("lt_lhmt")

_RECORDS_SCHEMA = pl.Schema(
    {
        "time": pl.Datetime(time_unit="us", time_zone="UTC"),
        "station_id": pl.Utf8,
        "native_field": pl.Utf8,
        "native_value": pl.Float64,
    }
)


class LtLhmtObservationParserError(FatalContractError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class LtLhmtParsedPayload:
    records: pl.DataFrame
    issues: tuple[Issue, ...]


def parse_lt_lhmt_observation_json(
    content: bytes,
    *,
    station_id: str,
    native_field: str,
) -> LtLhmtParsedPayload:
    if not content.strip():
        return LtLhmtParsedPayload(records=_empty_records(), issues=(_missing_data_issue(station_id),))

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LtLhmtObservationParserError(f"lt_lhmt observation response is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise LtLhmtObservationParserError("lt_lhmt observation response must be a JSON object")

    observations = payload.get("observations", [])
    if not isinstance(observations, list):
        raise LtLhmtObservationParserError("lt_lhmt 'observations' field must be a list")

    if not observations:
        return LtLhmtParsedPayload(records=_empty_records(), issues=(_missing_data_issue(station_id),))

    rows: list[dict[str, object]] = []
    invalid_count = 0
    date_only_count = 0

    for entry in observations:
        if not isinstance(entry, dict):
            invalid_count += 1
            continue

        date_str = entry.get("observationDateUtc")
        raw_value = entry.get(native_field)

        if not isinstance(date_str, str):
            invalid_count += 1
            continue

        if raw_value is None:
            invalid_count += 1
            continue

        if not isinstance(raw_value, int | float):
            invalid_count += 1
            continue

        # Timestamps from Meteo.lt are date-only strings (e.g. "2023-06-01"); no time-of-day component.
        # We interpret them as UTC midnight: "2023-06-01" -> 2023-06-01T00:00:00Z.
        if "T" not in date_str and len(date_str) == 10:
            date_only_count += 1
            timestamp_str = date_str + "T00:00:00Z"
        else:
            timestamp_str = date_str

        rows.append(
            {
                "time": timestamp_str,
                "station_id": station_id,
                "native_field": native_field,
                "native_value": float(raw_value),
            }
        )

    issues: list[Issue] = []
    if invalid_count:
        issues.append(
            _issue(
                LtLhmtObservationIssueCodes.INVALID_NUMERIC_VALUE,
                "Dropped observation entries with missing or non-numeric values",
                {"dropped_entries": invalid_count, "station_id": station_id, "native_field": native_field},
            )
        )
    if date_only_count and rows:
        issues.append(
            _issue(
                LtLhmtObservationIssueCodes.DATE_ONLY_TIMESTAMP,
                "Observation timestamps are date-only strings; interpreted as UTC midnight (T00:00:00Z)",
                {"rows": date_only_count, "station_id": station_id},
            )
        )

    if not rows:
        return LtLhmtParsedPayload(records=_empty_records(), issues=tuple(issues) + (_missing_data_issue(station_id),))

    parsed = pl.DataFrame(rows)
    records = parsed.with_columns(
        pl.col("time").str.to_datetime(time_zone="UTC", strict=False).alias("time"),
    ).select(
        pl.col("time").cast(pl.Datetime(time_unit="us", time_zone="UTC")),
        pl.col("station_id").cast(pl.Utf8),
        pl.col("native_field").cast(pl.Utf8),
        pl.col("native_value").cast(pl.Float64),
    )

    null_times = records.filter(pl.col("time").is_null()).height
    records = records.filter(pl.col("time").is_not_null())
    if null_times:
        issues.append(
            _issue(
                LtLhmtObservationIssueCodes.TIMEZONE_AMBIGUITY,
                "Dropped rows with unparseable timestamps",
                {"dropped_rows": null_times, "station_id": station_id},
            )
        )

    if records.is_empty():
        return LtLhmtParsedPayload(records=_empty_records(), issues=tuple(issues) + (_missing_data_issue(station_id),))

    return LtLhmtParsedPayload(records=records.cast(_RECORDS_SCHEMA), issues=tuple(issues))


def _empty_records() -> pl.DataFrame:
    return pl.DataFrame(schema=_RECORDS_SCHEMA)


def _missing_data_issue(station_id: str) -> Issue:
    return _issue(LtLhmtObservationIssueCodes.MISSING_DATA, "No observation rows found", {"station_id": station_id})


def _issue(code: LtLhmtObservationIssueCodes, message: str, details: dict[str, object] | None) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

from __future__ import annotations

import json
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import polars as pl

from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.th_thaiwater.issue_codes import ThThaiWaterObservationIssueCodes

PROVIDER_ID = ProviderId("th_thaiwater")
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")

_RECORDS_SCHEMA = pl.Schema(
    {
        "time": pl.Datetime(time_unit="us", time_zone="UTC"),
        "station_id": pl.Utf8,
        "value_field": pl.Float64,
        "discharge_field": pl.Float64,
    }
)


class ThThaiWaterObservationParserError(FatalContractError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class ThThaiWaterParsedPayload:
    records: pl.DataFrame
    issues: tuple[Issue, ...]


def parse_th_thaiwater_observation_json(
    content: bytes,
    *,
    station_id: str,
) -> ThThaiWaterParsedPayload:
    if not content.strip():
        return ThThaiWaterParsedPayload(records=_empty_records(), issues=(_missing_data_issue(station_id),))

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ThThaiWaterObservationParserError(f"th_thaiwater observation response is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ThThaiWaterObservationParserError("th_thaiwater observation response must be a JSON object")

    data_block = payload.get("data", {})
    if not isinstance(data_block, dict):
        return ThThaiWaterParsedPayload(records=_empty_records(), issues=(_missing_data_issue(station_id),))

    graph_data = data_block.get("graph_data", [])
    if not isinstance(graph_data, list) or not graph_data:
        return ThThaiWaterParsedPayload(records=_empty_records(), issues=(_missing_data_issue(station_id),))

    rows: list[dict[str, object]] = []
    invalid_count = 0

    for entry in graph_data:
        if not isinstance(entry, dict):
            invalid_count += 1
            continue

        date_str = entry.get("datetime")
        if not isinstance(date_str, str) or not date_str.strip():
            invalid_count += 1
            continue

        raw_value = entry.get("value")
        raw_discharge = entry.get("discharge")

        # Parse timestamp as Bangkok local and convert to UTC
        from datetime import datetime

        try:
            local_dt = datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M:%S")
            aware_dt = local_dt.replace(tzinfo=BANGKOK_TZ)
            # Store as UTC microsecond datetime string for Polars
            utc_dt_str = aware_dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        except ValueError:
            invalid_count += 1
            continue

        value_float = _to_float(raw_value)
        discharge_float = _to_float(raw_discharge)

        rows.append(
            {
                "time": utc_dt_str,
                "station_id": station_id,
                "value_field": value_float,
                "discharge_field": discharge_float,
            }
        )

    issues: list[Issue] = []
    if invalid_count:
        issues.append(
            _issue(
                ThThaiWaterObservationIssueCodes.INVALID_NUMERIC_VALUE,
                "Dropped observation entries with missing or unparseable values",
                {"dropped_entries": invalid_count, "station_id": station_id},
            )
        )

    if not rows:
        return ThThaiWaterParsedPayload(
            records=_empty_records(),
            issues=tuple(issues) + (_missing_data_issue(station_id),),
        )

    parsed = pl.DataFrame(rows)
    records = parsed.with_columns(
        pl.col("time").str.to_datetime(time_zone="UTC", strict=False).alias("time"),
    ).select(
        pl.col("time").cast(pl.Datetime(time_unit="us", time_zone="UTC")),
        pl.col("station_id").cast(pl.Utf8),
        pl.col("value_field").cast(pl.Float64),
        pl.col("discharge_field").cast(pl.Float64),
    )

    null_times = records.filter(pl.col("time").is_null()).height
    records = records.filter(pl.col("time").is_not_null())
    if null_times:
        issues.append(
            _issue(
                ThThaiWaterObservationIssueCodes.TIMEZONE_LOCAL_TO_UTC,
                "Dropped rows with unparseable Bangkok timestamps",
                {"dropped_rows": null_times, "station_id": station_id},
            )
        )

    if records.is_empty():
        return ThThaiWaterParsedPayload(
            records=_empty_records(),
            issues=tuple(issues) + (_missing_data_issue(station_id),),
        )

    return ThThaiWaterParsedPayload(records=records.cast(_RECORDS_SCHEMA), issues=tuple(issues))


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _empty_records() -> pl.DataFrame:
    return pl.DataFrame(schema=_RECORDS_SCHEMA)


def _missing_data_issue(station_id: str) -> Issue:
    return _issue(
        ThThaiWaterObservationIssueCodes.MISSING_DATA,
        "No observation rows found",
        {"station_id": station_id},
    )


def _issue(
    code: ThThaiWaterObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

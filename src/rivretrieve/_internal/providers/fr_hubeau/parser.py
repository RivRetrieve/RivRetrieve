from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import polars as pl

from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.fr_hubeau.issue_codes import FrHubeauObservationIssueCodes

PROVIDER_ID = ProviderId("fr_hubeau")

_RECORDS_SCHEMA = pl.Schema(
    {
        "time": pl.Datetime(time_unit="us", time_zone="UTC"),
        "station_id": pl.Utf8,
        "grandeur_code": pl.Utf8,
        "raw_value": pl.Float64,
    }
)


class FrHubeauObservationParserError(FatalContractError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class FrHubeauParsedPayload:
    records: pl.DataFrame
    next_url: str | None
    issues: tuple[Issue, ...]


def parse_fr_hubeau_observation_json(
    content: bytes,
    *,
    station_id: str,
    grandeur_code: str,
) -> FrHubeauParsedPayload:
    if not content.strip():
        return FrHubeauParsedPayload(
            records=_empty_records(),
            next_url=None,
            issues=(_missing_data_issue(station_id),),
        )

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrHubeauObservationParserError(f"fr_hubeau observation response is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise FrHubeauObservationParserError("fr_hubeau observation response must be a JSON object")

    next_url_raw = payload.get("next")
    next_url = next_url_raw if isinstance(next_url_raw, str) and next_url_raw.strip() else None

    data_items = payload.get("data", [])
    if not isinstance(data_items, list) or not data_items:
        return FrHubeauParsedPayload(
            records=_empty_records(),
            next_url=next_url,
            issues=(_missing_data_issue(station_id),),
        )

    rows: list[dict[str, object]] = []
    invalid_count = 0
    date_only_count = 0

    for entry in data_items:
        if not isinstance(entry, dict):
            invalid_count += 1
            continue

        # Filter to the requested grandeur
        entry_grandeur = entry.get("grandeur_hydro_elab")
        if entry_grandeur != grandeur_code:
            continue

        date_str = entry.get("date_obs_elab")
        raw_value = entry.get("resultat_obs_elab")

        if not isinstance(date_str, str) or not date_str.strip():
            invalid_count += 1
            continue

        if raw_value is None or not isinstance(raw_value, int | float):
            invalid_count += 1
            continue

        # Hubeau returns date_obs_elab as date-only "YYYY-MM-DD" for daily elaborated observations.
        # Interpret as UTC midnight; emit date_only_timestamp warning (see series_annotations).
        date_str = date_str.strip()
        if "T" not in date_str and len(date_str) == 10:
            date_only_count += 1
            timestamp_str = date_str + "T00:00:00Z"
        else:
            # If Hubeau ever returns a full ISO datetime, parse it directly.
            timestamp_str = date_str

        rows.append(
            {
                "time": timestamp_str,
                "station_id": station_id,
                "grandeur_code": grandeur_code,
                "raw_value": float(raw_value),
            }
        )

    issues: list[Issue] = []
    if invalid_count:
        issues.append(
            _issue(
                FrHubeauObservationIssueCodes.INVALID_NUMERIC_VALUE,
                "Dropped observation entries with missing or non-numeric values",
                {"dropped_entries": invalid_count, "station_id": station_id, "grandeur_code": grandeur_code},
            )
        )
    if date_only_count and rows:
        issues.append(
            _issue(
                FrHubeauObservationIssueCodes.DATE_ONLY_TIMESTAMP,
                "Hubeau date_obs_elab is date-only; interpreted as UTC midnight (T00:00:00Z)",
                {"rows": date_only_count, "station_id": station_id},
            )
        )

    if not rows:
        return FrHubeauParsedPayload(
            records=_empty_records(),
            next_url=next_url,
            issues=tuple(issues) + (_missing_data_issue(station_id),),
        )

    parsed = pl.DataFrame(rows, schema_overrides={"raw_value": pl.Float64})
    records = parsed.with_columns(
        pl.col("time").str.to_datetime(time_zone="UTC", strict=False).alias("time"),
    ).select(
        pl.col("time").cast(pl.Datetime(time_unit="us", time_zone="UTC")),
        pl.col("station_id").cast(pl.Utf8),
        pl.col("grandeur_code").cast(pl.Utf8),
        pl.col("raw_value").cast(pl.Float64),
    )

    null_times = records.filter(pl.col("time").is_null()).height
    records = records.filter(pl.col("time").is_not_null())
    if null_times:
        issues.append(
            _issue(
                FrHubeauObservationIssueCodes.INVALID_NUMERIC_VALUE,
                "Dropped rows with unparseable timestamps",
                {"dropped_rows": null_times, "station_id": station_id},
            )
        )

    if records.is_empty():
        return FrHubeauParsedPayload(
            records=_empty_records(),
            next_url=next_url,
            issues=tuple(issues) + (_missing_data_issue(station_id),),
        )

    return FrHubeauParsedPayload(
        records=records.cast(_RECORDS_SCHEMA),
        next_url=next_url,
        issues=tuple(issues),
    )


def _empty_records() -> pl.DataFrame:
    return pl.DataFrame(schema=_RECORDS_SCHEMA)


def _missing_data_issue(station_id: str) -> Issue:
    return _issue(
        FrHubeauObservationIssueCodes.MISSING_DATA,
        "No observation rows found",
        {"station_id": station_id},
    )


def _issue(
    code: FrHubeauObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _now_utc() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)

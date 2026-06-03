from __future__ import annotations

import json
from dataclasses import dataclass

import polars as pl

from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.fr_hubeau.issue_codes import FrHubeauObservationIssueCodes

PROVIDER_ID = ProviderId("fr_hubeau")

# Shared schema for parsed intermediate records before product-specific transform.
# obs_elab and obs_tr share this schema; temperature uses _TEMP_RECORDS_SCHEMA.
_RECORDS_SCHEMA = pl.Schema(
    {
        "time": pl.Datetime(time_unit="us", time_zone="UTC"),
        "station_id": pl.Utf8,
        "grandeur_code": pl.Utf8,
        "raw_value": pl.Float64,
    }
)

_TEMP_RECORDS_SCHEMA = pl.Schema(
    {
        "time": pl.Datetime(time_unit="us", time_zone="UTC"),
        "station_id": pl.Utf8,
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


# ---------------------------------------------------------------------------
# obs_elab parser (daily elaborated — date-only timestamps)
# ---------------------------------------------------------------------------


def parse_fr_hubeau_obs_elab_json(
    content: bytes,
    *,
    station_id: str,
    grandeur_code: str,
) -> FrHubeauParsedPayload:
    """Parse a Hubeau obs_elab page.

    Timestamps are date-only (YYYY-MM-DD) interpreted as UTC midnight.
    Emits a date_only_timestamp warning issue when date-only rows are found.
    """
    if not content.strip():
        return FrHubeauParsedPayload(
            records=_empty_records(),
            next_url=None,
            issues=(_missing_data_issue(station_id),),
        )

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrHubeauObservationParserError(f"fr_hubeau obs_elab response is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise FrHubeauObservationParserError("fr_hubeau obs_elab response must be a JSON object")

    next_url = _extract_next(payload)
    data_items = payload.get("data", [])
    if not isinstance(data_items, list) or not data_items:
        return FrHubeauParsedPayload(
            records=_empty_records(), next_url=next_url, issues=(_missing_data_issue(station_id),)
        )

    rows: list[dict[str, object]] = []
    invalid_count = 0
    date_only_count = 0

    for entry in data_items:
        if not isinstance(entry, dict):
            invalid_count += 1
            continue

        if entry.get("grandeur_hydro_elab") != grandeur_code:
            continue

        date_str = entry.get("date_obs_elab")
        raw_value = entry.get("resultat_obs_elab")

        if not isinstance(date_str, str) or not date_str.strip():
            invalid_count += 1
            continue
        if raw_value is None or not isinstance(raw_value, int | float):
            invalid_count += 1
            continue

        date_str = date_str.strip()
        if "T" not in date_str and len(date_str) == 10:
            date_only_count += 1
            timestamp_str = date_str + "T00:00:00Z"
        else:
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
                "Dropped obs_elab entries with missing or non-numeric values",
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

    return _finalise_records(rows, next_url, station_id, issues, _RECORDS_SCHEMA)


# ---------------------------------------------------------------------------
# observations_tr parser (real-time / instantaneous — full UTC timestamps)
# ---------------------------------------------------------------------------


def parse_fr_hubeau_obs_tr_json(
    content: bytes,
    *,
    station_id: str,
    grandeur_code: str,
) -> FrHubeauParsedPayload:
    """Parse a Hubeau observations_tr page.

    Timestamps in date_obs are full ISO 8601 UTC (YYYY-MM-DDTHH:MM:SSZ).
    Units: H in mm, Q in l/s (same conversion factors as obs_elab).
    """
    if not content.strip():
        return FrHubeauParsedPayload(records=_empty_records(), next_url=None, issues=(_missing_data_issue(station_id),))

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrHubeauObservationParserError(f"fr_hubeau observations_tr response is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise FrHubeauObservationParserError("fr_hubeau observations_tr response must be a JSON object")

    next_url = _extract_next(payload)
    data_items = payload.get("data", [])
    if not isinstance(data_items, list) or not data_items:
        return FrHubeauParsedPayload(
            records=_empty_records(), next_url=next_url, issues=(_missing_data_issue(station_id),)
        )

    rows: list[dict[str, object]] = []
    invalid_count = 0

    for entry in data_items:
        if not isinstance(entry, dict):
            invalid_count += 1
            continue

        if entry.get("grandeur_hydro") != grandeur_code:
            continue

        date_str = entry.get("date_obs")
        raw_value = entry.get("resultat_obs")

        if not isinstance(date_str, str) or not date_str.strip():
            invalid_count += 1
            continue
        if raw_value is None or not isinstance(raw_value, int | float):
            invalid_count += 1
            continue

        rows.append(
            {
                "time": date_str.strip(),
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
                "Dropped observations_tr entries with missing or non-numeric values",
                {"dropped_entries": invalid_count, "station_id": station_id, "grandeur_code": grandeur_code},
            )
        )

    return _finalise_records(rows, next_url, station_id, issues, _RECORDS_SCHEMA)


# ---------------------------------------------------------------------------
# temperature/chronique parser
# ---------------------------------------------------------------------------


def parse_fr_hubeau_temperature_json(
    content: bytes,
    *,
    station_id: str,
) -> FrHubeauParsedPayload:
    """Parse a Hubeau temperature/chronique page.

    Timestamps are a date field (date_mesure_temp, YYYY-MM-DD) combined with
    a time field (heure_mesure_temp, HH:MM:SS), interpreted as UTC.
    Some API versions return a single date_mesure ISO field instead.
    """
    if not content.strip():
        return FrHubeauParsedPayload(
            records=_empty_temp_records(), next_url=None, issues=(_missing_data_issue(station_id),)
        )

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrHubeauObservationParserError(f"fr_hubeau temperature response is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise FrHubeauObservationParserError("fr_hubeau temperature response must be a JSON object")

    next_url = _extract_next(payload)
    data_items = payload.get("data", [])
    if not isinstance(data_items, list) or not data_items:
        return FrHubeauParsedPayload(
            records=_empty_temp_records(), next_url=next_url, issues=(_missing_data_issue(station_id),)
        )

    rows: list[dict[str, object]] = []
    invalid_count = 0

    for entry in data_items:
        if not isinstance(entry, dict):
            invalid_count += 1
            continue

        raw_value = entry.get("resultat")
        if raw_value is None or not isinstance(raw_value, int | float):
            invalid_count += 1
            continue

        # Prefer combined ISO field, fall back to date + time split
        date_mesure = entry.get("date_mesure")
        if isinstance(date_mesure, str) and "T" in date_mesure:
            timestamp_str = date_mesure.strip()
        else:
            d = entry.get("date_mesure_temp")
            h = entry.get("heure_mesure_temp")
            if not isinstance(d, str) or not d.strip():
                invalid_count += 1
                continue
            h_str = h.strip() if isinstance(h, str) and h.strip() else "00:00:00"
            # left-pad single-digit hours
            if len(h_str) > 0 and h_str[0].isdigit() and (len(h_str) < 8 or h_str[1] == ":"):
                h_str = "0" + h_str
            timestamp_str = f"{d.strip()}T{h_str}Z"

        rows.append(
            {
                "time": timestamp_str,
                "station_id": station_id,
                "raw_value": float(raw_value),
            }
        )

    issues: list[Issue] = []
    if invalid_count:
        issues.append(
            _issue(
                FrHubeauObservationIssueCodes.INVALID_NUMERIC_VALUE,
                "Dropped temperature entries with missing or non-numeric values",
                {"dropped_entries": invalid_count, "station_id": station_id},
            )
        )

    return _finalise_temp_records(rows, next_url, station_id, issues)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_next(payload: dict[str, object]) -> str | None:
    val = payload.get("next")
    return val if isinstance(val, str) and val.strip() else None


def _finalise_records(
    rows: list[dict[str, object]],
    next_url: str | None,
    station_id: str,
    issues: list[Issue],
    schema: pl.Schema,
) -> FrHubeauParsedPayload:
    if not rows:
        return FrHubeauParsedPayload(
            records=pl.DataFrame(schema=schema),
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
            records=pl.DataFrame(schema=schema),
            next_url=next_url,
            issues=tuple(issues) + (_missing_data_issue(station_id),),
        )

    return FrHubeauParsedPayload(records=records.cast(schema), next_url=next_url, issues=tuple(issues))


def _finalise_temp_records(
    rows: list[dict[str, object]],
    next_url: str | None,
    station_id: str,
    issues: list[Issue],
) -> FrHubeauParsedPayload:
    if not rows:
        return FrHubeauParsedPayload(
            records=_empty_temp_records(),
            next_url=next_url,
            issues=tuple(issues) + (_missing_data_issue(station_id),),
        )

    parsed = pl.DataFrame(rows, schema_overrides={"raw_value": pl.Float64})
    records = parsed.with_columns(
        pl.col("time").str.to_datetime(time_zone="UTC", strict=False).alias("time"),
    ).select(
        pl.col("time").cast(pl.Datetime(time_unit="us", time_zone="UTC")),
        pl.col("station_id").cast(pl.Utf8),
        pl.col("raw_value").cast(pl.Float64),
    )

    null_times = records.filter(pl.col("time").is_null()).height
    records = records.filter(pl.col("time").is_not_null())
    if null_times:
        issues.append(
            _issue(
                FrHubeauObservationIssueCodes.INVALID_NUMERIC_VALUE,
                "Dropped temperature rows with unparseable timestamps",
                {"dropped_rows": null_times, "station_id": station_id},
            )
        )

    if records.is_empty():
        return FrHubeauParsedPayload(
            records=_empty_temp_records(),
            next_url=next_url,
            issues=tuple(issues) + (_missing_data_issue(station_id),),
        )

    return FrHubeauParsedPayload(records=records.cast(_TEMP_RECORDS_SCHEMA), next_url=next_url, issues=tuple(issues))


def _empty_records() -> pl.DataFrame:
    return pl.DataFrame(schema=_RECORDS_SCHEMA)


def _empty_temp_records() -> pl.DataFrame:
    return pl.DataFrame(schema=_TEMP_RECORDS_SCHEMA)


def _missing_data_issue(station_id: str) -> Issue:
    return _issue(FrHubeauObservationIssueCodes.MISSING_DATA, "No observation rows found", {"station_id": station_id})


def _issue(
    code: FrHubeauObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)


# ---------------------------------------------------------------------------
# Backward-compat alias — existing tests call parse_fr_hubeau_observation_json
# ---------------------------------------------------------------------------

parse_fr_hubeau_observation_json = parse_fr_hubeau_obs_elab_json

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.no_nve.issue_codes import NoNveObservationIssueCodes

PROVIDER_ID = ProviderId("no_nve")
UTC_DTYPE = pl.Datetime(time_unit="us", time_zone="UTC")

_DATA_SCHEMA = {
    "time": UTC_DTYPE,
    "station_id": pl.Utf8,
    "product_id": pl.Utf8,
    "value": pl.Float64,
}
_ROW_ANNOTATION_SCHEMA = {
    "time": pl.Datetime(time_unit="us"),
    "station_id": pl.Utf8,
    "product_id": pl.Utf8,
    "annotation": pl.Utf8,
    "value": pl.Utf8,
}
_SERIES_ANNOTATION_SCHEMA = {
    "station_id": pl.Utf8,
    "product_id": pl.Utf8,
    "annotation": pl.Utf8,
    "value": pl.Utf8,
}


@dataclass(frozen=True)
class NoNveProductPolicy:
    product_id: str
    parameter_id: int
    resolution_time: int
    frequency: str  # "daily" | "hourly" | "irregular"
    native_unit: str
    canonical_unit: str
    timezone_handling: str  # "date_only_utc_midnight" | "provider_timestamp_offset"


@dataclass(frozen=True)
class NoNveTransformedSeries:
    data: pl.DataFrame
    row_annotations: pl.DataFrame
    series_annotations: pl.DataFrame
    issues: tuple[Issue, ...]


PRODUCT_POLICIES: dict[str, NoNveProductPolicy] = {
    "stage_daily_mean": NoNveProductPolicy(
        product_id="stage_daily_mean",
        parameter_id=1000,
        resolution_time=1440,
        frequency="daily",
        native_unit="m",
        canonical_unit="m",
        timezone_handling="date_only_utc_midnight",
    ),
    "stage_hourly_mean": NoNveProductPolicy(
        product_id="stage_hourly_mean",
        parameter_id=1000,
        resolution_time=60,
        frequency="hourly",
        native_unit="m",
        canonical_unit="m",
        timezone_handling="provider_timestamp_offset",
    ),
    "stage_instantaneous": NoNveProductPolicy(
        product_id="stage_instantaneous",
        parameter_id=1000,
        resolution_time=0,
        frequency="irregular",
        native_unit="m",
        canonical_unit="m",
        timezone_handling="provider_timestamp_offset",
    ),
    "discharge_daily_mean": NoNveProductPolicy(
        product_id="discharge_daily_mean",
        parameter_id=1001,
        resolution_time=1440,
        frequency="daily",
        native_unit="m3/s",
        canonical_unit="m3/s",
        timezone_handling="date_only_utc_midnight",
    ),
    "discharge_hourly_mean": NoNveProductPolicy(
        product_id="discharge_hourly_mean",
        parameter_id=1001,
        resolution_time=60,
        frequency="hourly",
        native_unit="m3/s",
        canonical_unit="m3/s",
        timezone_handling="provider_timestamp_offset",
    ),
    "discharge_instantaneous": NoNveProductPolicy(
        product_id="discharge_instantaneous",
        parameter_id=1001,
        resolution_time=0,
        frequency="irregular",
        native_unit="m3/s",
        canonical_unit="m3/s",
        timezone_handling="provider_timestamp_offset",
    ),
    "water_temperature_daily_mean": NoNveProductPolicy(
        product_id="water_temperature_daily_mean",
        parameter_id=1003,
        resolution_time=1440,
        frequency="daily",
        native_unit="degC",
        canonical_unit="degC",
        timezone_handling="date_only_utc_midnight",
    ),
    "water_temperature_hourly_mean": NoNveProductPolicy(
        product_id="water_temperature_hourly_mean",
        parameter_id=1003,
        resolution_time=60,
        frequency="hourly",
        native_unit="degC",
        canonical_unit="degC",
        timezone_handling="provider_timestamp_offset",
    ),
    "water_temperature_instantaneous": NoNveProductPolicy(
        product_id="water_temperature_instantaneous",
        parameter_id=1003,
        resolution_time=0,
        frequency="irregular",
        native_unit="degC",
        canonical_unit="degC",
        timezone_handling="provider_timestamp_offset",
    ),
}


def resolve_product_policy(product_id: str) -> NoNveProductPolicy:
    from rivretrieve._internal.issues import InvalidObservationRequestError

    if product_id not in PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported no_nve observation product: {product_id}")
    return PRODUCT_POLICIES[product_id]


def transform_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: NoNveProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
) -> NoNveTransformedSeries:
    if records.is_empty():
        return _empty_series(station_id, policy, windows, endpoints, "No records from parser")

    valid = records.filter(pl.col("raw_value").is_not_null())
    if valid.is_empty():
        return _empty_series(station_id, policy, windows, endpoints, "No rows with non-null raw_value")

    deduped = valid.sort("time").unique(subset=["time"], keep="last", maintain_order=True)

    rows_data: list[dict[str, object]] = []
    rows_ann: list[dict[str, object]] = []

    for row in deduped.iter_rows(named=True):
        t = row["time"]
        if not isinstance(t, datetime):
            continue
        raw = row["raw_value"]
        if not isinstance(raw, float):
            raw = float(raw)

        rows_data.append(
            {
                "time": t,
                "station_id": station_id,
                "product_id": policy.product_id,
                "value": raw,
            }
        )
        ann_time = t.replace(tzinfo=None) if t.tzinfo is not None else t
        for annotation, ann_value in {
            "native_unit": policy.native_unit,
            "raw_value": _float_string(raw),
        }.items():
            rows_ann.append(
                {
                    "time": ann_time,
                    "station_id": station_id,
                    "product_id": policy.product_id,
                    "annotation": annotation,
                    "value": ann_value,
                }
            )

    if not rows_data:
        return _empty_series(station_id, policy, windows, endpoints, "No rows remained after transformation")

    data_df = pl.DataFrame(rows_data, schema=_DATA_SCHEMA).sort(["station_id", "product_id", "time"])
    ann_df = pl.DataFrame(rows_ann, schema=_ROW_ANNOTATION_SCHEMA)

    times_list = data_df["time"].to_list()
    returned_start = times_list[0] if times_list else None
    returned_end = times_list[-1] if times_list else None

    return NoNveTransformedSeries(
        data=data_df,
        row_annotations=ann_df,
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            windows=windows,
            endpoints=endpoints,
            returned_start=returned_start,
            returned_end=returned_end,
        ),
        issues=(),
    )


def empty_data() -> pl.DataFrame:
    return pl.DataFrame(schema=_DATA_SCHEMA)


def empty_row_annotations() -> pl.DataFrame:
    return pl.DataFrame(schema=_ROW_ANNOTATION_SCHEMA)


def empty_series_annotations() -> pl.DataFrame:
    return pl.DataFrame(schema=_SERIES_ANNOTATION_SCHEMA)


def _empty_series(
    station_id: str,
    policy: NoNveProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
    reason: str,
) -> NoNveTransformedSeries:
    return NoNveTransformedSeries(
        data=empty_data(),
        row_annotations=empty_row_annotations(),
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            windows=windows,
            endpoints=endpoints,
            returned_start=None,
            returned_end=None,
        ),
        issues=(
            _issue(
                NoNveObservationIssueCodes.MISSING_DATA,
                reason,
                {"station_id": station_id, "product_id": policy.product_id},
            ),
        ),
    )


def _series_annotations(
    *,
    station_id: str,
    policy: NoNveProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
    returned_start: object,
    returned_end: object,
) -> pl.DataFrame:
    if policy.timezone_handling == "date_only_utc_midnight":
        timezone_source = "date_only_utc_midnight"
        date_only_flag = "true"
        local_tz = None
    else:
        timezone_source = "provider_timestamp_offset"
        date_only_flag = None
        local_tz = None  # NVE provides explicit offset, no inference needed

    values: dict[str, str | None] = {
        "parameter_id": str(policy.parameter_id),
        "resolution_time": str(policy.resolution_time),
        "native_unit_returned": policy.native_unit,
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "resolved_timezone": "UTC",
        "timezone_source": timezone_source,
        "provider_endpoints": json.dumps(list(endpoints), sort_keys=True, separators=(",", ":")),
        "requested_windows": json.dumps([list(w) for w in windows], sort_keys=True, separators=(",", ":")),
    }
    if date_only_flag is not None:
        values["date_only_timestamp_flag"] = date_only_flag
    if local_tz is not None:
        values["local_timezone"] = local_tz

    return pl.DataFrame(
        [
            {
                "station_id": station_id,
                "product_id": policy.product_id,
                "annotation": annotation,
                "value": value,
            }
            for annotation, value in values.items()
        ],
        schema=_SERIES_ANNOTATION_SCHEMA,
    )


def _float_string(value: float) -> str:
    return format(value, ".15g")


def _iso_z(value: object) -> str:
    if isinstance(value, datetime):
        value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _issue(
    code: NoNveObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

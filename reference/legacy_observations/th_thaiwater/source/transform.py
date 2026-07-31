from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import polars as pl

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.th_thaiwater.issue_codes import ThThaiWaterObservationIssueCodes

PROVIDER_ID = ProviderId("th_thaiwater")
BANGKOK_TZ = ZoneInfo("Asia/Bangkok")

_DATA_SCHEMA = {
    "time": pl.Datetime(time_unit="us", time_zone="UTC"),
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
class ThThaiWaterProductPolicy:
    product_id: str
    native_field: str
    aggregate_daily: bool
    native_unit: str
    canonical_unit: str


@dataclass(frozen=True)
class ThThaiWaterTransformedSeries:
    data: pl.DataFrame
    row_annotations: pl.DataFrame
    series_annotations: pl.DataFrame
    issues: tuple[Issue, ...]


PRODUCT_POLICIES: dict[str, ThThaiWaterProductPolicy] = {
    "stage_daily_mean": ThThaiWaterProductPolicy(
        product_id="stage_daily_mean",
        native_field="value_field",
        aggregate_daily=True,
        native_unit="m",
        canonical_unit="m",
    ),
    "stage_instantaneous": ThThaiWaterProductPolicy(
        product_id="stage_instantaneous",
        native_field="value_field",
        aggregate_daily=False,
        native_unit="m",
        canonical_unit="m",
    ),
    "discharge_daily_mean": ThThaiWaterProductPolicy(
        product_id="discharge_daily_mean",
        native_field="discharge_field",
        aggregate_daily=True,
        native_unit="m3/s",
        canonical_unit="m3/s",
    ),
    "discharge_instantaneous": ThThaiWaterProductPolicy(
        product_id="discharge_instantaneous",
        native_field="discharge_field",
        aggregate_daily=False,
        native_unit="m3/s",
        canonical_unit="m3/s",
    ),
}


def resolve_product_policy(product_id: str) -> ThThaiWaterProductPolicy:
    from rivretrieve._internal.issues import InvalidObservationRequestError

    if product_id not in PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported th_thaiwater observation product: {product_id}")
    return PRODUCT_POLICIES[product_id]


def transform_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: ThThaiWaterProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
) -> ThThaiWaterTransformedSeries:
    if records.is_empty():
        return ThThaiWaterTransformedSeries(
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
                    ThThaiWaterObservationIssueCodes.MISSING_DATA,
                    "No rows after transformation",
                    {"station_id": station_id, "product_id": policy.product_id},
                ),
            ),
        )

    # Drop rows where the native field is null
    field_col = policy.native_field
    valid = records.filter(pl.col(field_col).is_not_null())

    if valid.is_empty():
        return ThThaiWaterTransformedSeries(
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
                    ThThaiWaterObservationIssueCodes.MISSING_DATA,
                    f"No rows with non-null {policy.native_field} field",
                    {"station_id": station_id, "product_id": policy.product_id},
                ),
            ),
        )

    if policy.aggregate_daily:
        # Group by Bangkok calendar date, take mean, assign Bangkok midnight UTC
        working = valid.with_columns(
            pl.col("time").dt.convert_time_zone("Asia/Bangkok").dt.truncate("1d").alias("bangkok_day"),
        )
        daily = working.group_by("bangkok_day").agg(pl.col(field_col).mean().alias("value")).sort("bangkok_day")
        # Convert Bangkok midnight back to UTC
        data_rows: list[dict[str, object]] = []
        row_ann_rows: list[dict[str, object]] = []
        for row in daily.iter_rows(named=True):
            bangkok_day = row["bangkok_day"]
            if not isinstance(bangkok_day, datetime):
                continue
            utc_dt = bangkok_day.astimezone(UTC)
            raw = row["value"]
            if raw is None:
                continue
            if not isinstance(raw, float):
                raw = float(raw)
            data_rows.append(
                {
                    "time": utc_dt,
                    "station_id": station_id,
                    "product_id": policy.product_id,
                    "value": raw,
                }
            )
            ann_time = utc_dt.replace(tzinfo=None)
            for annotation, ann_value in {
                "native_field": policy.native_field,
                "native_unit": policy.native_unit,
                "converted_unit": policy.canonical_unit,
            }.items():
                row_ann_rows.append(
                    {
                        "time": ann_time,
                        "station_id": station_id,
                        "product_id": policy.product_id,
                        "annotation": annotation,
                        "value": ann_value,
                    }
                )
    else:
        # Instantaneous: deduplicate by time (keep last), preserve per-row annotations
        deduped = valid.sort("time").unique(subset=["time"], keep="last", maintain_order=True)
        data_rows = []
        row_ann_rows = []
        for row in deduped.iter_rows(named=True):
            t = row["time"]
            if not isinstance(t, datetime):
                continue
            raw = row[field_col]
            if raw is None:
                continue
            if not isinstance(raw, float):
                raw = float(raw)
            data_rows.append(
                {
                    "time": t,
                    "station_id": station_id,
                    "product_id": policy.product_id,
                    "value": raw,
                }
            )
            ann_time = t.replace(tzinfo=None) if t.tzinfo is not None else t
            for annotation, ann_value in {
                "native_field": policy.native_field,
                "native_unit": policy.native_unit,
                "converted_unit": policy.canonical_unit,
                "raw_value": _float_string(raw),
            }.items():
                row_ann_rows.append(
                    {
                        "time": ann_time,
                        "station_id": station_id,
                        "product_id": policy.product_id,
                        "annotation": annotation,
                        "value": ann_value,
                    }
                )

    if not data_rows:
        return ThThaiWaterTransformedSeries(
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
                    ThThaiWaterObservationIssueCodes.MISSING_DATA,
                    "No observation rows remained after transformation",
                    {"station_id": station_id, "product_id": policy.product_id},
                ),
            ),
        )

    data_df = pl.DataFrame(data_rows, schema=_DATA_SCHEMA).sort(["station_id", "product_id", "time"])
    ann_df = pl.DataFrame(row_ann_rows, schema=_ROW_ANNOTATION_SCHEMA)

    times_list = data_df["time"].to_list()
    returned_start = times_list[0] if times_list else None
    returned_end = times_list[-1] if times_list else None

    tz_issues: tuple[Issue, ...] = (
        _info_issue(
            ThThaiWaterObservationIssueCodes.TIMEZONE_LOCAL_TO_UTC,
            "ThaiWater timestamps are in Asia/Bangkok local time and have been converted to UTC",
            {"station_id": station_id, "product_id": policy.product_id, "local_timezone": "Asia/Bangkok"},
        ),
    )

    return ThThaiWaterTransformedSeries(
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
        issues=tz_issues,
    )


def empty_data() -> pl.DataFrame:
    return pl.DataFrame(schema=_DATA_SCHEMA)


def empty_row_annotations() -> pl.DataFrame:
    return pl.DataFrame(schema=_ROW_ANNOTATION_SCHEMA)


def empty_series_annotations() -> pl.DataFrame:
    return pl.DataFrame(schema=_SERIES_ANNOTATION_SCHEMA)


def _series_annotations(
    *,
    station_id: str,
    policy: ThThaiWaterProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
    returned_start: object,
    returned_end: object,
) -> pl.DataFrame:
    values: dict[str, str | None] = {
        "native_field": policy.native_field,
        "native_unit_returned": policy.native_unit,
        "converted_unit": policy.canonical_unit,
        "aggregate_daily": str(policy.aggregate_daily).lower(),
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "resolved_timezone": "UTC",
        "timezone_source": "local_to_utc_conversion",
        "local_timezone": "Asia/Bangkok",
        "provider_endpoints": json.dumps(list(endpoints), sort_keys=True, separators=(",", ":")),
        "requested_windows": json.dumps([list(w) for w in windows], sort_keys=True, separators=(",", ":")),
    }
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
    code: ThThaiWaterObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)


def _info_issue(
    code: ThThaiWaterObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="info", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

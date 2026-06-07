from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.issues import InvalidObservationRequestError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.pl_imgw.issue_codes import PlImgwObservationIssueCodes

PROVIDER_ID = ProviderId("pl_imgw")

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
class PlImgwProductPolicy:
    product_id: str
    source_column: str  # column in cache records: level_cm | flow_m3s | temp_c
    native_unit: str
    canonical_unit: str
    unit_conversion: str | None  # "divide_by_100" | None


@dataclass(frozen=True)
class PlImgwTransformedSeries:
    data: pl.DataFrame
    row_annotations: pl.DataFrame
    series_annotations: pl.DataFrame
    issues: tuple[Issue, ...]


PRODUCT_POLICIES: dict[str, PlImgwProductPolicy] = {
    "discharge_daily_mean": PlImgwProductPolicy(
        product_id="discharge_daily_mean",
        source_column="flow_m3s",
        native_unit="m3/s",
        canonical_unit="m3/s",
        unit_conversion=None,
    ),
    "stage_daily_mean": PlImgwProductPolicy(
        product_id="stage_daily_mean",
        source_column="level_cm",
        native_unit="cm",
        canonical_unit="m",
        unit_conversion="divide_by_100",
    ),
    "water_temperature_daily_mean": PlImgwProductPolicy(
        product_id="water_temperature_daily_mean",
        source_column="temp_c",
        native_unit="degC",
        canonical_unit="degC",
        unit_conversion=None,
    ),
}


def resolve_product_policy(product_id: str) -> PlImgwProductPolicy:
    if product_id not in PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported pl_imgw observation product: {product_id!r}")
    return PRODUCT_POLICIES[product_id]


def convert_value(policy: PlImgwProductPolicy, raw: float) -> float:
    if policy.unit_conversion == "divide_by_100":
        return raw / 100.0
    return raw


def transform_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: PlImgwProductPolicy,
    cache_path: Path,
) -> PlImgwTransformedSeries:
    if records.is_empty():
        return PlImgwTransformedSeries(
            data=empty_data(),
            row_annotations=empty_row_annotations(),
            series_annotations=_series_annotations(
                station_id=station_id,
                policy=policy,
                cache_path=cache_path,
                returned_start=None,
                returned_end=None,
            ),
            issues=(
                _issue(
                    PlImgwObservationIssueCodes.MISSING_DATA,
                    "No rows for station after filtering",
                    {"station_id": station_id, "product_id": policy.product_id},
                ),
            ),
        )

    rows_data: list[dict[str, object]] = []
    rows_ann: list[dict[str, object]] = []

    for row in records.iter_rows(named=True):
        t = row["time"]
        if not isinstance(t, datetime):
            continue
        raw = row[policy.source_column]
        if raw is None:
            continue
        raw = float(raw)
        value = convert_value(policy, raw)

        rows_data.append(
            {
                "time": t,
                "station_id": station_id,
                "product_id": policy.product_id,
                "value": value,
            }
        )
        ann_time = t.replace(tzinfo=None) if t.tzinfo is not None else t
        for annotation, ann_value in {
            "native_unit": policy.native_unit,
            "converted_unit": policy.canonical_unit,
            "raw_value": _float_str(raw),
            "timezone_source": "date_only_utc_midnight",
            "date_only_timestamp_flag": "true",
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
        return PlImgwTransformedSeries(
            data=empty_data(),
            row_annotations=empty_row_annotations(),
            series_annotations=_series_annotations(
                station_id=station_id,
                policy=policy,
                cache_path=cache_path,
                returned_start=None,
                returned_end=None,
            ),
            issues=(
                _issue(
                    PlImgwObservationIssueCodes.MISSING_DATA,
                    "All rows for station-product have null values after sentinel removal",
                    {"station_id": station_id, "product_id": policy.product_id},
                ),
            ),
        )

    data_df = pl.DataFrame(rows_data, schema=_DATA_SCHEMA).sort(["station_id", "product_id", "time"])
    ann_df = pl.DataFrame(rows_ann, schema=_ROW_ANNOTATION_SCHEMA)

    times = data_df["time"].to_list()
    returned_start = times[0] if times else None
    returned_end = times[-1] if times else None

    return PlImgwTransformedSeries(
        data=data_df,
        row_annotations=ann_df,
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            cache_path=cache_path,
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


def _series_annotations(
    *,
    station_id: str,
    policy: PlImgwProductPolicy,
    cache_path: Path,
    returned_start: object,
    returned_end: object,
) -> pl.DataFrame:
    values: dict[str, str | None] = {
        "source_column": policy.source_column,
        "native_unit_returned": policy.native_unit,
        "converted_unit": policy.canonical_unit,
        "timezone_source": "date_only_utc_midnight",
        "date_only_timestamp_flag": "true",
        "resolved_timezone": "UTC",
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "cache_source": str(cache_path),
    }
    return pl.DataFrame(
        [
            {
                "station_id": station_id,
                "product_id": policy.product_id,
                "annotation": k,
                "value": v,
            }
            for k, v in values.items()
        ],
        schema=_SERIES_ANNOTATION_SCHEMA,
    )


def _float_str(v: float) -> str:
    return format(v, ".15g")


def _iso_z(value: object) -> str:
    if isinstance(value, datetime):
        value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _issue(
    code: PlImgwObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

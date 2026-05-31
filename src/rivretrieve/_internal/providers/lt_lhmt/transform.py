from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.lt_lhmt.issue_codes import LtLhmtObservationIssueCodes

PROVIDER_ID = ProviderId("lt_lhmt")
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
class LtLhmtProductPolicy:
    product_id: str
    native_field: str
    native_unit: str
    canonical_unit: str
    unit_conversion: str | None


@dataclass(frozen=True)
class LtLhmtTransformedSeries:
    data: pl.DataFrame
    row_annotations: pl.DataFrame
    series_annotations: pl.DataFrame
    issues: tuple[Issue, ...]


PRODUCT_POLICIES: dict[str, LtLhmtProductPolicy] = {
    "discharge_daily_mean": LtLhmtProductPolicy(
        product_id="discharge_daily_mean",
        native_field="waterDischarge",
        native_unit="m3/s",
        canonical_unit="m3/s",
        unit_conversion=None,
    ),
    "stage_daily_mean": LtLhmtProductPolicy(
        product_id="stage_daily_mean",
        native_field="waterLevel",
        native_unit="cm",
        canonical_unit="m",
        unit_conversion="divide_by_100",
    ),
}


def resolve_product_policy(product_id: str) -> LtLhmtProductPolicy:
    from rivretrieve._internal.issues import InvalidObservationRequestError

    if product_id not in PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported lt_lhmt observation product: {product_id}")
    return PRODUCT_POLICIES[product_id]


def convert_value(policy: LtLhmtProductPolicy, raw_value: float) -> float:
    if policy.unit_conversion == "divide_by_100":
        return raw_value / 100.0
    return raw_value


def transform_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: LtLhmtProductPolicy,
    year_months: tuple[str, ...],
    endpoints: tuple[str, ...],
    date_only_timestamp: bool = False,
) -> LtLhmtTransformedSeries:
    if records.is_empty():
        return LtLhmtTransformedSeries(
            data=empty_data(),
            row_annotations=empty_row_annotations(),
            series_annotations=_series_annotations(
                station_id=station_id,
                policy=policy,
                year_months=year_months,
                endpoints=endpoints,
                returned_start=None,
                returned_end=None,
                date_only_timestamp=date_only_timestamp,
            ),
            issues=(
                _issue(
                    LtLhmtObservationIssueCodes.MISSING_DATA,
                    "No rows after transformation",
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
        raw = row["native_value"]
        if not isinstance(raw, float):
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
            "native_field": policy.native_field,
            "native_unit": policy.native_unit,
            "converted_unit": policy.canonical_unit,
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
        return LtLhmtTransformedSeries(
            data=empty_data(),
            row_annotations=empty_row_annotations(),
            series_annotations=_series_annotations(
                station_id=station_id,
                policy=policy,
                year_months=year_months,
                endpoints=endpoints,
                returned_start=None,
                returned_end=None,
                date_only_timestamp=date_only_timestamp,
            ),
            issues=(
                _issue(
                    LtLhmtObservationIssueCodes.MISSING_DATA,
                    "No observation rows remained after transformation",
                    {"station_id": station_id, "product_id": policy.product_id},
                ),
            ),
        )

    data_df = pl.DataFrame(rows_data, schema=_DATA_SCHEMA).sort(["station_id", "product_id", "time"])
    ann_df = pl.DataFrame(rows_ann, schema=_ROW_ANNOTATION_SCHEMA)

    times_list = data_df["time"].to_list()
    returned_start = times_list[0] if times_list else None
    returned_end = times_list[-1] if times_list else None

    return LtLhmtTransformedSeries(
        data=data_df,
        row_annotations=ann_df,
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            year_months=year_months,
            endpoints=endpoints,
            returned_start=returned_start,
            returned_end=returned_end,
            date_only_timestamp=date_only_timestamp,
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
    policy: LtLhmtProductPolicy,
    year_months: tuple[str, ...],
    endpoints: tuple[str, ...],
    returned_start: object,
    returned_end: object,
    date_only_timestamp: bool,
) -> pl.DataFrame:
    values: dict[str, str | None] = {
        "native_field": policy.native_field,
        "native_unit_returned": policy.native_unit,
        "converted_unit": policy.canonical_unit,
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "resolved_timezone": "UTC",
        "date_only_timestamp_flag": _bool_string(date_only_timestamp),
        "provider_endpoints": json.dumps(list(endpoints), sort_keys=True, separators=(",", ":")),
        "requested_year_months": json.dumps(list(year_months), sort_keys=True, separators=(",", ":")),
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


def _bool_string(value: bool) -> str:
    return "true" if value else "false"


def _iso_z(value: object) -> str:
    if isinstance(value, datetime):
        value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _issue(code: LtLhmtObservationIssueCodes, message: str, details: dict[str, object] | None) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

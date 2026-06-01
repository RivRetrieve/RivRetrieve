from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.usgs_nwis.issue_codes import UsgsNwisObservationIssueCodes

PROVIDER_ID = ProviderId("usgs_nwis")
UTC_DTYPE = pl.Datetime(time_unit="us", time_zone="UTC")

_CFS_TO_M3S = 0.0283168466
_FT_TO_M = 0.3048

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
class UsgsNwisProductPolicy:
    product_id: str
    param_code: str
    stat_code: str | None
    endpoint: str
    native_unit: str
    canonical_unit: str
    unit_conversion: str


@dataclass(frozen=True)
class UsgsNwisTransformedSeries:
    data: pl.DataFrame
    row_annotations: pl.DataFrame
    series_annotations: pl.DataFrame
    issues: tuple[Issue, ...]


PRODUCT_POLICIES: dict[str, UsgsNwisProductPolicy] = {
    "discharge_daily_mean": UsgsNwisProductPolicy(
        product_id="discharge_daily_mean",
        param_code="00060",
        stat_code="00003",
        endpoint="dv",
        native_unit="ft3/s",
        canonical_unit="m3/s",
        unit_conversion="cfs_to_m3s",
    ),
    "discharge_instantaneous": UsgsNwisProductPolicy(
        product_id="discharge_instantaneous",
        param_code="00060",
        stat_code=None,
        endpoint="iv",
        native_unit="ft3/s",
        canonical_unit="m3/s",
        unit_conversion="cfs_to_m3s",
    ),
    "stage_daily_mean": UsgsNwisProductPolicy(
        product_id="stage_daily_mean",
        param_code="00065",
        stat_code="00003",
        endpoint="dv",
        native_unit="ft",
        canonical_unit="m",
        unit_conversion="ft_to_m",
    ),
    "stage_daily_max": UsgsNwisProductPolicy(
        product_id="stage_daily_max",
        param_code="00065",
        stat_code="00001",
        endpoint="dv",
        native_unit="ft",
        canonical_unit="m",
        unit_conversion="ft_to_m",
    ),
    "stage_daily_min": UsgsNwisProductPolicy(
        product_id="stage_daily_min",
        param_code="00065",
        stat_code="00002",
        endpoint="dv",
        native_unit="ft",
        canonical_unit="m",
        unit_conversion="ft_to_m",
    ),
    "stage_instantaneous": UsgsNwisProductPolicy(
        product_id="stage_instantaneous",
        param_code="00065",
        stat_code=None,
        endpoint="iv",
        native_unit="ft",
        canonical_unit="m",
        unit_conversion="ft_to_m",
    ),
}


def resolve_product_policy(product_id: str) -> UsgsNwisProductPolicy:
    from rivretrieve._internal.issues import InvalidObservationRequestError

    if product_id not in PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported usgs_nwis observation product: {product_id}")
    return PRODUCT_POLICIES[product_id]


def convert_value(policy: UsgsNwisProductPolicy, raw_value: float) -> float:
    if policy.unit_conversion == "cfs_to_m3s":
        return raw_value * _CFS_TO_M3S
    if policy.unit_conversion == "ft_to_m":
        return raw_value * _FT_TO_M
    return raw_value


def transform_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: UsgsNwisProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
) -> UsgsNwisTransformedSeries:
    if records.is_empty():
        return UsgsNwisTransformedSeries(
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
                    UsgsNwisObservationIssueCodes.MISSING_DATA,
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
        qualifier = row.get("qualifier", "")
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
            "native_field": policy.param_code,
            "native_unit": policy.native_unit,
            "converted_unit": policy.canonical_unit,
            "raw_value": _float_string(raw),
            "qualifier": qualifier if isinstance(qualifier, str) else "",
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
        return UsgsNwisTransformedSeries(
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
                    UsgsNwisObservationIssueCodes.MISSING_DATA,
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

    return UsgsNwisTransformedSeries(
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


def _series_annotations(
    *,
    station_id: str,
    policy: UsgsNwisProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
    returned_start: object,
    returned_end: object,
) -> pl.DataFrame:
    values: dict[str, str | None] = {
        "native_field": policy.param_code,
        "native_unit_returned": policy.native_unit,
        "converted_unit": policy.canonical_unit,
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "resolved_timezone": "UTC",
        "timezone_source": "provider_timestamp_offset",
        "provider_endpoints": json.dumps(list(endpoints), sort_keys=True, separators=(",", ":")),
        "requested_windows": json.dumps([list(w) for w in windows], sort_keys=True, separators=(",", ":")),
        "endpoint_type": policy.endpoint,
        "param_code": policy.param_code,
        "stat_code": policy.stat_code if policy.stat_code is not None else "",
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
    code: UsgsNwisObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

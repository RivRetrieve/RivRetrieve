from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.jp_mlit.issue_codes import JpMlitObservationIssueCodes

PROVIDER_ID = ProviderId("jp_mlit")
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
class JpMlitProductPolicy:
    product_id: str
    kind: int  # MLIT KIND value: 2, 3, 6, 7
    frequency: str  # "hourly" | "daily"
    native_unit: str  # "m" or "m3/s" (no conversion needed)
    canonical_unit: str
    timezone_handling: str  # "jst_to_utc" | "date_only_utc_midnight"


@dataclass(frozen=True)
class JpMlitTransformedSeries:
    data: pl.DataFrame
    row_annotations: pl.DataFrame
    series_annotations: pl.DataFrame
    issues: tuple[Issue, ...]


PRODUCT_POLICIES: dict[str, JpMlitProductPolicy] = {
    "stage_daily_mean": JpMlitProductPolicy(
        product_id="stage_daily_mean",
        kind=3,
        frequency="daily",
        native_unit="m",
        canonical_unit="m",
        timezone_handling="date_only_utc_midnight",
    ),
    "discharge_daily_mean": JpMlitProductPolicy(
        product_id="discharge_daily_mean",
        kind=7,
        frequency="daily",
        native_unit="m3/s",
        canonical_unit="m3/s",
        timezone_handling="date_only_utc_midnight",
    ),
    "stage_hourly_mean": JpMlitProductPolicy(
        product_id="stage_hourly_mean",
        kind=2,
        frequency="hourly",
        native_unit="m",
        canonical_unit="m",
        timezone_handling="jst_to_utc",
    ),
    "discharge_hourly_mean": JpMlitProductPolicy(
        product_id="discharge_hourly_mean",
        kind=6,
        frequency="hourly",
        native_unit="m3/s",
        canonical_unit="m3/s",
        timezone_handling="jst_to_utc",
    ),
}


def resolve_product_policy(product_id: str) -> JpMlitProductPolicy:
    from rivretrieve._internal.issues import InvalidObservationRequestError

    if product_id not in PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported jp_mlit observation product: {product_id}")
    return PRODUCT_POLICIES[product_id]


def transform_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: JpMlitProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
) -> JpMlitTransformedSeries:
    if records.is_empty():
        return _empty_series(station_id, policy, windows, endpoints, "No rows after transformation")

    valid = records.filter(pl.col("raw_value").is_not_null())
    if valid.is_empty():
        return _empty_series(station_id, policy, windows, endpoints, "No rows with non-null raw_value")

    # Deduplicate by time (keep last).
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
                "value": raw,  # no unit conversion needed
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

    return JpMlitTransformedSeries(
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
    policy: JpMlitProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
    reason: str,
) -> JpMlitTransformedSeries:
    return JpMlitTransformedSeries(
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
                JpMlitObservationIssueCodes.MISSING_DATA,
                reason,
                {"station_id": station_id, "product_id": policy.product_id},
            ),
        ),
    )


def _series_annotations(
    *,
    station_id: str,
    policy: JpMlitProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
    returned_start: object,
    returned_end: object,
) -> pl.DataFrame:
    # Timezone annotation values.
    if policy.timezone_handling == "date_only_utc_midnight":
        timezone_source = "date_only_utc_midnight"
        date_only_flag = "true"
    else:
        timezone_source = "local_to_utc_conversion"
        date_only_flag = None

    values: dict[str, str | None] = {
        "kind": str(policy.kind),
        "native_unit_returned": policy.native_unit,
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "resolved_timezone": "UTC",
        "timezone_source": timezone_source,
        "provider_endpoints": json.dumps(list(endpoints), sort_keys=True, separators=(",", ":")),
        "requested_windows": json.dumps([list(w) for w in windows], sort_keys=True, separators=(",", ":")),
    }
    if policy.timezone_handling == "jst_to_utc":
        values["local_timezone"] = "Asia/Tokyo"
    if date_only_flag is not None:
        values["date_only_timestamp_flag"] = date_only_flag

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
    code: JpMlitObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

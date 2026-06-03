from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.fr_hubeau.issue_codes import FrHubeauObservationIssueCodes

PROVIDER_ID = ProviderId("fr_hubeau")
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
class FrHubeauProductPolicy:
    product_id: str
    grandeur_code: str
    native_unit: str
    canonical_unit: str
    conversion_factor: float


@dataclass(frozen=True)
class FrHubeauTransformedSeries:
    data: pl.DataFrame
    row_annotations: pl.DataFrame
    series_annotations: pl.DataFrame
    issues: tuple[Issue, ...]


PRODUCT_POLICIES: dict[str, FrHubeauProductPolicy] = {
    "discharge_daily_mean": FrHubeauProductPolicy(
        product_id="discharge_daily_mean",
        grandeur_code="QmnJ",
        native_unit="l/s",
        canonical_unit="m3/s",
        conversion_factor=1000.0,
    ),
    "stage_daily_max": FrHubeauProductPolicy(
        product_id="stage_daily_max",
        grandeur_code="HIXnJ",
        native_unit="mm",
        canonical_unit="m",
        conversion_factor=1000.0,
    ),
}

GRANDEUR_TO_PRODUCT: dict[str, str] = {p.grandeur_code: p.product_id for p in PRODUCT_POLICIES.values()}


def resolve_product_policy(product_id: str) -> FrHubeauProductPolicy:
    from rivretrieve._internal.issues import InvalidObservationRequestError

    if product_id not in PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported fr_hubeau observation product: {product_id}")
    return PRODUCT_POLICIES[product_id]


def transform_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: FrHubeauProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
) -> FrHubeauTransformedSeries:
    if records.is_empty():
        return FrHubeauTransformedSeries(
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
                    FrHubeauObservationIssueCodes.MISSING_DATA,
                    "No rows after transformation",
                    {"station_id": station_id, "product_id": policy.product_id},
                ),
            ),
        )

    valid = records.filter(pl.col("raw_value").is_not_null())

    if valid.is_empty():
        return FrHubeauTransformedSeries(
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
                    FrHubeauObservationIssueCodes.MISSING_DATA,
                    "No rows with non-null raw_value",
                    {"station_id": station_id, "product_id": policy.product_id},
                ),
            ),
        )

    # Deduplicate by time (keep last), preserving the native Hubeau daily timestamp.
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
        value = raw / policy.conversion_factor

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
            "grandeur_code": policy.grandeur_code,
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
        return FrHubeauTransformedSeries(
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
                    FrHubeauObservationIssueCodes.MISSING_DATA,
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

    return FrHubeauTransformedSeries(
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
    policy: FrHubeauProductPolicy,
    windows: tuple[tuple[str, str], ...],
    endpoints: tuple[str, ...],
    returned_start: object,
    returned_end: object,
) -> pl.DataFrame:
    values: dict[str, str | None] = {
        "grandeur_code": policy.grandeur_code,
        "native_unit_returned": policy.native_unit,
        "converted_unit": policy.canonical_unit,
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "resolved_timezone": "UTC",
        "date_only_timestamp_flag": "true",
        "timezone_source": "date_only_utc_midnight",
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
    code: FrHubeauObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

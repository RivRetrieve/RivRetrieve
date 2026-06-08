from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from rivretrieve._internal.issues import InvalidObservationRequestError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ba_fhmzbih.issue_codes import BaFhmzbihObservationIssueCodes

PROVIDER_ID = ProviderId("ba_fhmzbih")
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
class BaFhmzbihProductPolicy:
    product_id: str
    parameter_code: str  # "Q", "H", or "WT"
    workbook_file: str  # "Q_1Y.xlsx", "H_1Y.xlsx", "Tvode_1Y.xlsx"
    native_unit: str
    canonical_unit: str
    conversion_factor: float  # divide raw by this to get canonical units
    aggregate_daily: bool


@dataclass(frozen=True)
class BaFhmzbihTransformedSeries:
    data: pl.DataFrame
    row_annotations: pl.DataFrame
    series_annotations: pl.DataFrame
    issues: tuple[Issue, ...]


PRODUCT_POLICIES: dict[str, BaFhmzbihProductPolicy] = {
    "discharge_instantaneous": BaFhmzbihProductPolicy(
        product_id="discharge_instantaneous",
        parameter_code="Q",
        workbook_file="Q_1Y.xlsx",
        native_unit="m3/s",
        canonical_unit="m3/s",
        conversion_factor=1.0,
        aggregate_daily=False,
    ),
    "discharge_daily_mean": BaFhmzbihProductPolicy(
        product_id="discharge_daily_mean",
        parameter_code="Q",
        workbook_file="Q_1Y.xlsx",
        native_unit="m3/s",
        canonical_unit="m3/s",
        conversion_factor=1.0,
        aggregate_daily=True,
    ),
    "stage_instantaneous": BaFhmzbihProductPolicy(
        product_id="stage_instantaneous",
        parameter_code="H",
        workbook_file="H_1Y.xlsx",
        native_unit="cm",
        canonical_unit="m",
        conversion_factor=100.0,
        aggregate_daily=False,
    ),
    "stage_daily_mean": BaFhmzbihProductPolicy(
        product_id="stage_daily_mean",
        parameter_code="H",
        workbook_file="H_1Y.xlsx",
        native_unit="cm",
        canonical_unit="m",
        conversion_factor=100.0,
        aggregate_daily=True,
    ),
    "water_temperature_instantaneous": BaFhmzbihProductPolicy(
        product_id="water_temperature_instantaneous",
        parameter_code="WT",
        workbook_file="Tvode_1Y.xlsx",
        native_unit="degC",
        canonical_unit="degC",
        conversion_factor=1.0,
        aggregate_daily=False,
    ),
    "water_temperature_daily_mean": BaFhmzbihProductPolicy(
        product_id="water_temperature_daily_mean",
        parameter_code="WT",
        workbook_file="Tvode_1Y.xlsx",
        native_unit="degC",
        canonical_unit="degC",
        conversion_factor=1.0,
        aggregate_daily=True,
    ),
}


def resolve_product_policy(product_id: str) -> BaFhmzbihProductPolicy:
    if product_id not in PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported ba_fhmzbih observation product: {product_id}")
    return PRODUCT_POLICIES[product_id]


def transform_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: BaFhmzbihProductPolicy,
    group: int | None,
    endpoint: str | None,
) -> BaFhmzbihTransformedSeries:
    """Transform parsed ``(time_local, raw_value)`` rows into a canonical series.

    Local naive timestamps (Europe/Sarajevo) are localized and converted to
    UTC. Daily-mean products are aggregated by *local* calendar day — matching
    the provider's hourly reporting cadence and the meaning a Bosnian
    operator would assign to "daily mean" — and the resulting daily value is
    anchored at local midnight, then converted to UTC (so the UTC hour
    reflects the +01:00/+02:00 CET/CEST offset for that date).
    """
    if records.is_empty():
        return _empty_series(station_id, policy, group, endpoint, "No rows after parsing")

    valid = records.filter(pl.col("raw_value").is_not_null()).sort("time_local")
    if valid.is_empty():
        return _empty_series(station_id, policy, group, endpoint, "No rows with non-null raw_value")

    localized = _localize_to_utc(valid)
    if localized.is_empty():
        return _empty_series(
            station_id,
            policy,
            group,
            endpoint,
            "All rows fell on a non-existent local time during a DST transition",
        )

    if policy.aggregate_daily:
        working = (
            localized.with_columns(pl.col("time_local").dt.date().alias("local_date"))
            .group_by("local_date")
            .agg(pl.col("raw_value").mean().alias("raw_value"))
            .sort("local_date")
            .with_columns(
                pl.col("local_date")
                .cast(pl.Datetime(time_unit="us"))
                .dt.replace_time_zone("Europe/Sarajevo", ambiguous="earliest", non_existent="null")
                .dt.convert_time_zone("UTC")
                .alias("time")
            )
            .drop_nulls("time")
            .select("time", "raw_value")
        )
    else:
        working = localized.select("time", "raw_value")

    if working.is_empty():
        return _empty_series(station_id, policy, group, endpoint, "No observation rows remained after transformation")

    deduped = working.unique(subset=["time"], keep="last", maintain_order=True).sort("time")

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
        for annotation, ann_value in (
            ("native_unit", policy.native_unit),
            ("converted_unit", policy.canonical_unit),
            ("raw_value", _float_string(raw)),
        ):
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
        return _empty_series(station_id, policy, group, endpoint, "No observation rows remained after transformation")

    data_df = pl.DataFrame(rows_data, schema=_DATA_SCHEMA).sort(["station_id", "product_id", "time"])
    ann_df = pl.DataFrame(rows_ann, schema=_ROW_ANNOTATION_SCHEMA)

    times_list = data_df["time"].to_list()
    returned_start = times_list[0] if times_list else None
    returned_end = times_list[-1] if times_list else None

    return BaFhmzbihTransformedSeries(
        data=data_df,
        row_annotations=ann_df,
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            group=group,
            endpoint=endpoint,
            returned_start=returned_start,
            returned_end=returned_end,
        ),
        issues=(_timezone_issue(station_id, policy.product_id),),
    )


def _localize_to_utc(records: pl.DataFrame) -> pl.DataFrame:
    return records.with_columns(
        pl.col("time_local")
        .dt.replace_time_zone("Europe/Sarajevo", ambiguous="earliest", non_existent="null")
        .dt.convert_time_zone("UTC")
        .alias("time")
    ).drop_nulls("time")


def empty_data() -> pl.DataFrame:
    return pl.DataFrame(schema=_DATA_SCHEMA)


def empty_row_annotations() -> pl.DataFrame:
    return pl.DataFrame(schema=_ROW_ANNOTATION_SCHEMA)


def empty_series_annotations() -> pl.DataFrame:
    return pl.DataFrame(schema=_SERIES_ANNOTATION_SCHEMA)


def _empty_series(
    station_id: str,
    policy: BaFhmzbihProductPolicy,
    group: int | None,
    endpoint: str | None,
    reason: str,
) -> BaFhmzbihTransformedSeries:
    return BaFhmzbihTransformedSeries(
        data=empty_data(),
        row_annotations=empty_row_annotations(),
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            group=group,
            endpoint=endpoint,
            returned_start=None,
            returned_end=None,
        ),
        issues=(
            _issue(
                BaFhmzbihObservationIssueCodes.MISSING_DATA,
                reason,
                {"station_id": station_id, "product_id": policy.product_id},
            ),
        ),
    )


def _series_annotations(
    *,
    station_id: str,
    policy: BaFhmzbihProductPolicy,
    group: int | None,
    endpoint: str | None,
    returned_start: object,
    returned_end: object,
) -> pl.DataFrame:
    values: dict[str, str | None] = {
        "native_unit_returned": policy.native_unit,
        "converted_unit": policy.canonical_unit,
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "resolved_timezone": "UTC",
        "timezone_source": "local_to_utc_conversion",
        "source_timezone": "Europe/Sarajevo",
        "aggregation": "local_calendar_day_mean" if policy.aggregate_daily else "instantaneous_hourly",
        "station_group": None if group is None else str(group),
        "provider_endpoint": endpoint,
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


def _timezone_issue(station_id: str, product_id: str) -> Issue:
    return Issue(
        severity="info",
        code=str(BaFhmzbihObservationIssueCodes.TIMEZONE_LOCAL_TO_UTC),
        message=(
            "ba_fhmzbih timestamps are published as naive local time with no UTC offset. "
            "Values are interpreted as Europe/Sarajevo local time (CET/CEST, observing EU DST) "
            "and converted to timezone-aware UTC."
        ),
        details={"station_id": station_id, "product_id": product_id, "source_timezone": "Europe/Sarajevo"},
        provider_id=PROVIDER_ID,
    )


def _float_string(value: float) -> str:
    return format(value, ".15g")


def _iso_z(value: object) -> str:
    if isinstance(value, datetime):
        value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _issue(
    code: BaFhmzbihObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

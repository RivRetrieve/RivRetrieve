from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import polars as pl

from rivretrieve._internal.issues import InvalidObservationRequestError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.za_dws.issue_codes import ZaDwsObservationIssueCodes

PROVIDER_ID = ProviderId("za_dws")

# South Africa Standard Time — UTC+2, no DST.
SAST = ZoneInfo("Africa/Johannesburg")

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
class ZaDwsProductPolicy:
    product_id: str
    data_type: str  # "Daily" | "Point"
    value_column: str  # "d_avg_fr" | "cor_flow" | "cor_level"
    native_unit: str
    canonical_unit: str
    chunk_years: int
    is_daily: bool


@dataclass(frozen=True)
class ZaDwsTransformedSeries:
    data: pl.DataFrame
    row_annotations: pl.DataFrame
    series_annotations: pl.DataFrame
    issues: tuple[Issue, ...]


PRODUCT_POLICIES: dict[str, ZaDwsProductPolicy] = {
    "discharge_daily_mean": ZaDwsProductPolicy(
        product_id="discharge_daily_mean",
        data_type="Daily",
        value_column="d_avg_fr",
        native_unit="m3/s",
        canonical_unit="m3/s",
        chunk_years=20,
        is_daily=True,
    ),
    "discharge_instantaneous": ZaDwsProductPolicy(
        product_id="discharge_instantaneous",
        data_type="Point",
        value_column="cor_flow",
        native_unit="m3/s",
        canonical_unit="m3/s",
        chunk_years=1,
        is_daily=False,
    ),
    "stage_instantaneous": ZaDwsProductPolicy(
        product_id="stage_instantaneous",
        data_type="Point",
        value_column="cor_level",
        native_unit="m",
        canonical_unit="m",
        chunk_years=1,
        is_daily=False,
    ),
}


def resolve_product_policy(product_id: str) -> ZaDwsProductPolicy:
    if product_id not in PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported za_dws observation product: {product_id!r}")
    return PRODUCT_POLICIES[product_id]


def transform_daily_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: ZaDwsProductPolicy,
    endpoint: str | None,
) -> ZaDwsTransformedSeries:
    """Transform parsed daily records (date_str, d_avg_fr) → UTC midnight timestamps."""
    if records.is_empty():
        return _empty_series(station_id, policy, endpoint, "date_only_utc_midnight")

    rows_data: list[dict[str, object]] = []
    rows_ann: list[dict[str, object]] = []

    for row in records.iter_rows(named=True):
        date_str = row.get("date_str", "")
        raw_value = row.get(policy.value_column)
        if not date_str or raw_value is None:
            continue
        try:
            dt = datetime.strptime(str(date_str), "%Y%m%d").replace(tzinfo=UTC)
        except ValueError:
            continue

        rows_data.append({"time": dt, "station_id": station_id, "product_id": policy.product_id, "value": raw_value})
        ann_time = dt.replace(tzinfo=None)
        for annotation, val in (("native_unit", policy.native_unit), ("converted_unit", policy.canonical_unit)):
            rows_ann.append(
                {
                    "time": ann_time,
                    "station_id": station_id,
                    "product_id": policy.product_id,
                    "annotation": annotation,
                    "value": val,
                }
            )

    if not rows_data:
        return _empty_series(station_id, policy, endpoint, "date_only_utc_midnight")

    data_df = pl.DataFrame(rows_data, schema=_DATA_SCHEMA).sort(["station_id", "product_id", "time"])
    ann_df = pl.DataFrame(rows_ann, schema=_ROW_ANNOTATION_SCHEMA)
    times = data_df["time"].to_list()

    date_only_issue = Issue(
        severity="warning",
        code=str(ZaDwsObservationIssueCodes.DATE_ONLY_TIMESTAMP),
        message=(
            "DWS daily timestamps are date-only (YYYYMMDD). "
            "Interpreted as UTC midnight (T00:00:00Z). True intraday timing is unknown."
        ),
        details={"station_id": station_id, "product_id": policy.product_id},
        provider_id=PROVIDER_ID,
    )

    return ZaDwsTransformedSeries(
        data=data_df,
        row_annotations=ann_df,
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            endpoint=endpoint,
            returned_start=times[0] if times else None,
            returned_end=times[-1] if times else None,
            timezone_source="date_only_utc_midnight",
            source_timezone=None,
        ),
        issues=(date_only_issue,),
    )


def transform_point_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: ZaDwsProductPolicy,
    endpoint: str | None,
) -> ZaDwsTransformedSeries:
    """Transform parsed Point records (date_str, time_str, cor_level/cor_flow) → SAST → UTC.

    DWS sub-daily observation timestamps carry no UTC offset. South Africa uses
    SAST (Africa/Johannesburg, UTC+2) with no daylight-saving transitions, so
    conversion to UTC is unambiguous: subtract 2 hours.
    """
    if records.is_empty():
        return _empty_series(station_id, policy, endpoint, "local_to_utc_conversion")

    col = policy.value_column
    working = records.drop_nulls(col)
    if working.is_empty():
        return _empty_series(station_id, policy, endpoint, "local_to_utc_conversion")

    rows_data: list[dict[str, object]] = []
    rows_ann: list[dict[str, object]] = []

    for row in working.iter_rows(named=True):
        date_str = row.get("date_str", "")
        time_str = row.get("time_str", "")
        raw_value = row.get(col)
        if not date_str or not time_str or raw_value is None:
            continue
        try:
            naive = datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
        except ValueError:
            continue

        utc_dt = naive.replace(tzinfo=SAST).astimezone(UTC)

        rows_data.append(
            {"time": utc_dt, "station_id": station_id, "product_id": policy.product_id, "value": raw_value}
        )
        ann_time = utc_dt.replace(tzinfo=None)
        for annotation, val in (("native_unit", policy.native_unit), ("converted_unit", policy.canonical_unit)):
            rows_ann.append(
                {
                    "time": ann_time,
                    "station_id": station_id,
                    "product_id": policy.product_id,
                    "annotation": annotation,
                    "value": val,
                }
            )

    if not rows_data:
        return _empty_series(station_id, policy, endpoint, "local_to_utc_conversion")

    data_df = (
        pl.DataFrame(rows_data, schema=_DATA_SCHEMA)
        .unique(subset=["time", "station_id", "product_id"], keep="last", maintain_order=True)
        .sort(["station_id", "product_id", "time"])
    )
    ann_df = pl.DataFrame(rows_ann, schema=_ROW_ANNOTATION_SCHEMA)
    times = data_df["time"].to_list()

    tz_issue = Issue(
        severity="info",
        code=str(ZaDwsObservationIssueCodes.TIMEZONE_LOCAL_TO_UTC),
        message=(
            "DWS point observation timestamps carry no UTC offset. "
            "Interpreted as South Africa Standard Time (SAST, Africa/Johannesburg, UTC+2, no DST) "
            "and converted to timezone-aware UTC."
        ),
        details={
            "station_id": station_id,
            "product_id": policy.product_id,
            "source_timezone": "Africa/Johannesburg",
        },
        provider_id=PROVIDER_ID,
    )

    return ZaDwsTransformedSeries(
        data=data_df,
        row_annotations=ann_df,
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            endpoint=endpoint,
            returned_start=times[0] if times else None,
            returned_end=times[-1] if times else None,
            timezone_source="local_to_utc_conversion",
            source_timezone="Africa/Johannesburg",
        ),
        issues=(tz_issue,),
    )


def empty_data() -> pl.DataFrame:
    return pl.DataFrame(schema=_DATA_SCHEMA)


def empty_row_annotations() -> pl.DataFrame:
    return pl.DataFrame(schema=_ROW_ANNOTATION_SCHEMA)


def empty_series_annotations() -> pl.DataFrame:
    return pl.DataFrame(schema=_SERIES_ANNOTATION_SCHEMA)


def _empty_series(
    station_id: str,
    policy: ZaDwsProductPolicy,
    endpoint: str | None,
    timezone_source: str,
) -> ZaDwsTransformedSeries:
    return ZaDwsTransformedSeries(
        data=empty_data(),
        row_annotations=empty_row_annotations(),
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            endpoint=endpoint,
            returned_start=None,
            returned_end=None,
            timezone_source=timezone_source,
            source_timezone="Africa/Johannesburg" if timezone_source == "local_to_utc_conversion" else None,
        ),
        issues=(
            Issue(
                severity="warning",
                code=str(ZaDwsObservationIssueCodes.MISSING_DATA),
                message="No observations found for this station/product combination",
                details={"station_id": station_id, "product_id": policy.product_id},
                provider_id=PROVIDER_ID,
            ),
        ),
    )


def _series_annotations(
    *,
    station_id: str,
    policy: ZaDwsProductPolicy,
    endpoint: str | None,
    returned_start: object,
    returned_end: object,
    timezone_source: str,
    source_timezone: str | None,
) -> pl.DataFrame:
    values: dict[str, str | None] = {
        "native_unit_returned": policy.native_unit,
        "converted_unit": policy.canonical_unit,
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "resolved_timezone": "UTC",
        "timezone_source": timezone_source,
        "source_timezone": source_timezone,
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


def _iso_z(value: object) -> str:
    if isinstance(value, datetime):
        value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)

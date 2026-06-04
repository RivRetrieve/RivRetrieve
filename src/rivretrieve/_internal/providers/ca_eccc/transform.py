from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl

from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ca_eccc.issue_codes import CaEcccObservationIssueCodes

PROVIDER_ID = ProviderId("ca_eccc")
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
class CaEcccProductPolicy:
    product_id: str
    table_name: str  # "DLY_FLOWS" or "DLY_LEVELS"
    value_prefix: str  # "FLOW" or "LEVEL"
    symbol_prefix: str  # "FLOW_SYMBOL" or "LEVEL_SYMBOL"
    frequency: str
    native_unit: str
    canonical_unit: str


@dataclass(frozen=True)
class CaEcccTransformedSeries:
    data: pl.DataFrame
    row_annotations: pl.DataFrame
    series_annotations: pl.DataFrame
    issues: tuple[Issue, ...]


PRODUCT_POLICIES: dict[str, CaEcccProductPolicy] = {
    "discharge_daily_mean": CaEcccProductPolicy(
        product_id="discharge_daily_mean",
        table_name="DLY_FLOWS",
        value_prefix="FLOW",
        symbol_prefix="FLOW_SYMBOL",
        frequency="daily",
        native_unit="m3/s",
        canonical_unit="m3/s",
    ),
    "stage_daily_mean": CaEcccProductPolicy(
        product_id="stage_daily_mean",
        table_name="DLY_LEVELS",
        value_prefix="LEVEL",
        symbol_prefix="LEVEL_SYMBOL",
        frequency="daily",
        native_unit="m",
        canonical_unit="m",
    ),
}


def resolve_product_policy(product_id: str) -> CaEcccProductPolicy:
    from rivretrieve._internal.issues import InvalidObservationRequestError

    if product_id not in PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported ca_eccc observation product: {product_id}")
    return PRODUCT_POLICIES[product_id]


def transform_series(
    records: pl.DataFrame,
    *,
    station_id: str,
    policy: CaEcccProductPolicy,
    query_years: tuple[int, int],
    hydat_source: str,
    data_symbols: dict[str, str],
) -> CaEcccTransformedSeries:
    if records.is_empty():
        return _empty_series(station_id, policy, query_years, hydat_source, "No records from parser")

    valid = records.filter(pl.col("raw_value").is_not_null())
    if valid.is_empty():
        return _empty_series(station_id, policy, query_years, hydat_source, "No non-null raw_value rows")

    deduped = valid.sort("time").unique(subset=["time"], keep="last", maintain_order=True)

    rows_data: list[dict[str, object]] = []
    rows_ann: list[dict[str, object]] = []

    for row in deduped.iter_rows(named=True):
        t = row["time"]
        if not isinstance(t, datetime):
            continue
        raw = row["raw_value"]
        if raw is None:
            continue
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
        symbol_code = str(row.get("symbol") or "")
        symbol_desc = data_symbols.get(symbol_code, symbol_code)

        for annotation, ann_value in {
            "native_unit": policy.native_unit,
            "raw_value": _float_string(raw),
            "quality_flag": symbol_code,
            "quality_description": symbol_desc,
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
        return _empty_series(station_id, policy, query_years, hydat_source, "No rows remained after transformation")

    data_df = pl.DataFrame(rows_data, schema=_DATA_SCHEMA).sort(["station_id", "product_id", "time"])
    ann_df = pl.DataFrame(rows_ann, schema=_ROW_ANNOTATION_SCHEMA)

    times_list = data_df["time"].to_list()
    returned_start = times_list[0] if times_list else None
    returned_end = times_list[-1] if times_list else None

    return CaEcccTransformedSeries(
        data=data_df,
        row_annotations=ann_df,
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            query_years=query_years,
            hydat_source=hydat_source,
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
    policy: CaEcccProductPolicy,
    query_years: tuple[int, int],
    hydat_source: str,
    reason: str,
) -> CaEcccTransformedSeries:
    return CaEcccTransformedSeries(
        data=empty_data(),
        row_annotations=empty_row_annotations(),
        series_annotations=_series_annotations(
            station_id=station_id,
            policy=policy,
            query_years=query_years,
            hydat_source=hydat_source,
            returned_start=None,
            returned_end=None,
        ),
        issues=(
            _issue(
                CaEcccObservationIssueCodes.MISSING_DATA,
                reason,
                {"station_id": station_id, "product_id": policy.product_id},
            ),
        ),
    )


def _series_annotations(
    *,
    station_id: str,
    policy: CaEcccProductPolicy,
    query_years: tuple[int, int],
    hydat_source: str,
    returned_start: object,
    returned_end: object,
) -> pl.DataFrame:
    values: dict[str, str | None] = {
        "hydat_table": policy.table_name,
        "hydat_value_prefix": policy.value_prefix,
        "hydat_source": hydat_source,
        "query_years": json.dumps(list(query_years), separators=(",", ":")),
        "native_unit_returned": policy.native_unit,
        "returned_time_range_start": None if returned_start is None else _iso_z(returned_start),
        "returned_time_range_end": None if returned_end is None else _iso_z(returned_end),
        "resolved_timezone": "UTC",
        "timezone_source": "date_only_utc_midnight",
        "date_only_timestamp_flag": "true",
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
    code: CaEcccObservationIssueCodes,
    message: str,
    details: dict[str, object] | None,
) -> Issue:
    return Issue(severity="warning", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)

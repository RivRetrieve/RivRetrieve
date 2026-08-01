from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path

import polars as pl

from rivretrieve._internal.issues import InvalidObservationRequestError

BUCKET = "existenzApi"
MEASUREMENT = "hydro"
MAX_WINDOW_DAYS = 366
_CATALOGUE_PATH = Path(__file__).with_name("catalogue")


@dataclass(frozen=True)
class ChFoenProductPolicy:
    product_id: str
    native_fields: tuple[str, ...]
    preferred_field: str
    fallback_field: str | None
    canonical_unit: str
    aggregate_daily: bool
    instant: bool


@dataclass(frozen=True)
class ChFoenTimeWindow:
    start: datetime
    end: datetime
    query_stop: datetime


@dataclass(frozen=True)
class ChFoenProviderCall:
    station_id: str
    product_id: str
    window: ChFoenTimeWindow
    native_fields: tuple[str, ...]
    query: str


_PRODUCT_POLICIES = {
    "discharge_daily_mean": ChFoenProductPolicy(
        product_id="discharge_daily_mean",
        native_fields=("flow", "flow_ls"),
        preferred_field="flow",
        fallback_field="flow_ls",
        canonical_unit="m3/s",
        aggregate_daily=True,
        instant=False,
    ),
    "discharge_instantaneous": ChFoenProductPolicy(
        product_id="discharge_instantaneous",
        native_fields=("flow", "flow_ls"),
        preferred_field="flow",
        fallback_field="flow_ls",
        canonical_unit="m3/s",
        aggregate_daily=False,
        instant=True,
    ),
    "stage_daily_mean": ChFoenProductPolicy(
        product_id="stage_daily_mean",
        native_fields=("height_abs", "height"),
        preferred_field="height_abs",
        fallback_field="height",
        canonical_unit="m",
        aggregate_daily=True,
        instant=False,
    ),
    "stage_instantaneous": ChFoenProductPolicy(
        product_id="stage_instantaneous",
        native_fields=("height_abs", "height"),
        preferred_field="height_abs",
        fallback_field="height",
        canonical_unit="m",
        aggregate_daily=False,
        instant=True,
    ),
    "water_temperature_daily_mean": ChFoenProductPolicy(
        product_id="water_temperature_daily_mean",
        native_fields=("temperature",),
        preferred_field="temperature",
        fallback_field=None,
        canonical_unit="degC",
        aggregate_daily=True,
        instant=False,
    ),
    "water_temperature_instantaneous": ChFoenProductPolicy(
        product_id="water_temperature_instantaneous",
        native_fields=("temperature",),
        preferred_field="temperature",
        fallback_field=None,
        canonical_unit="degC",
        aggregate_daily=False,
        instant=True,
    ),
}


def resolve_product_policy(product_id: str) -> ChFoenProductPolicy:
    if product_id not in _catalogue_product_ids() or product_id not in _PRODUCT_POLICIES:
        raise InvalidObservationRequestError(f"Unsupported ch_foen observation product: {product_id}")
    return _PRODUCT_POLICIES[product_id]


def build_calls(
    *,
    station_id: str,
    product_id: str,
    start: datetime,
    end: datetime,
) -> tuple[ChFoenProviderCall, ...]:
    policy = resolve_product_policy(product_id)
    return tuple(
        ChFoenProviderCall(
            station_id=station_id,
            product_id=product_id,
            window=window,
            native_fields=policy.native_fields,
            query=build_flux_query(station_id=station_id, native_fields=policy.native_fields, window=window),
        )
        for window in split_time_windows(start, end)
    )


def split_time_windows(start: datetime, end: datetime) -> tuple[ChFoenTimeWindow, ...]:
    start_day = _utc_midnight(start)
    end_day = _utc_midnight(end)
    if start_day > end_day:
        return ()

    windows: list[ChFoenTimeWindow] = []
    current = start_day
    while current <= end_day:
        window_end = min(end_day, current + timedelta(days=MAX_WINDOW_DAYS - 1))
        windows.append(
            ChFoenTimeWindow(
                start=current,
                end=window_end,
                query_stop=window_end + timedelta(days=1),
            )
        )
        current = window_end + timedelta(days=1)
    return tuple(windows)


def build_flux_query(*, station_id: str, native_fields: tuple[str, ...], window: ChFoenTimeWindow) -> str:
    fields_expr = " or ".join(f'r["_field"] == "{field}"' for field in native_fields)
    return (
        f'from(bucket: "{BUCKET}")'
        f" |> range(start: {_iso_z(window.start)}, stop: {_iso_z(window.query_stop)})"
        f' |> filter(fn: (r) => r["_measurement"] == "{MEASUREMENT}")'
        f' |> filter(fn: (r) => r["loc"] == "{station_id}")'
        f" |> filter(fn: (r) => {fields_expr})"
    )


def provider_query_fields_json(
    *,
    station_id: str,
    policy: ChFoenProductPolicy,
    windows: tuple[ChFoenTimeWindow, ...],
) -> str:
    value = {
        "bucket": BUCKET,
        "measurement": MEASUREMENT,
        "station_id": station_id,
        "product_id": policy.product_id,
        "native_fields": list(policy.native_fields),
        "preferred_field": policy.preferred_field,
        "fallback_field": policy.fallback_field,
        "windows": [
            {
                "range_start": _iso_z(window.start),
                "range_stop": _iso_z(window.query_stop),
            }
            for window in windows
        ],
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def native_unit_for(native_field: str) -> str:
    try:
        return {
            "flow": "m3/s",
            "flow_ls": "L/s",
            "height_abs": "m",
            "height": "m",
            "temperature": "degC",
        }[native_field]
    except KeyError as exc:
        raise InvalidObservationRequestError(f"Unknown ch_foen native field: {native_field}") from exc


def _iso_z(value: datetime) -> str:
    return _as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_midnight(value: datetime) -> datetime:
    value = _as_utc(value)
    return datetime.combine(value.date(), time.min, tzinfo=UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@lru_cache
def _catalogue_product_ids() -> frozenset[str]:
    products = pl.read_parquet(_CATALOGUE_PATH / "products.parquet")
    return frozenset(products["product_id"].to_list())

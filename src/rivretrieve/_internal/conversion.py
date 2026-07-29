"""convert : Rows × ProviderConfig × RequestedWindow → WithIssues[CanonicalRows]   (pure)"""

from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import assert_never
from zoneinfo import ZoneInfo

import polars as pl

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import (
    CanonicalRows,
    CanonicalRowsSchema,
    Daily,
    Instant,
    ProductConfig,
    ProviderConfig,
    RequestedWindow,
    Rows,
    RowsSchema,
    Unit,
    WithIssues,
    ZoneValue,
)
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId


def convert(
    rows: Rows,
    config: ProviderConfig,
    window: RequestedWindow,
) -> WithIssues[CanonicalRows]:
    validate_catalogue(rows, RowsSchema, on_issue="raise")

    product_ids = rows["product_id"].unique().to_list()
    missing_product_ids = sorted(
        product_id for product_id in product_ids if ProductId(product_id) not in config.products
    )
    if missing_product_ids:
        raise FatalContractError(f"Rows contain undeclared products: {', '.join(missing_product_ids)}")

    supplied_start = window.start
    supplied_end = window.end
    if not isinstance(supplied_start, datetime) or not isinstance(supplied_end, datetime):
        raise TypeError("requested window endpoints must be datetime values")

    canonical_records: list[dict[str, object]] = []
    unknown_station_products: set[tuple[str, str]] = set()
    unknown_row_count = 0

    for row in rows.iter_rows(named=True):
        station_id = row["station_id"]
        product_id = row["product_id"]
        native_time = row["time"]
        value = row["value"]
        row_zone = row["time_zone"]
        product = config.products[ProductId(product_id)]
        validated_zone = ZoneValue(row_zone).value

        if isinstance(product.semantics, Daily):
            if supplied_start.date() > supplied_end.date():
                raise ValueError("requested window start must not be after end")
            if (
                native_time.hour != 0
                or native_time.minute != 0
                or native_time.second != 0
                or native_time.microsecond != 0
            ):
                raise FatalContractError(
                    f"Daily row for station {station_id} and product {product_id} must have a midnight label"
                )
            keep = supplied_start.date() <= native_time.date() <= supplied_end.date()
        elif isinstance(product.semantics, Instant):
            start_utc = _endpoint_utc(supplied_start)
            end_utc = _endpoint_utc(supplied_end)
            if start_utc > end_utc:
                raise ValueError("requested window start must not be after end")
            if validated_zone == "unknown":
                keep = True
                unknown_row_count += 1
                unknown_station_products.add((station_id, product_id))
            else:
                comparison_key = native_time.replace(
                    tzinfo=_time_zone(validated_zone),
                    fold=native_time.fold,
                ).astimezone(UTC)
                keep = start_utc <= comparison_key <= end_utc
        else:
            assert_never(product.semantics)

        if keep:
            canonical_records.append(
                {
                    "time": native_time,
                    "time_zone": row_zone,
                    "station_id": station_id,
                    "product_id": product_id,
                    "value": _convert_value(value, product),
                }
            )

    issues: list[Issue] = []
    if unknown_row_count:
        issues.append(
            Issue(
                severity="warning",
                code="convert.unknown_time_zone",
                message=(
                    f"Retained {unknown_row_count} instantaneous row(s) without window clipping "
                    "because time_zone is unknown"
                ),
                details={
                    "row_count": unknown_row_count,
                    "station_products": [
                        {"station_id": station_id, "product_id": product_id}
                        for station_id, product_id in sorted(unknown_station_products)
                    ],
                },
            )
        )

    canonical_rows = pl.DataFrame(
        canonical_records,
        schema=CanonicalRowsSchema.polars_schema,
    )
    validate_catalogue(canonical_rows, CanonicalRowsSchema, on_issue="raise")
    return WithIssues(value=canonical_rows, issues=tuple(issues))


def _endpoint_utc(endpoint: datetime) -> datetime:
    if endpoint.tzinfo is None:
        return endpoint.replace(tzinfo=UTC)
    return endpoint.astimezone(UTC)


def _time_zone(value: str) -> tzinfo:
    if value.startswith(("+", "-")):
        hours, minutes = (int(part) for part in value[1:].split(":"))
        offset = timedelta(hours=hours, minutes=minutes)
        if value.startswith("-"):
            offset = -offset
        return timezone(offset)
    return ZoneInfo(value)


def _convert_value(value: float | None, product: ProductConfig) -> float | None:
    if value is None:
        return None
    match product.unit:
        case Unit.M:
            factor = 1.0
        case Unit.CM:
            factor = 0.01
        case Unit.FT:
            factor = 0.3048
        case Unit.MM:
            factor = 0.001
        case Unit.M3_S:
            factor = 1.0
        case Unit.FT3_S:
            factor = 0.028316846592
        case Unit.L_S:
            factor = 0.001
        case Unit.DEG_C:
            factor = 1.0
        case _ as unreachable:
            assert_never(unreachable)
    return value * factor

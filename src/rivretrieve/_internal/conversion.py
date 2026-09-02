"""convert : Rows × ProviderConfig × RequestedWindow → WithIssues[CanonicalRows]   (pure)"""

from datetime import datetime
from typing import assert_never

import polars as pl

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import (
    CanonicalRows,
    CanonicalRowsSchema,
    Daily,
    Hourly,
    Instant,
    ProductConfig,
    ProviderConfig,
    RequestedWindow,
    Rows,
    RowsSchema,
    Unit,
    WindowEndpoint,
    WithIssues,
    ZoneValue,
)
from rivretrieve._internal.issues import FatalContractError
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
    adapted_start = _endpoint_datetime(supplied_start)
    adapted_end = _endpoint_datetime(supplied_end)

    canonical_records: list[dict[str, object]] = []
    semantics_by_row: list[Daily | Hourly | Instant] = []

    for row in rows.iter_rows(named=True):
        station_id = row["station_id"]
        product_id = row["product_id"]
        native_time = row["time"]
        value = row["value"]
        row_zone = row["time_zone"]
        product = config.products[ProductId(product_id)]
        ZoneValue(row_zone)

        if isinstance(product.semantics, Daily):
            if (
                native_time.hour != 0
                or native_time.minute != 0
                or native_time.second != 0
                or native_time.microsecond != 0
            ):
                raise FatalContractError(
                    f"Daily row for station {station_id} and product {product_id} must have a midnight label"
                )
        elif isinstance(product.semantics, Hourly):
            if native_time.minute != 0 or native_time.second != 0 or native_time.microsecond != 0:
                raise FatalContractError(
                    f"Hourly row for station {station_id} and product {product_id} must have an on-hour label"
                )
        elif isinstance(product.semantics, Instant):
            pass
        else:
            assert_never(product.semantics)

        canonical_records.append(
            {
                "time": native_time,
                "time_zone": row_zone,
                "station_id": station_id,
                "product_id": product_id,
                "value": _convert_value(value, product),
            }
        )
        semantics_by_row.append(product.semantics)

    canonical_rows = pl.DataFrame(
        canonical_records,
        schema=CanonicalRowsSchema.polars_schema,
    )

    keep_values: list[bool] = []
    for native_time, semantics in zip(canonical_rows["time"], semantics_by_row, strict=True):
        if isinstance(semantics, Daily):
            keep_values.append(adapted_start.date() <= native_time.date() <= adapted_end.date())
        elif isinstance(semantics, Hourly | Instant):
            # Unknown interval anchoring cannot support inferred interval-overlap clipping.
            # Preserve the source label and clip it on the timestamp axis.
            keep_values.append(adapted_start <= native_time <= adapted_end)
        else:
            assert_never(semantics)
    canonical_rows = canonical_rows.filter(pl.Series(keep_values, dtype=pl.Boolean))

    validate_catalogue(canonical_rows, CanonicalRowsSchema, on_issue="raise")
    return WithIssues(value=canonical_rows, issues=())


def _endpoint_datetime(endpoint: WindowEndpoint) -> datetime:
    return datetime(
        endpoint.year,
        endpoint.month,
        endpoint.day,
        endpoint.hour,
        endpoint.minute,
        endpoint.second,
        endpoint.microsecond,
    )


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

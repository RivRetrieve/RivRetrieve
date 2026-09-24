"""Admission-checked per-segment conversion and physical window clipping."""

from collections.abc import Mapping
from datetime import datetime

import polars as pl

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import (
    CanonicalRows,
    CanonicalRowsSchema,
    ProductConfig,
    ProviderConfig,
    RequestedWindow,
    Rows,
    RowsSchema,
    WindowEndpoint,
    WithIssues,
    ZoneValue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.source_series import ClippingAxis, SourceSeries, admission, validate_series_rows


def convert(
    rows: Rows, config: ProviderConfig, window: RequestedWindow, *, series: tuple[SourceSeries, ...]
) -> WithIssues[CanonicalRows]:
    validate_native_rows(rows, config.products, series=series)
    facts = {fact.facts_id: fact for definition in series for fact in definition.facts}
    start, end = _endpoint_datetime(window.start), _endpoint_datetime(window.end)
    output: list[dict[str, object]] = []
    for row in rows.iter_rows(named=True):
        fact = facts[row["facts_id"]]
        timestamp = row["time"]
        keep = (
            start.date() <= timestamp.date() <= end.date()
            if fact.clipping_axis is ClippingAxis.CALENDAR_DATE
            else start <= timestamp <= end
        )
        if not keep:
            continue
        decision = admission(fact)
        if decision.factor is None or decision.target_unit is None:
            raise FatalContractError("Conversion received an unadmitted physical segment")
        output.append(
            {
                **row,
                "value": None if row["value"] is None else row["value"] * decision.factor,
                "quantity": fact.quantity.value,
                "unit": decision.target_unit,
            }
        )
    canonical = pl.DataFrame(output, schema=CanonicalRowsSchema.polars_schema)
    validate_catalogue(canonical, CanonicalRowsSchema, on_issue="raise")
    return WithIssues(canonical)


def _endpoint_datetime(endpoint: WindowEndpoint) -> datetime:
    return datetime.fromisoformat(endpoint.isoformat())


def validate_native_rows(
    rows: Rows, products: Mapping[ProductId, ProductConfig], *, series: tuple[SourceSeries, ...]
) -> None:
    validate_catalogue(rows, RowsSchema, on_issue="raise")
    validate_series_rows(rows, series)
    for product_id in rows["product_id"].unique():
        if ProductId(product_id) not in products:
            raise FatalContractError(f"Rows contain undeclared product: {product_id}")
    facts = {fact.facts_id: fact for definition in series for fact in definition.facts}
    for row in rows.iter_rows(named=True):
        ZoneValue(row["time_zone"])
        fact = facts[row["facts_id"]]
        if fact.label_time is not None:
            from rivretrieve._internal.engine import DailyLabelTime

            expected = DailyLabelTime(fact.label_time).components
            timestamp = row["time"]
            if (timestamp.hour, timestamp.minute, timestamp.second, timestamp.microsecond) != expected:
                raise FatalContractError(f"Source row contradicts established timestamp anchor {fact.label_time}")

"""Admission-checked per-segment conversion and physical window clipping."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import polars as pl

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.coverage import RequestedInterval
from rivretrieve._internal.engine import (
    CanonicalRows,
    CanonicalRowsSchema,
    DailyLabelTime,
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
from rivretrieve._internal.physical_window import native_window
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.source_annotations import AnnotationBundle, filter_native_with_annotations_by_mask
from rivretrieve._internal.source_series import Admission, PhysicalFacts, SourceSeries, admission, validate_series_rows


@dataclass
class WindowFactPreparation:
    """Request-scoped per-fact admission and physical-window cache."""

    series: tuple[SourceSeries, ...]
    window: RequestedWindow
    start: datetime
    end: datetime
    facts_by_id: dict[str, PhysicalFacts]
    intervals: dict[str, RequestedInterval] = field(default_factory=dict)
    admissions: dict[str, Admission] = field(default_factory=dict)

    @classmethod
    def for_request(cls, window: RequestedWindow, series: tuple[SourceSeries, ...]) -> WindowFactPreparation:
        """Prepare immutable fact lookup for ``window`` and ``series``."""
        facts_by_id: dict[str, PhysicalFacts] = {}
        for definition in series:
            for fact in definition.facts:
                existing = facts_by_id.get(fact.facts_id)
                if existing is not None and existing != fact:
                    raise FatalContractError(f"Conflicting physical fact definitions for {fact.facts_id!r}")
                facts_by_id[fact.facts_id] = fact
        return cls(
            series=series,
            window=window,
            start=_endpoint_datetime(window.start),
            end=_endpoint_datetime(window.end),
            facts_by_id=facts_by_id,
        )

    def register_series(self, series: tuple[SourceSeries, ...]) -> None:
        """Register additional source series while preserving cached intervals and admissions."""
        for definition in series:
            for fact in definition.facts:
                existing = self.facts_by_id.get(fact.facts_id)
                if existing is not None and existing != fact:
                    raise FatalContractError(f"Conflicting physical fact definitions for {fact.facts_id!r}")
                self.facts_by_id[fact.facts_id] = fact

    def prepare_intervals(
        self,
        facts_ids: Iterable[str],
        *,
        allowed_facts: set[str] | None = None,
        unknown_facts: Literal["raise", "exclude"] = "raise",
        unknown_message: str = "Native clipping references unknown physical facts",
    ) -> None:
        """Compute and cache ``native_window`` once per distinct ``facts_id``."""
        for fid in facts_ids:
            if allowed_facts is not None and fid not in allowed_facts:
                if unknown_facts == "raise":
                    raise FatalContractError(unknown_message)
                continue
            if fid in self.intervals:
                continue
            fact = self.facts_by_id.get(fid)
            if fact is None:
                if unknown_facts == "raise":
                    raise FatalContractError(unknown_message)
                continue
            self.intervals[fid] = native_window(self.start, self.end, fact)

    def prepare_admissions(self, facts_ids: Iterable[str]) -> None:
        """Compute and cache ``admission`` once per distinct ``facts_id``."""
        for fid in facts_ids:
            if fid in self.admissions:
                continue
            fact = self.facts_by_id.get(fid)
            if fact is None:
                raise FatalContractError("Conversion references unknown physical facts")
            self.admissions[fid] = admission(fact)

    def window_keep_mask(
        self,
        frame: pl.DataFrame,
        *,
        allowed_facts: set[str] | None = None,
        unknown_facts: Literal["raise", "exclude"] = "raise",
        unknown_message: str = "Native clipping references unknown physical facts",
    ) -> pl.Series:
        """Return a boolean mask selecting rows within each fact's physical ``native_window``."""
        if frame.is_empty():
            return pl.Series("_keep", [], dtype=pl.Boolean)
        present_fids = frame["facts_id"].unique().to_list()
        self.prepare_intervals(
            present_fids,
            allowed_facts=allowed_facts,
            unknown_facts=unknown_facts,
            unknown_message=unknown_message,
        )
        known_fids = [
            fid for fid in present_fids if fid in self.intervals and (allowed_facts is None or fid in allowed_facts)
        ]
        if not known_fids:
            return pl.repeat(False, frame.height, dtype=pl.Boolean, eager=True)
        unique_bounds = {(self.intervals[fid].start, self.intervals[fid].end) for fid in known_fids}
        if len(unique_bounds) == 1 and len(known_fids) == len(present_fids):
            iv_start, iv_end = next(iter(unique_bounds))
            return frame.select(
                ((pl.col("time") >= iv_start) & (pl.col("time") <= iv_end)).fill_null(False).alias("_k")
            )["_k"]
        if len(known_fids) <= 16:
            start_map = {fid: self.intervals[fid].start for fid in known_fids}
            end_map = {fid: self.intervals[fid].end for fid in known_fids}
            start_expr = pl.col("facts_id").replace_strict(start_map, default=None, return_dtype=pl.Datetime("us"))
            end_expr = pl.col("facts_id").replace_strict(end_map, default=None, return_dtype=pl.Datetime("us"))
            return frame.select(
                ((pl.col("time") >= start_expr) & (pl.col("time") <= end_expr)).fill_null(False).alias("_k")
            )["_k"]
        bounds_df = pl.DataFrame(
            {
                "facts_id": known_fids,
                "_iv_start": [self.intervals[fid].start for fid in known_fids],
                "_iv_end": [self.intervals[fid].end for fid in known_fids],
            },
            schema={"facts_id": pl.String(), "_iv_start": pl.Datetime("us"), "_iv_end": pl.Datetime("us")},
        )
        return (
            frame.select("facts_id", "time")
            .join(bounds_df, on="facts_id", how="left", maintain_order="left")
            .select(
                ((pl.col("time") >= pl.col("_iv_start")) & (pl.col("time") <= pl.col("_iv_end")))
                .fill_null(False)
                .alias("_k")
            )["_k"]
        )


def convert_with_annotations(
    rows: Rows,
    annotations: AnnotationBundle,
    config: ProviderConfig,
    window: RequestedWindow,
    *,
    series: tuple[SourceSeries, ...],
    preparation: WindowFactPreparation | None = None,
) -> tuple[WithIssues[CanonicalRows], AnnotationBundle]:
    """Validate, physically clip once per table, and convert rows alongside aligned annotations."""
    validate_native_rows(rows, config.products, series=series)
    if preparation is not None:
        preparation.register_series(series)
        prep = preparation
    else:
        prep = WindowFactPreparation.for_request(window, series)
    keep_mask = prep.window_keep_mask(rows, unknown_facts="raise")
    clipped_rows, filtered_annotations = filter_native_with_annotations_by_mask(
        rows,
        annotations,
        keep_mask,
        unmeasured_mask_fn=lambda df: prep.window_keep_mask(df, unknown_facts="exclude"),
    )
    if clipped_rows.is_empty():
        canonical = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)
        validate_catalogue(canonical, CanonicalRowsSchema, on_issue="raise")
        return WithIssues(canonical), filtered_annotations

    kept_fids = clipped_rows["facts_id"].unique().to_list()
    prep.prepare_admissions(kept_fids)
    factor_map: dict[str, float] = {}
    qty_map: dict[str, str] = {}
    unit_map: dict[str, str] = {}
    for fid in kept_fids:
        decision = prep.admissions[fid]
        qty_val = prep.facts_by_id[fid].quantity.value
        if decision.factor is None or decision.target_unit is None or qty_val is None:
            raise FatalContractError("Conversion received an unadmitted physical segment")
        factor_map[fid] = decision.factor
        qty_map[fid] = qty_val
        unit_map[fid] = decision.target_unit

    if len(kept_fids) == 1:
        fid = kept_fids[0]
        factor = factor_map[fid]
        value_expr = (pl.col("value") if factor == 1.0 else pl.col("value") * factor).cast(pl.Float64).alias("value")
        converted = clipped_rows.with_columns(
            value_expr,
            pl.lit(qty_map[fid], dtype=pl.String).alias("quantity"),
            pl.lit(unit_map[fid], dtype=pl.String).alias("unit"),
        )
    else:
        converted = clipped_rows.with_columns(
            (pl.col("value") * pl.col("facts_id").replace_strict(factor_map, return_dtype=pl.Float64))
            .cast(pl.Float64)
            .alias("value"),
            pl.col("facts_id").replace_strict(qty_map, return_dtype=pl.String).alias("quantity"),
            pl.col("facts_id").replace_strict(unit_map, return_dtype=pl.String).alias("unit"),
        )
    canonical = converted.select(list(CanonicalRowsSchema.polars_schema))
    validate_catalogue(canonical, CanonicalRowsSchema, on_issue="raise")
    return WithIssues(canonical), filtered_annotations


def convert(
    rows: Rows, config: ProviderConfig, window: RequestedWindow, *, series: tuple[SourceSeries, ...]
) -> WithIssues[CanonicalRows]:
    canonical, _ = convert_with_annotations(rows, AnnotationBundle.empty(), config, window, series=series)
    return canonical


def filter_annotations_for_window(
    rows: Rows,
    annotations: AnnotationBundle,
    window: RequestedWindow,
    *,
    series: tuple[SourceSeries, ...],
    preparation: WindowFactPreparation | None = None,
) -> AnnotationBundle:
    """Keep measured and unmeasured annotations falling within each fact's native window."""
    if annotations.is_empty:
        return annotations
    if preparation is not None:
        preparation.register_series(series)
        prep = preparation
    else:
        prep = WindowFactPreparation.for_request(window, series)
    keep_mask = prep.window_keep_mask(rows, unknown_facts="exclude")
    _, filtered = filter_native_with_annotations_by_mask(
        rows,
        annotations,
        keep_mask,
        unmeasured_mask_fn=lambda df: prep.window_keep_mask(df, unknown_facts="exclude"),
    )
    return filtered


def _endpoint_datetime(endpoint: WindowEndpoint) -> datetime:
    return datetime.fromisoformat(endpoint.isoformat())


def validate_native_rows(
    rows: Rows, products: Mapping[ProductId, ProductConfig], *, series: tuple[SourceSeries, ...]
) -> None:
    validate_catalogue(rows, RowsSchema, on_issue="raise")
    validate_series_rows(rows, series)
    if rows.is_empty():
        return
    for product_id in rows["product_id"].unique().to_list():
        if ProductId(product_id) not in products:
            raise FatalContractError(f"Rows contain undeclared product: {product_id}")
    for tz_raw in rows["time_zone"].unique().to_list():
        ZoneValue(tz_raw)
    facts_by_id = {fact.facts_id: fact for definition in series for fact in definition.facts}
    expected_us_by_fid: dict[str, int] = {}
    for fid in rows["facts_id"].unique().to_list():
        fact = facts_by_id[fid]
        if fact.label_time is not None:
            hour, minute, second, microsecond = DailyLabelTime(fact.label_time).components
            expected_us_by_fid[fid] = (((hour * 60 + minute) * 60 + second) * 1_000_000) + microsecond
    if expected_us_by_fid:
        actual_us = (
            pl.col("time").dt.hour().cast(pl.Int64) * 3_600_000_000
            + pl.col("time").dt.minute().cast(pl.Int64) * 60_000_000
            + pl.col("time").dt.second().cast(pl.Int64) * 1_000_000
            + pl.col("time").dt.microsecond().cast(pl.Int64)
        )
        expected_expr = pl.col("facts_id").replace_strict(expected_us_by_fid, default=None, return_dtype=pl.Int64)
        mismatch_mask = rows.select((expected_expr.is_not_null() & (actual_us != expected_expr)).alias("_bad"))["_bad"]
        if mismatch_mask.any():
            bad_fid = rows.filter(mismatch_mask)["facts_id"][0]
            raise FatalContractError(
                f"Source row contradicts established timestamp anchor {facts_by_id[bad_fid].label_time}"
            )

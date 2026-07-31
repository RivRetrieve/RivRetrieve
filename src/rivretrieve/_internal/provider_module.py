from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import polars as pl

from rivretrieve._internal.observations import AnnotationSchema
from rivretrieve._internal.primitives import CatalogSource, OnIssue
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.results import CatalogResult


@runtime_checkable
class ProviderModule(Protocol):
    @staticmethod
    def info() -> ProviderInfo: ...

    @staticmethod
    def products(
        *,
        source: CatalogSource = "packaged",
        observed_property: str | None = None,
        frequency: str | None = None,
        statistic: str | None = None,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]: ...

    @staticmethod
    def stations(
        *,
        source: CatalogSource = "packaged",
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]: ...

    @staticmethod
    def station_products(
        stations: Sequence[str] | None = None,
        *,
        source: CatalogSource = "packaged",
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]: ...

    @staticmethod
    def row_annotation_schema() -> list[AnnotationSchema]: ...

    @staticmethod
    def series_annotation_schema() -> list[AnnotationSchema]: ...

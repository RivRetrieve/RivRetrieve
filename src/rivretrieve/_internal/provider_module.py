from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import polars as pl

from rivretrieve._internal.primitives import OnIssue
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.results import CatalogResult


@runtime_checkable
class ProviderModule(Protocol):
    @staticmethod
    def info() -> ProviderInfo: ...

    @staticmethod
    def products(
        *,
        observed_property: str | None = None,
        frequency: str | None = None,
        statistic: str | None = None,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]: ...

    @staticmethod
    def stations(
        *,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]: ...

    @staticmethod
    def station_products(
        stations: Sequence[str] | None = None,
        *,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]: ...

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from rivretrieve._internal.catalogues.schemas import ProductCatalog, StationCatalog, StationProductCatalog
from rivretrieve._internal.observations import ObservationResult, RawMode
from rivretrieve._internal.primitives import CatalogSource, OnIssue
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.results import CatalogResult


@runtime_checkable
class ProviderHandle(Protocol):
    def info(self) -> ProviderInfo: ...

    def products(
        self,
        *,
        source: CatalogSource = "packaged",
        observed_property: str | None = None,
        frequency: str | None = None,
        statistic: str | None = None,
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[ProductCatalog]: ...

    def stations(
        self,
        *,
        source: CatalogSource = "packaged",
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[StationCatalog]: ...

    def station_products(
        self,
        stations: Sequence[str] | None = None,
        *,
        source: CatalogSource = "packaged",
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[StationProductCatalog]: ...

    def observations(
        self,
        *,
        stations: str | Sequence[str],
        products: str | Sequence[str],
        start: object,
        end: object,
        on_issue: OnIssue = "warn",
        raw: RawMode = RawMode.OMIT,
    ) -> ObservationResult: ...

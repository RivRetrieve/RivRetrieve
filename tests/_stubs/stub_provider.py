from __future__ import annotations

from collections.abc import Callable, Sequence

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.primitives import OnIssue
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.results import CatalogResult

_PROVIDER_INFO_ROW = {
    "provider_id": "stub_provider",
    "name": "stub_provider Provider",
    "live_stations": False,
    "live_products": False,
    "live_station_products": False,
    "bulk_observations": "none",
    "catalogue_version": "2026.01",
    "license": None,
    "citation": None,
}


def info() -> ProviderInfo:
    return ProviderInfo.from_row(_PROVIDER_INFO_ROW)


def products(
    *,
    observed_property: str | None = None,
    frequency: str | None = None,
    statistic: str | None = None,
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]:
    raise NotImplementedError("deferred to M2 step 02")


def stations(
    *,
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]:
    raise NotImplementedError("deferred to M2 step 02")


def station_products(
    stations: Sequence[str] | None = None,
    *,
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]:
    raise NotImplementedError("deferred to M2 step 02")


def build_artifact(
    factory: Callable[..., PackagedCatalogArtifact],
) -> PackagedCatalogArtifact:
    return factory("stub_provider")

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import polars as pl

from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact, load_packaged_catalogue_artifact
from rivretrieve._internal.primitives import OnIssue, ProviderId
from rivretrieve._internal.provider_info import ProviderInfo
from rivretrieve._internal.providers.ca_eccc.config import config as config
from rivretrieve._internal.providers.ca_eccc.config import window_declarations as window_declarations
from rivretrieve._internal.providers.ca_eccc.fetch import fetch as fetch
from rivretrieve._internal.providers.ca_eccc.observation_client import CacheStatus, HydatClient
from rivretrieve._internal.providers.ca_eccc.parse import parse as parse
from rivretrieve._internal.results import CatalogResult

PROVIDER_ID = ProviderId("ca_eccc")
_CATALOGUE_PATH = Path(__file__).with_name("catalogue")
observation_source: str = "local"


def info() -> ProviderInfo:
    return ProviderInfo.from_row(_artifact().provider_info)


def products(
    *,
    observed_property: str | None = None,
    frequency: str | None = None,
    statistic: str | None = None,
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]:
    return _reader().read_products(
        observed_property=observed_property,
        frequency=frequency,
        statistic=statistic,
        on_issue=on_issue,
    )


def stations(
    *,
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]:
    return _reader().read_stations(on_issue=on_issue)


def station_products(
    stations: Sequence[str] | None = None,
    *,
    on_issue: OnIssue = "warn",
) -> CatalogResult[pl.DataFrame]:
    return _reader().read_station_products(stations, on_issue=on_issue)


def cache_status() -> CacheStatus:
    """Return the status of the local HYDAT SQLite cache.

    Does not trigger a download. Safe to call before making any observation
    request to check whether the database is present and how old it is.

    """
    return HydatClient().cache_status()


def refresh_cache() -> list:
    """Force re-download of the HYDAT SQLite database.

    Deletes any existing cached file and downloads the latest quarterly release
    from ECCC (~1 GB zip). Blocks until complete (may take several minutes).

    Returns a list of structured ``Issue`` objects describing what happened
    (download started, complete, or failed).

    """
    return HydatClient().refresh_cache()


@lru_cache
def _artifact() -> PackagedCatalogArtifact:
    return load_packaged_catalogue_artifact(_CATALOGUE_PATH, on_issue="raise")


def _reader() -> CatalogueReader:
    return CatalogueReader(_artifact(), PROVIDER_ID)

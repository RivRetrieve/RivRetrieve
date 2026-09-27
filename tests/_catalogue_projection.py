"""Detached canonical tables for tests that inspect an unchanged catalogue build."""

from copy import deepcopy
from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class CatalogueProjection:
    provider_info: dict[str, object]
    products: pl.DataFrame
    stations: pl.DataFrame
    station_products: pl.DataFrame


def copy_catalogue_projection(catalogue):
    # Deliberately omit acquisition models and public artifacts: these fixtures
    # serve only read-only projection assertions, never loading or mutation tests.
    return CatalogueProjection(
        deepcopy(catalogue.provider_info),
        catalogue.products.clone(),
        catalogue.stations.clone(),
        catalogue.station_products.clone(),
    )

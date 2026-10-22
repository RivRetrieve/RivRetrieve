"""Synthetic catalogue and explicit stages for retained Existenz engine regressions.

These test inputs do not register an observation route in the shipped Swiss provider.
"""

from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import polars as pl

from rivretrieve._internal.catalogues.artifact import PackagedCatalogArtifact
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
)
from rivretrieve._internal.providers.ch_foen.catalogue_series import describe_catalogue
from rivretrieve._internal.providers.ch_foen.config import config, flux_window_declarations, window_declarations
from rivretrieve._internal.providers.ch_foen.fetch import fetch
from rivretrieve._internal.providers.ch_foen.parse import parse
from rivretrieve._internal.providers.registration import LiveStages, PublicArchiveAccess
from rivretrieve._internal.transport import AuthenticationCapability, CredentialHeader


def declaration_for_replay(declaration):
    def declarations(transport):
        if isinstance(transport, AuthenticationCapability) and transport.can_authenticate(
            "https://influx.konzept.space/api/v2/query"
        ):
            return flux_window_declarations()
        return window_declarations()

    stages = SimpleNamespace(
        observation_source="live",
        config=config(),
        window_declarations=window_declarations(),
        fetch=fetch,
        parse=parse,
        window_declarations_for_transport=declarations,
    )
    access = PublicArchiveAccess(
        CredentialHeader("Authorization", "Token SOURCE-READONLY-SENTINEL", ("https://influx.konzept.space",)),
        endpoint="https://influx.konzept.space/api/v2/query",
        recent_horizon=timedelta(days=32),
    )
    return replace(declaration, observations=LiveStages(stages), public_archive_access=access)


def catalogue_for_replay():
    products = pl.DataFrame(
        [
            ("ch_foen", product, quantity, "unknown", "unknown", "unknown", "unknown", unit, native)
            for product, quantity, unit, native in [
                ("discharge_reported", "discharge", "m3/s", "flow,flow_ls"),
                ("stage_reported", "water_level", "m", "height_abs,height"),
                ("water_temperature_reported", "water_temperature", "degC", "temperature"),
            ]
        ],
        schema=PRODUCT_CATALOG_SCHEMA.polars_schema,
        orient="row",
    )
    stations = pl.DataFrame(
        [("ch_foen", station, 46.0, 7.0, "unknown") for station in ("2018", "2135", "2251")],
        schema=STATION_CATALOG_SCHEMA.polars_schema,
        orient="row",
    )
    pairs = pl.DataFrame(
        [
            ("ch_foen", station, product, "unknown", "not_catalogued", None, None, date(2026, 1, 1))
            for station in stations["station_id"]
            for product in products["product_id"]
        ],
        schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema,
        orient="row",
    )
    artifact = PackagedCatalogArtifact(
        {
            "provider_id": "ch_foen",
            "name": "Synthetic replay catalogue",
            "live_stations": False,
            "live_products": False,
            "live_station_products": False,
            "bulk_observations": "synthetic",
            "catalogue_version": "2026-01-01",
            "license": None,
            "citation": None,
        },
        products,
        stations,
        pairs,
    )
    return replace(artifact, source_descriptions=describe_catalogue(artifact))

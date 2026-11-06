"""Build offline NRFA discovery tables from adopted station metadata."""

from __future__ import annotations

import polars as pl

from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.schemas import (
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    StationCatalog,
    StationProductCatalog,
)

PRODUCT_IDS = (
    "gdf",
    "ndf",
    "gmf",
    "nmf",
    "gauging-flow",
    "gauging-stage",
    "amax-flow",
    "amax-stage",
    "pot-flow",
    "pot-stage",
)


def build_stations(native_table: NativeTable) -> StationCatalog:
    return (
        native_table.data.select(
            pl.lit("uk_nrfa").alias("provider_id"),
            pl.col("id").alias("station_id"),
            "latitude",
            "longitude",
            pl.lit("EPSG:4326").alias("crs"),
        )
        .cast(STATION_CATALOG_SCHEMA.polars_schema)
        .sort("station_id")
    )


def build_station_products(native_table: NativeTable) -> StationProductCatalog:
    rows = []
    for station in native_table.data.iter_rows(named=True):
        for summary in station["data-summary"]:
            product = summary["data-type"]
            if product in PRODUCT_IDS:
                rows.append(
                    {
                        "provider_id": "uk_nrfa",
                        "station_id": station["id"],
                        "product_id": product,
                        "availability": "available",
                        "availability_reason": "Advertised in the NRFA station-info data-summary snapshot",
                        "published_record_start_date": None,
                        "published_record_end_date": None,
                        "last_catalogue_check": station["retrieved_at"].date(),
                    }
                )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).sort("station_id", "product_id")

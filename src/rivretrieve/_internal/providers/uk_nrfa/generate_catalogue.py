"""Build offline NRFA discovery tables from adopted station metadata."""

from __future__ import annotations

from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table
from rivretrieve._internal.catalogues.schemas import (
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    StationCatalog,
    StationProductCatalog,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.uk_nrfa.catalogue_series import PRODUCT_IDS


def build_stations(native_table: NativeTable) -> StationCatalog:
    return (
        native_table.data.select(
            pl.lit("uk_nrfa").alias("provider_id"),
            pl.col("station_id"),
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
        for summary in station["data-summary"]["data-types"]:
            product = summary["data-type"]
            if product in PRODUCT_IDS:
                rows.append(
                    {
                        "provider_id": "uk_nrfa",
                        "station_id": station["station_id"],
                        "product_id": product,
                        "availability": "available",
                        "availability_reason": "Advertised in the NRFA station-info data-summary snapshot",
                        "published_record_start_date": None,
                        "published_record_end_date": None,
                        "last_catalogue_check": station["retrieved_at"].date(),
                    }
                )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).sort("station_id", "product_id")


def prepare_native_table(
    station_info: dict[str, object], station_ids: dict[str, object], *, retrieved_at: RetrievedAt
) -> NativeTable:
    """Retain station-info fields after reconciling the separate UK station inventory.

    The altitude datum uses the published regional numbering convention only
    within this reconciled UK inventory. It does not define a stage datum.
    """
    rows = station_info.get("data")
    identities = station_ids.get("station-ids")
    if not isinstance(rows, list) or not rows or not isinstance(identities, list):
        raise FatalContractError("NRFA inventory responses require station rows and identifiers")
    if any(type(identity) is not int or identity < 0 for identity in identities):
        raise FatalContractError("NRFA inventory requires integer identifiers")
    if any(not isinstance(row, dict) for row in rows):
        raise FatalContractError("NRFA station row must be an object")
    station_rows = cast("list[dict[str, object]]", rows)
    source_ids = [row.get("id") for row in station_rows]
    if (
        any(type(identity) is not int for identity in source_ids)
        or len(set(source_ids)) != len(source_ids)
        or len(set(identities)) != len(identities)
        or set(source_ids) != set(identities)
    ):
        raise FatalContractError("NRFA station-info and station-ID inventory differ")
    prepared = []
    for row in station_rows:
        identity = str(row["id"])
        regional = identity.zfill(6)
        datum = None
        if len(regional) == 6:
            if regional[0] in {"0", "1"}:
                datum = "Ordnance Datum"
            elif regional[0] == "2":
                datum = "Malin Head"
        coordinates = row.get("lat-long")
        summary = row.get("data-summary")
        if not isinstance(coordinates, dict) or not isinstance(summary, dict):
            raise FatalContractError("NRFA station requires lat-long and data-summary objects")
        coordinates = cast("dict[str, object]", coordinates)
        summary = cast("dict[str, object]", summary)
        if not isinstance(summary.get("data-types"), list):
            raise FatalContractError("NRFA data-summary requires a data-types list")
        prepared.append(
            {
                **row,
                "station_id": identity,
                "latitude": coordinates.get("latitude"),
                "longitude": coordinates.get("longitude"),
                "station_altitude_datum": datum,
            }
        )
    data = (
        pl.DataFrame(prepared, infer_schema_length=None)
        .with_columns(
            pl.col("station_altitude_datum").cast(pl.String),
        )
        .sort("station_id")
    )
    return stamp_native_table(data, retrieved_at)


def build_products():
    from rivretrieve._internal.catalogues.products import product_row
    from rivretrieve._internal.catalogues.schemas import PRODUCT_CATALOG_SCHEMA
    from rivretrieve._internal.providers.uk_nrfa.catalogue_series import product_facts

    return pl.DataFrame(
        [product_row("uk_nrfa", product, product, facts) for product, facts in product_facts().items()],
        schema=PRODUCT_CATALOG_SCHEMA.polars_schema,
    ).sort("product_id")

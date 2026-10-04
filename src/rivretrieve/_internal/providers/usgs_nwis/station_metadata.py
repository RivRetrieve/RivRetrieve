"""Project station metadata within its approved issuing-agency scope."""

from __future__ import annotations

import polars as pl

from rivretrieve._internal.catalogue_origins import Field
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.station_metadata import MetadataField, build_station_metadata
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.station_metadata import source_metadata_frame


def project_station_metadata(
    native_table: NativeTable,
    stations: pl.DataFrame,
    station_origin: Field,
    fields: tuple[MetadataField, ...],
) -> pl.DataFrame:
    """Expose new elevations only for USGS-issued gauges, keeping every gauge.

    Other agencies retain the approved station-name and area fields. Their
    elevations receive no_metadata, even when native altitude cells have values.
    Observation admission and series availability do not determine this scope.
    """
    if native_table.data.schema.get("agency_cd") != pl.String or native_table.data.schema.get("site_no") != pl.String:
        raise FatalContractError("USGS station metadata requires native string agency and site identities")
    eligible = native_table.data.filter(pl.col("agency_cd") == "USGS").select(pl.col("site_no").alias("station_id"))
    usgs_stations = stations.join(eligible, on="station_id", how="semi")
    other_stations = stations.join(eligible, on="station_id", how="anti")
    source = pl.concat(
        [
            build_station_metadata("usgs_nwis", native_table, usgs_stations, station_origin, fields),
            build_station_metadata(
                "usgs_nwis",
                native_table,
                other_stations,
                station_origin,
                tuple(field for field in fields if field.attribute_role != "elevation"),
            ),
        ]
    )
    keys = stations.select(pl.lit("usgs_nwis").alias("provider_id"), "station_id")
    return source_metadata_frame(keys, source)

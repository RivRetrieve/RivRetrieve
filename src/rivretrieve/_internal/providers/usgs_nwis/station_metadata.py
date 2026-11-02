"""Project station metadata within its approved issuing-agency scope."""

from __future__ import annotations

import polars as pl

from rivretrieve._internal.catalogue_origins import Field, NativeColumn
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


def project_modern_station_metadata(
    modern_native: NativeTable,
    legacy_native: NativeTable,
    stations: pl.DataFrame,
    fields: tuple[MetadataField, ...],
) -> pl.DataFrame:
    """Project modern names with legacy quantities for matching agency and number.

    Canonical station IDs retain baseline identities and distinguish agency collisions. Legacy drainage areas
    require an exact agency-and-number match; elevations additionally require
    USGS issuance. Unmatched quantities receive no_metadata. Modern null names
    remain null even when a legacy name exists.
    """
    modern_names = build_station_metadata(
        "usgs_nwis",
        modern_native,
        stations,
        Field(NativeColumn("station_id")),
        tuple(field for field in fields if field.attribute_role == "station_name"),
    )
    matched = legacy_native.data.join(
        modern_native.data.select("agency_code", "monitoring_location_number", "station_id"),
        left_on=["agency_cd", "site_no"],
        right_on=["agency_code", "monitoring_location_number"],
        how="inner",
        validate="1:1",
    )
    quantities = []
    for usgs, eligible_fields in (
        (True, tuple(field for field in fields if field.attribute_role in ("drainage_area", "elevation"))),
        (False, tuple(field for field in fields if field.attribute_role == "drainage_area")),
    ):
        selected = matched.filter((pl.col("agency_cd") == "USGS") == usgs)
        quantities.append(
            build_station_metadata(
                "usgs_nwis",
                NativeTable(selected),
                stations.join(selected.select("station_id"), on="station_id", how="semi"),
                Field(NativeColumn("station_id")),
                eligible_fields,
            )
        )
    quantities = pl.concat(quantities).filter(pl.col("attribute_role").is_in(["drainage_area", "elevation"]))
    source = pl.concat(
        [
            modern_names.join(
                quantities.select("station_id", "attribute_role").unique(),
                on=["station_id", "attribute_role"],
                how="anti",
            ),
            quantities,
        ]
    )
    keys = stations.select(pl.lit("usgs_nwis").alias("provider_id"), "station_id")
    return source_metadata_frame(keys, source)

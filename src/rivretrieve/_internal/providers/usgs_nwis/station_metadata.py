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
    remain null even when a legacy name exists. Conflicting legacy fields are
    omitted; exact agreements remain exposed. Elevation requires agreement on
    both altitude and datum. Source strings are compared without normalization.
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
        validate="m:1",
    )
    quantities = []
    for field in fields:
        if field.attribute_role not in ("drainage_area", "elevation"):
            continue
        selected = matched
        if field.attribute_role == "elevation":
            selected = selected.filter(pl.col("agency_cd") == "USGS")
        alternatives = _field_alternatives(selected, field)
        agreed = alternatives.join(
            alternatives.group_by("station_id").len().filter(pl.col("len") == 1).select("station_id"),
            on="station_id",
            how="semi",
        )
        quantities.append(
            build_station_metadata(
                "usgs_nwis",
                NativeTable(
                    agreed.join(selected.group_by("station_id").agg(pl.col("retrieved_at").min()), on="station_id")
                ),
                stations.join(agreed.select("station_id"), on="station_id", how="semi"),
                Field(NativeColumn("station_id")),
                (field,),
            ).filter(pl.col("state") != "no_metadata")
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


def _field_alternatives(matched: pl.DataFrame, field: MetadataField) -> pl.DataFrame:
    columns = list(
        dict.fromkeys(["station_id", field.source_field, *([field.datum_field] if field.datum_field else [])])
    )
    return matched.select(columns).unique()


def legacy_metadata_conflicts(
    modern_native: NativeTable,
    legacy_native: NativeTable,
    fields: tuple[MetadataField, ...],
) -> tuple[tuple[str, str], ...]:
    """Identify omitted quantity fields, including disagreeing elevation datums."""
    matched = legacy_native.data.join(
        modern_native.data.select("agency_code", "monitoring_location_number", "station_id"),
        left_on=["agency_cd", "site_no"],
        right_on=["agency_code", "monitoring_location_number"],
        how="inner",
        validate="m:1",
    )
    conflicts = []
    for field in fields:
        if field.attribute_role not in ("drainage_area", "elevation"):
            continue
        selected = matched.filter(pl.col("agency_cd") == "USGS") if field.attribute_role == "elevation" else matched
        counts = _field_alternatives(selected, field).group_by("station_id").len()
        conflicts.extend((station, field.source_field) for station in counts.filter(pl.col("len") > 1)["station_id"])
    return tuple(sorted(conflicts))

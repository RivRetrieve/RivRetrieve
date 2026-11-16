"""Shared station metadata projection for VandA's single registry response."""

import polars as pl

from rivretrieve._internal.catalogue_origins import Field, NativeColumn
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
from rivretrieve._internal.providers.dk_vanda.origins import STATION_METADATA_FIELDS


def project_station_metadata(native: NativeTable, stations: pl.DataFrame) -> pl.DataFrame:
    """Publish the station name and catchment area, with unknowns intact.

    ``catchmentAreaKm2`` is empty for every retained station; this projects
    that absence honestly as a ``source_null`` drainage-area row rather than
    recovering a value from the free-text ``description`` field.
    """
    return build_station_metadata(
        "dk_vanda", native, stations, Field(NativeColumn("stationId")), STATION_METADATA_FIELDS
    )

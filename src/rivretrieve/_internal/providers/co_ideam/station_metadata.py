"""Shared station metadata projection for Colombia IDEAM."""

import polars as pl

from rivretrieve._internal.catalogue_origins import Field, NativeColumn
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
from rivretrieve._internal.providers.co_ideam.origins import STATION_METADATA_FIELDS


def project_station_metadata(native: NativeTable, stations: pl.DataFrame) -> pl.DataFrame:
    """Project reviewed station names, water-body names, and generic elevations under CC BY-SA 4.0."""
    return build_station_metadata("co_ideam", native, stations, Field(NativeColumn("Codigo")), STATION_METADATA_FIELDS)

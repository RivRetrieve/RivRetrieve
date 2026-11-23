"""Shared station metadata projection for Belgium - Wallonia (`be_wal`)."""

import polars as pl

from rivretrieve._internal.catalogue_origins import Field, NativeColumn
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
from rivretrieve._internal.providers.be_wal.origins import STATION_METADATA_FIELDS


def project_station_metadata(native: NativeTable, stations: pl.DataFrame) -> pl.DataFrame:
    """Project SPW station names, water-body names, and parsed catchment areas without elevation."""
    return build_station_metadata(
        "be_wal", native, stations, Field(NativeColumn("station_no")), STATION_METADATA_FIELDS
    )

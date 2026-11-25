"""Shared station metadata projection for Chile DGA."""

import polars as pl

from rivretrieve._internal.catalogue_origins import Field, NativeColumn
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
from rivretrieve._internal.providers.cl_dga.origins import STATION_METADATA_FIELDS


def project_station_metadata(native: NativeTable, stations: pl.DataFrame) -> pl.DataFrame:
    """Project DGA station names and positive altitudes while withholding ALTITUD=0."""
    return build_station_metadata(
        "cl_dga", native, stations, Field(NativeColumn("CODIGO ESTACION")), STATION_METADATA_FIELDS
    )

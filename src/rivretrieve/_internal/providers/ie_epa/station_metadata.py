"""Shared station metadata projection for Ireland EPA HydroNet."""

from __future__ import annotations

import polars as pl

from rivretrieve._internal.catalogue_origins import Field, NativeColumn
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
from rivretrieve._internal.providers.ie_epa.origins import STATION_METADATA_FIELDS


def project_station_metadata(native: NativeTable, stations: pl.DataFrame) -> pl.DataFrame:
    """Project HydroNet station names, water bodies, and inline km² catchment sizes."""
    return build_station_metadata(
        "ie_epa", native, stations, Field(NativeColumn("station_no")), STATION_METADATA_FIELDS
    )

"""Shared station metadata projection for Ireland Office of Public Works (OPW)."""

from __future__ import annotations

import polars as pl

from rivretrieve._internal.catalogue_origins import Field, NativeColumn
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
from rivretrieve._internal.providers.ie_opw.origins import STATION_METADATA_FIELDS


def project_station_metadata(native: NativeTable, stations: pl.DataFrame) -> pl.DataFrame:
    """Project OPW Hydro-Data station names, waterbodies, and inline km2 catchment sizes."""
    return build_station_metadata(
        "ie_opw", native, stations, Field(NativeColumn("station_no")), STATION_METADATA_FIELDS
    )

"""Shared station metadata projection for Estonia (Keskkonnaagentuur)."""

from __future__ import annotations

import polars as pl

from rivretrieve._internal.catalogue_origins import Field, NativeColumn
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
from rivretrieve._internal.providers.ee_est.origins import STATION_METADATA_FIELDS


def project_station_metadata(native: NativeTable, stations: pl.DataFrame) -> pl.DataFrame:
    """Project Keskkonnaagentuur station names, water-body names, and drainage areas."""
    return build_station_metadata("ee_est", native, stations, Field(NativeColumn("kkr_kood")), STATION_METADATA_FIELDS)

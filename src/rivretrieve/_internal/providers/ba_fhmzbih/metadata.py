from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaFhmzbihStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_id: str
    name: str
    river_name: str | None
    catchment_name: str | None
    latitude: float
    longitude: float
    country: str
    elevation_m: float | None
    drainage_area_km2: float | None
    source: str


class BaFhmzbihProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    parameter_code: str  # "Q", "H", or "WT"
    workbook_file: str  # "Q_1Y.xlsx", "H_1Y.xlsx", "Tvode_1Y.xlsx"
    native_unit: str
    canonical_unit: str
    unit_conversion: str | None
    aggregate_daily: bool
    notes: str | None


class BaFhmzbihStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    availability_source: str
    availability_note: str

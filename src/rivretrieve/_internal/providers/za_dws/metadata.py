from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ZaDwsStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_id: str
    name: str
    river: str | None
    description_original: str
    latitude: float
    longitude: float
    country: str
    elevation_m: float | None
    drainage_area_km2: float | None
    drainage_region: str
    wma: str


class ZaDwsProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    data_type: str
    value_column: str
    native_unit: str
    canonical_unit: str
    chunk_years: int
    notes: str


class ZaDwsStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    availability_source: str
    availability_note: str

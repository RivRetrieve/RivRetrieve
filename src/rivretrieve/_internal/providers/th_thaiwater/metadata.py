from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ThThaiWaterStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_id: str
    name: str
    name_local: str | None
    river_name: str | None
    latitude: float
    longitude: float
    country: str
    source: str
    station_code: str | None
    station_type: str
    agency: str | None
    basin: str | None
    province: str | None
    district: str | None
    subdistrict: str | None
    vertical_datum: str
    elevation_m: float | None
    drainage_area_km2: float | None


class ThThaiWaterProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_field: str
    aggregate_daily: bool
    native_unit: str
    canonical_unit: str
    notes: str | None


class ThThaiWaterStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    native_field: str
    availability_source: str
    availability_note: str

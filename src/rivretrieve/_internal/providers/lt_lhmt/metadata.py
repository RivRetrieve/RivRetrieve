from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LtLhmtStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_code: str
    name: str
    water_body: str | None
    latitude: float
    longitude: float
    country: str
    source: str
    elevation_m: float | None
    drainage_area_km2: float | None


class LtLhmtProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_field: str
    native_unit: str
    canonical_unit: str
    unit_conversion: str | None
    notes: str | None


class LtLhmtStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    native_field: str
    availability_source: str
    availability_note: str

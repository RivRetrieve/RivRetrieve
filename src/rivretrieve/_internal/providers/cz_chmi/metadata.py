from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CzChmiStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_id: str
    name: str
    water_body: str | None
    latitude: float
    longitude: float
    country: str
    source: str
    elevation_m: float | None
    drainage_area_km2: float | None


class CzChmiProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    ts_con_id: str
    url_type: str
    native_unit: str
    canonical_unit: str
    unit_conversion: str | None
    notes: str | None


class CzChmiStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    ts_con_id: str
    availability_source: str
    availability_note: str

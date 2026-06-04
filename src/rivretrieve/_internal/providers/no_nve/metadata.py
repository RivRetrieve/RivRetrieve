from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NoNveStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_id: str
    name: str | None
    latitude: float
    longitude: float
    country: str
    source: str
    elevation_m: float | None
    drainage_area_km2: float | None
    river_name: str | None = None
    active: bool | None = None


class NoNveProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    parameter_id: int  # NVE parameter code (1000 = stage, 1001 = discharge, 1003 = temperature)
    resolution_time: int  # NVE resTime in minutes (0 = instantaneous, 60 = hourly, 1440 = daily)
    frequency: str
    native_unit: str
    canonical_unit: str
    timezone_handling: str
    notes: str | None


class NoNveStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    parameter_id: int
    resolution_time: int
    availability_source: str
    availability_note: str

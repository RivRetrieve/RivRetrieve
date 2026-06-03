from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class JpMlitStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_id: str
    name: str | None
    latitude: float
    longitude: float
    country: str
    source: str
    elevation_m: float | None
    drainage_area_km2: float | None
    # Fields populated only when --live enrichment is used (SiteInfoDetail.exe)
    water_system_name: str | None = None
    river_name: str | None = None
    observation_type: str | None = None
    manager: str | None = None
    station_type_code: str | None = None
    address: str | None = None
    distance_from_mouth_km: float | None = None
    start_date_source: str | None = None  # ISO date string "YYYY-MM-DD"


class JpMlitProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: int
    frequency: str  # "hourly" | "daily"
    native_unit: str
    canonical_unit: str
    timezone_handling: str
    notes: str | None


class JpMlitStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    kind: int
    availability_source: str
    availability_note: str

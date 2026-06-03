from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BrAnaStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_id: str
    name: str
    basin_name: str | None
    latitude: float
    longitude: float
    country: str
    elevation_m: float | None
    drainage_area_km2: float | None


class BrAnaProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    day_column_prefix: str  # "Vazao_" or "Cota_"
    api_endpoint: str
    native_unit: str
    canonical_unit: str
    conversion_factor: float
    notes: str | None


class BrAnaStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    availability_source: str
    availability_note: str

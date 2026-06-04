from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CaEcccStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_id: str
    name: str | None
    latitude: float
    longitude: float
    country: str
    source: str
    elevation_m: float | None
    drainage_area_km2: float | None
    province: str | None = None
    hyd_status: str | None = None
    real_time: str | None = None


class CaEcccProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    ogc_field: str  # DISCHARGE or LEVEL
    ogc_symbol_field: str  # DISCHARGE_SYMBOL or LEVEL_SYMBOL
    frequency: str
    native_unit: str
    canonical_unit: str
    timezone_handling: str
    notes: str | None


class CaEcccStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    ogc_field: str
    availability_source: str
    availability_note: str

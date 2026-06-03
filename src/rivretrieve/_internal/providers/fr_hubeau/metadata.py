from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FrHubeauStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_id: str
    name: str
    river_name: str | None
    latitude: float
    longitude: float
    country: str
    source: str
    elevation_m: float | None
    drainage_area_km2: float | None
    commune: str | None
    departement: str | None
    in_service: bool | None
    opening_date: str | None


class FrHubeauProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    grandeur_hydro: str
    native_unit: str
    canonical_unit: str
    conversion_factor: float
    notes: str | None


class FrHubeauStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    grandeur_hydro: str
    availability_source: str
    availability_note: str

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ChFoenStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_key: str
    native_id: str
    name: str
    water_body_name: str | None
    water_body_type: str | None
    chx: float | None
    chy: float | None
    latitude: float
    longitude: float
    country: str
    source: str
    api_source: str | None
    api_url: str | None
    open_data_url: str | None
    license_url: str | None
    elevation_m: float | None
    drainage_area_km2: float | None


class ChFoenProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    legacy_variable: str
    native_id: str
    parameters: tuple[str, ...]
    preferred_parameter: str
    fallback_parameter: str | None
    aggregate_daily: bool
    legacy_unit: str
    notes: str | None


class ChFoenStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    native_parameters: tuple[str, ...]
    availability_source: str
    availability_note: str

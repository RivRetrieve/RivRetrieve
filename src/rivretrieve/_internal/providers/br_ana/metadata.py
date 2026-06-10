from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BrAnaStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_id: str
    name: str
    basin_name: str | None
    river_name: str | None
    latitude: float
    longitude: float
    country: str
    elevation_m: float | None
    drainage_area_km2: float | None
    # ANA inventory capability flags (Tipo_Estacao_* source fields).
    # has_discharge → Tipo_Estacao_Desc_Liquida
    # has_stage     → Tipo_Estacao_Escala
    # has_water_temperature → Tipo_Estacao_Qual_Agua
    has_discharge: bool
    has_stage: bool
    has_water_temperature: bool


class BrAnaProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    day_column_prefix: str | None  # "Vazao_" or "Cota_" — daily columnar series only
    native_field: str | None  # e.g. "Vazao_Adotada" — telemetric/instantaneous series only
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

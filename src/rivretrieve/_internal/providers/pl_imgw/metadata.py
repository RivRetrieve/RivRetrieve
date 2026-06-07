from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PlImgwStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_id: str
    name: str
    river: str | None
    province: str | None
    latitude: float | None
    longitude: float | None
    country: str
    source: str


class PlImgwProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_column: str
    native_unit: str
    canonical_unit: str
    unit_conversion: str | None
    notes: str | None


class PlImgwStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    availability_source: str
    availability_note: str

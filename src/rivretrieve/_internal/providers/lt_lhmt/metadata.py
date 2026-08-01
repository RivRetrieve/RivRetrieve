from __future__ import annotations

from pydantic import BaseModel, ConfigDict


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

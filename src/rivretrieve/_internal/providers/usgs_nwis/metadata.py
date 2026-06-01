from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UsgsNwisStationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    native_site_no: str
    name: str
    state_cd: str | None
    huc_cd: str | None
    tz_cd: str | None
    drain_area_sq_mi: float | None
    alt_va_ft: float | None
    begin_date: str | None
    end_date: str | None
    country: str


class UsgsNwisProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    param_code: str
    stat_code: str | None
    endpoint: str
    native_unit: str
    canonical_unit: str
    unit_conversion: str
    notes: str | None


class UsgsNwisStationProductMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    station_id: str
    product_id: str
    param_code: str
    stat_code: str | None
    endpoint: str
    availability_source: str
    availability_note: str

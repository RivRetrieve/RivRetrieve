"""Project reviewed native fields to source-supported station metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import polars as pl

from rivretrieve._internal.catalogue_origins import Field
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.station_metadata import (
    ATTRIBUTE_ROLES,
    SOURCE_METADATA_SCHEMA,
    SOURCE_SCALAR_DTYPES,
    source_metadata_frame,
)


@dataclass(frozen=True, slots=True)
class MetadataField:
    attribute_role: Literal["station_name", "river_name", "drainage_area"]
    source_field: str
    source_unit: str | None = None

    def __post_init__(self) -> None:
        if self.attribute_role not in ATTRIBUTE_ROLES:
            raise ValueError("Metadata field has an invalid attribute role")
        if not isinstance(self.source_field, str) or not self.source_field.strip():
            raise ValueError("Metadata field requires an exact nonblank source field")
        if self.source_unit is not None and not isinstance(self.source_unit, str):
            raise TypeError("Metadata source unit must be a string or None")


def build_station_metadata(
    provider_id: str,
    native_table: NativeTable,
    stations: pl.DataFrame,
    station_origin: Field,
    fields: tuple[MetadataField, ...],
) -> pl.DataFrame:
    """Project explicitly reviewed fields without converting their values or units.

    Native identity uses the station catalogue's declared conversion. Only
    canonical station IDs are emitted. Each absent role receives a no_metadata
    row. Null fields retain their dtype, unit and stable support fact name.
    Invalid identities, unsupported scalar types and inconsistent declarations
    raise FatalContractError. This function does not read or write files.
    """
    if not isinstance(station_origin, Field):
        raise FatalContractError("Station metadata requires a native field identity origin")
    if not provider_id or stations.schema.get("station_id") != pl.String:
        raise FatalContractError("Station metadata requires string provider and station identities")
    if (
        "provider_id" in stations.columns
        and stations.filter(pl.col("provider_id").is_null() | (pl.col("provider_id") != provider_id)).height
    ):
        raise FatalContractError("Station metadata canonical scope contains another provider")
    identities = stations["station_id"].to_list()
    if any(not identity for identity in identities) or len(set(identities)) != len(identities):
        raise FatalContractError("Station metadata has invalid or duplicate canonical identities")
    declarations = [(field.attribute_role, field.source_field) for field in fields]
    if len(set(declarations)) != len(declarations):
        raise FatalContractError("Station metadata has duplicate field declarations")
    native = native_table.data
    for field in fields:
        dtype = native.schema.get(field.source_field)
        if dtype is None or str(dtype) not in SOURCE_SCALAR_DTYPES:
            raise FatalContractError("Station metadata field requires a supported native scalar dtype")
        if field.attribute_role != "drainage_area" and dtype != pl.String:
            raise FatalContractError("Station metadata name fields require native strings")
    native_rows = {}
    for row in native.iter_rows(named=True):
        try:
            identity = station_origin.conversion.apply("station_id", station_origin.native_column, row)
        except (KeyError, ValueError, TypeError) as error:
            raise FatalContractError("Station metadata native identity conversion failed") from error
        if not isinstance(identity, str) or not identity or identity in native_rows:
            raise FatalContractError("Station metadata has invalid or duplicate native identities")
        native_rows[identity] = row
    if not set(identities) <= native_rows.keys():
        raise FatalContractError("Canonical station has no native metadata identity")
    rows = []
    for station in identities:
        for role in ATTRIBUTE_ROLES:
            selected = [field for field in fields if field.attribute_role == role]
            if not selected:
                rows.append(
                    {"provider_id": provider_id, "station_id": station, "attribute_role": role, "state": "no_metadata"}
                )
            for field in selected:
                value = native_rows[station][field.source_field]
                try:
                    encoded = None if value is None else json.dumps(value, ensure_ascii=False, allow_nan=False)
                except (TypeError, ValueError) as error:
                    raise FatalContractError("Station metadata value is not a finite JSON scalar") from error
                rows.append(
                    {
                        "provider_id": provider_id,
                        "station_id": station,
                        "attribute_role": role,
                        "source_field": field.source_field,
                        "source_value": encoded,
                        "source_dtype": str(native.schema[field.source_field]),
                        "source_unit": field.source_unit,
                        "state": "source_null" if value is None else "value",
                        "support_fact": f"metadata.{role}.{field.source_field}",
                    }
                )
    result = pl.DataFrame(rows, schema=SOURCE_METADATA_SCHEMA)
    keys = pl.DataFrame(
        {"provider_id": [provider_id] * len(identities), "station_id": identities},
        schema={"provider_id": pl.String, "station_id": pl.String},
    )
    return source_metadata_frame(keys, result)

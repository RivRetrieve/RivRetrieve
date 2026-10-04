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
    SOURCE_DATUM_DTYPES,
    SOURCE_METADATA_SCHEMA,
    SOURCE_SCALAR_DTYPES,
    metadata_support_fact,
    source_metadata_frame,
)


@dataclass(frozen=True, slots=True)
class MetadataField:
    """An approved native field and its established unit and elevation datum.

    ``datum_field`` names a native string or integer code column. ``datum`` instead declares a
    published datum that applies to every projected station. These are mutually
    exclusive and apply only to elevation. ``datum_support`` names provenance
    facts establishing the datum's meaning and applicability to this field.
    Publication requires those facts for either kind of association.
    ``support_facts`` names additional adopted source facts establishing the
    field's meaning or unit. ``source_scope`` identifies the source collection or
    entity when native field names overlap. ``source_facts`` selects adopted
    source facts for this field instead of the historical native-table support.
    An empty tuple uses that historical native support.
    """

    attribute_role: Literal["station_name", "water_body_name", "drainage_area", "elevation"]
    source_field: str
    source_unit: str | None = None
    datum_field: str | None = None
    datum: str | None = None
    datum_support: tuple[str, ...] = ()
    support_facts: tuple[str, ...] = ()
    source_scope: str | None = None
    source_facts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.attribute_role not in ATTRIBUTE_ROLES:
            raise ValueError("Metadata field has an invalid attribute role")
        if not isinstance(self.source_field, str) or not self.source_field.strip():
            raise ValueError("Metadata field requires an exact nonblank source field")
        if self.source_scope is not None and (not isinstance(self.source_scope, str) or not self.source_scope.strip()):
            raise ValueError("Metadata source scope must be a nonblank string or None")
        if self.source_unit is not None and not isinstance(self.source_unit, str):
            raise TypeError("Metadata source unit must be a string or None")
        if self.datum_field is not None and (not isinstance(self.datum_field, str) or not self.datum_field.strip()):
            raise ValueError("Metadata datum field requires an exact nonblank source field")
        if self.datum is not None and not isinstance(self.datum, str):
            raise TypeError("Metadata datum must be a string or None")
        if self.datum_field is not None and self.datum is not None:
            raise ValueError("Metadata datum field and declaration are mutually exclusive")
        associated = self.datum_field is not None or self.datum is not None
        if (associated or self.datum_support) and self.attribute_role != "elevation":
            raise ValueError("Only elevation metadata can declare a datum association")
        for support in (self.source_facts, self.support_facts, self.datum_support):
            if (
                not isinstance(support, tuple)
                or any(not isinstance(fact, str) or not fact.strip() for fact in support)
                or len(set(support)) != len(support)
            ):
                raise ValueError("Metadata support requires distinct nonblank fact names")
        if bool(self.datum_support) != associated:
            raise ValueError("Metadata datum associations require explicit support facts")


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
    declarations = [(field.attribute_role, field.source_scope, field.source_field) for field in fields]
    if len(set(declarations)) != len(declarations):
        raise FatalContractError("Station metadata has duplicate field declarations")
    native = native_table.data
    for field in fields:
        dtype = native.schema.get(field.source_field)
        if dtype is None or str(dtype) not in SOURCE_SCALAR_DTYPES:
            raise FatalContractError("Station metadata field requires a supported native scalar dtype")
        if field.attribute_role in ("station_name", "water_body_name") and dtype != pl.String:
            raise FatalContractError("Station metadata name fields require native strings")
        if field.datum_field is not None and str(native.schema.get(field.datum_field)) not in SOURCE_DATUM_DTYPES:
            raise FatalContractError("Station metadata datum fields require native string or integer codes")
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
                datum = native_rows[station][field.datum_field] if field.datum_field is not None else field.datum
                rows.append(
                    {
                        "provider_id": provider_id,
                        "station_id": station,
                        "attribute_role": role,
                        "source_field": field.source_field,
                        "source_scope": field.source_scope,
                        "source_value": encoded,
                        "source_dtype": str(native.schema[field.source_field]),
                        "source_unit": field.source_unit,
                        "state": "source_null" if value is None else "value",
                        "support_fact": metadata_support_fact(role, field.source_field, field.source_scope),
                        "source_datum": None if datum is None else str(datum),
                        "source_datum_field": field.datum_field,
                        "source_datum_dtype": str(native.schema[field.datum_field])
                        if field.datum_field is not None
                        else None,
                        "datum_support_fact": (
                            f"{metadata_support_fact(role, field.source_field, field.source_scope)}.datum"
                            if field.datum_support
                            else None
                        ),
                    }
                )
    result = pl.DataFrame(rows, schema=SOURCE_METADATA_SCHEMA)
    keys = pl.DataFrame(
        {"provider_id": [provider_id] * len(identities), "station_id": identities},
        schema={"provider_id": pl.String, "station_id": pl.String},
    )
    return source_metadata_frame(keys, result)


def validate_metadata_fields(metadata: pl.DataFrame, fields: tuple[MetadataField, ...]) -> None:
    """Check that emitted fields and associations match their publication declarations."""
    declarations = {(field.attribute_role, field.source_scope, field.source_field): field for field in fields}
    if len(declarations) != len(fields):
        raise FatalContractError("Station metadata has duplicate field declarations")
    exposed = metadata.filter(pl.col("state") != "no_metadata")
    identities = set(exposed.select("attribute_role", "source_scope", "source_field").iter_rows())
    if metadata.height and identities != set(declarations):
        raise FatalContractError("Station metadata fields do not match publication declarations")
    for row in exposed.iter_rows(named=True):
        field = declarations[(row["attribute_role"], row["source_scope"], row["source_field"])]
        fact = metadata_support_fact(field.attribute_role, field.source_field, field.source_scope)
        if (
            row["support_fact"] != fact
            or row["source_unit"] != field.source_unit
            or row["source_datum_field"] != field.datum_field
            or row["datum_support_fact"] != (f"{fact}.datum" if field.datum_support else None)
            or (field.datum_field is None and row["source_datum"] != field.datum)
        ):
            raise FatalContractError("Station metadata values or associations conflict with their declaration")

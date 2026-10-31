"""Exact-identity PHISIS enrichment and shared station metadata projection."""

from collections.abc import Mapping, Sequence
from typing import cast

import polars as pl

from rivretrieve._internal.catalogue_origins import Field, NativeColumn
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.station_metadata import MetadataField, build_station_metadata
from rivretrieve._internal.issues import FatalContractError

DETAIL_FIELDS = ("waterBody", "waterBodyType", "automaticCode", "conventionalCode", "levelType")
STATION_METADATA_FIELDS = (
    MetadataField("station_name", "name", source_scope="station_registry", source_facts=("source.station.registry",)),
    MetadataField(
        "water_body_name", "waterBody", source_scope="phisis_detail", source_facts=("source.station.phisis_detail",)
    ),
    MetadataField(
        "elevation",
        "altitude",
        "m",
        source_scope="station_registry",
        source_facts=("source.station.registry",),
        support_facts=("source.station.altitude_unit",),
    ),
)


def enrich_station_metadata(native: NativeTable, details: Sequence[Mapping[str, object]]) -> NativeTable:
    """Join detail water bodies and relationships only to matching primary codes.

    Registry coordinates, elevations and names remain authoritative. Relationship
    codes are preserved as source facts and do not propagate metadata to other stations.
    """
    rows = []
    identities = set(native.data["stationId"])
    seen = set()
    for payload in details:
        data = payload.get("data")
        if payload.get("status") is not True or not isinstance(data, dict):
            raise FatalContractError("PHISIS detail requires a successful station object")
        data = cast("dict[str, object]", data)
        code = data.get("code")
        if not isinstance(code, str) or code not in identities or code in seen:
            raise FatalContractError("PHISIS detail requires a distinct registry primary identity")
        seen.add(code)
        values = {name: data.get(name) for name in DETAIL_FIELDS}
        if any(value is not None and not isinstance(value, str) for value in values.values()):
            raise FatalContractError("PHISIS descriptive metadata must contain source strings or nulls")
        rows.append({"stationId": code, **values})
    supplementary = pl.DataFrame(rows, schema=pl.Schema(dict.fromkeys(("stationId", *DETAIL_FIELDS), pl.String)))
    return NativeTable(native.data.join(supplementary, on="stationId", how="left").sort("stationId"))


def project_station_metadata(native: NativeTable, stations: pl.DataFrame) -> pl.DataFrame:
    """Publish supported names and elevations with unknown datum and nulls intact."""
    return build_station_metadata(
        "pe_senamhi", native, stations, Field(NativeColumn("stationId")), STATION_METADATA_FIELDS
    )

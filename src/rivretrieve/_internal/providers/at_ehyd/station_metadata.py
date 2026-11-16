"""Endpoint-scoped eHYD station metadata projection."""

import polars as pl

from rivretrieve._internal.catalogue_origins import Field, NativeColumn
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.at_ehyd.origins import (
    OWF_METADATA_FIELDS,
    PEGEL_AKTUELL_METADATA_FIELDS,
)
from rivretrieve._internal.station_metadata import SOURCE_METADATA_SCHEMA, source_metadata_frame


def project_station_metadata(native: NativeTable, stations: pl.DataFrame) -> pl.DataFrame:
    """Project verified owf and Pegel Aktuell attributes without turning union padding into source_null.

    Stations absent from ``owf`` receive ``no_metadata`` for ``drainage_area`` rather
    than ``source_null``. All stations receive ``no_metadata`` for ``elevation`` because
    Stammdaten ``Pegelnullpunkt`` is a multi-row temporal datum history and ``mpua04``
    lacks an independently declared unit or vertical datum.
    """
    if stations.schema.get("station_id") != pl.String or (
        "provider_id" in stations.columns
        and stations.filter(pl.col("provider_id").is_null() | (pl.col("provider_id") != "at_ehyd")).height
    ):
        raise FatalContractError("eHYD station metadata requires canonical at_ehyd station identities")
    identities = stations["station_id"].to_list()
    if any(not item for item in identities) or len(set(identities)) != len(identities):
        raise FatalContractError("eHYD station metadata has invalid or duplicate canonical identities")
    required_cols = {"hzbnr", "in_owf", "in_pegel_aktuell"}
    if not required_cols <= set(native.data.columns):
        raise FatalContractError("eHYD native table lacks endpoint-membership flags")
    scoped = native.data.join(stations.select(pl.col("station_id").alias("hzbnr")), on="hzbnr", how="semi")
    if scoped.height != stations.height:
        raise FatalContractError("Canonical eHYD station has no native metadata identity")
    if scoped.filter(~(pl.col("in_owf") | pl.col("in_pegel_aktuell"))).height:
        raise FatalContractError("eHYD station must belong to at least one selected registry")

    owf_ids = scoped.filter(pl.col("in_owf")).select(pl.col("hzbnr").alias("station_id"))
    pa_ids = scoped.filter(pl.col("in_pegel_aktuell")).select(pl.col("hzbnr").alias("station_id"))
    owf_stations = stations.join(owf_ids, on="station_id", how="semi")
    pa_stations = stations.join(pa_ids, on="station_id", how="semi")

    origin = Field(NativeColumn("hzbnr"))
    owf_meta = (
        build_station_metadata("at_ehyd", native, owf_stations, origin, OWF_METADATA_FIELDS)
        if owf_stations.height
        else pl.DataFrame(schema=SOURCE_METADATA_SCHEMA)
    )
    pa_meta = (
        build_station_metadata("at_ehyd", native, pa_stations, origin, PEGEL_AKTUELL_METADATA_FIELDS)
        if pa_stations.height
        else pl.DataFrame(schema=SOURCE_METADATA_SCHEMA)
    )

    pa_exposed = pa_meta.filter(pl.col("state") != "no_metadata")
    pa_telemetry_only_absent = pa_meta.filter(pl.col("state") == "no_metadata").join(
        owf_ids, on="station_id", how="anti"
    )
    combined = pl.concat([owf_meta, pa_exposed, pa_telemetry_only_absent])
    keys = pl.DataFrame(
        {"provider_id": ["at_ehyd"] * len(identities), "station_id": identities},
        schema={"provider_id": pl.String, "station_id": pl.String},
    )
    return source_metadata_frame(keys, combined)

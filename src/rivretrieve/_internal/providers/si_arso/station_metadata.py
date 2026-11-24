"""Source-scoped Slovenia ARSO station metadata projection."""

from __future__ import annotations

import polars as pl

from rivretrieve._internal.catalogue_origins import Field, NativeColumn
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.station_metadata import build_station_metadata
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.si_arso.origins import (
    DROPDOWN_METADATA_FIELDS,
    Q_STATS_METADATA_FIELDS,
    SPISEK_METADATA_FIELDS,
)
from rivretrieve._internal.station_metadata import SOURCE_METADATA_SCHEMA, source_metadata_frame


def project_station_metadata(native: NativeTable, stations: pl.DataFrame) -> pl.DataFrame:
    """Project verified ARSO station attributes across ``Spisek``, ``Q_stats``, and dropdown partitions.

    Stations in ``Spisek vodomernih postaj_okt2019.xlsx`` (617 of 619) expose
    ``VODOMERNA POSTAJA``, ``VODOTOK``, and ``ZALEDJE - F (km2)`` (preserving documented
    indeterminable-catchment codes ``88888.88`` and ``99999.99`` verbatim). Station
    ``2070`` (absent from ``Spisek``, rescued from ``Q2000_obdobne_stat.xlsx``)
    exposes ``Postaja``, ``Vodotok``, and ``F (km2)``. Legacy station ``6310``
    (absent from both ``Spisek`` and ``Q6000``) exposes dropdown ``station_name``
    and ``water_body_name`` and keeps ``drainage_area`` at ``no_metadata``. All
    stations receive ``no_metadata`` for ``elevation`` because ARSO ``KOTA "0"``
    mixes gauge-zero epochs (with unspecified inland vertical datum) and
    relative/ground elevations.
    """
    if stations.schema.get("station_id") != pl.String or (
        "provider_id" in stations.columns
        and stations.filter(pl.col("provider_id").is_null() | (pl.col("provider_id") != "si_arso")).height
    ):
        raise FatalContractError("si_arso station metadata requires canonical si_arso station identities")
    identities = stations["station_id"].to_list()
    if any(not item for item in identities) or len(set(identities)) != len(identities):
        raise FatalContractError("si_arso station metadata has invalid or duplicate canonical identities")
    required_cols = {"sifra", "in_spisek", "in_q_stats"}
    if not required_cols <= set(native.data.columns):
        raise FatalContractError("si_arso native table lacks source-membership flags")

    scoped = native.data.join(stations.select(pl.col("station_id").alias("sifra")), on="sifra", how="semi")
    if scoped.height != stations.height:
        raise FatalContractError("Canonical si_arso station has no native metadata identity")

    spisek_ids = scoped.filter(pl.col("in_spisek")).select(pl.col("sifra").alias("station_id"))
    q_only_ids = scoped.filter(~pl.col("in_spisek") & pl.col("in_q_stats")).select(pl.col("sifra").alias("station_id"))
    dd_only_ids = scoped.filter(~pl.col("in_spisek") & ~pl.col("in_q_stats")).select(
        pl.col("sifra").alias("station_id")
    )

    origin = Field(NativeColumn("sifra"))
    frames: list[pl.DataFrame] = []
    for partition_ids, fields in (
        (spisek_ids, SPISEK_METADATA_FIELDS),
        (q_only_ids, Q_STATS_METADATA_FIELDS),
        (dd_only_ids, DROPDOWN_METADATA_FIELDS),
    ):
        part_stations = stations.join(partition_ids, on="station_id", how="semi")
        if part_stations.height:
            frames.append(build_station_metadata("si_arso", native, part_stations, origin, fields))

    combined = pl.concat(frames) if frames else pl.DataFrame(schema=SOURCE_METADATA_SCHEMA)
    keys = pl.DataFrame(
        {"provider_id": ["si_arso"] * len(identities), "station_id": identities},
        schema={"provider_id": pl.String, "station_id": pl.String},
    )
    return source_metadata_frame(keys, combined)

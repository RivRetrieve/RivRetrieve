"""drainage areas : SelectedStationIdentities × PackagedDrainageMetadata → SourceAreaFrame (pure)."""

from __future__ import annotations

import polars as pl

from rivretrieve._internal.issues import FatalContractError

DRAINAGE_AREA_SCHEMA = pl.Schema(
    {
        "provider_id": pl.String,
        "station_id": pl.String,
        "source_field": pl.String,
        "source_value": pl.String,
        "source_dtype": pl.String,
        "source_unit": pl.String,
        "state": pl.Enum(["value", "source_null", "no_metadata"]),
    }
)


def drainage_area_frame(stations: pl.DataFrame, metadata: pl.DataFrame) -> pl.DataFrame:
    """Select source rows once per station; a broken packaged projection raises."""
    if metadata.schema != DRAINAGE_AREA_SCHEMA:
        raise FatalContractError("Packaged drainage metadata has an invalid schema")
    keys = ["provider_id", "station_id"]
    if stations.join(metadata.select(keys).unique(), on=keys, how="anti").height:
        raise FatalContractError("Selected station is absent from packaged drainage metadata")
    return metadata.join(stations.unique(), on=keys, how="semi").sort(*keys, "source_field")

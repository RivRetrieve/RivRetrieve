"""Pure projections of source-supported station attributes and canonical geometry."""

from __future__ import annotations

import json
import math

import polars as pl

from rivretrieve._internal.issues import FatalContractError

ATTRIBUTE_ROLES = ("station_name", "river_name", "drainage_area")
SOURCE_METADATA_SCHEMA = pl.Schema(
    {
        "provider_id": pl.String,
        "station_id": pl.String,
        "source_field": pl.String,
        "source_value": pl.String,
        "source_dtype": pl.String,
        "source_unit": pl.String,
        "state": pl.Enum(["value", "source_null", "no_metadata"]),
        "attribute_role": pl.Enum(ATTRIBUTE_ROLES),
        "support_fact": pl.String,
    }
)
STATION_METADATA_SCHEMA = pl.Schema(
    {
        "provider_id": pl.String,
        "station_id": pl.String,
        "station_name": pl.String,
        "river_name": pl.String,
        "latitude": pl.Float64,
        "longitude": pl.Float64,
        "crs": pl.String,
        "station_name_alternatives": pl.Boolean,
        "river_name_alternatives": pl.Boolean,
    }
)
_KEYS = ["provider_id", "station_id"]
_INTEGER_BOUNDS = {
    **{f"Int{bits}": (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1) for bits in (8, 16, 32, 64, 128)},
    **{f"UInt{bits}": (0, 2**bits - 1) for bits in (8, 16, 32, 64, 128)},
}
SOURCE_SCALAR_DTYPES = frozenset({"String", "Boolean", "Float32", "Float64", *_INTEGER_BOUNDS})


def _scalar(text: str, dtype: str) -> object:
    try:
        value = json.loads(text)
    except (ValueError, TypeError) as error:
        raise FatalContractError("Packaged station metadata has invalid JSON scalar text") from error
    if value is None or isinstance(value, (list, dict)) or (isinstance(value, float) and not math.isfinite(value)):
        raise FatalContractError("Packaged station metadata requires a non-null finite JSON scalar")
    if dtype in _INTEGER_BOUNDS:
        lower, upper = _INTEGER_BOUNDS[dtype]
        valid = type(value) is int and lower <= value <= upper
    elif dtype in ("Float32", "Float64"):
        valid = type(value) is float
    elif dtype == "Boolean":
        valid = type(value) is bool
    else:
        valid = dtype == "String" and isinstance(value, str)
    if not valid:
        raise FatalContractError("Packaged station metadata scalar does not match its source dtype")
    return value


def source_metadata_frame(stations: pl.DataFrame, metadata: pl.DataFrame) -> pl.DataFrame:
    """Validate the packaged projection and select each gauge's attributes once."""
    if metadata.schema != SOURCE_METADATA_SCHEMA:
        raise FatalContractError("Packaged station metadata has an invalid schema")
    groups: dict[tuple[str, str, str], list[str]] = {}
    for row in metadata.iter_rows(named=True):
        if any(row[key] is None or row[key] == "" for key in (*_KEYS, "attribute_role", "state")):
            raise FatalContractError("Packaged station metadata has a missing identity, role or state")
        group = (row["provider_id"], row["station_id"], row["attribute_role"])
        groups.setdefault(group, []).append(row["state"])
        if row["state"] == "no_metadata":
            if any(
                row[key] is not None
                for key in ("source_field", "source_value", "source_dtype", "source_unit", "support_fact")
            ):
                raise FatalContractError("Packaged no_metadata row contains source attributes")
            continue
        if any(not row[key] or not row[key].strip() for key in ("source_field", "source_dtype", "support_fact")):
            raise FatalContractError("Packaged station metadata lacks field, dtype or support fact")
        dtype = row["source_dtype"]
        if dtype not in SOURCE_SCALAR_DTYPES:
            raise FatalContractError("Packaged station metadata has an unsupported source dtype")
        if row["attribute_role"] != "drainage_area" and dtype != "String":
            raise FatalContractError("Packaged source name requires String source dtype")
        if row["state"] == "source_null":
            if row["source_value"] is not None:
                raise FatalContractError("Packaged source_null row contains a value")
        else:
            _scalar(row["source_value"], dtype)
    if any("no_metadata" in states and len(states) != 1 for states in groups.values()):
        raise FatalContractError("Packaged no_metadata conflicts with source attributes")
    if metadata.is_duplicated().any():
        raise FatalContractError("Packaged station metadata contains duplicate rows")
    for provider, station in stations.unique().iter_rows():
        if any((provider, station, role) not in groups for role in ATTRIBUTE_ROLES):
            raise FatalContractError("Selected station role is absent from packaged station metadata")
    return metadata.join(stations.unique(), on=_KEYS, how="semi").sort(
        *_KEYS, "attribute_role", "source_field", "source_value", "support_fact"
    )


def station_metadata_frame(stations: pl.DataFrame, source: pl.DataFrame, locations: pl.DataFrame) -> pl.DataFrame:
    """Summarise validated source rows without choosing between distinct names."""
    rows = []
    names: dict[tuple[str, str, str], set[str]] = {}
    for row in source.filter(pl.col("attribute_role") != "drainage_area").iter_rows(named=True):
        if row["state"] == "value":
            value = json.loads(row["source_value"])
            if value.strip():
                names.setdefault((row["provider_id"], row["station_id"], row["attribute_role"]), set()).add(value)
    geometry = {(row["provider_id"], row["station_id"]): row for row in locations.iter_rows(named=True)}
    for provider, station in stations.unique().sort(_KEYS).iter_rows():
        row = {"provider_id": provider, "station_id": station}
        location = geometry.get((provider, station), {})
        row.update({key: location.get(key) for key in ("latitude", "longitude", "crs")})
        for role in ("station_name", "river_name"):
            alternatives = names.get((provider, station, role), set())
            row[role] = next(iter(alternatives)) if len(alternatives) == 1 else None
            row[f"{role}_alternatives"] = len(alternatives) > 1
        rows.append(row)
    return pl.DataFrame(rows, schema=STATION_METADATA_SCHEMA)

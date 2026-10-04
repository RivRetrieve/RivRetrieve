"""Pure projections of source-supported station attributes and canonical geometry."""

from __future__ import annotations

import json
import math
import re

import polars as pl

from rivretrieve._internal.issues import FatalContractError

ATTRIBUTE_ROLES = ("station_name", "water_body_name", "drainage_area", "elevation")
SOURCE_METADATA_SCHEMA = pl.Schema(
    {
        "provider_id": pl.String,
        "station_id": pl.String,
        "source_field": pl.String,
        "source_scope": pl.String,
        "source_value": pl.String,
        "source_dtype": pl.String,
        "source_unit": pl.String,
        "state": pl.Enum(["value", "source_null", "no_metadata"]),
        "attribute_role": pl.Enum(ATTRIBUTE_ROLES),
        "support_fact": pl.String,
        "source_datum": pl.String,
        "source_datum_field": pl.String,
        "source_datum_dtype": pl.String,
        "datum_support_fact": pl.String,
    }
)
STATION_METADATA_SCHEMA = pl.Schema(
    {
        "provider_id": pl.String,
        "station_id": pl.String,
        "station_name": pl.String,
        "latitude": pl.Float64,
        "longitude": pl.Float64,
        "crs": pl.String,
        "water_body_name_field": pl.List(pl.String),
        "water_body_name_value": pl.List(pl.String),
        "drainage_area_field": pl.List(pl.String),
        "drainage_area_value": pl.List(pl.String),
        "drainage_area_unit": pl.List(pl.String),
        "elevation_field": pl.List(pl.String),
        "elevation_value": pl.List(pl.String),
        "elevation_unit": pl.List(pl.String),
        "elevation_datum": pl.List(pl.String),
    }
)
_KEYS = ["provider_id", "station_id"]
_INTEGER_BOUNDS = {
    **{f"Int{bits}": (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1) for bits in (8, 16, 32, 64, 128)},
    **{f"UInt{bits}": (0, 2**bits - 1) for bits in (8, 16, 32, 64, 128)},
}
SOURCE_DATUM_DTYPES = frozenset({"String", *_INTEGER_BOUNDS})
SOURCE_SCALAR_DTYPES = frozenset({"String", "Boolean", "Float32", "Float64", *_INTEGER_BOUNDS})


# Only these source fields have reviewed inline-unit summary presentation.
_INLINE_QUANTITY_FIELDS = {
    ("jp_mlit", "drainage_area", None, "流域面積"): ("km2", "km2"),
    ("jp_mlit", "elevation", None, "零点高"): ("m", "m"),
    ("ba_fhmzbih", "drainage_area", None, "metadata_CATCHMENT_SIZE"): ("km²", "km²"),
    ("ch_foen", "drainage_area", "station_page", "Catchment size"): ("km2", "km2"),
    ("ch_foen", "elevation", "station_page", "Station altitude"): ("m", "m a.s.l."),
}
_PADDED_QUANTITY_FIELDS = {("usgs_nwis", "elevation", None, "alt_va")}
_NUMBER_TEXT = r"[ \t\u00a0]*[+-]?(?:(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+)"
_SEPARATOR = r"[ \t\u00a0]*"


def split_inline_quantity(value: object, suffix: str) -> str | None:
    """Return unchanged numeric text only when the whole string has the given suffix.

    Decimal signs, leading spaces and grouped thousands remain unchanged.
    Only horizontal spaces separating or following the suffix are removed.
    Qualified text, placeholders and non-string scalars do not match.
    """
    if not isinstance(value, str):
        return None
    match = re.fullmatch(rf"({_NUMBER_TEXT}){_SEPARATOR}{re.escape(suffix)}{_SEPARATOR}", value)
    return match[1] if match is not None else None


def _summary_quantity_value(item: dict) -> str | None:
    encoded = item["source_value"]
    key = tuple(item[name] for name in ("provider_id", "attribute_role", "source_scope", "source_field"))
    if key in _PADDED_QUANTITY_FIELDS and encoded is not None and item["source_dtype"] == "String":
        value = json.loads(encoded)
        if re.fullmatch(_NUMBER_TEXT, value) is not None:
            return json.dumps(value.lstrip(" \t\u00a0"), ensure_ascii=False)
    rule = _INLINE_QUANTITY_FIELDS.get(key)
    if rule is not None and encoded is not None and item["source_dtype"] == "String":
        unit, suffix = rule
        numeric = split_inline_quantity(json.loads(encoded), suffix)
        if item["source_unit"] == unit and numeric is not None:
            return json.dumps(numeric, ensure_ascii=False)
    return encoded


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


def metadata_support_fact(attribute_role: str, source_field: str, source_scope: str | None = None) -> str:
    """Name a projection fact without changing its native field or source scope."""
    scope = "" if source_scope is None else f"{source_scope}."
    return f"metadata.{attribute_role}.{scope}{source_field}"


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
                for key in (
                    "source_field",
                    "source_scope",
                    "source_value",
                    "source_dtype",
                    "source_unit",
                    "support_fact",
                    "source_datum",
                    "source_datum_field",
                    "source_datum_dtype",
                    "datum_support_fact",
                )
            ):
                raise FatalContractError("Packaged no_metadata row contains source attributes")
            continue
        if any(not row[key] or not row[key].strip() for key in ("source_field", "source_dtype", "support_fact")):
            raise FatalContractError("Packaged station metadata lacks field, dtype or support fact")
        if row["source_scope"] is not None and not row["source_scope"].strip():
            raise FatalContractError("Packaged station metadata has an empty source scope")
        dtype = row["source_dtype"]
        if dtype not in SOURCE_SCALAR_DTYPES:
            raise FatalContractError("Packaged station metadata has an unsupported source dtype")
        if row["attribute_role"] in ("station_name", "water_body_name") and dtype != "String":
            raise FatalContractError("Packaged source name requires String source dtype")
        datum_columns = ("source_datum", "source_datum_field", "source_datum_dtype", "datum_support_fact")
        if row["attribute_role"] != "elevation" and any(row[key] is not None for key in datum_columns):
            raise FatalContractError("Packaged datum association requires an elevation field")
        if row["datum_support_fact"] is None:
            if row["source_datum"] is not None or row["source_datum_field"] is not None:
                raise FatalContractError("Packaged datum association lacks its support fact")
        elif (
            row["datum_support_fact"]
            != f"{metadata_support_fact('elevation', row['source_field'], row['source_scope'])}.datum"
            or (row["source_datum"] is None and row["source_datum_field"] is None)
            or (row["source_datum_field"] is not None and not row["source_datum_field"].strip())
        ):
            raise FatalContractError("Packaged datum association has invalid field or support")
        if row["source_datum_field"] is None:
            if row["source_datum_dtype"] is not None:
                raise FatalContractError("Packaged declared datum cannot have a native dtype")
        else:
            datum_dtype = row["source_datum_dtype"]
            if datum_dtype not in SOURCE_DATUM_DTYPES:
                raise FatalContractError("Packaged native datum requires a string or integer dtype")
            datum_value = row["source_datum"]
            if (
                datum_value is not None
                and datum_dtype != "String"
                and str(_scalar(datum_value, datum_dtype)) != datum_value
            ):
                raise FatalContractError("Packaged datum code does not match its native dtype")
        if row["state"] == "source_null":
            if row["source_value"] is not None:
                raise FatalContractError("Packaged source_null row contains a value")
        else:
            _scalar(row["source_value"], dtype)
    if any("no_metadata" in states and len(states) != 1 for states in groups.values()):
        raise FatalContractError("Packaged no_metadata conflicts with source attributes")
    if metadata.select(*_KEYS, "attribute_role", "source_scope", "source_field").is_duplicated().any():
        raise FatalContractError("Packaged station metadata contains duplicate source fields")
    for provider, station in stations.unique().iter_rows():
        if any((provider, station, role) not in groups for role in ATTRIBUTE_ROLES):
            raise FatalContractError("Selected station role is absent from packaged station metadata")
    return metadata.join(stations.unique(), on=_KEYS, how="semi").sort(
        *_KEYS, "attribute_role", "source_field", "source_scope", "source_value", "support_fact"
    )


def station_metadata_frame(stations: pl.DataFrame, source: pl.DataFrame, locations: pl.DataFrame) -> pl.DataFrame:
    """Summarise validated source rows with aligned lists ordered by native field."""
    rows = []
    attributes: dict[tuple[str, str, str], list[dict]] = {}
    for item in source.sort("source_field", "source_scope").iter_rows(named=True):
        if item["state"] != "no_metadata":
            attributes.setdefault((item["provider_id"], item["station_id"], item["attribute_role"]), []).append(item)
    geometry = {(row["provider_id"], row["station_id"]): row for row in locations.iter_rows(named=True)}
    for provider, station in stations.unique().sort(_KEYS).iter_rows():
        row = {"provider_id": provider, "station_id": station}
        location = geometry.get((provider, station), {})
        row.update({key: location.get(key) for key in ("latitude", "longitude", "crs")})
        names = {
            json.loads(item["source_value"])
            for item in attributes.get((provider, station, "station_name"), [])
            if item["state"] == "value" and json.loads(item["source_value"]).strip()
        }
        row["station_name"] = next(iter(names)) if len(names) == 1 else None
        for role in ("water_body_name", "drainage_area", "elevation"):
            fields = attributes.get((provider, station, role), [])
            row[f"{role}_field"] = [item["source_field"] for item in fields] if fields else None
            row[f"{role}_value"] = (
                [
                    json.loads(item["source_value"])
                    if role == "water_body_name" and item["source_value"] is not None
                    else _summary_quantity_value(item)
                    for item in fields
                ]
                if fields
                else None
            )
            if role in ("drainage_area", "elevation"):
                row[f"{role}_unit"] = [item["source_unit"] for item in fields] if fields else None
            if role == "elevation":
                row["elevation_datum"] = [item["source_datum"] for item in fields] if fields else None
        rows.append(row)
    return pl.DataFrame(rows, schema=STATION_METADATA_SCHEMA)

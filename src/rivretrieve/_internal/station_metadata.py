"""Pure projections of source-supported station attributes and canonical geometry."""

from __future__ import annotations

import json
import math
import re
from typing import cast

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
_INLINE_QUANTITY_FIELDS: dict[tuple[str, str, str | None, str | None], tuple[str, str]] = {
    ("jp_mlit", "drainage_area", None, "流域面積"): ("km2", "km2"),
    ("jp_mlit", "elevation", None, "零点高"): ("m", "m"),
    ("ba_fhmzbih", "drainage_area", None, "metadata_CATCHMENT_SIZE"): ("km²", "km²"),
    ("ch_foen", "drainage_area", "station_page", "Catchment size"): ("km2", "km2"),
    ("ch_foen", "elevation", "station_page", "Station altitude"): ("m", "m a.s.l."),
}
_PADDED_QUANTITY_FIELDS = {("usgs_nwis", "elevation", None, "alt_va")}
_NUMBER_TEXT = r"[ \t\u00a0]*[+-]?(?:(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+)"
_NUMBER_TEXT_RE = re.compile(_NUMBER_TEXT)
_SEPARATOR = r"[ \t\u00a0]*"
_SPLIT_INLINE_RE_CACHE: dict[str, re.Pattern[str]] = {}
_PLAIN_QUOTED_JSON_STR_FULLMATCH = re.compile(r'"[^"\\\x00-\x1f]*"').fullmatch
_SIMPLE_JSON_FLOAT_FULLMATCH = re.compile(r"-?(?:0|[1-9][0-9]*)\.[0-9]+").fullmatch
_SIMPLE_JSON_INT_FULLMATCH = re.compile(r"0|-?[1-9][0-9]*").fullmatch


def _unquote_json_str(encoded: str) -> str:
    if _PLAIN_QUOTED_JSON_STR_FULLMATCH(encoded) is not None:
        return encoded[1:-1]
    return cast("str", json.loads(encoded))


def split_inline_quantity(value: object, suffix: str) -> str | None:
    """Return unchanged numeric text only when the whole string has the given suffix.

    Decimal signs, leading spaces and grouped thousands remain unchanged.
    Only horizontal spaces separating or following the suffix are removed.
    Qualified text, placeholders and non-string scalars do not match.
    """
    if not isinstance(value, str):
        return None
    pattern = _SPLIT_INLINE_RE_CACHE.get(suffix)
    if pattern is None:
        pattern = re.compile(rf"({_NUMBER_TEXT}){_SEPARATOR}{re.escape(suffix)}{_SEPARATOR}")
        _SPLIT_INLINE_RE_CACHE[suffix] = pattern
    match = pattern.fullmatch(value)
    return match[1] if match is not None else None


def _summary_quantity_value_fields(
    provider_id: str,
    attribute_role: str,
    source_scope: str | None,
    source_field: str | None,
    encoded: str | None,
    source_dtype: str | None,
    source_unit: str | None,
) -> str | None:
    if encoded is None or source_dtype != "String":
        return encoded
    key = (provider_id, attribute_role, source_scope, source_field)
    if key in _PADDED_QUANTITY_FIELDS:
        value = _unquote_json_str(encoded)
        if _NUMBER_TEXT_RE.fullmatch(value) is not None:
            return json.dumps(value.lstrip(" \t\u00a0"), ensure_ascii=False)
    rule = _INLINE_QUANTITY_FIELDS.get(key)
    if rule is not None:
        unit, suffix = rule
        if source_unit == unit:
            numeric = split_inline_quantity(_unquote_json_str(encoded), suffix)
            if numeric is not None:
                return json.dumps(numeric, ensure_ascii=False)
    return encoded


def _summary_quantity_value(item: dict) -> str | None:
    return _summary_quantity_value_fields(
        item["provider_id"],
        item["attribute_role"],
        item["source_scope"],
        item["source_field"],
        item["source_value"],
        item["source_dtype"],
        item["source_unit"],
    )


def _scalar(text: str, dtype: str) -> object:
    if type(text) is str:
        if dtype == "String" and _PLAIN_QUOTED_JSON_STR_FULLMATCH(text) is not None:
            return text[1:-1]
        if dtype in ("Float64", "Float32") and _SIMPLE_JSON_FLOAT_FULLMATCH(text) is not None:
            f_val = float(text)
            if math.isfinite(f_val):
                return f_val
        elif dtype in _INTEGER_BOUNDS and _SIMPLE_JSON_INT_FULLMATCH(text) is not None:
            i_val = int(text)
            lower, upper = _INTEGER_BOUNDS[dtype]
            if lower <= i_val <= upper:
                return i_val
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
    # Bitmask per (provider_id, station_id, attribute_role):
    #   1: single non-no_metadata row
    #   2: single no_metadata row
    #   5: multiple non-no_metadata rows
    #   6: no_metadata combined with any other row (including duplicate no_metadata)
    groups: dict[tuple[str, str, str], int] = {}
    if metadata.height:
        m_cols = metadata.to_dict(as_series=False)
        provs = m_cols["provider_id"]
        sids = m_cols["station_id"]
        s_fields = m_cols["source_field"]
        s_scopes = m_cols["source_scope"]
        s_values = m_cols["source_value"]
        s_dtypes = m_cols["source_dtype"]
        s_units = m_cols["source_unit"]
        states = m_cols["state"]
        roles = m_cols["attribute_role"]
        sup_facts = m_cols["support_fact"]
        s_datums = m_cols["source_datum"]
        s_datum_fields = m_cols["source_datum_field"]
        s_datum_dtypes = m_cols["source_datum_dtype"]
        datum_sup_facts = m_cols["datum_support_fact"]
        for idx in range(len(provs)):
            prov = provs[idx]
            sid = sids[idx]
            role = roles[idx]
            state = states[idx]
            if not prov or not sid or not role or not state:
                raise FatalContractError("Packaged station metadata has a missing identity, role or state")
            group = (prov, sid, role)
            prev = groups.get(group, 0)
            s_field = s_fields[idx]
            s_scope = s_scopes[idx]
            s_value = s_values[idx]
            s_dtype = s_dtypes[idx]
            s_unit = s_units[idx]
            sup_fact = sup_facts[idx]
            s_datum = s_datums[idx]
            s_datum_field = s_datum_fields[idx]
            s_datum_dtype = s_datum_dtypes[idx]
            datum_sup_fact = datum_sup_facts[idx]
            if state == "no_metadata":
                groups[group] = 2 if prev == 0 else 6
                if (
                    s_field is not None
                    or s_scope is not None
                    or s_value is not None
                    or s_dtype is not None
                    or s_unit is not None
                    or sup_fact is not None
                    or s_datum is not None
                    or s_datum_field is not None
                    or s_datum_dtype is not None
                    or datum_sup_fact is not None
                ):
                    raise FatalContractError("Packaged no_metadata row contains source attributes")
                continue
            groups[group] = 1 if prev == 0 else (6 if (prev & 2) else 5)
            if (
                not s_field
                or not s_field.strip()
                or not s_dtype
                or not s_dtype.strip()
                or not sup_fact
                or not sup_fact.strip()
            ):
                raise FatalContractError("Packaged station metadata lacks field, dtype or support fact")
            if s_scope is not None and not s_scope.strip():
                raise FatalContractError("Packaged station metadata has an empty source scope")
            if s_dtype not in SOURCE_SCALAR_DTYPES:
                raise FatalContractError("Packaged station metadata has an unsupported source dtype")
            if role in ("station_name", "water_body_name") and s_dtype != "String":
                raise FatalContractError("Packaged source name requires String source dtype")
            if role != "elevation" and (
                s_datum is not None
                or s_datum_field is not None
                or s_datum_dtype is not None
                or datum_sup_fact is not None
            ):
                raise FatalContractError("Packaged datum association requires an elevation field")
            if datum_sup_fact is None:
                if s_datum is not None or s_datum_field is not None:
                    raise FatalContractError("Packaged datum association lacks its support fact")
            elif (
                datum_sup_fact != f"{metadata_support_fact('elevation', s_field, s_scope)}.datum"
                or (s_datum is None and s_datum_field is None)
                or (s_datum_field is not None and not s_datum_field.strip())
            ):
                raise FatalContractError("Packaged datum association has invalid field or support")
            if s_datum_field is None:
                if s_datum_dtype is not None:
                    raise FatalContractError("Packaged declared datum cannot have a native dtype")
            else:
                if s_datum_dtype not in SOURCE_DATUM_DTYPES:
                    raise FatalContractError("Packaged native datum requires a string or integer dtype")
                if (
                    s_datum is not None
                    and s_datum_dtype != "String"
                    and str(_scalar(s_datum, s_datum_dtype)) != s_datum
                ):
                    raise FatalContractError("Packaged datum code does not match its native dtype")
            if state == "source_null":
                if s_value is not None:
                    raise FatalContractError("Packaged source_null row contains a value")
            else:
                _scalar(s_value, s_dtype)
    if 6 in groups.values():
        raise FatalContractError("Packaged no_metadata conflicts with source attributes")
    if metadata.select(*_KEYS, "attribute_role", "source_scope", "source_field").is_duplicated().any():
        raise FatalContractError("Packaged station metadata contains duplicate source fields")
    unique_stations = stations.unique()
    if unique_stations.height:
        st_cols = unique_stations.to_dict(as_series=False)
        for provider, station in zip(st_cols["provider_id"], st_cols["station_id"], strict=True):
            if (
                (provider, station, "station_name") not in groups
                or (provider, station, "water_body_name") not in groups
                or (provider, station, "drainage_area") not in groups
                or (provider, station, "elevation") not in groups
            ):
                raise FatalContractError("Selected station role is absent from packaged station metadata")
    return metadata.join(unique_stations, on=_KEYS, how="semi").sort(
        *_KEYS, "attribute_role", "source_field", "source_scope", "source_value", "support_fact"
    )


def station_metadata_frame(stations: pl.DataFrame, source: pl.DataFrame, locations: pl.DataFrame) -> pl.DataFrame:
    """Summarise validated source rows with aligned lists ordered by native field."""
    sorted_stations = stations.unique().sort(_KEYS)
    if not sorted_stations.height:
        return pl.DataFrame(schema=STATION_METADATA_SCHEMA)

    # Tuple layout: (source_field, source_scope, source_value, source_dtype, source_unit, state, source_datum)
    attributes: dict[
        tuple[str, str, str], list[tuple[str, str | None, str | None, str | None, str | None, str, str | None]]
    ] = {}
    if source.height:
        src_sorted = source.sort("source_field", "source_scope")
        src_cols = src_sorted.to_dict(as_series=False)
        for prov, sid, role, state, s_field, s_scope, s_val, s_dtype, s_unit, s_datum in zip(
            src_cols["provider_id"],
            src_cols["station_id"],
            src_cols["attribute_role"],
            src_cols["state"],
            src_cols["source_field"],
            src_cols["source_scope"],
            src_cols["source_value"],
            src_cols["source_dtype"],
            src_cols["source_unit"],
            src_cols["source_datum"],
            strict=True,
        ):
            if state != "no_metadata":
                attributes.setdefault((prov, sid, role), []).append(
                    (s_field, s_scope, s_val, s_dtype, s_unit, state, s_datum)
                )

    geometry: dict[tuple[str, str], tuple[float | None, float | None, str | None]] = {}
    if locations.height:
        loc_cols = locations.to_dict(as_series=False)
        for prov, sid, lat, lon, crs in zip(
            loc_cols["provider_id"],
            loc_cols["station_id"],
            loc_cols["latitude"],
            loc_cols["longitude"],
            loc_cols["crs"],
            strict=True,
        ):
            geometry[(prov, sid)] = (lat, lon, crs)

    st_cols = sorted_stations.to_dict(as_series=False)
    out_provs: list[str] = st_cols["provider_id"]
    out_sids: list[str] = st_cols["station_id"]
    out_names: list[str | None] = []
    out_lats: list[float | None] = []
    out_lons: list[float | None] = []
    out_crs: list[str | None] = []
    out_wb_field: list[list[str] | None] = []
    out_wb_val: list[list[str | None] | None] = []
    out_da_field: list[list[str] | None] = []
    out_da_val: list[list[str | None] | None] = []
    out_da_unit: list[list[str | None] | None] = []
    out_el_field: list[list[str] | None] = []
    out_el_val: list[list[str | None] | None] = []
    out_el_unit: list[list[str | None] | None] = []
    out_el_datum: list[list[str | None] | None] = []

    for provider, station in zip(out_provs, out_sids, strict=True):
        loc = geometry.get((provider, station))
        if loc is not None:
            out_lats.append(loc[0])
            out_lons.append(loc[1])
            out_crs.append(loc[2])
        else:
            out_lats.append(None)
            out_lons.append(None)
            out_crs.append(None)

        name_items = attributes.get((provider, station, "station_name"))
        if name_items:
            names: set[str] = set()
            for item in name_items:
                if item[5] == "value" and item[2] is not None:
                    parsed_name = _unquote_json_str(item[2])
                    if parsed_name.strip():
                        names.add(parsed_name)
            out_names.append(next(iter(names)) if len(names) == 1 else None)
        else:
            out_names.append(None)

        wb_items = attributes.get((provider, station, "water_body_name"))
        if wb_items:
            out_wb_field.append([item[0] for item in wb_items])
            out_wb_val.append([_unquote_json_str(item[2]) if item[2] is not None else None for item in wb_items])
        else:
            out_wb_field.append(None)
            out_wb_val.append(None)

        da_items = attributes.get((provider, station, "drainage_area"))
        if da_items:
            out_da_field.append([item[0] for item in da_items])
            out_da_val.append(
                [
                    _summary_quantity_value_fields(
                        provider, "drainage_area", item[1], item[0], item[2], item[3], item[4]
                    )
                    for item in da_items
                ]
            )
            out_da_unit.append([item[4] for item in da_items])
        else:
            out_da_field.append(None)
            out_da_val.append(None)
            out_da_unit.append(None)

        el_items = attributes.get((provider, station, "elevation"))
        if el_items:
            out_el_field.append([item[0] for item in el_items])
            out_el_val.append(
                [
                    _summary_quantity_value_fields(provider, "elevation", item[1], item[0], item[2], item[3], item[4])
                    for item in el_items
                ]
            )
            out_el_unit.append([item[4] for item in el_items])
            out_el_datum.append([item[6] for item in el_items])
        else:
            out_el_field.append(None)
            out_el_val.append(None)
            out_el_unit.append(None)
            out_el_datum.append(None)

    import pyarrow as pa

    pa_str_list = pa.list_(pa.string())

    def _list_series(name: str, values: list[list[str] | None] | list[list[str | None] | None]) -> pl.Series:
        return cast("pl.Series", pl.from_arrow(pa.array(values, type=pa_str_list))).rename(name)

    return pl.DataFrame(
        [
            pl.Series("provider_id", out_provs, dtype=pl.String),
            pl.Series("station_id", out_sids, dtype=pl.String),
            pl.Series("station_name", out_names, dtype=pl.String),
            pl.Series("latitude", out_lats, dtype=pl.Float64),
            pl.Series("longitude", out_lons, dtype=pl.Float64),
            pl.Series("crs", out_crs, dtype=pl.String),
            _list_series("water_body_name_field", out_wb_field),
            _list_series("water_body_name_value", out_wb_val),
            _list_series("drainage_area_field", out_da_field),
            _list_series("drainage_area_value", out_da_val),
            _list_series("drainage_area_unit", out_da_unit),
            _list_series("elevation_field", out_el_field),
            _list_series("elevation_value", out_el_val),
            _list_series("elevation_unit", out_el_unit),
            _list_series("elevation_datum", out_el_datum),
        ]
    )

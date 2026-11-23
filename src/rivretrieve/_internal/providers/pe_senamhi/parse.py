"""Read SENAMHI native fields without assigning unpublished physical meaning."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import (
    NATIVE_SCHEMA,
    SeriesMapping,
    UnsupportedSourceStructureError,
    parse_mapped_series,
)
from rivretrieve._internal.providers.pe_senamhi.series import SenamhiSourceCoordinates, series_mappings
from rivretrieve._internal.source_series import ParsedSeries, SeriesScope, stable_id


def decode_response(
    content: bytes,
    route: SenamhiSourceCoordinates,
    station: str,
) -> tuple[dict[str, object] | None, str | None]:
    """Decode and validate one SENAMHI JSON envelope, returning ``(data, failure_reason)``."""
    try:
        document = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return None, "Malformed SENAMHI JSON response"
    if not isinstance(document, dict) or type(document.get("status")) is not bool:
        return None, "Malformed SENAMHI response envelope"
    if not document["status"]:
        message = document.get("message")
        return None, "SENAMHI failed response: " + (message if isinstance(message, str) else "unpublished reason")
    data = document.get("data")
    if not isinstance(data, dict):
        return None, "Malformed SENAMHI response data"
    if route.subsystem == "monthly_archive":
        if not isinstance(data.get("columns"), list) or not isinstance(data.get("readings"), list):
            return None, "Malformed SENAMHI monthly response structure"
    else:
        rows_key = "daily" if route.resolution == "DAILY" else "hourly"
        raw_rows = data.get(rows_key)
        if not isinstance(raw_rows, list) or any(not isinstance(row, dict) for row in raw_rows):
            return None, "Malformed SENAMHI PHISIS response structure"
        identity = data.get("station")
        if not isinstance(identity, dict) or identity.get("code") != station:
            return None, "SENAMHI response does not match the requested station"
        if (data.get("type"), data.get("variable"), data.get("unit")) != (route.resolution, route.variable, route.unit):
            return None, "SENAMHI response does not match the requested product"
    return cast("dict[str, object]", data), None


def _combine_field_parts(parts: list[ParsedSeries], acquisition_id: str) -> ParsedSeries:
    if not parts:
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), ())
    return ParsedSeries(
        pl.concat([part.rows for part in parts]),
        tuple(series for part in parts for series in part.series),
        (
            parts[0]
            .inventories[0]
            .model_copy(
                update={
                    "members": tuple(series.series_id for part in parts for series in part.series),
                    "snapshot_id": stable_id(acquisition_id, "supported source fields"),
                }
            ),
        ),
        tuple(outcome for part in parts for outcome in part.outcomes),
        tuple(issue for part in parts for issue in part.issues),
    )


def _native_frame(
    station: str,
    product: ProductId,
    extracted: tuple[list[datetime], list[float | None]] | UnsupportedSourceStructureError,
) -> WithIssues[pl.DataFrame]:
    if isinstance(extracted, UnsupportedSourceStructureError):
        raise extracted
    times, values = extracted
    count = len(times)
    frame = pl.DataFrame(
        {
            "station_id": [station] * count,
            "product_id": [str(product)] * count,
            "time": times,
            "value": values,
            "time_zone": ["unknown"] * count,
        },
        schema=NATIVE_SCHEMA,
    )
    return WithIssues(frame)


def interpret_decoded_group(
    payload: Payload,
    pair_payloads: Mapping[tuple[str, ProductId], Payload],
    data: dict[str, object] | None,
    provider_config: ProviderConfig,
    *,
    response_hash: str | None = None,
) -> dict[tuple[str, ProductId], ParsedSeries]:
    """Build per-pair ``ParsedSeries`` results from an already decoded SENAMHI response."""
    if not pair_payloads:
        raise FatalContractError("SENAMHI group parse requires at least one pair payload")
    stations = {station for station, _ in pair_payloads}
    if len(stations) != 1:
        raise FatalContractError("SENAMHI payload requires one station and selected products")
    if not isinstance(payload.source_coordinates.value, SenamhiSourceCoordinates):
        raise FatalContractError("SENAMHI payload requires source coordinates")

    coords_by_pair: dict[tuple[str, ProductId], SenamhiSourceCoordinates] = {}
    for key, pair_payload in pair_payloads.items():
        station, product = key
        if pair_payload.station_products != ((station, product),):
            raise FatalContractError("Pair payload station_products does not match its group key")
        product_cfg = provider_config.products.get(product)
        coordinate = product_cfg.coordinates.value if product_cfg is not None else None
        if not isinstance(coordinate, SenamhiSourceCoordinates):
            raise FatalContractError("SENAMHI product requires source coordinates")
        coords_by_pair[key] = coordinate

    if data is None:
        empty = ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), ())
        return dict.fromkeys(pair_payloads, empty)

    resolved_hash = response_hash if response_hash is not None else hashlib.sha256(payload.content).hexdigest()
    phisis_fields: dict[tuple[str | None, str, str], tuple[SenamhiSourceCoordinates, set[str]]] = {}
    monthly_fields: list[str] = []
    pair_field_specs: dict[tuple[str, ProductId], list[tuple[str, SeriesMapping, SenamhiSourceCoordinates, bool]]] = {}

    for key, pair_payload in pair_payloads.items():
        station, product = key
        coordinate = coords_by_pair[key]
        pair_scope = pair_payload.scope or SeriesScope(
            provider_ids=("pe_senamhi",),
            station_ids=(station,),
            product_ids=(str(product),),
        )
        specs: list[tuple[str, SeriesMapping, SenamhiSourceCoordinates, bool]] = []
        mappings = series_mappings(coordinate.subsystem, coordinate.resolution, coordinate.variable, coordinate.unit)
        for field, mapping in mappings.items():
            series = mapping.source_series("pe_senamhi", station, product)
            is_matched = pair_scope.matches(series)
            specs.append((field, mapping, coordinate, is_matched))
            if is_matched:
                if coordinate.subsystem == "phisis":
                    route_key = (coordinate.resolution, coordinate.variable, coordinate.unit)
                    entry = phisis_fields.get(route_key)
                    if entry is None:
                        phisis_fields[route_key] = (coordinate, {field})
                    else:
                        entry[1].add(field)
                elif field not in monthly_fields:
                    monthly_fields.append(field)
        pair_field_specs[key] = specs

    extracted_monthly = _extract_monthly_fields(data, tuple(monthly_fields)) if monthly_fields else {}
    extracted_phisis = {
        route_key: _extract_phisis_fields(data, route, tuple(sorted(fields)))
        for route_key, (route, fields) in phisis_fields.items()
    }

    results: dict[tuple[str, ProductId], ParsedSeries] = {}
    for key, pair_payload in pair_payloads.items():
        station, product = key
        parts: list[ParsedSeries] = []
        for field, mapping, coordinate, _is_matched in pair_field_specs[key]:
            if coordinate.subsystem == "phisis":
                route_key = (coordinate.resolution, coordinate.variable, coordinate.unit)

                def native_phisis(
                    tagged: Payload, _cfg: ProviderConfig, rk=route_key, fld=field, st=station, pr=product
                ):
                    return _native_frame(st, pr, extracted_phisis[rk][fld])

                native_fn = native_phisis
            else:

                def native_monthly(tagged: Payload, _cfg: ProviderConfig, fld=field, st=station, pr=product):
                    return _native_frame(st, pr, extracted_monthly[fld])

                native_fn = native_monthly

            parts.append(
                parse_mapped_series(
                    pair_payload,
                    provider_config,
                    provider="pe_senamhi",
                    mappings={product: mapping},
                    native_parse=native_fn,
                    response_hash=resolved_hash,
                )
            )
        results[key] = _combine_field_parts(parts, pair_payload.acquisition_id)
    return results


def parse_group(
    payload: Payload,
    pair_payloads: Mapping[tuple[str, ProductId], Payload],
    provider_config: ProviderConfig,
) -> dict[tuple[str, ProductId], ParsedSeries]:
    """Decode one SENAMHI response once and project per-pair ``ParsedSeries`` results."""
    if not pair_payloads:
        raise FatalContractError("SENAMHI group parse requires at least one pair payload")
    stations = {station for station, _ in pair_payloads}
    if len(stations) != 1:
        raise FatalContractError("SENAMHI payload requires one station and selected products")
    coordinate = payload.source_coordinates.value
    if not isinstance(coordinate, SenamhiSourceCoordinates):
        raise FatalContractError("SENAMHI payload requires source coordinates")
    station = next(iter(stations))
    data, reason = decode_response(payload.content, coordinate, station)
    return interpret_decoded_group(payload, pair_payloads, data if reason is None else None, provider_config)


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Preserve each published field as a separate native source series."""
    if not payload.station_products or len({station for station, _ in payload.station_products}) != 1:
        raise FatalContractError("SENAMHI payload requires one station and selected products")
    coordinate = payload.source_coordinates.value
    if not isinstance(coordinate, SenamhiSourceCoordinates):
        raise FatalContractError("SENAMHI payload requires source coordinates")
    station = payload.station_products[0][0]
    if len(payload.station_products) == 1:
        pair = payload.station_products[0]
        return parse_group(payload, {pair: payload}, provider_config)[pair]

    data, reason = decode_response(payload.content, coordinate, station)
    if reason is not None:
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), ())
    pair_payloads = {pair: replace(payload, station_products=(pair,)) for pair in payload.station_products}
    grouped = interpret_decoded_group(payload, pair_payloads, data, provider_config)
    parts = [grouped[pair] for pair in payload.station_products]
    return _combine_field_parts(parts, payload.acquisition_id)


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise UnsupportedSourceStructureError("SENAMHI value must be numeric or null")
    try:
        number = float(value)
    except OverflowError as error:
        raise UnsupportedSourceStructureError("SENAMHI value must be finite") from error
    if not isfinite(number):
        raise UnsupportedSourceStructureError("SENAMHI value must be finite")
    return number


def _time(value: object, format: str) -> datetime:
    if not isinstance(value, str):
        raise UnsupportedSourceStructureError("SENAMHI timestamp must be a string")
    try:
        result = datetime.strptime(value, format)
    except ValueError as error:
        raise UnsupportedSourceStructureError("Unsupported SENAMHI timestamp") from error
    if result.strftime(format) != value:
        raise UnsupportedSourceStructureError("Unsupported SENAMHI timestamp")
    return result


def _extract_phisis_fields(
    data: dict[str, object],
    coordinate: SenamhiSourceCoordinates,
    fields: tuple[str, ...],
) -> dict[str, tuple[list[datetime], list[float | None]] | UnsupportedSourceStructureError]:
    daily = coordinate.resolution == "DAILY"
    raw_rows = cast("list[dict[str, object]]", data["daily" if daily else "hourly"])
    time_key = "date" if daily else "time"
    time_format = "%Y-%m-%d" if daily else "%Y-%m-%dT%H:%M:%S"

    times_by_field: dict[str, list[datetime]] = {field: [] for field in fields}
    values_by_field: dict[str, list[float | None]] = {field: [] for field in fields}
    errors: dict[str, UnsupportedSourceStructureError] = {}
    active = list(fields)

    for entry in raw_rows:
        missing = [field for field in active if field not in entry]
        if missing:
            missing_err = UnsupportedSourceStructureError("SENAMHI PHISIS row is missing a published field")
            for field in missing:
                errors[field] = missing_err
            active = [field for field in active if field in entry]
            if not active:
                break
        try:
            wall_clock = _time(entry.get(time_key), time_format)
        except UnsupportedSourceStructureError as error:
            for field in active:
                errors[field] = error
            break
        still_active: list[str] = []
        for field in active:
            try:
                number = _number(entry[field])
            except UnsupportedSourceStructureError as error:
                errors[field] = error
            else:
                times_by_field[field].append(wall_clock)
                values_by_field[field].append(number)
                still_active.append(field)
        active = still_active
        if not active:
            break

    return {
        field: errors[field] if field in errors else (times_by_field[field], values_by_field[field]) for field in fields
    }


def _extract_monthly_fields(
    data: dict[str, object],
    fields: tuple[str, ...],
) -> dict[str, tuple[list[datetime], list[float | None]] | UnsupportedSourceStructureError]:
    columns = cast("list[object]", data["columns"])
    if any(not isinstance(column, dict) for column in columns):
        error = UnsupportedSourceStructureError("SENAMHI monthly columns must be objects")
        return dict.fromkeys(fields, error)

    errors: dict[str, UnsupportedSourceStructureError] = {}
    active: list[str] = []
    declared_fields: set[str] = set()
    column_dicts = cast("list[dict[str, object]]", columns)
    for field in fields:
        selected = [column for column in column_dicts if column.get("column") == field]
        if len(selected) > 1 or any(column.get("unit") != "m" for column in selected):
            errors[field] = UnsupportedSourceStructureError(
                "SENAMHI monthly field has inconsistent units or duplicate columns"
            )
            continue
        if selected:
            declared_fields.add(field)
        active.append(field)

    times_by_field: dict[str, list[datetime]] = {field: [] for field in fields}
    values_by_field: dict[str, list[float | None]] = {field: [] for field in fields}
    active_set = set(active)

    if active_set:
        for entry in cast("list[object]", data["readings"]):
            if not isinstance(entry, dict):
                row_err = UnsupportedSourceStructureError("SENAMHI monthly reading requires source values")
                for field in active_set:
                    errors[field] = row_err
                break
            entry_map = cast("dict[str, object]", entry)
            raw_values = entry_map.get("values")
            if not isinstance(raw_values, list):
                row_err = UnsupportedSourceStructureError("SENAMHI monthly reading requires source values")
                for field in active_set:
                    errors[field] = row_err
                break
            try:
                clock = entry_map.get("time")
                wall_clock = (
                    _time(entry_map.get("date"), "%Y-%m-%d")
                    if clock == ""
                    else _time(str(entry_map.get("date")) + " " + str(clock), "%d/%m/%Y %H:%M")
                )
            except UnsupportedSourceStructureError as error:
                for field in active_set:
                    errors[field] = error
                break

            for cell in cast("list[object]", raw_values):
                if not isinstance(cell, dict):
                    cell_err = UnsupportedSourceStructureError("SENAMHI monthly cell requires column and value")
                    for field in active_set:
                        errors[field] = cell_err
                    active_set.clear()
                    break
                cell_map = cast("dict[str, object]", cell)
                if "column" not in cell_map or "value" not in cell_map:
                    cell_err = UnsupportedSourceStructureError("SENAMHI monthly cell requires column and value")
                    for field in active_set:
                        errors[field] = cell_err
                    active_set.clear()
                    break
                cell_col = cell_map["column"]
                if cell_col in active_set:
                    field = cast("str", cell_col)
                    if field not in declared_fields:
                        errors[field] = UnsupportedSourceStructureError(
                            "SENAMHI monthly value lacks its unit declaration"
                        )
                        active_set.remove(field)
                        continue
                    try:
                        number = _number(cell_map["value"])
                    except UnsupportedSourceStructureError as error:
                        errors[field] = error
                        active_set.remove(field)
                    else:
                        times_by_field[field].append(wall_clock)
                        values_by_field[field].append(number)
            if not active_set:
                break

    return {
        field: errors[field] if field in errors else (times_by_field[field], values_by_field[field]) for field in fields
    }

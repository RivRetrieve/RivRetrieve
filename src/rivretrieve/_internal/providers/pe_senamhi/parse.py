"""Read SENAMHI native fields without assigning unpublished physical meaning."""

import json
from dataclasses import replace
from datetime import datetime
from math import isfinite

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_series import NATIVE_SCHEMA, UnsupportedSourceStructureError, parse_mapped_series
from rivretrieve._internal.providers.pe_senamhi.fetch import SenamhiSourceCoordinates, _response_failure
from rivretrieve._internal.providers.pe_senamhi.series import series_mappings
from rivretrieve._internal.source_series import ParsedSeries, stable_id


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    """Preserve each published field as a separate native source series."""
    if not payload.station_products or len({station for station, _ in payload.station_products}) != 1:
        raise FatalContractError("SENAMHI payload requires one station and selected products")
    coordinate = payload.source_coordinates.value
    if not isinstance(coordinate, SenamhiSourceCoordinates):
        raise FatalContractError("SENAMHI payload requires source coordinates")
    if _response_failure(payload.content, coordinate, payload.station_products[0][0]) is not None:
        # Acquisition already retains the failed envelope, outcomes and issues.
        return ParsedSeries(pl.DataFrame(schema=RowsSchema.polars_schema), (), (), ())
    data = json.loads(payload.content)["data"]
    parts = []
    for station, product in payload.station_products:
        coordinate = provider_config.products[product].coordinates.value
        if not isinstance(coordinate, SenamhiSourceCoordinates):
            raise FatalContractError("SENAMHI product requires source coordinates")
        for field, mapping in series_mappings(
            coordinate.subsystem, coordinate.resolution, coordinate.variable, coordinate.unit
        ).items():

            def native(tagged, config, field=field, coordinate=coordinate, station=station, product=product):
                rows = _phisis(data, coordinate, field) if coordinate.subsystem == "phisis" else _monthly(data, field)
                return WithIssues(
                    pl.DataFrame(
                        [
                            {
                                "station_id": station,
                                "product_id": product,
                                "time": time,
                                "value": value,
                                "time_zone": "unknown",
                            }
                            for time, value in rows
                        ],
                        schema=NATIVE_SCHEMA,
                    )
                )

            parts.append(
                parse_mapped_series(
                    replace(payload, station_products=((station, product),)),
                    provider_config,
                    provider="pe_senamhi",
                    mappings={product: mapping},
                    native_parse=native,
                )
            )
    return ParsedSeries(
        pl.concat([part.rows for part in parts]) if parts else pl.DataFrame(schema=RowsSchema.polars_schema),
        tuple(series for part in parts for series in part.series),
        (
            parts[0]
            .inventories[0]
            .model_copy(
                update={
                    "members": tuple(series.series_id for part in parts for series in part.series),
                    "snapshot_id": stable_id(payload.acquisition_id, "supported source fields"),
                }
            ),
        )
        if parts
        else (),
        tuple(outcome for part in parts for outcome in part.outcomes),
        tuple(issue for part in parts for issue in part.issues),
    )


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


def _phisis(data: dict, coordinate: SenamhiSourceCoordinates, field: str) -> list[tuple[datetime, float | None]]:
    daily = coordinate.resolution == "DAILY"
    rows = []
    for entry in data["daily" if daily else "hourly"]:
        if field not in entry:
            raise UnsupportedSourceStructureError("SENAMHI PHISIS row is missing a published field")
        time = _time(entry.get("date" if daily else "time"), "%Y-%m-%d" if daily else "%Y-%m-%dT%H:%M:%S")
        rows.append((time, _number(entry[field])))
    return rows


def _monthly(data: dict, field: str) -> list[tuple[datetime, float | None]]:
    columns = data["columns"]
    if any(not isinstance(column, dict) for column in columns):
        raise UnsupportedSourceStructureError("SENAMHI monthly columns must be objects")
    selected = [column for column in columns if column.get("column") == field]
    if len(selected) > 1 or any(column.get("unit") != "m" for column in selected):
        raise UnsupportedSourceStructureError("SENAMHI monthly field has inconsistent units or duplicate columns")
    rows = []
    for entry in data["readings"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("values"), list):
            raise UnsupportedSourceStructureError("SENAMHI monthly reading requires source values")
        clock = entry.get("time")
        time = (
            _time(entry.get("date"), "%Y-%m-%d")
            if clock == ""
            else _time(str(entry.get("date")) + " " + str(clock), "%d/%m/%Y %H:%M")
        )
        for cell in entry["values"]:
            if not isinstance(cell, dict) or "column" not in cell or "value" not in cell:
                raise UnsupportedSourceStructureError("SENAMHI monthly cell requires column and value")
            if cell["column"] == field:
                if not selected:
                    raise UnsupportedSourceStructureError("SENAMHI monthly value lacks its unit declaration")
                rows.append((time, _number(cell["value"])))
    return rows

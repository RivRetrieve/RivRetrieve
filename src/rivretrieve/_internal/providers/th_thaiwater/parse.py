"""th_thaiwater parse : Payload × ProviderConfig → WithIssues[Rows].

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.th_thaiwater.config import ThThaiWaterSourceCoordinates


def parse(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    if not payload.station_products:
        raise FatalContractError("th_thaiwater payload must contain at least one station-product pair")
    stations = {station for station, _ in payload.station_products}
    if len(stations) != 1:
        raise FatalContractError("th_thaiwater payload must contain exactly one station")
    station = next(iter(stations))
    coordinates = {product: _coordinates(product, provider_config) for _, product in payload.station_products}
    document = _document(payload.content)
    entries = _entries(document, station)

    rows: list[dict[str, object]] = []
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise FatalContractError(f"th_thaiwater observation {index} must be a JSON object")
        entry = cast("dict[str, object]", raw_entry)
        wall_clock = _time(entry, index)
        for station_id, product in payload.station_products:
            field = coordinates[product].native_field
            if field not in entry:
                raise FatalContractError(f"th_thaiwater observation {index} is missing {field}")
            value = entry[field]
            if value is not None and (type(value) not in (int, float)):
                raise FatalContractError(f"th_thaiwater observation {index} field {field} must be numeric or null")
            rows.append(
                {
                    "station_id": station_id,
                    "product_id": product,
                    "time": wall_clock,
                    "value": None if value is None else float(cast("int | float", value)),
                    "time_zone": "unknown",
                }
            )
    result = pl.DataFrame(rows, schema=RowsSchema.polars_schema)
    validate_catalogue(result, RowsSchema, on_issue="raise")
    return WithIssues(value=result, issues=())


def _coordinates(product: ProductId, config: ProviderConfig) -> ThThaiWaterSourceCoordinates:
    try:
        value = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"th_thaiwater product is absent from provider config: {product}") from error
    if not isinstance(value, ThThaiWaterSourceCoordinates):
        raise FatalContractError(f"th_thaiwater product has invalid source coordinates: {product}")
    return value


def _document(content: bytes) -> dict[str, object]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FatalContractError("th_thaiwater payload content is not valid JSON") from error
    if not isinstance(value, dict):
        raise FatalContractError("th_thaiwater payload content must be a JSON object")
    return cast("dict[str, object]", value)


def _entries(document: dict[str, object], station: str) -> list[object]:
    del station
    if document.get("result") != "OK":
        raise FatalContractError("th_thaiwater payload result must be 'OK'")
    data = document.get("data")
    if not isinstance(data, dict):
        raise FatalContractError("th_thaiwater payload data must be a JSON object")
    entries = cast("dict[str, object]", data).get("graph_data")
    if not isinstance(entries, list):
        raise FatalContractError("th_thaiwater payload data.graph_data must be a list")
    return cast("list[object]", entries)


def _time(entry: dict[str, object], index: int) -> datetime:
    value = entry.get("datetime")
    if not isinstance(value, str):
        raise FatalContractError(f"th_thaiwater observation {index} datetime must be a string")
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError as error:
        raise FatalContractError(
            f"th_thaiwater observation {index} datetime must be a strict naive minute timestamp"
        ) from error

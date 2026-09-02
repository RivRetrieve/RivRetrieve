"""lt_lhmt parse : Payload × ProviderConfig → WithIssues[Rows].

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
from rivretrieve._internal.providers.lt_lhmt.config import LtLhmtSourceCoordinates


def parse(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    if not payload.station_products:
        raise FatalContractError("lt_lhmt payload must contain at least one station-product pair")
    stations = {station for station, _ in payload.station_products}
    if len(stations) != 1:
        raise FatalContractError("lt_lhmt payload must contain exactly one station")
    station = next(iter(stations))
    coordinates = {product: _coordinates(product, provider_config) for _, product in payload.station_products}
    document = _document(payload.content)
    entries = _entries(document, station)

    rows: list[dict[str, object]] = []
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise FatalContractError(f"lt_lhmt observation {index} must be a JSON object")
        entry = cast("dict[str, object]", raw_entry)
        wall_clock = _time(entry, index)
        for station_id, product in payload.station_products:
            field = coordinates[product].native_field
            if field not in entry:
                raise FatalContractError(f"lt_lhmt observation {index} is missing {field}")
            value = entry[field]
            if value is not None and (type(value) not in (int, float)):
                raise FatalContractError(f"lt_lhmt observation {index} field {field} must be numeric or null")
            rows.append(
                {
                    "station_id": station_id,
                    "product_id": product,
                    "time": wall_clock,
                    "value": None if value is None else float(cast("int | float", value)),
                    "time_zone": "+00:00",
                }
            )
    result = pl.DataFrame(rows, schema=RowsSchema.polars_schema)
    validate_catalogue(result, RowsSchema, on_issue="raise")
    return WithIssues(value=result, issues=())


def _coordinates(product: ProductId, config: ProviderConfig) -> LtLhmtSourceCoordinates:
    try:
        value = config.products[product].coordinates.value
    except KeyError as error:
        raise FatalContractError(f"lt_lhmt product is absent from provider config: {product}") from error
    if not isinstance(value, LtLhmtSourceCoordinates):
        raise FatalContractError(f"lt_lhmt product has invalid source coordinates: {product}")
    return value


def _document(content: bytes) -> dict[str, object]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FatalContractError("lt_lhmt payload content is not valid JSON") from error
    if not isinstance(value, dict):
        raise FatalContractError("lt_lhmt payload content must be a JSON object")
    return cast("dict[str, object]", value)


def _entries(document: dict[str, object], station: str) -> list[object]:
    source_station = document.get("station")
    if not isinstance(source_station, dict):
        raise FatalContractError("lt_lhmt payload station must be a JSON object")
    if cast("dict[str, object]", source_station).get("code") != station:
        raise FatalContractError("lt_lhmt payload station does not match its requested station")
    entries = document.get("observations")
    if not isinstance(entries, list):
        raise FatalContractError("lt_lhmt payload observations must be a list")
    return cast("list[object]", entries)


def _time(entry: dict[str, object], index: int) -> datetime:
    value = entry.get("observationDateUtc")
    if not isinstance(value, str):
        raise FatalContractError(f"lt_lhmt observation {index} observationDateUtc must be a string")
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise FatalContractError(
            f"lt_lhmt observation {index} observationDateUtc must be a strict UTC date label"
        ) from error

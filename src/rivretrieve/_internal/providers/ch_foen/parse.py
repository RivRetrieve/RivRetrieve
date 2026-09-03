"""ch_foen parse : Payload × ProviderConfig → WithIssues[Rows].

Contributed by: Nicolas Lazaro
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ch_foen.config import ChFoenSourceCoordinates, NativeField


def parse(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    if payload.content.lstrip().startswith(b"{"):
        rows = _parse_rest(payload, provider_config)
    else:
        rows = _parse_flux(payload, provider_config)
    validate_catalogue(rows, RowsSchema, on_issue="raise")
    return WithIssues(rows)


def _parse_rest(payload: Payload, config: ProviderConfig) -> Rows:
    try:
        document = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FatalContractError("ch_foen REST payload is not valid JSON") from exc
    if not isinstance(document, dict) or not isinstance(document.get("payload"), dict):
        raise FatalContractError("ch_foen REST payload must contain a payload object")
    body = cast("dict[str, object]", document["payload"])
    timestamps = body.get("timestamp")
    if not isinstance(timestamps, list):
        raise FatalContractError("ch_foen REST payload timestamp must be an array")
    result: list[dict[str, object]] = []
    for station, product in payload.station_products:
        field = _select_field(
            station, product, config, {key.split("|", 1)[1] for key in body if key.startswith(f"{station}|")}
        )
        values = body.get(f"{station}|{field.name}")
        if not isinstance(values, list) or len(values) != len(timestamps):
            raise FatalContractError("ch_foen REST values must align exactly with timestamps")
        for raw_time, raw_value in zip(timestamps, values, strict=True):
            if not isinstance(raw_time, int) or isinstance(raw_time, bool):
                raise FatalContractError("ch_foen REST timestamp must be integer Unix seconds")
            value = _number_or_none(raw_value)
            result.append(_row(station, product, _naive(datetime.fromtimestamp(raw_time, UTC)), value, field))
    return pl.DataFrame(result, schema=RowsSchema.polars_schema)


def _parse_flux(payload: Payload, config: ProviderConfig) -> Rows:
    try:
        reader = csv.DictReader(io.StringIO(payload.content.decode("utf-8")))
        records = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise FatalContractError("ch_foen Flux payload is not valid CSV") from exc
    required = {"_time", "_value", "_field", "_measurement", "loc"}
    if reader.fieldnames is None or not required <= set(reader.fieldnames):
        raise FatalContractError("ch_foen Flux CSV is missing required columns")
    result: list[dict[str, object]] = []
    for station, product in payload.station_products:
        station_records = [row for row in records if row["loc"] == station]
        if any(row["_measurement"] != "hydro" for row in station_records):
            raise FatalContractError("ch_foen Flux measurement must be hydro")
        field = _select_field(station, product, config, {row["_field"] for row in station_records})
        for record in station_records:
            if record["_field"] != field.name:
                continue
            try:
                instant = datetime.fromisoformat(record["_time"])
            except ValueError as exc:
                raise FatalContractError("ch_foen Flux timestamp must be RFC3339") from exc
            if instant.tzinfo is None or instant.utcoffset() != UTC.utcoffset(instant):
                raise FatalContractError("ch_foen Flux timestamp must be explicit UTC")
            result.append(_row(station, product, _naive(instant), _number_or_none(record["_value"]), field))
    return pl.DataFrame(result, schema=RowsSchema.polars_schema)


def _select_field(station: str, product: ProductId, config: ProviderConfig, present: set[str]) -> NativeField:
    try:
        coordinates = config.products[product].coordinates.value
    except KeyError as exc:
        raise FatalContractError(f"ch_foen product is absent from provider config: {product}") from exc
    if not isinstance(coordinates, ChFoenSourceCoordinates):
        raise FatalContractError(f"ch_foen product has invalid source coordinates: {product}")
    matched = tuple(field for field in coordinates.fields if field.name in present)
    if len(matched) > 1:
        raise FatalContractError(f"ch_foen returned multiple alternatives for station {station} and product {product}")
    if not matched:
        raise FatalContractError(f"ch_foen returned no declared field for station {station} and product {product}")
    return matched[0]


def _number_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str | int | float) or isinstance(value, bool):
        raise FatalContractError("ch_foen observation value must be numeric or null")
    try:
        return float(value)
    except ValueError as exc:
        raise FatalContractError("ch_foen observation value must be numeric or null") from exc


def _row(
    station: str, product: ProductId, time: datetime, value: float | None, field: NativeField
) -> dict[str, object]:
    return {"station_id": station, "product_id": product, "time": time, "value": value, "time_zone": "+00:00"}


def _naive(value: datetime) -> datetime:
    return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second, value.microsecond)

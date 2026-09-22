"""cz_chmi native observations and source-series evidence.

Contributed by: Thiago von Däniken
"""

import json
from datetime import datetime
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, Unit, WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import NATIVE_SCHEMA, UnsupportedSourceStructureError, parse_mapped_series
from rivretrieve._internal.providers.cz_chmi.config import SERIES_MAPPINGS, CzChmiSourceCoordinates
from rivretrieve._internal.providers.cz_chmi.fetch import CzChmiRequestCoordinates
from rivretrieve._internal.source_series import ParsedSeries

_NATIVE_UNITS = {Unit.CM: "CM", Unit.M3_S: "M3_S", Unit.DEG_C: "0C"}


def _parse_native(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    if not payload.station_products:
        raise FatalContractError("cz_chmi payload must contain at least one station-product pair")
    stations = {station_id for station_id, _ in payload.station_products}
    if len(stations) != 1:
        raise FatalContractError("cz_chmi payload station-product pairs must name one station")
    station_id = next(iter(stations))
    try:
        document = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("cz_chmi payload content is not valid JSON") from error
    if not isinstance(document, dict):
        raise UnsupportedSourceStructureError("cz_chmi payload content must be a JSON object")
    if document.get("objID") != station_id:
        raise UnsupportedSourceStructureError("cz_chmi payload station identity differs from its request tag")
    series = document.get("tsList")
    if not isinstance(series, list):
        raise UnsupportedSourceStructureError("cz_chmi tsList must be a list")

    request_coordinates = payload.source_coordinates.value
    if not isinstance(request_coordinates, CzChmiRequestCoordinates):
        raise FatalContractError("cz_chmi payload has invalid request coordinates")

    requested: dict[str, ProductId] = {}
    for tagged_station, product_id in payload.station_products:
        del tagged_station
        try:
            product = provider_config.products[product_id]
        except KeyError as error:
            raise FatalContractError(f"cz_chmi product is absent from provider config: {product_id}") from error
        coordinates = product.coordinates.value
        if not isinstance(coordinates, CzChmiSourceCoordinates):
            raise FatalContractError(f"cz_chmi product has invalid source coordinates: {product_id}")
        if coordinates.ts_con_id in requested:
            raise FatalContractError("cz_chmi payload has duplicate native time-series requests")
        if coordinates.file_code != request_coordinates.file_code:
            raise FatalContractError("cz_chmi payload combines products from different annual files")
        requested[coordinates.ts_con_id] = product_id
    if tuple(requested) != request_coordinates.ts_con_ids:
        raise FatalContractError("cz_chmi payload request coordinates differ from its product tags")

    found: set[str] = set()
    malformed_identity = False
    records: list[dict[str, object]] = []
    for raw_series in series:
        if not isinstance(raw_series, dict):
            malformed_identity = True
            continue
        ts_con_id = raw_series.get("tsConID")
        if not isinstance(ts_con_id, str):
            # An unassignable source entry must not discard identified siblings.
            malformed_identity = True
            continue
        if ts_con_id not in requested:
            continue
        if ts_con_id in found:
            raise UnsupportedSourceStructureError("cz_chmi requested time series must occur exactly once")
        found.add(ts_con_id)
        product_id = requested[ts_con_id]
        product = provider_config.products[product_id]
        if raw_series.get("unit") != _NATIVE_UNITS[product.unit]:
            raise UnsupportedSourceStructureError(f"cz_chmi native unit differs from config for {product_id}")
        values = _values(raw_series)
        for row_number, raw_row in enumerate(values, start=1):
            if not isinstance(raw_row, list) or len(raw_row) != 2:
                raise UnsupportedSourceStructureError(f"cz_chmi {ts_con_id} row {row_number} must contain DT and VAL")
            raw_time, raw_value = raw_row
            wall_clock = _utc_wall_clock(raw_time, ts_con_id, row_number)
            if request_coordinates.file_code == "DQ" and any(
                (wall_clock.hour, wall_clock.minute, wall_clock.second, wall_clock.microsecond)
            ):
                raise UnsupportedSourceStructureError(
                    f"cz_chmi {ts_con_id} row {row_number} daily timestamp must label midnight"
                )
            if raw_value is not None and (isinstance(raw_value, bool) or not isinstance(raw_value, int | float)):
                raise UnsupportedSourceStructureError(
                    f"cz_chmi {ts_con_id} row {row_number} value must be numeric or null"
                )
            try:
                number = None if raw_value is None else float(raw_value)
            except OverflowError as error:
                raise UnsupportedSourceStructureError(
                    f"cz_chmi {ts_con_id} row {row_number} value is not representable as a finite number"
                ) from error
            if number is not None and not isfinite(number):
                raise UnsupportedSourceStructureError(f"cz_chmi {ts_con_id} row {row_number} value must be finite")
            records.append(
                {
                    "station_id": station_id,
                    "product_id": product_id,
                    "time": wall_clock,
                    "value": number,
                    "time_zone": "+00:00",
                }
            )
    missing = sorted(set(requested) - found)
    if missing:
        detail = "; tsConID identity must be a string" if malformed_identity else ""
        raise UnsupportedSourceStructureError(
            f"cz_chmi payload is missing requested time series: {', '.join(missing)}{detail}"
        )
    rows = pl.DataFrame(records, schema=NATIVE_SCHEMA)
    return WithIssues(value=rows, issues=())


def _values(series: dict[str, object]) -> list[object]:
    ts_data = series.get("tsData")
    if not isinstance(ts_data, dict):
        raise UnsupportedSourceStructureError("cz_chmi tsData must be a DataCollection object")
    ts_data_object = cast("dict[str, object]", ts_data)
    if ts_data_object.get("type") != "DataCollection":
        raise UnsupportedSourceStructureError("cz_chmi tsData must be a DataCollection object")
    data = ts_data_object.get("data")
    if not isinstance(data, dict):
        raise UnsupportedSourceStructureError("cz_chmi time-series header must be DT,VAL")
    data_object = cast("dict[str, object]", data)
    if data_object.get("header") != "DT,VAL":
        raise UnsupportedSourceStructureError("cz_chmi time-series header must be DT,VAL")
    values = data_object.get("values")
    if not isinstance(values, list):
        raise UnsupportedSourceStructureError("cz_chmi time-series values must be a list")
    return cast("list[object]", values)


def _utc_wall_clock(value: object, series: str, row_number: int) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise UnsupportedSourceStructureError(f"cz_chmi {series} row {row_number} timestamp must have a UTC Z suffix")
    try:
        wall_clock = datetime.fromisoformat(value[:-1])
    except ValueError as error:
        raise UnsupportedSourceStructureError(f"cz_chmi {series} row {row_number} timestamp is invalid") from error
    if wall_clock.tzinfo is not None:
        raise UnsupportedSourceStructureError(
            f"cz_chmi {series} row {row_number} timestamp has an offset before its UTC Z suffix"
        )
    return wall_clock


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    from dataclasses import replace

    from rivretrieve._internal.engine import SourceCoordinates

    request_coordinates = payload.source_coordinates.value
    if not isinstance(request_coordinates, CzChmiRequestCoordinates):
        raise FatalContractError("cz_chmi payload has invalid request coordinates")
    expected_ids = []
    for _, product in payload.station_products:
        if product not in provider_config.products:
            raise FatalContractError("cz_chmi product is absent from provider config")
        coordinates = provider_config.products[product].coordinates.value
        if not isinstance(coordinates, CzChmiSourceCoordinates):
            raise FatalContractError("cz_chmi product has invalid source coordinates")
        if coordinates.file_code != request_coordinates.file_code:
            raise FatalContractError("cz_chmi request coordinates combine different annual files")
        expected_ids.append(coordinates.ts_con_id)
    if tuple(expected_ids) != request_coordinates.ts_con_ids:
        raise FatalContractError("cz_chmi request coordinates differ from product tags")

    def narrow(tagged: Payload, product: str) -> Payload:
        coordinates = tagged.source_coordinates.value
        if not isinstance(coordinates, CzChmiRequestCoordinates):
            raise FatalContractError("cz_chmi payload has invalid request coordinates")
        mapping = SERIES_MAPPINGS[product]
        assert mapping.published_id is not None
        return replace(
            tagged, source_coordinates=SourceCoordinates(replace(coordinates, ts_con_ids=(mapping.published_id,)))
        )

    return parse_mapped_series(
        payload,
        provider_config,
        provider="cz_chmi",
        mappings=SERIES_MAPPINGS,
        native_parse=_parse_native,
        narrow_payload=narrow,
    )

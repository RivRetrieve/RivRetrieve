"""th_thaiwater native observations and source-series evidence.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import NATIVE_SCHEMA, UnsupportedSourceStructureError, parse_mapped_series
from rivretrieve._internal.providers.th_thaiwater.config import SERIES_MAPPINGS, ThThaiWaterSourceCoordinates
from rivretrieve._internal.providers.th_thaiwater.issue_codes import ThThaiWaterObservationIssueCodes
from rivretrieve._internal.source_series import ParsedSeries


def _parse_native(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    if not payload.station_products:
        raise FatalContractError("th_thaiwater payload must contain at least one station-product pair")
    stations = {station for station, _ in payload.station_products}
    if len(stations) != 1:
        raise FatalContractError("th_thaiwater payload must contain exactly one station")
    station = next(iter(stations))
    coordinates = {product: _coordinates(product, provider_config) for _, product in payload.station_products}
    document = _document(payload.content)
    if document.get("result") == "NO":
        source_message = document.get("data")
        if not isinstance(source_message, str) or not source_message.strip():
            raise UnsupportedSourceStructureError("th_thaiwater source failure must carry a non-empty data message")
        return WithIssues(
            value=pl.DataFrame(schema=NATIVE_SCHEMA),
            issues=(
                Issue(
                    severity="error",
                    code=ThThaiWaterObservationIssueCodes.SOURCE_REQUEST_FAILED,
                    message=f"ThaiWater reported a source failure for station {station}: {source_message}",
                    details={
                        "station_id": station,
                        "product_ids": [str(product) for product in coordinates],
                        "source_result": "NO",
                        "source_message": source_message,
                    },
                    provider_id=ProviderId("th_thaiwater"),
                ),
            ),
        )
    entries = _entries(document)

    rows: list[dict[str, object]] = []
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise UnsupportedSourceStructureError(f"th_thaiwater observation {index} must be a JSON object")
        entry = cast("dict[str, object]", raw_entry)
        wall_clock = _time(entry, index)
        for station_id, product in payload.station_products:
            field = coordinates[product].native_field
            if field not in entry:
                raise UnsupportedSourceStructureError(f"th_thaiwater observation {index} is missing {field}")
            value = entry[field]
            if value is not None and (type(value) not in (int, float)):
                raise UnsupportedSourceStructureError(
                    f"th_thaiwater observation {index} field {field} must be numeric or null"
                )
            rows.append(
                {
                    "station_id": station_id,
                    "product_id": product,
                    "time": wall_clock,
                    "value": None if value is None else float(cast("int | float", value)),
                    "time_zone": "unknown",
                }
            )
    result = pl.DataFrame(rows, schema=NATIVE_SCHEMA)
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
        raise UnsupportedSourceStructureError("th_thaiwater payload content is not valid JSON") from error
    if not isinstance(value, dict):
        raise UnsupportedSourceStructureError("th_thaiwater payload content must be a JSON object")
    return cast("dict[str, object]", value)


def _entries(document: dict[str, object]) -> list[object]:
    if document.get("result") != "OK":
        raise UnsupportedSourceStructureError("th_thaiwater payload result must be 'OK'")
    data = document.get("data")
    if not isinstance(data, dict):
        raise UnsupportedSourceStructureError("th_thaiwater payload data must be a JSON object")
    entries = cast("dict[str, object]", data).get("graph_data")
    if not isinstance(entries, list):
        raise UnsupportedSourceStructureError("th_thaiwater payload data.graph_data must be a list")
    return cast("list[object]", entries)


def _time(entry: dict[str, object], index: int) -> datetime:
    value = entry.get("datetime")
    if not isinstance(value, str):
        raise UnsupportedSourceStructureError(f"th_thaiwater observation {index} datetime must be a string")
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError as error:
        raise UnsupportedSourceStructureError(
            f"th_thaiwater observation {index} datetime must be a strict naive minute timestamp"
        ) from error


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    return parse_mapped_series(
        payload, provider_config, provider="th_thaiwater", mappings=SERIES_MAPPINGS, native_parse=_parse_native
    )

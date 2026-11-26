"""th_thaiwater native observations and source-series evidence.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import (
    NATIVE_SCHEMA,
    UnsupportedSourceStructureError,
    parse_mapped_group,
    parse_mapped_series,
)
from rivretrieve._internal.providers.th_thaiwater.config import SERIES_MAPPINGS, ThThaiWaterSourceCoordinates
from rivretrieve._internal.providers.th_thaiwater.issue_codes import ThThaiWaterObservationIssueCodes
from rivretrieve._internal.source_series import ParsedSeries


def _numeric_field(entry: dict[str, object], field: str, index: int) -> float | None:
    if field not in entry:
        raise UnsupportedSourceStructureError(f"th_thaiwater observation {index} is missing {field}")
    value = entry[field]
    if value is not None and (type(value) not in (int, float)):
        raise UnsupportedSourceStructureError(f"th_thaiwater observation {index} field {field} must be numeric or null")
    try:
        number = None if value is None else float(cast("int | float", value))
    except OverflowError as error:
        raise UnsupportedSourceStructureError(
            f"th_thaiwater observation {index} field {field} is not representable as a finite number"
        ) from error
    if number is not None and not isfinite(number):
        raise UnsupportedSourceStructureError(f"th_thaiwater observation {index} field {field} must be finite")
    return number


def _extract_native_group(
    payload: Payload,
    pair_payloads: Mapping[tuple[str, ProductId], Payload],
    provider_config: ProviderConfig,
) -> Mapping[tuple[str, ProductId], WithIssues[Rows] | UnsupportedSourceStructureError]:
    if not pair_payloads:
        raise FatalContractError("th_thaiwater payload must contain at least one station-product pair")
    stations = {station for station, _ in pair_payloads}
    if len(stations) != 1:
        raise FatalContractError("th_thaiwater payload must contain exactly one station")
    station = next(iter(stations))
    coordinates = {key: _coordinates(key[1], provider_config) for key in pair_payloads}
    document = _document(payload.content)
    if document.get("result") == "NO":
        source_message = document.get("data")
        if not isinstance(source_message, str) or not source_message.strip():
            raise UnsupportedSourceStructureError("th_thaiwater source failure must carry a non-empty data message")
        del document
        empty_rows = pl.DataFrame(schema=NATIVE_SCHEMA)
        product_ids = [str(product) for _, product in pair_payloads]
        return {
            key: WithIssues(
                value=empty_rows,
                issues=(
                    Issue(
                        severity="error",
                        code=ThThaiWaterObservationIssueCodes.SOURCE_REQUEST_FAILED,
                        message=f"ThaiWater reported a source failure for station {station}: {source_message}",
                        details={
                            "station_id": station,
                            "product_ids": product_ids,
                            "source_result": "NO",
                            "source_message": source_message,
                        },
                        provider_id=ProviderId("th_thaiwater"),
                    ),
                ),
            )
            for key in pair_payloads
        }
    entries = _entries(document)

    times_by_key: dict[tuple[str, ProductId], list[datetime]] = {key: [] for key in pair_payloads}
    values_by_key: dict[tuple[str, ProductId], list[float | None]] = {key: [] for key in pair_payloads}
    errors_by_key: dict[tuple[str, ProductId], UnsupportedSourceStructureError] = {}
    active_keys = list(pair_payloads)

    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            row_error = UnsupportedSourceStructureError(f"th_thaiwater observation {index} must be a JSON object")
            for key in active_keys:
                errors_by_key[key] = row_error
            break
        entry = cast("dict[str, object]", raw_entry)
        try:
            wall_clock = _time(entry, index)
        except UnsupportedSourceStructureError as error:
            for key in active_keys:
                errors_by_key[key] = error
            break

        still_active: list[tuple[str, ProductId]] = []
        for key in active_keys:
            try:
                number = _numeric_field(entry, coordinates[key].native_field, index)
            except UnsupportedSourceStructureError as error:
                errors_by_key[key] = error
            else:
                times_by_key[key].append(wall_clock)
                values_by_key[key].append(number)
                still_active.append(key)
        active_keys = still_active
        if not active_keys:
            break

    del document, entries
    results: dict[tuple[str, ProductId], WithIssues[Rows] | UnsupportedSourceStructureError] = {}
    for key in pair_payloads:
        if key in errors_by_key:
            results[key] = errors_by_key[key]
            continue
        station_id, product = key
        times = times_by_key[key]
        count = len(times)
        frame = pl.DataFrame(
            {
                "station_id": [station_id] * count,
                "product_id": [str(product)] * count,
                "time": times,
                "value": values_by_key[key],
                "time_zone": ["unknown"] * count,
            },
            schema=NATIVE_SCHEMA,
        )
        results[key] = WithIssues(value=frame, issues=())
    return results


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
        payload,
        provider_config,
        provider="th_thaiwater",
        mappings=SERIES_MAPPINGS,
        native_parse_group=_extract_native_group,
    )


def parse_group(
    payload: Payload,
    pair_payloads: Mapping[tuple[str, ProductId], Payload],
    provider_config: ProviderConfig,
) -> Mapping[tuple[str, ProductId], ParsedSeries]:
    """Decode one shared ThaiWater graph response once across co-acquired products."""
    return parse_mapped_group(
        payload,
        pair_payloads,
        provider_config,
        provider="th_thaiwater",
        mappings=SERIES_MAPPINGS,
        native_parse_group=_extract_native_group,
    )

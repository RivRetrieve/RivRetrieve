"""fr_hydroportail native observations and source-series evidence.

Contributed by: Thiago von Däniken
"""

import json
from datetime import datetime
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_series import NATIVE_SCHEMA, UnsupportedSourceStructureError, parse_mapped_series
from rivretrieve._internal.providers.fr_hydroportail.config import SERIES_MAPPINGS, FrHydroportailSourceCoordinates
from rivretrieve._internal.source_series import ParsedSeries


def _parse_native(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    if len(payload.station_products) != 1:
        raise FatalContractError("fr_hydroportail payload must contain one station-product pair")
    station, product = payload.station_products[0]
    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, FrHydroportailSourceCoordinates):
        raise FatalContractError("fr_hydroportail payload has invalid source coordinates")
    try:
        document = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("fr_hydroportail payload content is not valid JSON") from error
    if not isinstance(document, dict):
        raise UnsupportedSourceStructureError("fr_hydroportail payload must be a JSON object")
    root = cast("dict[str, object]", document)
    series_value = root.get("series")
    if not isinstance(series_value, dict):
        raise UnsupportedSourceStructureError("fr_hydroportail payload has no series object")
    series = cast("dict[str, object]", series_value)
    if series.get("code") != station:
        raise UnsupportedSourceStructureError("fr_hydroportail response contains an unexpected station identity")
    if series.get("metric") != coordinates.field:
        raise UnsupportedSourceStructureError("fr_hydroportail response contains an unexpected metric")
    title = series.get("title")
    expected_title = "Hauteur instantanée" if coordinates.field == "H" else "Débit instantané"
    if not isinstance(title, str) or title.partition(" - ")[0] != expected_title:
        raise UnsupportedSourceStructureError(
            "fr_hydroportail title does not establish the requested instantaneous quantity"
        )
    expected_unit = "mm" if coordinates.field == "H" else "l"
    if series.get("unit") != expected_unit or root.get("timezone") != "UTC":
        raise UnsupportedSourceStructureError(
            "fr_hydroportail unit or timezone differs from the evidenced source contract"
        )
    if series.get("statuses") != "raw":
        raise UnsupportedSourceStructureError("fr_hydroportail response does not contain the requested raw series")
    raw_rows = series.get("data")
    if not isinstance(raw_rows, list):
        raise UnsupportedSourceStructureError("fr_hydroportail payload has no observation data list")
    rows: list[dict[str, object]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise UnsupportedSourceStructureError("fr_hydroportail observation must be an object")
        row = cast("dict[str, object]", raw)
        raw_time = row.get("t")
        if not isinstance(raw_time, str) or not raw_time.endswith("Z"):
            raise UnsupportedSourceStructureError("fr_hydroportail timestamp must end in Z")
        timestamp = _naive(raw_time[:-1])
        value = _value(row, "v")
        zone = "+00:00"
        rows.append(
            {"station_id": station, "product_id": product, "time": timestamp, "value": value, "time_zone": zone}
        )
    frame = pl.DataFrame(rows, schema=NATIVE_SCHEMA).sort("time")
    return WithIssues(frame)


def _naive(value: object) -> datetime:
    if not isinstance(value, str):
        raise UnsupportedSourceStructureError("fr_hydroportail observation timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise UnsupportedSourceStructureError("fr_hydroportail observation timestamp is invalid") from error
    if parsed.tzinfo is not None:
        raise UnsupportedSourceStructureError("fr_hydroportail parser expected a naive wall-clock timestamp")
    return parsed


def _value(row: dict[str, object], field: str) -> float | None:
    if field not in row:
        raise UnsupportedSourceStructureError(f"fr_hydroportail observation is missing its {field} measurement")
    value = row[field]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise UnsupportedSourceStructureError("fr_hydroportail observation value must be numeric or null")
    try:
        number = float(value)
    except OverflowError as error:
        raise UnsupportedSourceStructureError(
            "fr_hydroportail observation value is not representable as a finite number"
        ) from error
    if not isfinite(number):
        raise UnsupportedSourceStructureError("fr_hydroportail observation value must be finite")
    return number


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    return parse_mapped_series(
        payload, provider_config, provider="fr_hydroportail", mappings=SERIES_MAPPINGS, native_parse=_parse_native
    )

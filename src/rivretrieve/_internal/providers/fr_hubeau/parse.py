"""fr_hubeau native observations and source-series evidence.

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
from rivretrieve._internal.providers.fr_hubeau.config import SERIES_MAPPINGS, FrHubeauSourceCoordinates
from rivretrieve._internal.providers.fr_hubeau.fetch import next_url_from_response
from rivretrieve._internal.source_series import ParsedSeries


def _parse_native(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    if len(payload.station_products) != 1:
        raise FatalContractError("fr_hubeau payload must contain one station-product pair")
    station, product = payload.station_products[0]
    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, FrHubeauSourceCoordinates):
        raise FatalContractError("fr_hubeau payload has invalid source coordinates")
    try:
        document = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UnsupportedSourceStructureError("fr_hubeau payload content is not valid JSON") from error
    if not isinstance(document, dict):
        raise UnsupportedSourceStructureError("fr_hubeau payload must be a JSON object")
    root = cast("dict[str, object]", document)
    next_url_from_response(payload.content)
    raw_rows = root.get("data")
    if not isinstance(raw_rows, list):
        raise UnsupportedSourceStructureError("fr_hubeau payload has no observation data list")
    rows: list[dict[str, object]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise UnsupportedSourceStructureError("fr_hubeau observation must be an object")
        row = cast("dict[str, object]", raw)
        if coordinates.family == "daily":
            if row.get("code_station") != station:
                raise UnsupportedSourceStructureError(
                    "fr_hubeau daily response contains an unexpected station identity"
                )
            if row.get("grandeur_hydro_elab") != coordinates.field:
                raise UnsupportedSourceStructureError(
                    "fr_hubeau daily response contains an unexpected grandeur_hydro_elab"
                )
            timestamp = _naive(row.get("date_obs_elab"))
            if any((timestamp.hour, timestamp.minute, timestamp.second, timestamp.microsecond)):
                raise UnsupportedSourceStructureError("fr_hubeau daily observation timestamp must label midnight")
            value = _value(row, "resultat_obs_elab")
            zone = "unknown"
        elif coordinates.family == "temperature":
            if row.get("symbole_unite") != "°C" or row.get("code_unite") != "27":
                raise UnsupportedSourceStructureError(
                    "fr_hubeau temperature unit differs from the published Celsius contract"
                )
            if row.get("code_parametre") != "1301":
                raise UnsupportedSourceStructureError("fr_hubeau temperature parameter is not 1301")
            if row.get("code_station") != station:
                raise UnsupportedSourceStructureError(
                    "fr_hubeau temperature response contains an unexpected station identity"
                )
            date = row.get("date_mesure_temp")
            clock = row.get("heure_mesure_temp")
            if not isinstance(date, str) or not isinstance(clock, str):
                raise UnsupportedSourceStructureError("fr_hubeau temperature timestamp fields must be strings")
            timestamp = _naive(f"{date}T{clock}")
            value = _value(row, "resultat")
            zone = "unknown"
        rows.append(
            {"station_id": station, "product_id": product, "time": timestamp, "value": value, "time_zone": zone}
        )
    frame = pl.DataFrame(rows, schema=NATIVE_SCHEMA).sort("time")
    return WithIssues(frame)


def _naive(value: object) -> datetime:
    if not isinstance(value, str):
        raise UnsupportedSourceStructureError("fr_hubeau observation timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise UnsupportedSourceStructureError("fr_hubeau observation timestamp is invalid") from error
    if parsed.tzinfo is not None:
        raise UnsupportedSourceStructureError("fr_hubeau parser expected a naive wall-clock timestamp")
    return parsed


def _value(row: dict[str, object], field: str) -> float | None:
    if field not in row:
        raise UnsupportedSourceStructureError(f"fr_hubeau observation is missing its {field} measurement")
    value = row[field]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise UnsupportedSourceStructureError("fr_hubeau observation value must be numeric or null")
    try:
        number = float(value)
    except OverflowError as error:
        raise UnsupportedSourceStructureError(
            "fr_hubeau observation value is not representable as a finite number"
        ) from error
    if not isfinite(number):
        raise UnsupportedSourceStructureError("fr_hubeau observation value must be finite")
    return number


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    return parse_mapped_series(
        payload, provider_config, provider="fr_hubeau", mappings=SERIES_MAPPINGS, native_parse=_parse_native
    )

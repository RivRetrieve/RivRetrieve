"""fr_hubeau parse : Payload × ProviderConfig → WithIssues[Rows].

Contributed by: Thiago von Däniken
"""

import json
from datetime import datetime
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.fr_hubeau.config import FrHubeauSourceCoordinates


def parse(payload: Payload, provider_config: ProviderConfig) -> WithIssues[Rows]:
    if len(payload.station_products) != 1:
        raise FatalContractError("fr_hubeau payload must contain one station-product pair")
    station, product = payload.station_products[0]
    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, FrHubeauSourceCoordinates):
        raise FatalContractError("fr_hubeau payload has invalid source coordinates")
    try:
        document = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FatalContractError("fr_hubeau payload content is not valid JSON") from error
    if not isinstance(document, dict):
        raise FatalContractError("fr_hubeau payload must be a JSON object")
    root = cast("dict[str, object]", document)
    series_value = root.get("series")
    if coordinates.family == "hydroportail" and isinstance(series_value, dict):
        raw_rows = cast("dict[str, object]", series_value).get("data")
    else:
        raw_rows = root.get("data")
    if not isinstance(raw_rows, list):
        raise FatalContractError("fr_hubeau payload has no observation data list")
    rows: list[dict[str, object]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise FatalContractError("fr_hubeau observation must be an object")
        row = cast("dict[str, object]", raw)
        if coordinates.family == "daily":
            if row.get("code_station") != station:
                raise FatalContractError("fr_hubeau daily response contains an unexpected station identity")
            if row.get("grandeur_hydro_elab") != coordinates.field:
                raise FatalContractError("fr_hubeau daily response contains an unexpected grandeur_hydro_elab")
            timestamp = _naive(row.get("date_obs_elab"))
            value = _value(row.get("resultat_obs_elab"))
            zone = "unknown"
        elif coordinates.family == "temperature":
            if row.get("code_station") != station:
                raise FatalContractError("fr_hubeau temperature response contains an unexpected station identity")
            date = row.get("date_mesure_temp")
            clock = row.get("heure_mesure_temp")
            if not isinstance(date, str) or not isinstance(clock, str):
                raise FatalContractError("fr_hubeau temperature timestamp fields must be strings")
            timestamp = _naive(f"{date}T{clock}")
            value = _value(row.get("resultat"))
            zone = "unknown"
        else:
            series = cast("dict[str, object]", root["series"])
            expected_code = "Y2510020" if coordinates.field == "Q" else station
            if series.get("code") != expected_code:
                raise FatalContractError("fr_hubeau HydroPortail response contains an unexpected entity identity")
            if series.get("metric") != coordinates.field:
                raise FatalContractError("fr_hubeau HydroPortail response contains an unexpected metric")
            expected_unit = "mm" if coordinates.field == "H" else "l"
            if series.get("unit") != expected_unit or root.get("timezone") != "UTC":
                raise FatalContractError(
                    "fr_hubeau HydroPortail unit or timezone differs from the evidenced source contract"
                )
            raw_time = row.get("t")
            if not isinstance(raw_time, str) or not raw_time.endswith("Z"):
                raise FatalContractError("fr_hubeau HydroPortail timestamp must end in Z")
            timestamp = _naive(raw_time[:-1])
            value = _value(row.get("v"))
            zone = "+00:00"
        rows.append(
            {"station_id": station, "product_id": product, "time": timestamp, "value": value, "time_zone": zone}
        )
    frame = pl.DataFrame(rows, schema=RowsSchema.polars_schema).sort("time")
    validate_catalogue(frame, RowsSchema, on_issue="raise")
    return WithIssues(frame)


def _naive(value: object) -> datetime:
    if not isinstance(value, str):
        raise FatalContractError("fr_hubeau observation timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise FatalContractError("fr_hubeau observation timestamp is invalid") from error
    if parsed.tzinfo is not None:
        raise FatalContractError("fr_hubeau parser expected a naive wall-clock timestamp")
    return parsed


def _value(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise FatalContractError("fr_hubeau observation value must be numeric or null")
    return float(value)

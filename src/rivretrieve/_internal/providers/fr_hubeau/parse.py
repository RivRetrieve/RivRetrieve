"""fr_hubeau native observations and source-series evidence.

Contributed by: Thiago von Däniken
"""

import json
from dataclasses import replace
from datetime import datetime
from math import isfinite
from typing import cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.provider_series import NATIVE_SCHEMA, UnsupportedSourceStructureError, parse_mapped_series
from rivretrieve._internal.providers.fr_hubeau.annotations import (
    FR_HUBEAU_OBS_ELAB_SCHEMA,
    FR_HUBEAU_TEMPERATURE_SCHEMA,
)
from rivretrieve._internal.providers.fr_hubeau.config import SERIES_MAPPINGS, FrHubeauSourceCoordinates
from rivretrieve._internal.source_annotations import AnnotationBundle, ObservationAnnotationTable
from rivretrieve._internal.source_series import ParsedSeries

_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1


def _optional_int64(row: dict[str, object], field: str) -> int | None:
    value = row.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not (_INT64_MIN <= value <= _INT64_MAX):
        raise UnsupportedSourceStructureError(
            f"fr_hubeau observation {field} annotation must be a signed 64-bit integer or null"
        )
    return value


def _optional_str(row: dict[str, object], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise UnsupportedSourceStructureError(f"fr_hubeau observation {field} annotation must be a string or null")
    return value


def _parse_native(
    payload: Payload,
    provider_config: ProviderConfig,
    *,
    annotations_out: list[dict[str, int | str | None]] | None = None,
) -> WithIssues[Rows]:
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
    raw_rows = root.get("data")
    if not isinstance(raw_rows, list):
        raise UnsupportedSourceStructureError("fr_hubeau payload has no observation data list")
    entries: list[tuple[datetime, dict[str, object], dict[str, int | str | None]]] = []
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
            daily_fields: dict[str, int | str | None] = {
                "code_statut": _optional_int64(row, "code_statut"),
                "libelle_statut": _optional_str(row, "libelle_statut"),
                "code_qualification": _optional_int64(row, "code_qualification"),
                "libelle_qualification": _optional_str(row, "libelle_qualification"),
                "code_methode": _optional_int64(row, "code_methode"),
                "libelle_methode": _optional_str(row, "libelle_methode"),
            }
            ann_fields = daily_fields
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
            temp_fields: dict[str, int | str | None] = {
                "code_qualification": _optional_str(row, "code_qualification"),
                "libelle_qualification": _optional_str(row, "libelle_qualification"),
            }
            ann_fields = temp_fields
        else:
            raise UnsupportedSourceStructureError(f"Unsupported fr_hubeau family: {coordinates.family}")
        entries.append(
            (
                timestamp,
                {"station_id": station, "product_id": product, "time": timestamp, "value": value, "time_zone": zone},
                ann_fields,
            )
        )
    entries.sort(key=lambda item: item[0])
    frame = pl.DataFrame([item[1] for item in entries], schema=NATIVE_SCHEMA)
    if annotations_out is not None:
        annotations_out.extend(item[2] for item in entries)
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
    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, FrHubeauSourceCoordinates):
        raise FatalContractError("fr_hubeau payload has invalid source coordinates")
    captured_annotations: list[dict[str, int | str | None]] = []
    parsed = parse_mapped_series(
        payload,
        provider_config,
        provider="fr_hubeau",
        mappings={
            **SERIES_MAPPINGS,
        },
        native_parse=lambda tagged, cfg: _parse_native(tagged, cfg, annotations_out=captured_annotations),
    )
    if parsed.rows.is_empty():
        return replace(parsed, annotations=AnnotationBundle.empty())
    if len(captured_annotations) != parsed.rows.height:
        raise FatalContractError("fr_hubeau parsed rows and observation annotations count mismatch")
    schema = FR_HUBEAU_OBS_ELAB_SCHEMA if coordinates.family == "daily" else FR_HUBEAU_TEMPERATURE_SCHEMA
    dtypes = {"Int64": pl.Int64(), "String": pl.String()}
    ann_frame = parsed.rows.select(
        "series_id", "facts_id", "station_id", "product_id", "time", "time_zone"
    ).with_columns(
        pl.lit(True).cast(pl.Boolean()).alias("measured"),
        *(
            pl.Series(field.name, [item[field.name] for item in captured_annotations], dtype=dtypes[field.dtype])
            for field in schema.fields
        ),
    )
    ann_table = ObservationAnnotationTable.from_rows(
        schema=schema,
        rows=ann_frame,
        measurement_indices=list(range(parsed.rows.height)),
    )
    return replace(parsed, annotations=AnnotationBundle(observation_tables={schema.schema_id: ann_table}))

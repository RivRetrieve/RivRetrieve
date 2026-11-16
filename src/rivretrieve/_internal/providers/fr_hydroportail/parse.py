"""fr_hydroportail native observations and source-series evidence.

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
from rivretrieve._internal.providers.fr_hydroportail.annotations import FR_HYDROPORTAIL_SERIES_SCHEMA
from rivretrieve._internal.providers.fr_hydroportail.config import (
    SERIES_MAPPINGS,
    FrHydroportailSourceCoordinates,
    series_mapping,
)
from rivretrieve._internal.source_annotations import AnnotationBundle, ObservationAnnotationTable
from rivretrieve._internal.source_series import ParsedSeries

_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1


def _parse_native(
    payload: Payload,
    provider_config: ProviderConfig,
    *,
    annotations_out: list[dict[str, int | None]] | None = None,
) -> WithIssues[Rows]:
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
    if series.get("statuses") != coordinates.variant:
        raise UnsupportedSourceStructureError("fr_hydroportail response does not contain the requested source selector")
    raw_rows = series.get("data")
    if not isinstance(raw_rows, list):
        raise UnsupportedSourceStructureError("fr_hydroportail payload has no observation data list")
    entries: list[tuple[datetime, dict[str, object], dict[str, int | None]]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise UnsupportedSourceStructureError("fr_hydroportail observation must be an object")
        row = cast("dict[str, object]", raw)
        raw_time = row.get("t")
        if not isinstance(raw_time, str) or not raw_time.endswith("Z"):
            raise UnsupportedSourceStructureError("fr_hydroportail timestamp must end in Z")
        timestamp = _naive(raw_time[:-1])
        value = _value(row, "v")
        ann_codes = {field.name: _annotation_code(row, field.name) for field in FR_HYDROPORTAIL_SERIES_SCHEMA.fields}
        zone = "+00:00"
        entries.append(
            (
                timestamp,
                {"station_id": station, "product_id": product, "time": timestamp, "value": value, "time_zone": zone},
                ann_codes,
            )
        )
    entries.sort(key=lambda item: item[0])
    frame = pl.DataFrame([item[1] for item in entries], schema=NATIVE_SCHEMA)
    if annotations_out is not None:
        annotations_out.extend(item[2] for item in entries)
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


def _annotation_code(row: dict[str, object], field: str) -> int | None:
    if field not in row:
        raise UnsupportedSourceStructureError(f"fr_hydroportail observation is missing its {field} annotation")
    value = row[field]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not (_INT64_MIN <= value <= _INT64_MAX):
        raise UnsupportedSourceStructureError(
            f"fr_hydroportail observation {field} annotation must be a signed 64-bit integer or null"
        )
    return value


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, FrHydroportailSourceCoordinates):
        raise FatalContractError("fr_hydroportail payload has invalid source coordinates")
    captured_annotations: list[dict[str, int | None]] = []
    parsed = parse_mapped_series(
        payload,
        provider_config,
        provider="fr_hydroportail",
        mappings={product: series_mapping(product, coordinates.variant) for product in SERIES_MAPPINGS},
        native_parse=lambda tagged, cfg: _parse_native(tagged, cfg, annotations_out=captured_annotations),
    )
    series = tuple(item.model_copy(update={"variant": coordinates.variant}) for item in parsed.series)
    if parsed.rows.is_empty():
        return replace(parsed, series=series, annotations=AnnotationBundle.empty())
    if len(captured_annotations) != parsed.rows.height:
        raise FatalContractError("fr_hydroportail parsed rows and observation annotations count mismatch")
    schema = FR_HYDROPORTAIL_SERIES_SCHEMA
    ann_frame = parsed.rows.select(
        "series_id", "facts_id", "station_id", "product_id", "time", "time_zone"
    ).with_columns(
        pl.lit(True).cast(pl.Boolean()).alias("measured"),
        *(
            pl.Series(field.name, [item[field.name] for item in captured_annotations], dtype=pl.Int64())
            for field in schema.fields
        ),
    )
    ann_table = ObservationAnnotationTable.from_rows(
        schema=schema,
        rows=ann_frame,
        measurement_indices=list(range(parsed.rows.height)),
    )
    return replace(
        parsed,
        series=series,
        annotations=AnnotationBundle(observation_tables={schema.schema_id: ann_table}),
    )

"""fr_hubeau native observations and source-series evidence.

Contributed by: Thiago von Däniken
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from math import isfinite
from typing import TYPE_CHECKING, cast

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, Rows, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.provider_series import (
    NATIVE_SCHEMA,
    UnsupportedSourceStructureError,
    parse_mapped_group,
    parse_mapped_series,
)
from rivretrieve._internal.providers.fr_hubeau.annotations import (
    FR_HUBEAU_OBS_ELAB_SCHEMA,
    FR_HUBEAU_TEMPERATURE_SCHEMA,
)
from rivretrieve._internal.providers.fr_hubeau.config import SERIES_MAPPINGS, FrHubeauSourceCoordinates
from rivretrieve._internal.source_annotations import AnnotationBundle, ObservationAnnotationTable
from rivretrieve._internal.source_series import OutcomeStatus, ParsedSeries

if TYPE_CHECKING:
    from rivretrieve._internal.request_planning import ConsumerNeed

_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1


@dataclass(frozen=True, slots=True)
class FrHubeauPageInterpretation:
    """Single-decode Hub'Eau page parse together with validated pagination link state."""

    parsed: ParsedSeries
    next_url: str | None
    next_url_error: str | None = None


@dataclass(frozen=True, slots=True)
class FrHubeauBatchPageInterpretation:
    """Single-decode batched Hub'Eau page parse with per-pair interpretations and next link state."""

    interpretations: dict[tuple[str, ProductId], ParsedSeries]
    next_url: str | None
    next_url_error: str | None = None
    stop_reason: str | None = None


def next_url_from_document(document: object) -> str | None:
    """Extract and validate Hub'Eau's pagination ``next`` URL from a decoded JSON document."""
    if not isinstance(document, dict):
        raise UnsupportedSourceStructureError("fr_hubeau payload must be a JSON object")
    value = cast("dict[str, object]", document).get("next")
    if value is not None and not isinstance(value, str):
        raise UnsupportedSourceStructureError("fr_hubeau response next must be a URL or null")
    if value is not None and not value.startswith("https://hubeau.eaufrance.fr/api/"):
        raise UnsupportedSourceStructureError("fr_hubeau response next URL is outside Hub Eau")
    return value


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


def _extract_observation_entry(
    raw: object,
    coordinates: FrHubeauSourceCoordinates,
    product: ProductId,
    allowed_stations: set[str],
) -> tuple[str, datetime, dict[str, object], dict[str, int | str | None]]:
    if not isinstance(raw, dict):
        raise UnsupportedSourceStructureError("fr_hubeau observation must be an object")
    row = cast("dict[str, object]", raw)
    raw_station = row.get("code_station")
    station = raw_station if isinstance(raw_station, str) and raw_station in allowed_stations else None
    if coordinates.family == "daily":
        if station is None:
            raise UnsupportedSourceStructureError("fr_hubeau daily response contains an unexpected station identity")
        if row.get("grandeur_hydro_elab") != coordinates.field:
            raise UnsupportedSourceStructureError("fr_hubeau daily response contains an unexpected grandeur_hydro_elab")
        timestamp = _naive(row.get("date_obs_elab"))
        if any((timestamp.hour, timestamp.minute, timestamp.second, timestamp.microsecond)):
            raise UnsupportedSourceStructureError("fr_hubeau daily observation timestamp must label midnight")
        value = _value(row, "resultat_obs_elab")
        zone = "unknown"
        ann_fields: dict[str, int | str | None] = {
            "code_statut": _optional_int64(row, "code_statut"),
            "libelle_statut": _optional_str(row, "libelle_statut"),
            "code_qualification": _optional_int64(row, "code_qualification"),
            "libelle_qualification": _optional_str(row, "libelle_qualification"),
            "code_methode": _optional_int64(row, "code_methode"),
            "libelle_methode": _optional_str(row, "libelle_methode"),
        }
    elif coordinates.family == "temperature":
        if row.get("symbole_unite") != "°C" or row.get("code_unite") != "27":
            raise UnsupportedSourceStructureError(
                "fr_hubeau temperature unit differs from the published Celsius contract"
            )
        if row.get("code_parametre") != "1301":
            raise UnsupportedSourceStructureError("fr_hubeau temperature parameter is not 1301")
        if station is None:
            raise UnsupportedSourceStructureError(
                "fr_hubeau temperature response contains an unexpected station identity"
            )
        date_part = row.get("date_mesure_temp")
        clock = row.get("heure_mesure_temp")
        if not isinstance(date_part, str) or not isinstance(clock, str):
            raise UnsupportedSourceStructureError("fr_hubeau temperature timestamp fields must be strings")
        timestamp = _naive(f"{date_part}T{clock}")
        value = _value(row, "resultat")
        zone = "unknown"
        temp_fields: dict[str, int | str | None] = {
            "code_qualification": _optional_str(row, "code_qualification"),
            "libelle_qualification": _optional_str(row, "libelle_qualification"),
        }
        ann_fields = temp_fields
    else:
        raise UnsupportedSourceStructureError(f"Unsupported fr_hubeau family: {coordinates.family}")
    return (
        station,
        timestamp,
        {"station_id": station, "product_id": product, "time": timestamp, "value": value, "time_zone": zone},
        ann_fields,
    )


def _parse_native_document(
    payload: Payload,
    provider_config: ProviderConfig,
    document: object,
    *,
    annotations_out: list[dict[str, int | str | None]] | None = None,
) -> WithIssues[Rows]:
    if len(payload.station_products) != 1:
        raise FatalContractError("fr_hubeau payload must contain one station-product pair")
    station, product = payload.station_products[0]
    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, FrHubeauSourceCoordinates):
        raise FatalContractError("fr_hubeau payload has invalid source coordinates")
    if not isinstance(document, dict):
        raise UnsupportedSourceStructureError("fr_hubeau payload must be a JSON object")
    root = cast("dict[str, object]", document)
    raw_rows = root.get("data")
    if not isinstance(raw_rows, list):
        raise UnsupportedSourceStructureError("fr_hubeau payload has no observation data list")
    entries: list[tuple[datetime, dict[str, object], dict[str, int | str | None]]] = []
    allowed = {station}
    for raw in raw_rows:
        _, timestamp, row_dict, ann_fields = _extract_observation_entry(raw, coordinates, product, allowed)
        entries.append((timestamp, row_dict, ann_fields))
    entries.sort(key=lambda item: item[0])
    frame = pl.DataFrame([item[1] for item in entries], schema=NATIVE_SCHEMA)
    if annotations_out is not None:
        annotations_out.extend(item[2] for item in entries)
    return WithIssues(frame)


def _annotation_bundle(
    rows: pl.DataFrame,
    captured_annotations: list[dict[str, int | str | None]],
    coordinates: FrHubeauSourceCoordinates,
) -> AnnotationBundle:
    if rows.is_empty():
        return AnnotationBundle.empty()
    if len(captured_annotations) != rows.height:
        raise FatalContractError("fr_hubeau parsed rows and observation annotations count mismatch")
    schema = FR_HUBEAU_OBS_ELAB_SCHEMA if coordinates.family == "daily" else FR_HUBEAU_TEMPERATURE_SCHEMA
    dtypes = {"Int64": pl.Int64(), "String": pl.String()}
    ann_frame = rows.select("series_id", "facts_id", "station_id", "product_id", "time", "time_zone").with_columns(
        pl.lit(True).cast(pl.Boolean()).alias("measured"),
        *(
            pl.Series(field.name, [item[field.name] for item in captured_annotations], dtype=dtypes[field.dtype])
            for field in schema.fields
        ),
    )
    ann_table = ObservationAnnotationTable.from_rows(
        schema=schema,
        rows=ann_frame,
        measurement_indices=list(range(rows.height)),
    )
    return AnnotationBundle(observation_tables={schema.schema_id: ann_table})


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


def interpret_page(payload: Payload, provider_config: ProviderConfig) -> FrHubeauPageInterpretation:
    """Decode one Hub'Eau response once into parsed rows, annotations, and validated pagination state."""
    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, FrHubeauSourceCoordinates):
        raise FatalContractError("fr_hubeau payload has invalid source coordinates")
    document: object = None
    decode_error: Exception | None = None
    try:
        document = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        decode_error = error

    def _native_from_decoded(
        tagged: Payload,
        cfg: ProviderConfig,
        *,
        annotations_out: list[dict[str, int | str | None]],
    ) -> WithIssues[Rows]:
        if decode_error is not None:
            raise UnsupportedSourceStructureError("fr_hubeau payload content is not valid JSON") from decode_error
        return _parse_native_document(tagged, cfg, document, annotations_out=annotations_out)

    captured_annotations: list[dict[str, int | str | None]] = []
    parsed = parse_mapped_series(
        payload,
        provider_config,
        provider="fr_hubeau",
        mappings={
            **SERIES_MAPPINGS,
        },
        native_parse=lambda tagged, cfg: _native_from_decoded(tagged, cfg, annotations_out=captured_annotations),
    )
    parsed_result = replace(parsed, annotations=_annotation_bundle(parsed.rows, captured_annotations, coordinates))

    if decode_error is not None:
        return FrHubeauPageInterpretation(
            parsed=parsed_result,
            next_url=None,
            next_url_error="fr_hubeau payload content is not valid JSON",
        )
    try:
        next_url = next_url_from_document(document)
        next_url_error = None
    except UnsupportedSourceStructureError as error:
        next_url = None
        next_url_error = str(error)
    return FrHubeauPageInterpretation(parsed=parsed_result, next_url=next_url, next_url_error=next_url_error)


def interpret_batch_page(
    payload: Payload,
    consumers: tuple[ConsumerNeed, ...],
    provider_config: ProviderConfig,
) -> FrHubeauBatchPageInterpretation:
    """Decode one single-station or batched Hub'Eau response page once."""
    if not consumers:
        raise FatalContractError("fr_hubeau batch page interpretation requires at least one consumer")
    if len(consumers) == 1:
        need = consumers[0]
        single_payload = replace(
            payload,
            station_products=((need.station, need.product),),
            scope=need.scope,
            known_series=need.known_series or payload.known_series,
        )
        single = interpret_page(single_payload, provider_config)
        if any(
            outcome.status in (OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED, OutcomeStatus.FAILED)
            for outcome in single.parsed.outcomes
        ):
            stop_reason: str | None = "Hub Eau cursor chain contains an unsupported observation page"
        else:
            stop_reason = single.next_url_error
        return FrHubeauBatchPageInterpretation(
            interpretations={(need.station, need.product): single.parsed},
            next_url=single.next_url,
            next_url_error=single.next_url_error,
            stop_reason=stop_reason,
        )

    coordinates = payload.source_coordinates.value
    if not isinstance(coordinates, FrHubeauSourceCoordinates):
        raise FatalContractError("fr_hubeau payload has invalid source coordinates")
    product = consumers[0].product
    if any(need.product != product for need in consumers):
        raise FatalContractError("fr_hubeau batched page must share one product")

    resolved_hash = hashlib.sha256(payload.content).hexdigest()
    pair_payloads = {
        (need.station, need.product): replace(
            payload,
            station_products=((need.station, need.product),),
            scope=need.scope,
            known_series=tuple(
                item
                for item in (need.known_series or payload.known_series)
                if item.station_id == need.station and item.product_id == need.product
            ),
        )
        for need in consumers
    }
    allowed_stations = {need.station for need in consumers}
    annotations_by_pair: dict[tuple[str, ProductId], list[dict[str, int | str | None]]] = {}
    page_error: UnsupportedSourceStructureError | None = None
    next_url: str | None = None
    next_url_error: str | None = None
    by_station: dict[str, list[tuple[datetime, dict[str, object], dict[str, int | str | None]]]] = {
        st: [] for st in allowed_stations
    }
    try:
        document = json.loads(payload.content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        page_error = UnsupportedSourceStructureError("fr_hubeau payload content is not valid JSON")
        next_url_error = str(page_error)
    else:
        if not isinstance(document, dict):
            page_error = UnsupportedSourceStructureError("fr_hubeau payload must be a JSON object")
        else:
            raw_rows = cast("dict[str, object]", document).get("data")
            if not isinstance(raw_rows, list):
                page_error = UnsupportedSourceStructureError("fr_hubeau payload has no observation data list")
            else:
                try:
                    for raw in raw_rows:
                        station, timestamp, row_dict, ann_fields = _extract_observation_entry(
                            raw, coordinates, product, allowed_stations
                        )
                        by_station[station].append((timestamp, row_dict, ann_fields))
                except UnsupportedSourceStructureError as error:
                    page_error = error
            try:
                next_url = next_url_from_document(document)
            except UnsupportedSourceStructureError as error:
                next_url = None
                next_url_error = str(error)

    def _native_batch(
        _tagged: Payload,
        matched: Mapping[tuple[str, ProductId], Payload],
        _cfg: ProviderConfig,
    ) -> Mapping[tuple[str, ProductId], WithIssues[Rows]]:
        if page_error is not None:
            raise page_error
        out: dict[tuple[str, ProductId], WithIssues[Rows]] = {}
        for pair_key in matched:
            station, _ = pair_key
            entries = sorted(by_station[station], key=lambda item: item[0])
            annotations_by_pair[pair_key] = [item[2] for item in entries]
            out[pair_key] = WithIssues(pl.DataFrame([item[1] for item in entries], schema=NATIVE_SCHEMA))
        return out

    grouped = parse_mapped_group(
        payload,
        pair_payloads,
        provider_config,
        provider="fr_hubeau",
        mappings=SERIES_MAPPINGS,
        native_parse_group=_native_batch,
        response_hash=resolved_hash,
    )
    empty_rows = pl.DataFrame(schema=RowsSchema.polars_schema)
    final_interpretations: dict[tuple[str, ProductId], ParsedSeries] = {}
    has_unsupported = False
    for pair_key, pair_parsed in grouped.items():
        if any(
            outcome.status in (OutcomeStatus.UNSUPPORTED, OutcomeStatus.UNRESOLVED, OutcomeStatus.FAILED)
            for outcome in pair_parsed.outcomes
        ):
            has_unsupported = True
            final_interpretations[pair_key] = replace(pair_parsed, annotations=AnnotationBundle.empty())
        elif pair_parsed.rows.is_empty():
            # Unsettled station on an intermediate page: leave outcomes/inventories empty until chain completion.
            final_interpretations[pair_key] = ParsedSeries(
                empty_rows,
                pair_parsed.series,
                (),
                (),
                pair_parsed.issues,
            )
        else:
            bundle = _annotation_bundle(pair_parsed.rows, annotations_by_pair.get(pair_key, []), coordinates)
            final_interpretations[pair_key] = replace(pair_parsed, annotations=bundle)

    if page_error is not None or has_unsupported:
        stop_reason = (
            str(page_error)
            if page_error is not None
            else "Hub Eau cursor chain contains an unsupported observation page"
        )
    else:
        stop_reason = next_url_error
    return FrHubeauBatchPageInterpretation(
        interpretations=final_interpretations,
        next_url=next_url if stop_reason is None else None,
        next_url_error=next_url_error,
        stop_reason=stop_reason,
    )


def parse(payload: Payload, provider_config: ProviderConfig) -> ParsedSeries:
    return interpret_page(payload, provider_config).parsed

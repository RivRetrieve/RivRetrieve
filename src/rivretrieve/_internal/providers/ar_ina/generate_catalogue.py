"""Offline catalogue transformations for the official Argentina INA Alerta5 API."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import cast

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
    RecordingReference,
    RetainedInputReceipt,
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.catalogues.station_metadata import MetadataField
from rivretrieve._internal.issues import FatalContractError

EXCLUDED_MAREOGRAPHIC_TABLES: frozenset[str] = frozenset({"estaciones_shn", "estaciones_pvnymm"})
OBSERVATIONAL_PROCEDURES: frozenset[int] = frozenset({1, 2})


@dataclass(frozen=True, slots=True)
class SeriesProductSpec:
    """Verified INA Alerta5 observational series coordinate and canonical unit mapping."""

    var_id: int
    proc_id: int
    product_id: str
    observed_property: str
    expected_unit_id: int
    expected_unit_abrev: str
    canonical_unit: str

    @property
    def native_id(self) -> str:
        return f"var_id={self.var_id};proc_id={self.proc_id}"


IN_SCOPE_SERIES_SPECS: tuple[SeriesProductSpec, ...] = (
    SeriesProductSpec(40, 1, "discharge_daily_mean", "discharge", 10, "m^3/s", "m3/s"),
    SeriesProductSpec(4, 2, "discharge_instantaneous", "discharge", 10, "m^3/s", "m3/s"),
    SeriesProductSpec(48, 1, "discharge_monthly_mean", "discharge", 10, "m^3/s", "m3/s"),
    SeriesProductSpec(51, 1, "discharge_monthly_min", "discharge", 10, "m^3/s", "m3/s"),
    SeriesProductSpec(52, 1, "discharge_monthly_max", "discharge", 10, "m^3/s", "m3/s"),
    SeriesProductSpec(39, 1, "stage_daily_mean", "stage", 11, "m", "m"),
    SeriesProductSpec(2, 1, "stage_instantaneous", "stage", 11, "m", "m"),
    SeriesProductSpec(85, 1, "stage_hourly", "stage", 11, "m", "m"),
    SeriesProductSpec(101, 1, "stage_4hourly", "stage", 11, "m", "m"),
    SeriesProductSpec(67, 1, "stage_weekly_mean", "stage", 11, "m", "m"),
    SeriesProductSpec(33, 1, "stage_monthly_mean", "stage", 11, "m", "m"),
    SeriesProductSpec(49, 1, "stage_monthly_min", "stage", 11, "m", "m"),
    SeriesProductSpec(50, 1, "stage_monthly_max", "stage", 11, "m", "m"),
)

SPECS_BY_VAR_ID: dict[int, SeriesProductSpec] = {spec.var_id: spec for spec in IN_SCOPE_SERIES_SPECS}
SPECS_BY_PRODUCT_ID: dict[str, SeriesProductSpec] = {spec.product_id: spec for spec in IN_SCOPE_SERIES_SPECS}

STATION_SOURCE_SCHEMA = pl.Schema(
    {
        "id": pl.String,
        "nombre": pl.String,
        "rio": pl.String,
        "latitude": pl.Float64,
        "longitude": pl.Float64,
        "tabla": pl.String,
        "pais": pl.String,
        "propietario": pl.String,
        "tipo": pl.String,
        "cero_ign": pl.Float64,
        "altitud": pl.Float64,
        "real": pl.Boolean,
        "has_obs": pl.Boolean,
        "in_estaciones_endpoint": pl.Boolean,
    }
)

STAMPED_STATION_SCHEMA = pl.Schema({**STATION_SOURCE_SCHEMA, "retrieved_at": pl.Datetime("us", "UTC")})

ASSOCIATION_SCHEMA = pl.Schema(
    {
        "station_id": pl.String,
        "product_id": pl.String,
        "var_id": pl.Int64,
        "proc_id": pl.Int64,
        "series_id": pl.Int64,
        "unit_abrev": pl.String,
    }
)


def _positive_int(value: object, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FatalContractError(message)
    return value


def _optional_str(value: object, message: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FatalContractError(message)
    return value


def _optional_bool(value: object, message: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise FatalContractError(message)
    return value


def _optional_float(value: object, message: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise FatalContractError(message)
    numeric = float(value)
    if not math.isfinite(numeric):
        raise FatalContractError(message)
    return numeric


def _as_json_object(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, object]", value)


def _parse_geom(geom: object, *, require_point: bool) -> tuple[float | None, float | None]:
    if geom is None:
        if require_point:
            raise FatalContractError("INA estaciones endpoint record lacks Point geometry")
        return None, None
    geom_obj = _as_json_object(geom)
    if geom_obj is None or geom_obj.get("type") != "Point":
        raise FatalContractError("INA station geom must be a GeoJSON Point or null")
    coords = geom_obj.get("coordinates")
    if not isinstance(coords, list) or len(coords) != 2:
        raise FatalContractError("INA station Point geometry requires [longitude, latitude]")
    lon = _optional_float(coords[0], "INA station longitude must be a finite number")
    lat = _optional_float(coords[1], "INA station latitude must be a finite number")
    if lon is None or lat is None or not (-180.0 <= lon <= 180.0) or not (-90.0 <= lat <= 90.0):
        raise FatalContractError("INA station coordinates fall outside geographic bounds")
    return lat, lon


def _normalize_estacion_row(raw: object, *, in_estaciones_endpoint: bool) -> dict[str, object]:
    row = _as_json_object(raw)
    if row is None:
        raise FatalContractError("INA Estacion record must be a JSON object")
    station_int = _positive_int(row.get("id"), "INA Estacion.id must be a positive integer")
    nombre = _optional_str(row.get("nombre"), "INA Estacion.nombre must be a string or null")
    tabla = _optional_str(row.get("tabla"), "INA Estacion.tabla must be a string")
    if tabla is None or not tabla.strip():
        raise FatalContractError("INA Estacion.tabla must be a nonblank string")
    lat, lon = _parse_geom(row.get("geom"), require_point=in_estaciones_endpoint)
    normalized: dict[str, object] = {
        "id": str(station_int),
        "nombre": nombre,
        "rio": _optional_str(row.get("rio"), "INA Estacion.rio must be a string or null"),
        "latitude": lat,
        "longitude": lon,
        "tabla": tabla,
        "pais": _optional_str(row.get("pais"), "INA Estacion.pais must be a string or null"),
        "propietario": _optional_str(row.get("propietario"), "INA Estacion.propietario must be a string or null"),
        "tipo": _optional_str(row.get("tipo"), "INA Estacion.tipo must be a string or null"),
        "cero_ign": _optional_float(row.get("cero_ign"), "INA Estacion.cero_ign must be a finite number or null"),
        "altitud": _optional_float(row.get("altitud"), "INA Estacion.altitud must be a finite number or null"),
        "real": _optional_bool(row.get("real"), "INA Estacion.real must be a boolean or null"),
        "has_obs": _optional_bool(row.get("has_obs"), "INA Estacion.has_obs must be a boolean or null"),
        "in_estaciones_endpoint": in_estaciones_endpoint,
    }
    if not _is_excluded_estacion(normalized) and (nombre is None or not nombre.strip()):
        raise FatalContractError(f"Retained INA hydrometric station {station_int} lacks a nonblank nombre")
    return normalized


def _is_excluded_estacion(row: Mapping[str, object]) -> bool:
    return row.get("real") is False or row.get("tipo") == "V" or str(row.get("tabla")) in EXCLUDED_MAREOGRAPHIC_TABLES


def _extract_series_rows(payload: object, var_id: int) -> list[dict[str, object]]:
    payload_obj = _as_json_object(payload)
    if payload_obj is None:
        raise FatalContractError(f"INA series response for var_id={var_id} must contain a JSON rows array")
    rows = payload_obj.get("rows")
    if not isinstance(rows, list):
        raise FatalContractError(f"INA series response for var_id={var_id} must contain a JSON rows array")
    if any(not isinstance(item, dict) for item in rows):
        raise FatalContractError(f"INA series rows for var_id={var_id} must be JSON objects")
    return cast("list[dict[str, object]]", rows)


def _shared_estacion_fields(row: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in row.items() if key != "in_estaciones_endpoint"}


def station_native_table_and_associations(
    estaciones_payload: object,
    series_by_var_id: Mapping[int, object],
    *,
    retrieved_at: RetrievedAt,
) -> tuple[NativeTable, pl.DataFrame]:
    """Build the verified 829-gauge INA native table and 2,611 witnessed series associations.

    ``GET /obs/puntual/estaciones`` omits PostGIS rows with ``geom IS NULL`` (station ``96``,
    ``Colorado`` on ``BERMEJO`` in ``alturas_prefe``). Embedded ``series.estacion`` records
    supply coordinate-less gauges while cross-checking every overlapping gauge attribute
    against ``estaciones``. Simulated, forecast, virtual, mareographic, and undated series
    shells establish neither canonical stations nor product availability.
    """
    estaciones_obj = _as_json_object(estaciones_payload)
    if estaciones_obj is not None and "rows" in estaciones_obj:
        raw_estaciones = estaciones_obj["rows"]
    else:
        raw_estaciones = estaciones_payload
    if not isinstance(raw_estaciones, list):
        raise FatalContractError("INA estaciones payload must be a JSON array")
    if set(series_by_var_id) != set(SPECS_BY_VAR_ID):
        raise FatalContractError("INA series catalogue requires all 13 in-scope variable captures")

    estaciones_by_id: dict[str, dict[str, object]] = {}
    for item in raw_estaciones:
        normalized = _normalize_estacion_row(item, in_estaciones_endpoint=True)
        sid = str(normalized["id"])
        if sid in estaciones_by_id:
            raise FatalContractError(f"Duplicate INA Estacion.id {sid!r} in estaciones snapshot")
        estaciones_by_id[sid] = normalized

    selected_stations: dict[str, dict[str, object]] = {}
    seen_pairs: dict[tuple[str, str], int] = {}
    association_rows: list[dict[str, object]] = []

    for var_id in sorted(SPECS_BY_VAR_ID):
        spec = SPECS_BY_VAR_ID[var_id]
        for raw_series in _extract_series_rows(series_by_var_id[var_id], var_id):
            series_id = _positive_int(raw_series.get("id"), "INA Serie.id must be a positive integer")
            var_obj = _as_json_object(raw_series.get("var"))
            proc_obj = _as_json_object(raw_series.get("procedimiento"))
            unit_obj = _as_json_object(raw_series.get("unidades"))
            if var_obj is None or var_obj.get("id") != var_id:
                raise FatalContractError(f"INA series {series_id} disagrees with requested var_id={var_id}")
            if proc_obj is None:
                raise FatalContractError(f"INA series {series_id} lacks procedimiento object")
            proc_id = _positive_int(proc_obj.get("id"), f"INA series {series_id} requires integer procedimiento.id")
            if proc_id not in OBSERVATIONAL_PROCEDURES:
                continue
            raw_date_range = raw_series.get("date_range")
            date_range = _as_json_object(raw_date_range)
            if raw_date_range is not None and date_range is None:
                raise FatalContractError(f"INA series {series_id} has malformed date_range")
            timestart = date_range.get("timestart") if date_range is not None else None
            if timestart is None:
                continue
            if not isinstance(timestart, str) or not timestart.strip():
                raise FatalContractError(f"INA series {series_id} has invalid date_range.timestart")

            embedded = _normalize_estacion_row(raw_series.get("estacion"), in_estaciones_endpoint=False)
            if _is_excluded_estacion(embedded):
                continue

            if proc_id != spec.proc_id:
                raise FatalContractError(
                    f"Unexpected observational procedure {proc_id} on INA var_id={var_id} (series {series_id})"
                )
            if unit_obj is None:
                raise FatalContractError(f"INA series {series_id} lacks unidades object")
            unit_id = unit_obj.get("id")
            unit_abrev = unit_obj.get("abrev")
            if unit_id != spec.expected_unit_id or unit_abrev != spec.expected_unit_abrev:
                raise FatalContractError(
                    f"Unsupported INA unit ({unit_id!r}, {unit_abrev!r}) on series {series_id} for var_id={var_id}"
                )

            sid = str(embedded["id"])
            if sid in estaciones_by_id:
                endpoint_row = estaciones_by_id[sid]
                if _shared_estacion_fields(endpoint_row) != _shared_estacion_fields(embedded):
                    raise FatalContractError(f"INA station {sid} attributes disagree between estaciones and series")
                selected_stations[sid] = endpoint_row
            else:
                if embedded["latitude"] is not None or embedded["longitude"] is not None:
                    raise FatalContractError(f"Coordinate-bearing INA station {sid} is absent from estaciones snapshot")
                previous = selected_stations.get(sid)
                if previous is not None and previous != embedded:
                    raise FatalContractError(f"Coordinate-less INA station {sid} disagrees across series records")
                selected_stations[sid] = embedded

            pair_key = (sid, spec.product_id)
            if pair_key in seen_pairs:
                raise FatalContractError(
                    f"Conflicting INA series IDs ({seen_pairs[pair_key]}, {series_id}) for {pair_key}"
                )
            seen_pairs[pair_key] = series_id
            association_rows.append(
                {
                    "station_id": sid,
                    "product_id": spec.product_id,
                    "var_id": var_id,
                    "proc_id": proc_id,
                    "series_id": series_id,
                    "unit_abrev": str(unit_abrev),
                }
            )

    if not selected_stations:
        raise FatalContractError("INA station selection produced an empty native table")
    native_frame = pl.DataFrame(list(selected_stations.values()), schema=STATION_SOURCE_SCHEMA, strict=True).sort("id")
    associations = pl.DataFrame(association_rows, schema=ASSOCIATION_SCHEMA, strict=True).sort(
        "station_id", "product_id"
    )
    return stamp_native_table(native_frame, retrieved_at), associations


def catalogue_tables(
    native: NativeTable,
    associations: pl.DataFrame,
    *,
    checked_on: date,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Build offline INA Alerta5 tables while keeping unwitnessed pairs unknown."""
    from rivretrieve._internal.catalogues.schemas import (
        PRODUCT_CATALOG_SCHEMA,
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
        validate_catalogue,
    )

    stations = native.data.select(
        pl.lit("ar_ina").alias("provider_id"),
        pl.col("id").alias("station_id"),
        pl.col("latitude").cast(pl.Float64),
        pl.col("longitude").cast(pl.Float64),
        pl.lit("EPSG:4326").alias("crs"),
    ).sort("station_id")
    if not set(associations["station_id"]) <= set(stations["station_id"]):
        raise FatalContractError("INA association references a station absent from canonical hydrometric scope")

    products = pl.DataFrame(
        [
            {
                "provider_id": "ar_ina",
                "product_id": spec.product_id,
                "observed_property": spec.observed_property,
                "frequency": "unknown",
                "statistic": "unknown",
                "period_type": "unknown",
                "period_anchor": "unknown",
                "unit": spec.canonical_unit,
                "native_id": spec.native_id,
            }
            for spec in IN_SCOPE_SERIES_SPECS
        ],
        schema=PRODUCT_CATALOG_SCHEMA.polars_schema,
    ).sort("product_id")

    observed = {(station, product) for station, product in associations.select("station_id", "product_id").iter_rows()}
    pairs = pl.DataFrame(
        [
            {
                "provider_id": "ar_ina",
                "station_id": station,
                "product_id": product,
                "availability": "available" if (station, product) in observed else "unknown",
                "availability_reason": (
                    "Witnessed in retained official INA Alerta5 series inventory; record bounds remain unestablished"
                    if (station, product) in observed
                    else "No in-scope observational series witnessed in retained INA Alerta5 snapshot"
                ),
                "published_record_start_date": None,
                "published_record_end_date": None,
                "last_catalogue_check": checked_on,
            }
            for station in stations["station_id"]
            for product in products["product_id"]
        ],
        schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema,
    )
    for frame, schema in (
        (products, PRODUCT_CATALOG_SCHEMA),
        (stations, STATION_CATALOG_SCHEMA),
        (pairs, STATION_PRODUCT_CATALOG_SCHEMA),
    ):
        validate_catalogue(frame, schema, on_issue="raise")
    return products, stations, pairs


def describe_associations(associations: pl.DataFrame) -> SourceDescriptions:
    """Describe witnessed INA Alerta5 series coordinates with verified units and gauge-zero stage reference."""
    from rivretrieve._internal.catalogues.source_series import SourceDescription, SourceDescriptions
    from rivretrieve._internal.source_series import EvidenceFact, PhysicalFacts, SourceIdentity, known, stable_id

    evidence = "catalogue:ar_ina:source.station_product.series_associations"
    grouped: dict[str, list[str]] = {}
    for station, product in associations.select("station_id", "product_id").unique().iter_rows():
        grouped.setdefault(product, []).append(station)

    descriptions = []
    for product_id in sorted(grouped):
        spec = SPECS_BY_PRODUCT_ID[product_id]
        vertical_ref = (
            known("gauge_zero", "catalogue:ar_ina:source.station.cero_ign_definition")
            if spec.observed_property == "stage"
            else EvidenceFact()
        )
        facts = PhysicalFacts(
            facts_id="pending",
            quantity=known(spec.observed_property, evidence),
            source_unit=known(spec.expected_unit_abrev, evidence),
            normalized_unit=spec.canonical_unit,
            vertical_reference=vertical_ref,
        )
        facts = facts.model_copy(update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))})
        descriptions.append(
            SourceDescription(
                product_id=product_id,
                station_ids=tuple(sorted(grouped[product_id])),
                identity_key=(str(spec.var_id), str(spec.proc_id), spec.expected_unit_abrev),
                native_coordinate=spec.native_id,
                identity=SourceIdentity(
                    namespace="alerta.ina.gob.ar/a5/obs/puntual/series",
                    published_id=spec.native_id,
                    origin="catalogue",
                    evidence=(evidence,),
                ),
                facts=(facts,),
            )
        )
    return SourceDescriptions(provider_id="ar_ina", descriptions=tuple(descriptions))


def read_original(evidence_root: Path, reference: RecordingReference, *, input_receipt: RetainedInputReceipt) -> bytes:
    """Verify one explicitly selected publisher body before parsing it."""
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    selected = {item.consumer_path: item for item in input_receipt.inputs}
    member = selected.get(reference.repository_path)
    if member is None:
        raise FatalContractError("INA original is absent from selected retained inputs")
    if member.sha256 != reference.sha256:
        raise FatalContractError("INA original differs from its selected recording identity")
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    return (evidence_root / reference.repository_path).read_bytes()


@dataclass(frozen=True)
class GeneratedArInaCatalogue:
    provider_info: dict[str, object]
    products: pl.DataFrame
    stations: pl.DataFrame
    station_products: pl.DataFrame
    acquisition_provenance: AcquisitionProvenance
    source_descriptions: SourceDescriptions


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
    *,
    associations: pl.DataFrame,
    checked_on: date,
    provenance: AcquisitionProvenance,
) -> GeneratedArInaCatalogue:
    """Assemble the official Argentina INA Alerta5 offline station and product catalogue."""
    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId

    if native_table.data.schema != STAMPED_STATION_SCHEMA:
        raise FatalContractError("INA native table does not match STAMPED_STATION_SCHEMA")
    if native_table.data.is_empty():
        raise FatalContractError("INA native table must not be empty")

    products, stations, pairs = catalogue_tables(native_table, associations, checked_on=checked_on)
    enforce_catalogue_origins(ProviderId("ar_ina"), origins, native_table, stations)
    if provenance is None or provenance.provider_id != "ar_ina":
        raise FatalContractError("Official INA catalogue requires its selected acquisition provenance")

    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info: dict[str, object] = {
        "provider_id": "ar_ina",
        "name": "Instituto Nacional del Agua (INA) - Sistema de Información Hidrológica Alerta5",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": statements.get("license"),
        "citation": statements.get("citation"),
    }
    return GeneratedArInaCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=pairs,
        acquisition_provenance=provenance,
        source_descriptions=describe_associations(associations),
    )


def write_catalogue(
    catalogue: GeneratedArInaCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
    metadata_fields: tuple[MetadataField, ...] | None = None,
) -> None:
    """Publish candidate runtime tables through the shared evidence-aware publication path."""
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.ar_ina.origins import (
        STATION_CATALOGUE_ORIGINS,
        STATION_METADATA_FIELDS,
        STATION_METADATA_NOTICE,
    )

    files = {
        "provider.json": (json.dumps(catalogue.provider_info, sort_keys=True, separators=(",", ":")) + "\n").encode()
    }
    for name, frame in (
        ("products", catalogue.products),
        ("stations", catalogue.stations),
        ("station_products", catalogue.station_products),
    ):
        buffer = BytesIO()
        frame.write_parquet(buffer)
        files[f"{name}.parquet"] = buffer.getvalue()
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (STATION_CATALOGUE_ORIGINS,),
        files,
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=STATION_METADATA_FIELDS if metadata_fields is None else metadata_fields,
        station_metadata_notice=STATION_METADATA_NOTICE,
        source_descriptions=catalogue.source_descriptions,
    )
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, content in {**files, **metadata}.items():
        (output / name).write_bytes(content)


@dataclass(frozen=True)
class CatalogueSources:
    native_table: NativeTable
    associations: pl.DataFrame
    provenance: AcquisitionProvenance
    checked_on: date


def _read_selection_and_originals(
    evidence_root: Path,
    *,
    selection_path: str,
    input_receipt: RetainedInputReceipt,
) -> tuple[dict[str, object], tuple[RecordingReference, ...], NativeTable, pl.DataFrame]:
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("INA selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt, evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    if not isinstance(selection, dict) or not isinstance(selection.get("captures"), list):
        raise FatalContractError("INA selection requires explicit captures")

    recordings: list[RecordingReference] = []
    estaciones_payload: object | None = None
    series_by_var: dict[int, object] = {}
    retrieval_instants = []

    for capture in selection["captures"]:
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError("INA selected body disagrees with recording identity")
        recordings.append(reference)
        raw = read_original(evidence_root, reference, input_receipt=input_receipt)
        kind = capture["kind"]
        if kind == "estaciones":
            if estaciones_payload is not None:
                raise FatalContractError("INA selection must contain exactly one estaciones snapshot")
            estaciones_payload = json.loads(raw)
            retrieval_instants.append(reference.retrieved_at)
        elif kind == "series_var":
            var_id = _positive_int(capture.get("var_id"), "INA series_var capture requires positive var_id")
            if var_id in series_by_var:
                raise FatalContractError(f"Duplicate INA series_var capture for var_id={var_id}")
            series_by_var[var_id] = json.loads(raw)
            retrieval_instants.append(reference.retrieved_at)
        elif kind == "portal_map":
            text = raw.decode("utf-8")
            if "projection: 'EPSG:4326'" not in text or "cero de escala" not in text:
                raise FatalContractError("INA portal map does not establish EPSG:4326 and cero de escala")
        elif kind == "openapi_spec":
            text = raw.decode("utf-8")
            if "Estacion:" not in text or "enum: [Point]" not in text:
                raise FatalContractError("INA OpenAPI spec does not establish GeoJSON Point Estacion schema")
        elif kind == "terms_html":
            text = raw.decode("utf-8")
            if "Creative Commons Atribución 4.0 Internacional" not in text:
                raise FatalContractError("Argentina.gob.ar terms capture lacks CC BY 4.0 license statement")
        elif kind in {"reference_table", "landing_html", "drainage_audit"}:
            continue
        else:
            raise FatalContractError(f"Unsupported INA capture kind: {kind!r}")

    if estaciones_payload is None:
        raise FatalContractError("INA selection lacks an estaciones snapshot")
    recomputed_native, associations = station_native_table_and_associations(
        estaciones_payload,
        series_by_var,
        retrieved_at=RetrievedAt(max(retrieval_instants)),
    )
    return cast("dict[str, object]", selection), tuple(recordings), recomputed_native, associations


def read_native_sources(
    evidence_root: Path,
    *,
    selection_path: str = "maintenance/catalogue/ar_ina/official/selection.json",
    input_receipt: RetainedInputReceipt,
) -> NativeTable:
    """Recompute the INA native station table from verified selected originals."""
    _, _, recomputed_native, _ = _read_selection_and_originals(
        evidence_root,
        selection_path=selection_path,
        input_receipt=input_receipt,
    )
    return recomputed_native


def read_catalogue_sources(
    evidence_root: Path,
    *,
    selection_path: str = "maintenance/catalogue/ar_ina/official/selection.json",
    input_receipt: RetainedInputReceipt,
) -> CatalogueSources:
    """Read an explicitly selected offline INA build after exact member verification."""
    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.ar_ina import origins

    selection, recordings, recomputed_native, associations = _read_selection_and_originals(
        evidence_root,
        selection_path=selection_path,
        input_receipt=input_receipt,
    )
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    native_path = selection.get("native_table")
    if not isinstance(native_path, str) or native_path not in selected:
        raise FatalContractError("INA native table is absent from selected inputs")
    native_member = selected[native_path]
    retained_native = read_native_table(
        evidence_root / native_path,
        expected_sha256=native_member.sha256,
        expected_byte_size=native_member.byte_size,
    )
    if not retained_native.data.equals(recomputed_native.data):
        raise FatalContractError("INA retained native table differs from recomputed station snapshot")

    native_revision = selection.get("native_revision")
    checked_on_raw = selection.get("checked_on")
    if not isinstance(native_revision, str) or not isinstance(checked_on_raw, str):
        raise FatalContractError("INA selection requires native_revision and checked_on strings")

    provenance = origins.build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path=native_path,
            revision=native_revision,
            sha256=native_member.sha256,
            byte_size=native_member.byte_size,
        ),
        recordings,
        acquisitions=tuple(
            AcquisitionRecord.model_validate(item)
            for item in cast("list[object]", selection["publication_acquisitions"])
        ),
        source_bindings=tuple(
            FactBinding.model_validate(item) for item in cast("list[object]", selection["source_bindings"])
        ),
        statements=tuple(
            SourceStatement.model_validate(item) for item in cast("list[object]", selection["statements"])
        ),
    )
    checked_on = date.fromisoformat(checked_on_raw)
    return CatalogueSources(
        native_table=retained_native,
        associations=associations,
        provenance=provenance,
        checked_on=checked_on,
    )


def selected_supporting_inputs(provenance: AcquisitionProvenance, selection: dict) -> dict[str, tuple[str, ...]]:
    """Associate selected INA acquisition receipts with the facts of their original bodies."""
    receipt_by_body = {capture["body"]: capture["receipt"] for capture in selection["captures"]}
    facts_by_acquisition = {
        (source.source_id, acquisition.acquisition_id): tuple(
            fact
            for binding in provenance.fact_bindings
            if binding.source_id == source.source_id and binding.acquisition_id == acquisition.acquisition_id
            for fact in binding.facts
        )
        for source in provenance.source_records
        for acquisition in source.acquisitions
    }
    result: dict[str, tuple[str, ...]] = {}
    for source in provenance.source_records:
        paths = {item.recording.recording_id: item.recording.repository_path for item in source.evidence}
        for acquisition in source.acquisitions:
            facts = facts_by_acquisition[(source.source_id, acquisition.acquisition_id)]
            for recording_id in acquisition.recording_ids:
                path = paths[recording_id]
                if path in receipt_by_body and facts:
                    result[receipt_by_body[path]] = facts
    return result


def main(argv: list[str] | None = None) -> int:
    """Compose a derived native candidate or runtime INA Alerta5 catalogue outside source checkouts."""
    import argparse

    from rivretrieve._internal.catalogues.native import write_native_table

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--selection", default="maintenance/catalogue/ar_ina/official/selection.json")
    parser.add_argument("--input-receipt", type=Path, required=True)
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--build-inputs", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    output = args.out.resolve()
    evidence_root = args.evidence_root.resolve(strict=True)
    if output.exists() or output.is_relative_to(evidence_root) or evidence_root.is_relative_to(output):
        raise FatalContractError("INA catalogue output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("INA catalogue output must stay outside source checkouts")

    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
    if args.native_only:
        native = read_native_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        write_native_table(native, output / "native.parquet")
        return 0

    if args.build_inputs is None:
        raise FatalContractError("INA catalogue publication requires explicit --build-inputs")
    from rivretrieve._internal.providers.ar_ina.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

    sources = read_catalogue_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
    catalogue = build_catalogue(
        sources.native_table,
        STATION_CATALOGUE_ORIGINS,
        associations=sources.associations,
        checked_on=sources.checked_on,
        provenance=sources.provenance,
    )
    write_catalogue(
        catalogue,
        output,
        build_inputs=CatalogueBuildInputs.model_validate_json(args.build_inputs.read_bytes()),
        native_table=sources.native_table,
        metadata_fields=STATION_METADATA_FIELDS,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

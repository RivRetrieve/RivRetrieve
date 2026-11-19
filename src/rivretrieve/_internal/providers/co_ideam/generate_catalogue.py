"""Offline transformations of Colombia IDEAM S3 station, variable, and object-prefix inventories."""

from __future__ import annotations

import csv
import io
import json
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
    RecordingReference,
    RetainedInputReceipt,
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table
from rivretrieve._internal.catalogues.products import product_row
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.catalogues.station_metadata import MetadataField
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.co_ideam.series import (
    DISCHARGE_LABELS,
    IN_SCOPE_HYDROLOGICAL_LABELS,
    association_product,
    build_source_descriptions,
    route_product_facts,
    validate_s3_observation_csv_bytes,
    validate_socrata_series_view,
    validate_variables_row,
)

S3_XML_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
S3_BUCKET_NAME = "s3-estacionesideam"

SYNTHETIC_STATION_EXCLUSIONS: frozenset[str] = frozenset({"0010000000"})
MARINE_CORRIENTES: frozenset[str] = frozenset({"MAR CARIBE", "PACÍFICO", "OCÉANO PACÍFICO"})
STANDING_CORRIENTE_PATTERN = re.compile(r"\b(?:EMBALSE|REPRESA|LAGO|LAGUNA|CIÉNAGA|CIENAGA)\b")
STANDING_POOL_STATION_EXCLUSIONS: frozenset[str] = frozenset(
    {
        "0017027010",  # BOWDON-EMBALSE (spillway reservoir pool)
        "0024017070",  # GACHANECA REPRESA (impoundment reservoir pool)
        "0025027310",  # REPRESA EL CALLAO (impoundment reservoir pool)
        "0026137240",  # LAGUNA DEL OTUN (high-Andean glacial lake)
        "0027017650",  # EMBALSE LA GARCIA (40-47 m municipal reservoir pool)
        "0027027240",  # EMBALSE MIRAFLORES (39-69 m hydroelectric reservoir pool)
        "0032157030",  # LAGUNA EL CEJAL (floodplain oxbow lagoon)
    }
)
HYDROMETRIC_CATEGORIES: frozenset[str] = frozenset({"Limnimétrica", "Limnigráfica"})

CATALOGO_COLUMNS: tuple[str, ...] = (
    "Codigo",
    "Nombre",
    "Descripcion",
    "Categoria",
    "Tecnologia",
    "Estado",
    "Departamento",
    "Municipio",
    "Altitud",
    "Longitud",
    "Latitud",
    "Fecha_instalacion",
    "Fecha_suspension",
    "Area_Operativa",
    "Corriente",
    "Area_Hidrografica",
    "Zona_Hidrografica",
    "Subzona_Hidrografica",
    "Entidad",
    "Subred",
    "Red",
)

STATION_SOURCE_SCHEMA = pl.Schema(dict.fromkeys(CATALOGO_COLUMNS, pl.String))
ASSOCIATION_SCHEMA = pl.Schema(dict.fromkeys(("station_id", "etiqueta", "unit"), pl.String))


def _decode_utf8_csv(raw_bytes: bytes, label: str) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise FatalContractError(f"IDEAM {label} CSV is not valid UTF-8 text") from error
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise FatalContractError(f"IDEAM {label} CSV has no header row")
    rows: list[dict[str, str]] = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise FatalContractError(f"IDEAM {label} CSV contains ragged columns")
        rows.append({key: str(value) for key, value in row.items() if key is not None})
    if not rows:
        raise FatalContractError(f"IDEAM {label} CSV contains zero rows")
    return tuple(reader.fieldnames), rows


def parse_variables_catalogue(raw_bytes: bytes) -> dict[str, tuple[str, str]]:
    """Verify IDEAM variables.csv parameters, units, periods, and statistics for all 20 series."""
    fieldnames, rows = _decode_utf8_csv(raw_bytes, "variables")
    required = {"etiqueta", "parametro", "unidad", "periodo", "descripcion", "tipo_estadistica"}
    if not required <= set(fieldnames):
        raise FatalContractError("IDEAM variables.csv is missing required schema columns")
    by_label: dict[str, dict[str, str]] = {}
    for row in rows:
        label = row["etiqueta"].strip()
        if not label:
            raise FatalContractError("IDEAM variables.csv contains a blank etiqueta")
        if label in by_label:
            raise FatalContractError(f"IDEAM variables.csv contains duplicate etiqueta {label!r}")
        by_label[label] = row

    verified: dict[str, tuple[str, str]] = {}
    for label in IN_SCOPE_HYDROLOGICAL_LABELS:
        raw_row = by_label.get(label)
        if raw_row is None:
            raise FatalContractError(f"IDEAM variables.csv is missing hydrological series {label!r}")
        spec = validate_variables_row(
            label,
            parametro=raw_row["parametro"],
            unidad=raw_row["unidad"],
            periodo=raw_row["periodo"],
            tipo_estadistica=raw_row["tipo_estadistica"],
        )
        verified[label] = (spec.expected_parametro, spec.source_unit)
    return verified


def parse_s3_prefix_listings(pages_by_label: Mapping[str, Sequence[bytes]]) -> dict[str, frozenset[str]]:
    """Verify complete paginated S3 ListObjectsV2 XML listings across all 20 hydrological prefixes."""
    if set(pages_by_label) != set(IN_SCOPE_HYDROLOGICAL_LABELS):
        raise FatalContractError("IDEAM S3 listings must cover the exact 20 in-scope hydrological prefixes")

    stations_by_label: dict[str, frozenset[str]] = {}
    for label in IN_SCOPE_HYDROLOGICAL_LABELS:
        pages = pages_by_label[label]
        if not pages:
            raise FatalContractError(f"IDEAM S3 prefix {label!r} has zero listing pages")
        expected_prefix = f"observaciones/historicos/csv/{label}/"
        seen_stations: set[str] = set()
        expected_continuation: str | None = None

        for page_index, raw_xml in enumerate(pages):
            upper_head = raw_xml[:1024].upper()
            if b"<!DOCTYPE" in upper_head or b"<!ENTITY" in upper_head:
                raise FatalContractError("IDEAM S3 XML listing contains disallowed DTD declarations")
            try:
                root = ET.fromstring(raw_xml)
            except ET.ParseError as error:
                raise FatalContractError(f"IDEAM S3 XML listing for {label!r} is malformed") from error
            if root.tag != f"{{{S3_XML_NS['s3']}}}ListBucketResult":
                raise FatalContractError(f"IDEAM S3 XML listing for {label!r} is not a ListBucketResult")
            bucket = root.findtext("s3:Name", default="", namespaces=S3_XML_NS)
            prefix = root.findtext("s3:Prefix", default="", namespaces=S3_XML_NS)
            if bucket != S3_BUCKET_NAME or prefix != expected_prefix:
                raise FatalContractError(f"IDEAM S3 XML listing for {label!r} has unexpected bucket or prefix")

            continuation = root.findtext("s3:ContinuationToken", namespaces=S3_XML_NS)
            if page_index == 0:
                if continuation is not None:
                    raise FatalContractError(f"IDEAM S3 first page for {label!r} carries an unexpected token")
            elif continuation != expected_continuation:
                raise FatalContractError(f"IDEAM S3 continuation token mismatch on {label!r} page {page_index + 1}")

            contents = root.findall("s3:Contents", S3_XML_NS)
            key_count_text = root.findtext("s3:KeyCount", default="", namespaces=S3_XML_NS)
            if not key_count_text.isdigit() or int(key_count_text) != len(contents):
                raise FatalContractError(f"IDEAM S3 KeyCount disagrees with Contents elements for {label!r}")

            suffix = f"-{label}.csv"
            for item in contents:
                key = item.findtext("s3:Key", default="", namespaces=S3_XML_NS)
                size_text = item.findtext("s3:Size", default="", namespaces=S3_XML_NS)
                if not key.startswith(expected_prefix) or not key.endswith(suffix):
                    raise FatalContractError(f"IDEAM S3 object key {key!r} does not match prefix {expected_prefix!r}")
                filename = key[len(expected_prefix) :]
                if "/" in filename:
                    raise FatalContractError(f"IDEAM S3 object key {key!r} contains unexpected nested path")
                station_id = filename[: -len(suffix)]
                if len(station_id) != 10 or not station_id.isdigit():
                    raise FatalContractError(f"IDEAM S3 object key {key!r} lacks a 10-digit station code")
                if not size_text.isdigit() or int(size_text) <= 0:
                    raise FatalContractError(f"IDEAM S3 object {key!r} has non-positive byte size {size_text!r}")
                if station_id in seen_stations:
                    raise FatalContractError(f"IDEAM S3 listing for {label!r} duplicates station {station_id!r}")
                seen_stations.add(station_id)

            is_truncated = root.findtext("s3:IsTruncated", default="", namespaces=S3_XML_NS)
            is_last_page = page_index == len(pages) - 1
            if is_last_page:
                if is_truncated != "false":
                    raise FatalContractError(f"IDEAM S3 listing for {label!r} is truncated on final page")
                expected_continuation = None
            else:
                if is_truncated != "true":
                    raise FatalContractError(f"IDEAM S3 listing for {label!r} has extra page after IsTruncated=false")
                next_token = root.findtext("s3:NextContinuationToken", default="", namespaces=S3_XML_NS)
                if not next_token:
                    raise FatalContractError(f"IDEAM S3 truncated page for {label!r} lacks NextContinuationToken")
                expected_continuation = next_token

        if not seen_stations:
            raise FatalContractError(f"IDEAM S3 prefix {label!r} contains zero station CSV objects")
        stations_by_label[label] = frozenset(seen_stations)
    return stations_by_label


def _parse_finite_float(text: str | None, *, field_name: str, station_id: str) -> float:
    if text is None:
        raise FatalContractError(f"IDEAM station {station_id!r} lacks required {field_name}")
    try:
        value = float(text)
    except ValueError as error:
        raise FatalContractError(f"IDEAM station {station_id!r} has non-numeric {field_name} {text!r}") from error
    if not math.isfinite(value):
        raise FatalContractError(f"IDEAM station {station_id!r} has non-finite {field_name} {text!r}")
    return value


def is_canonical_river_station(row: Mapping[str, str | None], *, has_discharge: bool) -> bool:
    """Apply the reviewed Option A flowing-watercourse scope rules to an S3-active station."""
    station_id = row["Codigo"]
    if station_id is None:
        raise FatalContractError("IDEAM station row lacks Codigo")
    if station_id in SYNTHETIC_STATION_EXCLUSIONS:
        return False

    categoria = (row["Categoria"] or "").strip()
    corriente_upper = (row["Corriente"] or "").strip().upper()

    if categoria == "Meteorológica Marina" or corriente_upper in MARINE_CORRIENTES:
        return False
    if corriente_upper == "POZO":
        return False
    if STANDING_CORRIENTE_PATTERN.search(corriente_upper) is not None and not has_discharge:
        return False
    if station_id in STANDING_POOL_STATION_EXCLUSIONS:
        if has_discharge:
            raise FatalContractError(
                f"Standing-pool exclusion {station_id!r} unexpectedly publishes discharge; re-audit scope"
            )
        return False
    return categoria in HYDROMETRIC_CATEGORIES or has_discharge or bool(corriente_upper)


def station_native_table(
    catalogo_csv_bytes: bytes,
    stations_by_label: Mapping[str, frozenset[str]],
    *,
    retrieved_at: RetrievedAt,
) -> NativeTable:
    """Build the lossless derived native table of 1,372 canonical IDEAM river stations."""
    fieldnames, raw_rows = _decode_utf8_csv(catalogo_csv_bytes, "catalogo")
    if fieldnames != CATALOGO_COLUMNS:
        raise FatalContractError(f"IDEAM catalogo.csv columns differ from expected schema: {fieldnames!r}")

    registry_by_code: dict[str, dict[str, str | None]] = {}
    for raw_row in raw_rows:
        code = raw_row["Codigo"].strip()
        if len(code) != 10 or not code.isdigit():
            raise FatalContractError(f"IDEAM catalogo.csv contains invalid 10-digit Codigo {code!r}")
        if code in registry_by_code:
            raise FatalContractError(f"IDEAM catalogo.csv contains duplicate Codigo {code!r}")
        normalized: dict[str, str | None] = {}
        for col in CATALOGO_COLUMNS:
            cell = raw_row[col].strip()
            normalized[col] = cell if cell else None
        normalized["Codigo"] = code
        registry_by_code[code] = normalized

    s3_active_stations = set().union(*stations_by_label.values())
    if not s3_active_stations:
        raise FatalContractError("IDEAM S3 listings yielded zero hydrological stations")
    missing_in_registry = sorted(s3_active_stations - registry_by_code.keys())
    if missing_in_registry:
        raise FatalContractError(
            f"IDEAM S3 hydrological stations absent from catalogo.csv: {missing_in_registry[:5]!r}"
        )

    selected_rows: list[dict[str, str | None]] = []
    for station_id in sorted(s3_active_stations):
        row = registry_by_code[station_id]
        has_discharge = any(station_id in stations_by_label[label] for label in DISCHARGE_LABELS)
        if not is_canonical_river_station(row, has_discharge=has_discharge):
            continue
        if row["Nombre"] is None:
            raise FatalContractError(f"Canonical IDEAM station {station_id!r} lacks Nombre")
        lat = _parse_finite_float(row["Latitud"], field_name="Latitud", station_id=station_id)
        lon = _parse_finite_float(row["Longitud"], field_name="Longitud", station_id=station_id)
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise FatalContractError(f"Canonical IDEAM station {station_id!r} coordinates out of geographic bounds")
        if row["Altitud"] is not None:
            _parse_finite_float(row["Altitud"], field_name="Altitud", station_id=station_id)
        selected_rows.append(row)

    if not selected_rows:
        raise FatalContractError("IDEAM canonical river selection produced zero stations")
    frame = pl.DataFrame(selected_rows, schema=STATION_SOURCE_SCHEMA).sort("Codigo")
    return stamp_native_table(frame, retrieved_at)


def s3_list_associations(
    native: NativeTable,
    stations_by_label: Mapping[str, frozenset[str]],
    variables: Mapping[str, tuple[str, str]],
) -> pl.DataFrame:
    """Build canonical station-series associations from verified S3 prefix listings and variables.csv."""
    canonical_ids = set(native.data["Codigo"])
    rows: list[tuple[str, str, str]] = []
    for label in IN_SCOPE_HYDROLOGICAL_LABELS:
        if label not in variables:
            raise FatalContractError(f"Missing verified variable metadata for {label!r}")
        _, unit = variables[label]
        for station_id in sorted(stations_by_label[label] & canonical_ids):
            rows.append((station_id, label, unit))
    if not rows:
        raise FatalContractError("IDEAM S3 listings produced zero canonical station associations")
    return pl.DataFrame(rows, schema=ASSOCIATION_SCHEMA, orient="row").sort(ASSOCIATION_SCHEMA.names())


def catalogue_tables(
    native: NativeTable,
    associations: pl.DataFrame,
    *,
    checked_on: date,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Build canonical IDEAM station, product, and exhaustive S3 prefix availability tables."""
    from rivretrieve._internal.catalogues.schemas import (
        PRODUCT_CATALOG_SCHEMA,
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
        AvailabilityDtype,
        validate_catalogue,
    )

    stations = native.data.select(
        pl.lit("co_ideam").alias("provider_id"),
        pl.col("Codigo").alias("station_id"),
        pl.col("Latitud").cast(pl.Float64).alias("latitude"),
        pl.col("Longitud").cast(pl.Float64).alias("longitude"),
        pl.lit("unknown").alias("crs"),
    ).sort("station_id")

    if not set(associations["station_id"]) <= set(stations["station_id"]):
        raise FatalContractError("IDEAM association references a station absent from canonical river scope")

    product_rows = [
        product_row(
            "co_ideam",
            association_product(etiqueta),
            etiqueta,
            route_product_facts(etiqueta, source_unit=unit),
        )
        for etiqueta, unit in associations.select("etiqueta", "unit").unique().sort("etiqueta", "unit").iter_rows()
    ]
    products = pl.DataFrame(product_rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")

    observed = {(station, association_product(etiqueta)) for station, etiqueta, _ in associations.iter_rows()}
    pairs = (
        pl.DataFrame(
            [
                {
                    "provider_id": "co_ideam",
                    "station_id": station,
                    "product_id": product,
                    "availability": "available" if (station, product) in observed else "unavailable",
                    "availability_reason": (
                        "Non-empty CSV object present in complete IDEAM S3 prefix listing; temporal coverage bounds remain unestablished"
                        if (station, product) in observed
                        else "No CSV object for station in complete IDEAM S3 prefix listing snapshot"
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
        .with_columns(pl.col("availability").cast(AvailabilityDtype))
        .sort("station_id", "product_id")
    )

    for frame, schema in (
        (products, PRODUCT_CATALOG_SCHEMA),
        (stations, STATION_CATALOG_SCHEMA),
        (pairs, STATION_PRODUCT_CATALOG_SCHEMA),
    ):
        validate_catalogue(frame, schema, on_issue="raise")
    return products, stations, pairs


def describe_associations(associations: pl.DataFrame) -> SourceDescriptions:
    """Describe witnessed IDEAM S3 source series with established physical and temporal facts."""
    from rivretrieve._internal.catalogues.source_series import SourceDescriptions

    grouped: dict[tuple[str, str], list[str]] = {}
    for station, etiqueta, unit in associations.unique().sort(ASSOCIATION_SCHEMA.names()).iter_rows():
        grouped.setdefault((etiqueta, unit), []).append(station)

    ordered = [(etiqueta, unit, station_list) for (etiqueta, unit), station_list in sorted(grouped.items())]
    return SourceDescriptions(provider_id="co_ideam", descriptions=build_source_descriptions(ordered))


def read_original(evidence_root: Path, reference: RecordingReference, *, input_receipt: RetainedInputReceipt) -> bytes:
    """Verify one explicitly selected publisher body before parsing it."""
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    selected = {item.consumer_path: item for item in input_receipt.inputs}
    member = selected.get(reference.repository_path)
    if member is None:
        raise FatalContractError("IDEAM original is absent from selected retained inputs")
    if member.sha256 != reference.sha256:
        raise FatalContractError("IDEAM original differs from its selected recording identity")
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    return (evidence_root / reference.repository_path).read_bytes()


def _read_selection(evidence_root: Path, selection_path: str, input_receipt: RetainedInputReceipt) -> dict:
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("IDEAM selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt, evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    if not isinstance(selection, dict) or not isinstance(selection.get("captures"), list):
        raise FatalContractError("IDEAM selection requires explicit captures")
    return selection


def _extract_selected_inventories(
    evidence_root: Path, selection: dict, input_receipt: RetainedInputReceipt
) -> tuple[bytes, dict[str, tuple[str, str]], dict[str, frozenset[str]], list[RecordingReference], RetrievedAt]:
    catalogo_bytes: bytes | None = None
    variables_bytes: bytes | None = None
    pages_by_label: dict[str, list[tuple[int, bytes]]] = {}
    recordings: list[RecordingReference] = []
    inventory_times = []

    for capture in selection["captures"]:
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError("IDEAM selected body disagrees with recording identity")
        raw_bytes = read_original(evidence_root, reference, input_receipt=input_receipt)
        recordings.append(reference)
        kind = capture["kind"]
        if kind == "s3_catalogo_estaciones":
            if catalogo_bytes is not None:
                raise FatalContractError("IDEAM selection requires exactly one s3_catalogo_estaciones snapshot")
            catalogo_bytes = raw_bytes
            inventory_times.append(reference.retrieved_at)
        elif kind == "s3_catalogo_variables":
            if variables_bytes is not None:
                raise FatalContractError("IDEAM selection requires exactly one s3_catalogo_variables snapshot")
            variables_bytes = raw_bytes
            inventory_times.append(reference.retrieved_at)
        elif kind == "s3_prefix_listing":
            label = capture.get("etiqueta")
            page = capture.get("page")
            if not isinstance(label, str) or type(page) is not int or page < 1:
                raise FatalContractError("IDEAM s3_prefix_listing capture requires string etiqueta and positive page")
            pages_by_label.setdefault(label, []).append((page, raw_bytes))
            inventory_times.append(reference.retrieved_at)
        elif kind == "datosgov_metadata_view":
            doc = json.loads(raw_bytes.decode("utf-8"))
            if not isinstance(doc, dict) or doc.get("licenseId") != "CC_40_BY_SA":
                raise FatalContractError("IDEAM Datos Abiertos metadata view must declare CC_40_BY_SA")
        elif kind == "datosgov_series_view":
            view_id = capture.get("view_id")
            etiqueta = capture.get("etiqueta")
            if not isinstance(view_id, str) or not isinstance(etiqueta, str):
                raise FatalContractError("IDEAM datosgov_series_view capture requires string view_id and etiqueta")
            spec = validate_socrata_series_view(raw_bytes, expected_view_id=view_id)
            if spec.etiqueta != etiqueta:
                raise FatalContractError(
                    f"IDEAM datosgov_series_view {view_id!r} etiqueta {spec.etiqueta!r} disagrees with {etiqueta!r}"
                )
        elif kind == "ideam_hydrological_manual":
            if not raw_bytes.startswith(b"%PDF-"):
                raise FatalContractError("IDEAM hydrological manual capture is not a valid PDF document")
        elif kind == "s3_observation_sample":
            etiqueta = capture.get("etiqueta")
            station_id = capture.get("station_id")
            if not isinstance(etiqueta, str) or not isinstance(station_id, str):
                raise FatalContractError("IDEAM s3_observation_sample capture requires string etiqueta and station_id")
            validate_s3_observation_csv_bytes(raw_bytes, etiqueta=etiqueta)
        else:
            raise FatalContractError(f"Unsupported IDEAM capture kind: {kind!r}")

    if catalogo_bytes is None or variables_bytes is None:
        raise FatalContractError("IDEAM selection lacks required catalogo.csv or variables.csv snapshot")

    ordered_pages: dict[str, Sequence[bytes]] = {}
    for label, numbered in pages_by_label.items():
        ordered = sorted(numbered, key=lambda item: item[0])
        if [item[0] for item in ordered] != list(range(1, len(ordered) + 1)):
            raise FatalContractError(f"IDEAM S3 listing pages for {label!r} are non-contiguous")
        ordered_pages[label] = tuple(item[1] for item in ordered)

    variables = parse_variables_catalogue(variables_bytes)
    stations_by_label = parse_s3_prefix_listings(ordered_pages)
    return catalogo_bytes, variables, stations_by_label, recordings, RetrievedAt(max(inventory_times))


def read_native_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> NativeTable:
    """Derive canonical IDEAM river station rows from verified selected originals."""
    selection = _read_selection(evidence_root, selection_path, input_receipt)
    catalogo_bytes, _, stations_by_label, _, retrieved_at = _extract_selected_inventories(
        evidence_root, selection, input_receipt
    )
    return station_native_table(catalogo_bytes, stations_by_label, retrieved_at=retrieved_at)


@dataclass(frozen=True)
class GeneratedIdeamCatalogue:
    provider_info: dict[str, object]
    products: pl.DataFrame
    stations: pl.DataFrame
    station_products: pl.DataFrame
    acquisition_provenance: AcquisitionProvenance
    source_descriptions: SourceDescriptions
    station_metadata: pl.DataFrame | None = None


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
    *,
    associations: pl.DataFrame,
    checked_on: date,
    provenance: AcquisitionProvenance,
    station_metadata: pl.DataFrame | None = None,
) -> GeneratedIdeamCatalogue:
    """Assemble the official Colombia IDEAM offline station and product catalogue."""
    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId

    products, stations, pairs = catalogue_tables(native_table, associations, checked_on=checked_on)
    enforce_catalogue_origins(ProviderId("co_ideam"), origins, native_table, stations)
    if provenance is None or provenance.provider_id != "co_ideam":
        raise FatalContractError("Official IDEAM catalogue requires its selected acquisition provenance")
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info: dict[str, object] = {
        "provider_id": "co_ideam",
        "name": "Instituto de Hidrología, Meteorología y Estudios Ambientales (IDEAM, Colombia)",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": statements.get("license"),
        "citation": statements.get("citation"),
    }
    return GeneratedIdeamCatalogue(
        provider_info,
        products,
        stations,
        pairs,
        provenance,
        describe_associations(associations),
        station_metadata,
    )


def write_catalogue(
    catalogue: GeneratedIdeamCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
    metadata_fields: tuple[MetadataField, ...] = (),
) -> None:
    """Publish candidate runtime tables through the shared evidence-aware publication path."""
    from io import BytesIO

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.co_ideam.origins import (
        STATION_CATALOGUE_ORIGINS,
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
        metadata_fields=metadata_fields,
        station_metadata=catalogue.station_metadata,
        metadata_implementation=(
            "src/rivretrieve/_internal/providers/co_ideam/station_metadata.py",
            "project_station_metadata",
        )
        if catalogue.station_metadata is not None
        else None,
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
    station_metadata: pl.DataFrame
    checked_on: date


def read_catalogue_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> CatalogueSources:
    """Recompute native rows and S3 prefix associations from verified selected originals."""
    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.co_ideam.origins import build_acquisition_provenance
    from rivretrieve._internal.providers.co_ideam.station_metadata import project_station_metadata

    selection = _read_selection(evidence_root, selection_path, input_receipt)
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    native_path = selection["native_table"]
    if not isinstance(native_path, str) or native_path not in selected:
        raise FatalContractError("IDEAM native table is absent from selected inputs")
    member = selected[native_path]
    native = read_native_table(
        evidence_root / native_path, expected_sha256=member.sha256, expected_byte_size=member.byte_size
    )
    catalogo_bytes, variables, stations_by_label, recordings, retrieved_at = _extract_selected_inventories(
        evidence_root, selection, input_receipt
    )
    reconstructed = station_native_table(catalogo_bytes, stations_by_label, retrieved_at=retrieved_at)
    if not native.data.equals(reconstructed.data):
        raise FatalContractError("IDEAM retained native differs from selected original reconstruction")

    observed = s3_list_associations(native, stations_by_label, variables)
    provenance = build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path=native_path,
            revision=selection["native_revision"],
            sha256=member.sha256,
            byte_size=member.byte_size,
        ),
        tuple(recordings),
        acquisitions=tuple(AcquisitionRecord.model_validate(item) for item in selection["publication_acquisitions"]),
        source_bindings=tuple(FactBinding.model_validate(item) for item in selection["source_bindings"]),
        statements=tuple(SourceStatement.model_validate(item) for item in selection["statements"]),
    )
    checked_on = date.fromisoformat(selection["checked_on"])
    _, stations, _ = catalogue_tables(native, observed, checked_on=checked_on)
    return CatalogueSources(native, observed, provenance, project_station_metadata(native, stations), checked_on)


def selected_supporting_inputs(provenance: AcquisitionProvenance, selection: dict) -> dict[str, tuple[str, ...]]:
    """Associate selected acquisition receipts with the facts of their original bodies."""
    captures = selection["captures"]
    receipt_by_body = {capture["body"]: capture["receipt"] for capture in captures}
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
    """Compose a derived native candidate or runtime catalogue outside source checkouts."""
    import argparse

    from rivretrieve._internal.catalogues.native import write_native_table

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--input-receipt", type=Path, required=True)
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--build-inputs", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.out.resolve()
    evidence_root = args.evidence_root.resolve(strict=True)
    if output.exists() or output.is_relative_to(evidence_root) or evidence_root.is_relative_to(output):
        raise FatalContractError("IDEAM output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("IDEAM output must stay outside source checkouts")
    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
    if args.native_only:
        native = read_native_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        write_native_table(native, output / "native.parquet")
    else:
        if args.build_inputs is None:
            raise FatalContractError("Catalogue publication requires explicit build inputs")
        from rivretrieve._internal.providers.co_ideam.origins import (
            STATION_CATALOGUE_ORIGINS,
            STATION_METADATA_FIELDS,
        )

        sources = read_catalogue_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        catalogue = build_catalogue(
            sources.native_table,
            STATION_CATALOGUE_ORIGINS,
            associations=sources.associations,
            checked_on=sources.checked_on,
            provenance=sources.provenance,
            station_metadata=sources.station_metadata,
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

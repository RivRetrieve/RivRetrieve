"""Offline catalogue transformations for Chile DGA historical discharge archives."""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import openpyxl
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
from rivretrieve._internal.providers.cl_dga.origins import DGA_CITATION, unsigned_dms_coordinate
from rivretrieve._internal.providers.cl_dga.series import SERIES_MAPPINGS

_STATION_CODE_RE = re.compile(r"^\d{8}$")
_STATION_CODE_CHECKDIGIT_RE = re.compile(r"^(\d{8})(?:-([0-9Kk]))?$")
_HIDROLINEA_CHECKDIGIT_RE = re.compile(r"\b\d{8}-[0-9Kk]\b")
_INFORME_DMS_RE = re.compile(r"^(\d{1,3})°(\d{2})'(\d{2})''$")
_MAPAS2_JSON_RE = re.compile(r"var\s+json\s*=\s*JSON\.parse\((\".*\")\)\s*;")

_STATION_METADATA_COLUMNS: tuple[str, ...] = (
    "NOMBRE ESTACION",
    "COD_REGION",
    "REGION",
    "COMUNA",
    "LAT",
    "LONG",
    "UTM_ESTE",
    "UTM_NORTE",
    "ALTITUD",
)

DAILY_HEADER: tuple[str, ...] = (
    "CODIGO ESTACION",
    "NOMBRE ESTACION",
    "COD_REGION",
    "REGION",
    "COMUNA",
    "LAT",
    "LONG",
    "UTM_ESTE",
    "UTM_NORTE",
    "ALTITUD",
    "FECHA",
    "Caudal_diario",
    "Unidad",
)

MONTHLY_HEADER: tuple[str, ...] = (
    "CODIGO ESTACION",
    "NOMBRE ESTACION",
    "COD_REGION",
    "REGION",
    "COMUNA",
    "LAT",
    "LONG",
    "UTM_ESTE",
    "UTM_NORTE",
    "ALTITUD",
    "Año",
    "Mes",
    "Caudal_Medio_mensual",
    "Unidad",
)

INFORME_NACIONAL_HEADERS: tuple[str, ...] = (
    "Código",
    "Estación",
    "Fecha Instalación",
    "Región",
    "Provincia",
    "Comuna",
    "Cuenca",
    "SubCuenca",
    "SubSubCuenca",
    "UTM WGS84 Norte(m)",
    "UTM WGS84 Este(m)",
    "Datum",
    "Latitud",
    "Longitud",
    "Altitud m.s.n.m",
    "Tipo de Estación",
)

STATION_SOURCE_SCHEMA = pl.Schema(
    {
        "CODIGO ESTACION": pl.String,
        "NOMBRE ESTACION": pl.String,
        "COD_REGION": pl.String,
        "REGION": pl.String,
        "COMUNA": pl.String,
        "LAT": pl.String,
        "LONG": pl.String,
        "UTM_ESTE": pl.String,
        "UTM_NORTE": pl.String,
        "ALTITUD_RAW": pl.String,
        "ALTITUD": pl.Int64,
        "in_daily_zip": pl.Boolean,
        "in_monthly_zip": pl.Boolean,
        "in_mapas2_json": pl.Boolean,
        "in_mapas2_fluviometric": pl.Boolean,
        "in_informe_nacional": pl.Boolean,
        "in_informe_nacional_fluviometric": pl.Boolean,
    }
)


def reconcile_station_code(raw_code: str) -> str:
    """Normalize an 8-digit DGA code (optionally suffixed with ``-DV``) while keeping leading zeros."""
    if not isinstance(raw_code, str):
        raise FatalContractError("DGA station code must be a string")
    match = _STATION_CODE_CHECKDIGIT_RE.fullmatch(raw_code.strip())
    if match is None:
        raise FatalContractError(f"Invalid DGA station code format: {raw_code!r}")
    return match.group(1)


def reconcile_check_digit_inventory(codes: Iterable[str]) -> dict[str, str]:
    """Verify check-digit station codes map 1-to-1 to 8-digit base codes without collisions."""
    mapping: dict[str, str] = {}
    for raw in codes:
        cleaned = raw.strip()
        base = reconcile_station_code(cleaned)
        previous = mapping.get(base)
        if previous is not None and previous != cleaned:
            raise FatalContractError(f"DGA check-digit inventory has duplicate base code {base!r}")
        mapping[base] = cleaned
    return mapping


def _parse_altitud_raw(raw_alt: str, station_code: str) -> int:
    if not raw_alt.isdigit():
        raise FatalContractError(f"DGA station {station_code!r} has non-integer ALTITUD: {raw_alt!r}")
    return int(raw_alt)


def parse_historical_zip_metadata(
    source: Path | bytes,
    *,
    kind: Literal["daily", "monthly"],
) -> dict[str, dict[str, str]]:
    """Stream station metadata from a national DGA historical discharge ZIP archive."""
    expected_header = DAILY_HEADER if kind == "daily" else MONTHLY_HEADER
    expected_inner = "caudal_diario_historico.txt" if kind == "daily" else "caudal_medio_mensual_historico.txt"
    zip_arg: Path | io.BytesIO = source if isinstance(source, Path) else io.BytesIO(source)
    stations: dict[str, dict[str, str]] = {}
    with zipfile.ZipFile(zip_arg) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        if members != [expected_inner]:
            raise FatalContractError(f"DGA {kind} ZIP must contain {expected_inner!r}, found {members!r}")
        with archive.open(expected_inner) as raw_stream:
            text_stream = io.TextIOWrapper(raw_stream, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text_stream)
            if reader.fieldnames is None or tuple(reader.fieldnames) != expected_header:
                raise FatalContractError(f"DGA {kind} CSV header mismatch: {reader.fieldnames!r}")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise FatalContractError(f"DGA {kind} CSV row has malformed column count")
                unit = row["Unidad"].strip()
                if unit != "m3/s":
                    raise FatalContractError(f"DGA {kind} CSV has unexpected Unidad {unit!r}")
                code = row["CODIGO ESTACION"].strip()
                if _STATION_CODE_RE.fullmatch(code) is None:
                    raise FatalContractError(f"DGA {kind} CSV has invalid 8-digit station code {code!r}")
                meta = {col: row[col].strip() for col in _STATION_METADATA_COLUMNS}
                existing = stations.get(code)
                if existing is None:
                    unsigned_dms_coordinate(meta["LAT"], "latitude")
                    unsigned_dms_coordinate(meta["LONG"], "longitude")
                    _parse_altitud_raw(meta["ALTITUD"], code)
                    stations[code] = meta
                elif existing != meta:
                    raise FatalContractError(f"DGA {kind} CSV has conflicting metadata rows for station {code!r}")
    if not stations:
        raise FatalContractError(f"DGA {kind} CSV contains zero stations")
    return stations


def parse_mapas2_html_stations(raw_bytes: bytes) -> dict[str, dict[str, object]]:
    """Extract embedded station inventory JSON from ``mapas2.mop.gob.cl`` HTML."""
    html = raw_bytes.decode("utf-8")
    match = _MAPAS2_JSON_RE.search(html)
    if match is None:
        raise FatalContractError("mapas2 HTML lacks embedded station JSON array")
    entries = json.loads(json.loads(match.group(1)))
    if not isinstance(entries, list) or not entries:
        raise FatalContractError("mapas2 embedded station JSON must be a non-empty list")
    by_code: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise FatalContractError("mapas2 station JSON entry must be an object")
        code = str(entry.get("cod_estacion", "")).strip()
        if _STATION_CODE_RE.fullmatch(code) is None:
            raise FatalContractError(f"mapas2 JSON has invalid station code {code!r}")
        if code in by_code:
            raise FatalContractError(f"mapas2 JSON contains duplicate station code {code!r}")
        by_code[code] = entry
    return by_code


def _informe_dms_to_7digit(value: object) -> str:
    if not isinstance(value, str):
        raise FatalContractError(f"Informe Nacional coordinate must be a DMS string, got {value!r}")
    match = _INFORME_DMS_RE.fullmatch(value.strip())
    if match is None:
        raise FatalContractError(f"Informe Nacional coordinate lacks DD°MM'SS'' format: {value!r}")
    return f"{int(match.group(1)):03d}{match.group(2)}{match.group(3)}"


def parse_informe_nacional_xlsx(source: Path | bytes) -> dict[str, list[dict[str, object]]]:
    """Read DGA ``Informe Nacional`` active-station rows from Excel row 17 onward."""
    xlsx_arg: Path | io.BytesIO = source if isinstance(source, Path) else io.BytesIO(source)
    wb = openpyxl.load_workbook(xlsx_arg, read_only=True, data_only=True)
    try:
        if "Nacional" not in wb.sheetnames:
            raise FatalContractError("Informe Nacional workbook lacks 'Nacional' sheet")
        ws = wb["Nacional"]
        iterator = ws.iter_rows(values_only=True)
        header_row = None
        for idx, row in enumerate(iterator):
            if idx == 16:
                header_row = tuple(row[1 : 1 + len(INFORME_NACIONAL_HEADERS)])
                break
        if header_row != INFORME_NACIONAL_HEADERS:
            raise FatalContractError(f"Informe Nacional row-17 headers mismatch: {header_row!r}")
        by_code: dict[str, list[dict[str, object]]] = {}
        for row in iterator:
            values = row[1 : 1 + len(INFORME_NACIONAL_HEADERS)]
            if not values or values[0] is None:
                continue
            record = dict(zip(INFORME_NACIONAL_HEADERS, values, strict=True))
            code = str(record["Código"]).strip()
            if _STATION_CODE_RE.fullmatch(code) is None:
                raise FatalContractError(f"Informe Nacional has invalid station code {code!r}")
            datum = record["Datum"]
            if type(datum) is not int or datum not in (18, 19):
                raise FatalContractError(f"Informe Nacional station {code!r} has unexpected Datum {datum!r}")
            by_code.setdefault(code, []).append(record)
    finally:
        wb.close()
    if not by_code:
        raise FatalContractError("Informe Nacional workbook contains zero station rows")
    return by_code


def parse_hidrolinea_check_digit_codes(raw_bytes: bytes) -> dict[str, str]:
    """Extract and reconcile 8-digit+check-digit station codes from Hidrolínea HTML."""
    text = raw_bytes.decode("utf-8", errors="replace")
    codes = sorted(set(_HIDROLINEA_CHECKDIGIT_RE.findall(text)))
    if not codes:
        raise FatalContractError("Hidrolínea HTML contains zero check-digit station codes")
    return reconcile_check_digit_inventory(codes)


def station_native_table(
    daily_stations: Mapping[str, Mapping[str, str]],
    monthly_stations: Mapping[str, Mapping[str, str]],
    mapas2_stations: Mapping[str, Mapping[str, object]],
    informe_rows: Mapping[str, list[dict[str, object]]],
    *,
    retrieved_at: RetrievedAt,
) -> NativeTable:
    """Build native station rows exclusively from historical ZIP-backed stations.

    Supporting ``mapas2`` JSON and ``Informe Nacional`` listings corroborate
    attributes and record source coverage flags without adding stations that
    lack historical ZIP observations. ``ALTITUD=0`` is preserved verbatim in
    ``ALTITUD_RAW`` and withheld as ``None`` in nullable ``ALTITUD``.
    """
    codes = sorted(set(daily_stations) | set(monthly_stations))
    if not codes:
        raise FatalContractError("DGA native table requires at least one ZIP-backed station")
    rows: list[dict[str, object]] = []
    for code in codes:
        daily_meta = daily_stations.get(code)
        monthly_meta = monthly_stations.get(code)
        if daily_meta is not None and monthly_meta is not None and dict(daily_meta) != dict(monthly_meta):
            raise FatalContractError(f"Daily and monthly historical ZIPs disagree for station {code!r}")
        meta = daily_meta if daily_meta is not None else monthly_meta
        assert meta is not None
        alt_int = _parse_altitud_raw(meta["ALTITUD"], code)
        mp = mapas2_stations.get(code)
        if mp is not None:
            mp_alt = mp.get("val_altitud")
            if type(mp_alt) is not int or mp_alt != alt_int:
                raise FatalContractError(f"mapas2 JSON ALTITUD disagrees with ZIP for station {code!r}")
        xr_list = informe_rows.get(code, [])
        for xr in xr_list:
            if (
                _informe_dms_to_7digit(xr["Latitud"]) != meta["LAT"]
                or _informe_dms_to_7digit(xr["Longitud"]) != meta["LONG"]
            ):
                raise FatalContractError(f"Informe Nacional DMS coordinates disagree with ZIP for station {code!r}")
            xr_alt = xr["Altitud m.s.n.m"]
            if type(xr_alt) is not int or xr_alt != alt_int:
                raise FatalContractError(f"Informe Nacional ALTITUD disagrees with ZIP for station {code!r}")
        rows.append(
            {
                "CODIGO ESTACION": code,
                "NOMBRE ESTACION": meta["NOMBRE ESTACION"],
                "COD_REGION": meta["COD_REGION"],
                "REGION": meta["REGION"],
                "COMUNA": meta["COMUNA"],
                "LAT": meta["LAT"],
                "LONG": meta["LONG"],
                "UTM_ESTE": meta["UTM_ESTE"],
                "UTM_NORTE": meta["UTM_NORTE"],
                "ALTITUD_RAW": meta["ALTITUD"],
                "ALTITUD": None if alt_int == 0 else alt_int,
                "in_daily_zip": daily_meta is not None,
                "in_monthly_zip": monthly_meta is not None,
                "in_mapas2_json": mp is not None,
                "in_mapas2_fluviometric": (mp is not None and "Fluviometricas" in str(mp.get("glosa_tipo") or "")),
                "in_informe_nacional": bool(xr_list),
                "in_informe_nacional_fluviometric": any(
                    "FLUVIOMETRICA" in str(xr.get("Tipo de Estación") or "") for xr in xr_list
                ),
            }
        )
    frame = pl.DataFrame(rows, schema=STATION_SOURCE_SCHEMA).sort("CODIGO ESTACION")
    return stamp_native_table(frame, retrieved_at)


def catalogue_tables(
    native: NativeTable,
    *,
    checked_on: date,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Project verified DGA native rows to canonical product, station, and station-product tables."""
    from rivretrieve._internal.catalogues.schemas import (
        PRODUCT_CATALOG_SCHEMA,
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
        validate_catalogue,
    )

    stations_rows = [
        {
            "provider_id": "cl_dga",
            "station_id": row["CODIGO ESTACION"],
            "latitude": unsigned_dms_coordinate(row["LAT"], "latitude"),
            "longitude": unsigned_dms_coordinate(row["LONG"], "longitude"),
            "crs": "unknown",
        }
        for row in native.data.sort("CODIGO ESTACION").iter_rows(named=True)
    ]
    stations = pl.DataFrame(stations_rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")

    products = pl.DataFrame(
        [
            {
                "provider_id": "cl_dga",
                "product_id": "discharge_daily",
                "observed_property": "discharge",
                "frequency": "daily",
                "statistic": "unknown",
                "period_type": "unknown",
                "period_anchor": "unknown",
                "unit": "m3/s",
                "native_id": "Caudal_diario",
            },
            {
                "provider_id": "cl_dga",
                "product_id": "discharge_monthly_mean",
                "observed_property": "discharge",
                "frequency": "monthly",
                "statistic": "mean",
                "period_type": "unknown",
                "period_anchor": "unknown",
                "unit": "m3/s",
                "native_id": "Caudal_Medio_mensual",
            },
        ],
        schema=PRODUCT_CATALOG_SCHEMA.polars_schema,
    ).sort("product_id")

    flag_by_product = {"discharge_daily": "in_daily_zip", "discharge_monthly_mean": "in_monthly_zip"}
    pair_rows: list[dict[str, object]] = []
    for row in native.data.sort("CODIGO ESTACION").iter_rows(named=True):
        station_id = row["CODIGO ESTACION"]
        for product_id in ("discharge_daily", "discharge_monthly_mean"):
            available = bool(row[flag_by_product[product_id]])
            pair_rows.append(
                {
                    "provider_id": "cl_dga",
                    "station_id": station_id,
                    "product_id": product_id,
                    "availability": "available" if available else "unavailable",
                    "availability_reason": (
                        "Station has observations in the retained DGA historical ZIP snapshot; "
                        "continuous coverage across requested periods is not implied"
                        if available
                        else "Station is absent from this retained DGA historical ZIP snapshot"
                    ),
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": checked_on,
                }
            )
    pairs = pl.DataFrame(pair_rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).sort(
        "station_id", "product_id"
    )
    for frame, schema in (
        (products, PRODUCT_CATALOG_SCHEMA),
        (stations, STATION_CATALOG_SCHEMA),
        (pairs, STATION_PRODUCT_CATALOG_SCHEMA),
    ):
        validate_catalogue(frame, schema, on_issue="raise")
    return products, stations, pairs


def describe_products(products: pl.DataFrame) -> SourceDescriptions:
    """Build explicit source-series descriptions from shared mappings."""
    from rivretrieve._internal.catalogues.source_descriptions import content_identified_descriptions
    from rivretrieve._internal.catalogues.source_series import SourceDescription

    descriptions = []
    for row in products.sort("product_id").iter_rows(named=True):
        product_id = row["product_id"]
        mapping = SERIES_MAPPINGS[product_id]
        descriptions.append(
            SourceDescription(
                product_id=product_id,
                native_coordinate=row["native_id"],
                identity=mapping.identity(),
                facts=(mapping.physical_facts(),),
            )
        )
    return content_identified_descriptions(SourceDescriptions(provider_id="cl_dga", descriptions=tuple(descriptions)))


@dataclass(frozen=True)
class GeneratedClDgaCatalogue:
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
    checked_on: date,
    provenance: AcquisitionProvenance,
    station_metadata: pl.DataFrame | None = None,
) -> GeneratedClDgaCatalogue:
    """Assemble the offline DGA station catalogue from verified ZIP-backed native rows."""
    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId

    products, stations, pairs = catalogue_tables(native_table, checked_on=checked_on)
    enforce_catalogue_origins(ProviderId("cl_dga"), origins, native_table, stations)
    if provenance is None or provenance.provider_id != "cl_dga":
        raise FatalContractError("Official DGA catalogue requires its selected acquisition provenance")
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info: dict[str, object] = {
        "provider_id": "cl_dga",
        "name": "Dirección General de Aguas (DGA), Ministerio de Obras Públicas (MOP)",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": statements.get("license"),
        "citation": DGA_CITATION,
    }
    return GeneratedClDgaCatalogue(
        provider_info,
        products,
        stations,
        pairs,
        provenance,
        describe_products(products),
        station_metadata,
    )


def write_catalogue(
    catalogue: GeneratedClDgaCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
    metadata_fields: tuple[MetadataField, ...] = (),
) -> None:
    """Publish candidate tables through the shared evidence-aware publication path."""
    from io import BytesIO

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.cl_dga.origins import (
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
            "src/rivretrieve/_internal/providers/cl_dga/station_metadata.py",
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
    provenance: AcquisitionProvenance
    station_metadata: pl.DataFrame
    checked_on: date


def _verify_selected_member(
    evidence_root: Path, reference: RecordingReference, *, input_receipt: RetainedInputReceipt
) -> Path:
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    selected = {item.consumer_path: item for item in input_receipt.inputs}
    member = selected.get(reference.repository_path)
    if member is None:
        raise FatalContractError("DGA original is absent from selected retained inputs")
    if member.sha256 != reference.sha256:
        raise FatalContractError("DGA original differs from its selected recording identity")
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    return evidence_root / reference.repository_path


def _read_selection(evidence_root: Path, selection_path: str, input_receipt: RetainedInputReceipt) -> dict:
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("DGA selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt, evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    if not isinstance(selection, dict) or not isinstance(selection.get("captures"), list):
        raise FatalContractError("DGA selection requires explicit captures")
    return selection


def _selected_native(
    evidence_root: Path, selection: dict, input_receipt: RetainedInputReceipt
) -> tuple[NativeTable, tuple[RecordingReference, ...]]:
    captures_by_kind: dict[str, dict] = {}
    recordings: list[RecordingReference] = []
    for capture in selection["captures"]:
        kind = capture["kind"]
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError("DGA selected body disagrees with recording identity")
        recordings.append(reference)
        if kind in captures_by_kind:
            raise FatalContractError(f"DGA selection requires one snapshot for {kind!r}")
        captures_by_kind[kind] = capture
    required_kinds = {"daily_zip", "monthly_zip", "mapas2_home", "informe_nacional", "hidrolinea_home"}
    if missing := required_kinds - set(captures_by_kind):
        raise FatalContractError(f"DGA selection lacks required captures: {sorted(missing)!r}")

    station_times = []
    paths: dict[str, Path] = {}
    for kind in ("daily_zip", "monthly_zip", "mapas2_home", "informe_nacional", "hidrolinea_home"):
        reference = RecordingReference.model_validate(captures_by_kind[kind]["recording"])
        paths[kind] = _verify_selected_member(evidence_root, reference, input_receipt=input_receipt)
        if kind != "hidrolinea_home":
            station_times.append(reference.retrieved_at)

    # Verify check-digit codes reconcile cleanly without base-code collisions.
    parse_hidrolinea_check_digit_codes(paths["hidrolinea_home"].read_bytes())
    daily = parse_historical_zip_metadata(paths["daily_zip"], kind="daily")
    monthly = parse_historical_zip_metadata(paths["monthly_zip"], kind="monthly")
    mapas2 = parse_mapas2_html_stations(paths["mapas2_home"].read_bytes())
    informe = parse_informe_nacional_xlsx(paths["informe_nacional"])
    native = station_native_table(
        daily,
        monthly,
        mapas2,
        informe,
        retrieved_at=RetrievedAt(max(station_times)),
    )
    return native, tuple(recordings)


def read_native_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> NativeTable:
    """Derive the verified native station table from selected retained originals."""
    selection = _read_selection(evidence_root, selection_path, input_receipt)
    native, _ = _selected_native(evidence_root, selection, input_receipt)
    return native


def read_catalogue_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> CatalogueSources:
    """Recompute native rows and build validated catalogue inputs from retained originals."""
    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.cl_dga.origins import build_acquisition_provenance
    from rivretrieve._internal.providers.cl_dga.station_metadata import project_station_metadata

    selection = _read_selection(evidence_root, selection_path, input_receipt)
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    native_path = selection["native_table"]
    if native_path not in selected:
        raise FatalContractError("DGA native table is absent from selected inputs")
    member = selected[native_path]
    native = read_native_table(
        evidence_root / native_path, expected_sha256=member.sha256, expected_byte_size=member.byte_size
    )
    reconstructed, recordings = _selected_native(evidence_root, selection, input_receipt)
    if not native.data.equals(reconstructed.data):
        raise FatalContractError("DGA retained native differs from selected original reconstruction")
    for capture in selection["captures"]:
        reference = RecordingReference.model_validate(capture["recording"])
        _verify_selected_member(evidence_root, reference, input_receipt=input_receipt)
    provenance = build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path=native_path,
            revision=selection["native_revision"],
            sha256=member.sha256,
            byte_size=member.byte_size,
        ),
        recordings,
        acquisitions=tuple(AcquisitionRecord.model_validate(item) for item in selection["publication_acquisitions"]),
        source_bindings=tuple(FactBinding.model_validate(item) for item in selection["source_bindings"]),
        statements=tuple(SourceStatement.model_validate(item) for item in selection["statements"]),
    )
    checked_on = date.fromisoformat(selection["checked_on"])
    _, stations, _ = catalogue_tables(native, checked_on=checked_on)
    return CatalogueSources(native, provenance, project_station_metadata(native, stations), checked_on)


def selected_supporting_inputs(provenance: AcquisitionProvenance, selection: dict) -> dict[str, tuple[str, ...]]:
    """Associate selected acquisition receipts with the facts of their original bodies."""
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
    """Compose a derived native candidate or full offline catalogue outside source checkouts."""
    import argparse

    from rivretrieve._internal.catalogues.native import write_native_table
    from rivretrieve._internal.providers.cl_dga.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--selection", default="maintenance/catalogue/cl_dga/official/selection.json")
    parser.add_argument("--input-receipt", type=Path, required=True)
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--build-inputs", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.out.resolve()
    evidence_root = args.evidence_root.resolve(strict=True)
    if output.exists() or output.is_relative_to(evidence_root) or evidence_root.is_relative_to(output):
        raise FatalContractError("DGA output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("DGA output must stay outside source checkouts")
    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
    if args.native_only:
        native = read_native_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        write_native_table(native, output / "native.parquet")
    else:
        if args.build_inputs is None:
            raise FatalContractError("Catalogue publication requires explicit build inputs")
        sources = read_catalogue_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        catalogue = build_catalogue(
            sources.native_table,
            STATION_CATALOGUE_ORIGINS,
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

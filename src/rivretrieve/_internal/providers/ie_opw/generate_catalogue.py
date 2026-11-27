"""Generate and certify the Ireland OPW (`ie_opw`) offline station catalogue."""

from __future__ import annotations

import io
import json
import math
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
    RecordingReference,
    RetainedInputReceipt,
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    validate_catalogue,
)
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.catalogues.station_metadata import MetadataField
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ie_opw.series import (
    COMPLETE_ZIP_BY_PARAM,
    PRODUCT_SPECS,
    YEAR_JSON_BY_PARAM_SHORTNAME,
    catalogue_product_rows,
    describe_associations,
)

MAX_REPUBLICATION_STATION_NO = 41000

EXCLUDED_COASTAL_TIDAL_STATIONS: frozenset[str] = frozenset(
    {
        "06062",  # Giles Quay (Inactive, SEA)
        "07062",  # Mornington (Boyne estuary tidal)
        "10042",  # Arklow Town Br (AVOCA, empirical tidal)
        "10062",  # Ravenswell Road (Dargle, empirical tidal)
        "12002",  # Enniscorthy (Level & Flow with Q=0 and semidiurnal tide)
        "12007",  # St. John's tidal
        "12008",  # Clonjordan tidal
        "12009",  # Blackwater Bridge tidal
        "12061",  # Wexford Harbour / Ferrycarrig tidal
        "12064",  # Ferrycarrig tidal
        "13005",  # New Ross / Barrow tidal
        "19162",  # Cork Harbour / Blackrock tidal
        "20020",  # Bandon Estuary tidal
        "23030",  # Tralee / Blennerville coastal polder tidal
        "23039",  # Coastal tidal / polder pump below OD
        "23040",  # Coastal tidal / polder
        "23041",  # Coastal tidal / polder below OD
        "23042",  # Coastal tidal / polder
        "24009",  # Shannon Estuary / Askeaton tidal
        "24053",  # Blackabbey (Level & Flow with Q=0 and semidiurnal tide)
        "24067",  # Tarbert / Shannon Estuary tidal
        "27025",  # Fergus / Clarecastle tidal
        "27026",  # Shannon Airport / Bunratty tidal
        "27060",  # Limerick Dock tidal
        "27068",  # Shannon Estuary tidal
    }
)

EXCLUDED_LAKE_STATIONS: frozenset[str] = frozenset(
    {
        "07081",
        "13070",
        "13072",
        "13081",
        "22071",
        "22082",
        "25085",
        "26074",
        "26079",
        "26082",
        "26083",
        "26086",
        "26087",
        "26088",
        "26093",
        "26305",
        "30081",
        "30082",
        "30083",
        "30084",
        "30089",  # Angligham (L     CORRIB standing-lake level gauge)
        "34081",
        "34082",
        "34083",
        "35078",
        "35087",
        "36073",
        "36083",
        "36084",
        "36091",
        "36171",
    }
)

EXCLUDED_RESERVOIR_TURLOUGH_STATIONS: frozenset[str] = frozenset(
    {
        "16073",  # Marlfield Reservoir
        "19094",  # Inniscarra Headrace
        "19095",  # Carrigadrohid Headrace
        "29002",  # Rahasane Turlough
    }
)

EXCLUDED_CANAL_BOG_LANDFILL_STATIONS: frozenset[str] = frozenset(
    {
        "09110",  # Bluebell
        "14056",  # Milford Lock
        "25058",  # Victoria Lock
        "26374",  # Scragh Bog
        "27092",  # Gaurus Landfill
        "30034",  # Cregaree
    }
)

EXCLUDED_STATION_NUMBERS: frozenset[str] = (
    EXCLUDED_COASTAL_TIDAL_STATIONS
    | EXCLUDED_LAKE_STATIONS
    | EXCLUDED_RESERVOIR_TURLOUGH_STATIONS
    | EXCLUDED_CANAL_BOG_LANDFILL_STATIONS
)

NATIVE_SCHEMA = pl.Schema(
    {
        "station_no": pl.String,
        "station_id": pl.String,
        "site_no": pl.String,
        "station_name": pl.String,
        "station_latitude": pl.String,
        "station_longitude": pl.String,
        "WTO_OBJECT": pl.String,
        "CATCHMENT_SIZE": pl.String,
        "Stn_Class": pl.String,
        "station_status": pl.String,
        "station_gauge_datum_unit": pl.String,
        "GAUGE_DATUM": pl.String,
    }
)

ASSOCIATION_SCHEMA = pl.Schema(
    {
        "station_id": pl.String,
        "product_id": pl.String,
        "availability": pl.String,
        "availability_reason": pl.String,
    }
)

_UNPROBED_REASON = (
    "Unprobed static Hydro-Data station file; per-station archives are not bulk-enumerated to respect OPW rate limits"
)

_LAYER_SPECS: dict[str, tuple[str, set[str], str]] = {
    "layer_10": ("stage_instantaneous", {"WEB.Cmd.P-Continuous.Absolute"}, "m"),
    "layer_20": ("water_temperature_instantaneous", {"WEB.Cmd.P-Water-Temp", "Cmd.P-Water-Temp"}, "°C"),
    "layer_30": ("discharge_instantaneous", {"WEB.Cmd.Runoff"}, "cumec"),
}


def _blank_to_none(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FatalContractError(f"Expected string or null metadata value, got {type(value).__name__}")
    stripped = value.strip()
    return stripped if stripped else None


_LAKE_WTO_RE = re.compile(r"(?:^|\s)L\.?\s+\S")
_KEPT_LAKE_OUTLET_STATIONS: frozenset[str] = frozenset({"26075", "35071"})


def is_excluded_station(row: Mapping[str, Any]) -> bool:
    """Return True when an OPW station is barred (>41000) or outside flowing watercourses."""
    sno = row.get("station_no")
    if not isinstance(sno, str) or len(sno) != 5 or not sno.isdigit():
        raise FatalContractError(f"OPW station_no must be a 5-digit numeric string, got {sno!r}")
    if int(sno) > MAX_REPUBLICATION_STATION_NO:
        return True
    if row.get("Stn_Class") == "Tidal":
        return True
    if sno in EXCLUDED_STATION_NUMBERS:
        return True
    wto = row.get("WTO_OBJECT") or ""
    if not isinstance(wto, str):
        raise FatalContractError(f"OPW WTO_OBJECT on {sno} must be a string")
    wto_upper = wto.upper()
    if sno not in _KEPT_LAKE_OUTLET_STATIONS and _LAKE_WTO_RE.search(wto_upper):
        return True
    return sno != "30061" and ("ESTY" in wto_upper or "ESTUARY" in wto_upper)


def _validate_geojson_overlap(kept_rows: list[dict[str, object]], geojson_payload: object) -> None:
    if not isinstance(geojson_payload, dict):
        raise FatalContractError("OPW /geojson/ payload must be a JSON object")
    geojson_dict = cast("dict[str, Any]", geojson_payload)
    crs_obj = geojson_dict.get("crs")
    crs_name = (
        crs_obj.get("properties", {}).get("name")
        if isinstance(crs_obj, dict) and isinstance(crs_obj.get("properties"), dict)
        else None
    )
    if crs_name != "EPSG:4326":
        raise FatalContractError(f"OPW /geojson/ CRS must be EPSG:4326, got {crs_name!r}")
    features = geojson_dict.get("features")
    if not isinstance(features, list):
        raise FatalContractError("OPW /geojson/ lacks features list")
    coords_by_ref: dict[str, tuple[float, float]] = {}
    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties")
        geom = feat.get("geometry")
        if not isinstance(props, dict) or not isinstance(geom, dict):
            continue
        ref = props.get("ref")
        coords = geom.get("coordinates")
        if isinstance(ref, str) and isinstance(coords, list) and len(coords) >= 2:
            coords_by_ref[ref] = (float(coords[1]), float(coords[0]))
    if not coords_by_ref:
        raise FatalContractError("OPW /geojson/ contains zero indexed stations")
    for row in kept_rows:
        sno = str(row["station_no"])
        if sno in coords_by_ref:
            glat, glon = coords_by_ref[sno]
            lat = float(str(row["station_latitude"]))
            lon = float(str(row["station_longitude"]))
            if abs(glat - lat) > 1e-4 or abs(glon - lon) > 1e-4:
                raise FatalContractError(
                    f"OPW GeoJSON coordinate mismatch on {sno}: stations=({lat}, {lon}), geojson=({glat}, {glon})"
                )


def station_native_table(
    stations_payload: object,
    geojson_payload: object,
    *,
    retrieved_at: RetrievedAt,
) -> NativeTable:
    """Build the verified flowing-watercourse OPW native table from retained registries."""
    if not isinstance(stations_payload, list):
        raise FatalContractError("OPW stations.json must decode as a JSON list")

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_item in stations_payload:
        if not isinstance(raw_item, dict):
            raise FatalContractError("OPW stations.json entry must be an object")
        item = cast("dict[str, Any]", raw_item)
        sno = item.get("station_no")
        if not isinstance(sno, str) or len(sno) != 5 or not sno.isdigit():
            raise FatalContractError(f"OPW station_no must be 5 digits, got {sno!r}")
        if sno in seen:
            raise FatalContractError(f"Duplicate OPW station_no {sno!r}")
        seen.add(sno)
        if is_excluded_station(item):
            continue

        lat_str = item.get("station_latitude")
        lon_str = item.get("station_longitude")
        if not isinstance(lat_str, str) or not isinstance(lon_str, str):
            raise FatalContractError(f"OPW coordinates on {sno} must be verbatim source strings")
        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError as error:
            raise FatalContractError(f"Invalid OPW coordinate on {sno}: ({lat_str!r}, {lon_str!r})") from error
        if not (math.isfinite(lat) and math.isfinite(lon) and 51.3 <= lat <= 55.5 and -10.7 <= lon <= -5.4):
            raise FatalContractError(f"OPW coordinate on {sno} falls outside Ireland bounds: ({lat}, {lon})")

        name = item.get("station_name")
        if not isinstance(name, str) or not name.strip():
            raise FatalContractError(f"OPW station {sno} lacks nonblank station_name")

        catchment = _blank_to_none(item.get("CATCHMENT_SIZE"))
        if catchment is not None and not catchment.endswith(" km²"):
            raise FatalContractError(f"Unexpected OPW CATCHMENT_SIZE unit suffix on {sno}: {catchment!r}")

        rows.append(
            {
                "station_no": sno,
                "station_id": str(item.get("station_id") or ""),
                "site_no": str(item.get("site_no") or ""),
                "station_name": name,
                "station_latitude": lat_str,
                "station_longitude": lon_str,
                "WTO_OBJECT": _blank_to_none(item.get("WTO_OBJECT")),
                "CATCHMENT_SIZE": catchment,
                "Stn_Class": str(item.get("Stn_Class") or ""),
                "station_status": _blank_to_none(item.get("station_status")),
                "station_gauge_datum_unit": _blank_to_none(item.get("station_gauge_datum_unit")),
                "GAUGE_DATUM": _blank_to_none(item.get("GAUGE_DATUM")),
            }
        )

    _validate_geojson_overlap(rows, geojson_payload)
    frame = pl.DataFrame(rows, schema=NATIVE_SCHEMA, strict=True).sort("station_no")
    return stamp_native_table(frame, retrieved_at)


def _check_complete_zip_bytes(
    raw_bytes: bytes,
    *,
    station_no: str,
    parameter: str,
) -> tuple[str, str]:
    spec = COMPLETE_ZIP_BY_PARAM[parameter]
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as archive:
        names = archive.namelist()
        if names != ["tsvalues.csv"]:
            raise FatalContractError(f"Unexpected OPW complete.zip members on {station_no}/{parameter}: {names!r}")
        text = archive.read("tsvalues.csv").decode("utf-8-sig")

    headers: dict[str, str] = {}
    has_columns_header = False
    non_null = 0
    for line in io.StringIO(text):
        stripped = line.rstrip("\r\n")
        if not stripped:
            continue
        if stripped.startswith("#"):
            if stripped == "#Timestamp;Value;Quality Code":
                has_columns_header = True
                continue
            key, sep, val = stripped[1:].partition(";")
            if sep:
                headers[key] = val
            continue
        parts = stripped.split(";")
        if len(parts) < 2:
            raise FatalContractError(f"Malformed OPW CSV data line on {station_no}/{parameter}: {stripped!r}")
        if not parts[0].endswith("Z"):
            raise FatalContractError(f"Expected UTC 'Z' timestamp in OPW ZIP on {station_no}/{parameter}: {parts[0]!r}")
        if parts[1].strip():
            non_null += 1

    if not has_columns_header:
        raise FatalContractError(f"OPW ZIP missing '#Timestamp;Value;Quality Code' header on {station_no}/{parameter}")
    if headers.get("station_no") != station_no:
        raise FatalContractError(f"OPW ZIP station_no {headers.get('station_no')!r} disagrees with {station_no!r}")
    if headers.get("stationparameter_name") != parameter:
        raise FatalContractError(f"OPW ZIP parameter {headers.get('stationparameter_name')!r} != {parameter!r}")
    if headers.get("ts_shortname") != spec.ts_shortname:
        raise FatalContractError(f"OPW ZIP ts_shortname {headers.get('ts_shortname')!r} != {spec.ts_shortname!r}")
    if headers.get("ts_unitsymbol") != spec.source_unit:
        raise FatalContractError(f"OPW ZIP unit {headers.get('ts_unitsymbol')!r} != {spec.source_unit!r}")
    if headers.get("tz", "UTC0") != "UTC0":
        raise FatalContractError(f"OPW ZIP tz {headers.get('tz')!r} != 'UTC0'")

    if non_null > 0:
        return ("available", f"{non_null} non-null instantaneous rows witnessed in OPW {spec.route}")
    return ("unavailable", f"0 non-null instantaneous rows in OPW {spec.route} (#rows;{headers.get('rows', '0')})")


def _set_witness(
    state: dict[tuple[str, str], tuple[str, str]],
    key: tuple[str, str],
    availability: str,
    reason: str,
) -> None:
    prev = state.get(key)
    if prev is not None and prev[0] != "unknown" and prev[0] != availability:
        raise FatalContractError(f"Conflicting OPW availability witnesses for {key}: {prev!r} vs {availability!r}")
    state[key] = (availability, reason)


def station_product_associations(
    native: NativeTable,
    *,
    layer_witnesses: dict[str, dict[str, str]],
    station_witnesses: dict[tuple[str, str], tuple[str, str]],
) -> pl.DataFrame:
    """Assemble 385 x 12 station-product availability from witnessed sources."""
    kept_ids = set(native.data["station_no"].to_list())
    state: dict[tuple[str, str], tuple[str, str]] = {
        (sid, spec.product_id): ("unknown", _UNPROBED_REASON) for sid in kept_ids for spec in PRODUCT_SPECS
    }
    for product_id, by_station in layer_witnesses.items():
        for sid, reason in by_station.items():
            if sid in kept_ids:
                _set_witness(state, (sid, product_id), "available", reason)
    for (sid, product_id), (availability, reason) in station_witnesses.items():
        if sid in kept_ids:
            _set_witness(state, (sid, product_id), availability, reason)

    rows = [
        {
            "station_id": sid,
            "product_id": product_id,
            "availability": availability,
            "availability_reason": reason,
        }
        for (sid, product_id), (availability, reason) in state.items()
    ]
    return pl.DataFrame(rows, schema=ASSOCIATION_SCHEMA).sort("station_id", "product_id")


def catalogue_tables(
    native: NativeTable,
    associations: pl.DataFrame,
    *,
    checked_on: date,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Derive canonical `products`, `stations`, and `station_products` tables."""
    station_rows = [
        {
            "provider_id": "ie_opw",
            "station_id": row["station_no"],
            "latitude": float(row["station_latitude"]),
            "longitude": float(row["station_longitude"]),
            "crs": "EPSG:4326",
        }
        for row in native.data.sort("station_no").to_dicts()
    ]
    stations = pl.DataFrame(station_rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")
    products = pl.DataFrame(catalogue_product_rows(), schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")

    pair_rows = [
        {
            "provider_id": "ie_opw",
            "station_id": sid,
            "product_id": pid,
            "availability": availability,
            "availability_reason": reason,
            "published_record_start_date": None,
            "published_record_end_date": None,
            "last_catalogue_check": checked_on,
        }
        for sid, pid, availability, reason in associations.select(
            "station_id", "product_id", "availability", "availability_reason"
        ).iter_rows()
    ]
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


def read_original(evidence_root: Path, reference: RecordingReference, *, input_receipt: RetainedInputReceipt) -> bytes:
    """Verify one selected publisher body against the retained input receipt before reading it."""
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    selected = {item.consumer_path: item for item in input_receipt.inputs}
    member = selected.get(reference.repository_path)
    if member is None:
        raise FatalContractError(f"OPW original {reference.repository_path!r} absent from selected inputs")
    if member.sha256 != reference.sha256:
        raise FatalContractError(f"OPW original {reference.repository_path!r} SHA-256 differs from selection")
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    return (evidence_root / reference.repository_path).read_bytes()


def _read_selection(evidence_root: Path, selection_path: str, input_receipt: RetainedInputReceipt) -> dict[str, Any]:
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("OPW selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt, evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    if not isinstance(selection, dict) or not isinstance(selection.get("captures"), list):
        raise FatalContractError("OPW selection requires explicit captures")
    return selection


def _extract_registry_payloads(
    evidence_root: Path, captures: list[dict[str, Any]], *, input_receipt: RetainedInputReceipt
) -> tuple[object, object, RetrievedAt, list[RecordingReference]]:
    stations_payload: object | None = None
    geojson_payload: object | None = None
    retrieved_at: RetrievedAt | None = None
    recordings: list[RecordingReference] = []
    for cap in captures:
        if cap["kind"] not in {"stations_json", "geojson_crs"}:
            continue
        reference = RecordingReference.model_validate(cap["recording"])
        if reference.repository_path != cap["body"]:
            raise FatalContractError(f"OPW selected body disagrees with recording identity for {cap['kind']!r}")
        raw = read_original(evidence_root, reference, input_receipt=input_receipt)
        recordings.append(reference)
        if cap["kind"] == "stations_json":
            if stations_payload is not None:
                raise FatalContractError("OPW selection requires exactly one stations_json capture")
            stations_payload = json.loads(raw)
            retrieved_at = RetrievedAt(reference.retrieved_at)
        else:
            if geojson_payload is not None:
                raise FatalContractError("OPW selection requires exactly one geojson_crs capture")
            geojson_payload = json.loads(raw)
    if stations_payload is None or geojson_payload is None or retrieved_at is None:
        raise FatalContractError("OPW selection lacks required stations_json or geojson_crs capture")
    return stations_payload, geojson_payload, retrieved_at, recordings


def read_native_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> NativeTable:
    """Derive canonical Ireland OPW native rows purely from verified selected originals."""
    selection = _read_selection(evidence_root, selection_path, input_receipt)
    stations_payload, geojson_payload, retrieved_at, _ = _extract_registry_payloads(
        evidence_root, selection["captures"], input_receipt=input_receipt
    )
    return station_native_table(stations_payload, geojson_payload, retrieved_at=retrieved_at)


@dataclass(frozen=True)
class GeneratedIeOpwCatalogue:
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
) -> GeneratedIeOpwCatalogue:
    """Assemble the official Ireland OPW catalogue from verified captures and origins."""
    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId

    products, stations, pairs = catalogue_tables(native_table, associations, checked_on=checked_on)
    enforce_catalogue_origins(ProviderId("ie_opw"), origins, native_table, stations)
    if provenance is None or provenance.provider_id != "ie_opw":
        raise FatalContractError("Official OPW catalogue requires selected acquisition provenance")
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info: dict[str, object] = {
        "provider_id": "ie_opw",
        "name": "Office of Public Works (OPW)",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": statements.get("license"),
        "citation": statements.get("citation"),
    }
    return GeneratedIeOpwCatalogue(
        provider_info,
        products,
        stations,
        pairs,
        provenance,
        describe_associations(),
        station_metadata,
    )


def write_catalogue(
    catalogue: GeneratedIeOpwCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
    metadata_fields: tuple[MetadataField, ...] = (),
) -> None:
    """Publish deterministic candidate tables through shared publication metadata builder."""
    from io import BytesIO

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.ie_opw.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_NOTICE

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
            "src/rivretrieve/_internal/providers/ie_opw/station_metadata.py",
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


def _verified_capture_http_status(
    evidence_root: Path,
    capture: dict[str, object],
    reference: RecordingReference,
    *,
    input_receipt: RetainedInputReceipt,
    raw_body: bytes,
) -> int:
    """Verify capture HTTP receipt against retained inputs when present or required (HTTP 404)."""
    receipt_path = capture.get("receipt")
    declared_status = capture.get("http_status")
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    if not isinstance(receipt_path, str):
        if declared_status == 404:
            raise FatalContractError("OPW HTTP 404 capture requires a retained receipt path")
        return 200
    if receipt_path not in selected:
        if declared_status == 404:
            raise FatalContractError("OPW HTTP 404 receipt is absent from selected retained inputs")
        return 200
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    member = selected[receipt_path]
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    receipt_doc = json.loads((evidence_root / receipt_path).read_bytes())
    if not isinstance(receipt_doc, dict):
        raise FatalContractError(f"OPW receipt {receipt_path} must decode as JSON object")
    status = receipt_doc.get("http_status")
    if isinstance(status, bool) or not isinstance(status, int) or status not in (200, 404):
        raise FatalContractError(f"OPW receipt {receipt_path} has unsupported http_status {status!r}")
    if declared_status is not None and status != declared_status:
        raise FatalContractError(f"OPW receipt {receipt_path} http_status disagrees with capture declaration")
    if (
        receipt_doc.get("sha256") != reference.sha256
        or receipt_doc.get("byte_size") != len(raw_body)
        or receipt_doc.get("url") != reference.source_url
    ):
        raise FatalContractError(f"OPW receipt {receipt_path} disagrees with body identity or source URL")
    return status


def read_catalogue_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> CatalogueSources:
    """Recompute native rows and all witnessed availability pairs from selected originals."""
    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.ie_opw.origins import build_acquisition_provenance
    from rivretrieve._internal.providers.ie_opw.station_metadata import project_station_metadata

    selection = _read_selection(evidence_root, selection_path, input_receipt)
    captures = selection["captures"]
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    native_path = selection["native_table"]
    if native_path not in selected:
        raise FatalContractError("OPW native table is absent from selected inputs")
    member = selected[native_path]
    native = read_native_table(
        evidence_root / native_path, expected_sha256=member.sha256, expected_byte_size=member.byte_size
    )

    stations_payload, geojson_payload, retrieved_at, reg_recordings = _extract_registry_payloads(
        evidence_root, captures, input_receipt=input_receipt
    )
    reconstructed = station_native_table(stations_payload, geojson_payload, retrieved_at=retrieved_at)
    if not native.data.equals(reconstructed.data):
        raise FatalContractError("OPW retained native differs from selected original reconstruction")

    recordings: list[RecordingReference] = [*reg_recordings]
    layer_witnesses: dict[str, dict[str, str]] = {}
    station_witnesses: dict[tuple[str, str], tuple[str, str]] = {}

    for capture in captures:
        kind = capture["kind"]
        if kind in {"stations_json", "geojson_crs"}:
            continue
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError(f"OPW selected body disagrees with recording identity for {kind!r}")
        raw = read_original(evidence_root, reference, input_receipt=input_receipt)
        recordings.append(reference)
        if kind in {"terms", "layers_index", "layer_rainfall", "excluded_witness", "month_json", "series_meaning"}:
            continue
        if kind in _LAYER_SPECS:
            product_id, valid_shortnames, expected_unit = _LAYER_SPECS[kind]
            payload = json.loads(raw)
            if not isinstance(payload, list):
                raise FatalContractError(f"OPW {kind} payload must decode as JSON list")
            by_station: dict[str, str] = {}
            for row in payload:
                if not isinstance(row, dict):
                    continue
                if row.get("ts_shortname") not in valid_shortnames or row.get("ts_unitsymbol") != expected_unit:
                    raise FatalContractError(
                        f"Unexpected OPW {kind} entry on {row.get('station_no')}: {row.get('ts_shortname')!r} ({row.get('ts_unitsymbol')!r})"
                    )
                if row.get("ts_value") is not None:
                    by_station[str(row["station_no"])] = (
                        f"Non-null live reading witnessed in OPW Hydro-Data {kind} index"
                    )
            layer_witnesses[product_id] = by_station
        elif kind == "year_json":
            station_no = capture["station_id"]
            parameter = capture["parameter"]
            status = _verified_capture_http_status(
                evidence_root, capture, reference, input_receipt=input_receipt, raw_body=raw
            )
            expected_shortnames = {s for (p, s) in YEAR_JSON_BY_PARAM_SHORTNAME if p == parameter}
            if status == 404:
                for shortname in sorted(expected_shortnames):
                    spec = YEAR_JSON_BY_PARAM_SHORTNAME[(parameter, shortname)]
                    _set_witness(
                        station_witnesses,
                        (station_no, spec.product_id),
                        "unavailable",
                        f"HTTP 404 on OPW {parameter}/year.json",
                    )
                continue
            payload = json.loads(raw)
            if not isinstance(payload, list):
                raise FatalContractError(f"OPW {station_no}/{parameter}/year.json must decode as JSON list")
            seen_shortnames: set[str] = set()
            for entry in payload:
                if not isinstance(entry, dict):
                    raise FatalContractError(f"Malformed entry in {station_no}/{parameter}/year.json")
                shortname = entry.get("ts_shortname")
                spec = YEAR_JSON_BY_PARAM_SHORTNAME.get((parameter, str(shortname)))
                if spec is None:
                    raise FatalContractError(
                        f"Unexpected ts_shortname {shortname!r} in {station_no}/{parameter}/year.json"
                    )
                if entry.get("ts_unitsymbol") != spec.source_unit:
                    raise FatalContractError(
                        f"Unexpected unit {entry.get('ts_unitsymbol')!r} in {station_no}/{parameter}/year.json"
                    )
                if str(shortname) in seen_shortnames:
                    raise FatalContractError(
                        f"Duplicate ts_shortname {shortname!r} in {station_no}/{parameter}/year.json"
                    )
                seen_shortnames.add(str(shortname))
                data = entry.get("data", [])
                non_null = sum(1 for row in data if isinstance(row, list) and len(row) >= 2 and row[1] is not None)
                if non_null > 0:
                    _set_witness(
                        station_witnesses,
                        (station_no, spec.product_id),
                        "available",
                        f"{non_null} non-null daily rows witnessed in OPW {parameter}/year.json ({shortname})",
                    )
                else:
                    _set_witness(
                        station_witnesses,
                        (station_no, spec.product_id),
                        "unavailable",
                        f"0 non-null daily rows in OPW {parameter}/year.json ({shortname})",
                    )
            for shortname in sorted(expected_shortnames - seen_shortnames):
                spec = YEAR_JSON_BY_PARAM_SHORTNAME[(parameter, shortname)]
                _set_witness(
                    station_witnesses,
                    (station_no, spec.product_id),
                    "unavailable",
                    f"Series {shortname} absent in OPW {parameter}/year.json",
                )
        elif kind == "complete_zip":
            station_no = capture["station_id"]
            parameter = capture["parameter"]
            spec = COMPLETE_ZIP_BY_PARAM[parameter]
            status = _verified_capture_http_status(
                evidence_root, capture, reference, input_receipt=input_receipt, raw_body=raw
            )
            if status == 404:
                _set_witness(
                    station_witnesses,
                    (station_no, spec.product_id),
                    "unavailable",
                    f"HTTP 404 on OPW {parameter}/{spec.route}",
                )
                continue
            availability, reason = _check_complete_zip_bytes(raw, station_no=station_no, parameter=parameter)
            _set_witness(station_witnesses, (station_no, spec.product_id), availability, reason)
        else:
            raise FatalContractError(f"Unknown capture kind {kind!r} in OPW selection")

    associations = station_product_associations(
        native,
        layer_witnesses=layer_witnesses,
        station_witnesses=station_witnesses,
    )
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
    _, stations, _ = catalogue_tables(native, associations, checked_on=checked_on)
    return CatalogueSources(native, associations, provenance, project_station_metadata(native, stations), checked_on)


def main(argv: list[str] | None = None) -> int:
    """Compose a derived native table or full catalogue artifact from selected originals."""
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
        raise FatalContractError("OPW native/catalogue output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("OPW native/catalogue output must stay outside source checkouts")
    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
    if args.native_only:
        native = read_native_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        write_native_table(native, output / "native.parquet")
    else:
        if args.build_inputs is None:
            raise FatalContractError("Catalogue publication requires explicit build inputs")
        from rivretrieve._internal.providers.ie_opw.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

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

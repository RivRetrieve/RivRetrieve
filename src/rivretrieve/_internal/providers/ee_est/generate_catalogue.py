"""Generate and certify the Estonia (`ee_est`) offline station catalogue."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
    RecordingReference,
    RetainedInputReceipt,
)
from rivretrieve._internal.catalogue_origins import NativeColumn, OriginDeclarations
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
from rivretrieve._internal.providers.ee_est.origins import EstonianLest97ToWgs84Conversion
from rivretrieve._internal.providers.ee_est.series import (
    EM_KEY_TO_PRODUCT,
    FH_AEGRIDA_TO_PRODUCT,
    PRODUCT_SPECS,
    catalogue_product_rows,
    describe_associations,
    parse_jaam_kood,
)

ALLOWED_WATERBODY_TYPES: frozenset[str] = frozenset({"Jõgi", "Oja", "Peakraav"})

NATIVE_SCHEMA = pl.Schema(
    {
        "kkr_kood": pl.String,
        "kood": pl.String,
        "jaam_kood": pl.Int64,
        "nimi": pl.String,
        "veekogu_nimi": pl.String,
        "veekogu_tyyp_selg": pl.String,
        "kesk_x": pl.Float64,
        "kesk_y": pl.Float64,
        "area": pl.Float64,
    }
)

ASSOCIATION_SCHEMA = pl.Schema(
    {
        "station_id": pl.String,
        "jaam_kood": pl.Int64,
        "product_id": pl.String,
        "native_id": pl.String,
        "available": pl.Boolean,
        "availability_reason": pl.String,
    }
)

_EM_EXPECTED_UNITS = {"Q": "m³/s", "H": "m", "T": "°C"}


def station_native_table(
    estmodel_stations: Any,
    seirejaamad_rows: Any,
    active_fh_codes: set[int],
    *,
    retrieved_at: RetrievedAt,
) -> NativeTable:
    """Build the verified 60-station inland flowing-water native table from agency registries."""
    if not isinstance(estmodel_stations, list) or not isinstance(seirejaamad_rows, list):
        raise FatalContractError("Estonia station registries must decode as JSON lists")

    sj_by_kkr: dict[str, dict[str, Any]] = {}
    for item in seirejaamad_rows:
        if not isinstance(item, dict):
            raise FatalContractError("f_seirejaamad entry must be an object")
        kkr = item.get("kkr_kood")
        if not isinstance(kkr, str) or not kkr.strip():
            raise FatalContractError("f_seirejaamad entry requires nonblank kkr_kood")
        if kkr in sj_by_kkr:
            raise FatalContractError(f"Duplicate kkr_kood {kkr!r} in f_seirejaamad")
        if item.get("seiretyyp") != "HJ":
            raise FatalContractError(f"Unexpected seiretyyp {item.get('seiretyyp')!r} on {kkr}")
        sj_by_kkr[kkr] = item

    rows: list[dict[str, object]] = []
    seen_codes: set[str] = set()
    for em in estmodel_stations:
        if not isinstance(em, dict):
            raise FatalContractError("EstModel station entry must be an object")
        if em.get("type") != "HYDROLOGICAL":
            continue
        code = em.get("code")
        if not isinstance(code, str) or not code.strip():
            raise FatalContractError("EstModel HYDROLOGICAL entry requires nonblank code")
        if code in seen_codes:
            raise FatalContractError(f"Duplicate EstModel HYDROLOGICAL code {code!r}")
        seen_codes.add(code)
        sj = sj_by_kkr.get(code)
        if sj is None:
            raise FatalContractError(f"EstModel HYDROLOGICAL station {code!r} absent from f_seirejaamad HJ")
        wb_type = sj.get("veekogu_tyyp_selg")
        if not isinstance(wb_type, str):
            raise FatalContractError(f"Station {code!r} lacks string veekogu_tyyp_selg")
        if wb_type not in ALLOWED_WATERBODY_TYPES:
            continue

        nimi = sj.get("nimi")
        veekogu = sj.get("veekogu_nimi")
        if not isinstance(nimi, str) or not nimi.strip():
            raise FatalContractError(f"Station {code!r} lacks nonblank nimi")
        if not isinstance(veekogu, str) or not veekogu.strip():
            raise FatalContractError(f"Station {code!r} lacks nonblank veekogu_nimi")

        x = sj.get("kesk_x")
        y = sj.get("kesk_y")
        area = em.get("area")
        if not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x):
            raise FatalContractError(f"Station {code!r} lacks finite kesk_x")
        if not isinstance(y, (int, float)) or isinstance(y, bool) or not math.isfinite(y):
            raise FatalContractError(f"Station {code!r} lacks finite kesk_y")
        if not (300_000.0 <= float(x) <= 800_000.0 and 6_350_000.0 <= float(y) <= 6_650_000.0):
            raise FatalContractError(f"Station {code!r} coordinates ({x}, {y}) outside Estonia L-EST97 bounds")
        if (
            not isinstance(area, (int, float))
            or isinstance(area, bool)
            or not math.isfinite(area)
            or float(area) <= 0.0
        ):
            raise FatalContractError(f"Station {code!r} lacks positive drainage area")

        candidates = parse_jaam_kood(sj.get("kood"))
        active_matches = [jk for jk in candidates if jk in active_fh_codes]
        if len(active_matches) > 1:
            raise FatalContractError(f"Ambiguous active f_hydroseire jaam_kood {active_matches!r} on {code}")
        jaam_kood = active_matches[0] if active_matches else None
        raw_kood = sj.get("kood")
        rows.append(
            {
                "kkr_kood": code,
                "kood": str(raw_kood) if raw_kood is not None else None,
                "jaam_kood": jaam_kood,
                "nimi": nimi,
                "veekogu_nimi": veekogu,
                "veekogu_tyyp_selg": wb_type,
                "kesk_x": float(x),
                "kesk_y": float(y),
                "area": float(area),
            }
        )

    if not rows:
        raise FatalContractError("No inland river hydrological stations extracted")
    frame = pl.DataFrame(rows, schema=NATIVE_SCHEMA).sort("kkr_kood")
    return stamp_native_table(frame, retrieved_at)


def station_product_associations(
    native: NativeTable,
    *,
    em_available: Mapping[tuple[str, str], str],
    em_unavailable: Mapping[tuple[str, str], str],
    fh_available: Mapping[tuple[str, str], str],
    fh_unavailable: Mapping[tuple[str, str], str],
) -> pl.DataFrame:
    """Assemble exhaustive witnessed availability across all `station × product` pairs."""
    rows: list[dict[str, object]] = []
    for station_id, jaam_kood in native.data.select("kkr_kood", "jaam_kood").sort("kkr_kood").iter_rows():
        for spec in sorted(PRODUCT_SPECS, key=lambda item: item.product_id):
            key = (station_id, spec.product_id)
            if spec.source_api == "estmodel":
                if key in em_available:
                    available, reason = True, em_available[key]
                elif key in em_unavailable:
                    available, reason = False, em_unavailable[key]
                else:
                    raise FatalContractError(f"Missing EstModel witness for {key!r}")
            else:
                if key in fh_available:
                    available, reason = True, fh_available[key]
                elif key in fh_unavailable:
                    available, reason = False, fh_unavailable[key]
                else:
                    raise FatalContractError(f"Missing f_hydroseire witness for {key!r}")
            rows.append(
                {
                    "station_id": station_id,
                    "jaam_kood": jaam_kood,
                    "product_id": spec.product_id,
                    "native_id": spec.native_id,
                    "available": available,
                    "availability_reason": reason,
                }
            )
    return pl.DataFrame(rows, schema=ASSOCIATION_SCHEMA).sort("station_id", "product_id")


def catalogue_tables(
    native: NativeTable,
    associations: pl.DataFrame,
    *,
    checked_on: date,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Derive canonical `products`, `stations`, and `station_products` tables."""
    projection = EstonianLest97ToWgs84Conversion()
    station_rows: list[dict[str, object]] = []
    for row in native.data.sort("kkr_kood").to_dicts():
        lat = projection.apply("latitude", NativeColumn("kesk_y"), row)
        lon = projection.apply("longitude", NativeColumn("kesk_x"), row)
        if not isinstance(lat, float) or not isinstance(lon, float):
            raise FatalContractError(f"Failed to project L-EST97 coordinate for {row['kkr_kood']}")
        if not (57.0 <= lat <= 60.0 and 21.0 <= lon <= 29.0):
            raise FatalContractError(
                f"Projected coordinate out of Estonia bounds for {row['kkr_kood']}: ({lat}, {lon})"
            )
        station_rows.append(
            {
                "provider_id": "ee_est",
                "station_id": row["kkr_kood"],
                "latitude": lat,
                "longitude": lon,
                "crs": "EPSG:4326",
            }
        )
    stations = pl.DataFrame(station_rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")
    products = pl.DataFrame(catalogue_product_rows(), schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")

    pair_rows: list[dict[str, object]] = []
    for station_id, product_id, available, reason in associations.select(
        "station_id", "product_id", "available", "availability_reason"
    ).iter_rows():
        pair_rows.append(
            {
                "provider_id": "ee_est",
                "station_id": station_id,
                "product_id": product_id,
                "availability": "available" if available else "unavailable",
                "availability_reason": reason,
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


def read_original(evidence_root: Path, reference: RecordingReference, *, input_receipt: RetainedInputReceipt) -> bytes:
    """Verify one selected publisher body against the retained input receipt before reading it."""
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    selected = {item.consumer_path: item for item in input_receipt.inputs}
    member = selected.get(reference.repository_path)
    if member is None:
        raise FatalContractError(f"Estonia original {reference.repository_path!r} absent from selected inputs")
    if member.sha256 != reference.sha256:
        raise FatalContractError(f"Estonia original {reference.repository_path!r} SHA-256 differs from selection")
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    return (evidence_root / reference.repository_path).read_bytes()


def _read_selection(evidence_root: Path, selection_path: str, input_receipt: RetainedInputReceipt) -> dict:
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("Estonia selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt, evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    if not isinstance(selection, dict) or not isinstance(selection.get("captures"), list):
        raise FatalContractError("Estonia selection requires explicit captures")
    return selection


def _decode_fh_slices(
    evidence_root: Path, captures: list[dict], *, input_receipt: RetainedInputReceipt
) -> tuple[set[int], set[tuple[int, str]], list[RecordingReference]]:
    active_fh_codes: set[int] = set()
    seen_fh_nonnull: set[tuple[int, str]] = set()
    recordings: list[RecordingReference] = []
    for capture in captures:
        if capture["kind"] != "fh_slice":
            continue
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError("Estonia fh_slice body disagrees with recording identity")
        rows = json.loads(read_original(evidence_root, reference, input_receipt=input_receipt))
        recordings.append(reference)
        for row in rows:
            if row.get("vaartus") is not None:
                jk = int(row["jaam_kood"])
                ae = str(row["aegrida_nimi"])
                active_fh_codes.add(jk)
                seen_fh_nonnull.add((jk, ae))
    return active_fh_codes, seen_fh_nonnull, recordings


def _extract_registry_payloads(
    evidence_root: Path, captures: list[dict], *, input_receipt: RetainedInputReceipt
) -> tuple[object, object, RetrievedAt, list[RecordingReference]]:
    em_payload: object | None = None
    sj_payload: object | None = None
    em_ts: datetime | None = None
    sj_ts: datetime | None = None
    recordings: list[RecordingReference] = []
    for capture in captures:
        kind = capture["kind"]
        if kind not in {"estmodel_stations", "seirejaamad"}:
            continue
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError("Estonia registry body disagrees with recording identity")
        payload = json.loads(read_original(evidence_root, reference, input_receipt=input_receipt))
        recordings.append(reference)
        if kind == "estmodel_stations":
            if em_payload is not None:
                raise FatalContractError("Estonia selection requires exactly one estmodel_stations capture")
            em_payload = payload
            em_ts = reference.retrieved_at
        else:
            if sj_payload is not None:
                raise FatalContractError("Estonia selection requires exactly one seirejaamad capture")
            sj_payload = payload
            sj_ts = reference.retrieved_at
    if em_payload is None or sj_payload is None or em_ts is None or sj_ts is None:
        raise FatalContractError("Estonia selection requires estmodel_stations and seirejaamad captures")
    latest_ts = max(em_ts, sj_ts)
    return em_payload, sj_payload, RetrievedAt(latest_ts), recordings


def read_native_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> NativeTable:
    """Reconstruct native table offline from verified registry + slice captures."""
    selection = _read_selection(evidence_root, selection_path, input_receipt)
    captures = selection["captures"]
    em_payload, sj_payload, retrieved_at, _ = _extract_registry_payloads(
        evidence_root, captures, input_receipt=input_receipt
    )
    active_fh_codes, _, _ = _decode_fh_slices(evidence_root, captures, input_receipt=input_receipt)
    return station_native_table(em_payload, sj_payload, active_fh_codes, retrieved_at=retrieved_at)


@dataclass(frozen=True)
class GeneratedEeEstCatalogue:
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
) -> GeneratedEeEstCatalogue:
    """Assemble the official Estonia catalogue from verified captures and origins."""
    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId

    products, stations, pairs = catalogue_tables(native_table, associations, checked_on=checked_on)
    enforce_catalogue_origins(ProviderId("ee_est"), origins, native_table, stations)
    if provenance is None or provenance.provider_id != "ee_est":
        raise FatalContractError("Official Estonia catalogue requires selected acquisition provenance")
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info: dict[str, object] = {
        "provider_id": "ee_est",
        "name": "Estonian Environment Agency (Keskkonnaagentuur)",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": statements.get("license"),
        "citation": statements.get("citation"),
    }
    return GeneratedEeEstCatalogue(
        provider_info,
        products,
        stations,
        pairs,
        provenance,
        describe_associations(associations),
        station_metadata,
    )


def write_catalogue(
    catalogue: GeneratedEeEstCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
    metadata_fields: tuple[MetadataField, ...] = (),
) -> None:
    """Publish deterministic candidate tables through shared publication metadata builder."""
    from io import BytesIO

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.ee_est.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_NOTICE

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
            "src/rivretrieve/_internal/providers/ee_est/station_metadata.py",
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
    """Recompute native rows and all 60 x 18 availability witnesses from selected originals."""
    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.ee_est.origins import build_acquisition_provenance
    from rivretrieve._internal.providers.ee_est.station_metadata import project_station_metadata

    selection = _read_selection(evidence_root, selection_path, input_receipt)
    captures = selection["captures"]
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    native_path = selection["native_table"]
    if native_path not in selected:
        raise FatalContractError("Estonia native table is absent from selected inputs")
    member = selected[native_path]
    native = read_native_table(
        evidence_root / native_path, expected_sha256=member.sha256, expected_byte_size=member.byte_size
    )

    em_payload, sj_payload, retrieved_at, reg_recordings = _extract_registry_payloads(
        evidence_root, captures, input_receipt=input_receipt
    )
    active_fh_codes, seen_fh_nonnull, slice_recordings = _decode_fh_slices(
        evidence_root, captures, input_receipt=input_receipt
    )
    reconstructed = station_native_table(em_payload, sj_payload, active_fh_codes, retrieved_at=retrieved_at)
    if not native.data.equals(reconstructed.data):
        raise FatalContractError("Estonia retained native differs from selected original reconstruction")

    recordings: list[RecordingReference] = [*reg_recordings, *slice_recordings]
    em_available: dict[tuple[str, str], str] = {}
    em_unavailable: dict[tuple[str, str], str] = {}
    fh_available: dict[tuple[str, str], str] = {}
    fh_unavailable: dict[tuple[str, str], str] = {}

    # Witness f_hydroseire availability from verified slice + negative checks
    kkr_by_jk: dict[int, str] = {}
    for station_id, jaam_kood in native.data.select("kkr_kood", "jaam_kood").iter_rows():
        if jaam_kood is not None:
            kkr_by_jk[int(jaam_kood)] = station_id
    for jk, ae in seen_fh_nonnull:
        if jk in kkr_by_jk and ae in FH_AEGRIDA_TO_PRODUCT:
            spec = FH_AEGRIDA_TO_PRODUCT[ae]
            fh_available[(kkr_by_jk[jk], spec.product_id)] = (
                "Non-null hourly observation witnessed in selected Keskkonnaandmed f_hydroseire UTC slice"
            )

    station_koods = {
        row["kkr_kood"]: parse_jaam_kood(row["kood"]) for row in native.data.select("kkr_kood", "kood").to_dicts()
    }
    absent_checked_koods: set[int] = set()

    for capture in captures:
        kind = capture["kind"]
        if kind in {"estmodel_stations", "seirejaamad", "fh_slice"}:
            continue
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError(f"Estonia selected body disagrees with recording identity for {kind!r}")
        raw = read_original(evidence_root, reference, input_receipt=input_receipt)
        recordings.append(reference)
        if kind in {"terms", "series_meaning"}:
            continue
        payload = json.loads(raw)
        if kind == "fh_absent":
            if payload != []:
                raise FatalContractError(f"Expected empty f_hydroseire absent proof in {reference.recording_id}")
            absent_checked_koods.add(int(capture["jaam_kood"]))
        elif kind == "fh_check":
            if payload != []:
                raise FatalContractError(f"Expected empty f_hydroseire check in {reference.recording_id}")
            spec = FH_AEGRIDA_TO_PRODUCT[capture["aegrida_nimi"]]
            fh_unavailable[(capture["station_id"], spec.product_id)] = (
                "Keskkonnaandmed f_hydroseire query for this station and aegrida_nimi returned empty []"
            )
        elif kind == "estmodel_window":
            station_id = capture["station_id"]
            em_type = capture["em_type"]
            for row in payload:
                param = row.get("parameter")
                if param not in _EM_EXPECTED_UNITS:
                    continue
                if row.get("unit") != _EM_EXPECTED_UNITS[param]:
                    raise FatalContractError(f"Unexpected EstModel unit {row.get('unit')!r} on {station_id}/{param}")
                if row.get("value") is not None:
                    spec = EM_KEY_TO_PRODUCT[(param, em_type)]
                    em_available[(station_id, spec.product_id)] = (
                        "Non-null daily observation witnessed in EstModel 2025-2026 measurements query"
                    )
        elif kind == "estmodel_fullcheck":
            station_id = capture["station_id"]
            param = capture["em_parameter"]
            em_type = capture["em_type"]
            spec = EM_KEY_TO_PRODUCT[(param, em_type)]
            nonnull = any(r.get("value") is not None for r in payload)
            if nonnull:
                for row in payload:
                    if row.get("parameter") != param or row.get("unit") != _EM_EXPECTED_UNITS[param]:
                        raise FatalContractError(f"Unexpected EstModel row in {reference.recording_id}")
                em_available[(station_id, spec.product_id)] = (
                    "Non-null historical daily observations witnessed in EstModel full-history query"
                )
            else:
                em_unavailable[(station_id, spec.product_id)] = (
                    "EstModel unfiltered full-history measurements query returned empty list []"
                )
        else:
            raise FatalContractError(f"Unknown capture kind {kind!r} in Estonia selection")

    # Apply station-level fh_absent proofs to EstModel-only stations whose every kood returned []
    for station_id, jaam_kood in native.data.select("kkr_kood", "jaam_kood").iter_rows():
        if jaam_kood is None:
            koods = station_koods[station_id]
            if not koods or not set(koods) <= absent_checked_koods:
                raise FatalContractError(f"EstModel-only station {station_id} lacks complete fh_absent proof")
            for spec in PRODUCT_SPECS:
                if spec.source_api == "f_hydroseire":
                    fh_unavailable[(station_id, spec.product_id)] = (
                        "EstModel-only river station: f_hydroseire query for station kood returned empty []"
                    )

    associations = station_product_associations(
        native,
        em_available=em_available,
        em_unavailable=em_unavailable,
        fh_available=fh_available,
        fh_unavailable=fh_unavailable,
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
        raise FatalContractError("Estonia native/catalogue output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("Estonia native/catalogue output must stay outside source checkouts")
    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
    if args.native_only:
        native = read_native_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        write_native_table(native, output / "native.parquet")
    else:
        if args.build_inputs is None:
            raise FatalContractError("Catalogue publication requires explicit build inputs")
        from rivretrieve._internal.providers.ee_est.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

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

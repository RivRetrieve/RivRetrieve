"""Generate and certify the Ireland EPA HydroNet (`ie_epa`) offline station catalogue.

The station universe and every availability value come from retained EPA
originals: the HydroNet station register (``stations.json``) and each
candidate station's file list (``stations/{site_no}/{station_no}/index.json``).
A listed full-history file makes its station-product ``available`` whatever the
file holds at capture. A product without a listed file is ``unknown``: the file
list is silence, not an EPA statement that the series does not exist. The
register's ``DATA_AVAILABLE`` text never sets availability.
"""

from __future__ import annotations

import io
import json
import math
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
from rivretrieve._internal.providers.ie_epa.series import (
    FULL_HISTORY_FILES,
    GAUGINGS_FILE,
    PARAMETERS,
    PRODUCT_BY_FILE,
    PRODUCT_SPECS,
    PROVIDER_ID,
    ROLLING_FILES,
    catalogue_product_rows,
    describe_associations,
)

RESPONSIBLE_BODY = "Environmental Protection Agency"
OBJECT_TYPE = "General;Surface water"
LISTED_FILES: tuple[str, ...] = tuple(
    f"{parameter}/{name}.zip" for parameter in PARAMETERS for name in (*FULL_HISTORY_FILES, *ROLLING_FILES)
)
_IN_SCOPE_FILES = frozenset(LISTED_FILES)
_KNOWN_FILES = _IN_SCOPE_FILES | {GAUGINGS_FILE}


def listed_column(path: str) -> str:
    """Native boolean column recording whether a station file list names ``path``."""
    parameter, name = path.removesuffix(".zip").split("/")
    return f"listed_{parameter}_{name}"


_REGISTER_FIELDS = (
    "site_name",
    "station_name",
    "station_latitude",
    "station_longitude",
    "station_carteasting",
    "station_cartnorthing",
    "object_type",
    "station_status",
    "RESPONSIBLE_BODY",
    "STATION_OWNER",
    "TYPE_OF_GAUGING",
    "catchment_name",
    "WTO_OBJECT",
    "river_name",
    "CATCHMENT_SIZE",
    "station_gauge_datum",
    "station_gauge_datum_unit",
    "DATA_AVAILABLE",
)

NATIVE_SCHEMA = pl.Schema(
    {
        "station_no": pl.String,
        "site_no": pl.String,
        **dict.fromkeys(_REGISTER_FIELDS, pl.String),
        **{listed_column(path): pl.Boolean for path in LISTED_FILES},
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

_IRELAND_LATITUDE = (51.3, 55.5)
_IRELAND_LONGITUDE = (-10.7, -5.4)


def _available_reason(path: str) -> str:
    return (
        f"EPA HydroNet station file list lists {path}; a listed file is published by the EPA "
        "even when it holds no values at capture"
    )


def _unknown_reason(path: str) -> str:
    return (
        f"EPA HydroNet station file list omits {path}; the omission is not an EPA statement that "
        "the series is unavailable"
    )


def _text_or_none(value: object, *, station_no: str, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FatalContractError(f"EPA register field {field} on {station_no} must be a string")
    return value if value.strip() else None


def is_candidate(row: Mapping[str, Any]) -> bool:
    """Return whether a register row is an EPA-run river or stream gauge before file checks."""
    return row.get("RESPONSIBLE_BODY") == RESPONSIBLE_BODY and row.get("object_type") == OBJECT_TYPE


def listed_files(payload: object, *, site_no: str, station_no: str) -> frozenset[str]:
    """Return the station-relative ``.zip`` paths a HydroNet station file list names."""
    if not isinstance(payload, dict):
        raise FatalContractError(f"EPA file list for {site_no}/{station_no} must be a JSON object")
    document = cast("dict[str, Any]", payload)
    if document.get("site_no") != site_no or document.get("station_no") != station_no:
        raise FatalContractError(f"EPA file list identity differs from register for {site_no}/{station_no}")
    links = document.get("_links")
    if not isinstance(links, list):
        raise FatalContractError(f"EPA file list for {site_no}/{station_no} lacks _links")
    prefix = ["internet", "stations", site_no, station_no]
    paths: set[str] = set()
    for link in links:
        if not isinstance(link, dict) or link.get("type") != "resource":
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href.endswith(".zip"):
            continue
        parts = href.split("/")
        if parts[:4] != prefix or len(parts) != 6:
            raise FatalContractError(f"EPA file list for {site_no}/{station_no} names foreign file {href!r}")
        if link.get("station_parameter") != parts[4]:
            raise FatalContractError(f"EPA file list parameter disagrees with {href!r}")
        path = "/".join(parts[4:])
        if path not in _KNOWN_FILES:
            raise FatalContractError(f"Unsupported EPA HydroNet file {path!r} at {site_no}/{station_no}")
        paths.add(path)
    return frozenset(paths)


def station_native_table(
    stations_payload: object,
    file_lists: Mapping[tuple[str, str], object],
    *,
    retrieved_at: RetrievedAt,
) -> NativeTable:
    """Build the EPA river-gauge native table from the register and candidate file lists.

    Every register candidate requires exactly one file list. A candidate enters
    the table when its list names at least one ``S`` or ``Q`` file other than
    ``Q/complete_gaugings.zip``. ``station_no`` is kept exactly as published.
    """
    if not isinstance(stations_payload, list):
        raise FatalContractError("EPA stations.json must decode as a JSON list")
    seen: set[str] = set()
    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in stations_payload:
        if not isinstance(raw, dict):
            raise FatalContractError("EPA stations.json entry must be an object")
        row = cast("dict[str, Any]", raw)
        station_no = row.get("station_no")
        site_no = row.get("site_no")
        if not isinstance(station_no, str) or not station_no or station_no.strip() != station_no:
            raise FatalContractError(f"EPA station_no must be a nonblank string, got {station_no!r}")
        if not isinstance(site_no, str) or not site_no:
            raise FatalContractError(f"EPA site_no on {station_no} must be a nonblank string")
        if station_no in seen:
            raise FatalContractError(f"Duplicate EPA station_no {station_no!r}")
        seen.add(station_no)
        if is_candidate(row):
            candidates[(site_no, station_no)] = row
    if missing := sorted(set(candidates) - set(file_lists)):
        raise FatalContractError(f"EPA candidate stations lack a selected file list: {missing[:5]!r}")
    if extra := sorted(set(file_lists) - set(candidates)):
        raise FatalContractError(f"EPA file lists selected for non-candidate stations: {extra[:5]!r}")

    rows: list[dict[str, object]] = []
    for (site_no, station_no), row in candidates.items():
        listed = listed_files(file_lists[(site_no, station_no)], site_no=site_no, station_no=station_no)
        if not listed & _IN_SCOPE_FILES:
            continue
        native: dict[str, object] = {"station_no": station_no, "site_no": site_no}
        for field in _REGISTER_FIELDS:
            native[field] = _text_or_none(row.get(field), station_no=station_no, field=field)
        _check_station(native, station_no)
        native.update({listed_column(path): path in listed for path in LISTED_FILES})
        rows.append(native)
    frame = pl.DataFrame(rows, schema=NATIVE_SCHEMA, strict=True).sort("station_no")
    return stamp_native_table(frame, retrieved_at)


def _check_station(native: Mapping[str, object], station_no: str) -> None:
    latitude, longitude = native["station_latitude"], native["station_longitude"]
    if not isinstance(latitude, str) or not isinstance(longitude, str):
        raise FatalContractError(f"EPA station {station_no} lacks published coordinates")
    try:
        lat, lon = float(latitude), float(longitude)
    except ValueError as error:
        raise FatalContractError(f"Invalid EPA coordinate on {station_no}: ({latitude!r}, {longitude!r})") from error
    if not (
        math.isfinite(lat)
        and math.isfinite(lon)
        and _IRELAND_LATITUDE[0] <= lat <= _IRELAND_LATITUDE[1]
        and _IRELAND_LONGITUDE[0] <= lon <= _IRELAND_LONGITUDE[1]
    ):
        raise FatalContractError(f"EPA coordinate on {station_no} falls outside Ireland: ({lat}, {lon})")
    if native["station_name"] is None:
        raise FatalContractError(f"EPA station {station_no} lacks a station_name")
    area = native["CATCHMENT_SIZE"]
    if area is not None and not str(area).endswith(" km²"):
        raise FatalContractError(f"Unexpected EPA CATCHMENT_SIZE unit on {station_no}: {area!r}")


def station_product_associations(native: NativeTable) -> pl.DataFrame:
    """Set each station-product from its full-history file listing: available or unknown."""
    rows = []
    for row in native.data.iter_rows(named=True):
        for spec in PRODUCT_SPECS:
            path = spec.native_coordinate
            listed = row[listed_column(path)]
            rows.append(
                {
                    "station_id": row["station_no"],
                    "product_id": spec.product_id,
                    "availability": "available" if listed else "unknown",
                    "availability_reason": _available_reason(path) if listed else _unknown_reason(path),
                }
            )
    return pl.DataFrame(rows, schema=ASSOCIATION_SCHEMA).sort("station_id", "product_id")


def check_series_fields(raw: bytes, *, station_no: str, parameter: str, file: str) -> None:
    """Verify that a hosted file's headers state the product's parameter and unit."""
    spec = PRODUCT_BY_FILE.get((parameter, file))
    if spec is None:
        raise FatalContractError(f"No EPA product is declared for {parameter}/{file}")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if names != [f"{file}.csv"]:
            raise FatalContractError(f"Unexpected EPA {parameter}/{file}.zip members at {station_no}: {names!r}")
        text = archive.read(names[0]).decode("utf-8")
    headers: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        key, separator, value = line[1:].partition(";")
        if separator:
            headers[key] = value
    expected = {
        "Station Number": station_no,
        "Station Parameter Name": spec.parameter_name,
        "Unit Symbol": spec.source_unit,
    }
    for key, value in expected.items():
        if headers.get(key) != value:
            raise FatalContractError(
                f"EPA {parameter}/{file}.zip at {station_no} has {key} {headers.get(key)!r}, expected {value!r}"
            )


def catalogue_tables(
    native: NativeTable,
    associations: pl.DataFrame,
    *,
    checked_on: date,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Derive canonical ``products``, ``stations`` and ``station_products`` tables."""
    stations = pl.DataFrame(
        [
            {
                "provider_id": PROVIDER_ID,
                "station_id": row["station_no"],
                "latitude": float(row["station_latitude"]),
                "longitude": float(row["station_longitude"]),
                "crs": "unknown",
            }
            for row in native.data.iter_rows(named=True)
        ],
        schema=STATION_CATALOG_SCHEMA.polars_schema,
    ).sort("station_id")
    products = pl.DataFrame(catalogue_product_rows(), schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")
    pairs = pl.DataFrame(
        [
            {
                "provider_id": PROVIDER_ID,
                "station_id": station_id,
                "product_id": product_id,
                "availability": availability,
                "availability_reason": reason,
                "published_record_start_date": None,
                "published_record_end_date": None,
                "last_catalogue_check": checked_on,
            }
            for station_id, product_id, availability, reason in associations.select(
                "station_id", "product_id", "availability", "availability_reason"
            ).iter_rows()
        ],
        schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema,
    ).sort("station_id", "product_id")
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
        raise FatalContractError(f"EPA original {reference.repository_path!r} absent from selected inputs")
    if member.sha256 != reference.sha256:
        raise FatalContractError(f"EPA original {reference.repository_path!r} SHA-256 differs from selection")
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    return (evidence_root / reference.repository_path).read_bytes()


def _read_selection(evidence_root: Path, selection_path: str, input_receipt: RetainedInputReceipt) -> dict[str, Any]:
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("EPA selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt.model_copy(update={"inputs": ()}), evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    if not isinstance(selection, dict) or not isinstance(selection.get("captures"), list):
        raise FatalContractError("EPA selection requires explicit captures")
    return selection


@dataclass(frozen=True)
class _NativeInputs:
    stations_payload: object
    file_lists: dict[tuple[str, str], object]
    retrieved_at: RetrievedAt
    recordings: list[RecordingReference]


def _reference(capture: Mapping[str, Any]) -> RecordingReference:
    reference = RecordingReference.model_validate(capture["recording"])
    if reference.repository_path != capture["body"]:
        raise FatalContractError(f"EPA selected body disagrees with recording identity for {capture['kind']!r}")
    return reference


def _read_native_inputs(
    evidence_root: Path, captures: list[dict[str, Any]], *, input_receipt: RetainedInputReceipt
) -> _NativeInputs:
    stations_payload: object | None = None
    file_lists: dict[tuple[str, str], object] = {}
    recordings: list[RecordingReference] = []
    for capture in captures:
        kind = capture["kind"]
        if kind not in {"stations_json", "station_file_list"}:
            continue
        reference = _reference(capture)
        payload = json.loads(read_original(evidence_root, reference, input_receipt=input_receipt))
        recordings.append(reference)
        if kind == "stations_json":
            if stations_payload is not None:
                raise FatalContractError("EPA selection requires exactly one stations_json capture")
            stations_payload = payload
        else:
            key = (capture["site_no"], capture["station_no"])
            if key in file_lists:
                raise FatalContractError(f"EPA selection repeats the file list for {key!r}")
            file_lists[key] = payload
    if stations_payload is None:
        raise FatalContractError("EPA selection lacks the stations_json capture")
    retrieved_at = RetrievedAt(max(item.retrieved_at for item in recordings))
    return _NativeInputs(stations_payload, file_lists, retrieved_at, recordings)


def read_native_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> NativeTable:
    """Derive the EPA native table purely from verified selected originals."""
    selection = _read_selection(evidence_root, selection_path, input_receipt)
    inputs = _read_native_inputs(evidence_root, selection["captures"], input_receipt=input_receipt)
    return station_native_table(inputs.stations_payload, inputs.file_lists, retrieved_at=inputs.retrieved_at)


@dataclass(frozen=True)
class GeneratedIeEpaCatalogue:
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
) -> GeneratedIeEpaCatalogue:
    """Assemble the official EPA HydroNet catalogue from verified captures and origins."""
    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId

    products, stations, pairs = catalogue_tables(native_table, associations, checked_on=checked_on)
    enforce_catalogue_origins(ProviderId(PROVIDER_ID), origins, native_table, stations)
    if provenance.provider_id != PROVIDER_ID:
        raise FatalContractError("Official EPA HydroNet catalogue requires selected acquisition provenance")
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info: dict[str, object] = {
        "provider_id": PROVIDER_ID,
        "name": "Environmental Protection Agency (EPA)",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": statements.get("license"),
        "citation": statements.get("citation"),
    }
    return GeneratedIeEpaCatalogue(
        provider_info, products, stations, pairs, provenance, describe_associations(), station_metadata
    )


def write_catalogue(
    catalogue: GeneratedIeEpaCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
    metadata_fields: tuple[MetadataField, ...] = (),
) -> None:
    """Publish deterministic candidate tables through the shared publication metadata builder."""
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.ie_epa.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_NOTICE

    files = {
        "provider.json": (json.dumps(catalogue.provider_info, sort_keys=True, separators=(",", ":")) + "\n").encode()
    }
    for name, frame in (
        ("products", catalogue.products),
        ("stations", catalogue.stations),
        ("station_products", catalogue.station_products),
    ):
        buffer = io.BytesIO()
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
            "src/rivretrieve/_internal/providers/ie_epa/station_metadata.py",
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


_CONTEXT_KINDS = frozenset({"terms", "context"})


def read_catalogue_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> CatalogueSources:
    """Rebuild the native table, check it equals the retained table, and derive availability."""
    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.ie_epa.origins import build_acquisition_provenance
    from rivretrieve._internal.providers.ie_epa.station_metadata import project_station_metadata

    selection = _read_selection(evidence_root, selection_path, input_receipt)
    captures = selection["captures"]
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    native_path = selection["native_table"]
    member = selected.get(native_path)
    if member is None:
        raise FatalContractError("EPA native table is absent from selected inputs")
    native = read_native_table(
        evidence_root / native_path, expected_sha256=member.sha256, expected_byte_size=member.byte_size
    )
    inputs = _read_native_inputs(evidence_root, captures, input_receipt=input_receipt)
    reconstructed = station_native_table(inputs.stations_payload, inputs.file_lists, retrieved_at=inputs.retrieved_at)
    if not native.data.equals(reconstructed.data):
        raise FatalContractError("EPA retained native table differs from selected original reconstruction")

    recordings = list(inputs.recordings)
    witnessed: set[tuple[str, str]] = set()
    for capture in captures:
        kind = capture["kind"]
        if kind in {"stations_json", "station_file_list"}:
            continue
        reference = _reference(capture)
        raw = read_original(evidence_root, reference, input_receipt=input_receipt)
        recordings.append(reference)
        if kind in _CONTEXT_KINDS:
            continue
        if kind != "series_fields":
            raise FatalContractError(f"Unknown capture kind {kind!r} in EPA selection")
        check_series_fields(raw, station_no=capture["station_no"], parameter=capture["parameter"], file=capture["file"])
        witnessed.add((capture["parameter"], capture["file"]))
    if missing := {(spec.parameter, spec.file) for spec in PRODUCT_SPECS} - witnessed:
        raise FatalContractError(f"EPA products lack a series-field witness: {sorted(missing)!r}")

    associations = station_product_associations(native)
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
        raise FatalContractError("EPA native/catalogue output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("EPA native/catalogue output must stay outside source checkouts")
    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
    if args.native_only:
        native = read_native_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        write_native_table(native, output / "native.parquet")
    else:
        if args.build_inputs is None:
            raise FatalContractError("Catalogue publication requires explicit build inputs")
        from rivretrieve._internal.providers.ie_epa.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

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

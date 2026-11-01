"""Offline transformations of SENAMHI station registries and product witnesses."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
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
from rivretrieve._internal.providers.pe_senamhi.series import MONTHLY_LEVEL_FIELDS, series_mappings

HYDROLOGICAL_CATEGORIES = frozenset({"05", "06", "18", "22"})
STATION_SOURCE_SCHEMA = pl.Schema(
    {
        "stationId": pl.String,
        "legacyStationId": pl.String,
        "typeId": pl.String,
        "typeDescription": pl.String,
        "name": pl.String,
        "categoryId": pl.String,
        "categoryDescription": pl.String,
        "categoryAbbreviation": pl.String,
        "conditionId": pl.String,
        "subTypeId": pl.String,
        "subTypeDescription": pl.String,
        "classId": pl.String,
        "receptionTypeDescription": pl.String,
        "provinceId": pl.String,
        "departmentId": pl.String,
        "districtId": pl.String,
        "zonalDirectionId": pl.String,
        "longitude": pl.String,
        "latitude": pl.String,
        "receptionTypeId": pl.Int64,
        "longitudeDegrees": pl.Int64,
        "longitudeMinutes": pl.Int64,
        "longitudeSeconds": pl.Float64,
        "latitudeDegrees": pl.Int64,
        "latitudeMinutes": pl.Int64,
        "latitudeSeconds": pl.Float64,
        "altitude": pl.Float64,
    }
)


def _data(payload: Mapping[str, object]) -> object:
    if payload.get("status") is not True:
        raise FatalContractError("SENAMHI selected response is not successful")
    return payload.get("data")


def _rows(payload: Mapping[str, object]) -> list[dict[str, object]]:
    data = _data(payload)
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise FatalContractError("SENAMHI registry must contain source objects")
    return cast("list[dict[str, object]]", data)


def station_native_table(
    hydrological: Mapping[str, object],
    meteorological: Mapping[str, object],
    active: Mapping[str, object],
    *,
    retrieved_at: RetrievedAt,
) -> NativeTable:
    """Retain hydrological primary identities regardless of operational condition.

    Registry category codes identify hydrological exceptions under the meteorological
    type. Legacy identifiers and published relationships never merge stations.
    Optional metadata remains null; conflicting duplicate registry rows raise.
    """
    selected: dict[str, dict[str, object]] = {}
    for payload in (hydrological, meteorological, active):
        for row in _rows(payload):
            if row.get("typeId") != "H" and row.get("categoryId") not in HYDROLOGICAL_CATEGORIES:
                continue
            identity = row.get("stationId")
            if not isinstance(identity, str) or not identity.strip():
                raise FatalContractError("SENAMHI stationId must be a nonblank source string")
            values = {name: row.get(name) for name in STATION_SOURCE_SCHEMA}
            for name, dtype in STATION_SOURCE_SCHEMA.items():
                value = values[name]
                if value is not None and (
                    (dtype == pl.String and not isinstance(value, str))
                    or (dtype == pl.Int64 and type(value) is not int)
                    or (dtype == pl.Float64 and (isinstance(value, bool) or not isinstance(value, int | float)))
                ):
                    raise FatalContractError("SENAMHI registry metadata has invalid scalar types")
            if identity in selected and selected[identity] != values:
                raise FatalContractError("SENAMHI registry snapshots disagree for one primary identity")
            selected[identity] = values
    frame = pl.DataFrame(list(selected.values()), schema=STATION_SOURCE_SCHEMA).sort("stationId")
    return stamp_native_table(frame, retrieved_at)


ASSOCIATION_SCHEMA = pl.Schema(dict.fromkeys(("station_id", "subsystem", "resolution", "variable", "unit"), pl.String))


def phisis_associations(
    payload: Mapping[str, object], *, station: str, resolution: str, variable: str, station_ids: set[str]
) -> pl.DataFrame:
    """Read recognized PHISIS identities even when their bounded window is empty.

    Units come from the response, independently of station levelType. Sample
    values and dates are not copied into the catalogue.
    """
    data = _data(payload)
    if not isinstance(data, dict):
        raise FatalContractError("PHISIS association requires an identifying response envelope")
    data = cast("dict[str, object]", data)
    identity = data.get("station")
    identity = cast("dict[str, object]", identity) if isinstance(identity, dict) else None
    if (
        station not in station_ids
        or not isinstance(identity, dict)
        or identity.get("code") != station
        or resolution not in {"DAILY", "HOURLY"}
        or data.get("type") != resolution
        or variable not in {"FLOW", "LEVEL"}
        or data.get("variable") != variable
    ):
        raise FatalContractError("PHISIS response differs from its selected station-variable request")
    unit = data.get("unit")
    if unit not in ({"m3/s"} if variable == "FLOW" else {"m", "m.s.n.m"}):
        raise FatalContractError("PHISIS association has an unsupported source unit")
    return pl.DataFrame([(station, "phisis", resolution, variable, unit)], schema=ASSOCIATION_SCHEMA, orient="row")


def monthly_associations(payload: Mapping[str, object], *, station: str, station_ids: set[str]) -> pl.DataFrame:
    """Preserve individually witnessed monthly level fields without assigning time meaning.

    The selected request supplies station identity because the monthly envelope
    does not repeat it. Meteorological-only answers establish no level association.
    """
    data = _data(payload)
    if station not in station_ids or not isinstance(data, dict):
        raise FatalContractError("Monthly association requires a selected registry station and columns")
    data = cast("dict[str, object]", data)
    columns = data.get("columns")
    if not isinstance(columns, list):
        raise FatalContractError("Monthly association requires source columns")
    rows = []
    for column in columns:
        if not isinstance(column, dict):
            raise FatalContractError("Monthly source column must be an object")
        column = cast("dict[str, object]", column)
        name = column.get("column")
        if name not in MONTHLY_LEVEL_FIELDS:
            continue
        if column.get("unit") != "m":
            raise FatalContractError("Monthly level association has an unsupported source unit")
        rows.append((station, "monthly_archive", None, name, column["unit"]))
    return pl.DataFrame(rows, schema=ASSOCIATION_SCHEMA, orient="row").unique().sort(ASSOCIATION_SCHEMA.names())


def association_product(subsystem: str, resolution: str | None, variable: str, unit: str) -> str:
    if subsystem == "phisis":
        suffix = "_above_sea_level" if unit == "m.s.n.m" else ""
        return f"phisis_{str(resolution).lower()}_{variable.lower()}{suffix}"
    return f"monthly_archive_{variable.lower()}"


def catalogue_tables(
    native: NativeTable, associations: pl.DataFrame, *, checked_on: "date"
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Build witnessed product candidates and leave all other station pairs unknown.

    Sampling frequency names remain source identity, without claiming temporal
    support or statistics. Sample dates never become published record bounds.
    """
    from rivretrieve._internal.catalogues.schemas import (
        PRODUCT_CATALOG_SCHEMA,
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
        validate_catalogue,
    )

    stations = native.data.select(
        pl.lit("pe_senamhi").alias("provider_id"),
        pl.col("stationId").alias("station_id"),
        pl.col("latitude").cast(pl.Float64),
        pl.col("longitude").cast(pl.Float64),
        pl.lit("unknown").alias("crs"),
    ).sort("station_id")
    if not set(associations["station_id"]) <= set(stations["station_id"]):
        raise FatalContractError("SENAMHI association is absent from selected registry")
    rows = []
    for subsystem, resolution, variable, unit in (
        associations.select("subsystem", "resolution", "variable", "unit")
        .unique()
        .sort("subsystem", "resolution", "variable", "unit")
        .iter_rows()
    ):
        rows.append(
            {
                "provider_id": "pe_senamhi",
                "product_id": association_product(subsystem, resolution, variable, unit),
                "observed_property": "discharge" if variable == "FLOW" else "stage",
                "frequency": "unknown",
                "statistic": "unknown",
                "period_type": "unknown",
                "period_anchor": "unknown",
                "unit": "m3/s" if variable == "FLOW" else "m",
                "native_id": ":".join(
                    str(value) for value in (subsystem, resolution, variable, unit) if value is not None
                ),
            }
        )
    products = pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")
    observed = {
        (station, association_product(subsystem, resolution, variable, unit))
        for station, subsystem, resolution, variable, unit in associations.iter_rows()
    }
    pairs = pl.DataFrame(
        [
            {
                "provider_id": "pe_senamhi",
                "station_id": station,
                "product_id": product,
                "availability": "available" if (station, product) in observed else "unknown",
                "availability_reason": "Recognized source association; historical inventory remains incomplete"
                if (station, product) in observed
                else "No association established by selected samples",
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
    """Describe witnessed source fields with only established physical facts."""
    from rivretrieve._internal.catalogues.source_series import SourceDescription

    descriptions = []
    for station, subsystem, resolution, variable, unit in (
        associations.unique().sort(ASSOCIATION_SCHEMA.names()).iter_rows()
    ):
        for field, mapping in series_mappings(subsystem, resolution, variable, unit).items():
            descriptions.append(
                SourceDescription(
                    product_id=association_product(subsystem, resolution, variable, unit),
                    station_id=station,
                    native_coordinate=field,
                    identity=mapping.identity(),
                    facts=(mapping.physical_facts(),),
                )
            )
    return SourceDescriptions(provider_id="pe_senamhi", descriptions=tuple(descriptions))


def read_original(evidence_root: Path, reference: RecordingReference, *, input_receipt: RetainedInputReceipt) -> bytes:
    """Verify one explicitly selected publisher body before parsing it.

    The private source verifier owns original receipt interpretation, including
    final page URL checks. This boundary checks the selected member bytes and
    declared recording identity; it does not discover files or make requests.
    """
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    selected = {item.consumer_path: item for item in input_receipt.inputs}
    member = selected.get(reference.repository_path)
    if member is None:
        raise FatalContractError("SENAMHI original is absent from selected retained inputs")
    if member.sha256 != reference.sha256:
        raise FatalContractError("SENAMHI original differs from its selected recording identity")
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    return (evidence_root / reference.repository_path).read_bytes()


def _read_selection(evidence_root: Path, selection_path: str, input_receipt: RetainedInputReceipt) -> dict:
    import json

    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("SENAMHI selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt, evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    if not isinstance(selection, dict) or not isinstance(selection.get("captures"), list):
        raise FatalContractError("SENAMHI selection requires explicit captures")
    return selection


def _selected_native(evidence_root: Path, selection: dict, input_receipt: RetainedInputReceipt) -> NativeTable:
    import json

    from rivretrieve._internal.providers.pe_senamhi.station_metadata import enrich_station_metadata

    payloads = {}
    registry_times = []
    details = []
    for capture in selection["captures"]:
        kind = capture["kind"]
        if kind not in {"registry_h", "registry_m", "registry_actives", "phisis_detail"}:
            continue
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError("SENAMHI selected body disagrees with recording identity")
        payload = json.loads(read_original(evidence_root, reference, input_receipt=input_receipt))
        if not isinstance(payload, dict):
            raise FatalContractError("SENAMHI source envelope requires an object")
        if kind == "phisis_detail":
            details.append(payload)
        else:
            if kind in payloads:
                raise FatalContractError("SENAMHI selection requires exactly one snapshot per registry")
            payloads[kind] = payload
            registry_times.append(reference.retrieved_at)
    if set(payloads) != {"registry_h", "registry_m", "registry_actives"}:
        raise FatalContractError("SENAMHI selection requires all three registry snapshots")
    native = station_native_table(
        payloads["registry_h"],
        payloads["registry_m"],
        payloads["registry_actives"],
        retrieved_at=RetrievedAt(max(registry_times)),
    )
    return enrich_station_metadata(native, details)


def read_native_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> NativeTable:
    """Derive native station rows from verified selected originals, without a native input.

    The UTC stamp records completion of the selected registry captures, not a
    source update date. Only exact primary-code PHISIS detail joins enrich rows.
    """
    selection = _read_selection(evidence_root, selection_path, input_receipt)
    return _selected_native(evidence_root, selection, input_receipt)


@dataclass(frozen=True)
class GeneratedSenamhiCatalogue:
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
) -> GeneratedSenamhiCatalogue:
    """Assemble an official catalogue from selected source-backed associations.

    No observation service is contacted. Source descriptions remain scoped to
    witnessed station identities, while unknown station-product inventory stays
    open. Metadata must be separately verified and approved before publication.
    """
    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId

    products, stations, pairs = catalogue_tables(native_table, associations, checked_on=checked_on)
    enforce_catalogue_origins(ProviderId("pe_senamhi"), origins, native_table, stations)
    if provenance is None or provenance.provider_id != "pe_senamhi":
        raise FatalContractError("Official catalogue requires its selected acquisition provenance")
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info: dict[str, object] = {
        "provider_id": "pe_senamhi",
        "name": "Servicio Nacional de Meteorología e Hidrología del Perú (SENAMHI)",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": statements.get("license"),
        "citation": "Servicio Nacional de Meteorología e Hidrología del Perú (SENAMHI)",
    }
    return GeneratedSenamhiCatalogue(
        provider_info,
        products,
        stations,
        pairs,
        provenance,
        describe_associations(associations),
        station_metadata,
    )


def write_catalogue(
    catalogue: GeneratedSenamhiCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
    metadata_fields: tuple[MetadataField, ...] = (),
) -> None:
    """Publish candidate tables through the shared evidence-aware publication path.

    Inputs must already be explicitly selected and verified. This writes public
    candidate products, never source bodies or restricted acquisition receipts.
    It does not authorize disclosure or replace genuine-input verification.
    """
    import json
    from io import BytesIO

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.pe_senamhi.origins import (
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
            "src/rivretrieve/_internal/providers/pe_senamhi/station_metadata.py",
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
    """Recompute native rows and product witnesses from verified selected originals.

    The retained derivative must equal the recomputed station table. Failed period
    probes remain evidence, not absent rows or unavailable station-product pairs.
    """
    import json

    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.pe_senamhi.origins import build_acquisition_provenance
    from rivretrieve._internal.providers.pe_senamhi.station_metadata import project_station_metadata

    selection = _read_selection(evidence_root, selection_path, input_receipt)
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    native_path = selection["native_table"]
    if native_path not in selected:
        raise FatalContractError("SENAMHI native table is absent from selected inputs")
    member = selected[native_path]
    native = read_native_table(
        evidence_root / native_path, expected_sha256=member.sha256, expected_byte_size=member.byte_size
    )
    reconstructed = _selected_native(evidence_root, selection, input_receipt)
    if not native.data.equals(reconstructed.data):
        raise FatalContractError("SENAMHI retained native differs from selected original reconstruction")
    identities = set(native.data["stationId"])
    recordings = []
    associations = []
    for capture in selection["captures"]:
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError("SENAMHI selected body disagrees with recording identity")
        content = read_original(evidence_root, reference, input_receipt=input_receipt)
        recordings.append(reference)
        if capture["kind"] == "hydrogram":
            associations.append(
                phisis_associations(
                    json.loads(content),
                    station=capture["station"],
                    resolution=capture["resolution"],
                    variable=capture["variable"],
                    station_ids=identities,
                )
            )
        elif capture["kind"] == "monthly":
            associations.append(
                monthly_associations(json.loads(content), station=capture["station"], station_ids=identities)
            )
    observed = (
        pl.concat(associations).unique().sort(ASSOCIATION_SCHEMA.names())
        if associations
        else pl.DataFrame(schema=ASSOCIATION_SCHEMA)
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
    _, stations, _ = catalogue_tables(native, observed, checked_on=checked_on)
    return CatalogueSources(native, observed, provenance, project_station_metadata(native, stations), checked_on)


def selected_supporting_inputs(provenance: AcquisitionProvenance, selection: dict) -> dict[str, tuple[str, ...]]:
    """Associate selected acquisition receipts with the facts of their original bodies.

    ``selection`` must be the digest-verified authored declaration used for the
    build. Only receipts of recordings adopted in provenance enter build support.
    """
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
    result = {}
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
    """Compose a derived native candidate outside source and retained-input roots."""
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
        raise FatalContractError("SENAMHI native output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("SENAMHI native output must stay outside source checkouts")
    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
    if args.native_only:
        native = read_native_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        write_native_table(native, output / "native.parquet")
    else:
        if args.build_inputs is None:
            raise FatalContractError("Catalogue publication requires explicit build inputs")
        from rivretrieve._internal.providers.pe_senamhi.origins import STATION_CATALOGUE_ORIGINS
        from rivretrieve._internal.providers.pe_senamhi.station_metadata import STATION_METADATA_FIELDS

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

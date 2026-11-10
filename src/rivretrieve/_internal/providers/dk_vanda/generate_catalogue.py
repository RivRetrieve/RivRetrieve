"""Offline transformations of VandA's single `GET /stations` registry.

Unlike providers that assemble a catalogue from several registry snapshots
(e.g. `pe_senamhi`'s hydrological/meteorological/active registries), VandA
returns station identity, coordinates and every station's examination list
in one response. Station rows and station-product associations are both
derived from that one retained capture.
"""

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
from rivretrieve._internal.providers.dk_vanda.series import EXAMINATION_PRODUCTS, series_mappings

RIVER_LOCATION_TYPE = "Vandløb"
EXPECTED_SRID = "25832"

STATION_SOURCE_SCHEMA = pl.Schema(
    {
        "stationId": pl.String,
        "stationUid": pl.String,
        "name": pl.String,
        "locationType": pl.String,
        "stationOwnerName": pl.String,
        "operatorName": pl.String,
        "x": pl.Float64,
        "y": pl.Float64,
        "catchmentAreaKm2": pl.Float64,
    }
)

ASSOCIATION_SCHEMA = pl.Schema(
    {"station_id": pl.String, "examination_type_sc": pl.Int64, "parameter": pl.String, "unit": pl.String}
)


def _rows(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise FatalContractError("VandA /stations response must be a list of station objects")
    return cast("list[dict[str, object]]", payload)


def station_native_table(payload: object, *, retrieved_at: RetrievedAt) -> NativeTable:
    """Keep river stations only, with their coordinates and registry metadata.

    Every retained station's ``location.srid`` must read ``"25832"``; a
    different value means the coordinate conversion in ``origins.py`` would
    silently misproject that station, so this raises rather than continuing.
    """
    selected: dict[str, dict[str, object]] = {}
    for row in _rows(payload):
        if row.get("locationType") != RIVER_LOCATION_TYPE:
            continue
        identity = row.get("stationId")
        if not isinstance(identity, str) or not identity.strip():
            raise FatalContractError("VandA stationId must be a nonblank source string")
        location = row.get("location")
        if not isinstance(location, dict):
            raise FatalContractError("VandA station requires a location object")
        location = cast("dict[str, object]", location)
        if location.get("srid") != EXPECTED_SRID:
            raise FatalContractError("VandA station has an unexpected coordinate reference system")
        values = {
            "stationId": identity,
            "stationUid": row.get("stationUid"),
            "name": row.get("name"),
            "locationType": row.get("locationType"),
            "stationOwnerName": row.get("stationOwnerName"),
            "operatorName": row.get("operatorName"),
            "x": location.get("x"),
            "y": location.get("y"),
            "catchmentAreaKm2": row.get("catchmentAreaKm2"),
        }
        for name, dtype in STATION_SOURCE_SCHEMA.items():
            value = values[name]
            if value is not None and (
                (dtype == pl.String and not isinstance(value, str))
                or (dtype == pl.Float64 and (isinstance(value, bool) or not isinstance(value, int | float)))
            ):
                raise FatalContractError("VandA registry metadata has invalid scalar types")
        if identity in selected and selected[identity] != values:
            raise FatalContractError("VandA registry has two river stations sharing one stationId")
        selected[identity] = values
    frame = pl.DataFrame(list(selected.values()), schema=STATION_SOURCE_SCHEMA).sort("stationId")
    return stamp_native_table(frame, retrieved_at)


def station_product_associations(payload: object, *, station_ids: set[str]) -> pl.DataFrame:
    """Read each selected station's admitted examinations, ignoring the rest.

    Only the three examination types settled in scope (discharge, stage,
    water temperature) become associations; field gaugings, levelling surveys
    and instrument diagnostics are read and discarded here, not treated as an
    error, since they are real, documented, out-of-scope examination types.
    """
    rows: list[tuple[str, int, str, str]] = []
    for row in _rows(payload):
        identity = row.get("stationId")
        if identity not in station_ids:
            continue
        points = row.get("measurementPoints")
        if not isinstance(points, list):
            raise FatalContractError("VandA station requires a measurement-point list")
        for point in points:
            if not isinstance(point, dict):
                raise FatalContractError("VandA measurement point must be an object")
            point = cast("dict[str, object]", point)
            examinations = point.get("examinations")
            if not isinstance(examinations, list):
                raise FatalContractError("VandA measurement point requires an examination list")
            for examination in examinations:
                if not isinstance(examination, dict):
                    raise FatalContractError("VandA examination must be an object")
                examination = cast("dict[str, object]", examination)
                code = examination.get("examinationTypeSc")
                if code not in EXAMINATION_PRODUCTS:
                    continue
                parameter, unit = examination.get("parameter"), examination.get("unit")
                if not isinstance(parameter, str) or not isinstance(unit, str):
                    raise FatalContractError("VandA admitted examination requires a published parameter and unit")
                rows.append((cast("str", identity), cast("int", code), parameter, unit))
    return (
        pl.DataFrame(rows, schema=ASSOCIATION_SCHEMA, orient="row").unique().sort(ASSOCIATION_SCHEMA.names())
        if rows
        else pl.DataFrame(schema=ASSOCIATION_SCHEMA)
    )


def _project_to_wgs84(x: pl.Series, y: pl.Series) -> tuple[pl.Series, pl.Series]:
    """Re-project native ETRS89/UTM32N coordinates to EPSG:4326 longitude/latitude.

    Independent of ``origins.Utm32EtrsToWgs84Conversion``, which exists only
    so the shared origin gate can recompute and verify this same projection
    from the native table, not to perform it here.
    """
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
    lon, lat = [], []
    for value_x, value_y in zip(x.to_list(), y.to_list(), strict=True):
        if value_x is None or value_y is None:
            lon.append(None)
            lat.append(None)
            continue
        projected_lon, projected_lat = transformer.transform(value_x, value_y)
        lon.append(projected_lon)
        lat.append(projected_lat)
    return pl.Series("longitude", lon, dtype=pl.Float64), pl.Series("latitude", lat, dtype=pl.Float64)


def catalogue_tables(
    native: NativeTable, associations: pl.DataFrame, *, checked_on: date
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Build witnessed product candidates and leave all other station pairs unknown."""
    from rivretrieve._internal.catalogues.schemas import (
        PRODUCT_CATALOG_SCHEMA,
        STATION_CATALOG_SCHEMA,
        STATION_PRODUCT_CATALOG_SCHEMA,
        validate_catalogue,
    )

    lon_by_x_y, lat_by_x_y = _project_to_wgs84(native.data["x"], native.data["y"])
    stations = (
        native.data.select(
            pl.lit("dk_vanda").alias("provider_id"),
            pl.col("stationId").alias("station_id"),
        )
        .with_columns(latitude=lat_by_x_y, longitude=lon_by_x_y, crs=pl.lit("EPSG:4326"))
        .sort("station_id")
    )
    if not set(associations["station_id"]) <= set(stations["station_id"]):
        raise FatalContractError("VandA association is absent from selected river-station registry")
    rows = []
    for code in sorted(set(associations["examination_type_sc"].to_list())):
        product = EXAMINATION_PRODUCTS[code]
        mapping = next(iter(series_mappings(code).values()))
        rows.append(
            {
                "provider_id": "dk_vanda",
                "product_id": product,
                "observed_property": mapping.quantity,
                "frequency": "unknown",
                "statistic": "unknown",
                "period_type": "unknown",
                "period_anchor": "unknown",
                "unit": mapping.source_unit,
                "native_id": str(code),
            }
        )
    products = pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")
    observed = {
        (station, EXAMINATION_PRODUCTS[code])
        for station, code in associations.select("station_id", "examination_type_sc").iter_rows()
    }
    pairs = pl.DataFrame(
        [
            {
                "provider_id": "dk_vanda",
                "station_id": station,
                "product_id": product,
                "availability": "available" if (station, product) in observed else "unknown",
                "availability_reason": "Recognized source examination; historical inventory remains incomplete"
                if (station, product) in observed
                else "No examination of this type found for this station in the selected capture",
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
    for station, code in (
        associations.select("station_id", "examination_type_sc")
        .unique()
        .sort("station_id", "examination_type_sc")
        .iter_rows()
    ):
        product = EXAMINATION_PRODUCTS[code]
        for field, mapping in series_mappings(code).items():
            descriptions.append(
                SourceDescription(
                    product_id=product,
                    station_id=station,
                    native_coordinate=field,
                    identity=mapping.identity(),
                    facts=(mapping.physical_facts(),),
                )
            )
    return SourceDescriptions(provider_id="dk_vanda", descriptions=tuple(descriptions))


def read_original(evidence_root: Path, reference: RecordingReference, *, input_receipt: RetainedInputReceipt) -> bytes:
    """Verify one explicitly selected publisher body before parsing it."""
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    selected = {item.consumer_path: item for item in input_receipt.inputs}
    member = selected.get(reference.repository_path)
    if member is None:
        raise FatalContractError("VandA original is absent from selected retained inputs")
    if member.sha256 != reference.sha256:
        raise FatalContractError("VandA original differs from its selected recording identity")
    verify_retained_input_files(
        input_receipt.model_copy(update={"inputs": (member,), "declaration_inputs": (), "support_inputs": ()}),
        evidence_root,
    )
    return (evidence_root / reference.repository_path).read_bytes()


def _read_selection(evidence_root: Path, selection_path: str, input_receipt: RetainedInputReceipt) -> dict:
    import json

    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("VandA selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt, evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    if not isinstance(selection, dict) or not isinstance(selection.get("captures"), list):
        raise FatalContractError("VandA selection requires explicit captures")
    return selection


def _selected_payload(
    evidence_root: Path, selection: dict, input_receipt: RetainedInputReceipt
) -> tuple[object, RetrievedAt]:
    import json

    captures = [capture for capture in selection["captures"] if capture["kind"] == "stations"]
    if len(captures) != 1:
        raise FatalContractError("VandA selection requires exactly one stations capture")
    capture = captures[0]
    reference = RecordingReference.model_validate(capture["recording"])
    if reference.repository_path != capture["body"]:
        raise FatalContractError("VandA selected body disagrees with recording identity")
    payload = json.loads(read_original(evidence_root, reference, input_receipt=input_receipt))
    return payload, RetrievedAt(reference.retrieved_at)


def read_native_sources(
    evidence_root: Path, *, selection_path: str, input_receipt: RetainedInputReceipt
) -> NativeTable:
    """Derive native station rows from the verified selected original."""
    selection = _read_selection(evidence_root, selection_path, input_receipt)
    payload, retrieved_at = _selected_payload(evidence_root, selection, input_receipt)
    return station_native_table(payload, retrieved_at=retrieved_at)


@dataclass(frozen=True)
class GeneratedDkVandaCatalogue:
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
) -> GeneratedDkVandaCatalogue:
    """Assemble an official catalogue from selected source-backed associations.

    No observation service is contacted. License/citation are published as
    unknown unless ``provenance`` actually carries recorded terms statements;
    this function does not fabricate either.
    """
    from rivretrieve._internal.catalogue_origins import enforce_catalogue_origins
    from rivretrieve._internal.primitives import ProviderId

    products, stations, pairs = catalogue_tables(native_table, associations, checked_on=checked_on)
    enforce_catalogue_origins(ProviderId("dk_vanda"), origins, native_table, stations)
    if provenance is None or provenance.provider_id != "dk_vanda":
        raise FatalContractError("Official catalogue requires its selected acquisition provenance")
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info: dict[str, object] = {
        "provider_id": "dk_vanda",
        "name": "Miljøstyrelsen (Danish Environmental Protection Agency), VandA / Miljøportal",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": statements.get("license"),
        "citation": statements.get("citation") or "Miljøstyrelsen (Danish Environmental Protection Agency)",
    }
    return GeneratedDkVandaCatalogue(
        provider_info, products, stations, pairs, provenance, describe_associations(associations), station_metadata
    )


def write_catalogue(
    catalogue: GeneratedDkVandaCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
    metadata_fields: tuple[MetadataField, ...] = (),
) -> None:
    """Publish candidate tables through the shared evidence-aware publication path."""
    import json
    from io import BytesIO

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.dk_vanda.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_NOTICE

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
            "src/rivretrieve/_internal/providers/dk_vanda/station_metadata.py",
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
    """Recompute native rows and product witnesses from the verified selected original."""
    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.dk_vanda.origins import build_acquisition_provenance
    from rivretrieve._internal.providers.dk_vanda.station_metadata import project_station_metadata

    selection = _read_selection(evidence_root, selection_path, input_receipt)
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    native_path = selection["native_table"]
    if native_path not in selected:
        raise FatalContractError("VandA native table is absent from selected inputs")
    member = selected[native_path]
    native = read_native_table(
        evidence_root / native_path, expected_sha256=member.sha256, expected_byte_size=member.byte_size
    )
    payload, retrieved_at = _selected_payload(evidence_root, selection, input_receipt)
    reconstructed = station_native_table(payload, retrieved_at=retrieved_at)
    if not native.data.equals(reconstructed.data):
        raise FatalContractError("VandA retained native differs from selected original reconstruction")
    identities = set(native.data["stationId"])
    capture = next(item for item in selection["captures"] if item["kind"] == "stations")
    reference = RecordingReference.model_validate(capture["recording"])
    associations = station_product_associations(payload, station_ids=identities)
    provenance = build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path=native_path,
            revision=selection["native_revision"],
            sha256=member.sha256,
            byte_size=member.byte_size,
        ),
        (reference,),
        acquisitions=tuple(AcquisitionRecord.model_validate(item) for item in selection["publication_acquisitions"]),
        source_bindings=tuple(FactBinding.model_validate(item) for item in selection["source_bindings"]),
        statements=tuple(SourceStatement.model_validate(item) for item in selection["statements"]),
    )
    checked_on = date.fromisoformat(selection["checked_on"])
    _, stations, _ = catalogue_tables(native, associations, checked_on=checked_on)
    return CatalogueSources(native, associations, provenance, project_station_metadata(native, stations), checked_on)


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
        raise FatalContractError("VandA native output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("VandA native output must stay outside source checkouts")
    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
    if args.native_only:
        native = read_native_sources(evidence_root, selection_path=args.selection, input_receipt=receipt)
        write_native_table(native, output / "native.parquet")
    else:
        if args.build_inputs is None:
            raise FatalContractError("Catalogue publication requires explicit build inputs")
        from rivretrieve._internal.providers.dk_vanda.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

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

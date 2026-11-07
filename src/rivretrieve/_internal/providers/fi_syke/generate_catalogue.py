"""SYKE catalogue maintenance : build(NativeTable × OriginDeclarations) -> GeneratedFiSykeCatalogue."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
    RetainedInputReceipt,
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations, enforce_catalogue_origins
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    AvailabilityDtype,
    ProductCatalog,
    StationCatalog,
    StationProductCatalog,
    validate_catalogue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.fi_syke.series import PRODUCT_DEFINITIONS, SUURE_ID_TO_PRODUCT

PROVIDER_ID = ProviderId("fi_syke")
PROVIDER_NAME = "Finnish Environment Institute (Syke), Hydrologiarajapinta"

NATIVE_SOURCE_SCHEMA = pl.Schema(
    {
        "Nro": pl.String,
        "Paikka_Id": pl.Int64,
        "Nimi": pl.String,
        "KuntaNimi": pl.String,
        "VesalNimi": pl.String,
        "PaaVesalNimi": pl.String,
        "KoordErTmIta": pl.Int64,
        "KoordErTmPohj": pl.Int64,
        "KoordYkIta": pl.Int64,
        "KoordYkPohj": pl.Int64,
        "KoordLat": pl.String,
        "KoordLong": pl.String,
        "latitude_etrs89": pl.Float64,
        "longitude_etrs89": pl.Float64,
    }
)
NATIVE_SCHEMA = pl.Schema({**NATIVE_SOURCE_SCHEMA, "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC")})

ASSOCIATION_SCHEMA = pl.Schema({"Nro": pl.String, "product_id": pl.String})

# SYKE's own identity field (Paikka_Id) is quantity-specific, not station-specific --
# confirmed live 2026-11-07: of 2,543 Paikka rows across the three admitted quantities,
# only 1,967 distinct Nro (SYKE's official site code) exist; 546 Nro values have two
# Paikka_Id rows (almost always a discharge + stage pair) and 30 have three, each with
# its own slightly different coordinates (tens of metres apart) and sometimes a
# different name or Tila_Id. Nro, not Paikka_Id, is the real station identity.
_QUANTITY_PRIORITY = {1: 0, 2: 1, 11: 2}  # stage, discharge, temperature


@dataclass(frozen=True)
class GeneratedFiSykeCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    acquisition_provenance: AcquisitionProvenance


def station_native_table(
    paikka_rows: list[dict[str, object]], *, retrieved_at: RetrievedAt
) -> tuple[NativeTable, pl.DataFrame, tuple[str, ...]]:
    """Group Paikka's quantity-specific rows by Nro into one row per real station.

    For a station with more than one Paikka_Id (one per quantity), keeps the first
    record in a fixed stage/discharge/temperature order -- the same "take the first
    encountered" rule au_bom already applies to its own ambiguous-duplicate-station
    problem -- and returns the Nro values where name or coordinates genuinely
    disagree across a station's own records, rather than silently merging or
    averaging them. Tila_Id is a per-(station, quantity) fact (confirmed to differ
    within 97 stations' own records), so it belongs to the associations, not here.
    """
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in paikka_rows:
        nro = row["Nro"]
        if not isinstance(nro, str) or not nro.strip():
            raise FatalContractError("fi_syke Paikka row has an invalid Nro")
        grouped.setdefault(nro, []).append(row)
    if not grouped:
        raise FatalContractError("fi_syke Paikka rows produced no stations")

    native_rows: list[dict[str, object]] = []
    assoc_rows: list[dict[str, object]] = []
    ambiguous: list[str] = []
    for nro in sorted(grouped):
        group = sorted(grouped[nro], key=lambda r: _QUANTITY_PRIORITY[_required_int(r["Suure_Id"])])
        primary = group[0]
        if len(group) > 1:
            coords = {(r["KoordErTmIta"], r["KoordErTmPohj"]) for r in group}
            names = {str(r["Nimi"]).strip() for r in group}
            if len(coords) > 1 or len(names) > 1:
                ambiguous.append(nro)
        native_rows.append(
            {
                "Nro": nro,
                "Paikka_Id": primary["Paikka_Id"],
                "Nimi": primary["Nimi"],
                "KuntaNimi": primary["KuntaNimi"],
                "VesalNimi": primary["VesalNimi"],
                "PaaVesalNimi": primary["PaaVesalNimi"],
                "KoordErTmIta": primary["KoordErTmIta"],
                "KoordErTmPohj": primary["KoordErTmPohj"],
                "KoordYkIta": primary["KoordYkIta"],
                "KoordYkPohj": primary["KoordYkPohj"],
                "KoordLat": primary["KoordLat"],
                "KoordLong": primary["KoordLong"],
                "latitude_etrs89": _ertm_to_etrs89_latitude(primary["KoordErTmIta"], primary["KoordErTmPohj"]),
                "longitude_etrs89": _ertm_to_etrs89_longitude(primary["KoordErTmIta"], primary["KoordErTmPohj"]),
            }
        )
        for r in group:
            product_id = SUURE_ID_TO_PRODUCT.get(_required_int(r["Suure_Id"]))
            if product_id is None:
                raise FatalContractError(f"fi_syke Paikka row has an unadmitted Suure_Id: {r['Suure_Id']!r}")
            assoc_rows.append({"Nro": nro, "product_id": product_id})

    source = pl.DataFrame(native_rows, schema=NATIVE_SOURCE_SCHEMA)
    associations = pl.DataFrame(assoc_rows, schema=ASSOCIATION_SCHEMA)
    return stamp_native_table(source, retrieved_at), associations, tuple(ambiguous)


def _required_int(value: object) -> int:
    if isinstance(value, int):
        return value
    raise FatalContractError(f"fi_syke Paikka row has a non-integer Suure_Id: {value!r}")


def _ertm_to_etrs89_latitude(easting: object, northing: object) -> float:
    return _ertm_to_etrs89(easting, northing)[1]


def _ertm_to_etrs89_longitude(easting: object, northing: object) -> float:
    return _ertm_to_etrs89(easting, northing)[0]


def _ertm_to_etrs89(easting: object, northing: object) -> tuple[float, float]:
    """Inverse-project ETRS-TM35FIN (EPSG:3067) to geographic ETRS89 (EPSG:4258).

    Finland's current national standard, not a reprojection to a different datum
    (WGS84): confirmed by direct numerical cross-check against the source's own
    legacy KKJ-family coordinates, see origins.py's module docstring and the
    station catalogue vision.
    """
    from pyproj import Transformer

    if not isinstance(easting, int) or not isinstance(northing, int):
        raise FatalContractError("fi_syke ETRS-TM35FIN coordinates must be integers")
    transformer = Transformer.from_crs("EPSG:3067", "EPSG:4258", always_xy=True)
    longitude, latitude = transformer.transform(easting, northing)
    return float(longitude), float(latitude)


def build_products() -> ProductCatalog:
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "product_id": d.product_id,
            "observed_property": d.observed_property,
            "frequency": d.frequency,
            "statistic": d.statistic,
            "period_type": "unknown",
            "period_anchor": "unknown",
            "unit": d.canonical_unit,
            "native_id": d.native_id,
        }
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(native_table: NativeTable) -> StationCatalog:
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "station_id": row["Nro"],
            "latitude": row["latitude_etrs89"],
            "longitude": row["longitude_etrs89"],
            "crs": "EPSG:4258" if row["KoordErTmIta"] is not None else "unknown",
        }
        for row in native_table.data.iter_rows(named=True)
    ]
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(
    *,
    station_ids: list[str],
    associations: pl.DataFrame,
    catalogue_date: date,
) -> StationProductCatalog:
    witnessed = {(row["Nro"], row["product_id"]) for row in associations.iter_rows(named=True)}
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "station_id": station_id,
            "product_id": d.product_id,
            "availability": "available" if (station_id, d.product_id) in witnessed else "unknown",
            "availability_reason": None
            if (station_id, d.product_id) in witnessed
            else "Not witnessed in SYKE's Paikka site list for this quantity",
            "published_record_start_date": None,
            "published_record_end_date": None,
            "last_catalogue_check": catalogue_date,
        }
        for station_id in station_ids
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(AvailabilityDtype)
    )


def build_provider_info(
    catalogue_date: date, *, license_text: str | None, citation_text: str | None
) -> dict[str, object]:
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "unknown: fi_syke is CatalogueOnly; retrieval behavior is not yet implemented",
        "catalogue_version": catalogue_date.isoformat(),
        "license": license_text,
        "citation": citation_text,
    }


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
    *,
    associations: pl.DataFrame,
    checked_on: date,
    provenance: AcquisitionProvenance,
) -> GeneratedFiSykeCatalogue:
    """Assemble the official Finland SYKE offline station and product catalogue."""
    if native_table.data.schema != NATIVE_SCHEMA:
        raise FatalContractError("fi_syke native table does not have the exact required schema")
    if native_table.data.is_empty():
        raise FatalContractError("fi_syke native table must not be empty")
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    station_products = build_station_products(
        station_ids=stations["station_id"].to_list(), associations=associations, catalogue_date=checked_on
    )
    for frame, schema in (
        (products, PRODUCT_CATALOG_SCHEMA),
        (stations, STATION_CATALOG_SCHEMA),
        (station_products, STATION_PRODUCT_CATALOG_SCHEMA),
    ):
        validate_catalogue(frame, schema, on_issue="raise")
    if provenance is None or provenance.provider_id != "fi_syke":
        raise FatalContractError("Official fi_syke catalogue requires its selected acquisition provenance")
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info = build_provider_info(
        checked_on, license_text=statements.get("license"), citation_text=statements.get("citation")
    )
    from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components

    packaged_catalogue_artifact_from_components(
        provider_info, products, stations, station_products, acquisition_provenance=provenance, on_issue="raise"
    )
    return GeneratedFiSykeCatalogue(provider_info, products, stations, station_products, provenance)


def write_catalogue(
    catalogue: GeneratedFiSykeCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
) -> None:
    """Publish candidate runtime tables through the shared evidence-aware publication path."""
    from io import BytesIO

    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.fi_syke.catalogue_series import describe_catalogue
    from rivretrieve._internal.providers.fi_syke.origins import (
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
        source_describer=describe_catalogue,
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=STATION_METADATA_FIELDS,
        station_metadata_notice=STATION_METADATA_NOTICE,
    )
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, content in {**files, **metadata}.items():
        (output / name).write_bytes(content)


@dataclass(frozen=True)
class CatalogueSources:
    native_table: NativeTable
    associations: pl.DataFrame
    checked_on: date
    provenance: AcquisitionProvenance


def read_catalogue_sources(
    evidence_root: Path,
    *,
    selection_path: str = "maintenance/catalogue/fi_syke/official/catalogue.json",
    input_receipt: RetainedInputReceipt,
) -> CatalogueSources:
    """Read an explicitly selected offline build after exact member verification.

    The reviewed declaration (``selection_path``, read from ``evidence_root``)
    names the 6 Paikka page captures, 3 reference-table captures, 1 terms-page
    capture, and one separately retained derived ``native_table``, each checked
    against ``input_receipt`` before use -- matching ``au_bom``'s and ``ch_foen``'s
    own ``read_catalogue_sources`` shape. The native table and associations are
    independently recomputed from the 6 Paikka page captures
    (``station_native_table``) and checked byte-for-byte (native table only;
    associations have no independent retained identity) against the separately
    retained ``native_table`` member.
    """
    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        RecordingReference,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.fi_syke import origins

    if selection_path not in {item.consumer_path for item in input_receipt.declaration_inputs}:
        raise FatalContractError("fi_syke selection requires a selected authored declaration")
    verify_retained_input_files(input_receipt, evidence_root)
    selection = json.loads((evidence_root / selection_path).read_bytes())
    selected = {item.consumer_path: item for item in input_receipt.inputs}
    captures = {capture["kind"]: capture for capture in selection["captures"]}

    def body(kind: str) -> bytes:
        capture = captures[kind]
        reference = RecordingReference.model_validate(capture["recording"])
        if reference.repository_path != capture["body"]:
            raise FatalContractError("fi_syke selected body disagrees with recording identity")
        member = selected.get(capture["body"])
        if member is None or member.sha256 != reference.sha256:
            raise FatalContractError("fi_syke original is absent from selected retained inputs")
        return (evidence_root / capture["body"]).read_bytes()

    paikka_rows: list[dict[str, object]] = []
    paikka_retrieved_at: list[datetime] = []
    for i in range(1, 7):
        kind = f"paikka-page-{i:02d}"
        doc = json.loads(body(kind))
        paikka_rows.extend(doc["value"])
        paikka_retrieved_at.append(RecordingReference.model_validate(captures[kind]["recording"]).retrieved_at)

    checked_on_date = date.fromisoformat(selection["checked_on"])
    native, associations, _ambiguous = station_native_table(
        paikka_rows,
        retrieved_at=RetrievedAt(max(paikka_retrieved_at)),
    )

    native_path = selection["native_table"]
    native_member = selected.get(native_path)
    if native_member is None:
        raise FatalContractError("fi_syke native table is absent from selected inputs")
    retained_native = read_native_table(
        evidence_root / native_path,
        expected_sha256=native_member.sha256,
        expected_byte_size=native_member.byte_size,
    )
    if not native.data.equals(retained_native.data):
        raise FatalContractError("fi_syke recomputed native table differs from its separately retained identity")

    provenance = origins.build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path=native_path,
            revision=native_member.archive_revision,
            sha256=native_member.sha256,
            byte_size=native_member.byte_size,
        ),
        tuple(RecordingReference.model_validate(capture["recording"]) for capture in selection["captures"]),
        acquisitions=tuple(AcquisitionRecord.model_validate(item) for item in selection["publication_acquisitions"]),
        source_bindings=tuple(FactBinding.model_validate(item) for item in selection["source_bindings"]),
        statements=tuple(SourceStatement.model_validate(item) for item in selection["statements"]),
    )
    return CatalogueSources(native, associations, checked_on_date, provenance)


def main(argv: list[str] | None = None) -> int:
    """Compose a selected, offline official fi_syke catalogue candidate outside source checkouts."""
    import argparse

    from rivretrieve._internal.acquisition_provenance import RetainedInputReceipt
    from rivretrieve._internal.providers.fi_syke.origins import STATION_CATALOGUE_ORIGINS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--selection", default="maintenance/catalogue/fi_syke/official/catalogue.json")
    parser.add_argument("--input-receipt", type=Path, required=True)
    parser.add_argument("--build-inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.out.resolve()
    evidence_root = args.evidence_root.resolve(strict=True)
    if output.exists() or output.is_relative_to(evidence_root) or evidence_root.is_relative_to(output):
        raise FatalContractError("fi_syke catalogue output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("fi_syke catalogue output must stay outside source checkouts")
    receipt = RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

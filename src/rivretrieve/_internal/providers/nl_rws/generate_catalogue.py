"""Rijkswaterstaat DDAPI 2.0 catalogue maintenance : build(NativeTable x OriginDeclarations) -> GeneratedNlRwsCatalogue."""

from __future__ import annotations

import json
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
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations, validate_catalogue_origins
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
from rivretrieve._internal.providers.nl_rws.catalogue_series import (
    ADMITTED_PRODUCT_KEY_TO_ID,
    PRODUCT_DEFINITIONS,
)

PROVIDER_ID = ProviderId("nl_rws")
PROVIDER_NAME = "Rijkswaterstaat"

NATIVE_SOURCE_SCHEMA = pl.Schema(
    {
        "Code": pl.String,
        "Locatie_MessageID": pl.Int64,
        "Naam": pl.String,
        "Omschrijving": pl.String,
        "Coordinatenstelsel": pl.String,
        "Lat": pl.Float64,
        "Lon": pl.Float64,
    }
)
NATIVE_SCHEMA = pl.Schema({**NATIVE_SOURCE_SCHEMA, "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC")})

ASSOCIATION_SCHEMA = pl.Schema({"Code": pl.String, "product_id": pl.String})


@dataclass(frozen=True)
class GeneratedNlRwsCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    acquisition_provenance: AcquisitionProvenance


def _as_dict(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return None


def _nested_code(entry: dict[str, object], key: str) -> str:
    nested = _as_dict(entry.get(key))
    if nested is not None:
        code = nested.get("Code")
        if isinstance(code, str):
            return code
    return ""


def station_native_table(
    catalogus_doc: Mapping[str, object],
    *,
    retrieved_at: RetrievedAt,
) -> tuple[NativeTable, pl.DataFrame]:
    """Extract the in-scope OW meting station native table and deduplicated product links."""
    locs_raw = catalogus_doc.get("LocatieLijst")
    meta_raw = catalogus_doc.get("AquoMetadataLijst")
    xref_raw = catalogus_doc.get("AquoMetadataLocatieLijst")
    if not isinstance(locs_raw, list) or not isinstance(meta_raw, list) or not isinstance(xref_raw, list):
        raise FatalContractError("nl_rws OphalenCatalogus payload missing required list fields")

    # Map admitted AquoMetadata_MessageID -> product_id
    meta_to_product: dict[int, str] = {}
    for raw_entry in meta_raw:
        entry = _as_dict(raw_entry)
        if entry is None:
            continue
        if _nested_code(entry, "Compartiment") != "OW":
            continue
        if entry.get("ProcesType") != "meting":
            continue
        if _nested_code(entry, "Groepering") != "":
            continue
        key = (
            _nested_code(entry, "Grootheid"),
            _nested_code(entry, "Eenheid"),
            _nested_code(entry, "Hoedanigheid"),
            _nested_code(entry, "WaardeBewerkingsMethode"),
        )
        product_id = ADMITTED_PRODUCT_KEY_TO_ID.get(key)
        if product_id is None:
            continue
        mid = entry.get("AquoMetadata_MessageID")
        if not isinstance(mid, int) or isinstance(mid, bool):
            raise FatalContractError(f"nl_rws AquoMetadata entry has invalid AquoMetadata_MessageID: {mid!r}")
        meta_to_product[mid] = product_id

    # Validate all locations and index by Locatie_MessageID
    seen_codes: set[str] = set()
    loc_by_id: dict[int, dict[str, object]] = {}
    for raw_loc in locs_raw:
        loc = _as_dict(raw_loc)
        if loc is None:
            raise FatalContractError("nl_rws LocatieLijst entry must be a mapping")
        code = loc.get("Code")
        lid = loc.get("Locatie_MessageID")
        naam = loc.get("Naam")
        oms = loc.get("Omschrijving")
        crs = loc.get("Coordinatenstelsel")
        lat = loc.get("Lat")
        lon = loc.get("Lon")
        if not isinstance(code, str) or not code.strip():
            raise FatalContractError(f"nl_rws location has invalid Code: {code!r}")
        if code in seen_codes:
            raise FatalContractError(f"nl_rws LocatieLijst has duplicate Code: {code!r}")
        seen_codes.add(code)
        if not isinstance(lid, int) or isinstance(lid, bool):
            raise FatalContractError(f"nl_rws location {code!r} has invalid Locatie_MessageID: {lid!r}")
        if lid in loc_by_id:
            raise FatalContractError(f"nl_rws LocatieLijst has duplicate Locatie_MessageID: {lid!r}")
        if not isinstance(naam, str) or not naam.strip():
            raise FatalContractError(f"nl_rws location {code!r} has blank or invalid Naam: {naam!r}")
        if oms is not None and not isinstance(oms, str):
            raise FatalContractError(f"nl_rws location {code!r} has invalid Omschrijving: {oms!r}")
        if crs != "ETRS89":
            raise FatalContractError(
                f"nl_rws location {code!r} has unexpected Coordinatenstelsel (expected ETRS89): {crs!r}"
            )
        if (
            not isinstance(lat, (int, float))
            or not isinstance(lon, (int, float))
            or isinstance(lat, bool)
            or isinstance(lon, bool)
        ):
            raise FatalContractError(f"nl_rws location {code!r} has missing or non-numeric Lat/Lon")
        loc_by_id[lid] = {
            "Code": code,
            "Locatie_MessageID": lid,
            "Naam": naam,
            "Omschrijving": oms if oms is not None else "",
            "Coordinatenstelsel": crs,
            "Lat": float(lat),
            "Lon": float(lon),
        }

    # Resolve deduplicated (Code, product_id) pairs
    pairs: set[tuple[str, str]] = set()
    admitted_codes: set[str] = set()
    for raw_link in xref_raw:
        link = _as_dict(raw_link)
        if link is None:
            continue
        mid = link.get("AquoMetaData_MessageID")
        if mid is None:
            mid = link.get("AquoMetadata_MessageID")
        lid = link.get("Locatie_MessageID")
        if not isinstance(mid, int) or isinstance(mid, bool) or not isinstance(lid, int) or isinstance(lid, bool):
            continue
        product_id = meta_to_product.get(mid)
        if product_id is None:
            continue
        loc_row = loc_by_id.get(lid)
        if loc_row is None:
            continue
        code = str(loc_row["Code"])
        pairs.add((code, product_id))
        admitted_codes.add(code)

    native_rows = [row for row in loc_by_id.values() if row["Code"] in admitted_codes]
    if not native_rows:
        raise FatalContractError("nl_rws OphalenCatalogus produced no in-scope OW meting stations")

    source = pl.DataFrame(native_rows, schema=NATIVE_SOURCE_SCHEMA).sort("Code")
    associations = pl.DataFrame(
        [{"Code": code, "product_id": pid} for code, pid in sorted(pairs)],
        schema=ASSOCIATION_SCHEMA,
    )
    return stamp_native_table(source, retrieved_at), associations


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
            "station_id": row["Code"],
            "latitude": row["Lat"],
            "longitude": row["Lon"],
            "crs": "EPSG:4258",
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
    witnessed = {(row["Code"], row["product_id"]) for row in associations.iter_rows(named=True)}
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "station_id": station_id,
            "product_id": d.product_id,
            "availability": "available" if (station_id, d.product_id) in witnessed else "unknown",
            "availability_reason": None
            if (station_id, d.product_id) in witnessed
            else "Not linked in Rijkswaterstaat DDAPI 2.0 AquoMetadataLocatieLijst for this product",
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
    catalogue_date: date,
    *,
    license_text: str | None,
    citation_text: str | None,
) -> dict[str, object]:
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "none",
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
) -> GeneratedNlRwsCatalogue:
    """Assemble the official Netherlands Rijkswaterstaat (nl_rws) offline catalogue."""
    if native_table.data.schema != NATIVE_SCHEMA:
        raise FatalContractError("nl_rws native table does not have the exact required schema")
    if native_table.data.is_empty():
        raise FatalContractError("nl_rws native table must not be empty")
    products = build_products()
    stations = build_stations(native_table)
    origin_issues = validate_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    if origin_issues:
        raise FatalContractError(origin_issues[0].message, issues=origin_issues)
    station_products = build_station_products(
        station_ids=stations["station_id"].to_list(),
        associations=associations,
        catalogue_date=checked_on,
    )
    for frame, schema in (
        (products, PRODUCT_CATALOG_SCHEMA),
        (stations, STATION_CATALOG_SCHEMA),
        (station_products, STATION_PRODUCT_CATALOG_SCHEMA),
    ):
        validate_catalogue(frame, schema, on_issue="raise")
    if provenance is None or provenance.provider_id != "nl_rws":
        raise FatalContractError("Official nl_rws catalogue requires its selected acquisition provenance")
    statements = {
        statement.kind: statement.exact_text for source in provenance.source_records for statement in source.statements
    }
    provider_info = build_provider_info(
        checked_on,
        license_text=statements.get("license"),
        citation_text=statements.get("citation"),
    )
    from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components

    packaged_catalogue_artifact_from_components(
        provider_info,
        products,
        stations,
        station_products,
        acquisition_provenance=provenance,
        on_issue="raise",
    )
    return GeneratedNlRwsCatalogue(provider_info, products, stations, station_products, provenance)


def write_catalogue(
    catalogue: GeneratedNlRwsCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
) -> None:
    """Publish candidate runtime tables through the shared evidence-aware publication path."""
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.nl_rws.catalogue_series import describe_catalogue
    from rivretrieve._internal.providers.nl_rws.origins import (
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
    input_receipt: object | None = None,
) -> CatalogueSources:
    """Read retained nl_rws OphalenCatalogus and native.parquet inputs offline."""
    from datetime import UTC, datetime

    from rivretrieve._internal.acquisition_provenance import (
        AcquisitionRecord,
        FactBinding,
        NativeTableIdentity,
        RecordingReference,
        RetainedInputReceipt,
        SourceStatement,
    )
    from rivretrieve._internal.catalogues.inputs import verify_retained_input_files
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.nl_rws import origins

    catalogus_rel = "maintenance/catalogue/nl_rws/official/access/01b_catalogus_extended.json"
    receipts_rel = "maintenance/catalogue/nl_rws/official/access/acquisition-receipts.json"
    native_rel = "maintenance/catalogue/nl_rws/official/native.parquet"

    selected = {}
    if isinstance(input_receipt, RetainedInputReceipt):
        verify_retained_input_files(input_receipt, evidence_root)
        selected = {item.consumer_path: item for item in input_receipt.inputs}

    native_member = selected.get(native_rel)
    if native_member is not None:
        retained_native = read_native_table(
            evidence_root / native_rel,
            expected_sha256=native_member.sha256,
            expected_byte_size=native_member.byte_size,
        )
        native_rev = native_member.archive_revision
        native_sha = native_member.sha256
        native_size = native_member.byte_size
    else:
        retained_native = read_native_table(evidence_root / native_rel)
        native_rev = "983ebb162a4fa6064ec8bee56427fb7d4e0161d3"
        native_sha = "b9ea91a1285fdc1476592c75e4636f3bbb0ec5b215dc3c715155815ebf92dc0c"
        native_size = (evidence_root / native_rel).stat().st_size

    catalogus_bytes = (evidence_root / catalogus_rel).read_bytes()
    catalogus_doc = json.loads(catalogus_bytes)
    retrieved_at = retained_native.data["retrieved_at"][0]
    if not isinstance(retrieved_at, datetime):
        retrieved_at = datetime(2026, 11, 25, 13, 44, 26, tzinfo=UTC)
    native, associations = station_native_table(catalogus_doc, retrieved_at=RetrievedAt(retrieved_at))

    if not native.data.equals(retained_native.data):
        raise FatalContractError("nl_rws recomputed native table differs from its separately retained identity")

    provenance = origins.build_acquisition_provenance(
        NativeTableIdentity(
            location_kind="retained",
            repository_path=native_rel,
            revision=native_rev,
            sha256=native_sha,
            byte_size=native_size,
        ),
        (
            RecordingReference(
                recording_id="nl_rws_catalogus_extended",
                repository_path=catalogus_rel,
                source_url="https://ddapi20-waterwebservices.rijkswaterstaat.nl/METADATASERVICES/OphalenCatalogus",
                retrieved_at=retrieved_at,
                media_type="application/json",
                sha256="80db05e8f6fd3dbf5d2322e654b13a8e9e0c2b188e70a0731e37129559239919",
            ),
            RecordingReference(
                recording_id="nl_rws_terms_receipt",
                repository_path=receipts_rel,
                source_url="https://www.rijkswaterstaat.nl/copyright",
                retrieved_at=retrieved_at,
                media_type="application/json",
                sha256="f8022d9799e057c00b28ed0c818b5de9a828cbfc668489a822b1285808e47b28",
            ),
        ),
        acquisitions=(
            AcquisitionRecord(
                acquisition_id="nl_rws_catalogus_2026_11_25",
                method="http_request",
                instant_type="retrieval",
                description="Extended DDAPI 2.0 OphalenCatalogus snapshot (nl_rws-access-2026-11-25-v1)",
                requested_from=(
                    "https://ddapi20-waterwebservices.rijkswaterstaat.nl/METADATASERVICES/OphalenCatalogus",
                ),
                retrieved_at_start=retrieved_at,
                recording_ids=("nl_rws_catalogus_extended",),
            ),
            AcquisitionRecord(
                acquisition_id="nl_rws_terms_2026_11_25",
                method="http_request",
                instant_type="retrieval",
                description="Rijkswaterstaat open data licence (Public Domain Mark 1.0 / CC0 1.0) and recommended attribution",
                requested_from=("https://www.rijkswaterstaat.nl/copyright",),
                retrieved_at_start=retrieved_at,
                recording_ids=("nl_rws_terms_receipt",),
            ),
        ),
        source_bindings=(
            FactBinding(
                fact_group="nl_rws_catalogus_source",
                facts=(
                    "source.station.ophalen_catalogus_locations",
                    "source.station.etrs89_coordinates",
                    "source.product.aquo_metadata_catalogue",
                    "source.station_product.aquo_metadata_location_links",
                ),
                source_id="nl_rws",
                acquisition_id="nl_rws_catalogus_2026_11_25",
            ),
            FactBinding(
                fact_group="nl_rws_terms_source",
                facts=("source.provider.license", "source.provider.citation"),
                source_id="nl_rws",
                acquisition_id="nl_rws_terms_2026_11_25",
            ),
        ),
        statements=(
            SourceStatement(
                kind="license",
                exact_text="CC0-1.0",
                recording_id="nl_rws_terms_receipt",
                fact="source.provider.license",
            ),
            SourceStatement(
                kind="citation",
                exact_text="Bron: Rijkswaterstaat – Waterwebservices",
                recording_id="nl_rws_terms_receipt",
                fact="source.provider.citation",
            ),
        ),
    )
    return CatalogueSources(native, associations, date(2026, 11, 25), provenance)


def main(argv: list[str] | None = None) -> int:
    """Compose an offline official nl_rws catalogue candidate outside source checkouts."""
    import argparse

    from rivretrieve._internal.acquisition_provenance import RetainedInputReceipt
    from rivretrieve._internal.providers.nl_rws.origins import STATION_CATALOGUE_ORIGINS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--input-receipt", type=Path, default=None)
    parser.add_argument("--build-inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.out.resolve()
    evidence_root = args.evidence_root.resolve(strict=True)
    if (
        (output.exists() and any(output.iterdir()))
        or output.is_relative_to(evidence_root)
        or evidence_root.is_relative_to(output)
    ):
        raise FatalContractError("nl_rws catalogue output must be a new path separate from retained inputs")
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise FatalContractError("nl_rws catalogue output must stay outside source checkouts")
    receipt = (
        RetainedInputReceipt.model_validate_json(args.input_receipt.read_bytes())
        if args.input_receipt is not None
        else None
    )
    sources = read_catalogue_sources(evidence_root, input_receipt=receipt)
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

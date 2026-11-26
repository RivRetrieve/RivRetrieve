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

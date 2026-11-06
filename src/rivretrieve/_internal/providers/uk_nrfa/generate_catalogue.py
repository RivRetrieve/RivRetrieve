"""Build offline NRFA discovery tables from adopted station metadata."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
    verify_provenance_recordings,
)
from rivretrieve._internal.catalogue_origins import OriginDeclarations, enforce_catalogue_origins
from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, read_native_table, stamp_native_table
from rivretrieve._internal.catalogues.schemas import (
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    ProductCatalog,
    StationCatalog,
    StationProductCatalog,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.uk_nrfa.catalogue_series import PRODUCT_IDS


def build_stations(native_table: NativeTable) -> StationCatalog:
    return (
        native_table.data.select(
            pl.lit("uk_nrfa").alias("provider_id"),
            pl.col("station_id"),
            "latitude",
            "longitude",
            pl.lit("EPSG:4326").alias("crs"),
        )
        .cast(STATION_CATALOG_SCHEMA.polars_schema)
        .sort("station_id")
    )


def build_station_products(native_table: NativeTable) -> StationProductCatalog:
    rows = []
    for station in native_table.data.iter_rows(named=True):
        for summary in station["data-summary"]["data-types"]:
            product = summary["data-type"]
            if product in PRODUCT_IDS:
                rows.append(
                    {
                        "provider_id": "uk_nrfa",
                        "station_id": station["station_id"],
                        "product_id": product,
                        "availability": "available",
                        "availability_reason": "Advertised in the NRFA station-info data-summary snapshot",
                        "published_record_start_date": None,
                        "published_record_end_date": None,
                        "last_catalogue_check": station["retrieved_at"].date(),
                    }
                )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).sort("station_id", "product_id")


def prepare_native_table(
    station_info: dict[str, object], station_ids: dict[str, object], *, retrieved_at: RetrievedAt
) -> NativeTable:
    """Retain station-info fields after reconciling the separate UK station inventory.

    The altitude datum uses the published regional numbering convention only
    within this reconciled UK inventory. It does not define a stage datum.
    """
    rows = station_info.get("data")
    identities = station_ids.get("station-ids")
    if not isinstance(rows, list) or not rows or not isinstance(identities, list):
        raise FatalContractError("NRFA inventory responses require station rows and identifiers")
    if any(type(identity) is not int or identity < 0 for identity in identities):
        raise FatalContractError("NRFA inventory requires integer identifiers")
    if any(not isinstance(row, dict) for row in rows):
        raise FatalContractError("NRFA station row must be an object")
    station_rows = cast("list[dict[str, object]]", rows)
    source_ids = [row.get("id") for row in station_rows]
    if (
        any(type(identity) is not int for identity in source_ids)
        or len(set(source_ids)) != len(source_ids)
        or len(set(identities)) != len(identities)
        or set(source_ids) != set(identities)
    ):
        raise FatalContractError("NRFA station-info and station-ID inventory differ")
    prepared = []
    for row in station_rows:
        identity = str(row["id"])
        regional = identity.zfill(6)
        datum = None
        if len(regional) == 6:
            if regional[0] in {"0", "1"}:
                datum = "Ordnance Datum"
            elif regional[0] == "2":
                datum = "Malin Head"
        coordinates = row.get("lat-long")
        summary = row.get("data-summary")
        if not isinstance(coordinates, dict) or not isinstance(summary, dict):
            raise FatalContractError("NRFA station requires lat-long and data-summary objects")
        coordinates = cast("dict[str, object]", coordinates)
        summary = cast("dict[str, object]", summary)
        if not isinstance(summary.get("data-types"), list):
            raise FatalContractError("NRFA data-summary requires a data-types list")
        prepared.append(
            {
                **row,
                "station_id": identity,
                "latitude": coordinates.get("latitude"),
                "longitude": coordinates.get("longitude"),
                "station_altitude_datum": datum,
            }
        )
    data = (
        pl.DataFrame(prepared, infer_schema_length=None)
        .with_columns(
            pl.col("station_altitude_datum").cast(pl.String),
        )
        .sort("station_id")
    )
    original_by_id = {str(row["id"]): row for row in station_rows}
    for retained in data.iter_rows(named=True):
        original = original_by_id[retained["station_id"]]
        if not _same_source_value(original, {key: retained[key] for key in original}):
            raise FatalContractError("NRFA native table cannot preserve source scalar types")
    return stamp_native_table(data, retrieved_at)


def _same_source_value(original: object, retained: object) -> bool:
    if type(original) is not type(retained):
        return False
    if isinstance(original, dict) and isinstance(retained, dict):
        original = cast("dict[str, object]", original)
        retained = cast("dict[str, object]", retained)
        return original.keys() == retained.keys() and all(
            _same_source_value(value, retained[key]) for key, value in original.items()
        )
    if isinstance(original, list) and isinstance(retained, list):
        return len(original) == len(retained) and all(
            _same_source_value(left, right) for left, right in zip(original, retained, strict=True)
        )
    return original == retained


def build_products() -> ProductCatalog:
    from rivretrieve._internal.catalogues.products import product_row
    from rivretrieve._internal.catalogues.schemas import PRODUCT_CATALOG_SCHEMA
    from rivretrieve._internal.providers.uk_nrfa.catalogue_series import product_facts

    return pl.DataFrame(
        [product_row("uk_nrfa", product, product, facts) for product, facts in product_facts().items()],
        schema=PRODUCT_CATALOG_SCHEMA.polars_schema,
    ).sort("product_id")


@dataclass(frozen=True)
class GeneratedNrfaCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    acquisition_provenance: AcquisitionProvenance


def build_catalogue(native_table: NativeTable, origins: OriginDeclarations) -> GeneratedNrfaCatalogue:
    from rivretrieve._internal.providers.uk_nrfa.origins import build_acquisition_provenance

    if native_table.data.is_empty():
        raise FatalContractError("NRFA native inventory must not be empty")
    stations = build_stations(native_table)
    enforce_catalogue_origins(ProviderId("uk_nrfa"), origins, native_table, stations)
    checked_at = native_table.data["retrieved_at"].max()
    if not isinstance(checked_at, datetime):
        raise FatalContractError("NRFA native inventory requires retrieval instants")
    provider_info: dict[str, object] = {
        "provider_id": "uk_nrfa",
        "name": "UK National River Flow Archive (UK Centre for Ecology & Hydrology)",
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "false: catalogue-only; observation retrieval is not implemented",
        "catalogue_version": checked_at.date().isoformat(),
        "license": "https://eidc.ceh.ac.uk/licences/nrfa-data-terms-and-conditions-for-api-access-to-time-series-data-and-metadata/",
        "citation": "Data from the UK National River Flow Archive",
    }
    products = build_products()
    station_products = build_station_products(native_table)
    provenance = build_acquisition_provenance()
    packaged_catalogue_artifact_from_components(
        provider_info,
        products,
        stations,
        station_products,
        acquisition_provenance=provenance,
        on_issue="raise",
    )
    return GeneratedNrfaCatalogue(provider_info, products, stations, station_products, provenance)


def write_catalogue(
    catalogue: GeneratedNrfaCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs,
    native_table: NativeTable,
) -> None:
    from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.uk_nrfa.catalogue_series import describe_catalogue
    from rivretrieve._internal.providers.uk_nrfa.origins import (
        STATION_CATALOGUE_ORIGINS,
        STATION_METADATA_FIELDS,
        STATION_METADATA_NOTICE,
    )

    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "provider.json").write_text(json.dumps(catalogue.provider_info, sort_keys=True) + "\n")
    catalogue.products.write_parquet(output / "products.parquet")
    catalogue.stations.write_parquet(output / "stations.parquet")
    catalogue.station_products.write_parquet(output / "station_products.parquet")
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (STATION_CATALOGUE_ORIGINS,),
        {name: (output / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES},
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=STATION_METADATA_FIELDS,
        station_metadata_notice=STATION_METADATA_NOTICE,
        source_describer=describe_catalogue,
    )
    for name, content in metadata.items():
        (output / name).write_bytes(content)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the offline NRFA catalogue from selected private inputs.")
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--build-inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    from rivretrieve._internal.providers.uk_nrfa.origins import (
        NATIVE_TABLE_BYTE_SIZE,
        NATIVE_TABLE_SHA256,
        STATION_CATALOGUE_ORIGINS,
        build_acquisition_provenance,
    )

    build_inputs = CatalogueBuildInputs.model_validate_json(args.build_inputs.read_bytes())
    provenance = build_acquisition_provenance()
    verify_provenance_recordings(provenance, args.evidence_root)
    native = read_native_table(
        args.native, expected_sha256=NATIVE_TABLE_SHA256, expected_byte_size=NATIVE_TABLE_BYTE_SIZE
    )
    catalogue = build_catalogue(native, STATION_CATALOGUE_ORIGINS)
    write_catalogue(catalogue, args.out, build_inputs=build_inputs, native_table=native)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

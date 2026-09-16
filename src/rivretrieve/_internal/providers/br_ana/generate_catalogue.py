"""Brazil catalogue : NativeTable × OriginDeclarations × AcquisitionProvenance → GeneratedBrAnaCatalogue."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance, verified_provider_terms
from rivretrieve._internal.catalogue_origins import OriginDeclarations, enforce_catalogue_origins
from rivretrieve._internal.catalogues.artifact import (
    PackagedCatalogArtifact,
    packaged_catalogue_artifact_from_components,
)
from rivretrieve._internal.catalogues.native import NativeTable
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    ProductCatalog,
    StationCatalog,
    StationProductCatalog,
    validate_catalogue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId

PROVIDER_ID = ProviderId("br_ana")
PROVIDER_NAME = "ANA Hidroweb — Brazilian National Water and Sanitation Agency"
_MIGRATION = "br_ana legacy catalogue generation is retired; use --native with an attested inventory capture record"


@dataclass(frozen=True, slots=True)
class GeneratedBrAnaCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    acquisition_provenance: AcquisitionProvenance
    public_artifact: PackagedCatalogArtifact
    origins: OriginDeclarations
    acquired_station_count: int
    pluviometric_station_count: int


def project_stations(native_table: NativeTable) -> NativeTable:
    """Select the river-gauge scope without altering the retained acquired inventory."""
    data = native_table.data
    if "Tipo_Estacao" not in data.columns:
        raise FatalContractError("br_ana native inventory lacks Tipo_Estacao")
    kinds = data["Tipo_Estacao"]
    if kinds.dtype != pl.String or kinds.null_count() or not set(kinds.to_list()) <= {"Fluviometrica", "Pluviometrica"}:
        raise FatalContractError("br_ana native inventory has an unexpected Tipo_Estacao")
    return NativeTable(data.filter(pl.col("Tipo_Estacao") == "Fluviometrica"))


def build_stations(native_table: NativeTable) -> StationCatalog:
    projected = project_stations(native_table)
    try:
        return projected.data.select(
            pl.lit(PROVIDER_ID).cast(pl.String).alias("provider_id"),
            pl.col("codigoestacao").cast(pl.String, strict=True).alias("station_id"),
            pl.col("Latitude").cast(pl.Float64, strict=True).alias("latitude"),
            pl.col("Longitude").cast(pl.Float64, strict=True).alias("longitude"),
            pl.lit("unknown").cast(pl.String).alias("crs"),
        ).sort("station_id")
    except pl.exceptions.PolarsError as exc:
        raise FatalContractError("br_ana native station identity or coordinates are invalid") from exc


def build_catalogue(
    native_table: NativeTable, origins: OriginDeclarations, provenance: AcquisitionProvenance
) -> GeneratedBrAnaCatalogue:
    """Build only evidenced station identity and geometry; product semantics remain withheld."""
    projected = project_stations(native_table)
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, projected, stations)
    maximum = native_table.data["retrieved_at"].max()
    if not isinstance(maximum, datetime):
        raise FatalContractError("br_ana native inventory has no retrieval instant")
    terms = verified_provider_terms(provenance.source_records, provenance.fact_bindings, provenance.withheld_facts)
    provider_info: dict[str, object] = {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": "false: catalogue-only; observation product semantics remain withheld",
        "catalogue_version": maximum.date().isoformat(),
        "license": terms.get("license"),
        "citation": terms.get("citation"),
    }
    products = pl.DataFrame(schema=PRODUCT_CATALOG_SCHEMA.polars_schema)
    station_products = pl.DataFrame(schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema)
    for frame, schema in (
        (
            pl.DataFrame([provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema),
            PROVIDER_INFO_CATALOG_SCHEMA,
        ),
        (stations, STATION_CATALOG_SCHEMA),
        (products, PRODUCT_CATALOG_SCHEMA),
        (station_products, STATION_PRODUCT_CATALOG_SCHEMA),
    ):
        validate_catalogue(frame, schema, on_issue="raise")
    artifact = packaged_catalogue_artifact_from_components(
        provider_info, products, stations, station_products, acquisition_provenance=provenance, on_issue="raise"
    )
    return GeneratedBrAnaCatalogue(
        provider_info,
        products,
        stations,
        station_products,
        provenance,
        artifact,
        origins,
        native_table.data.height,
        native_table.data.height - projected.data.height,
    )


def generate_catalogue_from_fixture(
    fixture_path: Path | str, *, catalogue_date: date | None = None
) -> GeneratedBrAnaCatalogue:
    raise FatalContractError(_MIGRATION)


def generate_catalogue_from_live(
    *, catalogue_date: date | None = None, username: str | None = None, password: str | None = None
) -> GeneratedBrAnaCatalogue:
    raise FatalContractError(_MIGRATION)


def generate_catalogue(
    raw_payload: list[dict[str, object]], *, catalogue_date: date | None = None, generator_input: str = "fixture"
) -> GeneratedBrAnaCatalogue:
    raise FatalContractError(_MIGRATION)


def write_catalogue(catalogue: GeneratedBrAnaCatalogue, out_dir: Path) -> None:
    from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata

    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = catalogue.public_artifact
    (out_dir / "provider.json").write_text(
        json.dumps(artifact.provider_info, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    artifact.products.write_parquet(out_dir / "products.parquet")
    artifact.stations.write_parquet(out_dir / "stations.parquet")
    artifact.station_products.write_parquet(out_dir / "station_products.parquet")
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (catalogue.origins,),
        {name: (out_dir / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES},
    )
    for name, content in metadata.items():
        (out_dir / name).write_bytes(content)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the ANA catalogue offline from its attested native inventory.", allow_abbrev=False
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--native", type=Path)
    source.add_argument("--materialize-record", type=Path)
    source.add_argument("--fixture", type=Path)
    source.add_argument("--live", action="store_true")
    source.add_argument("--withhold-uncertified", action="store_true")
    parser.add_argument("--catalogue-date", type=date.fromisoformat)
    parser.add_argument("--capture-record", type=Path)
    parser.add_argument("--native-out", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.native is None and args.materialize_record is None:
        raise FatalContractError(_MIGRATION)
    if args.materialize_record is not None:
        from rivretrieve._internal.catalogues.native import write_native_table
        from rivretrieve._internal.providers.br_ana.capture import (
            materialize_captured_native_table,
            read_capture_record,
        )

        if args.native_out is None or args.out is not None or args.capture_record is not None:
            parser.error("--materialize-record requires --native-out and cannot use --out or --capture-record")
        capture = read_capture_record(args.materialize_record)
        native = materialize_captured_native_table(capture, args.repository_root)
        write_native_table(native, args.native_out)
        return 0
    if args.out is None or args.native_out is not None:
        parser.error("--native requires --out and cannot use --native-out")
    from rivretrieve._internal.catalogues.native import read_native_table
    from rivretrieve._internal.providers.br_ana.capture import read_capture_record, verify_native_identity
    from rivretrieve._internal.providers.br_ana.origins import STATION_CATALOGUE_ORIGINS, build_acquisition_provenance

    capture_path = args.capture_record or Path("tests/test_data/br_ana_inventory/capture.json")
    capture = read_capture_record(capture_path)
    native = read_native_table(
        args.native,
        expected_sha256=capture.native_table.sha256,
        expected_byte_size=capture.native_table.byte_size,
    )
    verify_native_identity(capture, args.native.read_bytes(), native)
    catalogue = build_catalogue(native, STATION_CATALOGUE_ORIGINS, build_acquisition_provenance(capture))
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

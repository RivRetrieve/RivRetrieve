"""Czech catalogue maintenance : refresh(ChmiMetadataEnvelope, RetrievedAt) → WithIssues[NativeTable]; build(NativeTable, OriginDeclarations) → GeneratedCzChmiCatalogue."""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
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
from rivretrieve._internal.catalogues.native import (
    NativeTable,
    RetrievedAt,
    read_native_table,
    stamp_native_table,
    write_native_table,
)
from rivretrieve._internal.catalogues.products import product_row
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    AvailabilityDtype,
    ProductCatalog,
    StationCatalog,
    StationProductCatalog,
    validate_catalogue,
)
from rivretrieve._internal.engine import WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.cz_chmi.config import SERIES_MAPPINGS, CzChmiSourceCoordinates
from rivretrieve._internal.providers.cz_chmi.config import config as source_config
from rivretrieve._internal.providers.cz_chmi.origins import (
    NATIVE_TABLE_BYTE_SIZE,
    NATIVE_TABLE_SHA256,
    build_acquisition_provenance,
)

PROVIDER_ID = ProviderId("cz_chmi")
PROVIDER_NAME = "Czech Hydrometeorological Institute (CHMI) Open Data"
METADATA_URL = "https://opendata.chmi.cz/hydrology/historical/metadata/meta1.json"
AVAILABILITY_REASON = "CHMI metadata catalogue does not expose per-variable station availability"
SOURCE_COLUMNS = (
    "objID",
    "DBC",
    "STATION_NAME",
    "STREAM_NAME",
    "GEOGR1",
    "GEOGR2",
    "SPA_TYP",
    "SPAH_DS",
    "SPAH_UNIT",
    "DRYH",
    "SPA1H",
    "SPA2H",
    "SPA3H",
    "SPA4H",
    "SPAQ_DS",
    "SPAQ_UNIT",
    "DRYQ",
    "SPA1Q",
    "SPA2Q",
    "SPA3Q",
    "SPA4Q",
    "PLO_STA",
    "HLGP4",
)
NUMERIC_COLUMNS = (
    "GEOGR1",
    "GEOGR2",
    "DRYH",
    "SPA1H",
    "SPA2H",
    "SPA3H",
    "SPA4H",
    "DRYQ",
    "SPA1Q",
    "SPA2Q",
    "SPA3Q",
    "SPA4Q",
    "PLO_STA",
)


@dataclass(frozen=True)
class GeneratedCzChmiCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    acquisition_provenance: AcquisitionProvenance


def refresh_native_table(
    payload: dict[str, object],
    *,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    rows = _extract_stations(payload)
    try:
        source_rows = (
            pl.DataFrame(rows, infer_schema_length=None)
            .select(SOURCE_COLUMNS)
            .with_columns(pl.col(column).cast(pl.Float64) for column in NUMERIC_COLUMNS)
            .sort("objID")
        )
    except pl.exceptions.PolarsError as exc:
        raise FatalContractError("cz_chmi metadata contains values incompatible with the native schema") from exc
    return WithIssues(value=stamp_native_table(source_rows, retrieved_at), issues=())


def refresh_native_table_from_fixture(
    fixture_path: Path | str,
    *,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    return refresh_native_table(
        _read_fixture_json(Path(fixture_path)),
        retrieved_at=retrieved_at,
    )


def refresh_native_table_from_live(*, retrieved_at: RetrievedAt) -> WithIssues[NativeTable]:
    return refresh_native_table(_read_live_json(METADATA_URL), retrieved_at=retrieved_at)


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
) -> GeneratedCzChmiCatalogue:
    if native_table.data.is_empty():
        raise FatalContractError("Czech native table must not be empty")
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("Czech native table has no valid retrieved_at values")
    station_dates = native_table.data.select(
        pl.col("objID").alias("station_id"),
        pl.col("retrieved_at").dt.date().alias("retrieved_date"),
    )
    station_products = build_station_products(station_dates)
    provider_info = build_provider_info(maximum_retrieved_at.date())

    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedCzChmiCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=station_products,
        acquisition_provenance=build_acquisition_provenance(),
    )


def build_products() -> ProductCatalog:
    rows = []
    for product_id, declared in source_config().products.items():
        coordinates = declared.coordinates.value
        if not isinstance(coordinates, CzChmiSourceCoordinates):
            raise FatalContractError("cz_chmi product has invalid source coordinates")
        rows.append(
            product_row(
                str(PROVIDER_ID),
                str(product_id),
                str(coordinates.ts_con_id),
                SERIES_MAPPINGS[product_id].physical_facts(),
            )
        )
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(native_table: NativeTable) -> StationCatalog:
    rows = [
        _native_station_row(item, row_number=row_number)
        for row_number, item in enumerate(native_table.data.iter_rows(named=True), start=1)
    ]
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(station_dates: pl.DataFrame) -> StationProductCatalog:
    rows: list[dict[str, object]] = []
    for station_id, retrieved_date in station_dates.iter_rows():
        if not isinstance(station_id, str):
            raise FatalContractError("cz_chmi station retrieval date has an invalid identifier")
        if not isinstance(retrieved_date, date):
            raise FatalContractError(f"cz_chmi station {station_id} retrieval date is invalid")
        for product_id in SERIES_MAPPINGS:
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": product_id,
                    "availability": "unknown",
                    "availability_reason": AVAILABILITY_REASON,
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": retrieved_date,
                }
            )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(AvailabilityDtype)
    )


def build_provider_info(
    catalogue_date: date,
) -> dict[str, object]:
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "false: live annual JSON requests coalesced by station, year, and DQ/HQ file family; "
            "non-success HTTP responses fail the source contract"
        ),
        "catalogue_version": catalogue_date.isoformat(),
        "license": None,
        "citation": None,
    }


def validate_generated_catalogue(
    provider_info: dict[str, object],
    products: ProductCatalog,
    stations: StationCatalog,
    station_products: StationProductCatalog,
) -> None:
    provider_info_df = pl.DataFrame([provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
    validate_catalogue(provider_info_df, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    packaged_catalogue_artifact_from_components(
        provider_info,
        products,
        stations,
        station_products,
        acquisition_provenance=build_acquisition_provenance(),
        on_issue="raise",
    )


def write_catalogue(
    catalogue: GeneratedCzChmiCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs | None = None,
    native_table: NativeTable | None = None,
) -> None:
    """Write a catalogue using adopted build inputs and its verified native table."""
    from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.cz_chmi.origins import (
        STATION_CATALOGUE_ORIGINS,
        STATION_METADATA_FIELDS,
        STATION_METADATA_NOTICE,
        TRANSFORMATION_IMPLEMENTATIONS,
    )

    if build_inputs is None or native_table is None:
        raise FatalContractError("Catalogue publication requires explicit build_inputs and native_table")

    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as file:
        json.dump(catalogue.provider_info, file, sort_keys=True, separators=(",", ":"))
        file.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (STATION_CATALOGUE_ORIGINS,),
        {name: (output_path / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES},
        source_config=source_config(),
        source_mappings=SERIES_MAPPINGS,
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=STATION_METADATA_FIELDS,
        station_metadata_notice=STATION_METADATA_NOTICE,
        transformation_implementations=TRANSFORMATION_IMPLEMENTATIONS,
    )
    for name, content in metadata.items():
        (output_path / name).write_bytes(content)


def _extract_stations(raw_metadata: dict[str, object]) -> list[dict[str, object]]:
    try:
        envelope_values = [
            raw_metadata["zaznamID"],
            raw_metadata["datovyZdrojID"],
            raw_metadata["datovyTokID"],
            raw_metadata["datumVytvoreni"],
            raw_metadata["verzeDat"],
        ]
        data = raw_metadata["data"]
        if not isinstance(data, dict):
            raise FatalContractError("cz_chmi metadata: 'data' must be an object")
        data_object = cast("dict[str, object]", data)
        data_type = data_object["type"]
        nested_data = data_object["data"]
        if not isinstance(nested_data, dict):
            raise FatalContractError("cz_chmi metadata: 'data.data' must be an object")
        data_block = cast("dict[str, object]", nested_data)
        header = data_block["header"]
        values = data_block["values"]
    except KeyError as exc:
        raise FatalContractError(f"cz_chmi metadata missing required key: {exc}") from exc

    if not all(isinstance(value, str) for value in envelope_values):
        raise FatalContractError("cz_chmi metadata envelope fields must be strings")
    if not isinstance(data_type, str):
        raise FatalContractError("cz_chmi metadata: 'data.type' must be a string")
    if not isinstance(header, str):
        raise FatalContractError("cz_chmi metadata: 'header' must be a string")
    if tuple(header.split(",")) != SOURCE_COLUMNS:
        raise FatalContractError("cz_chmi metadata header does not match the required source header")
    if not isinstance(values, list):
        raise FatalContractError("cz_chmi metadata: 'values' must be a list")

    station_rows: list[dict[str, object]] = []
    for row_number, row in enumerate(values, start=1):
        if not isinstance(row, list):
            raise FatalContractError(f"cz_chmi metadata row {row_number} must be a list")
        if len(row) != len(SOURCE_COLUMNS):
            raise FatalContractError(
                f"cz_chmi metadata row {row_number} has {len(row)} values; expected {len(SOURCE_COLUMNS)}"
            )
        station_id = row[0]
        if not isinstance(station_id, str) or not station_id.strip():
            raise FatalContractError(f"cz_chmi metadata row {row_number} has an invalid objID")
        station_rows.append(dict(zip(SOURCE_COLUMNS, row, strict=True)))
    return station_rows


def _native_station_row(item: dict[str, object], *, row_number: int) -> dict[str, object]:
    station_id = item.get("objID")
    if not isinstance(station_id, str) or not station_id.strip():
        raise FatalContractError(f"cz_chmi native station row {row_number} has an invalid objID")

    latitude = _required_native_coordinate(item.get("GEOGR1"), station_id, "latitude")
    longitude = _required_native_coordinate(item.get("GEOGR2"), station_id, "longitude")

    return {
        "provider_id": PROVIDER_ID,
        "station_id": station_id,
        "latitude": latitude,
        "longitude": longitude,
        "crs": "unknown",
    }


def _read_fixture_json(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as file:
            value = json.load(file)
    except OSError as exc:
        raise FatalContractError(f"Unable to read cz_chmi metadata fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"cz_chmi metadata fixture is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FatalContractError("cz_chmi metadata fixture must contain a JSON object")
    return cast("dict[str, object]", value)


def _read_live_json(url: str) -> dict[str, object]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status < 200 or response.status >= 300:
                raise FatalContractError(f"cz_chmi metadata live request failed with HTTP {response.status}")
            value = json.load(response)
    except OSError as exc:
        raise FatalContractError("cz_chmi metadata live request failed") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError("cz_chmi metadata live response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise FatalContractError("cz_chmi metadata live response must contain a JSON object")
    return cast("dict[str, object]", value)


def _required_native_coordinate(value: object, station_id: str, label: str) -> float:
    if value is None:
        raise FatalContractError(f"cz_chmi native station {station_id} has missing or null {label}")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise FatalContractError(f"cz_chmi native station {station_id} has non-numeric {label}")
    return float(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh or build the packaged cz_chmi catalogue.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to a CHMI metadata JSON fixture.")
    source.add_argument("--live", action="store_true", help="Fetch the live CHMI metadata endpoint.")
    source.add_argument("--native", type=Path, help="Path to the retained native Parquet table.")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--out", type=Path, help="Output directory for provider.json and parquet files.")
    destination.add_argument("--native-out", type=Path, help="Output path for the native Parquet table.")
    parser.add_argument("--retrieved-at", type=lambda value: RetrievedAt(datetime.fromisoformat(value)))
    parser.add_argument("--evidence-root", type=Path, help="External root for retained provenance inputs.")
    parser.add_argument("--build-inputs", type=Path, help="Reviewed adopted catalogue build inputs JSON.")
    args = parser.parse_args(argv)

    if args.native_out is not None:
        if args.native is not None:
            parser.error("--native cannot be used with --native-out")
        if args.retrieved_at is None:
            parser.error("--retrieved-at is required with --native-out")
        if args.live:
            native_outcome = refresh_native_table_from_live(retrieved_at=args.retrieved_at)
        else:
            native_outcome = refresh_native_table_from_fixture(args.fixture, retrieved_at=args.retrieved_at)
        write_native_table(native_outcome.value, args.native_out)
        return 0

    if args.native is None:
        parser.error("--out requires --native")
    if args.retrieved_at is not None:
        parser.error("--retrieved-at is only valid with refresh mode")
    from rivretrieve._internal.providers.cz_chmi.origins import STATION_CATALOGUE_ORIGINS

    if args.evidence_root is None:
        parser.error("--out requires --evidence-root")
    if args.build_inputs is None:
        parser.error("--out requires --build-inputs")
    build_inputs = CatalogueBuildInputs.model_validate_json(args.build_inputs.read_bytes())
    provenance = build_acquisition_provenance()
    verify_provenance_recordings(provenance, args.evidence_root)
    native_table = read_native_table(
        args.native,
        expected_sha256=NATIVE_TABLE_SHA256,
        expected_byte_size=NATIVE_TABLE_BYTE_SIZE,
    )
    write_catalogue(
        build_catalogue(
            native_table,
            STATION_CATALOGUE_ORIGINS,
        ),
        args.out,
        build_inputs=build_inputs,
        native_table=native_table,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

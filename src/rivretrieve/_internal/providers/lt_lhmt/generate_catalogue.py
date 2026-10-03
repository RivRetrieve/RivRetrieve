"""Lithuania catalogue maintenance : refresh(MeteoLtStations, RetrievedAt) → WithIssues[NativeTable]; build(NativeTable, OriginDeclarations) → GeneratedLtLhmtCatalogue."""

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
from rivretrieve._internal.providers.lt_lhmt.config import SERIES_MAPPINGS, LtLhmtSourceCoordinates
from rivretrieve._internal.providers.lt_lhmt.config import config as source_config
from rivretrieve._internal.providers.lt_lhmt.origins import (
    NATIVE_TABLE_BYTE_SIZE,
    NATIVE_TABLE_SHA256,
    build_acquisition_provenance,
)

PROVIDER_ID = ProviderId("lt_lhmt")
PROVIDER_NAME = "Lithuanian Hydrometeorological Service LHMT (Meteo.lt)"
METADATA_URL = "https://api.meteo.lt/v1/hydro-stations"
AVAILABILITY_REASON = "Meteo.lt hydro-stations catalogue does not expose per-variable station availability"


@dataclass(frozen=True)
class GeneratedLtLhmtCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    acquisition_provenance: AcquisitionProvenance


def refresh_native_table(
    raw_stations: list[object],
    *,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    rows: list[dict[str, object]] = []
    for item in raw_stations:
        _validate_native_station_entry(item)
        if not isinstance(item, dict):
            raise FatalContractError("Station entry must be a JSON object")
        rows.append(dict(cast("dict[str, object]", item)))
    source_rows = pl.DataFrame(rows, infer_schema_length=None).sort("code")
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
) -> GeneratedLtLhmtCatalogue:
    if native_table.data.is_empty():
        raise FatalContractError("Lithuania native table must not be empty")
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    station_dates = native_table.data.select(
        pl.col("code").alias("station_id"),
        pl.col("retrieved_at").dt.date().alias("retrieved_date"),
    )
    station_products = build_station_products(station_dates)
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("Lithuania native table has no valid retrieved_at values")
    provider_info = build_provider_info(maximum_retrieved_at.date())

    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedLtLhmtCatalogue(
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
        if not isinstance(coordinates, LtLhmtSourceCoordinates):
            raise FatalContractError("lt_lhmt product has invalid source coordinates")
        rows.append(
            product_row(
                str(PROVIDER_ID),
                str(product_id),
                str(coordinates.native_field),
                SERIES_MAPPINGS[product_id].physical_facts(),
            )
        )
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(native_table: NativeTable) -> StationCatalog:
    rows = []
    for station in native_table.data.iter_rows(named=True):
        code = station["code"]
        coordinates = station["coordinates"]
        if not isinstance(code, str) or not isinstance(coordinates, dict):
            raise FatalContractError("Lithuania native table contains an invalid station row")
        rows.append(
            {
                "provider_id": PROVIDER_ID,
                "station_id": code,
                "latitude": coordinates["latitude"],
                "longitude": coordinates["longitude"],
                "crs": "EPSG:4326",
            }
        )
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(station_dates: pl.DataFrame) -> StationProductCatalog:
    rows = []
    for station_id, retrieved_date in station_dates.iter_rows():
        if not isinstance(station_id, str) or not isinstance(retrieved_date, date):
            raise FatalContractError("station retrieval date must pair a string identifier with a date")
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
            "true: monthly station-window requests; co-published products share one source call; "
            "404 and retry exhaustion reported as recoverable issues"
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
    catalogue: GeneratedLtLhmtCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs | None = None,
    native_table: NativeTable | None = None,
) -> None:
    """Write a catalogue using adopted build inputs and its verified native table."""
    from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.lt_lhmt.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

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
    )
    for name, content in metadata.items():
        (output_path / name).write_bytes(content)


def _validate_native_station_entry(item: object) -> None:
    if not isinstance(item, dict):
        raise FatalContractError("Station entry must be a JSON object")
    station = cast("dict[str, object]", item)

    code = station.get("code")
    if not isinstance(code, str) or not code.strip():
        raise FatalContractError(f"Station entry missing required string field 'code': {station}")
    station_id = code.strip()

    coords = station.get("coordinates")
    if not isinstance(coords, dict):
        raise FatalContractError(f"Station {station_id} missing coordinates object")
    coords_data = cast("dict[str, object]", coords)
    _required_float(coords_data.get("latitude"), f"Station {station_id} latitude")
    _required_float(coords_data.get("longitude"), f"Station {station_id} longitude")


def _read_fixture_json(path: Path) -> list[object]:
    try:
        with path.open(encoding="utf-8") as file:
            value = json.load(file)
    except OSError as exc:
        raise FatalContractError(f"Unable to read Lithuania metadata fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"Lithuania metadata fixture is not valid JSON: {path}") from exc
    if not isinstance(value, list):
        raise FatalContractError("Lithuania metadata fixture must contain a JSON array")
    return cast("list[object]", value)


def _read_live_json(url: str) -> list[object]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status < 200 or response.status >= 300:
                raise FatalContractError(f"Lithuania metadata live request failed with HTTP {response.status}")
            value = json.load(response)
    except OSError as exc:
        raise FatalContractError("Lithuania metadata live request failed") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError("Lithuania metadata live response is not valid JSON") from exc
    if not isinstance(value, list):
        raise FatalContractError("Lithuania metadata live response must contain a JSON array")
    return cast("list[object]", value)


def _required_float(value: object, name: str) -> float:
    if isinstance(value, int | float):
        return float(value)
    raise FatalContractError(f"{name} is required and must be numeric")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged lt_lhmt catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to a Meteo.lt hydro-stations JSON fixture.")
    source.add_argument("--live", action="store_true", help="Fetch the live Meteo.lt hydro-stations endpoint.")
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
    from rivretrieve._internal.providers.lt_lhmt.origins import STATION_CATALOGUE_ORIGINS

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
    catalogue = build_catalogue(
        native_table,
        STATION_CATALOGUE_ORIGINS,
    )
    write_catalogue(catalogue, args.out, build_inputs=build_inputs, native_table=native_table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

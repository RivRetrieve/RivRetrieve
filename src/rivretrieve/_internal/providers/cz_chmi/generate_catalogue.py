"""Czech catalogue maintenance : refresh(ChmiMetadataEnvelope, RetrievedAt) → WithIssues[NativeTable]; existing catalogue generation remains operational."""

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

from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table, write_native_table
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
from rivretrieve._internal.providers.cz_chmi.metadata import (
    CzChmiProductMetadata,
    CzChmiStationProductMetadata,
)

PROVIDER_ID = "cz_chmi"
PROVIDER_NAME = "Czech Hydrometeorological Institute (CHMI) Open Data"
METADATA_URL = "https://opendata.chmi.cz/hydrology/historical/metadata/meta1.json"
AVAILABILITY_REASON = "CHMI metadata catalogue does not expose per-variable station availability"
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"
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


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    frequency: str
    statistic: str
    period_type: str
    period_anchor: str
    canonical_unit: str
    ts_con_id: str
    url_type: str
    native_unit: str
    unit_conversion: str | None
    notes: str | None

    @property
    def metadata(self) -> CzChmiProductMetadata:
        return CzChmiProductMetadata(
            ts_con_id=self.ts_con_id,
            url_type=self.url_type,
            native_unit=self.native_unit,
            canonical_unit=self.canonical_unit,
            unit_conversion=self.unit_conversion,
            notes=self.notes,
        )


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        product_id="discharge_daily_mean",
        observed_property="discharge",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        ts_con_id="QD",
        url_type="daily",
        native_unit="m3/s",
        unit_conversion=None,
        notes="Daily mean discharge from CHMI daily DQ file (tsConID=QD). Native unit is m3/s.",
    ),
    ProductDefinition(
        product_id="stage_daily_mean",
        observed_property="stage",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m",
        ts_con_id="HD",
        url_type="daily",
        native_unit="cm",
        unit_conversion="divide_by_100",
        notes="Daily mean stage from CHMI daily DQ file (tsConID=HD). Native unit is centimetres; converted to metres.",
    ),
    ProductDefinition(
        product_id="water_temperature_daily_mean",
        observed_property="water_temperature",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="degC",
        ts_con_id="TD",
        url_type="daily",
        native_unit="degC",
        unit_conversion=None,
        notes="Daily mean water temperature from CHMI daily DQ file (tsConID=TD). Native unit is degrees Celsius.",
    ),
    ProductDefinition(
        product_id="discharge_instantaneous",
        observed_property="discharge",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m3/s",
        ts_con_id="QH",
        url_type="hourly",
        native_unit="m3/s",
        unit_conversion=None,
        notes="Hourly instantaneous discharge from CHMI hourly HQ file (tsConID=QH). Native unit is m3/s.",
    ),
    ProductDefinition(
        product_id="stage_instantaneous",
        observed_property="stage",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m",
        ts_con_id="HH",
        url_type="hourly",
        native_unit="cm",
        unit_conversion="divide_by_100",
        notes="Hourly instantaneous stage from CHMI hourly HQ file (tsConID=HH). Native unit is centimetres; converted to metres.",
    ),
)


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


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
) -> GeneratedCzChmiCatalogue:
    return generate_catalogue(
        _read_fixture_json(Path(fixture_path)),
        catalogue_date=catalogue_date,
        generator_input="fixture",
    )


def generate_catalogue_from_live(
    *,
    catalogue_date: date | None = None,
) -> GeneratedCzChmiCatalogue:
    return generate_catalogue(
        _read_live_json(METADATA_URL),
        catalogue_date=catalogue_date,
        generator_input="live",
    )


def generate_catalogue(
    raw_metadata: dict[str, object],
    *,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedCzChmiCatalogue:
    effective_date = catalogue_date or date.today()
    raw_stations = _extract_stations(raw_metadata)
    products = build_products()
    stations = build_stations(raw_stations)
    station_products = build_station_products(stations, effective_date)
    provider_info = build_provider_info(effective_date, generator_input=generator_input)

    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedCzChmiCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=station_products,
    )


def build_products() -> ProductCatalog:
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "product_id": defn.product_id,
            "observed_property": defn.observed_property,
            "frequency": defn.frequency,
            "statistic": defn.statistic,
            "period_type": defn.period_type,
            "period_anchor": defn.period_anchor,
            "unit": defn.canonical_unit,
            "native_id": defn.ts_con_id,
            "derived": False,
            "derivation_method": None,
            "metadata": _metadata_json(defn.metadata),
        }
        for defn in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(raw_stations: list[dict[str, object]]) -> StationCatalog:
    rows = [_station_row(item) for item in raw_stations]
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(stations: StationCatalog, catalogue_date: date) -> StationProductCatalog:
    rows = []
    for station_id in stations["station_id"].to_list():
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        for defn in PRODUCT_DEFINITIONS:
            meta = CzChmiStationProductMetadata(
                station_id=station_id,
                product_id=defn.product_id,
                ts_con_id=defn.ts_con_id,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=(
                    "CHMI metadata catalogue does not expose per-variable station availability; "
                    "all station-product pairs are materialized as availability=unknown."
                ),
            )
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": defn.product_id,
                    "availability": "unknown",
                    "availability_reason": AVAILABILITY_REASON,
                    "start_date": None,
                    "end_date": None,
                    "last_catalogue_check": catalogue_date,
                    "metadata": _metadata_json(meta),
                }
            )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(AvailabilityDtype)
    )


def build_provider_info(
    catalogue_date: date,
    *,
    generator_input: str,
) -> dict[str, object]:
    metadata = {
        "metadata_url": METADATA_URL,
        "daily_url_template": "https://opendata.chmi.cz/hydrology/historical/data/daily/H_{station_id}_DQ_{year}.json",
        "hourly_url_template": "https://opendata.chmi.cz/hydrology/historical/data/hourly/H_{station_id}_HQ_{year}.json",
        "generator_input": generator_input,
        "terms_of_use": "https://opendata.chmi.cz/",
    }
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: annual-window requests per station-product pair; "
            "404 years silently skipped; partial failures reported as recoverable issues"
        ),
        "catalogue_version": catalogue_date.isoformat(),
        "metadata": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
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
        on_issue="raise",
    )


def write_catalogue(catalogue: GeneratedCzChmiCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as file:
        json.dump(catalogue.provider_info, file, sort_keys=True, separators=(",", ":"))
        file.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")


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


def _station_row(item: dict[str, object]) -> dict[str, object]:
    station_id_raw = item.get("objID")
    if not isinstance(station_id_raw, str) or not str(station_id_raw).strip():
        raise FatalContractError(f"cz_chmi station entry missing required string field 'objID': {item}")
    station_id = str(station_id_raw).strip()

    latitude = _optional_float(item.get("GEOGR1"), f"station {station_id} latitude")
    longitude = _optional_float(item.get("GEOGR2"), f"station {station_id} longitude")
    if latitude is None or longitude is None:
        raise FatalContractError(f"cz_chmi station {station_id} missing required latitude/longitude")

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


def _metadata_json(
    model: CzChmiProductMetadata | CzChmiStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _optional_float(value: object, name: str) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged cz_chmi catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to a CHMI metadata JSON fixture.")
    source.add_argument("--live", action="store_true", help="Fetch the live CHMI metadata endpoint.")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--out", type=Path, help="Output directory for provider.json and parquet files.")
    destination.add_argument("--native-out", type=Path, help="Output path for the native Parquet table.")
    parser.add_argument("--catalogue-date", type=date.fromisoformat)
    parser.add_argument("--retrieved-at", type=lambda value: RetrievedAt(datetime.fromisoformat(value)))
    args = parser.parse_args(argv)

    if args.native_out is not None:
        if args.retrieved_at is None:
            parser.error("--retrieved-at is required with --native-out")
        if args.catalogue_date is not None:
            parser.error("--catalogue-date is only valid with --out")
        if args.live:
            native_outcome = refresh_native_table_from_live(retrieved_at=args.retrieved_at)
        else:
            native_outcome = refresh_native_table_from_fixture(args.fixture, retrieved_at=args.retrieved_at)
        write_native_table(native_outcome.value, args.native_out)
        return 0

    if args.retrieved_at is not None:
        parser.error("--retrieved-at is only valid with --native-out")
    if args.live:
        catalogue = generate_catalogue_from_live(catalogue_date=args.catalogue_date)
    else:
        catalogue = generate_catalogue_from_fixture(args.fixture, catalogue_date=args.catalogue_date)
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

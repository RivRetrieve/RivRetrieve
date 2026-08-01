from __future__ import annotations

import argparse
import json
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
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
    """Parse the nested CHMI metadata structure.

    The metadata endpoint returns:
    { "data": { "data": { "header": "objID,...", "values": [[...], ...] } } }
    """
    try:
        inner = raw_metadata["data"]
        if not isinstance(inner, dict):
            raise FatalContractError("cz_chmi metadata: expected dict under 'data'")
        inner2 = cast("dict[str, object]", inner)["data"]
        if not isinstance(inner2, dict):
            raise FatalContractError("cz_chmi metadata: expected dict under 'data.data'")
        data_block = cast("dict[str, object]", inner2)
        header_str = data_block.get("header", "")
        values_raw = data_block.get("values", [])
    except (KeyError, TypeError) as exc:
        raise FatalContractError(f"cz_chmi metadata: unexpected JSON structure: {exc}") from exc

    if not isinstance(header_str, str) or not isinstance(values_raw, list):
        raise FatalContractError("cz_chmi metadata: 'header' must be a string and 'values' must be a list")

    columns = [c.strip() for c in header_str.split(",")]

    station_rows: list[dict[str, object]] = []
    for row in values_raw:
        if not isinstance(row, list):
            continue
        station_rows.append(dict(zip(columns, row, strict=False)))

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
    parser.add_argument("--out", type=Path, required=True, help="Output directory for provider.json and parquet files.")
    parser.add_argument("--catalogue-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)

    if args.live:
        catalogue = generate_catalogue_from_live(catalogue_date=args.catalogue_date)
    else:
        catalogue = generate_catalogue_from_fixture(args.fixture, catalogue_date=args.catalogue_date)
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

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
from rivretrieve._internal.providers.th_thaiwater.metadata import (
    ThThaiWaterProductMetadata,
    ThThaiWaterStationMetadata,
    ThThaiWaterStationProductMetadata,
)

PROVIDER_ID = "th_thaiwater"
PROVIDER_NAME = "ThaiWater public API / Hydro-Informatics Institute (HII)"
COUNTRY = "Thailand"
METADATA_URL = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load"
AVAILABILITY_REASON = "ThaiWater metadata catalogue does not expose per-variable station availability"
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"
VERTICAL_DATUM = "MSL"
STATION_TYPE_FILTER = "tele_waterlevel"


@dataclass(frozen=True)
class GeneratedThThaiWaterCatalogue:
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
    native_field: str
    aggregate_daily: bool
    native_unit: str
    notes: str | None

    @property
    def metadata(self) -> ThThaiWaterProductMetadata:
        return ThThaiWaterProductMetadata(
            native_field=self.native_field,
            aggregate_daily=self.aggregate_daily,
            native_unit=self.native_unit,
            canonical_unit=self.canonical_unit,
            notes=self.notes,
        )


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        product_id="stage_daily_mean",
        observed_property="stage",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m",
        native_field="value",
        aggregate_daily=True,
        native_unit="m",
        notes=("Daily mean stage from ThaiWater waterlevel_graph 'value' field aggregated over Bangkok calendar days."),
    ),
    ProductDefinition(
        product_id="stage_instantaneous",
        observed_property="stage",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m",
        native_field="value",
        aggregate_daily=False,
        native_unit="m",
        notes=(
            "Instantaneous stage from ThaiWater waterlevel_graph 'value' field. "
            "Timestamps are in Asia/Bangkok and converted to UTC."
        ),
    ),
    ProductDefinition(
        product_id="discharge_daily_mean",
        observed_property="discharge",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        native_field="discharge",
        aggregate_daily=True,
        native_unit="m3/s",
        notes=(
            "Daily mean discharge from ThaiWater waterlevel_graph 'discharge' field "
            "aggregated over Bangkok calendar days."
        ),
    ),
    ProductDefinition(
        product_id="discharge_instantaneous",
        observed_property="discharge",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m3/s",
        native_field="discharge",
        aggregate_daily=False,
        native_unit="m3/s",
        notes=(
            "Instantaneous discharge from ThaiWater waterlevel_graph 'discharge' field. "
            "Timestamps are in Asia/Bangkok and converted to UTC."
        ),
    ),
)

EXPECTED_PRODUCT_IDS = frozenset(d.product_id for d in PRODUCT_DEFINITIONS)


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
    product_definitions: Sequence[ProductDefinition] = PRODUCT_DEFINITIONS,
) -> GeneratedThThaiWaterCatalogue:
    return generate_catalogue(
        _read_fixture_json(Path(fixture_path)),
        catalogue_date=catalogue_date,
        product_definitions=product_definitions,
        generator_input="fixture",
    )


def generate_catalogue_from_live(
    *,
    catalogue_date: date | None = None,
    product_definitions: Sequence[ProductDefinition] = PRODUCT_DEFINITIONS,
) -> GeneratedThThaiWaterCatalogue:
    return generate_catalogue(
        _read_live_json(METADATA_URL),
        catalogue_date=catalogue_date,
        product_definitions=product_definitions,
        generator_input="live",
    )


def generate_catalogue(
    raw_payload: dict[str, object],
    *,
    catalogue_date: date | None = None,
    product_definitions: Sequence[ProductDefinition] = PRODUCT_DEFINITIONS,
    generator_input: str = "fixture",
) -> GeneratedThThaiWaterCatalogue:
    effective_date = catalogue_date or date.today()
    products = build_products(product_definitions)
    stations = build_stations(raw_payload)
    station_products = build_station_products(stations, product_definitions, effective_date)
    provider_info = build_provider_info(effective_date, generator_input=generator_input)

    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedThThaiWaterCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=station_products,
    )


def build_products(
    product_definitions: Sequence[ProductDefinition] = PRODUCT_DEFINITIONS,
) -> ProductCatalog:
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "product_id": d.product_id,
            "observed_property": d.observed_property,
            "frequency": d.frequency,
            "statistic": d.statistic,
            "period_type": d.period_type,
            "period_anchor": d.period_anchor,
            "unit": d.canonical_unit,
            "native_id": d.native_field,
            "derived": False,
            "derivation_method": None,
            "metadata": _metadata_json(d.metadata),
        }
        for d in product_definitions
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(raw_payload: dict[str, object]) -> StationCatalog:
    rows = list(_iter_station_rows(raw_payload))
    if not rows:
        raise FatalContractError("ThaiWater metadata returned no tele_waterlevel stations")
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(
    stations: StationCatalog,
    product_definitions: Sequence[ProductDefinition],
    catalogue_date: date,
) -> StationProductCatalog:
    rows = []
    for station_id in stations["station_id"].to_list():
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        for d in product_definitions:
            metadata = ThThaiWaterStationProductMetadata(
                station_id=station_id,
                product_id=d.product_id,
                native_field=d.native_field,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=(
                    "Materialised as availability=unknown; "
                    "waterlevel_load does not guarantee observed data for every product."
                ),
            )
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
                    "availability": "unknown",
                    "availability_reason": AVAILABILITY_REASON,
                    "start_date": None,
                    "end_date": None,
                    "last_catalogue_check": catalogue_date,
                    "metadata": _metadata_json(metadata),
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
    metadata: dict[str, object] = {
        "source_url": METADATA_URL,
        "generator_input": generator_input,
        "local_timezone": "Asia/Bangkok",
        "vertical_datum": VERTICAL_DATUM,
        "station_type_filter": STATION_TYPE_FILTER,
    }
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: 365-day window decomposition with stitched N x M station-product requests; "
            "partial failures reported as recoverable issues"
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


def write_catalogue(catalogue: GeneratedThThaiWaterCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as f:
        json.dump(catalogue.provider_info, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")


def _iter_station_rows(raw_payload: dict[str, object]):  # type: ignore[return]
    waterlevel_data = raw_payload.get("waterlevel_data", {})
    if not isinstance(waterlevel_data, dict):
        return
    data_list = waterlevel_data.get("data", [])
    if not isinstance(data_list, list):
        return

    seen: set[str] = set()
    for row in data_list:
        if not isinstance(row, dict):
            continue

        station = row.get("station", {})
        if not isinstance(station, dict):
            continue

        station_type = _clean_text(row.get("station_type") or station.get("tele_station_type"))
        if station_type != STATION_TYPE_FILTER:
            continue

        gauge_id = _clean_text(station.get("id"))
        if gauge_id is None:
            continue
        if gauge_id in seen:
            continue
        seen.add(gauge_id)

        name_en = _pick_localized_text(station.get("tele_station_name"), preferred=("en", "th"))
        name_th = _pick_localized_text(station.get("tele_station_name"), preferred=("th", "en"))
        lat = _to_float(station.get("tele_station_lat"))
        lon = _to_float(station.get("tele_station_long"))
        if lat is None or lon is None:
            continue

        geocode = row.get("geocode", {})
        geocode = geocode if isinstance(geocode, dict) else {}
        basin = row.get("basin", {})
        basin = basin if isinstance(basin, dict) else {}
        agency = row.get("agency", {})
        agency = agency if isinstance(agency, dict) else {}

        metadata = ThThaiWaterStationMetadata(
            native_id=gauge_id,
            name=name_en or name_th or gauge_id,
            name_local=name_th,
            river_name=_clean_text(row.get("river_name")),
            latitude=lat,
            longitude=lon,
            country=COUNTRY,
            source=PROVIDER_NAME,
            station_code=_clean_text(station.get("tele_station_oldcode")),
            station_type=station_type,
            agency=_pick_localized_text(agency.get("agency_name"), preferred=("en", "th")),
            basin=_pick_localized_text(basin.get("basin_name"), preferred=("en", "th")),
            province=_pick_localized_text(geocode.get("province_name"), preferred=("en", "th")),
            district=_pick_localized_text(geocode.get("amphoe_name"), preferred=("en", "th")),
            subdistrict=_pick_localized_text(geocode.get("tumbon_name"), preferred=("en", "th")),
            vertical_datum=VERTICAL_DATUM,
            elevation_m=None,
            drainage_area_km2=None,
        )

        yield {
            "provider_id": PROVIDER_ID,
            "station_id": gauge_id,
            "name": name_en or name_th or gauge_id,
            "latitude": lat,
            "longitude": lon,
            "country": COUNTRY,
            "elevation_m": None,
            "drainage_area_km2": None,
            "start_date": None,
            "end_date": None,
            "metadata": _metadata_json(metadata),
        }


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _pick_localized_text(value: Any, preferred: tuple[str, ...] = ("en", "th")) -> str | None:
    if isinstance(value, dict):
        for lang in preferred:
            text = _clean_text(value.get(lang))
            if text:
                return text
        for v in value.values():
            text = _clean_text(v)
            if text:
                return text
        return None
    return _clean_text(value)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metadata_json(
    model: ThThaiWaterStationMetadata | ThThaiWaterProductMetadata | ThThaiWaterStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _read_fixture_json(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except OSError as exc:
        raise FatalContractError(f"Unable to read ThaiWater metadata fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"ThaiWater metadata fixture is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FatalContractError("ThaiWater metadata fixture must contain a JSON object")
    return cast("dict[str, object]", value)


def _read_live_json(url: str) -> dict[str, object]:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            if response.status < 200 or response.status >= 300:
                raise FatalContractError(f"ThaiWater metadata live request failed with HTTP {response.status}")
            value = json.load(response)
    except OSError as exc:
        raise FatalContractError("ThaiWater metadata live request failed") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError("ThaiWater metadata live response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise FatalContractError("ThaiWater metadata live response must contain a JSON object")
    return cast("dict[str, object]", value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged th_thaiwater catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to a ThaiWater waterlevel_load JSON fixture.")
    source.add_argument("--live", action="store_true", help="Fetch the live ThaiWater metadata endpoint.")
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

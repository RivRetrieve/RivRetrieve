from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import polars as pl
import requests

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
from rivretrieve._internal.providers.no_nve.metadata import (
    NoNveProductMetadata,
    NoNveStationMetadata,
    NoNveStationProductMetadata,
)

PROVIDER_ID = "no_nve"
PROVIDER_NAME = "NVE HydAPI — Norwegian Water Resources and Energy Directorate"
COUNTRY = "Norway"

BASE_URL = "https://hydapi.nve.no/api/v1/"
STATIONS_URL = f"{BASE_URL}Stations"
OBSERVATIONS_URL = f"{BASE_URL}Observations"

MIN_LIVE_STATIONS = 100


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    frequency: str
    statistic: str
    period_type: str
    period_anchor: str
    canonical_unit: str
    parameter_id: int
    resolution_time: int
    native_unit: str
    timezone_handling: str
    notes: str | None

    @property
    def metadata(self) -> NoNveProductMetadata:
        return NoNveProductMetadata(
            parameter_id=self.parameter_id,
            resolution_time=self.resolution_time,
            frequency=self.frequency,
            native_unit=self.native_unit,
            canonical_unit=self.canonical_unit,
            timezone_handling=self.timezone_handling,
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
        parameter_id=1000,
        resolution_time=1440,
        native_unit="m",
        timezone_handling="date_only_utc_midnight",
        notes=(
            "NVE parameter 1000 (water level), resolution 1440 min (daily). "
            "Daily timestamps are date-only; interpreted as UTC midnight (T00:00:00Z). "
            "No unit conversion: values already in metres."
        ),
    ),
    ProductDefinition(
        product_id="stage_hourly_mean",
        observed_property="stage",
        frequency="hourly",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m",
        parameter_id=1000,
        resolution_time=60,
        native_unit="m",
        timezone_handling="provider_timestamp_offset",
        notes=(
            "NVE parameter 1000 (water level), resolution 60 min (hourly). "
            "Timestamps carry explicit ISO 8601 timezone offset; converted to UTC. "
            "Provider-specific product ID: no canonical hourly stage in V1 dictionary. "
            "No unit conversion: values already in metres."
        ),
    ),
    ProductDefinition(
        product_id="stage_instantaneous",
        observed_property="stage",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m",
        parameter_id=1000,
        resolution_time=0,
        native_unit="m",
        timezone_handling="provider_timestamp_offset",
        notes=(
            "NVE parameter 1000 (water level), resolution 0 (instantaneous). "
            "Timestamps carry explicit ISO 8601 timezone offset; converted to UTC. "
            "No unit conversion: values already in metres."
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
        parameter_id=1001,
        resolution_time=1440,
        native_unit="m3/s",
        timezone_handling="date_only_utc_midnight",
        notes=(
            "NVE parameter 1001 (discharge), resolution 1440 min (daily). "
            "Daily timestamps are date-only; interpreted as UTC midnight (T00:00:00Z). "
            "No unit conversion: values already in m³/s."
        ),
    ),
    ProductDefinition(
        product_id="discharge_hourly_mean",
        observed_property="discharge",
        frequency="hourly",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        parameter_id=1001,
        resolution_time=60,
        native_unit="m3/s",
        timezone_handling="provider_timestamp_offset",
        notes=(
            "NVE parameter 1001 (discharge), resolution 60 min (hourly). "
            "Timestamps carry explicit ISO 8601 timezone offset; converted to UTC. "
            "Provider-specific product ID: no canonical hourly discharge in V1 dictionary. "
            "No unit conversion: values already in m³/s."
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
        parameter_id=1001,
        resolution_time=0,
        native_unit="m3/s",
        timezone_handling="provider_timestamp_offset",
        notes=(
            "NVE parameter 1001 (discharge), resolution 0 (instantaneous). "
            "Timestamps carry explicit ISO 8601 timezone offset; converted to UTC. "
            "No unit conversion: values already in m³/s."
        ),
    ),
    ProductDefinition(
        product_id="water_temperature_daily_mean",
        observed_property="water_temperature",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="degC",
        parameter_id=1003,
        resolution_time=1440,
        native_unit="degC",
        timezone_handling="date_only_utc_midnight",
        notes=(
            "NVE parameter 1003 (water temperature), resolution 1440 min (daily). "
            "Daily timestamps are date-only; interpreted as UTC midnight (T00:00:00Z). "
            "No unit conversion: values already in °C."
        ),
    ),
    ProductDefinition(
        product_id="water_temperature_hourly_mean",
        observed_property="water_temperature",
        frequency="hourly",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="degC",
        parameter_id=1003,
        resolution_time=60,
        native_unit="degC",
        timezone_handling="provider_timestamp_offset",
        notes=(
            "NVE parameter 1003 (water temperature), resolution 60 min (hourly). "
            "Timestamps carry explicit ISO 8601 timezone offset; converted to UTC. "
            "Provider-specific product ID: no canonical hourly water_temperature in V1 dictionary. "
            "No unit conversion: values already in °C."
        ),
    ),
    ProductDefinition(
        product_id="water_temperature_instantaneous",
        observed_property="water_temperature",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="degC",
        parameter_id=1003,
        resolution_time=0,
        native_unit="degC",
        timezone_handling="provider_timestamp_offset",
        notes=(
            "NVE parameter 1003 (water temperature), resolution 0 (instantaneous). "
            "Timestamps carry explicit ISO 8601 timezone offset; converted to UTC. "
            "No unit conversion: values already in °C."
        ),
    ),
)

EXPECTED_PRODUCT_IDS = frozenset(d.product_id for d in PRODUCT_DEFINITIONS)

# Map (parameter_id, resolution_time) -> product_id for station-product availability.
_PARAM_RES_TO_PRODUCT: dict[tuple[int, int], str] = {
    (d.parameter_id, d.resolution_time): d.product_id for d in PRODUCT_DEFINITIONS
}


@dataclass(frozen=True)
class GeneratedNoNveCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
) -> GeneratedNoNveCatalogue:
    """Build catalogue from a JSON fixture (array of NVE station objects)."""
    path = Path(fixture_path)
    rows = _read_json_fixture(path)
    return generate_catalogue(rows, catalogue_date=catalogue_date, generator_input="fixture")


def generate_catalogue_from_live(
    *,
    api_key: str | None = None,
    catalogue_date: date | None = None,
) -> GeneratedNoNveCatalogue:
    """Fetch live station catalogue from NVE HydAPI (active and inactive stations)."""
    key = api_key or os.environ.get("NVE_API_KEY")
    if not key:
        raise FatalContractError("no_nve: NVE_API_KEY environment variable not set; required for live catalogue")

    headers = {"Accept": "application/json", "X-API-Key": key}
    rows: list[dict[str, object]] = []
    for active_flag in (1, 0):
        url = f"{STATIONS_URL}?Active={active_flag}"
        try:
            resp = requests.get(url, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            if isinstance(data, list):
                rows.extend(dict(r) for r in data if isinstance(r, dict))
        except requests.RequestException as exc:
            raise FatalContractError(f"no_nve: live station fetch failed (Active={active_flag}): {exc}") from exc

    if len(rows) < MIN_LIVE_STATIONS:
        raise FatalContractError(
            f"no_nve: live catalogue returned only {len(rows)} stations "
            f"(expected ≥ {MIN_LIVE_STATIONS}); possible fetch failure"
        )
    return generate_catalogue(rows, catalogue_date=catalogue_date, generator_input="live_hydapi")


def generate_catalogue(
    station_rows: list[dict[str, object]],
    *,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedNoNveCatalogue:
    effective_date = catalogue_date or date.today()
    products = build_products()
    stations = build_stations(station_rows)
    station_ids = stations["station_id"].to_list()
    station_products = build_station_products(
        station_rows=station_rows,
        station_ids=station_ids,
        catalogue_date=effective_date,
    )
    provider_info = build_provider_info(effective_date, generator_input=generator_input)
    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedNoNveCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=station_products,
    )


def build_products() -> ProductCatalog:
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
            "native_id": f"{d.parameter_id}:{d.resolution_time}",
            "derived": False,
            "derivation_method": None,
            "metadata": _metadata_json(d.metadata),
        }
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(station_rows: list[dict[str, object]]) -> StationCatalog:
    rows = list(_iter_station_rows(station_rows))
    if not rows:
        raise FatalContractError("no_nve: station build returned no rows")
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(
    *,
    station_rows: list[dict[str, object]],
    station_ids: list[object],
    catalogue_date: date,
) -> StationProductCatalog:
    # Build a map from station_id -> set of available (parameter_id, resolution_time) pairs.
    availability_map: dict[str, set[tuple[int, int]]] = {}
    for row in station_rows:
        if not isinstance(row, dict):
            continue
        station_id = _clean_text(row.get("stationId"))
        if station_id is None:
            continue
        series_list = row.get("seriesList")
        if not isinstance(series_list, list):
            availability_map.setdefault(station_id, set())
            continue
        pairs: set[tuple[int, int]] = set()
        for series in series_list:
            if not isinstance(series, dict):
                continue
            series_d = cast(dict[str, object], series)
            param_id = series_d.get("parameter")
            resolutions = series_d.get("resolutionList", [])
            if not isinstance(param_id, int) or not isinstance(resolutions, list):
                continue
            for res_info in resolutions:
                if not isinstance(res_info, dict):
                    continue
                res_info_d = cast(dict[str, object], res_info)
                res_time = res_info_d.get("resTime")
                if isinstance(res_time, int):
                    pairs.add((param_id, res_time))
        availability_map[station_id] = pairs

    rows = []
    for station_id in station_ids:
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        available_pairs = availability_map.get(station_id)
        for d in PRODUCT_DEFINITIONS:
            pair = (d.parameter_id, d.resolution_time)
            if available_pairs is not None and pair in available_pairs:
                availability = "available"
                availability_reason = f"NVE seriesList confirms parameter {d.parameter_id}, resTime {d.resolution_time}"
                availability_source = "nve_series_list"
            elif available_pairs is not None:
                availability = "unavailable"
                availability_reason = (
                    f"NVE seriesList does not include parameter {d.parameter_id}, resTime {d.resolution_time}"
                )
                availability_source = "nve_series_list"
            else:
                availability = "unknown"
                availability_reason = "NVE seriesList not present in catalogue input"
                availability_source = "catalogue_assumption"

            metadata = NoNveStationProductMetadata(
                station_id=station_id,
                product_id=d.product_id,
                parameter_id=d.parameter_id,
                resolution_time=d.resolution_time,
                availability_source=availability_source,
                availability_note=availability_reason,
            )
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
                    "availability": availability,
                    "availability_reason": availability_reason,
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
        "stations_url": STATIONS_URL,
        "observations_url": OBSERVATIONS_URL,
        "generator_input": generator_input,
        "auth_env_var": "NVE_API_KEY",
        "timestamp_convention": (
            "daily_resolution_1440=date_only_utc_midnight; "
            "hourly_resolution_60_and_instantaneous_resolution_0=provider_timestamp_offset_to_utc"
        ),
        "unit_convention": "m for stage, m3/s for discharge, degC for water_temperature — no conversions needed",
        "terms_of_use": "https://hydapi.nve.no/UserDocumentation/#termsofuse",
    }
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: yearly-window decomposition for daily products (resTime 1440), "
            "monthly-window decomposition for hourly/instantaneous (resTime 60, 0); "
            "requires NVE_API_KEY; partial failures reported as recoverable issues"
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


def write_catalogue(catalogue: GeneratedNoNveCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as f:
        json.dump(catalogue.provider_info, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")


# ---------------------------------------------------------------------------
# Station row iterator
# ---------------------------------------------------------------------------


def _iter_station_rows(station_rows: list[dict[str, object]]):  # type: ignore[return]
    seen: set[str] = set()
    for row in station_rows:
        if not isinstance(row, dict):
            continue
        station_id = _clean_text(row.get("stationId"))
        if station_id is None or station_id in seen:
            continue
        lat = _to_float(row.get("latitude"))
        lon = _to_float(row.get("longitude"))
        if lat is None or lon is None:
            continue
        seen.add(station_id)

        name = _clean_text(row.get("stationName")) or station_id
        elevation_m = _to_float(row.get("masl"))
        drainage_area_km2 = _to_float(row.get("drainageBasinArea"))
        river_name = _clean_text(row.get("riverName"))
        active = row.get("active")

        metadata = NoNveStationMetadata(
            native_id=station_id,
            name=name,
            latitude=lat,
            longitude=lon,
            country=COUNTRY,
            source=PROVIDER_NAME,
            elevation_m=elevation_m,
            drainage_area_km2=drainage_area_km2,
            river_name=river_name,
            active=bool(active) if active is not None else None,
        )

        yield {
            "provider_id": PROVIDER_ID,
            "station_id": station_id,
            "name": name,
            "latitude": lat,
            "longitude": lon,
            "country": COUNTRY,
            "elevation_m": elevation_m,
            "drainage_area_km2": drainage_area_km2,
            "start_date": None,
            "end_date": None,
            "metadata": _metadata_json(metadata),
        }


# ---------------------------------------------------------------------------
# Fixture reader
# ---------------------------------------------------------------------------


def _read_json_fixture(path: Path) -> list[dict[str, object]]:
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except OSError as exc:
        raise FatalContractError(f"Unable to read no_nve JSON fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"no_nve JSON fixture is not valid JSON: {path}") from exc
    if not isinstance(value, list):
        raise FatalContractError(f"no_nve JSON fixture must be a JSON array: {path}")
    return [dict(row) for row in value if isinstance(row, dict)]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "null"):
        return None
    return text


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metadata_json(
    model: NoNveStationMetadata | NoNveProductMetadata | NoNveStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the packaged no_nve catalogue artifacts.\n\n"
            "Two modes:\n"
            "  --fixture PATH   Offline. Build from a JSON fixture (NVE station array).\n"
            "  --live           Online. Fetch active and inactive stations from NVE HydAPI.\n"
            "                   Requires NVE_API_KEY environment variable."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--fixture",
        type=Path,
        metavar="JSON",
        help="Path to a JSON fixture file (array of NVE station objects).",
    )
    source.add_argument(
        "--live",
        action="store_true",
        help="Fetch live catalogue from NVE HydAPI. Requires NVE_API_KEY env var.",
    )
    parser.add_argument("--out", type=Path, required=True, help="Output directory for catalogue artifacts.")
    parser.add_argument("--catalogue-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--api-key", type=str, default=None, help="NVE API key (overrides NVE_API_KEY env var).")
    args = parser.parse_args(argv)

    if args.live:
        catalogue = generate_catalogue_from_live(
            api_key=args.api_key,
            catalogue_date=args.catalogue_date,
        )
    else:
        catalogue = generate_catalogue_from_fixture(args.fixture, catalogue_date=args.catalogue_date)
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

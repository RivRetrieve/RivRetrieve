"""Maintainer-only catalogue generator for pl_imgw.

NOT imported during normal package use. Run manually to regenerate packaged
catalogue artifacts when the IMGW station list changes.

Station source: the packaged ``poland_sites.csv`` from the legacy Python
RivRetrieve repo (1301 stations with lat/lon, elevation, and drainage area).
The live IMGW ``/api/data/hydro`` JSON endpoint has only 913 current stations,
314 of which lack coordinates, so the CSV is the richer source.

Usage:
    uv run python -m rivretrieve._internal.providers.pl_imgw.generate_catalogue \\
        --fixture tests/test_data/pl_imgw_stations.csv \\
        --out src/rivretrieve/_internal/providers/pl_imgw/catalogue

    uv run python -m rivretrieve._internal.providers.pl_imgw.generate_catalogue \\
        --live --out src/rivretrieve/_internal/providers/pl_imgw/catalogue
"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

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
from rivretrieve._internal.providers.pl_imgw.metadata import (
    PlImgwProductMetadata,
    PlImgwStationMetadata,
    PlImgwStationProductMetadata,
)

PROVIDER_ID = "pl_imgw"
PROVIDER_NAME = "Poland Institute of Meteorology and Water Management (IMGW)"
COUNTRY = "Poland"

# Primary station source (packaged CSV from legacy Python repo).
# Columns: gauge_id, gauge_name, river, area (km²), gauge_altitude (m), latitude, longitude
STATION_CSV_URL = (
    "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/lista_stacji_hydro.csv"
)
# The live JSON endpoint — usable as fallback but lacks elevation/area and has 314 stations without coords.
HYDRO_JSON_URL = "https://danepubliczne.imgw.pl/api/data/hydro"

AVAILABILITY_REASON = "IMGW does not expose per-variable station availability"
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"
LIVE_STATION_MINIMUM = 500


@dataclass(frozen=True)
class GeneratedPlImgwCatalogue:
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
    native_column: str
    native_unit: str
    unit_conversion: str | None
    notes: str | None

    @property
    def metadata(self) -> PlImgwProductMetadata:
        return PlImgwProductMetadata(
            native_column=self.native_column,
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
        native_column="Flow [m^3/s]",
        native_unit="m3/s",
        unit_conversion=None,
        notes="Daily mean discharge. Native unit is m³/s; no conversion required.",
    ),
    ProductDefinition(
        product_id="stage_daily_mean",
        observed_property="stage",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m",
        native_column="Water level [cm]",
        native_unit="cm",
        unit_conversion="divide_by_100",
        notes="Daily mean water stage. Native unit is centimetres; converted to metres.",
    ),
    ProductDefinition(
        product_id="water_temperature_daily_mean",
        observed_property="water_temperature",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="degC",
        native_column="Water temperature [deg. C]",
        native_unit="degC",
        unit_conversion=None,
        notes="Daily mean water temperature. Native unit is degrees Celsius.",
    ),
)


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
) -> GeneratedPlImgwCatalogue:
    """Generate catalogue from a local ``poland_sites.csv`` fixture file."""
    raw = _read_fixture_csv(Path(fixture_path))
    return generate_catalogue(raw, catalogue_date=catalogue_date, generator_input="fixture")


def generate_catalogue_from_live(
    *,
    catalogue_date: date | None = None,
) -> GeneratedPlImgwCatalogue:
    """Generate catalogue by downloading the live ``poland_sites.csv`` from IMGW.

    Note: the live IMGW station list CSV does not include coordinates. This
    falls back to the ``/api/data/hydro`` JSON endpoint to enrich with lat/lon,
    but that endpoint has ~314 stations without coordinates. For a complete
    catalogue, prefer ``--fixture tests/test_data/pl_imgw_stations.csv``.
    """
    raw = _fetch_live_stations()
    return generate_catalogue(raw, catalogue_date=catalogue_date, generator_input="live")


def generate_catalogue(
    raw_stations: list[dict[str, object]],
    *,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedPlImgwCatalogue:
    effective_date = catalogue_date or date.today()

    if generator_input == "live" and len(raw_stations) < LIVE_STATION_MINIMUM:
        raise FatalContractError(
            f"pl_imgw live catalogue returned only {len(raw_stations)} stations; "
            f"expected at least {LIVE_STATION_MINIMUM}."
        )

    products = build_products()
    stations = build_stations(raw_stations)
    station_products = build_station_products(stations, effective_date)
    provider_info = build_provider_info(effective_date, generator_input=generator_input)

    _validate(provider_info, products, stations, station_products)
    return GeneratedPlImgwCatalogue(
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
            "native_id": defn.native_column,
            "derived": False,
            "derivation_method": None,
            "metadata": _meta_json(defn.metadata),
        }
        for defn in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(raw_stations: list[dict[str, object]]) -> StationCatalog:
    rows = [_station_row(s) for s in raw_stations if _station_row(s) is not None]
    if not rows:
        raise FatalContractError("pl_imgw: no valid station rows produced from input data")
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(stations: StationCatalog, catalogue_date: date) -> StationProductCatalog:
    rows = []
    for station_id in stations["station_id"].to_list():
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        for defn in PRODUCT_DEFINITIONS:
            meta = PlImgwStationProductMetadata(
                station_id=station_id,
                product_id=defn.product_id,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=AVAILABILITY_REASON,
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
                    "metadata": _meta_json(meta),
                }
            )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(AvailabilityDtype)
    )


def build_provider_info(catalogue_date: date, *, generator_input: str) -> dict[str, object]:
    metadata = {
        "station_source": "poland_sites.csv from legacy RivRetrieve-Python repo (1301 stations)",
        "data_base_url": (
            "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/{year}/"
        ),
        "annual_zip_from_year": 2023,
        "annual_zip_template": "codz_{year}.zip",
        "monthly_zip_template": "codz_{year}_{month:02d}.zip",
        "csv_encoding_recent": "utf-8-sig (BOM), semicolon-separated",
        "csv_encoding_legacy": "cp1250, comma-separated, quoted",
        "cache_format": "parquet",
        "generator_input": generator_input,
        "terms_of_use": "https://danepubliczne.imgw.pl/",
    }
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: the source publishes all-station yearly ZIP files; RivRetrieve's "
            "catalogue-only provider exposes neither observation retrieval nor cache controls"
        ),
        "catalogue_version": catalogue_date.isoformat(),
        "metadata": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
    }


def write_catalogue(catalogue: GeneratedPlImgwCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as fh:
        json.dump(catalogue.provider_info, fh, sort_keys=True, separators=(",", ":"))
        fh.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _station_row(item: dict[str, object]) -> dict[str, object] | None:
    """Parse one station row from the poland_sites.csv columns."""
    station_id = str(item.get("gauge_id", "")).strip()
    if not station_id:
        return None

    name = str(item.get("gauge_name", "")).strip() or station_id

    river_raw = item.get("river")
    river = str(river_raw).strip() if isinstance(river_raw, str) and str(river_raw).strip() else None

    lat = _optional_float(item.get("latitude"))
    lon = _optional_float(item.get("longitude"))
    elevation_m = _optional_float(item.get("gauge_altitude"))
    drainage_area_km2 = _optional_float(item.get("area"))

    if lat is None or lon is None:
        return None

    meta = PlImgwStationMetadata(
        native_id=station_id,
        name=name,
        river=river,
        province=None,
        latitude=lat,
        longitude=lon,
        country=COUNTRY,
        source=PROVIDER_NAME,
    )
    return {
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
        "metadata": _meta_json(meta),
    }


def _optional_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value))
    except (ValueError, TypeError):
        return None


def _meta_json(
    model: PlImgwStationMetadata | PlImgwProductMetadata | PlImgwStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _read_fixture_csv(path: Path) -> list[dict[str, object]]:
    """Read the poland_sites.csv fixture (gauge_id, gauge_name, river, area, gauge_altitude, lat, lon)."""
    try:
        with path.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows: list[dict[str, object]] = [dict(row) for row in reader]
    except OSError as exc:
        raise FatalContractError(f"Cannot read pl_imgw station CSV fixture: {path}") from exc
    if not rows:
        raise FatalContractError(f"pl_imgw station CSV fixture is empty: {path}")
    return rows


def _fetch_live_stations() -> list[dict[str, object]]:
    """Download the live IMGW /api/data/hydro JSON and convert to the same dict shape as the CSV."""
    try:
        with urllib.request.urlopen(HYDRO_JSON_URL, timeout=30) as resp:
            if resp.status < 200 or resp.status >= 300:
                raise FatalContractError(f"pl_imgw live request failed with HTTP {resp.status}")
            data = json.load(resp)
    except OSError as exc:
        raise FatalContractError("pl_imgw live station request failed") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError("pl_imgw live station response is not valid JSON") from exc
    if not isinstance(data, list):
        raise FatalContractError("pl_imgw live station response must be a JSON array")

    # Map JSON fields → CSV-equivalent keys so _station_row() works for both.
    rows: list[dict[str, object]] = []
    for s in data:
        if not isinstance(s, dict):
            continue
        rows.append(
            {
                "gauge_id": s.get("id_stacji"),
                "gauge_name": s.get("stacja"),
                "river": s.get("rzeka"),
                "area": None,
                "gauge_altitude": None,
                "latitude": s.get("lat"),
                "longitude": s.get("lon"),
            }
        )
    return rows


def _validate(
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
    packaged_catalogue_artifact_from_components(provider_info, products, stations, station_products, on_issue="raise")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged pl_imgw catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--fixture",
        type=Path,
        help="Path to a poland_sites.csv file (gauge_id, gauge_name, river, area, gauge_altitude, lat, lon).",
    )
    source.add_argument("--live", action="store_true", help="Fetch the live IMGW /api/data/hydro endpoint.")
    parser.add_argument("--out", type=Path, required=True, help="Output directory for catalogue artifacts.")
    parser.add_argument("--catalogue-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)

    if args.live:
        catalogue = generate_catalogue_from_live(catalogue_date=args.catalogue_date)
    else:
        catalogue = generate_catalogue_from_fixture(args.fixture, catalogue_date=args.catalogue_date)
    write_catalogue(catalogue, args.out)
    print(
        f"pl_imgw catalogue written to {args.out}: "
        f"{catalogue.stations.height} stations, "
        f"{catalogue.products.height} products, "
        f"{catalogue.station_products.height} station-product rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

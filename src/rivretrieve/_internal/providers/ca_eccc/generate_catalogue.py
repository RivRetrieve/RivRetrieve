"""Maintainer-only catalogue generator for ca_eccc.

NOT imported during normal package use. Run directly:

    uv run python -m rivretrieve._internal.providers.ca_eccc.generate_catalogue \\
        --live --out src/rivretrieve/_internal/providers/ca_eccc/catalogue/

    uv run python -m rivretrieve._internal.providers.ca_eccc.generate_catalogue \\
        --fixture tests/test_data/ca_eccc_metadata.json \\
        --out src/rivretrieve/_internal/providers/ca_eccc/catalogue/
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

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
from rivretrieve._internal.providers.ca_eccc.metadata import (
    CaEcccProductMetadata,
    CaEcccStationProductMetadata,
)

PROVIDER_ID = "ca_eccc"
PROVIDER_NAME = "ECCC Hydrometric — Environment and Climate Change Canada"

BASE_URL = "https://api.weather.gc.ca/"
STATIONS_URL = f"{BASE_URL}collections/hydrometric-stations/items"
DAILY_MEAN_URL = f"{BASE_URL}collections/hydrometric-daily-mean/items"

MIN_LIVE_STATIONS = 1000
_STATION_PAGE_SIZE = 10000


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    frequency: str
    statistic: str
    period_type: str
    period_anchor: str
    canonical_unit: str
    ogc_field: str
    ogc_symbol_field: str
    native_unit: str
    notes: str | None

    @property
    def metadata(self) -> CaEcccProductMetadata:
        return CaEcccProductMetadata(
            ogc_field=self.ogc_field,
            ogc_symbol_field=self.ogc_symbol_field,
            frequency=self.frequency,
            native_unit=self.native_unit,
            canonical_unit=self.canonical_unit,
            timezone_handling="date_only_utc_midnight",
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
        ogc_field="DISCHARGE",
        ogc_symbol_field="DISCHARGE_SYMBOL",
        native_unit="m3/s",
        notes=(
            "ECCC OGC hydrometric-daily-mean collection, DISCHARGE field. "
            "Values in m³/s — no conversion. "
            "DATE field is date-only (YYYY-MM-DD); interpreted as UTC midnight. "
            "Quality code in DISCHARGE_SYMBOL (A=Estimated, B=Ice, D=Dry, E=Estimated, R=Revised)."
        ),
    ),
    ProductDefinition(
        product_id="stage_daily_mean",
        observed_property="stage",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m",
        ogc_field="LEVEL",
        ogc_symbol_field="LEVEL_SYMBOL",
        native_unit="m",
        notes=(
            "ECCC OGC hydrometric-daily-mean collection, LEVEL field. "
            "Values in m — no conversion. "
            "DATE field is date-only (YYYY-MM-DD); interpreted as UTC midnight. "
            "Quality code in LEVEL_SYMBOL (A=Estimated, B=Ice, D=Dry, E=Estimated, R=Revised)."
        ),
    ),
)


@dataclass(frozen=True)
class GeneratedCaEcccCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
) -> GeneratedCaEcccCatalogue:
    """Build catalogue from a JSON fixture (OGC FeatureCollection or array of feature properties)."""
    path = Path(fixture_path)
    rows = _read_json_fixture(path)
    return generate_catalogue(rows, catalogue_date=catalogue_date, generator_input="fixture")


def generate_catalogue_from_live(
    *,
    catalogue_date: date | None = None,
) -> GeneratedCaEcccCatalogue:
    """Fetch live station catalogue from ECCC OGC hydrometric-stations endpoint (paginated)."""
    rows: list[dict[str, object]] = []
    offset = 0

    while True:
        params: dict[str, str | int] = {
            "f": "json",
            "limit": _STATION_PAGE_SIZE,
            "offset": offset,
        }
        try:
            resp = requests.get(STATIONS_URL, params=params, timeout=60, headers={"Accept": "application/json"})
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise FatalContractError(f"ca_eccc: live station fetch failed: {exc}") from exc

        features = payload.get("features", [])
        if not isinstance(features, list):
            break
        for feat in features:
            if isinstance(feat, dict):
                props = feat.get("properties", {})
                if isinstance(props, dict):
                    row = dict(props)
                    # Coordinates live in GeoJSON geometry (lon, lat order), not in properties.
                    geom = feat.get("geometry")
                    if isinstance(geom, dict) and geom.get("type") == "Point":
                        coords = geom.get("coordinates", [])
                        if isinstance(coords, list) and len(coords) >= 2:
                            row["LONGITUDE"] = coords[0]
                            row["LATITUDE"] = coords[1]
                    rows.append(row)

        num_returned = payload.get("numberReturned", 0)
        if not isinstance(num_returned, int) or num_returned < _STATION_PAGE_SIZE:
            break
        offset += _STATION_PAGE_SIZE

    if len(rows) < MIN_LIVE_STATIONS:
        raise FatalContractError(
            f"ca_eccc: live catalogue returned only {len(rows)} stations "
            f"(expected ≥ {MIN_LIVE_STATIONS}); possible fetch failure"
        )
    return generate_catalogue(rows, catalogue_date=catalogue_date, generator_input="live_ogc")


def generate_catalogue(
    station_rows: list[dict[str, object]],
    *,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedCaEcccCatalogue:
    effective_date = catalogue_date or date.today()
    products = build_products()
    stations = build_stations(station_rows)
    station_ids = stations["station_id"].to_list()
    station_products = build_station_products(station_ids=station_ids, catalogue_date=effective_date)
    provider_info = build_provider_info(effective_date, generator_input=generator_input)
    _validate(provider_info, products, stations, station_products)
    return GeneratedCaEcccCatalogue(
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
            "native_id": d.ogc_field,
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
        raise FatalContractError("ca_eccc: station build returned no rows")
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(
    *,
    station_ids: list[object],
    catalogue_date: date,
) -> StationProductCatalog:
    # ECCC OGC does not expose per-station product availability → unknown for all.
    rows = []
    for station_id in station_ids:
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        for d in PRODUCT_DEFINITIONS:
            metadata = CaEcccStationProductMetadata(
                station_id=station_id,
                product_id=d.product_id,
                ogc_field=d.ogc_field,
                availability_source="catalogue_assumption",
                availability_note=(
                    "ECCC OGC hydrometric-stations endpoint does not expose per-variable "
                    "availability. Actual availability depends on whether the station "
                    f"has {d.ogc_field!r} values in the daily-mean collection."
                ),
            )
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
                    "availability": "unknown",
                    "availability_reason": metadata.availability_note,
                    "start_date": None,
                    "end_date": None,
                    "last_catalogue_check": catalogue_date,
                    "metadata": _metadata_json(metadata),
                }
            )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(AvailabilityDtype)
    )


def build_provider_info(catalogue_date: date, *, generator_input: str) -> dict[str, object]:
    metadata: dict[str, object] = {
        "catalogue_stations_url": STATIONS_URL,
        "observation_source": "HYDAT SQLite — full national archive downloaded on first use",
        "hydat_url_template": "https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/Hydat_sqlite3_YYYYMMDD.zip",
        "generator_input": generator_input,
        "auth": "none — public Government of Canada open data",
        "timestamp_convention": (
            "date_only_utc_midnight — HYDAT stores YEAR/MONTH/DAY integers; interpreted as T00:00:00Z"
        ),
        "unit_convention": "m for stage, m3/s for discharge — no conversions needed",
        "quality_flags": (
            "FLOW_SYMBOL / LEVEL_SYMBOL from HYDAT: "
            "A=Estimated, B=Ice conditions, D=Dry, E=Estimated (ice-affected), R=Revised, S=Sample"
        ),
        "license": "Open Government Licence - Canada (https://open.canada.ca/en/open-government-licence-canada)",
        "coverage_note": (
            "HYDAT is the complete national archive. Some stations have multi-decade gaps "
            "where data was not submitted to the national programme."
        ),
    }
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: HYDAT SQLite queried locally (downloaded on first use, ~1 GB, cached in "
            "platformdirs user cache dir); one SQL query per station/product over the full "
            "requested year range; no windowing; quality flags from DATA_SYMBOLS table; "
            "no authentication required; partial failures reported as recoverable issues"
        ),
        "catalogue_version": catalogue_date.isoformat(),
        "metadata": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
    }


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
    packaged_catalogue_artifact_from_components(
        provider_info,
        products,
        stations,
        station_products,
        on_issue="raise",
    )


def write_catalogue(catalogue: GeneratedCaEcccCatalogue, out_dir: Path | str) -> None:
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
        station_id = _clean_text(row.get("STATION_NUMBER"))
        if station_id is None or station_id in seen:
            continue

        lat = _to_float(row.get("LATITUDE"))
        lon = _to_float(row.get("LONGITUDE"))
        if lat is None or lon is None:
            continue

        seen.add(station_id)

        yield {
            "provider_id": PROVIDER_ID,
            "station_id": station_id,
            "latitude": lat,
            "longitude": lon,
            "crs": "unknown",
        }


# ---------------------------------------------------------------------------
# Fixture reader — accepts OGC FeatureCollection or array of properties dicts
# ---------------------------------------------------------------------------


def _read_json_fixture(path: Path) -> list[dict[str, object]]:
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except OSError as exc:
        raise FatalContractError(f"Unable to read ca_eccc JSON fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"ca_eccc JSON fixture is not valid JSON: {path}") from exc

    # Accept either a plain array of property dicts or an OGC FeatureCollection.
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, dict)]
    if isinstance(value, dict) and value.get("type") == "FeatureCollection":
        rows = []
        for feat in value.get("features", []):
            if isinstance(feat, dict):
                props = feat.get("properties", {})
                if isinstance(props, dict):
                    rows.append(dict(props))
        return rows
    raise FatalContractError(f"ca_eccc JSON fixture must be an array or OGC FeatureCollection: {path}")


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
    model: CaEcccProductMetadata | CaEcccStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the packaged ca_eccc catalogue artifacts.\n\n"
            "Two modes:\n"
            "  --fixture PATH   Offline. Build from a JSON fixture.\n"
            "  --live           Online. Fetch from ECCC OGC API (no auth required)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, metavar="JSON")
    source.add_argument("--live", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
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

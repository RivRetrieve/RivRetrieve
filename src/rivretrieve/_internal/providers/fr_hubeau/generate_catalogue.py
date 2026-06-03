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
from rivretrieve._internal.providers.fr_hubeau.metadata import (
    FrHubeauProductMetadata,
    FrHubeauStationMetadata,
    FrHubeauStationProductMetadata,
)

PROVIDER_ID = "fr_hubeau"
PROVIDER_NAME = "Hubeau / SCHAPI — French national hydrometric network"
COUNTRY = "France"
STATIONS_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations"
STATIONS_PARAMS = "format=json&size=5000&in_use=true"
AVAILABILITY_REASON = "Hubeau referentiel/stations does not expose per-variable station availability"
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"
MIN_LIVE_STATIONS = 500


@dataclass(frozen=True)
class GeneratedFrHubeauCatalogue:
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
    grandeur_code: str
    native_unit: str
    conversion_factor: float
    notes: str | None

    @property
    def metadata(self) -> FrHubeauProductMetadata:
        return FrHubeauProductMetadata(
            grandeur_hydro=self.grandeur_code,
            native_unit=self.native_unit,
            canonical_unit=self.canonical_unit,
            conversion_factor=self.conversion_factor,
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
        grandeur_code="QmnJ",
        native_unit="l/s",
        conversion_factor=1000.0,
        notes=(
            "Hubeau grandeur QmnJ (débit moyen journalier). "
            "Native unit l/s divided by 1000 to convert to m³/s. "
            "Timestamps are date-only YYYY-MM-DD interpreted as UTC midnight."
        ),
    ),
    ProductDefinition(
        product_id="stage_daily_max",
        observed_property="stage",
        frequency="daily",
        statistic="max",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m",
        grandeur_code="HIXnJ",
        native_unit="mm",
        conversion_factor=1000.0,
        notes=(
            "Hubeau grandeur HIXnJ (hauteur instantanée maximale journalière). "
            "Native unit mm divided by 1000 to convert to m. "
            "Timestamps are date-only YYYY-MM-DD interpreted as UTC midnight."
        ),
    ),
)

EXPECTED_PRODUCT_IDS = frozenset(d.product_id for d in PRODUCT_DEFINITIONS)


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
    product_definitions: Sequence[ProductDefinition] = PRODUCT_DEFINITIONS,
) -> GeneratedFrHubeauCatalogue:
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
) -> GeneratedFrHubeauCatalogue:
    return generate_catalogue(
        _read_live_stations(),
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
) -> GeneratedFrHubeauCatalogue:
    effective_date = catalogue_date or date.today()
    products = build_products(product_definitions)
    stations = build_stations(raw_payload, generator_input=generator_input)
    station_products = build_station_products(stations, product_definitions, effective_date)
    provider_info = build_provider_info(effective_date, generator_input=generator_input)

    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedFrHubeauCatalogue(
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
            "native_id": d.grandeur_code,
            "derived": False,
            "derivation_method": None,
            "metadata": _metadata_json(d.metadata),
        }
        for d in product_definitions
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(
    raw_payload: dict[str, object],
    *,
    generator_input: str = "fixture",
) -> StationCatalog:
    rows = list(_iter_station_rows(raw_payload))
    if not rows:
        raise FatalContractError("fr_hubeau: station build returned no rows with valid coordinates")
    if generator_input == "live" and len(rows) < MIN_LIVE_STATIONS:
        raise FatalContractError(
            f"fr_hubeau: live catalogue returned only {len(rows)} stations "
            f"(expected ≥ {MIN_LIVE_STATIONS}); possible fetch failure"
        )
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
            metadata = FrHubeauStationProductMetadata(
                station_id=station_id,
                product_id=d.product_id,
                grandeur_hydro=d.grandeur_code,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=(
                    "Materialised as availability=unknown; "
                    "referentiel/stations does not guarantee observed data for every grandeur."
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
        "source_url": STATIONS_URL,
        "generator_input": generator_input,
        "obs_elab_url": "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab",
        "timestamp_convention": "date_only_utc_midnight",
    }
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: 365-day window decomposition with paginated obs_elab requests; "
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


def write_catalogue(catalogue: GeneratedFrHubeauCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as f:
        json.dump(catalogue.provider_info, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")


def _iter_station_rows(raw_payload: dict[str, object]):  # type: ignore[return]
    data_list = raw_payload.get("data", [])
    if not isinstance(data_list, list):
        return

    seen: set[str] = set()
    for row in data_list:
        if not isinstance(row, dict):
            continue

        station_id = _clean_text(row.get("code_station"))
        if station_id is None:
            continue
        if station_id in seen:
            continue

        lat = _to_float(row.get("latitude_station"))
        lon = _to_float(row.get("longitude_station"))
        if lat is None or lon is None:
            continue

        seen.add(station_id)

        name = _clean_text(row.get("libelle_station")) or station_id
        river_name = _clean_text(row.get("libelle_cours_eau"))
        elevation_m = _to_float(row.get("altitude_ref_alti_station"))
        drainage_area_km2 = _to_float(row.get("surface_bv_reel_station"))
        commune = _clean_text(row.get("libelle_commune"))
        departement = _clean_text(row.get("libelle_departement"))
        in_service = row.get("en_service")
        if not isinstance(in_service, bool):
            in_service = None
        opening_date = _clean_text(row.get("date_ouverture_station"))

        metadata = FrHubeauStationMetadata(
            native_id=station_id,
            name=name,
            river_name=river_name,
            latitude=lat,
            longitude=lon,
            country=COUNTRY,
            source=PROVIDER_NAME,
            elevation_m=elevation_m,
            drainage_area_km2=drainage_area_km2,
            commune=commune,
            departement=departement,
            in_service=in_service,
            opening_date=opening_date,
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
    model: FrHubeauStationMetadata | FrHubeauProductMetadata | FrHubeauStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _read_fixture_json(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except OSError as exc:
        raise FatalContractError(f"Unable to read fr_hubeau station fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"fr_hubeau station fixture is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FatalContractError("fr_hubeau station fixture must contain a JSON object")
    return cast("dict[str, object]", value)


def _read_live_stations() -> dict[str, object]:
    """Fetch all station pages from Hubeau referentiel/stations and return combined payload."""
    initial_url = f"{STATIONS_URL}?{STATIONS_PARAMS}"
    all_data: list[object] = []
    current_url: str | None = initial_url

    while current_url is not None:
        try:
            with urllib.request.urlopen(current_url, timeout=60) as response:
                if response.status < 200 or response.status >= 300:
                    raise FatalContractError(
                        f"fr_hubeau stations live request failed with HTTP {response.status}: {current_url}"
                    )
                page = json.load(response)
        except OSError as exc:
            raise FatalContractError(f"fr_hubeau stations live request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise FatalContractError(f"fr_hubeau stations live response is not valid JSON: {exc}") from exc

        if not isinstance(page, dict):
            raise FatalContractError("fr_hubeau stations live response must be a JSON object")

        data = page.get("data", [])
        if isinstance(data, list):
            all_data.extend(data)

        next_url_raw = page.get("next")
        current_url = next_url_raw if isinstance(next_url_raw, str) and next_url_raw.strip() else None

    return cast("dict[str, object]", {"data": all_data})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged fr_hubeau catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to a Hubeau referentiel/stations JSON fixture.")
    source.add_argument("--live", action="store_true", help="Fetch the live Hubeau stations endpoint.")
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

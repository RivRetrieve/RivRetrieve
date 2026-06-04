from __future__ import annotations

import argparse
import json
import urllib.request
from collections.abc import Iterator, Sequence
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
from rivretrieve._internal.providers.fr_hubeau.transform import HYDRO_PRODUCT_IDS, TEMP_PRODUCT_IDS

PROVIDER_ID = "fr_hubeau"
PROVIDER_NAME = "Hubeau / SCHAPI — French national hydrometric network"
COUNTRY = "France"

HYDRO_STATIONS_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations"
HYDRO_STATIONS_PARAMS = "format=json&size=5000&in_use=true"
HYDRO_SITES_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/sites"
HYDRO_SITES_PARAMS = "format=json&size=5000"
TEMP_STATIONS_URL = "https://hubeau.eaufrance.fr/api/v1/temperature/station"
TEMP_STATIONS_PARAMS = "size=5000"

AVAILABILITY_REASON = "Hubeau catalogue does not expose per-variable station availability"
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"
MIN_LIVE_HYDRO_STATIONS = 500
MIN_LIVE_TEMP_STATIONS = 50


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
    api_type: str
    grandeur_code: str | None
    native_unit: str
    conversion_factor: float
    notes: str | None

    @property
    def metadata(self) -> FrHubeauProductMetadata:
        return FrHubeauProductMetadata(
            grandeur_code=self.grandeur_code,
            api_type=self.api_type,
            native_unit=self.native_unit,
            canonical_unit=self.canonical_unit,
            conversion_factor=self.conversion_factor,
            notes=self.notes,
        )


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    # --- obs_tr (real-time, ~1 month lookback) --------------------------------
    ProductDefinition(
        product_id="discharge_instantaneous",
        observed_property="discharge",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m3/s",
        api_type="obs_tr",
        grandeur_code="Q",
        native_unit="l/s",
        conversion_factor=1000.0,
        notes=(
            "Hubeau observations_tr grandeur Q (débit). "
            "Native unit l/s divided by 1000 to convert to m³/s. "
            "Timestamps are full UTC ISO 8601 (date_obs). "
            "Real-time only: Hubeau rejects requests older than ~1 month."
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
        api_type="obs_tr",
        grandeur_code="H",
        native_unit="mm",
        conversion_factor=1000.0,
        notes=(
            "Hubeau observations_tr grandeur H (hauteur). "
            "Native unit mm divided by 1000 to convert to m. "
            "Timestamps are full UTC ISO 8601 (date_obs). "
            "Real-time only: Hubeau rejects requests older than ~1 month."
        ),
    ),
    # --- obs_elab (historical archive) ----------------------------------------
    # NOTE: HmnJ (daily mean height) does NOT exist in Hubeau obs_elab.
    # The grandeur_hydro request parameter is ignored by the API; filtering is
    # done by the parser on the grandeur_hydro_elab field in each response row.
    ProductDefinition(
        product_id="discharge_daily_mean",
        observed_property="discharge",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        api_type="obs_elab",
        grandeur_code="QmnJ",
        native_unit="l/s",
        conversion_factor=1000.0,
        notes=(
            "Hubeau obs_elab grandeur QmnJ (débit moyen journalier). "
            "Native unit l/s divided by 1000 to convert to m³/s. "
            "Timestamps are date-only YYYY-MM-DD interpreted as UTC midnight."
        ),
    ),
    ProductDefinition(
        product_id="discharge_daily_max",
        observed_property="discharge",
        frequency="daily",
        statistic="max",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        api_type="obs_elab",
        grandeur_code="QIXnJ",
        native_unit="l/s",
        conversion_factor=1000.0,
        notes=(
            "Hubeau obs_elab grandeur QIXnJ (débit instantané maximal journalier). "
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
        api_type="obs_elab",
        grandeur_code="HIXnJ",
        native_unit="mm",
        conversion_factor=1000.0,
        notes=(
            "Hubeau obs_elab grandeur HIXnJ (hauteur instantanée maximale journalière). "
            "Native unit mm divided by 1000 to convert to m. "
            "Timestamps are date-only YYYY-MM-DD interpreted as UTC midnight. "
            "Note: daily mean height (HmnJ) does not exist in Hubeau obs_elab."
        ),
    ),
    # --- temperature/chronique (historical archive) ---------------------------
    ProductDefinition(
        product_id="water_temperature_instantaneous",
        observed_property="water_temperature",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="degC",
        api_type="temperature",
        grandeur_code=None,
        native_unit="degC",
        conversion_factor=1.0,
        notes=(
            "Hubeau temperature/chronique endpoint. "
            "Temperature in °C, no conversion needed. "
            "Timestamps from date_mesure_temp + heure_mesure_temp, interpreted as UTC."
        ),
    ),
)

HYDRO_PRODUCT_DEFS = tuple(d for d in PRODUCT_DEFINITIONS if d.product_id in HYDRO_PRODUCT_IDS)
TEMP_PRODUCT_DEFS = tuple(d for d in PRODUCT_DEFINITIONS if d.product_id in TEMP_PRODUCT_IDS)
EXPECTED_PRODUCT_IDS = frozenset(d.product_id for d in PRODUCT_DEFINITIONS)


def generate_catalogue_from_fixture(
    hydro_fixture_path: Path | str,
    temp_fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
) -> GeneratedFrHubeauCatalogue:
    return generate_catalogue(
        _read_fixture_json(Path(hydro_fixture_path)),
        _read_fixture_json(Path(temp_fixture_path)),
        catalogue_date=catalogue_date,
        generator_input="fixture",
    )


def generate_catalogue_from_live(
    *,
    catalogue_date: date | None = None,
) -> GeneratedFrHubeauCatalogue:
    hydro_payload = _read_live_stations(HYDRO_STATIONS_URL, HYDRO_STATIONS_PARAMS, "hydrometric")
    temp_payload = _read_live_stations(TEMP_STATIONS_URL, TEMP_STATIONS_PARAMS, "temperature")
    site_lookup = build_site_lookup(_read_live_stations(HYDRO_SITES_URL, HYDRO_SITES_PARAMS, "sites"))
    return generate_catalogue(
        hydro_payload,
        temp_payload,
        site_lookup=site_lookup,
        catalogue_date=catalogue_date,
        generator_input="live",
    )


def generate_catalogue(
    hydro_payload: dict[str, object],
    temp_payload: dict[str, object],
    *,
    site_lookup: dict[str, dict[str, float | None]] | None = None,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedFrHubeauCatalogue:
    effective_date = catalogue_date or date.today()
    products = build_products()
    hydro_stations = build_hydro_stations(hydro_payload, site_lookup=site_lookup, generator_input=generator_input)
    temp_stations = build_temp_stations(temp_payload, generator_input=generator_input)

    # Merge: hydro first, then temp; both sorted by station_id afterwards.
    stations: StationCatalog = pl.concat([hydro_stations, temp_stations]).sort("station_id")

    hydro_ids = hydro_stations["station_id"].to_list()
    temp_ids = temp_stations["station_id"].to_list()
    station_products = build_station_products(
        hydro_station_ids=hydro_ids,
        temp_station_ids=temp_ids,
        catalogue_date=effective_date,
    )

    provider_info = build_provider_info(effective_date, generator_input=generator_input)
    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedFrHubeauCatalogue(
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
            "native_id": d.grandeur_code or d.api_type,
            "derived": False,
            "derivation_method": None,
            "metadata": _metadata_json(d.metadata),
        }
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_site_lookup(sites_payload: dict[str, object]) -> dict[str, dict[str, float | None]]:
    """Build a code_site → {surface_bv, altitude_site} lookup from referentiel/sites response.

    surface_bv: drainage area in km² (~50% coverage across French hydrometric sites).
    altitude_site: site elevation in m (~37% coverage).
    """
    lookup: dict[str, dict[str, float | None]] = {}
    data_list = sites_payload.get("data", [])
    if not isinstance(data_list, list):
        return lookup
    for row in cast(list[dict[str, object]], data_list):
        if not isinstance(row, dict):
            continue
        code_site = _clean_text(row.get("code_site"))
        if code_site is None:
            continue
        lookup[code_site] = {
            "surface_bv": _to_float(row.get("surface_bv")),
            "altitude_site": _to_float(row.get("altitude_site")),
        }
    return lookup


def build_hydro_stations(
    raw_payload: dict[str, object],
    *,
    site_lookup: dict[str, dict[str, float | None]] | None = None,
    generator_input: str = "fixture",
) -> StationCatalog:
    rows = list(_iter_hydro_station_rows(raw_payload, site_lookup=site_lookup))
    if not rows:
        raise FatalContractError("fr_hubeau: hydrometric station build returned no rows with valid coordinates")
    if generator_input == "live" and len(rows) < MIN_LIVE_HYDRO_STATIONS:
        raise FatalContractError(
            f"fr_hubeau: live hydrometric catalogue returned only {len(rows)} stations "
            f"(expected ≥ {MIN_LIVE_HYDRO_STATIONS}); possible fetch failure"
        )
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_temp_stations(
    raw_payload: dict[str, object],
    *,
    generator_input: str = "fixture",
) -> StationCatalog:
    rows = list(_iter_temp_station_rows(raw_payload))
    if generator_input == "live" and len(rows) < MIN_LIVE_TEMP_STATIONS:
        raise FatalContractError(
            f"fr_hubeau: live temperature catalogue returned only {len(rows)} stations "
            f"(expected ≥ {MIN_LIVE_TEMP_STATIONS}); possible fetch failure"
        )
    # Return empty schema-valid DataFrame when fixture has no temp stations.
    if not rows:
        return pl.DataFrame(schema=STATION_CATALOG_SCHEMA.polars_schema)
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(
    *,
    hydro_station_ids: list[object],
    temp_station_ids: list[object],
    catalogue_date: date,
) -> StationProductCatalog:
    rows = []

    for station_id in hydro_station_ids:
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        for d in HYDRO_PRODUCT_DEFS:
            metadata = FrHubeauStationProductMetadata(
                station_id=station_id,
                product_id=d.product_id,
                grandeur_code=d.grandeur_code,
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

    for station_id in temp_station_ids:
        if not isinstance(station_id, str):
            raise FatalContractError("temperature station_id must be a string")
        for d in TEMP_PRODUCT_DEFS:
            metadata = FrHubeauStationProductMetadata(
                station_id=station_id,
                product_id=d.product_id,
                grandeur_code=d.grandeur_code,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=(
                    "Materialised as availability=unknown; "
                    "temperature/station does not guarantee observed data continuity."
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
        "hydro_stations_url": HYDRO_STATIONS_URL,
        "hydro_sites_url": HYDRO_SITES_URL,
        "temp_stations_url": TEMP_STATIONS_URL,
        "obs_elab_url": "https://hubeau.eaufrance.fr/api/v2/hydrometrie/obs_elab",
        "obs_tr_url": "https://hubeau.eaufrance.fr/api/v2/hydrometrie/observations_tr",
        "temperature_url": "https://hubeau.eaufrance.fr/api/v1/temperature/chronique",
        "generator_input": generator_input,
        "timestamp_convention": "obs_elab=date_only_utc_midnight; obs_tr=utc_iso; temperature=utc_iso",
    }
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: 365-day window decomposition with paginated obs_elab, observations_tr, "
            "and temperature/chronique requests; partial failures reported as recoverable issues"
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


# ---------------------------------------------------------------------------
# Station row iterators
# ---------------------------------------------------------------------------


def _iter_hydro_station_rows(
    raw_payload: dict[str, object],
    *,
    site_lookup: dict[str, dict[str, float | None]] | None = None,
) -> Iterator[dict[str, object]]:
    data_list = raw_payload.get("data", [])
    if not isinstance(data_list, list):
        return

    seen: set[str] = set()
    for row in cast(list[dict[str, object]], data_list):
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

        # Station-level altitude (gauge reference elevation, sometimes null).
        elevation_m = _to_float(row.get("altitude_ref_alti_station"))

        # Drainage area: surface_bv_reel_station is never populated in the Hubeau API.
        # Fall back to surface_bv from referentiel/sites via code_site.
        drainage_area_km2 = _to_float(row.get("surface_bv_reel_station"))

        # Enrich from site lookup when station-level fields are missing.
        code_site = _clean_text(row.get("code_site"))
        if site_lookup is not None and code_site is not None and code_site in site_lookup:
            site = site_lookup[code_site]
            if elevation_m is None:
                elevation_m = site.get("altitude_site")
            if drainage_area_km2 is None:
                drainage_area_km2 = site.get("surface_bv")

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
            station_type="hydrometric",
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


def _iter_temp_station_rows(raw_payload: dict[str, object]) -> Iterator[dict[str, object]]:
    data_list = raw_payload.get("data", [])
    if not isinstance(data_list, list):
        return

    seen: set[str] = set()
    for row in cast(list[dict[str, object]], data_list):
        if not isinstance(row, dict):
            continue

        station_id = _clean_text(row.get("code_station"))
        if station_id is None:
            continue
        if station_id in seen:
            continue

        # Temperature API uses 'latitude'/'longitude', not '*_station' variants.
        lat = _to_float(row.get("latitude"))
        lon = _to_float(row.get("longitude"))
        if lat is None or lon is None:
            continue

        seen.add(station_id)

        name = _clean_text(row.get("libelle_station")) or station_id
        river_name = _clean_text(row.get("libelle_cours_eau") or row.get("libelle_masse_eau"))
        elevation_m = _to_float(row.get("altitude"))
        # superficie_reelle is available in some records (km²).
        drainage_area_km2 = _to_float(row.get("superficie_reelle"))
        commune = _clean_text(row.get("libelle_commune"))
        departement = _clean_text(row.get("libelle_departement"))
        opening_date = _clean_text(row.get("date_mise_en_service"))

        metadata = FrHubeauStationMetadata(
            native_id=station_id,
            name=name,
            river_name=river_name,
            latitude=lat,
            longitude=lon,
            country=COUNTRY,
            source=PROVIDER_NAME,
            station_type="temperature",
            elevation_m=elevation_m,
            drainage_area_km2=drainage_area_km2,
            commune=commune,
            departement=departement,
            in_service=None,
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


# ---------------------------------------------------------------------------
# Live fetchers
# ---------------------------------------------------------------------------


def _read_live_stations(base_url: str, query_params: str, label: str) -> dict[str, object]:
    """Fetch all pages from a Hubeau station catalogue endpoint."""
    initial_url = f"{base_url}?{query_params}"
    all_data: list[object] = []
    current_url: str | None = initial_url

    while current_url is not None:
        try:
            with urllib.request.urlopen(current_url, timeout=60) as response:
                if response.status < 200 or response.status >= 300:
                    raise FatalContractError(
                        f"fr_hubeau {label} stations live request failed with HTTP {response.status}: {current_url}"
                    )
                page = json.load(response)
        except OSError as exc:
            raise FatalContractError(f"fr_hubeau {label} stations live request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise FatalContractError(f"fr_hubeau {label} stations live response is not valid JSON: {exc}") from exc

        if not isinstance(page, dict):
            raise FatalContractError(f"fr_hubeau {label} stations live response must be a JSON object")

        data = page.get("data", [])
        if isinstance(data, list):
            all_data.extend(data)

        next_url_raw = page.get("next")
        current_url = next_url_raw if isinstance(next_url_raw, str) and next_url_raw.strip() else None

    return cast("dict[str, object]", {"data": all_data})


def _read_fixture_json(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except OSError as exc:
        raise FatalContractError(f"Unable to read fr_hubeau fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"fr_hubeau fixture is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FatalContractError("fr_hubeau fixture must contain a JSON object")
    return cast("dict[str, object]", value)


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
    model: FrHubeauStationMetadata | FrHubeauProductMetadata | FrHubeauStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged fr_hubeau catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--hydro-fixture", type=Path, help="Path to a Hubeau referentiel/stations JSON fixture.")
    source.add_argument("--live", action="store_true", help="Fetch live Hubeau station endpoints.")
    parser.add_argument(
        "--temp-fixture",
        type=Path,
        help="Path to a Hubeau temperature/station JSON fixture (used with --hydro-fixture).",
    )
    parser.add_argument("--out", type=Path, required=True, help="Output directory for provider.json and parquet files.")
    parser.add_argument("--catalogue-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)

    if args.live:
        catalogue = generate_catalogue_from_live(catalogue_date=args.catalogue_date)
    else:
        temp_path = args.temp_fixture
        if temp_path is None:
            parser.error("--temp-fixture is required when using --hydro-fixture")
        catalogue = generate_catalogue_from_fixture(args.hydro_fixture, temp_path, catalogue_date=args.catalogue_date)
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

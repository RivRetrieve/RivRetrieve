from __future__ import annotations

import argparse
import json
import os
import time
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
from rivretrieve._internal.providers.br_ana.metadata import (
    BrAnaProductMetadata,
    BrAnaStationMetadata,
    BrAnaStationProductMetadata,
)

PROVIDER_ID = "br_ana"
PROVIDER_NAME = "ANA Hidroweb — Brazilian National Water and Sanitation Agency"
COUNTRY = "Brazil"

AUTH_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/OAUth/v1"
METADATA_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroInventarioEstacoes/v1"
DISCHARGE_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroSerieVazao/v1"
STAGE_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroSerieCotas/v1"

AVAILABILITY_REASON = "ANA catalogue does not expose per-variable station availability"
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"

# Brazil has 26 states + 1 Federal District.
BRAZIL_STATES = [
    "AC",
    "AL",
    "AM",
    "AP",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
]

MIN_LIVE_STATIONS = 1000


@dataclass(frozen=True)
class GeneratedBrAnaCatalogue:
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
    day_column_prefix: str
    api_endpoint: str
    native_unit: str
    conversion_factor: float
    notes: str | None

    @property
    def metadata(self) -> BrAnaProductMetadata:
        return BrAnaProductMetadata(
            day_column_prefix=self.day_column_prefix,
            api_endpoint=self.api_endpoint,
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
        day_column_prefix="Vazao_",
        api_endpoint=DISCHARGE_URL,
        native_unit="m3/s",
        conversion_factor=1.0,
        notes=(
            "ANA Hidroweb HidroSerieVazao/v1. "
            "Daily mean discharge in m³/s (no unit conversion needed). "
            "Timestamps are date-only, reconstructed from year/month/day columns "
            "and interpreted as UTC midnight (T00:00:00Z). "
            "True local timezone is undocumented (likely Brasília Standard Time, UTC-3)."
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
        day_column_prefix="Cota_",
        api_endpoint=STAGE_URL,
        native_unit="cm",
        conversion_factor=100.0,
        notes=(
            "ANA Hidroweb HidroSerieCotas/v1. "
            "Daily mean stage in cm, divided by 100 to convert to m. "
            "Raw cm value preserved in raw_value row annotation. "
            "Timestamps are date-only, reconstructed from year/month/day columns "
            "and interpreted as UTC midnight (T00:00:00Z). "
            "True local timezone is undocumented (likely Brasília Standard Time, UTC-3)."
        ),
    ),
)

EXPECTED_PRODUCT_IDS = frozenset(d.product_id for d in PRODUCT_DEFINITIONS)


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
) -> GeneratedBrAnaCatalogue:
    raw = _read_fixture_json(Path(fixture_path))
    return generate_catalogue(
        raw,
        catalogue_date=catalogue_date,
        generator_input="fixture",
    )


def generate_catalogue_from_live(
    *,
    catalogue_date: date | None = None,
    username: str | None = None,
    password: str | None = None,
) -> GeneratedBrAnaCatalogue:
    username = username or os.environ.get("ANA_IDENTIFICADOR")
    password = password or os.environ.get("ANA_SENHA")
    if not username or not password:
        raise FatalContractError("br_ana live catalogue generation requires ANA_IDENTIFICADOR and ANA_SENHA env vars")
    token = _fetch_token(username, password)
    raw_payload = _fetch_all_stations(token)
    return generate_catalogue(
        raw_payload,
        catalogue_date=catalogue_date,
        generator_input="live",
    )


def generate_catalogue(
    raw_payload: list[dict[str, object]],
    *,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedBrAnaCatalogue:
    effective_date = catalogue_date or date.today()
    products = build_products()
    stations = build_stations(raw_payload, generator_input=generator_input)
    station_ids = stations["station_id"].to_list()
    station_products = build_station_products(station_ids=station_ids, catalogue_date=effective_date)
    provider_info = build_provider_info(effective_date, generator_input=generator_input)
    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedBrAnaCatalogue(
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
            "native_id": d.day_column_prefix.rstrip("_"),
            "derived": False,
            "derivation_method": None,
            "metadata": _metadata_json(d.metadata),
        }
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(
    raw_payload: list[dict[str, object]],
    *,
    generator_input: str = "fixture",
) -> StationCatalog:
    rows = list(_iter_station_rows(raw_payload))
    if not rows:
        raise FatalContractError("br_ana: station build returned no rows")
    if generator_input == "live" and len(rows) < MIN_LIVE_STATIONS:
        raise FatalContractError(
            f"br_ana: live catalogue returned only {len(rows)} stations "
            f"(expected ≥ {MIN_LIVE_STATIONS}); possible fetch failure"
        )
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(
    *,
    station_ids: list[object],
    catalogue_date: date,
) -> StationProductCatalog:
    rows = []
    for station_id in station_ids:
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        for d in PRODUCT_DEFINITIONS:
            metadata = BrAnaStationProductMetadata(
                station_id=station_id,
                product_id=d.product_id,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=(
                    "Materialised as availability=unknown; "
                    "ANA inventory endpoint does not guarantee observed data for each variable."
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
        "auth_url": AUTH_URL,
        "metadata_url": METADATA_URL,
        "discharge_url": DISCHARGE_URL,
        "stage_url": STAGE_URL,
        "generator_input": generator_input,
        "timestamp_convention": "date_only_utc_midnight",
        "credential_requirement": "ANA_IDENTIFICADOR and ANA_SENHA env vars required for live catalogue and observations",
    }
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: annual window decomposition; requires ANA_IDENTIFICADOR/ANA_SENHA; "
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


def write_catalogue(catalogue: GeneratedBrAnaCatalogue, out_dir: Path | str) -> None:
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


def _iter_station_rows(raw_payload: list[dict[str, object]]):  # type: ignore[return]
    seen: set[str] = set()
    for row in raw_payload:
        if not isinstance(row, dict):
            continue

        station_id = _clean_text(row.get("codigoestacao"))
        if station_id is None:
            continue
        if station_id in seen:
            continue

        lat = _to_float(row.get("Latitude"))
        lon = _to_float(row.get("Longitude"))
        if lat is None or lon is None:
            continue

        seen.add(station_id)

        name = _clean_text(row.get("Estacao_Nome")) or station_id
        basin_name = _clean_text(row.get("Bacia_Nome"))
        elevation_m = _to_float(row.get("Altitude"))
        drainage_area_km2 = _to_float(row.get("Area_Drenagem"))

        metadata = BrAnaStationMetadata(
            native_id=station_id,
            name=name,
            basin_name=basin_name,
            latitude=lat,
            longitude=lon,
            country=COUNTRY,
            elevation_m=elevation_m,
            drainage_area_km2=drainage_area_km2,
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


def _fetch_token(username: str, password: str) -> str:
    req = urllib.request.Request(
        AUTH_URL,
        headers={"accept": "*/*", "Identificador": username, "Senha": password},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.load(response)
    except OSError as exc:
        raise FatalContractError(f"br_ana auth request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"br_ana auth response is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise FatalContractError("br_ana auth response must be a JSON object")

    items = data.get("items")
    if not isinstance(items, dict):
        raise FatalContractError(f"br_ana auth failed: {data.get('message', 'unknown error')}")

    token = items.get("tokenautenticacao")
    if not isinstance(token, str) or not token.strip():
        raise FatalContractError("br_ana auth response did not return a token")
    return token


def _fetch_all_stations(token: str) -> list[dict[str, object]]:
    all_stations: list[dict[str, object]] = []
    headers = {"accept": "*/*", "Authorization": f"Bearer {token}"}

    for state in BRAZIL_STATES:
        url = f"{METADATA_URL}?Unidade%20Federativa={state}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                data = json.load(response)
        except OSError as exc:
            raise FatalContractError(f"br_ana metadata request failed for state {state}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise FatalContractError(f"br_ana metadata response is not valid JSON for state {state}: {exc}") from exc

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    all_stations.append(cast("dict[str, object]", item))
        elif isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        all_stations.append(cast("dict[str, object]", item))

        time.sleep(0.1)

    return all_stations


def _read_fixture_json(path: Path) -> list[dict[str, object]]:
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except OSError as exc:
        raise FatalContractError(f"Unable to read br_ana fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"br_ana fixture is not valid JSON: {path}") from exc
    if isinstance(value, list):
        return cast("list[dict[str, object]]", value)
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            return cast("list[dict[str, object]]", items)
        raise FatalContractError("br_ana fixture dict must have an 'items' list")
    raise FatalContractError("br_ana fixture must be a JSON array or object with 'items'")


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
    model: BrAnaStationMetadata | BrAnaProductMetadata | BrAnaStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged br_ana catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to a HidroInventarioEstacoes JSON fixture.")
    source.add_argument("--live", action="store_true", help="Fetch live ANA Hidroweb station metadata.")
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

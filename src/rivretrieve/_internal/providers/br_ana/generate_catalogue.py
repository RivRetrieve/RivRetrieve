"""Brazil catalogue build : ProviderStationPayload → GeneratedBrAnaCatalogue."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
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

PROVIDER_ID = "br_ana"
PROVIDER_NAME = "ANA Hidroweb — Brazilian National Water and Sanitation Agency"

AUTH_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/OAUth/v1"
METADATA_URL = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroInventarioEstacoes/v1"
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
    day_column_prefix: str | None = None  # "Vazao_" / "Cota_" — daily columnar series
    native_field: str | None = None  # "Vazao_Adotada" etc. — telemetric/instantaneous series

    @property
    def native_id(self) -> str:
        if self.day_column_prefix is not None:
            return self.day_column_prefix.rstrip("_")
        return self.native_field or self.product_id


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
    ),
    ProductDefinition(
        product_id="discharge_instantaneous",
        observed_property="discharge",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        native_field="Vazao_Adotada",
    ),
    ProductDefinition(
        product_id="stage_instantaneous",
        observed_property="stage",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="provider_defined",
        canonical_unit="m",
        native_field="Cota_Adotada",
    ),
    ProductDefinition(
        product_id="water_temperature_instantaneous",
        observed_property="water_temperature",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="provider_defined",
        canonical_unit="degC",
        native_field="Temperatura_Agua",
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
            "native_id": d.native_id,
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
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
                    "availability": "unknown",
                    "availability_reason": AVAILABILITY_REASON,
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": catalogue_date,
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

        # Keep only stations relevant to our supported products: discharge
        # (Tipo_Estacao_Desc_Liquida), stage/level (Tipo_Estacao_Escala), or
        # water quality (Tipo_Estacao_Qual_Agua). Stations with none of these
        # flags set are e.g. pure rain-gauge (pluviométrica) stations and are
        # out of scope for the discharge_daily_mean / stage_daily_mean
        # products this provider port supports.
        # NOTE: field names confirmed against the live HidroInventarioEstacoes
        # response schema (underscore-separated, matching Estacao_Nome /
        # Bacia_Nome convention) — NOT the camelCase names from the R
        # hydrodownloadR adapter (TipoEstacaoDescLiquida etc.), which do not
        # match the live JSON payload.
        has_discharge = _to_bool(row.get("Tipo_Estacao_Desc_Liquida"))
        has_level = _to_bool(row.get("Tipo_Estacao_Escala"))
        has_quality = _to_bool(row.get("Tipo_Estacao_Qual_Agua"))
        if not (has_discharge or has_level or has_quality):
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


# ANA's gateway intermittently returns transient 5xx errors (observed: HTTP 504
# Gateway Time-out) under load — confirmed via direct curl testing, unrelated to
# our request shape. Retrying with backoff lets a ~10+ minute, 27-state sequential
# fetch survive a single flaky state instead of failing the whole run.
_METADATA_FETCH_MAX_ATTEMPTS = 4
_METADATA_FETCH_RETRY_BASE_SECONDS = 5.0


def _fetch_state_stations(state: str, headers: dict[str, str]) -> object:
    url = f"{METADATA_URL}?Unidade%20Federativa={state}"
    last_exc: Exception | None = None
    for attempt in range(1, _METADATA_FETCH_MAX_ATTEMPTS + 1):
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code < 500 or attempt == _METADATA_FETCH_MAX_ATTEMPTS:
                raise FatalContractError(f"br_ana metadata request failed for state {state}: {exc}") from exc
        except OSError as exc:
            last_exc = exc
            if attempt == _METADATA_FETCH_MAX_ATTEMPTS:
                raise FatalContractError(f"br_ana metadata request failed for state {state}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise FatalContractError(f"br_ana metadata response is not valid JSON for state {state}: {exc}") from exc

        backoff = _METADATA_FETCH_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
        print(
            f"  [br_ana catalogue] state {state}: transient error ({last_exc}); "
            f"retrying in {backoff:.0f}s (attempt {attempt}/{_METADATA_FETCH_MAX_ATTEMPTS})"
        )
        time.sleep(backoff)

    # Unreachable — loop always returns or raises — but keeps type-checkers happy.
    raise FatalContractError(f"br_ana metadata request failed for state {state}: {last_exc}")


def _fetch_all_stations(token: str) -> list[dict[str, object]]:
    all_stations: list[dict[str, object]] = []
    headers = {"accept": "*/*", "Authorization": f"Bearer {token}"}

    for state in BRAZIL_STATES:
        data = _fetch_state_stations(state, headers)

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    all_stations.append(cast("dict[str, object]", item))
        elif isinstance(data, dict):
            items = cast("dict[str, object]", data).get("items")
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


_TRUTHY_TEXT = {"sim", "true", "1", "s", "y", "yes"}


def _to_bool(value: Any) -> bool:
    """Tolerantly parse ANA's station-type flags.

    ANA's inventory encodes these as booleans, integers (0/1), or Portuguese
    yes/no strings ("Sim"/"Não") depending on the endpoint/response variant.
    Anything that cannot be confidently read as truthy is treated as False.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    text = str(value).strip().lower()
    return text in _TRUTHY_TEXT


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

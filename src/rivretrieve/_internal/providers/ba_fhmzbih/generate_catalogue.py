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
from rivretrieve._internal.providers.ba_fhmzbih.metadata import (
    BaFhmzbihProductMetadata,
    BaFhmzbihStationProductMetadata,
)

PROVIDER_ID = "ba_fhmzbih"
PROVIDER_NAME = "FHMZBiH — Federal Hydrometeorological Institute of Bosnia and Herzegovina (vodostaji.voda.ba)"

METADATA_URL = "https://vodostaji.voda.ba/data/internet/layers/20/index.json"
WORKBOOK_URL_TEMPLATE = "https://vodostaji.voda.ba/data/internet/stations/{group}/{station_id}/{code}/{file}"

AVAILABILITY_REASON = "FHMZBiH metadata snapshot does not expose per-variable station availability"
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"

MIN_LIVE_STATIONS = 30


@dataclass(frozen=True)
class GeneratedBaFhmzbihCatalogue:
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
    parameter_code: str
    workbook_file: str
    native_unit: str
    conversion_factor: float
    aggregate_daily: bool
    notes: str

    @property
    def metadata(self) -> BaFhmzbihProductMetadata:
        return BaFhmzbihProductMetadata(
            parameter_code=self.parameter_code,
            workbook_file=self.workbook_file,
            native_unit=self.native_unit,
            canonical_unit=self.canonical_unit,
            unit_conversion=None if self.conversion_factor == 1.0 else f"divide by {self.conversion_factor:g}",
            aggregate_daily=self.aggregate_daily,
            notes=self.notes,
        )


_TIMEZONE_NOTE = (
    "Timestamps are published as naive local time with no UTC offset; "
    "interpreted as Europe/Sarajevo local time (CET/CEST, EU DST) and converted to UTC."
)

_ROLLING_WINDOW_NOTE = (
    "The workbook always contains a rolling ~1-year window of hourly observations "
    "ending at the most recent reading; arbitrary historical date ranges are not queryable."
)

PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        product_id="discharge_instantaneous",
        observed_property="discharge",
        frequency="hourly",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m3/s",
        parameter_code="Q",
        workbook_file="Q_1Y.xlsx",
        native_unit="m3/s",
        conversion_factor=1.0,
        aggregate_daily=False,
        notes=f"FHMZBiH hourly discharge, m3/s direct (no conversion). {_TIMEZONE_NOTE} {_ROLLING_WINDOW_NOTE}",
    ),
    ProductDefinition(
        product_id="discharge_daily_mean",
        observed_property="discharge",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        parameter_code="Q",
        workbook_file="Q_1Y.xlsx",
        native_unit="m3/s",
        conversion_factor=1.0,
        aggregate_daily=True,
        notes=(
            "Derived by averaging hourly readings over each Europe/Sarajevo calendar day "
            f"and anchoring the result at local midnight before UTC conversion. {_TIMEZONE_NOTE} {_ROLLING_WINDOW_NOTE}"
        ),
    ),
    ProductDefinition(
        product_id="stage_instantaneous",
        observed_property="stage",
        frequency="hourly",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m",
        parameter_code="H",
        workbook_file="H_1Y.xlsx",
        native_unit="cm",
        conversion_factor=100.0,
        aggregate_daily=False,
        notes=(
            "FHMZBiH hourly stage in cm, divided by 100 to convert to m. "
            f"Raw cm value preserved in raw_value row annotation. {_TIMEZONE_NOTE} {_ROLLING_WINDOW_NOTE}"
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
        parameter_code="H",
        workbook_file="H_1Y.xlsx",
        native_unit="cm",
        conversion_factor=100.0,
        aggregate_daily=True,
        notes=(
            "Derived by averaging hourly cm readings over each Europe/Sarajevo calendar day, "
            "converting the mean to m, and anchoring the result at local midnight before UTC "
            f"conversion. {_TIMEZONE_NOTE} {_ROLLING_WINDOW_NOTE}"
        ),
    ),
    ProductDefinition(
        product_id="water_temperature_instantaneous",
        observed_property="water_temperature",
        frequency="hourly",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="degC",
        parameter_code="WT",
        workbook_file="Tvode_1Y.xlsx",
        native_unit="degC",
        conversion_factor=1.0,
        aggregate_daily=False,
        notes=f"FHMZBiH hourly water temperature, degC direct (no conversion). {_TIMEZONE_NOTE} {_ROLLING_WINDOW_NOTE}",
    ),
    ProductDefinition(
        product_id="water_temperature_daily_mean",
        observed_property="water_temperature",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="degC",
        parameter_code="WT",
        workbook_file="Tvode_1Y.xlsx",
        native_unit="degC",
        conversion_factor=1.0,
        aggregate_daily=True,
        notes=(
            "Derived by averaging hourly readings over each Europe/Sarajevo calendar day "
            f"and anchoring the result at local midnight before UTC conversion. {_TIMEZONE_NOTE} {_ROLLING_WINDOW_NOTE}"
        ),
    ),
)

EXPECTED_PRODUCT_IDS = frozenset(d.product_id for d in PRODUCT_DEFINITIONS)


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
) -> GeneratedBaFhmzbihCatalogue:
    raw = _read_fixture_json(Path(fixture_path))
    return generate_catalogue(raw, catalogue_date=catalogue_date, generator_input="fixture")


def generate_catalogue_from_live(
    *,
    catalogue_date: date | None = None,
) -> GeneratedBaFhmzbihCatalogue:
    raw_payload = _fetch_live_metadata()
    return generate_catalogue(raw_payload, catalogue_date=catalogue_date, generator_input="live")


def generate_catalogue(
    raw_payload: list[dict[str, object]],
    *,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedBaFhmzbihCatalogue:
    effective_date = catalogue_date or date.today()
    products = build_products()
    stations = build_stations(raw_payload, generator_input=generator_input)
    station_ids = stations["station_id"].to_list()
    station_products = build_station_products(station_ids=station_ids, catalogue_date=effective_date)
    provider_info = build_provider_info(effective_date, generator_input=generator_input)
    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedBaFhmzbihCatalogue(
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
            "native_id": d.parameter_code,
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
        raise FatalContractError("ba_fhmzbih: station build returned no rows")
    if generator_input == "live" and len(rows) < MIN_LIVE_STATIONS:
        raise FatalContractError(
            f"ba_fhmzbih: live catalogue returned only {len(rows)} stations "
            f"(expected >= {MIN_LIVE_STATIONS}); possible fetch failure"
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
            metadata = BaFhmzbihStationProductMetadata(
                station_id=station_id,
                product_id=d.product_id,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=(
                    "Materialised as availability=unknown; the station metadata snapshot "
                    "does not indicate which parameters a station actually reports, and "
                    "workbooks for unreported parameters return zero rows."
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
        "metadata_url": METADATA_URL,
        "workbook_url_template": WORKBOOK_URL_TEMPLATE,
        "generator_input": generator_input,
        "timestamp_convention": "local_to_utc_conversion",
        "source_timezone": "Europe/Sarajevo",
        "rolling_window_note": _ROLLING_WINDOW_NOTE,
        "station_groups": "1-10 (discovered per-station by URL probing; not exposed in metadata)",
    }
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: per (station, parameter) workbook fetch shared across instantaneous/daily-mean "
            "variants; partial failures reported as recoverable issues; only a rolling ~1-year "
            "window of history is available from the source"
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


def write_catalogue(catalogue: GeneratedBaFhmzbihCatalogue, out_dir: Path | str) -> None:
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

        station_id = _clean_text(row.get("metadata_station_no"))
        if station_id is None:
            continue
        if station_id in seen:
            continue

        lat = _to_float(row.get("metadata_station_latitude"))
        lon = _to_float(row.get("metadata_station_longitude"))
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
# Live fetchers
# ---------------------------------------------------------------------------


def _fetch_live_metadata() -> list[dict[str, object]]:
    req = urllib.request.Request(METADATA_URL, headers={"accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.load(response)
    except OSError as exc:
        raise FatalContractError(f"ba_fhmzbih metadata request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"ba_fhmzbih metadata response is not valid JSON: {exc}") from exc

    if isinstance(data, list):
        return [cast("dict[str, object]", item) for item in data if isinstance(item, dict)]
    raise FatalContractError("ba_fhmzbih live metadata response must be a JSON array")


def _read_fixture_json(path: Path) -> list[dict[str, object]]:
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except OSError as exc:
        raise FatalContractError(f"Unable to read ba_fhmzbih fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"ba_fhmzbih fixture is not valid JSON: {path}") from exc
    if isinstance(value, list):
        return cast("list[dict[str, object]]", value)
    raise FatalContractError("ba_fhmzbih fixture must be a JSON array")


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
    model: BaFhmzbihProductMetadata | BaFhmzbihStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged ba_fhmzbih catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to a layers/20/index.json metadata fixture.")
    source.add_argument("--live", action="store_true", help="Fetch the live FHMZBiH station metadata snapshot.")
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

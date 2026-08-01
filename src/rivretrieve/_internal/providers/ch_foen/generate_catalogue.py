from __future__ import annotations

import argparse
import json
import urllib.request
from collections.abc import Mapping, Sequence
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
from rivretrieve._internal.providers.ch_foen.metadata import (
    ChFoenProductMetadata,
    ChFoenStationProductMetadata,
)

PROVIDER_ID = "ch_foen"
PROVIDER_NAME = "Swiss Federal Office for the Environment FOEN / BAFU"
SOURCE_URL = "https://api.existenz.ch/apiv1/hydro/locations"
LEGACY_SOURCE = "thirdparty/RivRetrieve-Python @ origin/switzerland"
AVAILABILITY_REASON = "Existenz.ch locations catalogue does not expose per-variable station availability"
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"


@dataclass(frozen=True)
class GeneratedChFoenCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog


@dataclass(frozen=True)
class ProductDefinition:
    legacy_variable: str
    product_id: str
    observed_property: str
    frequency: str
    statistic: str
    period_type: str
    period_anchor: str
    unit: str
    parameters: tuple[str, ...]
    preferred_parameter: str
    fallback_parameter: str | None
    aggregate_daily: bool
    notes: str | None

    @property
    def metadata(self) -> ChFoenProductMetadata:
        return ChFoenProductMetadata(
            legacy_variable=self.legacy_variable,
            native_id=self.preferred_parameter,
            parameters=self.parameters,
            preferred_parameter=self.preferred_parameter,
            fallback_parameter=self.fallback_parameter,
            aggregate_daily=self.aggregate_daily,
            legacy_unit=self.unit,
            notes=self.notes,
        )


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        legacy_variable="DISCHARGE_DAILY_MEAN",
        product_id="discharge_daily_mean",
        observed_property="discharge",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        unit="m3/s",
        parameters=("flow", "flow_ls"),
        preferred_parameter="flow",
        fallback_parameter="flow_ls",
        aggregate_daily=True,
        notes="Legacy fetcher aggregates preferred flow or fallback flow_ls values to daily means.",
    ),
    ProductDefinition(
        legacy_variable="DISCHARGE_INSTANT",
        product_id="discharge_instantaneous",
        observed_property="discharge",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        unit="m3/s",
        parameters=("flow", "flow_ls"),
        preferred_parameter="flow",
        fallback_parameter="flow_ls",
        aggregate_daily=False,
        notes="Legacy fetcher prefers flow over flow_ls when both are present.",
    ),
    ProductDefinition(
        legacy_variable="STAGE_DAILY_MEAN",
        product_id="stage_daily_mean",
        observed_property="stage",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        unit="m",
        parameters=("height_abs", "height"),
        preferred_parameter="height_abs",
        fallback_parameter="height",
        aggregate_daily=True,
        notes="Legacy fetcher aggregates preferred height_abs or fallback height values to daily means.",
    ),
    ProductDefinition(
        legacy_variable="STAGE_INSTANT",
        product_id="stage_instantaneous",
        observed_property="stage",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        unit="m",
        parameters=("height_abs", "height"),
        preferred_parameter="height_abs",
        fallback_parameter="height",
        aggregate_daily=False,
        notes="Legacy fetcher prefers height_abs over height when both are present.",
    ),
    ProductDefinition(
        legacy_variable="WATER_TEMPERATURE_DAILY_MEAN",
        product_id="water_temperature_daily_mean",
        observed_property="water_temperature",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        unit="degC",
        parameters=("temperature",),
        preferred_parameter="temperature",
        fallback_parameter=None,
        aggregate_daily=True,
        notes="Legacy fetcher aggregates temperature values to daily means.",
    ),
    ProductDefinition(
        legacy_variable="WATER_TEMPERATURE_INSTANT",
        product_id="water_temperature_instantaneous",
        observed_property="water_temperature",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        unit="degC",
        parameters=("temperature",),
        preferred_parameter="temperature",
        fallback_parameter=None,
        aggregate_daily=False,
        notes=None,
    ),
)

EXPECTED_LEGACY_VARIABLES = frozenset(definition.legacy_variable for definition in PRODUCT_DEFINITIONS)


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
    product_definitions: Sequence[ProductDefinition] = PRODUCT_DEFINITIONS,
) -> GeneratedChFoenCatalogue:
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
) -> GeneratedChFoenCatalogue:
    return generate_catalogue(
        _read_live_json(SOURCE_URL),
        catalogue_date=catalogue_date,
        product_definitions=product_definitions,
        generator_input="live",
    )


def generate_catalogue(
    raw_payload: Mapping[str, object],
    *,
    catalogue_date: date | None = None,
    product_definitions: Sequence[ProductDefinition] = PRODUCT_DEFINITIONS,
    generator_input: str = "fixture",
) -> GeneratedChFoenCatalogue:
    effective_date = catalogue_date or date.today()
    payload = _station_payload(raw_payload)
    products = build_products(product_definitions)
    stations = build_stations(payload)
    station_products = build_station_products(stations, product_definitions, effective_date)
    provider_info = build_provider_info(raw_payload, effective_date, generator_input=generator_input)

    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedChFoenCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=station_products,
    )


def build_products(product_definitions: Sequence[ProductDefinition] = PRODUCT_DEFINITIONS) -> ProductCatalog:
    _validate_product_definitions(product_definitions)
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "product_id": definition.product_id,
            "observed_property": definition.observed_property,
            "frequency": definition.frequency,
            "statistic": definition.statistic,
            "period_type": definition.period_type,
            "period_anchor": definition.period_anchor,
            "unit": definition.unit,
            "native_id": definition.preferred_parameter,
            "derived": False,
            "derivation_method": None,
            "metadata": _metadata_json(definition.metadata),
        }
        for definition in product_definitions
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(payload: Mapping[str, object]) -> StationCatalog:
    rows = [_station_row(station_key, station) for station_key, station in payload.items()]
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
        for definition in product_definitions:
            metadata = ChFoenStationProductMetadata(
                station_id=station_id,
                product_id=definition.product_id,
                native_parameters=definition.parameters,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=(
                    "M3 materializes the known provider station-product universe with availability=unknown; "
                    "the locations catalogue does not guarantee observed data for every product."
                ),
            )
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": definition.product_id,
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
    raw_payload: Mapping[str, object],
    catalogue_date: date,
    *,
    generator_input: str,
) -> dict[str, object]:
    metadata = {
        "source_url": SOURCE_URL,
        "legacy_source": LEGACY_SOURCE,
        "generator_input": generator_input,
        "fixture_source": _optional_string(raw_payload.get("source")),
        "fixture_apiurl": _optional_string(raw_payload.get("apiurl")),
        "fixture_opendata": _optional_string(raw_payload.get("opendata")),
        "fixture_license": _optional_string(raw_payload.get("license")),
    }
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: 366-day window decomposition with stitched N x M station-product requests; partial failures reported "
            "as recoverable issues"
        ),
        "catalogue_version": catalogue_date.isoformat(),
        "metadata": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
    }


def validate_generated_catalogue(
    provider_info: Mapping[str, object],
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


def write_catalogue(catalogue: GeneratedChFoenCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as file:
        json.dump(catalogue.provider_info, file, sort_keys=True, separators=(",", ":"))
        file.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")


def _station_row(station_key: str, station: object) -> dict[str, object]:
    if not isinstance(station, dict):
        raise FatalContractError(f"Station {station_key} must be an object")
    station_data = cast("dict[str, object]", station)
    details = station_data.get("details")
    if not isinstance(details, dict):
        raise FatalContractError(f"Station {station_key} is missing details")
    details_data = cast("dict[str, object]", details)

    station_id_raw = details_data.get("id") or station_key
    native_id = _required_string(str(station_id_raw).strip(), f"Station {station_key} id")
    latitude = _required_float(details_data.get("lat"), f"Station {station_key} latitude")
    longitude = _required_float(details_data.get("lon"), f"Station {station_key} longitude")
    return {
        "provider_id": PROVIDER_ID,
        "station_id": native_id,
        "latitude": latitude,
        "longitude": longitude,
        "crs": "unknown",
    }


def _station_payload(raw_payload: Mapping[str, object]) -> Mapping[str, object]:
    payload = raw_payload.get("payload")
    if not isinstance(payload, dict) or not payload:
        raise FatalContractError("Swiss metadata fixture must contain a non-empty object payload")
    return cast("Mapping[str, object]", payload)


def _read_fixture_json(path: Path) -> Mapping[str, object]:
    try:
        with path.open(encoding="utf-8") as file:
            value = json.load(file)
    except OSError as exc:
        raise FatalContractError(f"Unable to read Swiss metadata fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"Swiss metadata fixture is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FatalContractError("Swiss metadata fixture must contain a JSON object")
    return cast("Mapping[str, object]", value)


def _read_live_json(url: str) -> Mapping[str, object]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status < 200 or response.status >= 300:
                raise FatalContractError(f"Swiss metadata live request failed with HTTP {response.status}")
            value = json.load(response)
    except OSError as exc:
        raise FatalContractError("Swiss metadata live request failed") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError("Swiss metadata live response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise FatalContractError("Swiss metadata live response must contain a JSON object")
    return cast("Mapping[str, object]", value)


def _validate_product_definitions(product_definitions: Sequence[ProductDefinition]) -> None:
    observed = frozenset(definition.legacy_variable for definition in product_definitions)
    if observed != EXPECTED_LEGACY_VARIABLES:
        missing = sorted(EXPECTED_LEGACY_VARIABLES - observed)
        unknown = sorted(observed - EXPECTED_LEGACY_VARIABLES)
        parts = []
        if missing:
            parts.append(f"missing: {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown: {', '.join(unknown)}")
        raise FatalContractError(f"Swiss product definition drift ({'; '.join(parts)})")
    for definition in product_definitions:
        if definition.preferred_parameter not in definition.parameters:
            raise FatalContractError(f"{definition.legacy_variable} preferred parameter is absent from parameters")


def _metadata_json(model: ChFoenProductMetadata | ChFoenStationProductMetadata) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise FatalContractError(f"{name} is required")
    stripped = value.strip()
    if not stripped:
        raise FatalContractError(f"{name} is required")
    return stripped


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _required_float(value: object, name: str) -> float:
    if isinstance(value, int | float):
        return float(value)
    raise FatalContractError(f"{name} is required")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged ch_foen catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to an Existenz.ch hydro locations JSON fixture.")
    source.add_argument("--live", action="store_true", help="Fetch the live Existenz.ch hydro locations endpoint.")
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

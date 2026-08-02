"""Swiss catalogue maintenance : refresh(ExistenzHydroLocations, RetrievedAt) → WithIssues[NativeTable]; generate(ExistenzHydroLocations) → GeneratedChFoenCatalogue."""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table, write_native_table
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
from rivretrieve._internal.engine import WithIssues
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
LIVE_MINIMUM_STATIONS = 200

NATIVE_SOURCE_SCHEMA = pl.Schema(
    {
        "payload_key": pl.String,
        "id": pl.Int64,
        "name": pl.String,
        "details.id": pl.String,
        "details.name": pl.String,
        "details.water-body-name": pl.String,
        "details.water-body-type": pl.String,
        "details.chx": pl.Int64,
        "details.chy": pl.Int64,
        "details.lat": pl.Float64,
        "details.lon": pl.Float64,
        "source": pl.String,
        "apiurl": pl.String,
        "opendata": pl.String,
        "license": pl.String,
    }
)


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


def refresh_native_table(
    raw_payload: Mapping[str, object],
    *,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    envelope = _envelope_strings(raw_payload)
    payload = _station_payload(raw_payload)
    rows = [_native_source_row(payload_key, station, envelope) for payload_key, station in payload.items()]
    source_rows = pl.DataFrame(rows, schema=NATIVE_SOURCE_SCHEMA).sort("payload_key")
    return WithIssues(value=stamp_native_table(source_rows, retrieved_at), issues=())


def refresh_native_table_from_fixture(
    fixture_path: Path | str,
    *,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    return refresh_native_table(
        _read_fixture_json(Path(fixture_path)),
        retrieved_at=retrieved_at,
    )


def refresh_native_table_from_live(*, retrieved_at: RetrievedAt) -> WithIssues[NativeTable]:
    raw_payload = _read_live_json(SOURCE_URL)
    outcome = refresh_native_table(raw_payload, retrieved_at=retrieved_at)
    if outcome.value.data.height < LIVE_MINIMUM_STATIONS:
        raise FatalContractError(f"Swiss metadata live response returned fewer than {LIVE_MINIMUM_STATIONS} stations")
    return outcome


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
    _envelope_strings(raw_payload)
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
    envelope = _envelope_strings(raw_payload)
    metadata = {
        "source_url": SOURCE_URL,
        "legacy_source": LEGACY_SOURCE,
        "generator_input": generator_input,
        "fixture_source": envelope["source"],
        "fixture_apiurl": envelope["apiurl"],
        "fixture_opendata": envelope["opendata"],
        "fixture_license": envelope["license"],
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
    source_row = _validated_station_source(station_key, station)
    return {
        "provider_id": PROVIDER_ID,
        "station_id": source_row["details.id"],
        "latitude": source_row["details.lat"],
        "longitude": source_row["details.lon"],
        "crs": "unknown",
    }


def _native_source_row(
    payload_key: str,
    station: object,
    envelope: Mapping[str, str],
) -> dict[str, object]:
    return {**_validated_station_source(payload_key, station), **envelope}


def _validated_station_source(station_key: str, station: object) -> dict[str, object]:
    payload_key = _required_string(station_key, "Station payload key")
    if not isinstance(station, dict):
        raise FatalContractError(f"Station {payload_key} must be an object")
    station_data = cast("dict[str, object]", station)
    station_id = _required_integer(
        _required_field(station_data, "id", f"Station {payload_key}"), f"Station {payload_key} id"
    )
    station_name = _required_string(
        _required_field(station_data, "name", f"Station {payload_key}"),
        f"Station {payload_key} name",
    )
    details = _required_field(station_data, "details", f"Station {payload_key}")
    if not isinstance(details, dict):
        raise FatalContractError(f"Station {payload_key} details must be an object")
    details_data = cast("dict[str, object]", details)

    return {
        "payload_key": payload_key,
        "id": station_id,
        "name": station_name,
        "details.id": _required_station_identifier(
            _required_field(details_data, "id", f"Station {payload_key} details"),
            f"Station {payload_key} details.id",
        ),
        "details.name": _required_string(
            _required_field(details_data, "name", f"Station {payload_key} details"),
            f"Station {payload_key} details.name",
        ),
        "details.water-body-name": _required_string(
            _required_field(details_data, "water-body-name", f"Station {payload_key} details"),
            f"Station {payload_key} details.water-body-name",
        ),
        "details.water-body-type": _required_string(
            _required_field(details_data, "water-body-type", f"Station {payload_key} details"),
            f"Station {payload_key} details.water-body-type",
        ),
        "details.chx": _required_integer(
            _required_field(details_data, "chx", f"Station {payload_key} details"),
            f"Station {payload_key} details.chx",
        ),
        "details.chy": _required_integer(
            _required_field(details_data, "chy", f"Station {payload_key} details"),
            f"Station {payload_key} details.chy",
        ),
        "details.lat": _required_float(
            _required_field(details_data, "lat", f"Station {payload_key} details"),
            f"Station {payload_key} details.lat",
        ),
        "details.lon": _required_float(
            _required_field(details_data, "lon", f"Station {payload_key} details"),
            f"Station {payload_key} details.lon",
        ),
    }


def _envelope_strings(raw_payload: Mapping[str, object]) -> dict[str, str]:
    return {
        field: _required_string(_required_field(raw_payload, field, "Swiss metadata response"), field)
        for field in ("source", "apiurl", "opendata", "license")
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


def _required_field(mapping: Mapping[str, object], field: str, context: str) -> object:
    try:
        return mapping[field]
    except KeyError as exc:
        raise FatalContractError(f"{context} is missing required field '{field}'") from exc


def _required_station_identifier(value: object, name: str) -> str:
    if type(value) is int:
        return str(value)
    return _required_string(value, name)


def _required_integer(value: object, name: str) -> int:
    if type(value) is int:
        return value
    raise FatalContractError(f"{name} is required and must be an integer")


def _required_float(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise FatalContractError(f"{name} is required and must be numeric")
    if isinstance(value, int | float):
        return float(value)
    raise FatalContractError(f"{name} is required and must be numeric")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged ch_foen catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to an Existenz.ch hydro locations JSON fixture.")
    source.add_argument("--live", action="store_true", help="Fetch the live Existenz.ch hydro locations endpoint.")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--out", type=Path, help="Output directory for provider.json and parquet files.")
    destination.add_argument("--native-out", type=Path, help="Output path for the native Parquet table.")
    parser.add_argument("--catalogue-date", type=date.fromisoformat)
    parser.add_argument("--retrieved-at", type=lambda value: RetrievedAt(datetime.fromisoformat(value)))
    args = parser.parse_args(argv)

    if args.native_out is not None:
        if args.retrieved_at is None:
            parser.error("--retrieved-at is required with --native-out")
        if args.catalogue_date is not None:
            parser.error("--catalogue-date is only valid with --out")
        if args.live:
            native_outcome = refresh_native_table_from_live(retrieved_at=args.retrieved_at)
        else:
            native_outcome = refresh_native_table_from_fixture(args.fixture, retrieved_at=args.retrieved_at)
        write_native_table(native_outcome.value, args.native_out)
        return 0

    if args.retrieved_at is not None:
        parser.error("--retrieved-at is only valid with --native-out")
    catalogue_date = args.catalogue_date or date.today()
    if args.live:
        catalogue = generate_catalogue_from_live(catalogue_date=catalogue_date)
    else:
        catalogue = generate_catalogue_from_fixture(args.fixture, catalogue_date=catalogue_date)
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

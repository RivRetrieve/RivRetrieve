"""Swiss catalogue maintenance : refresh(ExistenzHydroLocations, RetrievedAt) → WithIssues[NativeTable]; build(NativeTable, OriginDeclarations) → GeneratedChFoenCatalogue."""

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

from rivretrieve._internal.catalogue_origins import OriginDeclarations, enforce_catalogue_origins
from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
from rivretrieve._internal.catalogues.native import (
    NativeTable,
    RetrievedAt,
    read_native_table,
    stamp_native_table,
    write_native_table,
)
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
from rivretrieve._internal.primitives import ProviderId

PROVIDER_ID = ProviderId("ch_foen")
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


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
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


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
) -> GeneratedChFoenCatalogue:
    if native_table.data.is_empty():
        raise FatalContractError("Swiss native table must not be empty")
    envelope = _validate_native_build_rows(native_table)
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    station_dates = native_table.data.select(
        pl.col("name").alias("station_id"),
        pl.col("retrieved_at").dt.date().alias("retrieved_date"),
    )
    station_products = build_station_products(station_dates)
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("Swiss native table has no valid retrieved_at values")
    provider_info = build_provider_info(maximum_retrieved_at.date(), envelope)

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
        }
        for definition in product_definitions
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(native_table: NativeTable) -> StationCatalog:
    return native_table.data.select(
        pl.lit(PROVIDER_ID).cast(pl.String).alias("provider_id"),
        pl.col("name").cast(pl.String).alias("station_id"),
        pl.col("details.lat").cast(pl.Float64).alias("latitude"),
        pl.col("details.lon").cast(pl.Float64).alias("longitude"),
        pl.lit("unknown").cast(pl.String).alias("crs"),
    ).sort("station_id")


def build_station_products(station_dates: pl.DataFrame) -> StationProductCatalog:
    rows = []
    for station_id, retrieved_date in station_dates.iter_rows():
        if not isinstance(station_id, str) or not isinstance(retrieved_date, date):
            raise FatalContractError("station retrieval date must pair a string identifier with a date")
        for definition in PRODUCT_DEFINITIONS:
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": definition.product_id,
                    "availability": "unknown",
                    "availability_reason": AVAILABILITY_REASON,
                    "start_date": None,
                    "end_date": None,
                    "last_catalogue_check": retrieved_date,
                }
            )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(AvailabilityDtype)
    )


def build_provider_info(catalogue_version_date: date, envelope: Mapping[str, str]) -> dict[str, object]:
    {
        "source_url": SOURCE_URL,
        "legacy_source": LEGACY_SOURCE,
        "generator_input": "native",
        "source": envelope["source"],
        "apiurl": envelope["apiurl"],
        "opendata": envelope["opendata"],
        "license": envelope["license"],
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
        "catalogue_version": catalogue_version_date.isoformat(),
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


def _validate_native_build_rows(native_table: NativeTable) -> dict[str, str]:
    expected_envelope: dict[str, str] | None = None
    station_ids: set[str] = set()
    for row in native_table.data.iter_rows(named=True):
        payload_key = row.get("payload_key")
        if not isinstance(payload_key, str) or not payload_key.strip():
            raise FatalContractError("Swiss native table row has invalid payload_key")
        station_id = row.get("name")
        if not isinstance(station_id, str) or not station_id.strip():
            raise FatalContractError(f"payload_key {payload_key} has invalid name")
        if station_id in station_ids:
            raise FatalContractError(f"payload_key {payload_key} has duplicate station identity '{station_id}'")
        station_ids.add(station_id)
        for field in ("details.lat", "details.lon"):
            value = row.get(field)
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise FatalContractError(f"payload_key {payload_key} has invalid {field}")
        if not isinstance(row.get("retrieved_at"), datetime):
            raise FatalContractError(f"payload_key {payload_key} has invalid retrieved_at")
        envelope: dict[str, str] = {}
        for field in ("source", "apiurl", "opendata", "license"):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                raise FatalContractError(f"payload_key {payload_key} has invalid {field}")
            envelope[field] = value
            if expected_envelope is not None and value != expected_envelope[field]:
                raise FatalContractError(f"payload_key {payload_key} has inconsistent {field}")
        if expected_envelope is None:
            expected_envelope = envelope
    if expected_envelope is None:
        raise FatalContractError("Swiss native table must not be empty")
    return expected_envelope


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
    source.add_argument("--native", type=Path, help="Path to the committed native Parquet table.")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--out", type=Path, help="Output directory for provider.json and parquet files.")
    destination.add_argument("--native-out", type=Path, help="Output path for the native Parquet table.")
    parser.add_argument("--retrieved-at", type=lambda value: RetrievedAt(datetime.fromisoformat(value)))
    args = parser.parse_args(argv)

    if args.native_out is not None:
        if args.native is not None:
            parser.error("--native cannot be used with --native-out")
        if args.retrieved_at is None:
            parser.error("--retrieved-at is required with --native-out")
        if args.live:
            native_outcome = refresh_native_table_from_live(retrieved_at=args.retrieved_at)
        else:
            native_outcome = refresh_native_table_from_fixture(args.fixture, retrieved_at=args.retrieved_at)
        write_native_table(native_outcome.value, args.native_out)
        return 0

    if args.native is None:
        parser.error("--out requires --native")
    if args.retrieved_at is not None:
        parser.error("--retrieved-at is only valid with refresh mode")
    from rivretrieve._internal.providers.ch_foen.origins import STATION_CATALOGUE_ORIGINS

    catalogue = build_catalogue(read_native_table(args.native), STATION_CATALOGUE_ORIGINS)
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

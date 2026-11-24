"""Germany PEGELONLINE (`de_pegelonline`) station catalogue builder.

Builds `StationCatalog`, `ProductCatalog`, `StationProductCatalog` and
`ProviderInfoCatalog` from one retained snapshot of PEGELONLINE's REST API v2
`stations.json?includeTimeseries=true&includeCharacteristicValues=true` response
(step 1's settled source). Mirrors `lt_lhmt`'s lighter single-endpoint pattern
rather than `ch_foen`/`dk_vanda`'s retained-input-receipt/selection.json trail,
since this provider has one public, unauthenticated endpoint and no archive
member to select between.

Scope note (see the implementation PR description for the full account): a
fresh live fetch made while building this catalogue found zero stations
publishing a `TRM` or `TRM_WT` timeseries shortname, contradicting step 2's
vision text (which expected 120 and 2 stations respectively, from the private
verification-evidence research record). This builder therefore only defines the
three `product_id`s actually witnessed in the live catalogue (`W`, `Q`, `WT`);
`TRM`/`TRM_WT` are intentionally not fabricated. This is flagged as an open
question for the orchestrating session, not resolved here.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import cast

import polars as pl

from rivretrieve._internal.acquisition_provenance import AcquisitionProvenance, CatalogueBuildInputs
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
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.de_pegelonline.origins import STATIONS_URL

PROVIDER_ID = ProviderId("de_pegelonline")
PROVIDER_NAME = (
    "Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV) / "
    "Generaldirektion Wasserstraßen und Schifffahrt (GDWS), PEGELONLINE"
)

# Native timeseries shortname -> RivRetrieve observed_property. Only the
# shortnames actually witnessed in a fresh live fetch are mapped; see the
# module docstring's scope note about TRM/TRM_WT.
PRODUCTS: dict[str, str] = {"W": "stage", "Q": "discharge", "WT": "water_temperature"}
PRODUCT_UNITS: dict[str, str] = {"W": "unknown", "Q": "m3/s", "WT": "degC"}

TIMESERIES_STRUCT = pl.Struct({"shortname": pl.String, "unit": pl.String})
NATIVE_SCHEMA = pl.Schema(
    {
        "uuid": pl.String,
        "number": pl.String,
        "shortname": pl.String,
        "longname": pl.String,
        "km": pl.Float64,
        "agency": pl.String,
        "remark": pl.String,
        "longitude": pl.Float64,
        "latitude": pl.Float64,
        "water_shortname": pl.String,
        "water_longname": pl.String,
        "w_unit": pl.String,
        "w_gauge_zero_value": pl.Float64,
        "timeseries": pl.List(TIMESERIES_STRUCT),
    }
)


def _rows(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise FatalContractError("PEGELONLINE stations response must be a list of station objects")
    return cast("list[dict[str, object]]", payload)


def _required_str(source: dict[str, object], field: str, *, context: str = "station") -> str:
    value = source.get(field)
    if not isinstance(value, str) or not value.strip():
        raise FatalContractError(f"PEGELONLINE {context} requires a nonblank '{field}'")
    return value


def _optional_float(source: dict[str, object], field: str, *, context: str = "station") -> float | None:
    value = source.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FatalContractError(f"PEGELONLINE {context} field '{field}' must be numeric or absent")
    return float(value)


def station_native_table(payload: object, *, retrieved_at: RetrievedAt) -> NativeTable:
    """Flatten PEGELONLINE's station catalogue into one row per station.

    Preserves every station-level native field verbatim (including all timeseries
    shortnames and units, not only the three in scope) plus the `W` timeseries'
    own native unit (`cm`/`m+NN`/`m+PNP`) and `gaugeZero.value`, flattened into
    top-level scalar columns so the shared station-metadata mechanism can expose
    them. A station publishes at most one `W` timeseries (checked below); this
    does not hold generally for other shortnames, which stay in the nested
    `timeseries` list unflattened.
    """
    rows = _rows(payload)
    parsed: list[dict[str, object]] = []
    seen_uuids: set[str] = set()
    for row in rows:
        uuid = _required_str(row, "uuid")
        if uuid in seen_uuids:
            raise FatalContractError("PEGELONLINE station uuid is not unique")
        seen_uuids.add(uuid)

        number = _required_str(row, "number")
        shortname = _required_str(row, "shortname")
        longname = _required_str(row, "longname")
        agency = _required_str(row, "agency")
        km = _optional_float(row, "km")
        remark = row.get("remark")
        if remark is not None and not isinstance(remark, str):
            raise FatalContractError("PEGELONLINE station 'remark' must be a string when present")
        longitude = _optional_float(row, "longitude")
        latitude = _optional_float(row, "latitude")
        if (longitude is None) != (latitude is None):
            raise FatalContractError("PEGELONLINE station must publish both coordinates or neither")

        water = row.get("water")
        if not isinstance(water, dict):
            raise FatalContractError("PEGELONLINE station requires a 'water' object")
        water = cast("dict[str, object]", water)
        water_shortname = _required_str(water, "shortname", context="station water")
        water_longname = _required_str(water, "longname", context="station water")

        timeseries_raw = row.get("timeseries")
        if not isinstance(timeseries_raw, list):
            raise FatalContractError("PEGELONLINE station requires a 'timeseries' list")
        timeseries: list[dict[str, str]] = []
        seen_shortnames: set[str] = set()
        w_unit: str | None = None
        w_gauge_zero_value: float | None = None
        for entry in timeseries_raw:
            if not isinstance(entry, dict):
                raise FatalContractError("PEGELONLINE timeseries entry must be an object")
            entry = cast("dict[str, object]", entry)
            ts_shortname = _required_str(entry, "shortname", context="timeseries")
            ts_unit = _required_str(entry, "unit", context="timeseries")
            if ts_shortname in seen_shortnames:
                raise FatalContractError("PEGELONLINE station has duplicate timeseries shortnames")
            seen_shortnames.add(ts_shortname)
            timeseries.append({"shortname": ts_shortname, "unit": ts_unit})
            if ts_shortname == "W":
                w_unit = ts_unit
                gauge_zero = entry.get("gaugeZero")
                if gauge_zero is not None:
                    if not isinstance(gauge_zero, dict):
                        raise FatalContractError("PEGELONLINE gaugeZero must be an object or null")
                    w_gauge_zero_value = _optional_float(
                        cast("dict[str, object]", gauge_zero), "value", context="gaugeZero"
                    )
                    if w_gauge_zero_value is None:
                        raise FatalContractError("PEGELONLINE gaugeZero requires a numeric 'value' when present")

        parsed.append(
            {
                "uuid": uuid,
                "number": number,
                "shortname": shortname,
                "longname": longname,
                "km": km,
                "agency": agency,
                "remark": remark,
                "longitude": longitude,
                "latitude": latitude,
                "water_shortname": water_shortname,
                "water_longname": water_longname,
                "w_unit": w_unit,
                "w_gauge_zero_value": w_gauge_zero_value,
                "timeseries": timeseries,
            }
        )
    frame = pl.DataFrame(parsed, schema=NATIVE_SCHEMA).sort("uuid")
    return stamp_native_table(frame, retrieved_at)


def build_products() -> ProductCatalog:
    rows = [
        {
            "provider_id": str(PROVIDER_ID),
            "product_id": shortname,
            "observed_property": observed_property,
            "frequency": "unknown",
            "statistic": "unknown",
            "period_type": "unknown",
            "period_anchor": "unknown",
            "unit": PRODUCT_UNITS[shortname],
            "native_id": shortname,
        }
        for shortname, observed_property in PRODUCTS.items()
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(native_table: NativeTable) -> StationCatalog:
    return (
        native_table.data.select(
            pl.lit(str(PROVIDER_ID)).alias("provider_id"),
            pl.col("uuid").alias("station_id"),
            "latitude",
            "longitude",
            pl.when(pl.col("latitude").is_null()).then(pl.lit("unknown")).otherwise(pl.lit("EPSG:4326")).alias("crs"),
        )
        .sort("station_id")
        .cast(STATION_CATALOG_SCHEMA.polars_schema)
    )


def build_station_products(native_table: NativeTable, checked_on: date) -> StationProductCatalog:
    rows = []
    for station in native_table.data.iter_rows(named=True):
        present = {entry["shortname"] for entry in station["timeseries"]}
        for shortname in PRODUCTS:
            available = shortname in present
            rows.append(
                {
                    "provider_id": str(PROVIDER_ID),
                    "station_id": station["uuid"],
                    "product_id": shortname,
                    "availability": "available" if available else "unknown",
                    "availability_reason": (
                        "PEGELONLINE station catalogue lists this timeseries"
                        if available
                        else "PEGELONLINE station catalogue does not list this timeseries for this station"
                    ),
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": checked_on,
                }
            )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(AvailabilityDtype)
    )


def build_provider_info(checked_on: date) -> dict[str, object]:
    return {
        "provider_id": str(PROVIDER_ID),
        "name": PROVIDER_NAME,
        "live_stations": True,
        "live_products": True,
        "live_station_products": True,
        "bulk_observations": "none",
        "catalogue_version": checked_on.isoformat(),
        "license": "DL-DE->Zero-2.0",
        "citation": None,
    }


@dataclass(frozen=True)
class GeneratedDePegelonlineCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    acquisition_provenance: AcquisitionProvenance | None = None
    station_metadata: pl.DataFrame | None = None


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
    *,
    acquisition_provenance: AcquisitionProvenance | None = None,
    station_metadata: pl.DataFrame | None = None,
) -> GeneratedDePegelonlineCatalogue:
    """Assemble the four catalogue tables from one retained native snapshot.

    `checked_on` (the catalogue version and each station/product pair's
    `last_catalogue_check`) is derived from the native table's own
    `retrieved_at` column, matching `lt_lhmt`'s pattern, rather than taken as a
    separate argument that could drift from what was actually fetched.
    """
    if native_table.data.is_empty():
        raise FatalContractError("de_pegelonline native table must not be empty")
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("de_pegelonline native table has no valid retrieved_at values")
    checked_on = maximum_retrieved_at.date()
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    station_products = build_station_products(native_table, checked_on)
    provider_info = build_provider_info(checked_on)

    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedDePegelonlineCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=station_products,
        acquisition_provenance=acquisition_provenance,
        station_metadata=station_metadata,
    )


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
    packaged_catalogue_artifact_from_components(provider_info, products, stations, station_products, on_issue="raise")


def refresh_native_table_from_live(*, retrieved_at: RetrievedAt) -> NativeTable:
    return station_native_table(_read_live_json(STATIONS_URL), retrieved_at=retrieved_at)


def refresh_native_table_from_fixture(fixture_path: Path | str, *, retrieved_at: RetrievedAt) -> NativeTable:
    return station_native_table(_read_fixture_json(Path(fixture_path)), retrieved_at=retrieved_at)


def _read_fixture_json(path: Path) -> list[object]:
    try:
        with path.open(encoding="utf-8") as file:
            value = json.load(file)
    except OSError as exc:
        raise FatalContractError(f"Unable to read PEGELONLINE catalogue fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"PEGELONLINE catalogue fixture is not valid JSON: {path}") from exc
    if not isinstance(value, list):
        raise FatalContractError("PEGELONLINE catalogue fixture must contain a JSON array")
    return cast("list[object]", value)


def _read_live_json(url: str) -> list[object]:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 (fixed, documented https endpoint)
            if response.status < 200 or response.status >= 300:
                raise FatalContractError(f"PEGELONLINE live request failed with HTTP {response.status}")
            value = json.load(response)
    except OSError as exc:
        raise FatalContractError("PEGELONLINE live request failed") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError("PEGELONLINE live response is not valid JSON") from exc
    if not isinstance(value, list):
        raise FatalContractError("PEGELONLINE live response must contain a JSON array")
    return cast("list[object]", value)


def write_catalogue(
    catalogue: GeneratedDePegelonlineCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs | None = None,
    native_table: NativeTable | None = None,
) -> None:
    """Write a catalogue using adopted build inputs and its verified native table."""
    from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.de_pegelonline.origins import (
        STATION_CATALOGUE_ORIGINS,
        STATION_METADATA_FIELDS,
        STATION_METADATA_NOTICE,
    )

    if build_inputs is None or native_table is None:
        raise FatalContractError("Catalogue publication requires explicit build_inputs and native_table")
    if catalogue.acquisition_provenance is None:
        raise FatalContractError("Catalogue publication requires explicit acquisition provenance")

    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as file:
        json.dump(catalogue.provider_info, file, sort_keys=True, separators=(",", ":"))
        file.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (STATION_CATALOGUE_ORIGINS,),
        {name: (output_path / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES},
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=STATION_METADATA_FIELDS,
        station_metadata_notice=STATION_METADATA_NOTICE,
    )
    for name, content in metadata.items():
        (output_path / name).write_bytes(content)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged de_pegelonline catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to a PEGELONLINE stations.json fixture.")
    source.add_argument("--live", action="store_true", help="Fetch the live PEGELONLINE stations endpoint.")
    source.add_argument("--native", type=Path, help="Path to the retained native Parquet table.")
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
        native = (
            refresh_native_table_from_live(retrieved_at=args.retrieved_at)
            if args.live
            else refresh_native_table_from_fixture(args.fixture, retrieved_at=args.retrieved_at)
        )
        write_native_table(native, args.native_out)
        return 0

    if args.native is None:
        parser.error("--out requires --native")
    if args.retrieved_at is not None:
        parser.error("--retrieved-at is only valid with refresh mode")
    from rivretrieve._internal.providers.de_pegelonline.origins import STATION_CATALOGUE_ORIGINS

    native_table = read_native_table(args.native)
    catalogue = build_catalogue(native_table, STATION_CATALOGUE_ORIGINS)
    output_path = Path(args.out)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as file:
        json.dump(catalogue.provider_info, file, sort_keys=True, separators=(",", ":"))
        file.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

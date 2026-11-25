"""Germany PEGELONLINE (`de_pegelonline`) station catalogue builder.

Builds `StationCatalog`, `ProductCatalog`, `StationProductCatalog` and
`ProviderInfoCatalog` from one retained snapshot of PEGELONLINE's REST API v2
`stations.json?includeTimeseries=true&includeCharacteristicValues=true&includeTrmTimeseries=true`
response (step 1's settled source). Mirrors `lt_lhmt`'s lighter single-endpoint
pattern rather than `ch_foen`/`dk_vanda`'s retained-input-receipt/selection.json
trail, since this provider has one public, unauthenticated endpoint and no
archive member to select between.

Resolved scope note: an initial live fetch made while building this catalogue
omitted `includeTrmTimeseries=true` and found zero stations publishing a `TRM`
or `TRM_WT` timeseries shortname, apparently contradicting step 2's vision text
(120 and 2 stations respectively). That flag is a separate opt-in from
`includeTimeseries`/`includeCharacteristicValues` — without it PEGELONLINE
silently omits `TRM`/`TRM_WT` from every station's `timeseries` list, still
`HTTP 200`, no error. Adding it restores `TRM = 120`, `TRM_WT = 2`, exactly
matching the vision; both products are defined below. See the vision's own
corrected "Source" section for the confirmed request shape.

The full packaged artifact (`provider.json`, `products.parquet`, `stations.parquet`,
`station_products.parquet`, `source_series.json`, `provenance.json`, ...) is
committed under `catalogue/`, built by `write_catalogue()` against the real
`de_pegelonline-2026-11-25-v1` archive collection in
`RivRetrieve/verification-evidence` (native table and terms-of-use recording,
registered via that repository's own intake/publish tooling). `de_pegelonline`
is a built-in provider: see `provider_manifest.py`'s `BUILTIN_PROVIDER_IDS` and
`catalogues/artifact.py`'s `ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS`.
`build_catalogue()` requires real `acquisition_provenance` unconditionally
(matching `at_ehyd`/`ch_foen`'s precedent for a bespoke-builder enrolled
provider); `main()`'s `--out` CLI mode assembles the four core tables directly
instead, since it predates that requirement and is not part of the
packaged-artifact contract.
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
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.de_pegelonline.origins import STATIONS_URL

PROVIDER_ID = ProviderId("de_pegelonline")
PROVIDER_NAME = (
    "Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV) / "
    "Generaldirektion Wasserstraßen und Schifffahrt (GDWS), PEGELONLINE"
)

# Native timeseries shortname -> RivRetrieve observed_property. `TRM`/`TRM_WT`
# are the scheduled ("Terminwerte") reading variants of `W`/`WT` respectively;
# each keeps its own distinct product_id, never folded into the raw series it
# accompanies (step 2 vision). `WV`, `F`, `T`, and the other scheduled variants
# this source publishes for out-of-scope parameters (`TRM_LT`, `TRM_DFH`) stay
# out of scope entirely.
PRODUCTS: dict[str, str] = {
    "W": "stage",
    "Q": "discharge",
    "WT": "water_temperature",
    "TRM": "stage",
    "TRM_WT": "water_temperature",
}
# W merges three vertical-datum regimes (cm/m+NN/m+PNP) under one product_id,
# so its catalogue-level unit is genuinely unknown; TRM and TRM_WT each use one
# fixed native unit across every witnessed station (confirmed from a complete
# live fetch: 120/120 TRM series are "cm", 2/2 TRM_WT series are "°C"), so no
# such ambiguity applies to them.
PRODUCT_UNITS: dict[str, str] = {"W": "unknown", "Q": "m3/s", "WT": "degC", "TRM": "cm", "TRM_WT": "degC"}

TIMESERIES_STRUCT = pl.Struct({"shortname": pl.String, "unit": pl.String, "equidistance": pl.Int64})
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
        # `gaugeZero.unit` text (e.g. "m. ü. NN"), distinct from `w_unit` (the
        # W timeseries' own native unit, cm/m+NN/m+PNP): step 5's `describe_*`
        # catalogue builder needs this as `series.source_series()`'s
        # `gauge_zero_unit` argument (series.py's cm/m+PNP vertical-datum text).
        "w_gauge_zero_unit": pl.String,
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


def _optional_int(source: dict[str, object], field: str, *, context: str = "station") -> int | None:
    value = source.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise FatalContractError(f"PEGELONLINE {context} field '{field}' must be an integer or absent")
    return value


def station_native_table(payload: object, *, retrieved_at: RetrievedAt) -> NativeTable:
    """Flatten PEGELONLINE's station catalogue into one row per station.

    Preserves every station-level native field verbatim (including all timeseries
    shortnames, units and equidistance minute counts, not only the three products
    in scope) plus the `W` timeseries' own native unit (`cm`/`m+NN`/`m+PNP`) and
    `gaugeZero.value`/`gaugeZero.unit`, flattened into top-level scalar columns so
    the shared station-metadata mechanism can expose them. A station publishes at
    most one `W` timeseries (checked below); this does not hold generally for
    other shortnames, which stay in the nested `timeseries` list unflattened.
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
        timeseries: list[dict[str, object]] = []
        seen_shortnames: set[str] = set()
        w_unit: str | None = None
        w_gauge_zero_value: float | None = None
        w_gauge_zero_unit: str | None = None
        for entry in timeseries_raw:
            if not isinstance(entry, dict):
                raise FatalContractError("PEGELONLINE timeseries entry must be an object")
            entry = cast("dict[str, object]", entry)
            ts_shortname = _required_str(entry, "shortname", context="timeseries")
            ts_unit = _required_str(entry, "unit", context="timeseries")
            ts_equidistance = _optional_int(entry, "equidistance", context="timeseries")
            if ts_shortname in seen_shortnames:
                raise FatalContractError("PEGELONLINE station has duplicate timeseries shortnames")
            seen_shortnames.add(ts_shortname)
            timeseries.append({"shortname": ts_shortname, "unit": ts_unit, "equidistance": ts_equidistance})
            if ts_shortname == "W":
                w_unit = ts_unit
                gauge_zero = entry.get("gaugeZero")
                if gauge_zero is not None:
                    if not isinstance(gauge_zero, dict):
                        raise FatalContractError("PEGELONLINE gaugeZero must be an object or null")
                    gauge_zero = cast("dict[str, object]", gauge_zero)
                    w_gauge_zero_value = _optional_float(gauge_zero, "value", context="gaugeZero")
                    if w_gauge_zero_value is None:
                        raise FatalContractError("PEGELONLINE gaugeZero requires a numeric 'value' when present")
                    w_gauge_zero_unit = _required_str(gauge_zero, "unit", context="gaugeZero")

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
                "w_gauge_zero_unit": w_gauge_zero_unit,
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


def describe_station_products(native_table: NativeTable) -> SourceDescriptions:
    """Describe every witnessed de_pegelonline source identity and its established facts.

    Matches `at_ehyd/generate_catalogue.py`'s `describe_associations`, the
    established precedent for a bespoke-builder provider whose physical facts
    genuinely vary per station (here: `W`/`TRM`'s vertical-datum regime and
    every regular product's reporting interval). Iterates every station x
    product row actually published in the native table's own `timeseries`
    lists and calls `series.source_series(...)` with that station's native
    `unit` and `equidistance` for the exact timeseries entry, plus the
    station's own `W` `gaugeZero.unit` text. `gauge_zero_unit` is only
    consulted for the two stage products, `W` and `TRM` (which share one
    vertical-datum regime per `series.py`'s own note, and never publishes its
    own `gaugeZero`); passing it for `Q`/`WT`/`TRM_WT` is harmless since
    `source_series()` ignores it for every other product. Witnessed stations
    that share one identical identity and physical-fact segment are grouped
    under one description rather than repeated per station.
    """
    from rivretrieve._internal.catalogues.source_series import SourceDescription
    from rivretrieve._internal.providers.de_pegelonline.series import QUANTITIES, source_series
    from rivretrieve._internal.source_series import PhysicalFacts, SourceIdentity

    grouped: dict[tuple[str, SourceIdentity, tuple[PhysicalFacts, ...]], list[str]] = {}
    for row in native_table.data.iter_rows(named=True):
        station_id = row["uuid"]
        gauge_zero_unit = row["w_gauge_zero_unit"]
        for entry in row["timeseries"]:
            product_id = entry["shortname"]
            if product_id not in QUANTITIES:
                continue
            series = source_series(
                station_id,
                product_id,
                unit=entry["unit"],
                equidistance=entry["equidistance"],
                gauge_zero_unit=gauge_zero_unit,
                origin="catalogue",
            )
            grouped.setdefault((product_id, series.identity, series.facts), []).append(station_id)

    descriptions = [
        SourceDescription(
            product_id=product_id,
            station_ids=tuple(sorted(station_list)),
            identity_key=(identity.namespace, identity.published_id),
            native_coordinate=product_id,
            identity=identity,
            facts=facts,
        )
        for (product_id, identity, facts), station_list in sorted(
            grouped.items(), key=lambda item: (item[0][0], item[0][1].namespace, item[0][1].published_id or "")
        )
    ]
    return SourceDescriptions(provider_id=str(PROVIDER_ID), descriptions=tuple(descriptions))


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
    source_descriptions: SourceDescriptions
    acquisition_provenance: AcquisitionProvenance | None = None
    station_metadata: pl.DataFrame | None = None


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
    *,
    acquisition_provenance: AcquisitionProvenance,
    station_metadata: pl.DataFrame | None = None,
) -> GeneratedDePegelonlineCatalogue:
    """Assemble the four catalogue tables from one retained native snapshot.

    `checked_on` (the catalogue version and each station/product pair's
    `last_catalogue_check`) is derived from the native table's own
    `retrieved_at` column, matching `lt_lhmt`'s pattern, rather than taken as a
    separate argument that could drift from what was actually fetched.

    `acquisition_provenance` is required (matching `at_ehyd`/`ch_foen`'s own
    bespoke-builder precedent): `de_pegelonline` is enrolled in
    `ACQUISITION_PROVENANCE_ENROLLED_PROVIDERS`, so any packaged catalogue
    built for it, including this function's own self-check, must carry real
    provenance. `main()`'s `--out` CLI mode builds the four core tables
    directly instead of calling this function, since it predates provenance
    being available and is not part of the packaged-artifact contract.
    """
    if native_table.data.is_empty():
        raise FatalContractError("de_pegelonline native table must not be empty")
    if acquisition_provenance is None or acquisition_provenance.provider_id != str(PROVIDER_ID):
        raise FatalContractError("de_pegelonline catalogue requires its selected acquisition provenance")
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("de_pegelonline native table has no valid retrieved_at values")
    checked_on = maximum_retrieved_at.date()
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    station_products = build_station_products(native_table, checked_on)
    provider_info = build_provider_info(checked_on)
    source_descriptions = describe_station_products(native_table)

    validate_generated_catalogue(provider_info, products, stations, station_products, acquisition_provenance)
    return GeneratedDePegelonlineCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=station_products,
        source_descriptions=source_descriptions,
        acquisition_provenance=acquisition_provenance,
        station_metadata=station_metadata,
    )


def validate_generated_catalogue(
    provider_info: dict[str, object],
    products: ProductCatalog,
    stations: StationCatalog,
    station_products: StationProductCatalog,
    acquisition_provenance: AcquisitionProvenance,
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
        acquisition_provenance=acquisition_provenance,
        on_issue="raise",
    )


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


def write_core_catalogue_files(catalogue: GeneratedDePegelonlineCatalogue, out_dir: Path | str) -> Path:
    """Write the four `REQUIRED_ARTIFACT_FILES` (the minimum packaged catalogue).

    Shared by the CLI's `--out` mode and `write_catalogue`'s fuller publication
    path, so both ways of invoking this builder write identical core files
    rather than two independently maintained copies of the same four writes.
    """
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as file:
        json.dump(catalogue.provider_info, file, sort_keys=True, separators=(",", ":"))
        file.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")
    return output_path


def write_catalogue(
    catalogue: GeneratedDePegelonlineCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs | None = None,
    native_table: NativeTable | None = None,
) -> None:
    """Write the full packaged catalogue: the four core files plus evidence-bound metadata.

    Requires a reviewed `build_inputs`/`acquisition_provenance` and a source
    description for every product (`source_series.json`), which in turn
    requires each product's `SourceIdentity`/`PhysicalFacts` — step 3's job
    (#1018), not this builder's. This function exists for the step that has
    those available; it is not invoked by `main()`'s `--out` mode, which calls
    `write_core_catalogue_files` instead and stops there.
    """
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

    output_path = write_core_catalogue_files(catalogue, out_dir)
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (STATION_CATALOGUE_ORIGINS,),
        {name: (output_path / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES},
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=STATION_METADATA_FIELDS,
        station_metadata_notice=STATION_METADATA_NOTICE,
        source_descriptions=catalogue.source_descriptions,
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
    if native_table.data.is_empty():
        parser.error("native table must not be empty")
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        parser.error("native table has no valid retrieved_at values")
    checked_on = maximum_retrieved_at.date()
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, STATION_CATALOGUE_ORIGINS, native_table, stations)
    station_products = build_station_products(native_table, checked_on)
    provider_info = build_provider_info(checked_on)
    source_descriptions = describe_station_products(native_table)
    validate_catalogue(
        pl.DataFrame([provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema),
        PROVIDER_INFO_CATALOG_SCHEMA,
        on_issue="raise",
    )
    validate_catalogue(products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    catalogue = GeneratedDePegelonlineCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=station_products,
        source_descriptions=source_descriptions,
    )
    write_core_catalogue_files(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

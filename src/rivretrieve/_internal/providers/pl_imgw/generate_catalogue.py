"""Maintainer-only catalogue generator for pl_imgw.

refresh : RecoveredPolandStations × LiveImgwRoster × RetrievedAt → WithIssues[NativeTable]
build : NativeTable × OriginDeclarations → GeneratedPlImgwCatalogue

NOT imported during normal package use. Run manually to regenerate packaged
catalogue artifacts when the IMGW station list changes.

The packaged 1,301-row geometry is a recovered historical import. The complete
live IMGW roster independently checks its identifier set but carries no geometry.
IMGW's coordinate routes are partial, coarser corroborating sources.

Canonical artifacts are generated only from committed ``native.parquet`` plus
the provider's origin declarations.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Never

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

PROVIDER_ID = ProviderId("pl_imgw")
PROVIDER_NAME = "Poland Institute of Meteorology and Water Management (IMGW)"

# The live roster checks recovered station identity but has no coordinates.
STATION_CSV_URL = (
    "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/lista_stacji_hydro.csv"
)
AVAILABILITY_REASON = "IMGW does not expose per-variable station availability"
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"

NATIVE_SOURCE_SCHEMA = pl.Schema(
    {
        "gauge_id": pl.String,
        "gauge_name": pl.String,
        "river": pl.String,
        "area": pl.Float64,
        "gauge_altitude": pl.String,
        "latitude": pl.Float64,
        "longitude": pl.Float64,
    }
)
_NATIVE_SOURCE_COLUMNS = NATIVE_SOURCE_SCHEMA.names()
_EXPECTED_ROSTER_ROWS = 1301
_NATIVE_COMBINATION_PREFIX = "pl_imgw native refresh requires --fixture, --roster, --roster-retrieved-at, --retrieved-at, and --native-out together; missing="


@dataclass(frozen=True)
class GeneratedPlImgwCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog


@dataclass(frozen=True, slots=True)
class LiveImgwRoster:
    identifiers: tuple[str, ...]
    retrieved_at: RetrievedAt


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    frequency: str
    statistic: str
    period_type: str
    period_anchor: str
    canonical_unit: str
    native_column: str


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        product_id="discharge_daily_mean",
        observed_property="discharge",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        native_column="Flow [m^3/s]",
    ),
    ProductDefinition(
        product_id="stage_daily_mean",
        observed_property="stage",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m",
        native_column="Water level [cm]",
    ),
    ProductDefinition(
        product_id="water_temperature_daily_mean",
        observed_property="water_temperature",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="degC",
        native_column="Water temperature [deg. C]",
    ),
)


def parse_roster_retrieved_at(value: str) -> RetrievedAt:
    """Parse the independent roster capture instant at the file boundary."""
    return _parse_utc_instant(value, option="--roster-retrieved-at")


def parse_recovered_retrieved_at(value: str) -> RetrievedAt:
    """Parse the recovered payload's provenance lower-bound instant."""
    return _parse_utc_instant(value, option="--retrieved-at")


def refresh_native_table(
    recovered_rows: pl.DataFrame,
    roster: LiveImgwRoster,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    """Check recovered identities against the live roster and stamp the source rows."""
    if recovered_rows.schema != NATIVE_SOURCE_SCHEMA:
        raise FatalContractError(
            f"pl_imgw recovered header mismatch: expected={_NATIVE_SOURCE_COLUMNS!r}; actual={recovered_rows.columns!r}"
        )

    recovered_ids = set(recovered_rows["gauge_id"].to_list())
    roster_ids = set(roster.identifiers)
    recovered_only = sorted(recovered_ids - roster_ids)
    roster_only = sorted(roster_ids - recovered_ids)
    if recovered_only or roster_only:
        raise FatalContractError(
            f"pl_imgw roster identifier mismatch: recovered-only={recovered_only!r}; roster-only={roster_only!r}"
        )

    source_rows = recovered_rows.sort("gauge_id")
    return WithIssues(value=stamp_native_table(source_rows, retrieved_at), issues=())


def refresh_native_table_from_files(
    recovered_path: Path | str,
    roster_path: Path | str,
    *,
    roster_retrieved_at: RetrievedAt,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    """Parse strict offline captures and refresh the Poland native table."""
    recovered_rows = _read_recovered_stations(Path(recovered_path))
    roster = _read_live_roster(Path(roster_path), roster_retrieved_at)
    return refresh_native_table(recovered_rows, roster, retrieved_at)


def native_table_content_sha256(table: NativeTable) -> str:
    """Hash the canonical semantic content of a Poland native table."""
    frame = table.data.sort("gauge_id")
    columns = frame.columns
    rows: list[list[object]] = []
    for row in frame.iter_rows(named=False):
        rendered = list(row)
        retrieved_at = rendered[-1]
        if not isinstance(retrieved_at, datetime):
            raise FatalContractError("pl_imgw native retrieved_at is not a datetime")
        rendered[-1] = retrieved_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        rows.append(rendered)
    canonical = json.dumps(
        {"columns": columns, "rows": rows},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _parse_utc_instant(value: str, *, option: str) -> RetrievedAt:
    message = f"pl_imgw invalid {option}: {value!r}; expected RFC 3339 UTC instant"
    if not value.endswith("Z") or value.count("Z") != 1:
        raise FatalContractError(message)
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as exc:
        raise FatalContractError(message) from exc
    try:
        return RetrievedAt(parsed)
    except FatalContractError as exc:
        raise FatalContractError(message) from exc


def _read_recovered_stations(path: Path) -> pl.DataFrame:
    try:
        with path.open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            actual_header = reader.fieldnames
            if actual_header != _NATIVE_SOURCE_COLUMNS:
                raise FatalContractError(
                    f"pl_imgw recovered header mismatch: expected={_NATIVE_SOURCE_COLUMNS!r}; actual={actual_header!r}"
                )
            rows = [_parse_recovered_row(row, reader.line_num) for row in reader]
    except FileNotFoundError as exc:
        raise FatalContractError(f"pl_imgw recovered input not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise FatalContractError(
            f"pl_imgw recovered value invalid: row=1; field=encoding; value={exc.object!r}"
        ) from exc

    if len(rows) != _EXPECTED_ROSTER_ROWS:
        raise FatalContractError(f"pl_imgw recovered value invalid: row={len(rows) + 1}; field=gauge_id; value=''")
    duplicate_ids = sorted(
        station_id for station_id, count in Counter(row["gauge_id"] for row in rows).items() if count > 1
    )
    if duplicate_ids:
        duplicate = duplicate_ids[0]
        duplicate_row = next(index for index, row in enumerate(rows, start=2) if row["gauge_id"] == duplicate)
        raise FatalContractError(
            f"pl_imgw recovered value invalid: row={duplicate_row}; field=gauge_id; value={duplicate!r}"
        )
    return pl.DataFrame(rows, schema=NATIVE_SOURCE_SCHEMA)


def _parse_recovered_row(row: dict[str | None, str | list[str] | None], row_number: int) -> dict[str, object]:
    if None in row:
        _invalid_recovered(row_number, _NATIVE_SOURCE_COLUMNS[-1], row[None])

    parsed: dict[str, object] = {}
    for field in ("gauge_id", "gauge_name", "river", "gauge_altitude"):
        value = row.get(field)
        if not isinstance(value, str) or value == "":
            _invalid_recovered(row_number, field, value)
        if field == "gauge_id" and (len(value) != 9 or not value.isdigit()):
            _invalid_recovered(row_number, field, value)
        parsed[field] = value

    for field in ("area", "latitude", "longitude"):
        value = row.get(field)
        try:
            number = float(value) if isinstance(value, str) and value != "" else math.nan
        except ValueError:
            _invalid_recovered(row_number, field, value)
        if not math.isfinite(number):
            _invalid_recovered(row_number, field, value)
        parsed[field] = number
    return parsed


def _invalid_recovered(row_number: int, field: str, value: object) -> Never:
    raise FatalContractError(f"pl_imgw recovered value invalid: row={row_number}; field={field}; value={value!r}")


def _read_live_roster(path: Path, retrieved_at: RetrievedAt) -> LiveImgwRoster:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise FatalContractError(f"pl_imgw roster input not found: {path}") from exc
    try:
        text = raw.decode("cp1250", errors="strict")
    except UnicodeDecodeError as exc:
        raise FatalContractError(f"pl_imgw roster encoding invalid: expected=cp1250; path={path}") from exc

    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=","))
    for row_number, row in enumerate(rows, start=1):
        if len(row) != 4:
            raise FatalContractError(
                f"pl_imgw roster row invalid: row={row_number}; expected_columns=4; actual_columns={len(row)}"
            )
    if len(rows) != _EXPECTED_ROSTER_ROWS:
        raise FatalContractError(f"pl_imgw roster row count invalid: expected=1301; actual={len(rows)}")

    identifiers = tuple(row[0].lstrip() for row in rows)
    duplicate_ids = sorted(station_id for station_id, count in Counter(identifiers).items() if count > 1)
    if duplicate_ids:
        raise FatalContractError(f"pl_imgw roster identifiers duplicated: {duplicate_ids!r}")
    return LiveImgwRoster(identifiers=identifiers, retrieved_at=retrieved_at)


def build_catalogue(native_table: NativeTable, origins: OriginDeclarations) -> GeneratedPlImgwCatalogue:
    """Build all canonical artifacts from source-faithful native rows."""
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("pl_imgw native table has no valid retrieved_at values")
    effective_date = maximum_retrieved_at.date()
    station_products = build_station_products(stations, effective_date)
    provider_info = build_provider_info(effective_date)

    _validate(provider_info, products, stations, station_products)
    return GeneratedPlImgwCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=station_products,
    )


def build_products() -> ProductCatalog:
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "product_id": defn.product_id,
            "observed_property": defn.observed_property,
            "frequency": defn.frequency,
            "statistic": defn.statistic,
            "period_type": defn.period_type,
            "period_anchor": defn.period_anchor,
            "unit": defn.canonical_unit,
            "native_id": defn.native_column,
            "derived": False,
            "derivation_method": None,
        }
        for defn in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(native_table: NativeTable) -> StationCatalog:
    rows: list[dict[str, object]] = []
    first_rows: dict[str, int] = {}
    for row_number, item in enumerate(native_table.data.iter_rows(named=True)):
        station_id = item.get("gauge_id")
        if not isinstance(station_id, str) or len(station_id) != 9 or not station_id.isdigit():
            raise FatalContractError(
                f"pl_imgw native station invalid: row={row_number}; field=gauge_id; value={station_id!r}; "
                "expected=exactly nine numeric characters"
            )
        coordinates: dict[str, float] = {}
        for field in ("latitude", "longitude"):
            value = item.get(field)
            if value is None or value == "":
                raise FatalContractError(
                    f"pl_imgw native station invalid: row={row_number}; station_id={station_id!r}; "
                    f"field={field}; value={value!r}; expected=numeric coordinate"
                )
            try:
                coordinates[field] = float(value)
            except (TypeError, ValueError) as exc:
                raise FatalContractError(
                    f"pl_imgw native station invalid: row={row_number}; station_id={station_id!r}; "
                    f"field={field}; value={value!r}; expected=numeric coordinate"
                ) from exc
        if station_id in first_rows:
            raise FatalContractError(
                f"pl_imgw native station duplicate: station_id={station_id!r}; "
                f"first_row={first_rows[station_id]}; duplicate_row={row_number}"
            )
        first_rows[station_id] = row_number
        rows.append(
            {
                "provider_id": str(PROVIDER_ID),
                "station_id": station_id,
                "latitude": coordinates["latitude"],
                "longitude": coordinates["longitude"],
                "crs": "unknown",
            }
        )
    if not rows:
        raise FatalContractError("pl_imgw native table contains no stations")
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(stations: StationCatalog, catalogue_date: date) -> StationProductCatalog:
    rows = []
    for station_id in stations["station_id"].to_list():
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        for defn in PRODUCT_DEFINITIONS:
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": defn.product_id,
                    "availability": "unknown",
                    "availability_reason": AVAILABILITY_REASON,
                    "start_date": None,
                    "end_date": None,
                    "last_catalogue_check": catalogue_date,
                }
            )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(AvailabilityDtype)
    )


def build_provider_info(catalogue_date: date) -> dict[str, object]:
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: the source publishes all-station yearly ZIP files; RivRetrieve's "
            "catalogue-only provider exposes neither observation retrieval nor cache controls"
        ),
        "catalogue_version": catalogue_date.isoformat(),
        "license": None,
        "citation": None,
    }


def write_catalogue(catalogue: GeneratedPlImgwCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as fh:
        json.dump(catalogue.provider_info, fh, sort_keys=True, separators=(",", ":"))
        fh.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _meta_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _validate(
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged pl_imgw catalogue artifacts.")
    parser.add_argument(
        "--fixture",
        type=Path,
        help="Recovered source CSV used only to refresh a native table.",
    )
    parser.add_argument("--native", type=Path, help="Committed native Parquet used for canonical generation.")
    parser.add_argument("--out", type=Path, help="Output directory for catalogue artifacts.")
    parser.add_argument("--roster", type=Path, help="Path to the captured CP1250 IMGW station roster.")
    parser.add_argument("--roster-retrieved-at", help="Roster capture instant as RFC 3339 UTC.")
    parser.add_argument("--retrieved-at", help="Recovered payload provenance instant as RFC 3339 UTC.")
    parser.add_argument("--native-out", type=Path, help="Output path for the native Parquet table.")
    args = parser.parse_args(argv)

    native_values = {
        "--fixture": args.fixture,
        "--roster": args.roster,
        "--roster-retrieved-at": args.roster_retrieved_at,
        "--retrieved-at": args.retrieved_at,
        "--native-out": args.native_out,
    }
    native_mode = any(
        native_values[flag] is not None
        for flag in ("--roster", "--roster-retrieved-at", "--retrieved-at", "--native-out")
    )
    if native_mode:
        missing = sorted(flag for flag, value in native_values.items() if value is None)
        if missing == ["--roster-retrieved-at"]:
            raise FatalContractError("pl_imgw --roster-retrieved-at is required for native refresh")
        if missing:
            raise FatalContractError(f"{_NATIVE_COMBINATION_PREFIX}{missing!r}")
        if args.out is not None or args.native is not None:
            parser.error("native refresh cannot be combined with --out or --native")

        roster_retrieved_at = parse_roster_retrieved_at(args.roster_retrieved_at)
        retrieved_at = parse_recovered_retrieved_at(args.retrieved_at)
        outcome = refresh_native_table_from_files(
            args.fixture,
            args.roster,
            roster_retrieved_at=roster_retrieved_at,
            retrieved_at=retrieved_at,
        )
        write_native_table(outcome.value, args.native_out)
        reread = read_native_table(args.native_out)
        print(f"pl_imgw native table canonical SHA-256: {native_table_content_sha256(reread)}")
        return 0

    if args.fixture is not None:
        parser.error("--fixture is only valid for native refresh")
    if args.out is None or args.native is None:
        parser.error("canonical generation requires --native and --out")

    from rivretrieve._internal.providers.pl_imgw.origins import STATION_CATALOGUE_ORIGINS

    catalogue = build_catalogue(read_native_table(args.native), STATION_CATALOGUE_ORIGINS)
    write_catalogue(catalogue, args.out)
    print(
        f"pl_imgw catalogue written to {args.out}: "
        f"{catalogue.stations.height} stations, "
        f"{catalogue.products.height} products, "
        f"{catalogue.station_products.height} station-product rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

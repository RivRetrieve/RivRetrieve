"""Maintainer-only catalogue generator for pl_imgw.

refresh : RecoveredPolandStations × LiveImgwRoster × RetrievedAt → WithIssues[NativeTable]

NOT imported during normal package use. Run manually to regenerate packaged
catalogue artifacts when the IMGW station list changes.

The packaged 1,301-row geometry is a recovered historical import. The complete
live IMGW roster independently checks its identifier set but carries no geometry.
IMGW's coordinate routes are partial, coarser corroborating sources.

Usage:
    uv run python -m rivretrieve._internal.providers.pl_imgw.generate_catalogue \\
        --fixture tests/test_data/pl_imgw_stations.csv \\
        --out src/rivretrieve/_internal/providers/pl_imgw/catalogue

    uv run python -m rivretrieve._internal.providers.pl_imgw.generate_catalogue \\
        --live --out src/rivretrieve/_internal/providers/pl_imgw/catalogue
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import urllib.request
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Never

import polars as pl

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
from rivretrieve._internal.providers.pl_imgw.metadata import (
    PlImgwProductMetadata,
    PlImgwStationProductMetadata,
)

PROVIDER_ID = "pl_imgw"
PROVIDER_NAME = "Poland Institute of Meteorology and Water Management (IMGW)"

# The live roster checks recovered station identity but has no coordinates.
STATION_CSV_URL = (
    "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/lista_stacji_hydro.csv"
)
# Intermediate compatibility source; it is not the shipped 1,301-row geometry.
HYDRO_JSON_URL = "https://danepubliczne.imgw.pl/api/data/hydro"

AVAILABILITY_REASON = "IMGW does not expose per-variable station availability"
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"
LIVE_STATION_MINIMUM = 500

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
    native_unit: str
    unit_conversion: str | None
    notes: str | None

    @property
    def metadata(self) -> PlImgwProductMetadata:
        return PlImgwProductMetadata(
            native_column=self.native_column,
            native_unit=self.native_unit,
            canonical_unit=self.canonical_unit,
            unit_conversion=self.unit_conversion,
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
        native_column="Flow [m^3/s]",
        native_unit="m3/s",
        unit_conversion=None,
        notes="Daily mean discharge. Native unit is m³/s; no conversion required.",
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
        native_unit="cm",
        unit_conversion="divide_by_100",
        notes="Daily mean water stage. Native unit is centimetres; converted to metres.",
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
        native_unit="degC",
        unit_conversion=None,
        notes="Daily mean water temperature. Native unit is degrees Celsius.",
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


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
) -> GeneratedPlImgwCatalogue:
    """Generate catalogue from a local ``poland_sites.csv`` fixture file."""
    raw = _read_fixture_csv(Path(fixture_path))
    return generate_catalogue(raw, catalogue_date=catalogue_date, generator_input="fixture")


def generate_catalogue_from_live(
    *,
    catalogue_date: date | None = None,
) -> GeneratedPlImgwCatalogue:
    """Generate catalogue by downloading the live ``poland_sites.csv`` from IMGW.

    This intermediate compatibility entry point uses the partial current API.
    It is scheduled for deletion when the canonical builder consumes the
    committed native table.
    """
    raw = _fetch_live_stations()
    return generate_catalogue(raw, catalogue_date=catalogue_date, generator_input="live")


def generate_catalogue(
    raw_stations: list[dict[str, object]],
    *,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedPlImgwCatalogue:
    effective_date = catalogue_date or date.today()

    if generator_input == "live" and len(raw_stations) < LIVE_STATION_MINIMUM:
        raise FatalContractError(
            f"pl_imgw live catalogue returned only {len(raw_stations)} stations; "
            f"expected at least {LIVE_STATION_MINIMUM}."
        )

    products = build_products()
    stations = build_stations(raw_stations)
    station_products = build_station_products(stations, effective_date)
    provider_info = build_provider_info(effective_date, generator_input=generator_input)

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
            "metadata": _meta_json(defn.metadata),
        }
        for defn in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(raw_stations: list[dict[str, object]]) -> StationCatalog:
    rows = [_station_row(s) for s in raw_stations if _station_row(s) is not None]
    if not rows:
        raise FatalContractError("pl_imgw: no valid station rows produced from input data")
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(stations: StationCatalog, catalogue_date: date) -> StationProductCatalog:
    rows = []
    for station_id in stations["station_id"].to_list():
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        for defn in PRODUCT_DEFINITIONS:
            meta = PlImgwStationProductMetadata(
                station_id=station_id,
                product_id=defn.product_id,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=AVAILABILITY_REASON,
            )
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
                    "metadata": _meta_json(meta),
                }
            )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(AvailabilityDtype)
    )


def build_provider_info(catalogue_date: date, *, generator_input: str) -> dict[str, object]:
    metadata = {
        "station_source": "poland_sites.csv from legacy RivRetrieve-Python repo (1301 stations)",
        "data_base_url": (
            "https://danepubliczne.imgw.pl/data/dane_pomiarowo_obserwacyjne/dane_hydrologiczne/dobowe/{year}/"
        ),
        "annual_zip_from_year": 2023,
        "annual_zip_template": "codz_{year}.zip",
        "monthly_zip_template": "codz_{year}_{month:02d}.zip",
        "csv_encoding_recent": "utf-8-sig (BOM), semicolon-separated",
        "csv_encoding_legacy": "cp1250, comma-separated, quoted",
        "cache_format": "parquet",
        "generator_input": generator_input,
        "terms_of_use": "https://danepubliczne.imgw.pl/",
    }
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
        "metadata": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
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


def _station_row(item: dict[str, object]) -> dict[str, object] | None:
    """Parse one station identity and geometry row from poland_sites.csv."""
    station_id = str(item.get("gauge_id", "")).strip()
    if not station_id:
        return None

    lat = _optional_float(item.get("latitude"))
    lon = _optional_float(item.get("longitude"))

    if lat is None or lon is None:
        return None

    return {
        "provider_id": PROVIDER_ID,
        "station_id": station_id,
        "latitude": lat,
        "longitude": lon,
        "crs": "unknown",
    }


def _optional_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value))
    except (ValueError, TypeError):
        return None


def _meta_json(
    model: PlImgwProductMetadata | PlImgwStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _read_fixture_csv(path: Path) -> list[dict[str, object]]:
    """Read the poland_sites.csv fixture (gauge_id, gauge_name, river, area, gauge_altitude, lat, lon)."""
    try:
        with path.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            rows: list[dict[str, object]] = [dict(row) for row in reader]
    except OSError as exc:
        raise FatalContractError(f"Cannot read pl_imgw station CSV fixture: {path}") from exc
    if not rows:
        raise FatalContractError(f"pl_imgw station CSV fixture is empty: {path}")
    return rows


def _fetch_live_stations() -> list[dict[str, object]]:
    """Download the partial live API for intermediate canonical compatibility."""
    try:
        with urllib.request.urlopen(HYDRO_JSON_URL, timeout=30) as resp:
            if resp.status < 200 or resp.status >= 300:
                raise FatalContractError(f"pl_imgw live request failed with HTTP {resp.status}")
            data = json.load(resp)
    except OSError as exc:
        raise FatalContractError("pl_imgw live station request failed") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError("pl_imgw live station response is not valid JSON") from exc
    if not isinstance(data, list):
        raise FatalContractError("pl_imgw live station response must be a JSON array")

    # Map JSON fields → CSV-equivalent keys so _station_row() works for both.
    rows: list[dict[str, object]] = []
    for s in data:
        if not isinstance(s, dict):
            continue
        rows.append(
            {
                "gauge_id": s.get("id_stacji"),
                "gauge_name": s.get("stacja"),
                "river": s.get("rzeka"),
                "area": None,
                "gauge_altitude": None,
                "latitude": s.get("lat"),
                "longitude": s.get("lon"),
            }
        )
    return rows


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
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--fixture",
        type=Path,
        help="Path to a poland_sites.csv file (gauge_id, gauge_name, river, area, gauge_altitude, lat, lon).",
    )
    source.add_argument("--live", action="store_true", help="Fetch the live IMGW /api/data/hydro endpoint.")
    parser.add_argument("--out", type=Path, help="Output directory for catalogue artifacts.")
    parser.add_argument("--roster", type=Path, help="Path to the captured CP1250 IMGW station roster.")
    parser.add_argument("--roster-retrieved-at", help="Roster capture instant as RFC 3339 UTC.")
    parser.add_argument("--retrieved-at", help="Recovered payload provenance instant as RFC 3339 UTC.")
    parser.add_argument("--native-out", type=Path, help="Output path for the native Parquet table.")
    parser.add_argument("--catalogue-date", type=date.fromisoformat, default=date.today())
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
        if args.out is not None or args.live:
            parser.error("native refresh cannot be combined with --out or --live")

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

    if args.out is None:
        parser.error("canonical generation requires --out")
    if args.fixture is None and not args.live:
        parser.error("canonical generation requires --fixture or --live")

    if args.live:
        catalogue = generate_catalogue_from_live(catalogue_date=args.catalogue_date)
    else:
        catalogue = generate_catalogue_from_fixture(args.fixture, catalogue_date=args.catalogue_date)
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

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

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
    verify_acquisition_provenance_statements,
)
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
    acquisition_provenance: AcquisitionProvenance


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
        product_id="discharge_daily",
        observed_property="discharge",
        frequency="daily",
        statistic="unknown",
        period_type="unknown",
        period_anchor="unknown",
        canonical_unit="m3/s",
        native_column="COPRZP",
    ),
    ProductDefinition(
        product_id="stage_daily",
        observed_property="stage",
        frequency="daily",
        statistic="unknown",
        period_type="unknown",
        period_anchor="unknown",
        canonical_unit="m",
        native_column="COSTAN",
    ),
    ProductDefinition(
        product_id="water_temperature_daily",
        observed_property="water_temperature",
        frequency="daily",
        statistic="unknown",
        period_type="unknown",
        period_anchor="unknown",
        canonical_unit="degC",
        native_column="COPTMP",
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


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
) -> GeneratedPlImgwCatalogue:
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

    from rivretrieve._internal.providers.pl_imgw.origins import build_acquisition_provenance

    acquisition_provenance = build_acquisition_provenance()
    _validate(provider_info, products, stations, station_products, acquisition_provenance)
    return GeneratedPlImgwCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=station_products,
        acquisition_provenance=acquisition_provenance,
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
                    "published_record_start_date": None,
                    "published_record_end_date": None,
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
            "true: explicit download compiles the publisher's monthly or annual ZIP archives "
            "into a local native observation store; retrieval reads that store without network access"
        ),
        "catalogue_version": catalogue_date.isoformat(),
        "license": None,
        "citation": None,
    }


def write_catalogue(
    catalogue: GeneratedPlImgwCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs | None = None,
    native_table: NativeTable | None = None,
) -> None:
    """Write a catalogue using adopted build inputs and its verified native table."""
    from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.pl_imgw.catalogue_series import describe_catalogue
    from rivretrieve._internal.providers.pl_imgw.config import config as source_config
    from rivretrieve._internal.providers.pl_imgw.origins import STATION_CATALOGUE_ORIGINS, STATION_METADATA_FIELDS

    if build_inputs is None or native_table is None:
        raise FatalContractError("Catalogue publication requires explicit build_inputs and native_table")

    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as fh:
        json.dump(catalogue.provider_info, fh, sort_keys=True, separators=(",", ":"))
        fh.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")
    metadata = build_catalogue_metadata(
        catalogue.acquisition_provenance,
        (STATION_CATALOGUE_ORIGINS,),
        {name: (output_path / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES},
        source_config=source_config,
        source_describer=describe_catalogue,
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=STATION_METADATA_FIELDS,
    )
    for name, content in metadata.items():
        (output_path / name).write_bytes(content)


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged pl_imgw catalogue artifacts.")
    parser.add_argument(
        "--fixture",
        type=Path,
        help="Recovered source CSV used only to refresh a native table.",
    )
    parser.add_argument(
        "--native", type=Path, help="Retained native Parquet supplied from the external evidence directory."
    )
    parser.add_argument("--out", type=Path, help="Output directory for catalogue artifacts.")
    parser.add_argument("--roster", type=Path, help="Path to the captured CP1250 IMGW station roster.")
    parser.add_argument("--roster-retrieved-at", help="Roster capture instant as RFC 3339 UTC.")
    parser.add_argument("--retrieved-at", help="Recovered payload provenance instant as RFC 3339 UTC.")
    parser.add_argument("--native-out", type=Path, help="Output path for the native Parquet table.")
    parser.add_argument(
        "--terms-recording",
        type=Path,
        help="Exact public IMGW regulations recording required for canonical generation.",
    )
    parser.add_argument(
        "--private-verification-record",
        type=Path,
        help="Optional re-verification record; it must equal the committed redacted origin declaration.",
    )
    parser.add_argument(
        "--verify-forwarded-grdc-email",
        type=Path,
        help="Authorized private forwarded .eml to verify with an explicit original-identity limitation.",
    )
    parser.add_argument(
        "--private-verification-out",
        type=Path,
        help="Destination for the redacted private-email verification record.",
    )
    parser.add_argument(
        "--private-statement-text",
        type=Path,
        help="Private exact source words; read locally and included only after verification.",
    )
    parser.add_argument("--build-inputs", type=Path, help="Reviewed adopted catalogue build inputs JSON.")
    args = parser.parse_args(argv)

    private_email_inputs = tuple(value for value in (args.verify_forwarded_grdc_email,) if value is not None)
    private_mode = bool(private_email_inputs) or args.private_verification_out is not None
    if private_mode:
        if (
            len(private_email_inputs) != 1
            or args.private_verification_out is None
            or args.private_statement_text is None
        ):
            parser.error(
                "private verification requires exactly one private email input, "
                "--private-verification-out, and --private-statement-text"
            )
        other_values = (
            args.fixture,
            args.native,
            args.out,
            args.roster,
            args.roster_retrieved_at,
            args.retrieved_at,
            args.native_out,
            args.terms_recording,
            args.private_verification_record,
        )
        if any(value is not None for value in other_values):
            parser.error("private verification cannot be combined with catalogue generation")
        from rivretrieve._internal.private_source_verification import (
            serialize_private_email_verification,
            verify_forwarded_grdc_email,
        )

        private_email_path = private_email_inputs[0]
        try:
            private_bytes = private_email_path.read_bytes()
        except OSError as exc:
            raise FatalContractError("pl_imgw private email cannot be read") from exc
        try:
            private_statement_text = args.private_statement_text.read_text(encoding="utf-8")
        except OSError as exc:
            raise FatalContractError("pl_imgw private statement text cannot be read") from exc
        record = verify_forwarded_grdc_email(private_bytes, private_statement_text)
        args.private_verification_out.write_text(serialize_private_email_verification(record) + "\n", encoding="utf-8")
        print(f"pl_imgw private statement {record.statement_id}: verified; redacted record written")
        return 0

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
        if args.terms_recording is not None or args.private_verification_record is not None:
            parser.error("terms and private verification records are only valid for canonical generation")
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
    if args.out is None or args.native is None or args.terms_recording is None:
        parser.error("canonical generation requires --native, --out, and --terms-recording")

    from rivretrieve._internal.providers.pl_imgw.origins import (
        NATIVE_TABLE_SHA256,
        STATION_CATALOGUE_ORIGINS,
        build_acquisition_provenance,
    )

    if args.build_inputs is None:
        parser.error("--out requires --build-inputs")
    build_inputs = CatalogueBuildInputs.model_validate_json(args.build_inputs.read_bytes())
    private_verification = None
    if args.private_verification_record is not None:
        from rivretrieve._internal.private_source_verification import parse_private_email_verification

        try:
            private_verification_bytes = args.private_verification_record.read_bytes()
        except OSError as exc:
            raise FatalContractError("pl_imgw private verification input cannot be read") from exc
        private_verification = parse_private_email_verification(private_verification_bytes)
    if args.private_statement_text is not None:
        parser.error("--private-statement-text is accepted only during local private-email verification")
    provenance = build_acquisition_provenance(private_verification)
    try:
        terms_bytes = args.terms_recording.read_bytes()
    except OSError as exc:
        raise FatalContractError("pl_imgw source-statement recording cannot be read") from exc
    verify_acquisition_provenance_statements(
        provenance,
        {"pl_imgw_terms_regulations": terms_bytes},
    )
    native_table = read_native_table(args.native, expected_sha256=NATIVE_TABLE_SHA256)
    catalogue = build_catalogue(
        native_table,
        STATION_CATALOGUE_ORIGINS,
    )
    write_catalogue(catalogue, args.out, build_inputs=build_inputs, native_table=native_table)
    print(
        f"pl_imgw catalogue written to {args.out}: "
        f"{catalogue.stations.height} stations, "
        f"{catalogue.products.height} products, "
        f"{catalogue.station_products.height} station-product rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

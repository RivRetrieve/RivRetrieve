"""Bosnia catalogue maintenance : refresh(WiskiLayerSnapshot, RetrievedAt, RefreshInputKind) → WithIssues[NativeTable]; build(NativeTable, OriginDeclarations) → GeneratedBaFhmzbihCatalogue."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
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
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId

PROVIDER_ID = ProviderId("ba_fhmzbih")
PROVIDER_NAME = "FHMZBiH — Federal Hydrometeorological Institute of Bosnia and Herzegovina (vodostaji.voda.ba)"

METADATA_URL = "https://vodostaji.voda.ba/data/internet/layers/20/index.json"
WORKBOOK_URL_TEMPLATE = "https://vodostaji.voda.ba/data/internet/stations/{group}/{station_id}/{code}/{file}"

AVAILABILITY_REASON = "FHMZBiH metadata snapshot does not expose per-variable station availability"
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"

MIN_LIVE_STATIONS = 30

NATIVE_SOURCE_SCHEMA = pl.Schema(
    {
        "metadata_CATCHMENT_SIZE": pl.String,
        "metadata_WTO_OBJECT": pl.String,
        "metadata_catchment_name": pl.String,
        "metadata_object_type": pl.String,
        "metadata_river_name": pl.String,
        "metadata_site_name": pl.String,
        "metadata_site_no": pl.String,
        "metadata_station_carteasting": pl.String,
        "metadata_station_cartnorthing": pl.String,
        "metadata_station_elevation": pl.String,
        "metadata_station_id": pl.String,
        "metadata_station_latitude": pl.String,
        "metadata_station_local_x": pl.String,
        "metadata_station_local_y": pl.String,
        "metadata_station_longitude": pl.String,
        "metadata_station_longname": pl.String,
        "metadata_station_name": pl.String,
        "metadata_station_no": pl.String,
    }
)
METADATA_COLUMNS = tuple(NATIVE_SOURCE_SCHEMA.names())
VOLATILE_L1_COLUMNS = (
    "L1_label",
    "L1_req_timestamp",
    "L1_station_longname",
    "L1_stationparameter_name",
    "L1_stationparameter_no",
    "L1_timestamp",
    "L1_ts_id",
    "L1_ts_name",
    "L1_ts_precision",
    "L1_ts_unitsymbol",
    "L1_ts_value",
    "L1_web_flow_class",
)


class RefreshInputKind(StrEnum):
    FIXTURE = "fixture"
    LIVE = "live"


class CatalogueIssueCode(StrEnum):
    REFRESH_INVALID_ENVELOPE = "refresh_invalid_envelope"
    REFRESH_INVALID_ROW = "refresh_invalid_row"
    REFRESH_MISSING_REQUIRED_FIELDS = "refresh_missing_required_fields"
    REFRESH_INVALID_SOURCE_TYPES = "refresh_invalid_source_types"
    REFRESH_PAYLOAD_READ_FAILED = "refresh_payload_read_failed"
    REFRESH_BELOW_MINIMUM = "refresh_below_minimum"
    INVALID_STATION_ID = "invalid_station_id"
    DUPLICATE_STATION_ID = "duplicate_station_id"
    INVALID_STATION_COORDINATES = "invalid_station_coordinates"


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
    ),
)

EXPECTED_PRODUCT_IDS = frozenset(d.product_id for d in PRODUCT_DEFINITIONS)


def refresh_native_table(
    payload: object,
    *,
    retrieved_at: RetrievedAt,
    input_kind: RefreshInputKind,
) -> WithIssues[NativeTable]:
    if not isinstance(payload, list):
        return _refresh_failure(
            retrieved_at,
            CatalogueIssueCode.REFRESH_INVALID_ENVELOPE,
            "ba_fhmzbih station payload must be a JSON array",
            {"reason": "invalid_envelope"},
        )

    station_outcome = _iter_station_rows(cast("list[object]", payload))
    if station_outcome.issues:
        return WithIssues(
            value=_empty_native_table(retrieved_at),
            issues=station_outcome.issues,
        )
    if input_kind is RefreshInputKind.LIVE and len(station_outcome.value) < MIN_LIVE_STATIONS:
        count = len(station_outcome.value)
        return _refresh_failure(
            retrieved_at,
            CatalogueIssueCode.REFRESH_BELOW_MINIMUM,
            f"ba_fhmzbih: live catalogue returned only {count} stations "
            f"(expected >= {MIN_LIVE_STATIONS}); possible fetch failure",
            {"actual": count, "minimum": MIN_LIVE_STATIONS},
        )

    native_rows = [{column: cast("dict[str, object]", row)[column] for column in METADATA_COLUMNS} for row in payload]
    source_rows = pl.DataFrame(native_rows, schema=NATIVE_SOURCE_SCHEMA).sort("metadata_station_no")
    return WithIssues(value=stamp_native_table(source_rows, retrieved_at), issues=())


def refresh_native_table_from_file(
    payload_path: Path | str,
    *,
    retrieved_at: RetrievedAt,
    input_kind: RefreshInputKind,
) -> WithIssues[NativeTable]:
    path = Path(payload_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _refresh_failure(
            retrieved_at,
            CatalogueIssueCode.REFRESH_PAYLOAD_READ_FAILED,
            f"Unable to read ba_fhmzbih native payload: {path}",
            {"path": str(path), "reason": str(exc)},
        )
    return refresh_native_table(payload, retrieved_at=retrieved_at, input_kind=input_kind)


def materialize_native_table(
    payload: object,
    native_out: Path | str,
    *,
    retrieved_at: RetrievedAt,
    input_kind: RefreshInputKind,
) -> WithIssues[NativeTable]:
    outcome = refresh_native_table(payload, retrieved_at=retrieved_at, input_kind=input_kind)
    if not any(issue.severity == "error" for issue in outcome.issues):
        write_native_table(outcome.value, native_out)
    return outcome


def native_table_content_digest(table: NativeTable) -> str:
    payload = {
        "columns": table.data.columns,
        "rows": [[_canonical_json_value(value) for value in row] for row in table.data.iter_rows()],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _canonical_json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, tuple | list):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_json_value(item) for key, item in value.items()}
    return value


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
) -> GeneratedBaFhmzbihCatalogue:
    if native_table.data.is_empty():
        raise FatalContractError("ba_fhmzbih native table must not be empty")
    _validate_native_build_rows(native_table)
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    station_dates = native_table.data.select(
        pl.col("metadata_station_no").alias("station_id"),
        pl.col("retrieved_at").dt.date().alias("retrieved_date"),
    )
    station_products = build_station_products(station_dates)
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("ba_fhmzbih native table has no valid retrieved_at values")
    provider_info = build_provider_info(maximum_retrieved_at.date())
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
        }
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(native_table: NativeTable) -> StationCatalog:
    try:
        return native_table.data.select(
            pl.lit(PROVIDER_ID).cast(pl.String).alias("provider_id"),
            pl.col("metadata_station_no").cast(pl.String, strict=True).alias("station_id"),
            pl.col("metadata_station_latitude").cast(pl.Float64, strict=True).alias("latitude"),
            pl.col("metadata_station_longitude").cast(pl.Float64, strict=True).alias("longitude"),
            pl.lit("unknown").cast(pl.String).alias("crs"),
        ).sort("station_id")
    except pl.exceptions.PolarsError as exc:
        raise FatalContractError("ba_fhmzbih native table has invalid station columns") from exc


def build_station_products(
    station_dates: pl.DataFrame,
) -> StationProductCatalog:
    rows = []
    for station_id, retrieved_date in station_dates.iter_rows():
        if not isinstance(station_id, str) or not isinstance(retrieved_date, date):
            raise FatalContractError("station retrieval date must pair a string identifier with a date")
        for d in PRODUCT_DEFINITIONS:
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
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


def build_provider_info(
    catalogue_date: date,
) -> dict[str, object]:
    return {
        "provider_id": PROVIDER_ID,
        "name": PROVIDER_NAME,
        "live_stations": False,
        "live_products": False,
        "live_station_products": False,
        "bulk_observations": (
            "true: per (station, parameter) workbook fetch; partial failures reported as "
            "recoverable issues; only a rolling ~1-year window of history is available from the source"
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


def _iter_station_rows(raw_payload: list[object]) -> WithIssues[list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    issues: list[Issue] = []
    seen: set[str] = set()
    coordinate_columns = {
        "metadata_station_latitude",
        "metadata_station_longitude",
    }
    remaining_required = set(METADATA_COLUMNS) - coordinate_columns - {"metadata_station_no"}
    for index, item in enumerate(raw_payload):
        row: dict[str, object] | None = None
        station_id: str | None = None
        if not isinstance(item, dict):
            issues.append(
                _issue(
                    CatalogueIssueCode.REFRESH_INVALID_ROW,
                    f"ba_fhmzbih station row at index {index} must be an object",
                    {"index": index},
                )
            )
        else:
            row = cast("dict[str, object]", item)
            station_id_value = row.get("metadata_station_no")
            if (
                not isinstance(station_id_value, str)
                or not station_id_value
                or station_id_value.isspace()
                or station_id_value.lower() in {"nan", "none", "null"}
            ):
                issues.append(
                    _issue(
                        CatalogueIssueCode.INVALID_STATION_ID,
                        f"ba_fhmzbih station row at index {index} has missing or blank metadata_station_no",
                        {"index": index},
                    )
                )
            elif station_id_value in seen:
                station_id = station_id_value
                issues.append(
                    _issue(
                        CatalogueIssueCode.DUPLICATE_STATION_ID,
                        f"ba_fhmzbih duplicate metadata_station_no {station_id}",
                        {"station_id": station_id},
                    )
                )
            else:
                station_id = station_id_value
                latitude = _to_float(row.get("metadata_station_latitude"))
                longitude = _to_float(row.get("metadata_station_longitude"))
                if latitude is None or longitude is None:
                    issues.append(
                        _issue(
                            CatalogueIssueCode.INVALID_STATION_COORDINATES,
                            f"ba_fhmzbih station {station_id} has unparseable "
                            "metadata_station_latitude or metadata_station_longitude",
                            {"station_id": station_id},
                        )
                    )
                else:
                    missing = sorted(column for column in remaining_required if column not in row)
                    if missing:
                        issues.append(
                            _issue(
                                CatalogueIssueCode.REFRESH_MISSING_REQUIRED_FIELDS,
                                f"ba_fhmzbih station row at index {index} is missing required source fields: "
                                f"{', '.join(missing)}",
                                {"index": index, "fields": missing},
                            )
                        )
                    else:
                        invalid_types = sorted(
                            column for column in METADATA_COLUMNS if not isinstance(row[column], str)
                        )
                        if invalid_types:
                            issues.append(
                                _issue(
                                    CatalogueIssueCode.REFRESH_INVALID_SOURCE_TYPES,
                                    f"ba_fhmzbih station row at index {index} has non-string source fields: "
                                    f"{', '.join(invalid_types)}",
                                    {"index": index, "fields": invalid_types},
                                )
                            )
                        else:
                            seen.add(station_id)
                            rows.append(
                                {
                                    "provider_id": PROVIDER_ID,
                                    "station_id": station_id,
                                    "latitude": latitude,
                                    "longitude": longitude,
                                    "crs": "unknown",
                                }
                            )
    return WithIssues(value=rows, issues=tuple(issues))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _to_float(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _validate_native_build_rows(native_table: NativeTable) -> None:
    frame = native_table.data
    missing = [column for column in (*METADATA_COLUMNS, "retrieved_at") if column not in frame.columns]
    if missing:
        raise FatalContractError(f"ba_fhmzbih native table is missing columns: {', '.join(missing)}")
    seen: set[str] = set()
    for index, row in enumerate(frame.select(*METADATA_COLUMNS, "retrieved_at").iter_rows(named=True)):
        invalid_types = [column for column in METADATA_COLUMNS if not isinstance(row[column], str)]
        if invalid_types:
            raise FatalContractError(
                f"ba_fhmzbih native table row {index} has non-string source fields: {', '.join(invalid_types)}"
            )
        station_id = cast("str", row["metadata_station_no"])
        if not station_id.strip() or station_id.lower() in {"nan", "none", "null"}:
            raise FatalContractError(f"ba_fhmzbih native table row {index} has invalid metadata_station_no")
        if station_id in seen:
            raise FatalContractError(f"ba_fhmzbih native table has duplicate metadata_station_no {station_id}")
        seen.add(station_id)
        if _to_float(row["metadata_station_latitude"]) is None or _to_float(row["metadata_station_longitude"]) is None:
            raise FatalContractError(f"ba_fhmzbih native table station {station_id} has invalid coordinates")
        if not isinstance(row["retrieved_at"], datetime):
            raise FatalContractError(f"ba_fhmzbih native table station {station_id} has invalid retrieved_at")


def _empty_native_table(retrieved_at: RetrievedAt) -> NativeTable:
    return stamp_native_table(pl.DataFrame(schema=NATIVE_SOURCE_SCHEMA), retrieved_at)


def _issue(code: CatalogueIssueCode, message: str, details: dict[str, object]) -> Issue:
    return Issue(
        severity="error",
        code=str(code),
        message=message,
        details=details,
        provider_id=PROVIDER_ID,
    )


def _refresh_failure(
    retrieved_at: RetrievedAt,
    code: CatalogueIssueCode,
    message: str,
    details: dict[str, object],
) -> WithIssues[NativeTable]:
    return WithIssues(
        value=_empty_native_table(retrieved_at),
        issues=(_issue(code, message, details),),
    )


def _parse_retrieved_at(value: str) -> RetrievedAt:
    if not value.endswith("Z") or value.count("Z") != 1:
        raise argparse.ArgumentTypeError("retrieved_at must be an ISO 8601 UTC instant ending in Z")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
        return RetrievedAt(parsed)
    except (ValueError, FatalContractError) as exc:
        raise argparse.ArgumentTypeError("retrieved_at must be an ISO 8601 UTC instant ending in Z") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the packaged ba_fhmzbih catalogue artifacts.",
        allow_abbrev=False,
    )
    parser.add_argument("--native", type=Path, help="Path to the committed native Parquet table.")
    parser.add_argument("--native-payload", type=Path, help="Path to an attested layers/20 JSON payload.")
    parser.add_argument("--native-out", type=Path, help="Output path for the native Parquet table.")
    parser.add_argument("--retrieved-at", type=_parse_retrieved_at, help="UTC retrieval instant ending in Z.")
    parser.add_argument("--native-input-kind", choices=RefreshInputKind)
    parser.add_argument("--out", type=Path, help="Output directory for provider.json and parquet files.")
    args = parser.parse_args(argv)

    if args.native_payload is not None and (args.native is not None or args.out is not None):
        parser.error("--native-payload cannot be combined with --native or --out")
    if args.native_payload is not None and args.native_out is None:
        parser.error("--native-payload requires --native-out")
    if args.native_payload is not None and args.retrieved_at is None:
        parser.error("--native-payload requires --retrieved-at")
    if args.native_payload is not None and args.native_input_kind is None:
        parser.error("--native-payload requires --native-input-kind")
    if args.native_out is not None and args.native_payload is None:
        parser.error("--native-out requires --native-payload")
    if args.retrieved_at is not None and args.native_payload is None:
        parser.error("--retrieved-at requires --native-payload")
    if args.native_input_kind is not None and args.native_payload is None:
        parser.error("--native-input-kind requires --native-payload")
    if args.native is not None and args.out is None:
        parser.error("--native requires --out")
    if args.out is not None and args.native is None:
        parser.error("--out requires --native")
    if args.native is None and args.native_payload is None:
        parser.error("one of --native or --native-payload is required")

    if args.native_payload is not None:
        try:
            payload = json.loads(args.native_payload.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FatalContractError(f"Unable to read ba_fhmzbih native payload: {args.native_payload}") from exc
        outcome = materialize_native_table(
            payload,
            args.native_out,
            retrieved_at=args.retrieved_at,
            input_kind=RefreshInputKind(args.native_input_kind),
        )
        errors = tuple(issue for issue in outcome.issues if issue.severity == "error")
        if errors:
            raise FatalContractError(errors[0].message, issues=errors)
        digest = native_table_content_digest(read_native_table(args.native_out))
        print(f"ba_fhmzbih native table content SHA-256: {digest}")
        return 0

    from rivretrieve._internal.providers.ba_fhmzbih.origins import STATION_CATALOGUE_ORIGINS

    catalogue = build_catalogue(read_native_table(args.native), STATION_CATALOGUE_ORIGINS)
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

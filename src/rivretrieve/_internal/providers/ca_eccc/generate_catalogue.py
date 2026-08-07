"""Canada catalogue maintenance : refresh(OgcHydrometricStationPages, RetrievedAt) → WithIssues[NativeTable]; build(NativeTable, OriginDeclarations) → GeneratedCaEcccCatalogue."""

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
import requests

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

PROVIDER_ID = ProviderId("ca_eccc")
PROVIDER_NAME = "ECCC Hydrometric — Environment and Climate Change Canada"
BASE_URL = "https://api.weather.gc.ca/"
STATIONS_URL = f"{BASE_URL}collections/hydrometric-stations/items"
DAILY_MEAN_URL = f"{BASE_URL}collections/hydrometric-daily-mean/items"
MIN_LIVE_STATIONS = 8055
STATION_PAGE_SIZE = 1000

NATIVE_SOURCE_SCHEMA = pl.Schema(
    {
        "id": pl.String,
        "STATION_NAME": pl.String,
        "IDENTIFIER": pl.String,
        "STATION_NUMBER": pl.String,
        "PROV_TERR_STATE_LOC": pl.String,
        "STATUS_EN": pl.String,
        "STATUS_FR": pl.String,
        "CONTRIBUTOR_EN": pl.String,
        "CONTRIBUTOR_FR": pl.String,
        "VERTICAL_DATUM": pl.String,
        "REAL_TIME": pl.Int64,
        "RHBN": pl.Int64,
        "DRAINAGE_AREA_GROSS": pl.Float64,
        "DRAINAGE_AREA_EFFECT": pl.Float64,
        "geometry.type": pl.String,
        "geometry.coordinates[0]": pl.Float64,
        "geometry.coordinates[1]": pl.Float64,
    }
)
PROPERTY_COLUMNS = tuple(NATIVE_SOURCE_SCHEMA.names()[1:14])


class CatalogueIssueCode(StrEnum):
    REFRESH_REQUEST_FAILED = "refresh_request_failed"
    REFRESH_INVALID_PAGE = "refresh_invalid_page"
    REFRESH_INCONSISTENT_TOTAL = "refresh_inconsistent_total"
    REFRESH_DUPLICATE_PAGE = "refresh_duplicate_page"
    REFRESH_DUPLICATE_FEATURE = "refresh_duplicate_feature"
    REFRESH_MISSING_PAGE = "refresh_missing_page"
    REFRESH_SHORT_PAGE = "refresh_short_page"
    REFRESH_PREMATURE_EMPTY_PAGE = "refresh_premature_empty_page"
    REFRESH_COUNT_UNDERFLOW = "refresh_count_underflow"
    REFRESH_COUNT_OVERFLOW = "refresh_count_overflow"
    REFRESH_BELOW_MINIMUM = "refresh_below_minimum"
    INVALID_STATION_ID = "invalid_station_id"
    DUPLICATE_STATION_ID = "duplicate_station_id"
    INVALID_STATION_COORDINATES = "invalid_station_coordinates"


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    frequency: str
    statistic: str
    period_type: str
    period_anchor: str
    canonical_unit: str
    ogc_field: str


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        product_id="discharge_daily_mean",
        observed_property="discharge",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        ogc_field="DISCHARGE",
    ),
    ProductDefinition(
        product_id="stage_daily_mean",
        observed_property="stage",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m",
        ogc_field="LEVEL",
    ),
)


@dataclass(frozen=True)
class GeneratedCaEcccCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog


def refresh_native_table(
    payload: object,
    *,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    features, issues = _validate_feature_collection(payload)
    if issues:
        return WithIssues(value=_empty_native_table(retrieved_at), issues=tuple(issues))
    page = cast("dict[str, object]", payload)
    number_matched = cast("int", page["numberMatched"])
    if len(features) != number_matched:
        code = (
            CatalogueIssueCode.REFRESH_COUNT_UNDERFLOW
            if len(features) < number_matched
            else CatalogueIssueCode.REFRESH_COUNT_OVERFLOW
        )
        return _refresh_failure(
            retrieved_at,
            code,
            f"ca_eccc complete response contains {len(features)} features for numberMatched {number_matched}",
            {"accumulated": len(features), "numberMatched": number_matched},
        )
    rows: list[dict[str, object]] = []
    flatten_issues: list[Issue] = []
    for index, feature in enumerate(features):
        row, issue = _flatten_feature(feature, index=index)
        if issue is not None:
            flatten_issues.append(issue)
        elif row is not None:
            rows.append(row)
    if flatten_issues:
        return WithIssues(value=_empty_native_table(retrieved_at), issues=tuple(flatten_issues))
    source = pl.DataFrame(rows, schema=NATIVE_SOURCE_SCHEMA).sort("id")
    return WithIssues(value=stamp_native_table(source, retrieved_at), issues=())


def refresh_native_table_from_fixture(
    fixture_path: Path | str,
    *,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    try:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return WithIssues(
            value=_empty_native_table(retrieved_at),
            issues=(
                _issue(
                    CatalogueIssueCode.REFRESH_INVALID_PAGE,
                    f"ca_eccc fixture could not be read: {exc}",
                    {"path": str(fixture_path)},
                ),
            ),
        )
    return refresh_native_table(payload, retrieved_at=retrieved_at)


def refresh_native_table_from_live(
    *,
    retrieved_at: RetrievedAt,
    page_size: int = STATION_PAGE_SIZE,
    minimum_stations: int = MIN_LIVE_STATIONS,
) -> WithIssues[NativeTable]:
    features: list[object] = []
    feature_ids: set[str] = set()
    page_signatures: set[tuple[str, ...]] = set()
    expected_total: int | None = None
    offset = 0
    while expected_total is None or len(features) < expected_total:
        try:
            payload = _request_station_page(offset=offset, limit=page_size)
        except KeyError as exc:
            return _refresh_failure(
                retrieved_at,
                CatalogueIssueCode.REFRESH_MISSING_PAGE,
                f"ca_eccc station page is missing at offset {offset}: {exc}",
                {"offset": offset},
            )
        except (requests.RequestException, ValueError) as exc:
            return _refresh_failure(
                retrieved_at,
                CatalogueIssueCode.REFRESH_REQUEST_FAILED,
                f"ca_eccc station page request failed at offset {offset}: {exc}",
                {"offset": offset},
            )
        page_features, page_issues = _validate_feature_collection(payload)
        if page_issues:
            return WithIssues(value=_empty_native_table(retrieved_at), issues=tuple(page_issues))
        page = cast("dict[str, object]", payload)
        page_total = cast("int", page["numberMatched"])
        number_returned = cast("int", page["numberReturned"])
        if expected_total is None:
            expected_total = page_total
        elif page_total != expected_total:
            return _refresh_failure(
                retrieved_at,
                CatalogueIssueCode.REFRESH_INCONSISTENT_TOTAL,
                f"ca_eccc page offset {offset} changed numberMatched from {expected_total} to {page_total}",
                {"offset": offset, "expected": expected_total, "actual": page_total},
            )
        ids: list[str] = []
        for index, item in enumerate(page_features):
            if not isinstance(item, dict):
                return _refresh_failure(
                    retrieved_at,
                    CatalogueIssueCode.REFRESH_INVALID_PAGE,
                    f"ca_eccc page offset {offset} contains an invalid feature at index {index}",
                    {"offset": offset, "index": index},
                )
            item_data = cast("dict[str, object]", item)
            if not isinstance(item_data.get("id"), str):
                return _refresh_failure(
                    retrieved_at,
                    CatalogueIssueCode.REFRESH_INVALID_PAGE,
                    f"ca_eccc page offset {offset} contains an invalid feature at index {index}",
                    {"offset": offset, "index": index},
                )
            feature_id = cast("str", item_data["id"])
            ids.append(feature_id)
        signature = tuple(ids)
        if signature and signature in page_signatures:
            return _refresh_failure(
                retrieved_at,
                CatalogueIssueCode.REFRESH_DUPLICATE_PAGE,
                f"ca_eccc page offset {offset} repeats an earlier page",
                {"offset": offset},
            )
        for feature_id in ids:
            if feature_id in feature_ids:
                return _refresh_failure(
                    retrieved_at,
                    CatalogueIssueCode.REFRESH_DUPLICATE_FEATURE,
                    f"ca_eccc page offset {offset} repeats feature id {feature_id}",
                    {"offset": offset, "diagnostic_id": feature_id},
                )
        page_signatures.add(signature)
        feature_ids.update(ids)
        if number_returned == 0 and len(features) < expected_total:
            return _refresh_failure(
                retrieved_at,
                CatalogueIssueCode.REFRESH_PREMATURE_EMPTY_PAGE,
                f"ca_eccc page offset {offset} is empty before numberMatched is reached",
                {"offset": offset, "accumulated": len(features), "numberMatched": expected_total},
            )
        if number_returned < page_size and len(features) + number_returned < expected_total:
            return _refresh_failure(
                retrieved_at,
                CatalogueIssueCode.REFRESH_SHORT_PAGE,
                f"ca_eccc page offset {offset} is short before numberMatched is reached",
                {"offset": offset, "numberReturned": number_returned, "numberMatched": expected_total},
            )
        features.extend(page_features)
        if len(features) > expected_total:
            return _refresh_failure(
                retrieved_at,
                CatalogueIssueCode.REFRESH_COUNT_OVERFLOW,
                f"ca_eccc accumulated {len(features)} features above numberMatched {expected_total}",
                {"accumulated": len(features), "numberMatched": expected_total},
            )
        offset += page_size
    if expected_total is None or len(features) != expected_total:
        return _refresh_failure(
            retrieved_at,
            CatalogueIssueCode.REFRESH_COUNT_UNDERFLOW,
            f"ca_eccc accumulated {len(features)} features below numberMatched {expected_total}",
            {"accumulated": len(features), "numberMatched": expected_total},
        )
    envelope = {
        "type": "FeatureCollection",
        "numberMatched": expected_total,
        "numberReturned": expected_total,
        "features": features,
    }
    outcome = refresh_native_table(envelope, retrieved_at=retrieved_at)
    if outcome.issues:
        return outcome
    station_outcome = _iter_station_rows(_canonical_station_input(outcome.value))
    if station_outcome.issues:
        return WithIssues(value=outcome.value, issues=station_outcome.issues)
    if len(station_outcome.value) < minimum_stations:
        return WithIssues(
            value=outcome.value,
            issues=(
                _issue(
                    CatalogueIssueCode.REFRESH_BELOW_MINIMUM,
                    f"ca_eccc live catalogue returned only {len(station_outcome.value)} usable stations "
                    f"(expected at least {minimum_stations})",
                    {"actual": len(station_outcome.value), "minimum": minimum_stations},
                ),
            ),
        )
    return outcome


def build_catalogue(native_table: NativeTable, origins: OriginDeclarations) -> GeneratedCaEcccCatalogue:
    if native_table.data.is_empty():
        raise FatalContractError("Canada native table must not be empty")
    products = build_products()
    stations = build_stations(_canonical_station_input(native_table))
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    station_dates = native_table.data.select(
        pl.col("STATION_NUMBER").alias("station_id"),
        pl.col("retrieved_at").dt.date().alias("retrieved_date"),
    )
    station_products = build_station_products(station_dates)
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("Canada native table has no valid retrieved_at values")
    provider_info = build_provider_info(maximum_retrieved_at.date())
    _validate(provider_info, products, stations, station_products)
    return GeneratedCaEcccCatalogue(provider_info, products, stations, station_products)


def build_products() -> ProductCatalog:
    rows = [
        {
            "provider_id": PROVIDER_ID,
            "product_id": definition.product_id,
            "observed_property": definition.observed_property,
            "frequency": definition.frequency,
            "statistic": definition.statistic,
            "period_type": definition.period_type,
            "period_anchor": definition.period_anchor,
            "unit": definition.canonical_unit,
            "native_id": definition.ogc_field,
        }
        for definition in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def _iter_station_rows(station_rows: list[dict[str, object]]) -> WithIssues[list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    issues: list[Issue] = []
    seen: set[str] = set()
    for index, row in enumerate(station_rows):
        diagnostic_id = row.get("id") if isinstance(row.get("id"), str) else f"row-{index}"
        station_id = row.get("STATION_NUMBER")
        if not isinstance(station_id, str) or not station_id:
            issues.append(
                _issue(
                    CatalogueIssueCode.INVALID_STATION_ID,
                    f"ca_eccc station {diagnostic_id} has missing or empty STATION_NUMBER",
                    {"diagnostic_id": diagnostic_id, "reason": "missing_or_empty_station_number"},
                )
            )
            continue
        if station_id in seen:
            issues.append(
                _issue(
                    CatalogueIssueCode.DUPLICATE_STATION_ID,
                    f"ca_eccc station {diagnostic_id} duplicates STATION_NUMBER {station_id}",
                    {
                        "diagnostic_id": diagnostic_id,
                        "reason": "duplicate_station_number",
                        "station_id": station_id,
                    },
                )
            )
            continue
        latitude = row.get("LATITUDE")
        longitude = row.get("LONGITUDE")
        if latitude is None or longitude is None:
            issues.append(
                _issue(
                    CatalogueIssueCode.INVALID_STATION_COORDINATES,
                    f"ca_eccc station {diagnostic_id} has missing or null coordinates",
                    {"diagnostic_id": diagnostic_id, "reason": "missing_or_null_coordinates"},
                )
            )
            continue
        if (
            isinstance(latitude, bool)
            or isinstance(longitude, bool)
            or not isinstance(latitude, int | float)
            or not isinstance(longitude, int | float)
        ):
            issues.append(
                _issue(
                    CatalogueIssueCode.INVALID_STATION_COORDINATES,
                    f"ca_eccc station {diagnostic_id} has non-numeric coordinates",
                    {"diagnostic_id": diagnostic_id, "reason": "non_numeric_coordinates"},
                )
            )
            continue
        seen.add(station_id)
        rows.append(
            {
                "provider_id": PROVIDER_ID,
                "station_id": station_id,
                "latitude": float(latitude),
                "longitude": float(longitude),
                "crs": "EPSG:4326",
            }
        )
    return WithIssues(value=rows, issues=tuple(issues))


def build_stations(station_rows: list[dict[str, object]]) -> StationCatalog:
    outcome = _iter_station_rows(station_rows)
    if outcome.issues:
        raise FatalContractError(issues=outcome.issues)
    if not outcome.value:
        raise FatalContractError("ca_eccc: station build returned no rows")
    return pl.DataFrame(outcome.value, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(station_dates: pl.DataFrame) -> StationProductCatalog:
    rows: list[dict[str, object]] = []
    for station_id, retrieved_date in station_dates.iter_rows():
        if not isinstance(station_id, str) or not isinstance(retrieved_date, date):
            raise FatalContractError("station retrieval date must pair a string identifier with a date")
        for definition in PRODUCT_DEFINITIONS:
            availability_reason = (
                "ECCC OGC hydrometric-stations endpoint does not expose per-variable availability. "
                f"Actual availability depends on whether the station has {definition.ogc_field!r} values "
                "in the daily-mean collection."
            )
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": definition.product_id,
                    "availability": "unknown",
                    "availability_reason": availability_reason,
                    "start_date": None,
                    "end_date": None,
                    "last_catalogue_check": retrieved_date,
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
            "true: HYDAT SQLite queried locally (downloaded on first use, ~1 GB, cached in platformdirs user "
            "cache dir); one SQL query per station/product over the full requested year range; no windowing; "
            "quality flags from DATA_SYMBOLS table; no authentication required; partial failures reported as "
            "recoverable issues"
        ),
        "catalogue_version": catalogue_date.isoformat(),
        "license": None,
        "citation": None,
    }


def _validate(
    provider_info: dict[str, object],
    products: ProductCatalog,
    stations: StationCatalog,
    station_products: StationProductCatalog,
) -> None:
    validate_catalogue(
        pl.DataFrame([provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema),
        PROVIDER_INFO_CATALOG_SCHEMA,
        on_issue="raise",
    )
    validate_catalogue(products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    packaged_catalogue_artifact_from_components(provider_info, products, stations, station_products, on_issue="raise")


def write_catalogue(catalogue: GeneratedCaEcccCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "provider.json").write_text(
        f"{json.dumps(catalogue.provider_info, sort_keys=True, separators=(',', ':'))}\n",
        encoding="utf-8",
    )
    catalogue.products.write_parquet(output_path / "products.parquet", statistics=False)
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")


def _validate_feature_collection(payload: object) -> tuple[list[object], list[Issue]]:
    if not isinstance(payload, dict):
        return [], [
            _issue(
                CatalogueIssueCode.REFRESH_INVALID_PAGE,
                "ca_eccc station response must be a FeatureCollection object",
                {"reason": "invalid_envelope"},
            )
        ]
    payload_data = cast("dict[str, object]", payload)
    if payload_data.get("type") != "FeatureCollection":
        return [], [
            _issue(
                CatalogueIssueCode.REFRESH_INVALID_PAGE,
                "ca_eccc station response must be a FeatureCollection object",
                {"reason": "invalid_envelope"},
            )
        ]
    features = payload_data.get("features")
    number_matched = payload_data.get("numberMatched")
    number_returned = payload_data.get("numberReturned")
    if (
        not isinstance(features, list)
        or isinstance(number_matched, bool)
        or isinstance(number_returned, bool)
        or not isinstance(number_matched, int)
        or not isinstance(number_returned, int)
        or number_matched < 0
        or number_returned < 0
        or number_returned != len(features)
    ):
        return [], [
            _issue(
                CatalogueIssueCode.REFRESH_INVALID_PAGE,
                "ca_eccc station response has invalid counts or features",
                {"reason": "invalid_counts_or_features"},
            )
        ]
    return cast("list[object]", features), []


def _flatten_feature(feature: object, *, index: int) -> tuple[dict[str, object] | None, Issue | None]:
    if not isinstance(feature, dict):
        return None, _issue(
            CatalogueIssueCode.REFRESH_INVALID_PAGE,
            f"ca_eccc feature at index {index} must be an object",
            {"index": index, "reason": "invalid_feature"},
        )
    feature_data = cast("dict[str, object]", feature)
    feature_id = feature_data.get("id")
    properties = feature_data.get("properties")
    geometry = feature_data.get("geometry")
    if (
        not isinstance(feature_id, str)
        or not isinstance(properties, dict)
        or not isinstance(geometry, dict)
        or not all(column in properties for column in PROPERTY_COLUMNS)
    ):
        return None, _issue(
            CatalogueIssueCode.REFRESH_INVALID_PAGE,
            f"ca_eccc feature at index {index} is missing required source fields",
            {"index": index, "reason": "missing_source_fields"},
        )
    properties_data = cast("dict[str, object]", properties)
    geometry_data = cast("dict[str, object]", geometry)
    coordinates = geometry_data.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None, _issue(
            CatalogueIssueCode.REFRESH_INVALID_PAGE,
            f"ca_eccc feature {feature_id} has invalid geometry coordinates",
            {"diagnostic_id": feature_id, "reason": "invalid_geometry"},
        )
    row: dict[str, object] = {"id": feature_id}
    row.update({column: properties_data[column] for column in PROPERTY_COLUMNS})
    row["geometry.type"] = geometry_data.get("type")
    row["geometry.coordinates[0]"] = coordinates[0]
    row["geometry.coordinates[1]"] = coordinates[1]
    try:
        frame = pl.DataFrame([row], schema=NATIVE_SOURCE_SCHEMA)
    except (TypeError, ValueError, pl.exceptions.PolarsError):
        return None, _issue(
            CatalogueIssueCode.REFRESH_INVALID_PAGE,
            f"ca_eccc feature {feature_id} has source values outside the native schema",
            {"diagnostic_id": feature_id, "reason": "invalid_source_types"},
        )
    return frame.row(0, named=True), None


def _canonical_station_input(native_table: NativeTable) -> list[dict[str, object]]:
    return native_table.data.select(
        "id",
        "STATION_NUMBER",
        pl.col("geometry.coordinates[1]").alias("LATITUDE"),
        pl.col("geometry.coordinates[0]").alias("LONGITUDE"),
    ).to_dicts()


def _empty_native_table(retrieved_at: RetrievedAt) -> NativeTable:
    return stamp_native_table(pl.DataFrame(schema=NATIVE_SOURCE_SCHEMA), retrieved_at)


def _request_station_page(*, offset: int, limit: int) -> object:
    response = requests.get(
        STATIONS_URL,
        params={"f": "json", "limit": limit, "offset": offset},
        timeout=60,
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()


def _issue(code: CatalogueIssueCode, message: str, details: dict[str, object]) -> Issue:
    return Issue(severity="error", code=str(code), message=message, details=details, provider_id=PROVIDER_ID)


def _refresh_failure(
    retrieved_at: RetrievedAt,
    code: CatalogueIssueCode,
    message: str,
    details: dict[str, object],
) -> WithIssues[NativeTable]:
    return WithIssues(value=_empty_native_table(retrieved_at), issues=(_issue(code, message, details),))


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
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, tuple | list):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_json_value(item) for key, item in value.items()}
    return value


def _raise_on_error_issues(outcome: WithIssues[NativeTable]) -> NativeTable:
    errors = tuple(issue for issue in outcome.issues if issue.severity == "error")
    if errors:
        raise FatalContractError(issues=errors)
    return outcome.value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh or build the packaged ca_eccc catalogue.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path)
    source.add_argument("--live", action="store_true")
    source.add_argument("--native", type=Path)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--native-out", type=Path)
    destination.add_argument("--out", type=Path)
    parser.add_argument("--retrieved-at", type=lambda value: RetrievedAt(datetime.fromisoformat(value)))
    args = parser.parse_args(argv)
    if args.native_out is not None:
        if args.native is not None:
            parser.error("--native cannot be used with --native-out")
        if args.retrieved_at is None:
            parser.error("--retrieved-at is required with --native-out")
        outcome = (
            refresh_native_table_from_live(retrieved_at=args.retrieved_at)
            if args.live
            else refresh_native_table_from_fixture(args.fixture, retrieved_at=args.retrieved_at)
        )
        write_native_table(_raise_on_error_issues(outcome), args.native_out)
        digest = native_table_content_digest(read_native_table(args.native_out))
        print(f"ca_eccc native table content SHA-256: {digest}")
        return 0
    if args.native is None:
        parser.error("--out requires --native")
    if args.retrieved_at is not None:
        parser.error("--retrieved-at is only valid with refresh mode")
    from rivretrieve._internal.providers.ca_eccc.origins import STATION_CATALOGUE_ORIGINS

    write_catalogue(build_catalogue(read_native_table(args.native), STATION_CATALOGUE_ORIGINS), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

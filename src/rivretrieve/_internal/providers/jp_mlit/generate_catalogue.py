"""refresh_native_table : Responses × StationIds × RetrievedAtByStation × PriorNativeTable? → WithIssues[NativeTable]

build_catalogue : NativeTable × OriginDeclarations → GeneratedJpMlitCatalogue
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path

import polars as pl
import polars.testing as pl_testing

from rivretrieve._internal.catalogue_origins import OriginDeclarations, enforce_catalogue_origins
from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, read_native_table
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
from rivretrieve._internal.providers.jp_mlit.origins import (
    NATIVE_TABLE_SHA256,
    build_acquisition_provenance,
)

PROVIDER_ID = ProviderId("jp_mlit")
PROVIDER_NAME = "MLIT Water Information System — Japan national hydrometric network"

SITE_INFO_DETAIL_URL = "http://www1.river.go.jp/cgi-bin/SiteInfoDetail.exe"
DSP_URL = "http://www1.river.go.jp/cgi-bin/DspWaterData.exe"
CATALOGUE_SOURCE = "src/rivretrieve/_internal/providers/jp_mlit/catalogue/native.parquet"

_LIVE_REQUEST_DELAY_SECONDS = 0.3  # polite rate limit between SiteInfoDetail requests
_LIVE_TIMEOUT_SECONDS = 20

AVAILABILITY_REASON = "jp_mlit native station table does not publish per-KIND station availability"
AVAILABILITY_SOURCE = "native_station_table_not_published"

MIN_LIVE_STATIONS = 500

NATIVE_COLUMNS = (
    "観測所名",
    "観測項目",
    "観測所記号",
    "水系名",
    "河川名",
    "観測所管理者名",
    "観測所種別",
    "観測開始時期",
    "所在地",
    "河口または合流点からの距離",
    "世界測地系",
    "日本測地系",
    "流域面積",
    "零点高",
)
NATIVE_SCHEMA = pl.Schema({**dict.fromkeys(NATIVE_COLUMNS, pl.Utf8), "retrieved_at": pl.Datetime("us", "UTC")})
_SOURCE_MARKER = "世界測地系".encode("euc-jp")
_ABSENCE_PATTERN = re.compile(r"指定された観測所記号\((\d{15})\)の観測所諸元は存在しません。")
_STRICT_DMS_PATTERN = re.compile(r"北緯\s*(\d+)度(\d+)分(\d+)秒\s*東経\s*(\d+)度(\d+)分(\d+)秒")


class CatalogueIssueCode(StrEnum):
    STATION_NOT_PUBLISHED = "station_not_published"
    REFRESH_RESPONSE_REJECTED = "refresh_response_rejected"
    REFRESH_DECODE_FAILED = "refresh_decode_failed"
    INVALID_STATION_COORDINATES = "invalid_station_coordinates"
    REFRESH_REQUEST_FAILED = "refresh_request_failed"
    REFRESH_HTTP_FAILED = "refresh_http_failed"


@dataclass(frozen=True)
class GeneratedJpMlitCatalogue:
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
    kind: int


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        product_id="stage_hourly_mean",
        observed_property="stage",
        frequency="hourly",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m",
        kind=2,
    ),
    ProductDefinition(
        product_id="stage_daily_mean",
        observed_property="stage",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m",
        kind=3,
    ),
    ProductDefinition(
        product_id="discharge_hourly_mean",
        observed_property="discharge",
        frequency="hourly",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        kind=6,
    ),
    ProductDefinition(
        product_id="discharge_daily_mean",
        observed_property="discharge",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        kind=7,
    ),
)

EXPECTED_PRODUCT_IDS = frozenset(d.product_id for d in PRODUCT_DEFINITIONS)


def build_catalogue(native_table: NativeTable, origins: OriginDeclarations) -> GeneratedJpMlitCatalogue:
    if native_table.data.is_empty():
        raise FatalContractError("jp_mlit native table must not be empty")
    if native_table.data.schema != NATIVE_SCHEMA:
        raise FatalContractError("jp_mlit native table schema does not match NATIVE_SCHEMA")
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    station_dates = native_table.data.select(
        pl.col("観測所記号").alias("station_id"),
        pl.col("retrieved_at").dt.date().alias("retrieved_date"),
    )
    station_products = build_station_products(station_dates)
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("jp_mlit native table has no valid retrieved_at values")
    provider_info = build_provider_info(maximum_retrieved_at.date())
    _validate(provider_info, products, stations, station_products)
    return GeneratedJpMlitCatalogue(provider_info, products, stations, station_products)


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
            "native_id": str(d.kind),
        }
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(
    native_table: NativeTable,
) -> StationCatalog:
    rows: list[dict[str, object]] = []
    for station_id, coordinate in native_table.data.select("観測所記号", "世界測地系").iter_rows():
        if not isinstance(coordinate, str) or (match := _STRICT_DMS_PATTERN.fullmatch(coordinate)) is None:
            raise FatalContractError(
                f"jp_mlit station {station_id}: 世界測地系 has no parseable whole-number DMS coordinate"
            )
        (
            latitude_degrees,
            latitude_minutes,
            latitude_seconds,
            longitude_degrees,
            longitude_minutes,
            longitude_seconds,
        ) = map(int, match.groups())
        latitude = latitude_degrees + latitude_minutes / 60 + latitude_seconds / 3600
        longitude = longitude_degrees + longitude_minutes / 60 + longitude_seconds / 3600
        if (
            latitude > 90
            or longitude > 180
            or latitude_minutes >= 60
            or longitude_minutes >= 60
            or latitude_seconds > 60
            or longitude_seconds > 60
        ):
            raise FatalContractError(f"jp_mlit station {station_id}: 世界測地系 contains an impossible DMS coordinate")
        rows.append(
            {
                "provider_id": PROVIDER_ID,
                "station_id": station_id,
                "latitude": latitude,
                "longitude": longitude,
                "crs": "unknown",
            }
        )
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(
    station_dates: pl.DataFrame,
) -> StationProductCatalog:
    rows = []
    for station_id, catalogue_date in station_dates.iter_rows():
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        for d in PRODUCT_DEFINITIONS:
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
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
            "true: monthly-window decomposition for hourly products (KINDs 2,6), "
            "yearly-window decomposition for daily products (KINDs 3,7); "
            "HTML scrape + Shift-JIS .dat download; partial failures reported as recoverable issues"
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
        acquisition_provenance=build_acquisition_provenance(),
        on_issue="raise",
    )


def write_catalogue(catalogue: GeneratedJpMlitCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as f:
        json.dump(catalogue.provider_info, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")
    (output_path / "provenance.json").write_text(
        build_acquisition_provenance().model_dump_json() + "\n",
        encoding="utf-8",
    )


class _NativeTdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() == "td" and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "td" and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell))
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
            self._cell = None


def _parse_native_site_detail(html: str) -> dict[str, str | None]:
    parser = _NativeTdParser()
    parser.feed(html)
    values: dict[str, str | None] = dict.fromkeys(NATIVE_COLUMNS)
    for row in parser.rows:
        for index, cell in enumerate(row[:-1]):
            if cell in values:
                values[cell] = row[index + 1]
    return values


def _accept_site_detail_response(http_status: int, body: bytes) -> bool:
    return http_status == 200 and _SOURCE_MARKER in body


def _issue(code: CatalogueIssueCode, station_id: str, reason: str) -> Issue:
    return Issue(
        severity="warning",
        code=code.value,
        provider_id=PROVIDER_ID,
        message=f"jp_mlit station {station_id}: {code.value}: {reason}",
        details={"station_id": station_id, "reason": reason},
    )


def _validate_station_ids(station_ids: Sequence[object]) -> tuple[str, ...]:
    validated: list[str] = []
    for value in station_ids:
        if not isinstance(value, str):
            raise FatalContractError("jp_mlit malformed input: station-id-type")
        if not value:
            raise FatalContractError("jp_mlit malformed input: station-id-blank")
        if value in validated:
            raise FatalContractError("jp_mlit malformed input: station-id-duplicate")
        validated.append(value)
    return tuple(validated)


def _validate_refresh_inputs(
    responses: Mapping[str, bytes],
    station_ids: Sequence[object],
    retrieved_at_by_station: Mapping[str, RetrievedAt],
    prior: NativeTable | None,
) -> tuple[str, ...]:
    ids = _validate_station_ids(station_ids)
    expected = set(ids)
    response_keys = set(responses)
    timestamp_keys = set(retrieved_at_by_station)
    if missing := expected - response_keys:
        raise FatalContractError(f"jp_mlit malformed input: response-keys-missing {sorted(missing)!r}")
    if extra := response_keys - expected:
        raise FatalContractError(f"jp_mlit malformed input: response-keys-extra {sorted(extra)!r}")
    if missing := expected - timestamp_keys:
        raise FatalContractError(f"jp_mlit malformed input: timestamp-keys-missing {sorted(missing)!r}")
    if extra := timestamp_keys - expected:
        raise FatalContractError(f"jp_mlit malformed input: timestamp-keys-extra {sorted(extra)!r}")
    for value in retrieved_at_by_station.values():
        offset = value.value.utcoffset() if isinstance(value, RetrievedAt) else None
        if offset != timedelta(0):
            raise FatalContractError("jp_mlit malformed input: retrieved-at-utc")
    if prior is not None:
        if prior.data.schema != NATIVE_SCHEMA:
            raise FatalContractError("jp_mlit malformed input: prior-schema")
        if prior.data["観測所記号"].n_unique() != prior.data.height:
            raise FatalContractError("jp_mlit malformed input: prior-id-duplicate")
    return ids


def _carry_or_raise(
    station_id: str,
    issue: Issue,
    prior: NativeTable | None,
) -> dict[str, object]:
    if prior is not None:
        rows = prior.data.filter(pl.col("観測所記号") == station_id)
        if rows.height == 1:
            return rows.row(0, named=True)
    raise FatalContractError(
        f"jp_mlit station {station_id}: {issue.code}; no prior row",
        issues=(issue,),
    )


def _native_table_from_rows(rows: list[dict[str, object]]) -> NativeTable:
    return NativeTable(pl.DataFrame(rows, schema=NATIVE_SCHEMA).sort("観測所記号"))


def refresh_native_table(
    responses: Mapping[str, bytes],
    *,
    station_ids: Sequence[object],
    retrieved_at_by_station: Mapping[str, RetrievedAt],
    prior: NativeTable | None = None,
) -> WithIssues[NativeTable]:
    ids = _validate_refresh_inputs(responses, station_ids, retrieved_at_by_station, prior)
    rows: list[dict[str, object]] = []
    issues: list[Issue] = []
    for station_id in ids:
        body = responses[station_id]
        if not isinstance(body, bytes):
            issue = _issue(CatalogueIssueCode.REFRESH_RESPONSE_REJECTED, station_id, "response body is not bytes")
            rows.append(_carry_or_raise(station_id, issue, prior))
            issues.append(issue)
            continue
        if not _accept_site_detail_response(200, body):
            decoded = body.decode("euc-jp", errors="replace")
            absent = _ABSENCE_PATTERN.search(decoded)
            if absent is not None and absent.group(1) == station_id:
                issues.append(
                    _issue(
                        CatalogueIssueCode.STATION_NOT_PUBLISHED,
                        station_id,
                        "source-confirmed absence: station specification is not published",
                    )
                )
                continue
            issue = _issue(
                CatalogueIssueCode.REFRESH_RESPONSE_REJECTED, station_id, "HTTP 200 response lacks source marker"
            )
            rows.append(_carry_or_raise(station_id, issue, prior))
            issues.append(issue)
            continue
        try:
            html = body.decode("euc-jp", errors="strict")
        except UnicodeDecodeError:
            issue = _issue(CatalogueIssueCode.REFRESH_DECODE_FAILED, station_id, "strict EUC-JP decoding failed")
            rows.append(_carry_or_raise(station_id, issue, prior))
            issues.append(issue)
            continue
        parsed = _parse_native_site_detail(html)
        if parsed["観測所記号"] != station_id:
            raise FatalContractError(f"jp_mlit malformed input: station-id-disagreement {station_id}")
        coordinate = parsed["世界測地系"]
        if not isinstance(coordinate, str) or _STRICT_DMS_PATTERN.fullmatch(coordinate) is None:
            issue = _issue(
                CatalogueIssueCode.INVALID_STATION_COORDINATES,
                station_id,
                "世界測地系 is not parseable whole-number DMS",
            )
            rows.append(_carry_or_raise(station_id, issue, prior))
            issues.append(issue)
            continue
        rows.append({**parsed, "retrieved_at": retrieved_at_by_station[station_id].value})
    return WithIssues(value=_native_table_from_rows(rows), issues=tuple(issues))


def _fetch_site_detail_response(station_id: str) -> tuple[int, bytes]:
    url = f"{SITE_INFO_DETAIL_URL}?ID={station_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "http://www1.river.go.jp"})
    with urllib.request.urlopen(req, timeout=_LIVE_TIMEOUT_SECONDS) as response:
        return response.status, response.read()


def refresh_native_table_from_live(
    station_ids: Sequence[object],
    *,
    prior: NativeTable | None = None,
) -> WithIssues[NativeTable]:
    """Refresh the native table through the maintainer-only per-station seam.

    MLIT warns at http://www1.river.go.jp/caution.html against automated bulk
    collection. This compatibility seam retains a polite delay and is not used
    by supplied-capture materialization.
    """
    ids = _validate_station_ids(station_ids)
    if len(ids) < MIN_LIVE_STATIONS:
        raise FatalContractError(f"jp_mlit live station count {len(ids)} is below minimum 500")
    rows: list[dict[str, object]] = []
    issues: list[Issue] = []
    responses: dict[str, bytes] = {}
    instants: dict[str, RetrievedAt] = {}
    for station_id in ids:
        try:
            status, body = _fetch_site_detail_response(station_id)
        except urllib.error.HTTPError as exc:
            issue = _issue(CatalogueIssueCode.REFRESH_HTTP_FAILED, station_id, f"HTTP status {exc.code}")
            rows.append(_carry_or_raise(station_id, issue, prior))
            issues.append(issue)
            continue
        except Exception as exc:
            issue = _issue(CatalogueIssueCode.REFRESH_REQUEST_FAILED, station_id, f"request failed: {exc}")
            rows.append(_carry_or_raise(station_id, issue, prior))
            issues.append(issue)
            continue
        instant = RetrievedAt(datetime.now(UTC))
        if status != 200:
            issue = _issue(CatalogueIssueCode.REFRESH_HTTP_FAILED, station_id, f"HTTP status {status}")
            rows.append(_carry_or_raise(station_id, issue, prior))
            issues.append(issue)
            continue
        responses[station_id] = body
        instants[station_id] = instant
        time.sleep(_LIVE_REQUEST_DELAY_SECONDS)
    if responses:
        fresh = refresh_native_table(
            responses,
            station_ids=tuple(responses),
            retrieved_at_by_station=instants,
            prior=prior,
        )
        rows.extend(fresh.value.data.iter_rows(named=True))
        issues.extend(fresh.issues)
    return WithIssues(value=_native_table_from_rows(rows), issues=tuple(issues))


def native_table_content_digest(table: NativeTable) -> str:
    ordered = table.data.sort("観測所記号")
    rows: list[list[object]] = []
    for row in ordered.iter_rows():
        values: list[object] = []
        for value in row:
            if isinstance(value, datetime):
                values.append(value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
            else:
                values.append(value)
        rows.append(values)
    canonical = json.dumps(
        {"columns": ordered.columns, "rows": rows},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _manifest_failure(token: str, reason: str) -> FatalContractError:
    return FatalContractError(f"jp_mlit supplied capture {token}: {reason}")


def _manifest_string(entry: Mapping[str, object], key: str) -> str:
    value = entry[key]
    if not isinstance(value, str):
        raise _manifest_failure("manifest-binding-type", key)
    if not value:
        raise _manifest_failure("manifest-binding-blank", key)
    return value


def _manifest_instant(value: object, *, start: datetime, end: datetime) -> RetrievedAt:
    if not isinstance(value, str) or not value:
        raise _manifest_failure("manifest-retrieved-at", "instant must be a non-blank string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise _manifest_failure("manifest-retrieved-at", value) from exc
    if not start <= parsed <= end:
        raise _manifest_failure("manifest-retrieved-at", f"outside campaign: {value}")
    return RetrievedAt(parsed)


def _load_supplied_capture(
    station_catalogue: Path,
    responses_dir: Path,
    manifest_path: Path,
) -> tuple[dict[str, bytes], tuple[str, ...], dict[str, RetrievedAt]]:
    try:
        raw_manifest = manifest_path.read_bytes()
    except OSError as exc:
        raise _manifest_failure("manifest-missing", str(manifest_path)) from exc
    try:
        manifest = json.loads(raw_manifest)
    except json.JSONDecodeError as exc:
        raise _manifest_failure("manifest-not-object", "invalid JSON") from exc
    if not isinstance(manifest, dict):
        raise _manifest_failure("manifest-not-object", "top level")
    try:
        base_frame = pl.read_parquet(station_catalogue)
        base_values = base_frame["station_id"].to_list()
    except (OSError, pl.exceptions.PolarsError, KeyError) as exc:
        raise _manifest_failure("manifest-request-set", "station catalogue") from exc
    try:
        base_ids = _validate_station_ids(base_values)
    except FatalContractError as exc:
        raise _manifest_failure("manifest-request-set", str(exc)) from exc
    required_top = {
        "campaign_started_utc",
        "campaign_ended_utc",
        "requested",
        "stored",
        "rejected",
        "request_url_template",
        "encoding",
        "acceptance_rule",
        "entries",
        "failures",
    }
    if not required_top <= set(manifest):
        raise _manifest_failure("manifest-counts", "missing top-level binding")
    counts = (manifest["requested"], manifest["stored"], manifest["rejected"])
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in counts):
        raise _manifest_failure("manifest-counts", "counts must be integers")
    requested, stored, rejected = counts
    entries = manifest["entries"]
    failures = manifest["failures"]
    if (
        not isinstance(entries, list)
        or not isinstance(failures, list)
        or len(entries) != stored
        or len(failures) != rejected
        or stored + rejected != requested
        or requested != len(base_ids)
    ):
        raise _manifest_failure("manifest-counts", "declared counts disagree")
    template = manifest["request_url_template"]
    if template != f"{SITE_INFO_DETAIL_URL}?ID=<station_id>":
        raise _manifest_failure("manifest-url", "request template")
    if manifest["encoding"] != "EUC-JP":
        raise _manifest_failure("manifest-acceptance-marker", "encoding")
    if manifest["acceptance_rule"] != "HTTP 200 AND response body contains EUC-JP bytes for 世界測地系":
        raise _manifest_failure("manifest-acceptance-marker", "acceptance rule")
    try:
        start = datetime.strptime(str(manifest["campaign_started_utc"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        end = datetime.strptime(str(manifest["campaign_ended_utc"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise _manifest_failure("manifest-retrieved-at", "campaign window") from exc
    if start > end:
        raise _manifest_failure("manifest-retrieved-at", "campaign window order")
    required_entry = {"station_id", "url", "file", "bytes", "sha256", "http_status", "retrieved_at"}
    responses: dict[str, bytes] = {}
    timestamps: dict[str, RetrievedAt] = {}
    files: set[str] = set()
    urls: set[str] = set()
    for value in entries:
        if not isinstance(value, dict):
            raise _manifest_failure("manifest-entry-missing-field", "entry is not an object")
        if not required_entry <= set(value):
            raise _manifest_failure("manifest-entry-missing-field", "accepted entry")
        station_id = _manifest_string(value, "station_id")
        url = _manifest_string(value, "url")
        filename = _manifest_string(value, "file")
        digest = _manifest_string(value, "sha256")
        if station_id in responses:
            raise _manifest_failure("manifest-duplicate-station", station_id)
        if filename in files:
            raise _manifest_failure("manifest-duplicate-file", filename)
        if url in urls:
            raise _manifest_failure("manifest-url", "duplicate URL")
        if url != f"{SITE_INFO_DETAIL_URL}?ID={station_id}":
            raise _manifest_failure("manifest-url", station_id)
        if filename != f"{station_id}.html" or Path(filename).name != filename:
            raise _manifest_failure("manifest-filename", filename)
        if value["http_status"] != 200:
            raise _manifest_failure("manifest-http-status", station_id)
        payload_path = responses_dir / filename
        if payload_path.resolve().parent != responses_dir.resolve():
            raise _manifest_failure("manifest-filename", filename)
        try:
            body = payload_path.read_bytes()
        except OSError as exc:
            raise _manifest_failure("manifest-payload-missing", filename) from exc
        if value["bytes"] != len(body):
            raise _manifest_failure("manifest-byte-count", station_id)
        if hashlib.sha256(body).hexdigest() != digest:
            raise _manifest_failure("manifest-sha256", station_id)
        if _SOURCE_MARKER not in body:
            raise _manifest_failure("manifest-entry-marker-absent", station_id)
        responses[station_id] = body
        timestamps[station_id] = _manifest_instant(value["retrieved_at"], start=start, end=end)
        files.add(filename)
        urls.add(url)
    try:
        actual_files = {item.name for item in responses_dir.iterdir() if item.is_file()}
    except OSError as exc:
        raise _manifest_failure("manifest-payload-missing", str(responses_dir)) from exc
    if actual_files - files:
        raise _manifest_failure("manifest-payload-extra", repr(sorted(actual_files - files)))
    if files - actual_files:
        raise _manifest_failure("manifest-payload-missing", repr(sorted(files - actual_files)))
    for value in failures:
        if not isinstance(value, dict) or not required_entry | {"has_marker"} <= set(value):
            raise _manifest_failure("manifest-rejection", "failure binding")
        station_id = _manifest_string(value, "station_id")
        url = _manifest_string(value, "url")
        filename = _manifest_string(value, "file")
        digest = _manifest_string(value, "sha256")
        if station_id in responses:
            raise _manifest_failure("manifest-duplicate-station", station_id)
        if filename in files:
            raise _manifest_failure("manifest-duplicate-file", filename)
        if url in urls or url != f"{SITE_INFO_DETAIL_URL}?ID={station_id}":
            raise _manifest_failure("manifest-url", station_id)
        if Path(filename).name != filename:
            raise _manifest_failure("manifest-filename", filename)
        if value["http_status"] != 200 or value["has_marker"] is not False:
            raise _manifest_failure("manifest-rejection", station_id)
        rejection_path = manifest_path.parent / filename
        if rejection_path.resolve().parent != manifest_path.parent.resolve():
            raise _manifest_failure("manifest-rejection", filename)
        try:
            body = rejection_path.read_bytes()
        except OSError as exc:
            raise _manifest_failure("manifest-rejection", filename) from exc
        if value["bytes"] != len(body) or hashlib.sha256(body).hexdigest() != digest:
            raise _manifest_failure("manifest-rejection", station_id)
        if _SOURCE_MARKER in body:
            raise _manifest_failure("manifest-rejection-marker-present", station_id)
        responses[station_id] = body
        timestamps[station_id] = _manifest_instant(
            value["retrieved_at"], start=datetime.min.replace(tzinfo=UTC), end=datetime.max.replace(tzinfo=UTC)
        )
        files.add(filename)
        urls.add(url)
    if set(responses) != set(base_ids):
        raise _manifest_failure("manifest-request-set", "manifest stations differ from station catalogue")
    return responses, base_ids, timestamps


def refresh_native_table_from_supplied_capture(
    station_catalogue: Path,
    responses_dir: Path,
    manifest_path: Path,
) -> WithIssues[NativeTable]:
    responses, station_ids, timestamps = _load_supplied_capture(station_catalogue, responses_dir, manifest_path)
    return refresh_native_table(responses, station_ids=station_ids, retrieved_at_by_station=timestamps)


def _write_native_atomic(table: NativeTable, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        table.data.write_parquet(temporary)
        written = read_native_table(temporary)
        pl_testing.assert_frame_equal(written.data, table.data, check_exact=True)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or materialize the jp_mlit catalogue.")
    parser.add_argument("--native", type=Path)
    parser.add_argument("--station-catalogue", type=Path)
    parser.add_argument("--responses-dir", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--native-out", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    native_mode = args.native is not None or args.out is not None
    capture_mode = any(
        value is not None for value in (args.station_catalogue, args.responses_dir, args.manifest, args.native_out)
    )
    if native_mode and capture_mode:
        parser.error("jp_mlit modes cannot mix native-build and supplied-capture arguments")
    if native_mode:
        if args.native is None or args.out is None:
            parser.error("jp_mlit native mode requires both --native and --out")
        from rivretrieve._internal.providers.jp_mlit.origins import STATION_CATALOGUE_ORIGINS

        write_catalogue(
            build_catalogue(
                read_native_table(args.native, expected_sha256=NATIVE_TABLE_SHA256),
                STATION_CATALOGUE_ORIGINS,
            ),
            args.out,
        )
        return 0
    if capture_mode:
        if any(value is None for value in (args.station_catalogue, args.responses_dir, args.manifest, args.native_out)):
            parser.error(
                "jp_mlit supplied-capture mode requires --station-catalogue, --responses-dir, --manifest, and --native-out"
            )
        outcome = refresh_native_table_from_supplied_capture(
            args.station_catalogue,
            args.responses_dir,
            args.manifest,
        )
        _write_native_atomic(outcome.value, args.native_out)
        for issue in outcome.issues:
            print(f"{issue.code}: {issue.message}")
        print(f"jp_mlit native table content SHA-256: {native_table_content_digest(outcome.value)}")
        return 0
    parser.error("jp_mlit requires native-build or supplied-capture mode")


if __name__ == "__main__":
    raise SystemExit(main())

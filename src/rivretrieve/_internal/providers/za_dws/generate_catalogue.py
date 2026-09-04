"""DWS catalogue maintenance : refresh(CatalogueIndexCapture × Map[RiverPdfCapture]) → WithIssues[NativeTable]; build(NativeTable × OriginDeclarations) → GeneratedZaDwsCatalogue."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

import polars as pl
from pypdf import PdfReader

from rivretrieve._internal.acquisition_provenance import verify_provenance_recordings
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
from rivretrieve._internal.providers.za_dws.origins import unsigned_dms_coordinates

PROVIDER_ID = ProviderId("za_dws")
PROVIDER_NAME = "Department of Water and Sanitation — Verified Hydrology (DWS, South Africa)"

CATALOGUE_URL = "https://www.dws.gov.za/hydrology/Verified/HyCatalogue.aspx"
DATA_URL = "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx"
CATALOGUE_BASE = "https://www.dws.gov.za/hydrology/Verified/"

AVAILABILITY_NOTE = (
    "Materialised as availability=unknown; the DWS station catalogue does not "
    "expose which data variables are available per station."
)
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"
DMS_SIGN_CONVENTION = (
    "DWS publishes unsigned DMS magnitudes with no leading sign, hemisphere marker, or "
    "hemisphere note; the build applies a southern negative latitude sign and an eastern "
    "positive longitude sign that the source does not carry."
)

MIN_REFRESH_STATIONS = 2_905

# Regex matching a DWS station row inside a WMA River PDF.
# Format: STATION_CODE  DESCRIPTION  LAT_DMS  LON_DMS  DRAINAGE_REGION  AREA
_STATION_PATTERN = re.compile(
    r"^([A-Z][0-9][A-Z][0-9]{3}(?:[A-Z](?:[0-9]{2})?)?)\s+(.+?)\s+"
    r"(\d{2}:\d{2}:\d{2})\s+(\d{2}:\d{2}:\d{2})\s+"
    r"(?:([A-Z][A-Z0-9]+)\s+)?([0-9]+(?:\.[0-9]+)?)$"
)

_PDF_LINK_PATTERN = re.compile(r'href=["\']([^"\']*_River[^"\']*\.pdf)["\']', re.IGNORECASE)

NATIVE_SOURCE_SCHEMA = pl.Schema(
    {
        "Station": pl.String,
        "Description": pl.String,
        "Latitude (dd:mm:ss)": pl.String,
        "Longitude (dd:mm:ss)": pl.String,
        "Drainage Region": pl.String,
        "Catchment Area km**2": pl.String,
        "WMA source-file identity": pl.String,
    }
)
NATIVE_SCHEMA = pl.Schema({**NATIVE_SOURCE_SCHEMA, "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC")})


class CatalogueIssueCode(StrEnum):
    INDEX_REQUEST_FAILED = "index-request-failed"
    INDEX_HTTP_ERROR = "index-http-error"
    PDF_REQUEST_FAILED = "pdf-request-failed"
    PDF_HTTP_ERROR = "pdf-http-error"
    INVALID_PDF = "invalid-pdf"
    PDF_ROW_PARSE = "pdf-row-parse"
    DUPLICATE_STATION = "duplicate-station"
    INCOMPLETE_PDF_INPUT = "incomplete-pdf-input"
    BELOW_MINIMUM = "below-minimum"


_EXPECTED_BINDINGS: tuple[dict[str, object], ...] = (
    {
        "file": "HyCatalogue.aspx",
        "archived_url": "http://web.archive.org/web/20260311133455id_/https://www.dws.gov.za/hydrology/Verified/HyCatalogue.aspx",
        "origin_url": "https://www.dws.gov.za/hydrology/Verified/HyCatalogue.aspx",
        "wayback_timestamp": "20260311133455",
        "http_status": 200,
        "bytes": 6778,
        "sha256": "6cf0495ce6ef31bba2d0e746cc8c001d91a8ac8b2c4e634b57f9099d5edafc71",
        "retrieved_at": "2026-08-02T18:47:00Z",
    },
    {
        "file": "WMA1_Limpopo-Olifants_River.pdf",
        "archived_url": "http://web.archive.org/web/20251122081546id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA1_Limpopo-Olifants_River.pdf",
        "origin_url": "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA1_Limpopo-Olifants_River.pdf",
        "wayback_timestamp": "20251122081546",
        "http_status": 200,
        "bytes": 977280,
        "sha256": "b6efb89b9f74e0fe9bdca4f2984ce008d77b8f5692fd359a485b9ea4d8ad06a8",
        "retrieved_at": "2026-08-02T18:47:01Z",
    },
    {
        "file": "WMA2_Inkomati-Usuthu_River.pdf",
        "archived_url": "http://web.archive.org/web/20251127140120id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA2_Inkomati-Usuthu_River.pdf",
        "origin_url": "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA2_Inkomati-Usuthu_River.pdf",
        "wayback_timestamp": "20251127140120",
        "http_status": 200,
        "bytes": 449874,
        "sha256": "16186305a3fff3bdda90eaf0889827a773014837bdbb4cb2ab0f0ae1a2a360cf",
        "retrieved_at": "2026-08-02T18:47:02Z",
    },
    {
        "file": "WMA3_Pongola-Mtamvuna_River.pdf",
        "archived_url": "http://web.archive.org/web/20251127181748id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA3_Pongola-Mtamvuna_River.pdf",
        "origin_url": "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA3_Pongola-Mtamvuna_River.pdf",
        "wayback_timestamp": "20251127181748",
        "http_status": 200,
        "bytes": 689780,
        "sha256": "b9f0e0445484c980b708ff78c7a1cc8803a7d10f4d73c33925d5cae184611c8c",
        "retrieved_at": "2026-08-02T18:47:03Z",
    },
    {
        "file": "WMA4_Vaal-Orange_River.pdf",
        "archived_url": "http://web.archive.org/web/20251126040946id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA4_Vaal-Orange_River.pdf",
        "origin_url": "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA4_Vaal-Orange_River.pdf",
        "wayback_timestamp": "20251126040946",
        "http_status": 200,
        "bytes": 1179466,
        "sha256": "dc502341aaf4928def221e32dc9543fd5a9f982aee9df7de4950e95805cf5bc3",
        "retrieved_at": "2026-08-02T18:47:04Z",
    },
    {
        "file": "WMA5_Mzimvubu-Tsitsikamma_River.pdf",
        "archived_url": "http://web.archive.org/web/20251127142153id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA5_Mzimvubu-Tsitsikamma_River.pdf",
        "origin_url": "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA5_Mzimvubu-Tsitsikamma_River.pdf",
        "wayback_timestamp": "20251127142153",
        "http_status": 200,
        "bytes": 671281,
        "sha256": "0d76cedcfdafe2ce9dc8e93eef909e288f6826d7ab729a4856b1cb3c6e0fdde0",
        "retrieved_at": "2026-08-02T18:47:05Z",
    },
    {
        "file": "WMA6_Breede-Olifants_River.pdf",
        "archived_url": "http://web.archive.org/web/20251121090856id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA6_Breede-Olifants_River.pdf",
        "origin_url": "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA6_Breede-Olifants_River.pdf",
        "wayback_timestamp": "20251121090856",
        "http_status": 200,
        "bytes": 930945,
        "sha256": "6fb1d753b22bb4fbe038913249d0c2c8b58a619df35754918061c52163acd91e",
        "retrieved_at": "2026-08-02T18:47:06Z",
    },
    {
        "file": "WMA7_Eswatini_River.pdf",
        "archived_url": "http://web.archive.org/web/20251121161554id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA7_Eswatini_River.pdf",
        "origin_url": "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA7_Eswatini_River.pdf",
        "wayback_timestamp": "20251121161554",
        "http_status": 200,
        "bytes": 192256,
        "sha256": "f820f9002cdba9a0f44b1ac98b1d160b2755dc0ddb27713bac6c435d3c8a7e86",
        "retrieved_at": "2026-08-02T18:47:07Z",
    },
    {
        "file": "WMA8_Lesotho_River.pdf",
        "archived_url": "http://web.archive.org/web/20251121113702id_/https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA8_Lesotho_River.pdf",
        "origin_url": "https://www.dws.gov.za/hydrology/Verified/dwafapp2_wma/WMA8_Lesotho_River.pdf",
        "wayback_timestamp": "20251121113702",
        "http_status": 200,
        "bytes": 214048,
        "sha256": "9511f46b79d172a2e2540d90bb1679b93670ce75e9b0dc8660f1fde78277ee26",
        "retrieved_at": "2026-08-02T18:47:09Z",
    },
)
EXPECTED_SOURCE_BINDINGS = {str(entry["file"]): entry for entry in _EXPECTED_BINDINGS}
EXPECTED_PDF_FILENAMES = tuple(EXPECTED_SOURCE_BINDINGS)[1:]

_TIMEZONE_NOTE = (
    "Daily timestamps are date-only (YYYYMMDD), interpreted as UTC midnight (T00:00:00Z). "
    "Point/instantaneous timestamps are SAST (Africa/Johannesburg, UTC+2, no DST) converted to UTC."
)


@dataclass(frozen=True)
class GeneratedZaDwsCatalogue:
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
    value_column: str


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        product_id="discharge_daily_mean",
        observed_property="discharge",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        value_column="D_AVG_FR",
    ),
    ProductDefinition(
        product_id="discharge_instantaneous",
        observed_property="discharge",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m3/s",
        value_column="COR_FLOW",
    ),
    ProductDefinition(
        product_id="stage_instantaneous",
        observed_property="stage",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m",
        value_column="COR_LEVEL",
    ),
)


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
) -> GeneratedZaDwsCatalogue:
    if native_table.data.schema != NATIVE_SCHEMA:
        raise FatalContractError("za_dws native table does not have the exact required schema")
    if native_table.data.is_empty():
        raise FatalContractError("za_dws native table must not be empty")
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("za_dws native table has no valid retrieved_at values")
    catalogue_date = maximum_retrieved_at.date()
    station_products = build_station_products(
        station_ids=stations["station_id"].to_list(), catalogue_date=catalogue_date
    )
    provider_info = build_provider_info(catalogue_date)
    _validate(provider_info, products, stations, station_products)
    return GeneratedZaDwsCatalogue(
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
            "native_id": d.value_column,
        }
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(native_table: NativeTable) -> StationCatalog:
    rows: list[dict[str, object]] = []
    for native_row in native_table.data.iter_rows(named=True):
        station_id = native_row["Station"]
        latitude_dms = native_row["Latitude (dd:mm:ss)"]
        longitude_dms = native_row["Longitude (dd:mm:ss)"]
        if not isinstance(station_id, str):
            raise FatalContractError("za_dws native table contains a non-string Station")
        if not isinstance(latitude_dms, str) or not isinstance(longitude_dms, str):
            raise FatalContractError(f"za_dws station {station_id} has invalid DMS coordinates")
        latitude, longitude = convert_unsigned_dms_coordinates(latitude_dms, longitude_dms, station_id=station_id)
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
    *,
    station_ids: list[object],
    catalogue_date: date,
) -> StationProductCatalog:
    rows = []
    for station_id in station_ids:
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        for d in PRODUCT_DEFINITIONS:
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
                    "availability": "unknown",
                    "availability_reason": "DWS station catalogue does not expose per-variable availability",
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
            "true: per (station, product) window requests; "
            "Point requests shared between discharge_instantaneous and stage_instantaneous "
            "for the same station/window; partial failures reported as recoverable issues"
        ),
        "catalogue_version": catalogue_date.isoformat(),
        "license": None,
        "citation": None,
    }


def write_catalogue(catalogue: GeneratedZaDwsCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as f:
        json.dump(catalogue.provider_info, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")
    (output_path / "provenance.json").write_text(
        __import__("rivretrieve._internal.providers.za_dws.origins", fromlist=["build_acquisition_provenance"])
        .build_acquisition_provenance()
        .model_dump_json()
        + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Live station fetchers (maintainer-only, PDF scraping)
# ---------------------------------------------------------------------------


def _issue(code: CatalogueIssueCode, message: str, details: dict[str, object]) -> Issue:
    return Issue(severity="error", code=code.value, message=message, details=details, provider_id=PROVIDER_ID)


def _empty_native_table() -> NativeTable:
    return NativeTable(pl.DataFrame(schema=NATIVE_SCHEMA))


def _failure(code: CatalogueIssueCode, message: str, details: dict[str, object]) -> WithIssues[NativeTable]:
    return WithIssues(value=_empty_native_table(), issues=(_issue(code, message, details),))


def _parse_pdf_native_rows(pdf_bytes: bytes, filename: str) -> WithIssues[list[dict[str, object]]]:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        return WithIssues(
            value=[],
            issues=(
                _issue(
                    CatalogueIssueCode.INVALID_PDF,
                    f"za_dws: invalid PDF bytes for {filename}",
                    {"filename": filename, "error": str(exc)},
                ),
            ),
        )
    rows: list[dict[str, object]] = []
    issues: list[Issue] = []
    for source_line in text.splitlines():
        line = source_line.strip()
        match = _STATION_PATTERN.fullmatch(line)
        if match is not None:
            station, description, latitude, longitude, region, area = match.groups()
            rows.append(
                {
                    "Station": station,
                    "Description": description,
                    "Latitude (dd:mm:ss)": latitude,
                    "Longitude (dd:mm:ss)": longitude,
                    "Drainage Region": region,
                    "Catchment Area km**2": area,
                    "WMA source-file identity": filename,
                }
            )
        elif len(re.findall(r"\b\d{2}:\d{2}:\d{2}\b", line)) == 2:
            issues.append(
                _issue(
                    CatalogueIssueCode.PDF_ROW_PARSE,
                    f"za_dws: coordinate-bearing station row did not match in {filename}: {line}",
                    {"filename": filename, "line": line},
                )
            )
    return WithIssues(value=rows, issues=tuple(issues))


def refresh_native_table_from_captures(
    index_bytes: bytes,
    pdf_captures: Mapping[str, tuple[bytes, RetrievedAt]],
) -> WithIssues[NativeTable]:
    try:
        index_text = index_bytes.decode("utf-8")
    except UnicodeDecodeError:
        index_text = index_bytes.decode("utf-8", errors="replace")
    filenames = tuple(Path(link).name for link in _PDF_LINK_PATTERN.findall(index_text))
    expected = set(EXPECTED_PDF_FILENAMES)
    if set(filenames) != expected or set(pdf_captures) != expected or len(filenames) != len(expected):
        return _failure(
            CatalogueIssueCode.INCOMPLETE_PDF_INPUT,
            "za_dws: complete eight-PDF input is required",
            {
                "expected": sorted(expected),
                "index": sorted(filenames),
                "captures": sorted(pdf_captures),
            },
        )
    frames: list[pl.DataFrame] = []
    issues: list[Issue] = []
    for filename in EXPECTED_PDF_FILENAMES:
        payload, retrieved_at = pdf_captures[filename]
        parsed = _parse_pdf_native_rows(payload, filename)
        issues.extend(parsed.issues)
        if parsed.issues:
            continue
        source = pl.DataFrame(parsed.value, schema=NATIVE_SOURCE_SCHEMA)
        frames.append(stamp_native_table(source, retrieved_at).data)
    if issues:
        return WithIssues(value=_empty_native_table(), issues=tuple(issues))
    data = pl.concat(frames).sort("Station")
    duplicates = data.group_by("Station").len().filter(pl.col("len") > 1)
    if duplicates.height:
        station = duplicates.sort("Station")["Station"][0]
        return _failure(
            CatalogueIssueCode.DUPLICATE_STATION,
            f"za_dws: duplicate Station {station}",
            {"station": station},
        )
    if data.height < MIN_REFRESH_STATIONS:
        return _failure(
            CatalogueIssueCode.BELOW_MINIMUM,
            f"za_dws: refresh returned {data.height} stations; minimum is {MIN_REFRESH_STATIONS}",
            {"actual": data.height, "minimum": MIN_REFRESH_STATIONS},
        )
    return WithIssues(value=NativeTable(data), issues=())


def refresh_native_table_from_fixture(path: Path | str, *, retrieved_at: RetrievedAt) -> WithIssues[NativeTable]:
    raw = _read_fixture_json(Path(path))
    source = pl.DataFrame(raw, schema=NATIVE_SOURCE_SCHEMA).sort("Station")
    return WithIssues(value=stamp_native_table(source, retrieved_at), issues=())


def _request_bytes(url: str) -> tuple[bytes, int]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read(), response.status
    except urllib.error.HTTPError as exc:
        return exc.read(), exc.code


def refresh_native_table_from_live(*, retrieved_at: RetrievedAt) -> WithIssues[NativeTable]:
    try:
        index_bytes, status = _request_bytes(CATALOGUE_URL)
    except Exception as exc:
        return _failure(
            CatalogueIssueCode.INDEX_REQUEST_FAILED,
            f"za_dws: index request failed for {CATALOGUE_URL}",
            {"url": CATALOGUE_URL, "error": str(exc)},
        )
    if status != 200:
        return _failure(
            CatalogueIssueCode.INDEX_HTTP_ERROR,
            f"za_dws: index HTTP {status} for {CATALOGUE_URL}",
            {"url": CATALOGUE_URL, "status": status},
        )
    links = _PDF_LINK_PATTERN.findall(index_bytes.decode("utf-8", errors="replace"))
    captures: dict[str, tuple[bytes, RetrievedAt]] = {}
    for link in links:
        filename = Path(link).name
        if filename not in EXPECTED_PDF_FILENAMES:
            continue
        url = link if link.startswith("http") else CATALOGUE_BASE + link.lstrip("/")
        try:
            payload, status = _request_bytes(url)
        except Exception as exc:
            return _failure(
                CatalogueIssueCode.PDF_REQUEST_FAILED,
                f"za_dws: PDF request failed for {url}",
                {"url": url, "error": str(exc)},
            )
        if status != 200:
            return _failure(
                CatalogueIssueCode.PDF_HTTP_ERROR,
                f"za_dws: PDF HTTP {status} for {url}",
                {"url": url, "status": status},
            )
        captures[filename] = (payload, retrieved_at)
    return refresh_native_table_from_captures(index_bytes, captures)


def _parse_manifest_retrieved_at(value: object, filename: str) -> RetrievedAt:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise FatalContractError(f"manifest-retrieved-at: {filename}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return RetrievedAt(parsed)
    except (ValueError, FatalContractError) as exc:
        raise FatalContractError(f"manifest-retrieved-at: {filename}") from exc


def _verified_supplied_captures(
    archive_dir: Path, manifest_path: Path
) -> tuple[bytes, dict[str, tuple[bytes, RetrievedAt]]]:
    if not manifest_path.is_file():
        raise FatalContractError(f"manifest-missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FatalContractError("manifest-not-list") from exc
    if not isinstance(manifest, list):
        raise FatalContractError("manifest-not-list")
    if len(manifest) != 9:
        raise FatalContractError("manifest-entry-count")
    required = tuple(next(iter(EXPECTED_SOURCE_BINDINGS.values())))
    actual_files: set[str] = set()
    payloads: dict[str, bytes] = {}
    captures: dict[str, tuple[bytes, RetrievedAt]] = {}
    for position, raw_entry in enumerate(manifest):
        if not isinstance(raw_entry, dict):
            raise FatalContractError(f"manifest-binding-type: entry {position}")
        entry = cast(dict[str, object], raw_entry)
        missing = [field for field in required if field not in entry]
        if missing:
            raise FatalContractError(f"manifest-entry-missing-field: {missing[0]}")
        for field in required:
            expected_type = type(_EXPECTED_BINDINGS[position][field])
            if type(entry[field]) is not expected_type:
                raise FatalContractError(f"manifest-binding-type: {field}")
            if isinstance(entry[field], str) and not entry[field]:
                raise FatalContractError(f"manifest-binding-blank: {field}")
        expected = _EXPECTED_BINDINGS[position]
        filename = str(entry["file"])
        checks = (
            ("file", "manifest-filename"),
            ("archived_url", "manifest-archived-url"),
            ("origin_url", "manifest-origin-url"),
            ("wayback_timestamp", "manifest-wayback-timestamp"),
            ("http_status", "manifest-http-status"),
        )
        for field, token in checks:
            if entry[field] != expected[field]:
                raise FatalContractError(f"{token}: {filename}")
        if entry["retrieved_at"] != expected["retrieved_at"]:
            raise FatalContractError(f"manifest-retrieved-at: {filename}")
        retrieved_at = _parse_manifest_retrieved_at(entry["retrieved_at"], filename)
        path = archive_dir / filename
        if not path.is_file():
            raise FatalContractError(f"manifest-payload-missing: {filename}")
        payload = path.read_bytes()
        if len(payload) != entry["bytes"]:
            raise FatalContractError(f"manifest-byte-count: {filename}")
        if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
            raise FatalContractError(f"manifest-sha256: {filename}")
        actual_files.add(filename)
        payloads[filename] = payload
        if filename.endswith(".pdf"):
            captures[filename] = (payload, retrieved_at)
    extras = {path.name for path in archive_dir.iterdir() if path.is_file()} - actual_files
    if extras:
        raise FatalContractError(f"manifest-payload-extra: {sorted(extras)[0]}")
    return payloads["HyCatalogue.aspx"], captures


def refresh_native_table_from_supplied_archive(
    archive_dir: Path | str, manifest_path: Path | str
) -> WithIssues[NativeTable]:
    index, captures = _verified_supplied_captures(Path(archive_dir), Path(manifest_path))
    return refresh_native_table_from_captures(index, captures)


def native_table_content_sha256(table: NativeTable) -> str:
    if table.data.schema != NATIVE_SCHEMA:
        raise FatalContractError("za_dws native table does not have the exact required schema")
    rows: list[list[object]] = []
    for row in table.data.iter_rows():
        rows.append(
            [
                value.isoformat(timespec="microseconds").replace("+00:00", "Z")
                if isinstance(value, datetime)
                else value
                for value in row
            ]
        )
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _raise_on_error_issues(outcome: WithIssues[NativeTable]) -> NativeTable:
    errors = tuple(issue for issue in outcome.issues if issue.severity == "error")
    if errors:
        raise FatalContractError(issues=errors)
    return outcome.value


# ---------------------------------------------------------------------------
# Fixture reader
# ---------------------------------------------------------------------------


def _read_fixture_json(path: Path) -> list[dict[str, object]]:
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except OSError as exc:
        raise FatalContractError(f"Unable to read za_dws fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"za_dws fixture is not valid JSON: {path}") from exc
    if isinstance(value, list):
        return value  # type: ignore[return-value]
    raise FatalContractError("za_dws fixture must be a JSON array")


# ---------------------------------------------------------------------------
# Catalogue validation
# ---------------------------------------------------------------------------


def _validate(
    provider_info: dict[str, object],
    products: ProductCatalog,
    stations: StationCatalog,
    station_products: StationProductCatalog,
) -> None:
    pi_df = pl.DataFrame([provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)
    validate_catalogue(pi_df, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    packaged_catalogue_artifact_from_components(
        provider_info,
        products,
        stations,
        station_products,
        acquisition_provenance=__import__(
            "rivretrieve._internal.providers.za_dws.origins", fromlist=["build_acquisition_provenance"]
        ).build_acquisition_provenance(),
        on_issue="raise",
    )


# ---------------------------------------------------------------------------
# Coordinate / text helpers
# ---------------------------------------------------------------------------


def convert_unsigned_dms_coordinates(
    latitude_dms: str,
    longitude_dms: str,
    *,
    station_id: str,
) -> tuple[float, float]:
    """Transform a pair of unsigned native DMS magnitudes into signed decimal coordinates."""

    # DWS publishes unsigned DMS magnitudes with no leading sign, hemisphere marker, or
    # hemisphere note. This single representation boundary applies a southern negative
    # latitude sign and an eastern positive longitude sign that the source does not carry.
    try:
        return unsigned_dms_coordinates(latitude_dms, longitude_dms)
    except ValueError as exc:
        raise FatalContractError(f"za_dws station {station_id} has invalid DMS coordinates") from exc


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh or build the packaged za_dws catalogue.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to a stations JSON fixture.")
    source.add_argument("--live", action="store_true", help="Scrape the live DWS station PDFs.")
    source.add_argument("--archive-dir", type=Path, help="Directory containing supplied capture payloads.")
    source.add_argument("--native", type=Path, help="Path to the committed native Parquet table.")
    parser.add_argument("--manifest", type=Path, help="Manifest for supplied capture payloads.")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--native-out", type=Path, help="Output path for a refreshed native table.")
    destination.add_argument("--out", type=Path, help="Output directory for canonical artifacts.")
    parser.add_argument("--retrieved-at", type=lambda value: RetrievedAt(datetime.fromisoformat(value)))
    args = parser.parse_args(argv)

    if args.archive_dir is None and args.manifest is not None:
        parser.error("--manifest requires --archive-dir")
    if args.archive_dir is not None and args.manifest is None:
        parser.error("--archive-dir requires --manifest")

    if args.native_out is not None:
        if args.native is not None:
            parser.error("--native cannot be combined with --native-out")
        if args.archive_dir is not None and args.retrieved_at is not None:
            parser.error("--retrieved-at is not valid with supplied-archive refresh mode")
        if (args.fixture is not None or args.live) and args.retrieved_at is None:
            parser.error("--retrieved-at is required with fixture or live refresh mode")
        if args.archive_dir is not None:
            outcome = refresh_native_table_from_supplied_archive(args.archive_dir, args.manifest)
        elif args.live:
            outcome = refresh_native_table_from_live(retrieved_at=args.retrieved_at)
        else:
            outcome = refresh_native_table_from_fixture(args.fixture, retrieved_at=args.retrieved_at)
        table = _raise_on_error_issues(outcome)
        write_native_table(table, args.native_out)
        digest = native_table_content_sha256(read_native_table(args.native_out))
        print(f"za_dws native table canonical SHA-256: {digest}")
        return 0

    if args.native is None:
        parser.error("--out requires --native")
    if args.retrieved_at is not None:
        parser.error("--retrieved-at is only valid with fixture or live refresh mode")
    from rivretrieve._internal.providers.za_dws.origins import (
        NATIVE_TABLE_BYTE_SIZE,
        NATIVE_TABLE_SHA256,
        STATION_CATALOGUE_ORIGINS,
        build_acquisition_provenance,
    )

    verify_provenance_recordings(build_acquisition_provenance(), Path(__file__).resolve().parents[5])
    native_table = read_native_table(
        args.native,
        expected_sha256=NATIVE_TABLE_SHA256,
        expected_byte_size=NATIVE_TABLE_BYTE_SIZE,
    )
    write_catalogue(build_catalogue(native_table, STATION_CATALOGUE_ORIGINS), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

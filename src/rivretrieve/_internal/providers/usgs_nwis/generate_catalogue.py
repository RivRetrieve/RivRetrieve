"""Build modern station discovery with independent legacy sitefile enrichment."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import urllib.request
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl

from rivretrieve._internal.acquisition_provenance import (
    AcquisitionProvenance,
    CatalogueBuildInputs,
    verify_provenance_recordings,
)
from rivretrieve._internal.catalogue_origins import Field, OriginDeclarations, enforce_catalogue_origins
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
    ProductCatalog,
    StationCatalog,
    StationProductCatalog,
    validate_catalogue,
)
from rivretrieve._internal.catalogues.source_series import SourceDescriptions
from rivretrieve._internal.engine import WithIssues
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId

PROVIDER_ID = ProviderId("usgs_nwis")
PROVIDER_NAME = "U.S. Geological Survey National Water Information System (USGS NWIS)"
METADATA_BASE_URL = "https://waterservices.usgs.gov/nwis/site/"
SERIES_CATALOGUE_URL = (
    METADATA_BASE_URL + "?format=rdb&parameterCd=00060,00065&stateCd={state_cd}&seriesCatalogOutput=true"
)
EXPANDED_SITE_URL = METADATA_BASE_URL + "?format=rdb&parameterCd=00060,00065&stateCd={state_cd}&siteOutput=expanded"
# USGS site service requires a geographic filter; nationwide queries return HTTP 400.
# We iterate over the 50 state USPS codes plus DC.
_US_STATE_CODES = [
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
]

SERIES_HEADER = (
    "agency_cd",
    "site_no",
    "station_nm",
    "site_tp_cd",
    "dec_lat_va",
    "dec_long_va",
    "coord_acy_cd",
    "dec_coord_datum_cd",
    "alt_va",
    "alt_acy_va",
    "alt_datum_cd",
    "huc_cd",
    "data_type_cd",
    "parm_cd",
    "stat_cd",
    "ts_id",
    "loc_web_ds",
    "medium_grp_cd",
    "parm_grp_cd",
    "srs_id",
    "access_cd",
    "begin_date",
    "end_date",
    "count_nu",
)
SERIES_FORMAT = (
    "5s",
    "15s",
    "50s",
    "7s",
    "16s",
    "16s",
    "1s",
    "10s",
    "8s",
    "3s",
    "10s",
    "16s",
    "2s",
    "5s",
    "5s",
    "5n",
    "30s",
    "3s",
    "3s",
    "5n",
    "4n",
    "20d",
    "20d",
    "5n",
)
EXPANDED_HEADER = (
    "agency_cd",
    "site_no",
    "station_nm",
    "site_tp_cd",
    "lat_va",
    "long_va",
    "dec_lat_va",
    "dec_long_va",
    "coord_meth_cd",
    "coord_acy_cd",
    "coord_datum_cd",
    "dec_coord_datum_cd",
    "district_cd",
    "state_cd",
    "county_cd",
    "country_cd",
    "land_net_ds",
    "map_nm",
    "map_scale_fc",
    "alt_va",
    "alt_meth_cd",
    "alt_acy_va",
    "alt_datum_cd",
    "huc_cd",
    "basin_cd",
    "topo_cd",
    "instruments_cd",
    "construction_dt",
    "inventory_dt",
    "drain_area_va",
    "contrib_drain_area_va",
    "tz_cd",
    "local_time_fg",
    "reliability_cd",
    "gw_file_cd",
    "nat_aqfr_cd",
    "aqfr_cd",
    "aqfr_type_cd",
    "well_depth_va",
    "hole_depth_va",
    "depth_src_cd",
    "project_no",
)
EXPANDED_FORMAT = (
    "5s",
    "15s",
    "50s",
    "7s",
    "16s",
    "16s",
    "16s",
    "16s",
    "1s",
    "1s",
    "10s",
    "10s",
    "3s",
    "2s",
    "3s",
    "2s",
    "23s",
    "20s",
    "7s",
    "8s",
    "1s",
    "3s",
    "10s",
    "16s",
    "2s",
    "1s",
    "30s",
    "8s",
    "8s",
    "8s",
    "8s",
    "6s",
    "1s",
    "1s",
    "30s",
    "10s",
    "8s",
    "1s",
    "8s",
    "8s",
    "1s",
    "12s",
)
SHARED_STATION_FIELDS = SERIES_HEADER[:12]
SERIES_ONLY_FIELDS = SERIES_HEADER[12:]
NATIVE_SCHEMA = pl.Schema(
    {
        **dict.fromkeys(EXPANDED_HEADER, pl.String),
        **{name: pl.List(pl.String) for name in SERIES_ONLY_FIELDS},
        "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    }
)


def native_table_content_sha256(table: NativeTable) -> str:
    """Return the SHA-256 of the compact canonical JSON table in schema and row order."""
    if table.data.schema != NATIVE_SCHEMA:
        raise FatalContractError("USGS native table does not have the exact required schema")

    digest = hashlib.sha256()
    digest.update(b"[")
    for index, row in enumerate(table.data.iter_rows()):
        if index:
            digest.update(b",")
        values = [
            value.isoformat(timespec="microseconds").replace("+00:00", "Z") if isinstance(value, datetime) else value
            for value in row
        ]
        digest.update(json.dumps(values, separators=(",", ":"), ensure_ascii=False).encode())
    digest.update(b"]")
    return digest.hexdigest()


@dataclass(frozen=True)
class GeneratedUsgsNwisCatalogue:
    provider_info: dict[str, object]
    products: ProductCatalog
    stations: StationCatalog
    station_products: StationProductCatalog
    source_native: pl.DataFrame
    retained_series_ids: tuple[str, ...] = ()
    source_descriptions: SourceDescriptions | None = None


@dataclass(frozen=True)
class ProductDefinition:
    product_id: str
    observed_property: str
    frequency: str
    statistic: str
    period_type: str
    period_anchor: str
    canonical_unit: str
    param_code: str
    stat_code: str | None
    returned_data_type_cd: str
    returned_stat_cd: str

    @property
    def series_key(self) -> tuple[str, str, str]:
        return (self.returned_data_type_cd, self.param_code, self.returned_stat_cd)


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        product_id="discharge_daily_mean",
        observed_property="discharge",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="unknown",
        canonical_unit="m3/s",
        param_code="00060",
        stat_code="00003",
        returned_data_type_cd="dv",
        returned_stat_cd="00003",
    ),
    ProductDefinition(
        product_id="discharge_instantaneous",
        observed_property="discharge",
        frequency="unknown",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="unknown",
        canonical_unit="m3/s",
        param_code="00060",
        stat_code=None,
        returned_data_type_cd="uv",
        returned_stat_cd="",
    ),
    ProductDefinition(
        product_id="stage_daily_mean",
        observed_property="stage",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="unknown",
        canonical_unit="m",
        param_code="00065",
        stat_code="00003",
        returned_data_type_cd="dv",
        returned_stat_cd="00003",
    ),
    ProductDefinition(
        product_id="stage_daily_max",
        observed_property="stage",
        frequency="daily",
        statistic="max",
        period_type="interval",
        period_anchor="unknown",
        canonical_unit="m",
        param_code="00065",
        stat_code="00001",
        returned_data_type_cd="dv",
        returned_stat_cd="00001",
    ),
    ProductDefinition(
        product_id="stage_daily_min",
        observed_property="stage",
        frequency="daily",
        statistic="min",
        period_type="interval",
        period_anchor="unknown",
        canonical_unit="m",
        param_code="00065",
        stat_code="00002",
        returned_data_type_cd="dv",
        returned_stat_cd="00002",
    ),
    ProductDefinition(
        product_id="stage_instantaneous",
        observed_property="stage",
        frequency="unknown",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="unknown",
        canonical_unit="m",
        param_code="00065",
        stat_code=None,
        returned_data_type_cd="uv",
        returned_stat_cd="",
    ),
)


def _iter_strict_rdb(
    content: str,
    expected_header: tuple[str, ...],
    expected_format: tuple[str, ...],
    *,
    source_name: str,
) -> Iterator[dict[str, str]]:
    lines = (line for line in content.splitlines() if not line.startswith("#"))
    try:
        header_line = next(lines)
    except StopIteration as exc:
        raise FatalContractError(f"{source_name} RDB is empty") from exc
    header = tuple(header_line.split("\t"))
    if header != expected_header:
        raise FatalContractError(f"{source_name} RDB header does not match the required ordered schema")
    try:
        format_line = next(lines)
    except StopIteration as exc:
        raise FatalContractError(f"{source_name} RDB is missing its format row") from exc
    format_row = tuple(format_line.split("\t"))
    if format_row != expected_format:
        raise FatalContractError(f"{source_name} RDB format row does not match the required ordered schema")

    row_count = 0
    for line_number, line in enumerate(lines, start=3):
        fields = tuple(line.split("\t"))
        if fields in (expected_header, expected_format):
            raise FatalContractError(
                f"{source_name} RDB contains a repeated header or format row at line {line_number}"
            )
        if len(fields) != len(expected_header):
            raise FatalContractError(
                f"{source_name} RDB row {line_number} has {len(fields)} fields; expected {len(expected_header)}"
            )
        row_count += 1
        yield dict(zip(expected_header, fields, strict=True))
    if row_count == 0:
        raise FatalContractError(f"{source_name} RDB data is empty")


def parse_series_rdb(content: str) -> list[dict[str, str]]:
    return list(_iter_strict_rdb(content, SERIES_HEADER, SERIES_FORMAT, source_name="series catalogue"))


def parse_expanded_rdb(content: str) -> list[dict[str, str]]:
    return list(_iter_strict_rdb(content, EXPANDED_HEADER, EXPANDED_FORMAT, source_name="expanded site"))


def _validated_source_row(
    item: object,
    expected_header: tuple[str, ...],
    *,
    row_kind: str,
) -> dict[str, str]:
    if not isinstance(item, dict):
        raise FatalContractError(f"USGS {row_kind} row must be an object")
    row = cast("dict[object, object]", item)
    if "site_no" not in row:
        raise FatalContractError(f"USGS {row_kind} row has absent site_no")
    if tuple(row) != expected_header or any(not isinstance(value, str) for value in row.values()):
        raise FatalContractError(f"USGS {row_kind} row must have the exact ordered all-string source schema")
    return cast("dict[str, str]", row)


def _required_site_no(row: dict[str, str], *, row_kind: str) -> str:
    site_no = row["site_no"]
    if not site_no or site_no.isspace():
        raise FatalContractError(f"USGS {row_kind} row has absent or blank site_no")
    return site_no


def refresh_native_table(
    series_rows: Iterable[object],
    expanded_rows: Iterable[object],
    *,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    expanded_by_site: dict[tuple[str, str], list[dict[str, str]]] = {}
    for item in expanded_rows:
        row = _validated_source_row(item, EXPANDED_HEADER, row_kind="expanded")
        site_no = (_required_site_no(row, row_kind="expanded"), row["agency_cd"])
        expanded_by_site.setdefault(site_no, []).append(row)
    if not expanded_by_site:
        raise FatalContractError("USGS expanded input is empty")

    series_records: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    expanded_shared = {
        tuple(row[name] for name in SHARED_STATION_FIELDS) for rows in expanded_by_site.values() for row in rows
    }
    for item in series_rows:
        row = _validated_source_row(item, SERIES_HEADER, row_kind="series")
        site_no = (_required_site_no(row, row_kind="series"), row["agency_cd"])
        if site_no not in expanded_by_site:
            raise FatalContractError("USGS legacy series identities have no expanded site record")
        shared = tuple(row[name] for name in SHARED_STATION_FIELDS)
        if shared not in expanded_shared:
            differing = sorted(
                {
                    name
                    for expanded in expanded_by_site[site_no]
                    for name in SHARED_STATION_FIELDS
                    if expanded[name] != row[name]
                }
            )
            raise FatalContractError(f"USGS passes conflict on {', '.join(differing)} for site_no {site_no!r}")
        series_records.setdefault(shared, []).append(tuple(row[name] for name in SERIES_ONLY_FIELDS))

    native_rows: list[dict[str, object]] = []
    for site_no in sorted(expanded_by_site):
        for expanded in expanded_by_site[site_no]:
            shared = tuple(expanded[name] for name in SHARED_STATION_FIELDS)
            records = sorted(series_records.get(shared, []))
            native_row: dict[str, object] = dict(expanded)
            native_row.update(
                {name: [record[index] for record in records] for index, name in enumerate(SERIES_ONLY_FIELDS)}
            )
            native_rows.append(native_row)

    source = pl.DataFrame(native_rows, schema=pl.Schema(dict(list(NATIVE_SCHEMA.items())[:-1])))
    native = stamp_native_table(source, retrieved_at)
    if native.data.schema != NATIVE_SCHEMA:
        raise FatalContractError("USGS native table does not have the exact required schema")
    return WithIssues(value=native, issues=())


def refresh_native_table_from_fixtures(
    series_fixture_path: Path | str,
    expanded_fixture_path: Path | str,
    *,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    return refresh_native_table(
        _read_fixture_json(Path(series_fixture_path)),
        _read_fixture_json(Path(expanded_fixture_path)),
        retrieved_at=retrieved_at,
    )


def _read_rdb_file(
    path: Path,
    expected_header: tuple[str, ...],
    expected_format: tuple[str, ...],
    *,
    source_name: str,
) -> Iterator[dict[str, str]]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FatalContractError(f"Unable to read USGS RDB file: {path}") from exc
    yield from _iter_strict_rdb(content, expected_header, expected_format, source_name=source_name)


def refresh_native_table_from_rdb_directory(
    rdb_directory: Path | str,
    *,
    retrieved_at: RetrievedAt,
) -> WithIssues[NativeTable]:
    directory = Path(rdb_directory)
    series_rows = (
        row
        for state_cd in _US_STATE_CODES
        for row in _read_rdb_file(
            directory / f"{state_cd}_series.rdb",
            SERIES_HEADER,
            SERIES_FORMAT,
            source_name=f"{state_cd} series catalogue",
        )
    )
    expanded_rows = (
        row
        for state_cd in _US_STATE_CODES
        for row in _read_rdb_file(
            directory / f"{state_cd}_expanded.rdb",
            EXPANDED_HEADER,
            EXPANDED_FORMAT,
            source_name=f"{state_cd} expanded site",
        )
    )
    return refresh_native_table(
        series_rows,
        expanded_rows,
        retrieved_at=retrieved_at,
    )


def _read_rdb_url(url: str, *, source_name: str, series: bool) -> list[dict[str, str]]:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            if response.status < 200 or response.status >= 300:
                raise FatalContractError(f"USGS site service request failed with HTTP {response.status}: {url}")
            content = response.read().decode("utf-8")
    except OSError as exc:
        raise FatalContractError(f"USGS site service request failed: {url}") from exc
    if series:
        return parse_series_rdb(content)
    return parse_expanded_rdb(content)


def read_live_native_rows() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    series_rows: list[dict[str, str]] = []
    expanded_rows: list[dict[str, str]] = []
    for state_cd in _US_STATE_CODES:
        series_rows.extend(
            _read_rdb_url(
                SERIES_CATALOGUE_URL.format(state_cd=state_cd),
                source_name=f"{state_cd} series catalogue",
                series=True,
            )
        )
        expanded_rows.extend(
            _read_rdb_url(
                EXPANDED_SITE_URL.format(state_cd=state_cd),
                source_name=f"{state_cd} expanded site",
                series=False,
            )
        )
    return series_rows, expanded_rows


def refresh_native_table_from_live(*, retrieved_at: RetrievedAt) -> WithIssues[NativeTable]:
    series_rows, expanded_rows = read_live_native_rows()
    return refresh_native_table(
        series_rows,
        expanded_rows,
        retrieved_at=retrieved_at,
    )


def read_modern_metadata(directory: Path):
    """Verify exact publisher bytes and every link in both saved metadata chains."""
    features = []
    receipts = []
    for parameter in ("00060", "00065"):
        completion = json.loads((directory / f"metadata-{parameter}-completion.json").read_text())
        if completion["status"] != "complete" or completion["active_filter"] is not None or completion["sorting"]:
            raise FatalContractError("Modern metadata must include complete unsorted discontinued records")
        expected = f"https://api.waterdata.usgs.gov/ogcapi/v1/collections/time-series-metadata/items?f=json&parameter_code={parameter}&limit=10000"
        count = 0
        for index in range(completion["pages"]):
            stem = f"metadata-{parameter}-{index:04d}"
            receipt = json.loads((directory / f"{stem}.receipt.json").read_text())
            raw = gzip.decompress((directory / f"{stem}.json.gz").read_bytes())
            if receipt["status"] != 200 or receipt["url"] != expected or receipt["final_url"] != expected:
                raise FatalContractError("Modern metadata receipt breaks the publisher pagination chain")
            if len(raw) != receipt["bytes"] or hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
                raise FatalContractError("Modern metadata bytes do not match their receipt")
            page = json.loads(raw)
            if page["type"] != "FeatureCollection" or page["numberReturned"] != len(page["features"]):
                raise FatalContractError("Malformed modern metadata feature collection")
            links = [link["href"] for link in page["links"] if link["rel"] == "next"]
            if len(links) > 1:
                raise FatalContractError("Ambiguous modern metadata pagination")
            expected = links[0] if links else None
            for feature in page["features"]:
                properties = feature["properties"]
                if feature["id"] != properties["id"] or properties["parameter_code"] != parameter:
                    raise FatalContractError("Modern metadata contradicts requested identity or parameter")
                features.append(properties)
            count += len(page["features"])
            receipts.append(receipt)
        if expected is not None or count != completion["features"] or receipts[-1]["url"] != completion["last_url"]:
            raise FatalContractError("Modern metadata chain is incomplete")
    return features, receipts


def read_monitoring_locations(manifest_path: Path):
    """Verify explicitly selected modern location response bodies and receipts."""
    from urllib.parse import parse_qs, urlsplit

    requests = json.loads(manifest_path.read_text())
    if not isinstance(requests, list):
        raise FatalContractError("Monitoring-location selection must be an array")
    features, receipts = [], []
    seen = set()
    expected_url = None
    batch_ids: set[str] = set()
    batch_seen: set[str] = set()
    batch_pages = 0
    for request in requests:
        paths = []
        for key in ("body", "receipt"):
            relative = Path(request[key])
            if relative.is_absolute() or ".." in relative.parts:
                raise FatalContractError("Monitoring-location inputs require safe relative paths")
            paths.append(manifest_path.parent / relative)
        body_path, receipt_path = paths
        receipt = json.loads(receipt_path.read_text())
        url = receipt["url"]
        parsed = urlsplit(url)
        base = "/ogcapi/v1/collections/monitoring-locations/items"
        query = parse_qs(parsed.query)
        identities = query.get("id", [parsed.path.removeprefix(base + "/")])[0].split(",")
        if (
            not isinstance(identities, list)
            or not identities
            or any(not isinstance(item, str) or not item for item in identities)
            or len(set(identities)) != len(identities)
        ):
            raise FatalContractError("Monitoring-location request identities must be distinct")
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.waterdata.usgs.gov"
            or not (parsed.path == base or parsed.path.startswith(base + "/"))
        ):
            raise FatalContractError("Monitoring-location request has an unsupported source URL")
        if query.get("f") != ["json"]:
            raise FatalContractError("Monitoring-location request URL contradicts selected identities")
        try:
            offset = int(query.get("offset", ["0"])[0])
        except ValueError as exc:
            raise FatalContractError("Monitoring-location offset is invalid") from exc
        if expected_url is None:
            if offset != 0:
                raise FatalContractError("Monitoring-location chain must start at offset zero")
            batch_ids = set(identities)
            batch_seen = set()
            batch_pages = 0
        elif url != expected_url:
            raise FatalContractError("Monitoring-location receipt breaks the publisher chain")
        batch_pages += 1
        if batch_pages > len(batch_ids) + 1:
            raise FatalContractError("Monitoring-location pagination exceeds selected identities plus terminal page")
        raw = gzip.decompress(body_path.read_bytes())
        if (
            receipt.get("status") != 200
            or receipt.get("url") != url
            or receipt.get("final_url") != url
            or receipt.get("bytes") != len(raw)
            or receipt.get("sha256") != hashlib.sha256(raw).hexdigest()
        ):
            raise FatalContractError("Monitoring-location bytes or request do not match their receipt")
        page: dict[str, Any] = json.loads(raw)
        if page.get("type") == "Feature":
            page = {"type": "FeatureCollection", "features": [page], "numberReturned": 1, "links": []}
        if (
            page.get("type") != "FeatureCollection"
            or not isinstance(page.get("features"), list)
            or page.get("numberReturned") != len(page["features"])
        ):
            raise FatalContractError("Monitoring-location batch is malformed or incomplete")
        returned = [_required_native_string(item.get("id"), "monitoring-location id") for item in page["features"]]
        if len(returned) != len(set(returned)) or not set(returned) <= batch_ids or seen.intersection(returned):
            raise FatalContractError("Monitoring-location response identities do not resolve exactly")
        seen.update(returned)
        batch_seen.update(returned)
        links = [link["href"] for link in page.get("links", []) if link.get("rel") == "next"]
        if len(links) > 1:
            raise FatalContractError("Monitoring-location pagination is ambiguous")
        expected_url = links[0] if links else None
        if expected_url is not None:
            following = urlsplit(expected_url)
            next_query = parse_qs(following.query)
            try:
                next_offset = int(next_query.get("offset", ["0"])[0])
            except ValueError as exc:
                raise FatalContractError("Monitoring-location next offset is invalid") from exc
            if (
                following.scheme != parsed.scheme
                or following.netloc != parsed.netloc
                or following.path != parsed.path
                or following.fragment
                or {key: value for key, value in next_query.items() if key != "offset"}
                != {key: value for key, value in query.items() if key != "offset"}
                or next_offset <= offset
            ):
                raise FatalContractError("Monitoring-location next link changes identity or fails to advance")
        elif batch_seen != batch_ids:
            raise FatalContractError("Monitoring-location terminal batch identities do not resolve exactly")
        features.extend(page["features"])
        receipts.append(receipt)
    if expected_url is not None:
        raise FatalContractError("Monitoring-location publisher chain is incomplete")
    if not receipts:
        raise FatalContractError("Monitoring-location selection is empty")
    return features, receipts


def build_modern_catalogue(
    features: Sequence[dict[str, object]],
    location_features: Iterable[dict[str, object]],
    *,
    baseline_locations: Mapping[str, str],
    retrieved_at: RetrievedAt,
    historical_features: Sequence[dict[str, object]] = (),
    retained_series_ids: tuple[str, ...] = (),
    retained_locations: tuple[str, ...] = (),
    origins: OriginDeclarations | None = None,
) -> GeneratedUsgsNwisCatalogue:
    """Build stations and all supported published series from modern source records.

    Legacy sitefile attributes and series claims are independent publication
    inputs. They do not restrict modern station or series existence.
    """
    from rivretrieve._internal.providers.usgs_nwis.catalogue_series import (
        MODERN_PRODUCT_ROUTES,
        modern_source_descriptions,
        retain_source_descriptions,
    )

    selected_historical = [item for item in historical_features if item.get("id") in retained_series_ids]
    selected = set()
    for item in [*features, *selected_historical]:
        key = (item.get("parameter_code"), item.get("computation_period_identifier"), item.get("statistic_id"))
        if key in MODERN_PRODUCT_ROUTES:
            location = item.get("monitoring_location_id")
            if not isinstance(location, str) or not location:
                raise FatalContractError("Modern source series has no monitoring-location identity")
            selected.add(location)
    native, stations = build_modern_stations(
        location_features,
        selected,
        baseline_locations=baseline_locations,
        retrieved_at=retrieved_at,
        retained_locations=retained_locations,
    )
    from rivretrieve._internal.providers.usgs_nwis.origins import MODERN_STATION_CATALOGUE_ORIGINS

    enforce_catalogue_origins(
        PROVIDER_ID, MODERN_STATION_CATALOGUE_ORIGINS if origins is None else origins, native, stations
    )
    locations = dict(native.data.select("station_id", "monitoring_location_id").iter_rows())
    descriptions = modern_source_descriptions(features, locations)
    if retained_series_ids:
        descriptions = retain_source_descriptions(
            descriptions,
            modern_source_descriptions(selected_historical, locations),
            retained_series_ids,
            locations,
        )
    available = {(item.station_id, item.product_id) for item in descriptions.descriptions}
    vintage = retrieved_at.value.date()
    rows = []
    for station in stations["station_id"]:
        for definition in PRODUCT_DEFINITIONS:
            present = (station, definition.product_id) in available
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station,
                    "product_id": definition.product_id,
                    "availability": "available" if present else "unavailable",
                    "availability_reason": (
                        "Modern metadata UTC range bounds are not physical observation support"
                        if present
                        else "No matching series in the complete modern metadata snapshot"
                    ),
                    "published_record_start_date": None,
                    "published_record_end_date": None,
                    "last_catalogue_check": vintage,
                }
            )
    station_products = pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).sort(
        "station_id", "product_id"
    )
    products = build_products()
    provider_info = build_provider_info(vintage)
    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedUsgsNwisCatalogue(
        provider_info=provider_info,
        products=products,
        stations=stations,
        station_products=station_products,
        source_native=native.data,
        retained_series_ids=retained_series_ids,
        source_descriptions=descriptions,
    )


# FIPS codes for the 50 states and District of Columbia; territories are outside scope.
_US_STATE_FIPS = frozenset(
    [
        "01",
        "02",
        "04",
        "05",
        "06",
        "08",
        "09",
        "10",
        "11",
        "12",
        "13",
        "15",
        "16",
        "17",
        "18",
        "19",
        "20",
        "21",
        "22",
        "23",
        "24",
        "25",
        "26",
        "27",
        "28",
        "29",
        "30",
        "31",
        "32",
        "33",
        "34",
        "35",
        "36",
        "37",
        "38",
        "39",
        "40",
        "41",
        "42",
        "44",
        "45",
        "46",
        "47",
        "48",
        "49",
        "50",
        "51",
        "53",
        "54",
        "55",
        "56",
    ]
)
MODERN_STATION_SCHEMA = pl.Schema(
    {
        "agency_code": pl.String,
        "monitoring_location_number": pl.String,
        "station_id": pl.String,
        "monitoring_location_id": pl.String,
        "monitoring_location_name": pl.String,
        "latitude": pl.Float64,
        "longitude": pl.Float64,
        "crs": pl.String,
        "retrieved_at": pl.Datetime(time_unit="us", time_zone="UTC"),
    }
)


def build_modern_stations(
    features: Iterable[dict[str, object]],
    series_locations: set[str],
    *,
    baseline_locations: Mapping[str, str],
    retrieved_at: RetrievedAt,
    retained_locations: tuple[str, ...] = (),
) -> tuple[NativeTable, StationCatalog]:
    """Select modern locations with supported series in the declared geography.

    Explicitly retained locations may lie outside the 50 states and DC. Every
    requested identity must resolve to a publisher feature, even when its
    geometry is null. Missing responses are errors, not unlocated stations.
    ``baseline_locations`` preserves public IDs for previously registered source
    identities. New colliding station numbers use agency-qualified IDs.
    """
    import math

    rows = []
    seen = set()
    selected = series_locations | set(retained_locations) | set(baseline_locations.values())
    for feature in features:
        location = feature.get("id")
        properties = cast("dict[str, Any]", feature.get("properties"))
        if feature.get("type") != "Feature" or not isinstance(location, str) or not isinstance(properties, dict):
            raise FatalContractError("Malformed modern monitoring-location feature")
        if location not in selected:
            continue
        agency = _required_native_string(properties.get("agency_code"), "agency_code")
        number = _required_native_string(properties.get("monitoring_location_number"), "monitoring_location_number")
        if location != f"{agency}-{number}" or properties.get("id", location) != location or location in seen:
            raise FatalContractError("Modern monitoring-location identity is inconsistent or duplicated")
        seen.add(location)
        if location not in retained_locations:
            country = properties.get("country_code")
            if not isinstance(country, str) or not country:
                raise FatalContractError("Modern monitoring-location lacks source country_code")
            if country != "US":
                continue
            state = properties.get("state_code")
            if state in {"60", "66", "69", "72", "74", "78"}:
                continue
            if not isinstance(state, str) or state not in _US_STATE_FIPS:
                raise FatalContractError("Modern monitoring-location has unresolved source state_code")
        name = properties.get("monitoring_location_name")
        if name is not None and not isinstance(name, str):
            raise FatalContractError("Modern monitoring-location name must be a string or null")
        latitude = longitude = None
        if "geometry" not in feature:
            raise FatalContractError("Modern monitoring-location has no geometry field")
        geometry = cast("dict[str, Any] | None", feature["geometry"])
        if geometry is not None:
            if not isinstance(geometry, dict) or geometry.get("type") != "Point":
                raise FatalContractError("Modern monitoring-location geometry must be Point or null")
            coordinates = geometry.get("coordinates")
            if (
                not isinstance(coordinates, list)
                or len(coordinates) < 2
                or any(
                    isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                    for v in coordinates[:2]
                )
            ):
                raise FatalContractError("Modern monitoring-location has invalid coordinates")
            longitude, latitude = coordinates[:2]
            if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                raise FatalContractError("Modern monitoring-location coordinates are outside WGS84 bounds")
        rows.append(
            {
                "agency_code": agency,
                "monitoring_location_number": number,
                "monitoring_location_id": location,
                "monitoring_location_name": name,
                "latitude": latitude,
                "longitude": longitude,
                "crs": "unknown" if geometry is None else "EPSG:4326",
                "retrieved_at": retrieved_at.value,
            }
        )
    if selected - seen:
        raise FatalContractError("Modern monitoring-location features are missing selected series identities")
    counts: dict[str, int] = {}
    for row in rows:
        number = str(row["monitoring_location_number"])
        counts[number] = counts.get(number, 0) + 1
    baseline_by_location = {location: station for station, location in baseline_locations.items()}
    if len(baseline_by_location) != len(baseline_locations) or any(
        not isinstance(station, str)
        or not isinstance(location, str)
        or station not in (location, location.partition("-")[2])
        for station, location in baseline_locations.items()
    ):
        raise FatalContractError("Invalid baseline monitoring-location mapping")
    for row in rows:
        location, number = str(row["monitoring_location_id"]), str(row["monitoring_location_number"])
        row["station_id"] = baseline_by_location.get(
            location, number if counts[number] == 1 and number not in baseline_locations else location
        )
    if len({row["station_id"] for row in rows}) != len(rows):
        raise FatalContractError("Canonical station identities collide")
    native = NativeTable(pl.DataFrame(rows, schema=MODERN_STATION_SCHEMA).sort("station_id"))
    stations = native.data.select(
        pl.lit(str(PROVIDER_ID)).alias("provider_id"),
        "station_id",
        "latitude",
        "longitude",
        "crs",
    )
    return native, stations


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
            "native_id": (f"{defn.param_code}:{defn.stat_code}" if defn.stat_code else defn.param_code),
        }
        for defn in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


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
            "true: requests per station-product pair; "
            "modern daily and continuous endpoints selected by product; "
            "partial failures reported as recoverable issues"
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
        acquisition_provenance=__import__(
            "rivretrieve._internal.providers.usgs_nwis.origins", fromlist=["build_acquisition_provenance"]
        ).build_acquisition_provenance(),
        on_issue="raise",
    )


def write_catalogue(
    catalogue: GeneratedUsgsNwisCatalogue,
    out_dir: Path | str,
    *,
    build_inputs: CatalogueBuildInputs | None = None,
    native_table: NativeTable | None = None,
    acquisition_provenance: AcquisitionProvenance | None = None,
    legacy_table: NativeTable | None = None,
) -> None:
    """Write a catalogue from explicit adopted inputs, native table and acquisition provenance."""
    from rivretrieve._internal.catalogues.artifact import REQUIRED_ARTIFACT_FILES
    from rivretrieve._internal.catalogues.publication import build_catalogue_metadata
    from rivretrieve._internal.providers.usgs_nwis.origins import (
        MODERN_STATION_CATALOGUE_ORIGINS as STATION_CATALOGUE_ORIGINS,
    )
    from rivretrieve._internal.providers.usgs_nwis.origins import (
        SELECTED_SOURCE_ROLES,
        STATION_METADATA_NOTICE,
        bind_legacy_metadata_conflicts,
        selected_role_inputs,
        selected_station_metadata_fields,
    )

    if catalogue.source_descriptions is None:
        raise FatalContractError(
            "Modern USGS publication requires complete modern metadata; legacy native builds cannot be published"
        )

    if build_inputs is None or native_table is None:
        raise FatalContractError("Catalogue publication requires explicit build_inputs and native_table")
    if acquisition_provenance is None:
        raise FatalContractError("Catalogue publication requires explicit acquisition_provenance")

    if catalogue.retained_series_ids:
        selected_role_inputs(acquisition_provenance, "retained_historical_metadata")
    if legacy_table is None:
        raise FatalContractError("Modern publication requires explicit legacy enrichment and claims input")
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as file:
        json.dump(catalogue.provider_info, file, sort_keys=True, separators=(",", ":"))
        file.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")
    files = {name: (output_path / name).read_bytes() for name in REQUIRED_ARTIFACT_FILES}
    locations = dict(catalogue.source_native.select("station_id", "monitoring_location_id").iter_rows())
    descriptions = catalogue.source_descriptions
    provenance = acquisition_provenance
    from rivretrieve._internal.providers.usgs_nwis.catalogue_series import catalogue_claims
    from rivretrieve._internal.providers.usgs_nwis.station_metadata import (
        legacy_metadata_conflicts,
        project_modern_station_metadata,
    )

    station_origin = STATION_CATALOGUE_ORIGINS["station_id"]
    if not isinstance(station_origin, Field):
        raise FatalContractError("USGS metadata requires a native station identity field")
    metadata_fields = selected_station_metadata_fields(provenance)
    station_metadata = project_modern_station_metadata(native_table, legacy_table, catalogue.stations, metadata_fields)
    conflicts = legacy_metadata_conflicts(native_table, legacy_table, metadata_fields)
    provenance = bind_legacy_metadata_conflicts(provenance, conflicts)
    exposed_fields = set(station_metadata["source_field"].drop_nulls())
    metadata_fields = tuple(field for field in metadata_fields if field.source_field in exposed_fields)

    metadata = build_catalogue_metadata(
        provenance,
        (STATION_CATALOGUE_ORIGINS,),
        files,
        source_descriptions=descriptions,
        catalogue_claims=catalogue_claims(
            legacy_table.data,
            {definition.series_key: definition.product_id for definition in PRODUCT_DEFINITIONS},
            catalogue.source_native,
            evidence=tuple(
                f"catalogue:usgs_nwis:{fact}" for fact in selected_role_inputs(provenance, "legacy_series_claims")
            ),
        ),
        build_inputs=build_inputs,
        native_table=native_table,
        metadata_fields=metadata_fields,
        station_metadata=station_metadata,
        metadata_implementation=(
            "src/rivretrieve/_internal/providers/usgs_nwis/station_metadata.py",
            "project_modern_station_metadata",
        ),
        station_metadata_notice=STATION_METADATA_NOTICE,
        transformation_implementations={
            **{
                f"selected_{role}": (
                    "src/rivretrieve/_internal/providers/usgs_nwis/origins.py",
                    "build_modern_acquisition_provenance",
                )
                for role in SELECTED_SOURCE_ROLES
            },
            **{
                f"usgs_sitefile_conflict.{station}.{field}": (
                    "src/rivretrieve/_internal/providers/usgs_nwis/station_metadata.py",
                    "project_modern_station_metadata",
                )
                for station, field in conflicts
            },
        },
    )
    from rivretrieve._internal.catalogues.source_series import decode_source_descriptions, encode_source_descriptions

    metadata["source_series.json"] = encode_source_descriptions(descriptions, schema_version=2)
    if decode_source_descriptions(metadata["source_series.json"]) != descriptions:
        raise FatalContractError("Source-description encoding changed source definitions")
    from rivretrieve._internal.catalogues.descriptor import build_catalogue_descriptor
    from rivretrieve._internal.catalogues.evidence import EvidenceHeader
    from rivretrieve._internal.catalogues.evidence_encoding import EVIDENCE_FILENAMES, parse_catalogue_evidence

    evidence = parse_catalogue_evidence(
        EvidenceHeader.model_validate_json(metadata["provenance.json"]),
        {filename: metadata[filename] for filename in EVIDENCE_FILENAMES.values()},
    )
    metadata["monitoring_locations.json"] = (
        json.dumps(locations, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    metadata.pop("croissant.json")
    metadata["croissant.json"] = (
        json.dumps(
            build_catalogue_descriptor(
                evidence,
                (STATION_CATALOGUE_ORIGINS,),
                {**files, **metadata},
                station_metadata_notice=STATION_METADATA_NOTICE,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    ).encode()
    for name, content in metadata.items():
        (output_path / name).write_bytes(content)


def _read_fixture_json(path: Path) -> list[object]:
    try:
        with path.open(encoding="utf-8") as file:
            value = json.load(file)
    except OSError as exc:
        raise FatalContractError(f"Unable to read USGS NWIS sites fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"USGS NWIS sites fixture is not valid JSON: {path}") from exc
    if not isinstance(value, list):
        raise FatalContractError("USGS NWIS sites fixture must contain a JSON array")
    return cast("list[object]", value)


def _required_native_string(value: object, column: str) -> str:
    if not isinstance(value, str) or not value or value.isspace():
        raise FatalContractError(f"USGS native row has blank required {column}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the offline modern USGS station catalogue.")
    parser.add_argument("--modern-metadata", type=Path, required=True)
    parser.add_argument(
        "--monitoring-locations", type=Path, required=True, help="Explicit locations.json recording selection."
    )
    parser.add_argument("--retention-manifest", type=Path, required=True)
    parser.add_argument("--baseline-locations", type=Path, required=True)
    parser.add_argument("--baseline-sha256", required=True)
    parser.add_argument("--retained-metadata", type=Path, required=True)
    parser.add_argument("--native", type=Path, help="Adopted modern station projection.")
    parser.add_argument("--legacy-native", type=Path, help="Verified legacy enrichment and historical claims table.")
    parser.add_argument(
        "--native-out", type=Path, help="Write the modern station projection for reviewed input adoption."
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--build-inputs", type=Path)
    parser.add_argument("--acquisition-provenance", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    args = parser.parse_args(argv)
    if args.native_out is None and args.out is None:
        parser.error("select --native-out or --out")
    if args.out is not None and any(
        value is None
        for value in (
            args.build_inputs,
            args.acquisition_provenance,
            args.evidence_root,
            args.legacy_native,
            args.native,
        )
    ):
        parser.error("--out requires --build-inputs, --acquisition-provenance, --evidence-root and --legacy-native")
    if args.native_out is not None and args.out is not None:
        parser.error("--native-out preparation and --out publication are separate stages")
    selection = json.loads(args.retention_manifest.read_text())
    if (
        not isinstance(selection, dict)
        or set(selection) != {"schema_version", "historical_series_ids", "retained_station_ids"}
        or selection["schema_version"] != 1
    ):
        raise FatalContractError("Invalid USGS retention manifest schema")
    for key in ("historical_series_ids", "retained_station_ids"):
        values = selection[key]
        if (
            not isinstance(values, list)
            or any(not isinstance(item, str) or not item for item in values)
            or len(set(values)) != len(values)
        ):
            raise FatalContractError("USGS retention manifest requires distinct nonblank identities")
    features, receipts = read_modern_metadata(args.modern_metadata)
    locations, location_receipts = read_monitoring_locations(args.monitoring_locations)
    historical, _ = read_modern_metadata(args.retained_metadata)
    retrieved_at = RetrievedAt(
        max(datetime.fromisoformat(item["retrieved_at"]) for item in receipts + location_receipts)
    )
    baseline_bytes = args.baseline_locations.read_bytes()
    if hashlib.sha256(baseline_bytes).hexdigest() != args.baseline_sha256:
        raise FatalContractError("Baseline monitoring-location bytes changed")
    catalogue = build_modern_catalogue(
        features,
        locations,
        baseline_locations=json.loads(baseline_bytes),
        retrieved_at=retrieved_at,
        historical_features=historical,
        retained_series_ids=tuple(selection["historical_series_ids"]),
        retained_locations=tuple(selection["retained_station_ids"]),
    )
    native = NativeTable(catalogue.source_native)
    if args.native_out is not None:
        write_native_table(native, args.native_out)
    if args.out is not None:
        provenance = AcquisitionProvenance.model_validate_json(args.acquisition_provenance.read_bytes())
        verify_provenance_recordings(provenance, args.evidence_root)
        build_inputs = CatalogueBuildInputs.model_validate_json(args.build_inputs.read_bytes())
        baseline_inputs = [item for item in build_inputs.inputs if "source.station.baseline_identity" in item.facts]
        if len(baseline_inputs) != 1 or (
            baseline_inputs[0].reference.sha256 != args.baseline_sha256
            or baseline_inputs[0].reference.byte_size != len(baseline_bytes)
        ):
            raise FatalContractError("Publication requires the adopted baseline identity input")
        if provenance.provider_id != PROVIDER_ID or provenance.native_table is None:
            raise FatalContractError("Modern publication requires explicit matching native identity")
        adopted = read_native_table(
            args.native,
            expected_sha256=provenance.native_table.sha256,
            expected_byte_size=provenance.native_table.byte_size,
        )
        if not adopted.data.equals(native.data):
            raise FatalContractError("Rebuilt modern stations differ from the adopted native projection")
        from rivretrieve._internal.providers.usgs_nwis.origins import selected_role_inputs

        legacy_facts = set(selected_role_inputs(provenance, "legacy_sitefile_attributes"))
        legacy_inputs = [item for item in build_inputs.inputs if legacy_facts <= set(item.facts)]
        if len(legacy_inputs) != 1:
            raise FatalContractError("Modern publication requires one adopted legacy enrichment table")
        reference = legacy_inputs[0].reference
        legacy = read_native_table(
            args.legacy_native,
            expected_sha256=reference.sha256,
            expected_byte_size=reference.byte_size,
        )
        write_catalogue(
            catalogue,
            args.out,
            build_inputs=build_inputs,
            native_table=native,
            acquisition_provenance=provenance,
            legacy_table=legacy,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

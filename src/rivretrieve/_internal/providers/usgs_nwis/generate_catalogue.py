"""USGS catalogue maintenance : refresh(SeriesRdbRows × ExpandedRdbRows, RetrievedAt) → WithIssues[NativeTable]; build(NativeTable, OriginDeclarations) → GeneratedUsgsNwisCatalogue."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
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
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId

PROVIDER_ID = ProviderId("usgs_nwis")
PROVIDER_NAME = "U.S. Geological Survey National Water Information System (USGS NWIS)"
METADATA_BASE_URL = "https://waterservices.usgs.gov/nwis/site/"
SERIES_CATALOGUE_URL = (
    METADATA_BASE_URL
    + "?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd={state_cd}&seriesCatalogOutput=true"
)
EXPANDED_SITE_URL = (
    METADATA_BASE_URL
    + "?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd={state_cd}&siteOutput=expanded"
)
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


class NativeInputKind(Enum):
    FIXTURE = "fixture"
    SUPPLIED_NATIONAL = "supplied-national"


NO_MATCH_REASON = "No matching USGS source series was published for this station-product"
BLANK_COVERAGE_REASON = "Matching USGS source series states blank coverage dates"
CONFLICTING_COVERAGE_REASON = "Several matching USGS source series state conflicting coverage boundaries"

_DATUM_TO_CRS = {
    "NAD27": "EPSG:4267",
    "NAD83": "EPSG:4269",
    "OLDHI": "EPSG:4135",
    "WGS72": "EPSG:4322",
    "WGS84": "EPSG:4326",
}

_CFS_TO_M3S = 0.0283168466
_FT_TO_M = 0.3048


@dataclass(frozen=True)
class GeneratedUsgsNwisCatalogue:
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
        period_anchor="start",
        canonical_unit="m3/s",
        param_code="00060",
        stat_code="00003",
        returned_data_type_cd="dv",
        returned_stat_cd="00003",
    ),
    ProductDefinition(
        product_id="discharge_instantaneous",
        observed_property="discharge",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
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
        period_anchor="start",
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
        period_anchor="start",
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
        period_anchor="start",
        canonical_unit="m",
        param_code="00065",
        stat_code="00002",
        returned_data_type_cd="dv",
        returned_stat_cd="00002",
    ),
    ProductDefinition(
        product_id="stage_instantaneous",
        observed_property="stage",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
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


def _validate_national_products(series_records: dict[str, list[tuple[str, ...]]]) -> None:
    matches = {definition.series_key: 0 for definition in PRODUCT_DEFINITIONS}
    data_type_index = SERIES_ONLY_FIELDS.index("data_type_cd")
    parm_index = SERIES_ONLY_FIELDS.index("parm_cd")
    stat_index = SERIES_ONLY_FIELDS.index("stat_cd")
    for records in series_records.values():
        for record in records:
            key = (record[data_type_index], record[parm_index], record[stat_index])
            if key in matches:
                matches[key] += 1
    zero_matches = [definition for definition in PRODUCT_DEFINITIONS if matches[definition.series_key] == 0]
    if zero_matches:
        missing = ", ".join(f"{definition.product_id}={definition.series_key!r}" for definition in zero_matches)
        raise FatalContractError(f"USGS native input has products with zero matching series rows: {missing}")


def refresh_native_table(
    series_rows: Iterable[object],
    expanded_rows: Iterable[object],
    *,
    retrieved_at: RetrievedAt,
    input_kind: NativeInputKind,
) -> WithIssues[NativeTable]:
    expanded_by_site: dict[str, dict[str, str]] = {}
    for item in expanded_rows:
        row = _validated_source_row(item, EXPANDED_HEADER, row_kind="expanded")
        site_no = _required_site_no(row, row_kind="expanded")
        if site_no in expanded_by_site:
            raise FatalContractError(f"USGS expanded input contains duplicate site_no {site_no!r}")
        expanded_by_site[site_no] = row
    if not expanded_by_site:
        raise FatalContractError("USGS expanded input is empty")

    series_records: dict[str, list[tuple[str, ...]]] = {}
    series_shared: dict[str, tuple[str, ...]] = {}
    data_types: set[str] = set()
    for item in series_rows:
        row = _validated_source_row(item, SERIES_HEADER, row_kind="series")
        site_no = _required_site_no(row, row_kind="series")
        shared = tuple(row[name] for name in SHARED_STATION_FIELDS)
        previous_shared = series_shared.setdefault(site_no, shared)
        if shared != previous_shared:
            differing = next(
                name
                for name, previous, current in zip(SHARED_STATION_FIELDS, previous_shared, shared, strict=True)
                if previous != current
            )
            raise FatalContractError(f"USGS series rows conflict on {differing} for site_no {site_no!r}")
        series_records.setdefault(site_no, []).append(tuple(row[name] for name in SERIES_ONLY_FIELDS))
        data_types.add(row["data_type_cd"])
    if not series_records:
        raise FatalContractError("USGS series input is empty")

    series_sites = set(series_records)
    expanded_sites = set(expanded_by_site)
    if series_sites != expanded_sites:
        raise FatalContractError(
            "USGS series and expanded site sets differ: "
            f"expanded_only={len(expanded_sites - series_sites)}, series_only={len(series_sites - expanded_sites)}"
        )
    if not {"dv", "uv"}.issubset(data_types):
        raise FatalContractError("USGS series input must contain both dv and uv data_type_cd values")
    if input_kind is NativeInputKind.SUPPLIED_NATIONAL and len(expanded_by_site) < _LIVE_MIN_STATIONS:
        raise FatalContractError(
            f"USGS supplied-national native input has only {len(expanded_by_site):,} stations; "
            f"expected at least {_LIVE_MIN_STATIONS:,}"
        )
    if input_kind is NativeInputKind.SUPPLIED_NATIONAL:
        _validate_national_products(series_records)

    native_rows: list[dict[str, object]] = []
    for site_no in sorted(expanded_by_site):
        expanded = expanded_by_site[site_no]
        shared = series_shared[site_no]
        for name, series_value in zip(SHARED_STATION_FIELDS, shared, strict=True):
            if expanded[name] != series_value:
                raise FatalContractError(f"USGS passes conflict on {name} for site_no {site_no!r}")
        records = sorted(series_records[site_no])
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
        input_kind=NativeInputKind.FIXTURE,
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
        input_kind=NativeInputKind.SUPPLIED_NATIONAL,
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
        input_kind=NativeInputKind.SUPPLIED_NATIONAL,
    )


_LIVE_MIN_STATIONS = 10_000


def build_catalogue(
    native_table: NativeTable,
    origins: OriginDeclarations,
) -> GeneratedUsgsNwisCatalogue:
    if native_table.data.schema != NATIVE_SCHEMA:
        raise FatalContractError("USGS native table does not have the exact required schema")
    if native_table.data.is_empty():
        raise FatalContractError("USGS native table must not be empty")

    series_records = _series_records_by_station(native_table)
    _validate_national_products(series_records)
    products = build_products()
    stations = build_stations(native_table)
    enforce_catalogue_origins(PROVIDER_ID, origins, native_table, stations)
    station_products = build_station_products(native_table, series_records)
    maximum_retrieved_at = native_table.data["retrieved_at"].max()
    if not isinstance(maximum_retrieved_at, datetime):
        raise FatalContractError("USGS native table has no valid retrieved_at values")
    provider_info = build_provider_info(maximum_retrieved_at.date())
    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedUsgsNwisCatalogue(
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
            "native_id": (f"{defn.param_code}:{defn.stat_code}" if defn.stat_code else defn.param_code),
            "derived": False,
            "derivation_method": None,
        }
        for defn in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(native_table: NativeTable) -> StationCatalog:
    rows = []
    for native_row in native_table.data.iter_rows(named=True):
        station_id = _required_native_string(native_row["site_no"], "site_no")
        latitude = _required_native_float(native_row["dec_lat_va"], station_id, "dec_lat_va")
        longitude = _required_native_float(native_row["dec_long_va"], station_id, "dec_long_va")
        datum = native_row["dec_coord_datum_cd"]
        if not isinstance(datum, str):
            raise FatalContractError(f"USGS station {station_id!r} has invalid dec_coord_datum_cd")
        rows.append(
            {
                "provider_id": PROVIDER_ID,
                "station_id": station_id,
                "latitude": latitude,
                "longitude": longitude,
                "crs": _DATUM_TO_CRS.get(datum, "unknown"),
            }
        )
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(
    native_table: NativeTable,
    series_records: dict[str, list[tuple[str, ...]]] | None = None,
) -> StationProductCatalog:
    records_by_station = series_records or _series_records_by_station(native_table)
    rows = []
    for native_row in native_table.data.iter_rows(named=True):
        station_id = _required_native_string(native_row["site_no"], "site_no")
        retrieved_at = native_row["retrieved_at"]
        if not isinstance(retrieved_at, datetime):
            raise FatalContractError(f"USGS station {station_id!r} has invalid retrieved_at")
        station_records = records_by_station[station_id]
        for defn in PRODUCT_DEFINITIONS:
            matches = [record for record in station_records if _series_key(record) == defn.series_key]
            availability, reason, start_date, end_date = _matching_coverage(
                station_id,
                defn.product_id,
                matches,
            )
            {
                "station_id": station_id,
                "product_id": defn.product_id,
                "returned_series_key": {
                    "data_type_cd": defn.returned_data_type_cd,
                    "parm_cd": defn.param_code,
                    "stat_cd": defn.returned_stat_cd,
                },
                "exact_match_count": len(matches),
            }
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": defn.product_id,
                    "availability": availability,
                    "availability_reason": reason,
                    "start_date": start_date,
                    "end_date": end_date,
                    "last_catalogue_check": retrieved_at.date(),
                }
            )
    return (
        pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema)
        .with_columns(pl.col("availability").cast(AvailabilityDtype))
        .sort("station_id", "product_id")
    )


def _series_records_by_station(native_table: NativeTable) -> dict[str, list[tuple[str, ...]]]:
    records_by_station: dict[str, list[tuple[str, ...]]] = {}
    for native_row in native_table.data.iter_rows(named=True):
        station_id = _required_native_string(native_row["site_no"], "site_no")
        columns = [native_row[name] for name in SERIES_ONLY_FIELDS]
        if any(not isinstance(values, list) for values in columns):
            raise FatalContractError(f"USGS station {station_id!r} has malformed source-series list columns")
        lengths = {len(values) for values in columns}
        if len(lengths) != 1:
            raise FatalContractError(f"USGS station {station_id!r} has misaligned source-series list columns")
        records_by_station[station_id] = list(zip(*columns, strict=True))
    return records_by_station


def _series_key(record: tuple[str, ...]) -> tuple[str, str, str]:
    return (
        record[SERIES_ONLY_FIELDS.index("data_type_cd")],
        record[SERIES_ONLY_FIELDS.index("parm_cd")],
        record[SERIES_ONLY_FIELDS.index("stat_cd")],
    )


def _matching_coverage(
    station_id: str,
    product_id: str,
    matches: list[tuple[str, ...]],
) -> tuple[str, str | None, date | None, date | None]:
    if not matches:
        return "unavailable", NO_MATCH_REASON, None, None

    begin_index = SERIES_ONLY_FIELDS.index("begin_date")
    end_index = SERIES_ONLY_FIELDS.index("end_date")
    boundaries = {(record[begin_index], record[end_index]) for record in matches}
    if len(boundaries) > 1:
        return "available", CONFLICTING_COVERAGE_REASON, None, None

    begin_value, end_value = next(iter(boundaries))
    if not begin_value or not end_value:
        return "available", BLANK_COVERAGE_REASON, None, None
    try:
        return "available", None, date.fromisoformat(begin_value), date.fromisoformat(end_value)
    except ValueError as exc:
        raise FatalContractError(
            f"USGS station {station_id!r} product {product_id!r} has invalid nonblank coverage date"
        ) from exc


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
            "true: annual-window requests per station-product pair; "
            "DV and IV endpoints selected by product; "
            "partial failures reported as recoverable issues"
        ),
        "catalogue_version": catalogue_date.isoformat(),
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


def write_catalogue(catalogue: GeneratedUsgsNwisCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as file:
        json.dump(catalogue.provider_info, file, sort_keys=True, separators=(",", ":"))
        file.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")


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


def _required_native_float(value: object, station_id: str, column: str) -> float:
    if not isinstance(value, str) or not value or value.isspace():
        raise FatalContractError(f"USGS station {station_id!r} has blank required {column}")
    try:
        return float(value)
    except ValueError as exc:
        raise FatalContractError(f"USGS station {station_id!r} has nonnumeric required {column}") from exc


def _parse_retrieved_at(value: str) -> RetrievedAt:
    if not value.endswith("Z") or value.count("Z") != 1:
        raise argparse.ArgumentTypeError("retrieved_at must be an ISO 8601 UTC instant ending in Z")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("retrieved_at must be an ISO 8601 UTC instant ending in Z") from exc
    try:
        return RetrievedAt(parsed)
    except FatalContractError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged usgs_nwis catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--native", type=Path, help="Path to the committed native Parquet table.")
    source.add_argument("--rdb-dir", type=Path, help="Absolute directory containing the two attested RDB passes.")
    source.add_argument("--live", action="store_true", help="Refresh from the live USGS NWIS site service.")
    parser.add_argument("--out", type=Path, help="Output directory for provider.json and parquet files.")
    parser.add_argument("--native-out", type=Path, help="Output path for an attested native Parquet table.")
    parser.add_argument("--retrieved-at", type=_parse_retrieved_at, help="UTC retrieval instant ending in Z.")
    args = parser.parse_args(argv)

    if args.native is not None:
        if args.out is None:
            parser.error("--native requires --out")
        if args.native_out is not None or args.retrieved_at is not None:
            parser.error("--native cannot be combined with --native-out or --retrieved-at")
        from rivretrieve._internal.providers.usgs_nwis.origins import STATION_CATALOGUE_ORIGINS

        catalogue = build_catalogue(read_native_table(args.native), STATION_CATALOGUE_ORIGINS)
        write_catalogue(catalogue, args.out)
        return 0

    if args.out is not None:
        parser.error("native refresh mode cannot be combined with --out")
    if args.native_out is None or args.retrieved_at is None:
        parser.error("native refresh mode requires --native-out and --retrieved-at")

    if args.rdb_dir is not None:
        if not args.rdb_dir.is_absolute():
            parser.error("--rdb-dir must be an absolute path")
        outcome = refresh_native_table_from_rdb_directory(args.rdb_dir, retrieved_at=args.retrieved_at)
    else:
        outcome = refresh_native_table_from_live(retrieved_at=args.retrieved_at)
    write_native_table(outcome.value, args.native_out)
    print(f"USGS native table canonical SHA-256: {native_table_content_sha256(outcome.value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

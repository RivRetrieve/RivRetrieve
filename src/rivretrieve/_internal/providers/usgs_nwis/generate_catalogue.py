"""USGS catalogue maintenance : refresh(SeriesRdbRows × ExpandedRdbRows, RetrievedAt) → WithIssues[NativeTable]; legacy catalogue generation remains operational."""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
from rivretrieve._internal.catalogues.native import NativeTable, RetrievedAt, stamp_native_table, write_native_table
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
from rivretrieve._internal.providers.usgs_nwis.metadata import (
    UsgsNwisProductMetadata,
    UsgsNwisStationProductMetadata,
)

PROVIDER_ID = "usgs_nwis"
PROVIDER_NAME = "U.S. Geological Survey National Water Information System (USGS NWIS)"
METADATA_BASE_URL = "https://waterservices.usgs.gov/nwis/site/"
METADATA_URL = (
    METADATA_BASE_URL
    + "?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&siteOutput=expanded&stateCd={state_cd}"
)
SERIES_CATALOGUE_URL = (
    METADATA_BASE_URL
    + "?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd={state_cd}&seriesCatalogOutput=true"
)
EXPANDED_SITE_URL = (
    METADATA_BASE_URL
    + "?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&stateCd={state_cd}&siteOutput=expanded"
)
# USGS site service requires a geographic filter; nationwide queries return HTTP 400.
# We iterate over all US state FIPS codes.
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


class NativeInputKind(Enum):
    FIXTURE = "fixture"
    SUPPLIED_NATIONAL = "supplied-national"


AVAILABILITY_REASON = (
    "USGS NWIS site catalogue does not expose per-variable station availability at catalogue-generation time"
)
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"

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
    native_unit: str
    param_code: str
    stat_code: str | None
    endpoint: str
    unit_conversion: str
    notes: str | None

    @property
    def metadata(self) -> UsgsNwisProductMetadata:
        return UsgsNwisProductMetadata(
            param_code=self.param_code,
            stat_code=self.stat_code,
            endpoint=self.endpoint,
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
        period_anchor="start",
        canonical_unit="m3/s",
        native_unit="ft3/s",
        param_code="00060",
        stat_code="00003",
        endpoint="dv",
        unit_conversion="cfs_to_m3s",
        notes=(
            "Daily mean discharge. Native unit is cubic feet per second (cfs); "
            "converted to m3/s by multiplying by 0.0283168466. "
            "Timestamps are midnight local time with explicit timezone offset; converted to UTC."
        ),
    ),
    ProductDefinition(
        product_id="discharge_instantaneous",
        observed_property="discharge",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m3/s",
        native_unit="ft3/s",
        param_code="00060",
        stat_code=None,
        endpoint="iv",
        unit_conversion="cfs_to_m3s",
        notes=(
            "Instantaneous discharge (15-minute or sub-hourly). "
            "Native unit is cfs; converted to m3/s. "
            "Timestamps include explicit timezone offset; converted to UTC."
        ),
    ),
    ProductDefinition(
        product_id="stage_daily_mean",
        observed_property="stage",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="start",
        canonical_unit="m",
        native_unit="ft",
        param_code="00065",
        stat_code="00003",
        endpoint="dv",
        unit_conversion="ft_to_m",
        notes=("Daily mean gage height (stage). Native unit is feet; converted to metres by multiplying by 0.3048."),
    ),
    ProductDefinition(
        product_id="stage_daily_max",
        observed_property="stage",
        frequency="daily",
        statistic="max",
        period_type="interval",
        period_anchor="start",
        canonical_unit="m",
        native_unit="ft",
        param_code="00065",
        stat_code="00001",
        endpoint="dv",
        unit_conversion="ft_to_m",
        notes="Daily maximum gage height. Native unit is feet; converted to metres.",
    ),
    ProductDefinition(
        product_id="stage_daily_min",
        observed_property="stage",
        frequency="daily",
        statistic="min",
        period_type="interval",
        period_anchor="start",
        canonical_unit="m",
        native_unit="ft",
        param_code="00065",
        stat_code="00002",
        endpoint="dv",
        unit_conversion="ft_to_m",
        notes="Daily minimum gage height. Native unit is feet; converted to metres.",
    ),
    ProductDefinition(
        product_id="stage_instantaneous",
        observed_property="stage",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m",
        native_unit="ft",
        param_code="00065",
        stat_code=None,
        endpoint="iv",
        unit_conversion="ft_to_m",
        notes=("Instantaneous gage height (15-minute or sub-hourly). Native unit is feet; converted to metres."),
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
    matches = {
        ("dv" if definition.endpoint == "dv" else "uv", definition.param_code, definition.stat_code or ""): 0
        for definition in PRODUCT_DEFINITIONS
    }
    data_type_index = SERIES_ONLY_FIELDS.index("data_type_cd")
    parm_index = SERIES_ONLY_FIELDS.index("parm_cd")
    stat_index = SERIES_ONLY_FIELDS.index("stat_cd")
    for records in series_records.values():
        for record in records:
            key = (record[data_type_index], record[parm_index], record[stat_index])
            if key in matches:
                matches[key] += 1
    zero_matches = [key for key, count in matches.items() if count == 0]
    if zero_matches:
        raise FatalContractError(
            f"USGS supplied-national input has products with zero matching series rows: {zero_matches}"
        )


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


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
) -> GeneratedUsgsNwisCatalogue:
    return generate_catalogue(
        _read_fixture_json(Path(fixture_path)),
        catalogue_date=catalogue_date,
        generator_input="fixture",
    )


def generate_catalogue_from_live(
    *,
    catalogue_date: date | None = None,
) -> GeneratedUsgsNwisCatalogue:
    return generate_catalogue(
        _read_live_sites(),
        catalogue_date=catalogue_date,
        generator_input="live",
    )


_LIVE_MIN_STATIONS = 10_000  # USGS has 8 000+ active stream gauges; far fewer means the live fetch failed silently


def generate_catalogue(
    raw_sites: list[object],
    *,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedUsgsNwisCatalogue:
    effective_date = catalogue_date or date.today()
    products = build_products()
    stations = build_stations(raw_sites)
    if generator_input == "live" and stations.height < _LIVE_MIN_STATIONS:
        raise FatalContractError(
            f"usgs_nwis live catalogue has only {stations.height} stations — expected ≥{_LIVE_MIN_STATIONS}. "
            "The USGS site service fetch likely failed silently or returned a geographic subset. "
            "Do not commit this as the packaged catalogue."
        )
    station_products = build_station_products(stations, effective_date)
    provider_info = build_provider_info(effective_date, generator_input=generator_input)
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
            "metadata": _metadata_json(defn.metadata),
        }
        for defn in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(raw_sites: list[object]) -> StationCatalog:
    rows = [_station_row(item) for item in raw_sites]
    return pl.DataFrame(rows, schema=STATION_CATALOG_SCHEMA.polars_schema).sort("station_id")


def build_station_products(stations: StationCatalog, catalogue_date: date) -> StationProductCatalog:
    rows = []
    for station_id in stations["station_id"].to_list():
        if not isinstance(station_id, str):
            raise FatalContractError("station_id must be a string")
        for defn in PRODUCT_DEFINITIONS:
            meta = UsgsNwisStationProductMetadata(
                station_id=station_id,
                product_id=defn.product_id,
                param_code=defn.param_code,
                stat_code=defn.stat_code,
                endpoint=defn.endpoint,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=(
                    "USGS NWIS site catalogue does not expose per-variable station availability; "
                    "all station-product pairs are materialized as availability=unknown."
                ),
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
                    "metadata": _metadata_json(meta),
                }
            )
    return pl.DataFrame(rows, schema=STATION_PRODUCT_CATALOG_SCHEMA.polars_schema).with_columns(
        pl.col("availability").cast(AvailabilityDtype)
    )


def build_provider_info(
    catalogue_date: date,
    *,
    generator_input: str,
) -> dict[str, object]:
    metadata = {
        "dv_endpoint": "https://waterservices.usgs.gov/nwis/dv/",
        "iv_endpoint": "https://waterservices.usgs.gov/nwis/iv/",
        "site_service_url": "https://waterservices.usgs.gov/nwis/site/",
        "generator_input": generator_input,
        "terms_of_use": "https://waterservices.usgs.gov/",
        "unit_conversions": {
            "cfs_to_m3s": _CFS_TO_M3S,
            "ft_to_m": _FT_TO_M,
        },
    }
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
        "metadata": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
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


def _station_row(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise FatalContractError("Site entry must be a JSON object")
    site = cast("dict[str, object]", item)

    site_no = site.get("site_no")
    if not isinstance(site_no, str) or not site_no.strip():
        raise FatalContractError(f"Site entry missing required string field 'site_no': {site}")
    station_id = site_no.strip()

    lat = _optional_float(site.get("dec_lat_va"), f"Site {station_id} latitude")
    lon = _optional_float(site.get("dec_long_va"), f"Site {station_id} longitude")
    if lat is None or lon is None:
        raise FatalContractError(f"Site {station_id} missing required lat/lon")

    return {
        "provider_id": PROVIDER_ID,
        "station_id": station_id,
        "latitude": lat,
        "longitude": lon,
        "crs": "unknown",
    }


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


def _read_live_sites() -> list[object]:
    all_sites: list[object] = []
    seen: set[str] = set()
    for state_cd in _US_STATE_CODES:
        url = METADATA_URL.format(state_cd=state_cd)
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                if response.status < 200 or response.status >= 300:
                    raise FatalContractError(
                        f"USGS site service request failed with HTTP {response.status} for state {state_cd}"
                    )
                content = response.read().decode("utf-8")
        except OSError as exc:
            raise FatalContractError(f"USGS site service request failed for state {state_cd}") from exc
        for site in _parse_rdb(content):
            site_no = site.get("site_no")
            if isinstance(site_no, str) and site_no and site_no not in seen:
                seen.add(site_no)
                all_sites.append(site)
    return all_sites


def _parse_rdb(content: str) -> list[dict[str, str]]:
    lines = content.splitlines()
    header_line: list[str] | None = None
    data_lines: list[str] = []
    skip_next = False
    for line in lines:
        if line.startswith("#"):
            continue
        if header_line is None:
            header_line = line.split("\t")
            skip_next = True
            continue
        if skip_next:
            skip_next = False
            continue
        data_lines.append(line)
    if header_line is None:
        return []
    result: list[dict[str, str]] = []
    for data_line in data_lines:
        if not data_line.strip():
            continue
        fields = data_line.split("\t")
        row: dict[str, str] = {}
        for i, col in enumerate(header_line):
            row[col.strip()] = fields[i].strip() if i < len(fields) else ""
        result.append(row)
    return result


def _metadata_json(
    model: UsgsNwisProductMetadata | UsgsNwisStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _optional_float(value: object, name: str) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


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
    source.add_argument("--fixture", type=Path, help="Path to a USGS sites JSON fixture.")
    source.add_argument("--live", action="store_true", help="Fetch the live USGS NWIS site service.")
    source.add_argument("--rdb-dir", type=Path, help="Absolute directory containing the two attested RDB passes.")
    parser.add_argument("--out", type=Path, help="Output directory for provider.json and parquet files.")
    parser.add_argument("--native-out", type=Path, help="Output path for an attested native Parquet table.")
    parser.add_argument("--retrieved-at", type=_parse_retrieved_at, help="UTC retrieval instant ending in Z.")
    parser.add_argument("--catalogue-date", type=date.fromisoformat)
    args = parser.parse_args(argv)

    if args.rdb_dir is not None:
        if not args.rdb_dir.is_absolute():
            parser.error("--rdb-dir must be an absolute path")
        if args.native_out is None or args.retrieved_at is None:
            parser.error("native RDB mode requires --native-out and --retrieved-at")
        if args.out is not None or args.catalogue_date is not None:
            parser.error("native RDB mode cannot be combined with --out or --catalogue-date")
        outcome = refresh_native_table_from_rdb_directory(args.rdb_dir, retrieved_at=args.retrieved_at)
        write_native_table(outcome.value, args.native_out)
        return 0

    if args.out is None:
        parser.error("legacy fixture/live mode requires --out")
    if args.native_out is not None or args.retrieved_at is not None:
        parser.error("legacy fixture/live mode cannot be combined with --native-out or --retrieved-at")
    catalogue_date = args.catalogue_date or date.today()
    if args.live:
        catalogue = generate_catalogue_from_live(catalogue_date=catalogue_date)
    else:
        catalogue = generate_catalogue_from_fixture(args.fixture, catalogue_date=catalogue_date)
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

import polars as pl

from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
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
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.usgs_nwis.metadata import (
    UsgsNwisProductMetadata,
    UsgsNwisStationMetadata,
    UsgsNwisStationProductMetadata,
)

PROVIDER_ID = "usgs_nwis"
PROVIDER_NAME = "U.S. Geological Survey National Water Information System (USGS NWIS)"
COUNTRY = "United States"
METADATA_BASE_URL = "https://waterservices.usgs.gov/nwis/site/"
METADATA_URL = (
    METADATA_BASE_URL
    + "?format=rdb&siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065&siteOutput=expanded&stateCd={state_cd}"
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
AVAILABILITY_REASON = (
    "USGS NWIS site catalogue does not expose per-variable station availability at catalogue-generation time"
)
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"

_CFS_TO_M3S = 0.0283168466
_FT_TO_M = 0.3048
_SQ_MI_TO_KM2 = 2.58999


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


def generate_catalogue(
    raw_sites: list[object],
    *,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedUsgsNwisCatalogue:
    effective_date = catalogue_date or date.today()
    products = build_products()
    stations = build_stations(raw_sites)
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

    name = site.get("station_nm")
    if not isinstance(name, str) or not name.strip():
        raise FatalContractError(f"Site {station_id} missing required string field 'station_nm'")
    station_name = name.strip()

    lat = _optional_float(site.get("dec_lat_va"), f"Site {station_id} latitude")
    lon = _optional_float(site.get("dec_long_va"), f"Site {station_id} longitude")
    if lat is None or lon is None:
        raise FatalContractError(f"Site {station_id} missing required lat/lon")

    alt_va = _optional_float(site.get("alt_va"), f"Site {station_id} alt_va")
    elevation_m = alt_va * _FT_TO_M if alt_va is not None else None

    drain_area_sq_mi = _optional_float(site.get("drain_area_va"), f"Site {station_id} drain_area_va")
    drainage_area_km2 = drain_area_sq_mi * _SQ_MI_TO_KM2 if drain_area_sq_mi is not None else None

    state_cd_raw = site.get("state_cd")
    state_cd = state_cd_raw.strip() if isinstance(state_cd_raw, str) and state_cd_raw.strip() else None

    huc_cd_raw = site.get("huc_cd")
    huc_cd = huc_cd_raw.strip() if isinstance(huc_cd_raw, str) and huc_cd_raw.strip() else None

    tz_cd_raw = site.get("tz_cd")
    tz_cd = tz_cd_raw.strip() if isinstance(tz_cd_raw, str) and tz_cd_raw.strip() else None

    begin_date_raw = site.get("begin_date")
    begin_date = begin_date_raw.strip() if isinstance(begin_date_raw, str) and begin_date_raw.strip() else None

    end_date_raw = site.get("end_date")
    end_date_val = end_date_raw.strip() if isinstance(end_date_raw, str) and end_date_raw.strip() else None

    meta = UsgsNwisStationMetadata(
        native_site_no=station_id,
        name=station_name,
        state_cd=state_cd,
        huc_cd=huc_cd,
        tz_cd=tz_cd,
        drain_area_sq_mi=drain_area_sq_mi,
        alt_va_ft=alt_va,
        begin_date=begin_date,
        end_date=end_date_val,
        country=COUNTRY,
    )

    start_date_parsed = _parse_date(begin_date)
    end_date_parsed = _parse_date(end_date_val)

    return {
        "provider_id": PROVIDER_ID,
        "station_id": station_id,
        "name": station_name,
        "latitude": lat,
        "longitude": lon,
        "country": COUNTRY,
        "elevation_m": elevation_m,
        "drainage_area_km2": drainage_area_km2,
        "start_date": start_date_parsed,
        "end_date": end_date_parsed,
        "metadata": _metadata_json(meta),
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
    model: UsgsNwisStationMetadata | UsgsNwisProductMetadata | UsgsNwisStationProductMetadata,
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


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged usgs_nwis catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to a USGS sites JSON fixture.")
    source.add_argument("--live", action="store_true", help="Fetch the live USGS NWIS site service.")
    parser.add_argument("--out", type=Path, required=True, help="Output directory for provider.json and parquet files.")
    parser.add_argument("--catalogue-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)

    if args.live:
        catalogue = generate_catalogue_from_live(catalogue_date=args.catalogue_date)
    else:
        catalogue = generate_catalogue_from_fixture(args.fixture, catalogue_date=args.catalogue_date)
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

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
from rivretrieve._internal.providers.jp_mlit.metadata import (
    JpMlitProductMetadata,
    JpMlitStationProductMetadata,
)

PROVIDER_ID = "jp_mlit"
PROVIDER_NAME = "MLIT Water Information System — Japan national hydrometric network"

SITE_INFO_URL = "http://www1.river.go.jp/cgi-bin/SiteInfo.exe"
SITE_INFO_DETAIL_URL = "http://www1.river.go.jp/cgi-bin/SiteInfoDetail.exe"
DSP_URL = "http://www1.river.go.jp/cgi-bin/DspWaterData.exe"

_LIVE_REQUEST_DELAY_SECONDS = 0.3  # polite rate limit between SiteInfoDetail requests
_LIVE_TIMEOUT_SECONDS = 20

AVAILABILITY_REASON = "jp_mlit catalogue (japan_sites.csv) does not expose per-variable station availability"
AVAILABILITY_SOURCE = "cached_csv_assumption"

MIN_LIVE_STATIONS = 500


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
    native_unit: str
    timezone_handling: str
    notes: str | None

    @property
    def metadata(self) -> JpMlitProductMetadata:
        return JpMlitProductMetadata(
            kind=self.kind,
            frequency=self.frequency,
            native_unit=self.native_unit,
            canonical_unit=self.canonical_unit,
            timezone_handling=self.timezone_handling,
            notes=self.notes,
        )


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
        native_unit="m",
        timezone_handling="jst_to_utc",
        notes=(
            "MLIT KIND 2 hourly stage. "
            "Timestamps in Japan Standard Time (JST = Asia/Tokyo = UTC+9); converted to UTC. "
            "No unit conversion: values are already in metres. "
            "Note: the MLIT website labels KIND 2 as 'Daily' but it provides HOURLY data."
        ),
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
        native_unit="m",
        timezone_handling="date_only_utc_midnight",
        notes=(
            "MLIT KIND 3 daily stage mean. "
            "Timestamps are date-only (Japanese calendar day = JST day); "
            "interpreted as UTC midnight (T00:00:00Z) following the established pattern. "
            "No unit conversion: values are already in metres."
        ),
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
        native_unit="m3/s",
        timezone_handling="jst_to_utc",
        notes=(
            "MLIT KIND 6 hourly discharge. "
            "Timestamps in Japan Standard Time (JST = Asia/Tokyo = UTC+9); converted to UTC. "
            "No unit conversion: values are already in m³/s. "
            "Note: the MLIT website labels KIND 6 as 'Daily' but it provides HOURLY data."
        ),
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
        native_unit="m3/s",
        timezone_handling="date_only_utc_midnight",
        notes=(
            "MLIT KIND 7 daily discharge mean. "
            "Timestamps are date-only (Japanese calendar day = JST day); "
            "interpreted as UTC midnight (T00:00:00Z) following the established pattern. "
            "No unit conversion: values are already in m³/s."
        ),
    ),
)

EXPECTED_PRODUCT_IDS = frozenset(d.product_id for d in PRODUCT_DEFINITIONS)


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
) -> GeneratedJpMlitCatalogue:
    """Build catalogue from a fixture file (.json array or .csv of station rows)."""
    path = Path(fixture_path)
    rows = _read_json_fixture(path) if path.suffix.lower() == ".json" else _read_csv_fixture(path)
    return generate_catalogue(rows, catalogue_date=catalogue_date, generator_input="fixture")


def generate_catalogue_from_live(
    csv_path: Path | str,
    *,
    catalogue_date: date | None = None,
    verbose: bool = False,
) -> GeneratedJpMlitCatalogue:
    """Build a fully-enriched catalogue by calling SiteInfoDetail.exe once per station.

    Station IDs are read from the cached japan_sites.csv (the MLIT portal has no
    bulk-list API). For each ID, SiteInfoDetail.exe is called to retrieve:
    - station name (Japanese)
    - drainage area (流域面積, km²)
    - observation start date (観測開始時期)
    - WGS84 lat/lon (世界測地系)
    - zero-point elevation (零点高, metres)
    - water system, river name, manager, address

    This makes ~1030 HTTP requests and takes a few minutes. Run it once to produce
    the packaged catalogue artifacts; normal users read those offline.

    Rate limit: {_LIVE_REQUEST_DELAY_SECONDS}s between requests.
    """
    station_ids = _read_station_ids_from_csv(Path(csv_path))
    if not station_ids:
        raise FatalContractError(f"jp_mlit: no station IDs found in CSV: {csv_path}")

    try:
        from tqdm import tqdm  # type: ignore[import-untyped]

        iterator = tqdm(station_ids, desc="jp_mlit SiteInfoDetail", unit="station")
    except ImportError:
        print(f"jp_mlit live enrichment: fetching {len(station_ids)} stations (install tqdm for a progress bar)")
        iterator = iter(station_ids)  # type: ignore[assignment]

    enriched_rows: list[dict[str, object]] = []
    failed = 0

    for station_id in iterator:
        detail = _fetch_site_detail(station_id)
        enriched_rows.append({"gauge_id": station_id, **detail})
        time.sleep(_LIVE_REQUEST_DELAY_SECONDS)
        if detail.get("_fetch_error"):
            failed += 1

    if failed:
        print(f"Warning: {failed}/{len(station_ids)} stations had fetch errors (kept with None fields)")

    return generate_catalogue(
        enriched_rows,
        catalogue_date=catalogue_date,
        generator_input="live_siteinfo_detail",
    )


def generate_catalogue(
    station_rows: list[dict[str, object]],
    *,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedJpMlitCatalogue:
    effective_date = catalogue_date or date.today()
    products = build_products()
    stations = build_stations(station_rows, generator_input=generator_input)
    station_ids = stations["station_id"].to_list()
    station_products = build_station_products(
        station_ids=station_ids,
        catalogue_date=effective_date,
    )
    provider_info = build_provider_info(effective_date, generator_input=generator_input)
    validate_generated_catalogue(provider_info, products, stations, station_products)
    return GeneratedJpMlitCatalogue(
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
            "native_id": str(d.kind),
            "derived": False,
            "derivation_method": None,
            "metadata": _metadata_json(d.metadata),
        }
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(
    station_rows: list[dict[str, object]],
    *,
    generator_input: str = "fixture",
) -> StationCatalog:
    rows = list(_iter_station_rows(station_rows))
    if not rows:
        raise FatalContractError("jp_mlit: station build returned no rows")
    if generator_input == "live" and len(rows) < MIN_LIVE_STATIONS:
        raise FatalContractError(
            f"jp_mlit: catalogue returned only {len(rows)} stations "
            f"(expected ≥ {MIN_LIVE_STATIONS}); possible fetch failure"
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
            metadata = JpMlitStationProductMetadata(
                station_id=station_id,
                product_id=d.product_id,
                kind=d.kind,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=(
                    "Materialised as availability=unknown; "
                    "japan_sites.csv does not indicate per-KIND data availability."
                ),
            )
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
                    "availability": "unknown",
                    "availability_reason": AVAILABILITY_REASON,
                    "start_date": None,
                    "end_date": None,
                    "last_catalogue_check": catalogue_date,
                    "metadata": _metadata_json(metadata),
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
    metadata: dict[str, object] = {
        "dsp_url": DSP_URL,
        "site_info_url": SITE_INFO_URL,
        "generator_input": generator_input,
        "catalogue_source": "cached japan_sites.csv from legacy RivRetrieve-Python",
        "timestamp_convention": ("hourly_kinds_2_6=jst_to_utc; daily_kinds_3_7=date_only_utc_midnight"),
        "note": (
            "MLIT website labels KINDs 2 and 6 as 'Daily' but they provide HOURLY data. "
            "KINDs 3 and 7 provide true DAILY data."
        ),
    }
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


def write_catalogue(catalogue: GeneratedJpMlitCatalogue, out_dir: Path | str) -> None:
    output_path = Path(out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with (output_path / "provider.json").open("w", encoding="utf-8") as f:
        json.dump(catalogue.provider_info, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
    catalogue.products.write_parquet(output_path / "products.parquet")
    catalogue.stations.write_parquet(output_path / "stations.parquet")
    catalogue.station_products.write_parquet(output_path / "station_products.parquet")


# ---------------------------------------------------------------------------
# Station row iterator
# ---------------------------------------------------------------------------


def _iter_station_rows(station_rows: list[dict[str, object]]):  # type: ignore[return]
    """Yield one station catalogue row per input dict.

    Fixture and live-enriched rows both produce canonical identity and geometry.
    """
    seen: set[str] = set()
    for row in station_rows:
        if not isinstance(row, dict):
            continue
        station_id = _clean_text(row.get("gauge_id"))
        if station_id is None or station_id in seen:
            continue

        # Prefer WGS84 lat/lon from live enrichment; fall back to cached CSV values.
        lat = _to_float(row.get("latitude_wgs84")) or _to_float(row.get("latitude"))
        lon = _to_float(row.get("longitude_wgs84")) or _to_float(row.get("longitude"))
        if lat is None or lon is None:
            continue
        seen.add(station_id)

        yield {
            "provider_id": PROVIDER_ID,
            "station_id": station_id,
            "latitude": lat,
            "longitude": lon,
            "crs": "unknown",
        }


# ---------------------------------------------------------------------------
# Live enrichment — SiteInfoDetail.exe per station
# ---------------------------------------------------------------------------

_DMS_PATTERN = re.compile(r"北緯\s*(\d+)度(\d+)分(\d+)秒\s*東経\s*(\d+)度(\d+)分(\d+)秒")
_DRAIN_PATTERN = re.compile(r"([\d.]+)\s*km2")
_ELEV_PATTERN = re.compile(r"([-\d.]+)\s*m$")
_DIST_PATTERN = re.compile(r"([\d.]+)\s*km$")
_JP_DATE_PATTERN = re.compile(r"(\d{4})年(\d{2})月(\d{2})日")
_LABEL_VALUE_PATTERN = re.compile(r"<TD[^>]*>(.*?)</TD>\s*<TD[^>]*>(.*?)</TD>", re.DOTALL)


def _read_station_ids_from_csv(path: Path) -> list[str]:
    rows = _read_csv_fixture(path)
    ids: list[str] = []
    for row in rows:
        sid = _clean_text(row.get("gauge_id"))
        if sid and sid not in ids:
            ids.append(sid)
    return ids


def _fetch_site_detail(station_id: str) -> dict[str, object]:
    """Fetch SiteInfoDetail.exe for one station and return a dict of parsed fields.

    Returns an empty dict with _fetch_error=True on any network or parse failure
    so the caller can fall back to None fields rather than aborting the whole run.
    """
    url = f"{SITE_INFO_DETAIL_URL}?ID={station_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "http://www1.river.go.jp"})
        with urllib.request.urlopen(req, timeout=_LIVE_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
        html = raw.decode("euc-jp", errors="replace")
        return _parse_site_detail_html(html)
    except Exception:
        return {"_fetch_error": True}


def _parse_site_detail_html(html: str) -> dict[str, object]:
    """Extract station fields from a SiteInfoDetail.exe HTML response."""
    result: dict[str, object] = {}

    def first_td_after(label: str) -> str | None:
        m = re.search(
            re.escape(label) + r"</TD>\s*(?:<TD[^>]*>){1,3}(.*?)</TD>",
            html,
            re.DOTALL,
        )
        if not m:
            return None
        return re.sub(r"<[^>]+>", "", m.group(1)).strip() or None

    # Station name
    result["name"] = first_td_after("観測所名")
    # Observation type (水位流量 etc.)
    result["observation_type"] = first_td_after("観測項目")
    # Water system / river
    result["water_system_name"] = first_td_after("水系名")
    result["river_name"] = first_td_after("河川名")
    # Managing agency
    result["manager"] = first_td_after("観測所管理者名")
    # Station type code
    result["station_type_code"] = first_td_after("観測所種別")
    # Observation start date
    start_raw = first_td_after("観測開始時期")
    result["start_date"] = _jp_date_to_iso(start_raw) if start_raw else None
    # Address
    result["address"] = first_td_after("所在地")
    # Distance from river mouth
    dist_raw = first_td_after("河口または合流点からの距離")
    result["distance_from_mouth_km"] = _extract_float(_DIST_PATTERN, dist_raw)
    # WGS84 lat/lon (世界測地系 row)
    latlon_raw = first_td_after("世界測地系")
    if latlon_raw:
        lat, lon = _parse_dms(latlon_raw)
        result["latitude_wgs84"] = lat
        result["longitude_wgs84"] = lon
    else:
        result["latitude_wgs84"] = None
        result["longitude_wgs84"] = None
    # Drainage area (流域面積)
    drain_raw = first_td_after("流域面積")
    result["drainage_area_km2"] = _extract_float(_DRAIN_PATTERN, drain_raw)
    # Zero-point elevation (零点高)
    elev_raw = first_td_after("零点高")
    result["elevation_m"] = _extract_float(_ELEV_PATTERN, elev_raw)

    return result


def _parse_dms(text: str) -> tuple[float | None, float | None]:
    """Parse '北緯 44度04分29秒 東経 142度44分25秒' → (lat, lon) decimal degrees."""
    m = _DMS_PATTERN.search(text)
    if not m:
        return None, None
    lat_d, lat_m, lat_s, lon_d, lon_m, lon_s = (int(x) for x in m.groups())
    lat = lat_d + lat_m / 60.0 + lat_s / 3600.0
    lon = lon_d + lon_m / 60.0 + lon_s / 3600.0
    return lat, lon


def _jp_date_to_iso(text: str) -> str | None:
    """Parse '1970年11月01日' → '1970-11-01'."""
    m = _JP_DATE_PATTERN.search(text)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _extract_float(pattern: re.Pattern[str], text: str | None) -> float | None:
    if not text:
        return None
    m = pattern.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# CSV reader
# ---------------------------------------------------------------------------


def _read_json_fixture(path: Path) -> list[dict[str, object]]:
    try:
        with path.open(encoding="utf-8") as f:
            value = json.load(f)
    except OSError as exc:
        raise FatalContractError(f"Unable to read jp_mlit JSON fixture: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FatalContractError(f"jp_mlit JSON fixture is not valid JSON: {path}") from exc
    if not isinstance(value, list):
        raise FatalContractError(f"jp_mlit JSON fixture must be a JSON array: {path}")
    return [dict(row) for row in value if isinstance(row, dict)]


def _read_csv_fixture(path: Path) -> list[dict[str, object]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except OSError as exc:
        raise FatalContractError(f"Unable to read jp_mlit fixture CSV: {path}") from exc


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip('"')
    if not text or text.lower() in ("nan", "none", "null"):
        return None
    return text


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().strip('"'))
    except (TypeError, ValueError):
        return None


def _metadata_json(
    model: JpMlitProductMetadata | JpMlitStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the packaged jp_mlit catalogue artifacts.\n\n"
            "Two modes:\n"
            "  --fixture PATH   Fast, offline. Uses only the cached japan_sites.csv "
            "(gauge_id, lat, lon). No station names or drainage areas.\n"
            "  --live PATH      Slow, online. Uses japan_sites.csv for IDs, then calls "
            "SiteInfoDetail.exe once per station (~1030 requests, ~5 min) to enrich "
            "with real names, drainage areas, start dates, river names, etc."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--fixture",
        type=Path,
        metavar="CSV_OR_JSON",
        help="Path to japan_sites.csv (or a JSON fixture). Offline, no enrichment.",
    )
    source.add_argument(
        "--live",
        type=Path,
        metavar="CSV",
        help=(
            "Path to japan_sites.csv. Fetches SiteInfoDetail.exe for each station ID "
            "to enrich name, drainage area, start date, etc. Takes ~5 minutes."
        ),
    )
    parser.add_argument("--out", type=Path, required=True, help="Output directory for catalogue artifacts.")
    parser.add_argument("--catalogue-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--verbose", action="store_true", help="Print progress for every station (--live only).")
    args = parser.parse_args(argv)

    if args.live:
        catalogue = generate_catalogue_from_live(
            args.live,
            catalogue_date=args.catalogue_date,
            verbose=args.verbose,
        )
    else:
        catalogue = generate_catalogue_from_fixture(args.fixture, catalogue_date=args.catalogue_date)
    write_catalogue(catalogue, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

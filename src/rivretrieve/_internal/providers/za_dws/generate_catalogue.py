from __future__ import annotations

import argparse
import io
import json
import re
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from pypdf import PdfReader

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
from rivretrieve._internal.providers.za_dws.metadata import (
    ZaDwsProductMetadata,
    ZaDwsStationProductMetadata,
)

PROVIDER_ID = "za_dws"
PROVIDER_NAME = "Department of Water and Sanitation — Verified Hydrology (DWS, South Africa)"

CATALOGUE_URL = "https://www.dws.gov.za/hydrology/Verified/HyCatalogue.aspx"
DATA_URL = "https://www.dws.gov.za/Hydrology/Verified/HyData.aspx"
CATALOGUE_BASE = "https://www.dws.gov.za/hydrology/Verified/"

AVAILABILITY_NOTE = (
    "Materialised as availability=unknown; the DWS station catalogue does not "
    "expose which data variables are available per station."
)
AVAILABILITY_SOURCE = "provider_station_catalogue_assumption"

# Minimum stations expected from a live scrape. 2863 stations were observed
# across 8 WMA PDFs in June 2026; use 500 as a conservative guard.
MIN_LIVE_STATIONS = 500

# Regex matching a DWS station row inside a WMA River PDF.
# Format: STATION_CODE  DESCRIPTION  LAT_DMS  LON_DMS  DRAINAGE_REGION  AREA
_STATION_PATTERN = re.compile(
    r"^([A-Z][0-9][A-Z][0-9]{3})\s+(.+?)\s+"
    r"(\d{2}:\d{2}:\d{2})\s+(\d{2}:\d{2}:\d{2})\s+"
    r"([A-Z0-9]{2,})\s+([0-9]+(?:\.[0-9]+)?)"
)

_PDF_LINK_PATTERN = re.compile(r'href=["\']([^"\']*_River[^"\']*\.pdf)["\']', re.IGNORECASE)

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
    data_type: str
    value_column: str
    native_unit: str
    chunk_years: int
    notes: str

    @property
    def metadata(self) -> ZaDwsProductMetadata:
        return ZaDwsProductMetadata(
            data_type=self.data_type,
            value_column=self.value_column,
            native_unit=self.native_unit,
            canonical_unit=self.canonical_unit,
            chunk_years=self.chunk_years,
            notes=self.notes,
        )


PRODUCT_DEFINITIONS: tuple[ProductDefinition, ...] = (
    ProductDefinition(
        product_id="discharge_daily_mean",
        observed_property="discharge",
        frequency="daily",
        statistic="mean",
        period_type="interval",
        period_anchor="provider_defined",
        canonical_unit="m3/s",
        data_type="Daily",
        value_column="D_AVG_FR",
        native_unit="m3/s",
        chunk_years=20,
        notes=(
            "DWS daily average flow rate (D_AVG_FR column) in m³/s. "
            "Retrieved from DataType=Daily endpoint in 20-year windows. "
            f"{_TIMEZONE_NOTE}"
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
        data_type="Point",
        value_column="COR_FLOW",
        native_unit="m3/s",
        chunk_years=1,
        notes=(
            "DWS corrected flow (COR_FLOW column) in m³/s, derived from COR_LEVEL via rating curve. "
            "Retrieved from DataType=Point endpoint in 1-year windows. "
            f"{_TIMEZONE_NOTE}"
        ),
    ),
    ProductDefinition(
        product_id="stage_instantaneous",
        observed_property="stage",
        frequency="irregular",
        statistic="instantaneous",
        period_type="instant",
        period_anchor="instant",
        canonical_unit="m",
        data_type="Point",
        value_column="COR_LEVEL",
        native_unit="m",
        chunk_years=1,
        notes=(
            "DWS corrected level (COR_LEVEL column) in metres. "
            "Retrieved from DataType=Point endpoint in 1-year windows. "
            f"{_TIMEZONE_NOTE}"
        ),
    ),
)


def generate_catalogue_from_fixture(
    fixture_path: Path | str,
    *,
    catalogue_date: date | None = None,
) -> GeneratedZaDwsCatalogue:
    raw = _read_fixture_json(Path(fixture_path))
    return generate_catalogue(raw, catalogue_date=catalogue_date, generator_input="fixture")


def generate_catalogue_from_live(
    *,
    catalogue_date: date | None = None,
) -> GeneratedZaDwsCatalogue:
    raw = _fetch_live_stations()
    return generate_catalogue(raw, catalogue_date=catalogue_date, generator_input="live")


def generate_catalogue(
    raw_stations: list[dict[str, object]],
    *,
    catalogue_date: date | None = None,
    generator_input: str = "fixture",
) -> GeneratedZaDwsCatalogue:
    effective_date = catalogue_date or date.today()
    products = build_products()
    stations = build_stations(raw_stations, generator_input=generator_input)
    station_ids = stations["station_id"].to_list()
    station_products = build_station_products(station_ids=station_ids, catalogue_date=effective_date)
    provider_info = build_provider_info(effective_date, generator_input=generator_input)
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
            "derived": False,
            "derivation_method": None,
            "metadata": _metadata_json(d.metadata),
        }
        for d in PRODUCT_DEFINITIONS
    ]
    return pl.DataFrame(rows, schema=PRODUCT_CATALOG_SCHEMA.polars_schema).sort("product_id")


def build_stations(
    raw_stations: list[dict[str, object]],
    *,
    generator_input: str = "fixture",
) -> StationCatalog:
    rows = list(_iter_station_rows(raw_stations))
    if not rows:
        raise FatalContractError("za_dws: station build returned no rows")
    if generator_input == "live" and len(rows) < MIN_LIVE_STATIONS:
        raise FatalContractError(
            f"za_dws: live catalogue returned only {len(rows)} stations "
            f"(expected >= {MIN_LIVE_STATIONS}); possible fetch or parse failure"
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
            metadata = ZaDwsStationProductMetadata(
                station_id=station_id,
                product_id=d.product_id,
                availability_source=AVAILABILITY_SOURCE,
                availability_note=AVAILABILITY_NOTE,
            )
            rows.append(
                {
                    "provider_id": PROVIDER_ID,
                    "station_id": station_id,
                    "product_id": d.product_id,
                    "availability": "unknown",
                    "availability_reason": "DWS station catalogue does not expose per-variable availability",
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
        "data_url": DATA_URL,
        "catalogue_url": CATALOGUE_URL,
        "station_catalogue_source": "WMA River PDF files scraped from HyCatalogue.aspx",
        "variable_code": "100.00",
        "timezone_note": _TIMEZONE_NOTE,
        "generator_input": generator_input,
    }
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
        "metadata": json.dumps(metadata, sort_keys=True, separators=(",", ":")),
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


# ---------------------------------------------------------------------------
# Station row iterator
# ---------------------------------------------------------------------------


def _iter_station_rows(raw_stations: list[dict[str, object]]):  # type: ignore[return]
    seen: set[str] = set()
    for raw in raw_stations:
        if not isinstance(raw, dict):
            continue

        station_id = _clean_text(raw.get("station_id"))
        if station_id is None or station_id in seen:
            continue

        lat = _to_float(raw.get("latitude"))
        lon = _to_float(raw.get("longitude"))
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
# Live station fetchers (maintainer-only, PDF scraping)
# ---------------------------------------------------------------------------


def _fetch_live_stations() -> list[dict[str, object]]:
    """Scrape all WMA River PDFs from HyCatalogue.aspx and parse station rows."""
    pdf_urls = _fetch_pdf_urls()
    if not pdf_urls:
        raise FatalContractError("za_dws: no *_River.pdf links found on HyCatalogue.aspx")

    all_stations: list[dict[str, object]] = []
    for url in pdf_urls:
        try:
            stations = _parse_pdf_stations(url)
            all_stations.extend(stations)
        except FatalContractError:
            raise
        except Exception as exc:
            raise FatalContractError(f"za_dws: failed to parse PDF {url}: {exc}") from exc

    return all_stations


def _fetch_pdf_urls() -> list[str]:
    """Fetch HyCatalogue.aspx and return absolute URLs for all WMA River PDFs."""
    req = urllib.request.Request(
        CATALOGUE_URL,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
    except OSError as exc:
        raise FatalContractError(f"za_dws: failed to fetch HyCatalogue.aspx: {exc}") from exc

    hrefs = _PDF_LINK_PATTERN.findall(html)
    return [h if h.startswith("http") else CATALOGUE_BASE + h.lstrip("/") for h in hrefs]


def _parse_pdf_stations(pdf_url: str) -> list[dict[str, object]]:
    """Download and parse one WMA River PDF into station dicts."""
    req = urllib.request.Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            pdf_bytes = r.read()
    except OSError as exc:
        raise FatalContractError(f"za_dws: failed to download PDF {pdf_url}: {exc}") from exc

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        all_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise FatalContractError(f"za_dws: failed to parse PDF {pdf_url}: {exc}") from exc

    stations: list[dict[str, object]] = []
    for line in all_text.split("\n"):
        m = _STATION_PATTERN.match(line.strip())
        if not m:
            continue
        station_id, _, lat_dms, lon_dms, _, _ = m.groups()
        lat = _dms_to_dd(lat_dms, positive=False)
        lon = _dms_to_dd(lon_dms, positive=True)
        if lat is None or lon is None:
            continue
        stations.append(
            {
                "station_id": station_id,
                "latitude": lat,
                "longitude": lon,
            }
        )
    return stations


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
    packaged_catalogue_artifact_from_components(provider_info, products, stations, station_products, on_issue="raise")


# ---------------------------------------------------------------------------
# Coordinate / text helpers
# ---------------------------------------------------------------------------


def _dms_to_dd(dms: str, *, positive: bool) -> float | None:
    """Convert dd:mm:ss string to decimal degrees.

    South African latitude is always south (negative); longitude is always east (positive).
    """
    parts = dms.split(":")
    if len(parts) != 3:
        return None
    try:
        d, m, s = float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError:
        return None
    dd = d + m / 60.0 + s / 3600.0
    return dd if positive else -dd


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", "null"):
        return None
    return text


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metadata_json(
    model: ZaDwsProductMetadata | ZaDwsStationProductMetadata,
) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the packaged za_dws catalogue artifacts.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Path to a stations JSON fixture.")
    source.add_argument("--live", action="store_true", help="Scrape the live DWS station PDFs.")
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

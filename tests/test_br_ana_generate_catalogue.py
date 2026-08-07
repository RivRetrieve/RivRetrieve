"""Catalogue-generation tests retained after archiving BR ANA observations."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
)
from rivretrieve._internal.providers.br_ana.generate_catalogue import generate_catalogue_from_fixture

_METADATA_FIXTURE = Path(__file__).parent / "test_data" / "br_ana_metadata.json"


def test_generate_catalogue_station_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.stations.height == 2


def test_generate_catalogue_product_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    # discharge_daily_mean, stage_daily_mean, discharge_instantaneous,
    # stage_instantaneous, water_temperature_instantaneous
    assert cat.products.height == 5


def test_generate_catalogue_station_products_count() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    # 2 stations × 5 products = 10
    assert cat.station_products.height == 10


def test_generate_catalogue_station_fields() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    row = cat.stations.filter(pl.col("station_id") == "12345000")
    assert row.height == 1
    assert row["crs"][0] == "unknown"


def test_generate_catalogue_filters_no_coord_station() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.stations["station_id"].to_list())
    assert "99999999" not in ids


def test_generate_catalogue_filters_pure_pluviometric_station() -> None:
    """Stations with no discharge/level/water-quality flag set are out of scope."""
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.stations["station_id"].to_list())
    assert "77777000" not in ids


def test_generate_catalogue_keeps_stations_with_any_relevant_type_flag() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    ids = set(cat.stations["station_id"].to_list())
    # 12345000: discharge + level; 60435000: level only — both relevant to our products.
    assert {"12345000", "60435000"} <= ids


def test_fixture_build_uses_exact_reduced_carriers() -> None:
    cat = generate_catalogue_from_fixture(_METADATA_FIXTURE)
    assert cat.products.schema == PRODUCT_CATALOG_SCHEMA.polars_schema
    assert cat.station_products.schema == STATION_PRODUCT_CATALOG_SCHEMA.polars_schema
    assert tuple(cat.provider_info) == tuple(PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)


def _frame_content_sha256(frame: pl.DataFrame) -> str:
    def normalized(value: object) -> object:
        return value.isoformat() if isinstance(value, date | datetime) else value

    payload = {
        "columns": frame.columns,
        "rows": [[normalized(value) for value in row] for row in frame.iter_rows()],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def test_projected_national_artifacts_have_pinned_complete_content() -> None:
    catalogue = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/br_ana/catalogue"
    assert hashlib.sha256((catalogue / "provider.json").read_bytes()).hexdigest() == (
        "96ed829f389b0079c1194133af94ad3ca7f6c07aecaa5a5c8a8f27b4fbfde1f2"
    )
    assert _frame_content_sha256(pl.read_parquet(catalogue / "products.parquet")) == (
        "eb464a090e8727a2d4982f3cb2d330893830cfe9f28efa4baf05f77ceef6cb11"
    )
    assert _frame_content_sha256(pl.read_parquet(catalogue / "stations.parquet")) == (
        "aa9428890df6b35f13e80a9de5e1de44e0c01dbd298f10ab9f057c511c898666"
    )
    assert _frame_content_sha256(pl.read_parquet(catalogue / "station_products.parquet")) == (
        "d6352179f8e2d88e20a5366e9243db608a778560249f1de2e364d6bf5e7aa321"
    )

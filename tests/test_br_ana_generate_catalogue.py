"""Catalogue-generation tests retained after archiving BR ANA observations."""

from __future__ import annotations

import json
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


def test_projected_national_artifacts_have_pinned_complete_content() -> None:
    catalogue = Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/br_ana/catalogue"
    provider_info = json.loads((catalogue / "provider.json").read_text(encoding="utf-8"))
    assert provider_info["catalogue_version"] is None
    assert pl.read_parquet(catalogue / "products.parquet").is_empty()
    assert pl.read_parquet(catalogue / "stations.parquet").is_empty()
    assert pl.read_parquet(catalogue / "station_products.parquet").is_empty()
    provenance = json.loads((catalogue / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["native_table"] is None
    assert {statement["kind"] for source in provenance["source_records"] for statement in source["statements"]} == {
        "license"
    }
    assert len(provenance["fact_bindings"]) == 2
    authored = provenance["fact_bindings"][0]
    assert authored["fact_group"] == "rivretrieve_authored_provider_registration"
    assert authored["transformation"]["kind"] == "authored_constant"
    assert {item["reason"] for item in provenance["withheld_facts"]} == {"no_acquisition_record_established"}

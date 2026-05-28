from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from rivretrieve._internal.catalogues.artifact import packaged_catalogue_artifact_from_components
from rivretrieve._internal.catalogues.schemas import (
    PRODUCT_CATALOG_SCHEMA,
    PROVIDER_INFO_CATALOG_SCHEMA,
    STATION_CATALOG_SCHEMA,
    STATION_PRODUCT_CATALOG_SCHEMA,
    validate_catalogue,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.ch_foen import generate_catalogue

FIXTURE_PATH = Path("tests/test_data/switzerland_metadata_locations.json")
CATALOGUE_DATE = date(2026, 5, 28)


def test_ch_foen_generator_uses_committed_fixture_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_live_json(url: str) -> object:
        raise AssertionError(f"unexpected live request to {url}")

    monkeypatch.setattr(generate_catalogue, "_read_live_json", fail_live_json)

    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )

    assert catalogue.stations.height == 246


def test_ch_foen_generator_station_count_matches_legacy_fixture() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )

    assert catalogue.stations.height == 246


def test_ch_foen_generator_station_2016_brugg_matches_legacy_fixture() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )

    row = catalogue.stations.filter(pl.col("station_id") == "2016").row(0, named=True)
    metadata = json.loads(row["metadata"])
    assert row["name"] == "Brugg"
    assert metadata["water_body_name"] == "Aare"
    assert row["latitude"] == 47.4825
    assert row["longitude"] == 8.1949


def test_ch_foen_generator_handles_nullable_elevation_and_drainage_area() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )

    assert catalogue.stations["elevation_m"].null_count() == 246
    assert catalogue.stations["drainage_area_km2"].null_count() == 246
    validate_catalogue(catalogue.stations, STATION_CATALOG_SCHEMA, on_issue="raise")


def test_ch_foen_generator_artifacts_validate_against_all_catalogue_schemas() -> None:
    catalogue = generate_catalogue.generate_catalogue_from_fixture(
        FIXTURE_PATH,
        catalogue_date=CATALOGUE_DATE,
    )
    provider_info = pl.DataFrame([catalogue.provider_info], schema=PROVIDER_INFO_CATALOG_SCHEMA.polars_schema)

    validate_catalogue(provider_info, PROVIDER_INFO_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.products, PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.stations, STATION_CATALOG_SCHEMA, on_issue="raise")
    validate_catalogue(catalogue.station_products, STATION_PRODUCT_CATALOG_SCHEMA, on_issue="raise")
    packaged_catalogue_artifact_from_components(
        catalogue.provider_info,
        catalogue.products,
        catalogue.stations,
        catalogue.station_products,
        on_issue="raise",
    )


def test_ch_foen_generator_rejects_unknown_variable_code() -> None:
    unknown = (
        generate_catalogue.ProductDefinition(
            legacy_variable="UNKNOWN_VARIABLE",
            product_id="discharge_daily_mean",
            observed_property="discharge",
            frequency="daily",
            statistic="mean",
            period_type="interval",
            period_anchor="provider_defined",
            unit="m3/s",
            parameters=("flow",),
            preferred_parameter="flow",
            fallback_parameter=None,
            aggregate_daily=True,
            notes=None,
        ),
    )

    with pytest.raises(FatalContractError, match="unknown"):
        generate_catalogue.build_products(unknown)


def test_ch_foen_generator_rejects_corrupt_fixture(tmp_path: Path) -> None:
    corrupt_fixture = tmp_path / "corrupt.json"
    corrupt_fixture.write_text('{"payload":[]}', encoding="utf-8")

    with pytest.raises(FatalContractError, match="payload"):
        generate_catalogue.generate_catalogue_from_fixture(corrupt_fixture)


def test_ch_foen_generator_writes_artifacts(tmp_path: Path) -> None:
    output_path = tmp_path / "catalogue"

    result = generate_catalogue.main(
        [
            "--fixture",
            str(FIXTURE_PATH),
            "--out",
            str(output_path),
            "--catalogue-date",
            CATALOGUE_DATE.isoformat(),
        ]
    )

    assert result == 0
    assert (output_path / "provider.json").is_file()
    assert (output_path / "products.parquet").is_file()
    assert (output_path / "stations.parquet").is_file()
    assert (output_path / "station_products.parquet").is_file()

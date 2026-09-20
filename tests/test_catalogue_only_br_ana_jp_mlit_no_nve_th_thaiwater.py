"""Catalogue-only contracts and retained source evidence."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.registry import _registry
from tests._catalogue import catalogue_path, catalogue_reader, provider_info

CATALOGUE_ONLY_PROVIDERS = (
    (
        "za_dws",
        2905,
        3,
        8715,
        {"discharge_daily_mean", "discharge_instantaneous", "stage_instantaneous"},
        "Department of Water and Sanitation — Verified Hydrology (DWS, South Africa)",
        "2026-08-02",
        {"unknown"},
    ),
)
DEFERRED_CATALOGUE_MODULE_FILES = {"__init__.py", "generate_catalogue.py", "issue_codes.py"}
DWS_CATALOGUE_MODULE_FILES = {"__init__.py", "generate_catalogue.py", "origins.py", "catalogue_series.py"}
ENROLLED_CATALOGUE_MODULE_FILES = {
    "za_dws": DWS_CATALOGUE_MODULE_FILES,
}


@pytest.mark.parametrize(
    (
        "provider_id",
        "station_count",
        "product_count",
        "station_product_count",
        "product_ids",
        "provider_name",
        "catalogue_version",
        "availability",
    ),
    CATALOGUE_ONLY_PROVIDERS,
)
def test_catalogue_only_provider_remains_discoverable_and_readable(
    provider_id: str,
    station_count: int,
    product_count: int,
    station_product_count: int,
    product_ids: set[str],
    provider_name: str,
    catalogue_version: str | None,
    availability: set[str],
) -> None:
    assert provider_id in rr.providers().get_column("provider_id").to_list()
    reader = catalogue_reader(provider_id)
    info = provider_info(provider_id)
    stations_result = reader.read_stations()
    products_result = reader.read_products()
    station_products_result = reader.read_station_products()
    for result in (stations_result, products_result, station_products_result):
        assert hasattr(result, "data")
        assert hasattr(result, "provenance")
        assert hasattr(result, "issues")
    stations = stations_result.data
    products = products_result.data
    station_products = station_products_result.data
    assert info.provider_id == provider_id
    assert info.name == provider_name
    if catalogue_version is None:
        assert info.catalogue_version is None
    else:
        assert str(info.catalogue_version) == catalogue_version
    assert stations.height == station_count
    if station_count:
        assert stations["crs"].unique().to_list() == ["unknown"]
    else:
        assert stations.is_empty()
    assert products.height == product_count
    assert set(products["product_id"].to_list()) == product_ids
    if product_count:
        assert set(products["provider_id"].to_list()) == {provider_id}
    else:
        assert products.is_empty()
    assert station_products.height == station_product_count
    assert set(station_products["availability"].cast(str).to_list()) == availability

    global_products = rr.products(provider=provider_id)
    assert len(global_products) == product_count
    assert set(global_products) == product_ids


@pytest.mark.parametrize(
    (
        "provider_id",
        "station_count",
        "product_count",
        "station_product_count",
        "product_ids",
        "provider_name",
        "catalogue_version",
        "availability",
    ),
    CATALOGUE_ONLY_PROVIDERS,
)
def test_catalogue_only_provider_directory_retains_declared_surface(
    provider_id: str,
    station_count: int,
    product_count: int,
    station_product_count: int,
    product_ids: set[str],
    provider_name: str,
    catalogue_version: str | None,
    availability: set[str],
) -> None:
    reader = catalogue_reader(provider_id)
    info = provider_info(provider_id)
    stations = reader.read_stations().data
    products = reader.read_products().data
    station_products = reader.read_station_products().data
    assert info.provider_id == provider_id
    assert info.name == provider_name
    if catalogue_version is None:
        assert info.catalogue_version is None
    else:
        assert str(info.catalogue_version) == catalogue_version
    assert stations.height == station_count
    if station_count:
        assert stations["crs"].unique().to_list() == ["unknown"]
    else:
        assert stations.is_empty()
    assert products.height == product_count
    assert set(products["product_id"].to_list()) == product_ids
    if product_count:
        assert set(products["provider_id"].to_list()) == {provider_id}
    else:
        assert products.is_empty()
    assert station_products.height == station_product_count
    assert set(station_products["availability"].cast(str).to_list()) == availability
    provider_directory = catalogue_path(provider_id).parent
    assert set(ENROLLED_CATALOGUE_MODULE_FILES) == {row[0] for row in CATALOGUE_ONLY_PROVIDERS}
    expected_module_files = ENROLLED_CATALOGUE_MODULE_FILES[provider_id]
    assert {path.name for path in provider_directory.glob("*.py")} == expected_module_files | {"declaration.py"}
    assert catalogue_path(provider_id).exists()
    artifact_names = {"provider.json", "stations.parquet", "products.parquet", "station_products.parquet"}
    if provider_id in {"br_ana", "jp_mlit", "no_nve"}:
        artifact_names.update(
            {
                "provenance.json",
                "provenance_facts.parquet",
                "provenance_acquisitions.parquet",
                "provenance_bindings.parquet",
                "provenance_binding_facts.parquet",
                "provenance_external_inputs.parquet",
                "format.json",
                "source_series.json",
                "series_claims.parquet",
            }
        )
    for artifact_name in artifact_names:
        assert (catalogue_path(provider_id) / artifact_name).exists()


@pytest.mark.parametrize("provider_id", [row[0] for row in CATALOGUE_ONLY_PROVIDERS])
def test_catalogue_only_provider_rejects_observation_retrieval(provider_id: str) -> None:
    rr.providers()
    with pytest.raises(ObservationsUnavailableError, match=f"Provider {provider_id} has no observations registered"):
        _registry.get(provider_id).observations(stations="unused", products="unused", start=None, end=None)


def test_no_nve_packaged_availability_is_certified() -> None:
    station_products = catalogue_reader("no_nve").read_station_products().data
    assert station_products.height == 44_118
    assert set(station_products["availability"].cast(str)) == {"available", "unavailable"}


def test_jp_mlit_packaged_source_coordinates_are_adopted() -> None:
    stations = catalogue_reader("jp_mlit").read_stations().data
    expected = {
        "302011282228100": (37.415277777777774, 140.48333333333332),
        "302011282218050": (37.81111111111111, 140.4958333333333),
        "308011288805010": (33.78333333333333, 132.8738888888889),
    }
    assert "307051287711040" not in stations["station_id"].to_list()
    assert stations["crs"].unique().to_list() == ["unknown"]
    for station_id, coordinates in expected.items():
        row = stations.filter(pl.col("station_id") == station_id)
        assert row.select("latitude", "longitude").row(0) == coordinates


def test_brazil_verification_evidence_is_available() -> None:
    evidence = Path(__file__).parent / "recordings" / "br_ana"
    assert (evidence / "daily-public-live-verification.json").is_file()
    assert (evidence / "public-live-verification.json").is_file()
    assert (evidence / "daily-independent-expectations.json").is_file()
    assert (evidence / "detailed-candidate-field-summary.json").is_file()


def test_active_catalogue_fixtures_remain_available() -> None:
    fixture_dir = Path(__file__).parent / "test_data"
    for fixture_name in (
        "br_ana_metadata.json",
        "jp_mlit_metadata.json",
        "no_nve_metadata.json",
        "th_thaiwater_metadata.json",
    ):
        assert (fixture_dir / fixture_name).is_file()

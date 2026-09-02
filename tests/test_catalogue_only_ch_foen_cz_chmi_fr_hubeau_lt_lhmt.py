from __future__ import annotations

from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.registry import _registry
from tests._catalogue import catalogue_path, catalogue_reader, provider_info

CATALOGUE_ONLY_PROVIDERS = (
    (
        "ch_foen",
        246,
        3,
        738,
        {
            "discharge_instantaneous",
            "stage_instantaneous",
            "water_temperature_instantaneous",
        },
        "Swiss Federal Office for the Environment FOEN / BAFU",
        {"unknown"},
        {"unknown"},
    ),
    (
        "fr_hubeau",
        0,
        6,
        0,
        {
            "discharge_daily_max",
            "discharge_daily_mean",
            "discharge_instantaneous",
            "stage_daily_max",
            "stage_instantaneous",
            "water_temperature_instantaneous",
        },
        "Hubeau / SCHAPI — French national hydrometric network",
        set(),
        set(),
    ),
)
ENROLLED_CATALOGUE_MODULE_FILES = {
    "ch_foen": {"__init__.py", "generate_catalogue.py", "issue_codes.py", "origins.py"},
    "fr_hubeau": {"__init__.py", "generate_catalogue.py", "issue_codes.py", "origins.py"},
}
REFERENCE_ROOT = Path(__file__).parents[1] / "reference" / "legacy_observations"


@pytest.mark.parametrize(
    (
        "provider_id",
        "station_count",
        "product_count",
        "station_product_count",
        "product_ids",
        "provider_name",
        "availability",
        "expected_crs",
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
    availability: set[str],
    expected_crs: set[str],
) -> None:
    assert provider_id in rr.providers()

    reader = catalogue_reader(provider_id)
    info = provider_info(provider_id)
    stations = reader.read_stations().data
    products = reader.read_products().data
    station_products = reader.read_station_products().data
    assert info.provider_id == provider_id
    assert info.name == provider_name
    assert stations.height == station_count
    assert set(stations["crs"].to_list()) == expected_crs
    assert products.height == product_count
    assert set(products["product_id"].to_list()) == product_ids
    assert set(products["provider_id"].to_list()) == {provider_id}
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
        "availability",
        "expected_crs",
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
    availability: set[str],
    expected_crs: set[str],
) -> None:
    reader = catalogue_reader(provider_id)

    info = provider_info(provider_id)
    stations = reader.read_stations().data
    products = reader.read_products().data
    station_products = reader.read_station_products().data
    assert info.provider_id == provider_id
    assert info.name == provider_name
    assert stations.height == station_count
    assert set(stations["crs"].to_list()) == expected_crs
    assert products.height == product_count
    assert set(products["product_id"].to_list()) == product_ids
    assert set(products["provider_id"].to_list()) == {provider_id}
    assert station_products.height == station_product_count
    assert set(station_products["availability"].cast(str).to_list()) == availability
    provider_directory = catalogue_path(provider_id).parent
    assert set(ENROLLED_CATALOGUE_MODULE_FILES) == {row[0] for row in CATALOGUE_ONLY_PROVIDERS}
    expected_module_files = ENROLLED_CATALOGUE_MODULE_FILES[provider_id]
    assert {path.name for path in provider_directory.glob("*.py")} == expected_module_files | {"declaration.py"}
    assert catalogue_path(provider_id).exists()
    for artifact_name in (
        "provider.json",
        "stations.parquet",
        "products.parquet",
        "station_products.parquet",
    ):
        assert (catalogue_path(provider_id) / artifact_name).exists()


def test_readme_presents_ch_foen_as_catalogue_only() -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text()

    assert "provider.observations(" not in readme
    assert 'provider="ch_foen"' not in readme
    assert "`ch_foen` currently provides catalogue data only." in readme


def test_fr_hubeau_generator_is_independent_of_retired_observation_transform() -> None:
    from rivretrieve._internal.providers.fr_hubeau import generate_catalogue

    assert {definition.product_id for definition in generate_catalogue.HYDRO_PRODUCT_DEFS} == {
        "discharge_daily_max",
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_daily_max",
        "stage_instantaneous",
    }
    assert {definition.product_id for definition in generate_catalogue.TEMP_PRODUCT_DEFS} == {
        "water_temperature_instantaneous"
    }


@pytest.mark.parametrize("provider_id", [row[0] for row in CATALOGUE_ONLY_PROVIDERS])
def test_catalogue_only_provider_rejects_observation_retrieval(provider_id: str) -> None:
    rr.providers()
    with pytest.raises(
        ObservationsUnavailableError,
        match=rf"Provider {provider_id} has no observations registered",
    ):
        _registry.get(provider_id).observations(
            stations="not-consulted",
            products="not-consulted",
            start=None,
            end="2020-01-02",
        )


def test_ch_foen_has_origins_and_no_metadata_module() -> None:
    provider_directory = catalogue_path("ch_foen").parent

    assert (provider_directory / "origins.py").is_file()
    assert not (provider_directory / "metadata.py").exists()


def test_reference_tree_preserves_ch_foen_fetch_evidence() -> None:
    client = REFERENCE_ROOT / "ch_foen" / "source" / "observation_client.py"
    assert "https://influx.konzept.space/api/v2/query?org=api.existenz.ch" in client.read_text()


def test_reference_fixtures_are_colocated_and_active_catalogue_fixtures_remain() -> None:
    expected_source_files = {
        "ch_foen": {
            "issue_codes.py",
            "module.py",
            "observation_client.py",
            "parser.py",
            "query.py",
            "raw_payload.py",
            "retrieval.py",
            "transform.py",
        },
        "fr_hubeau": {
            "issue_codes.py",
            "module.py",
            "observation_client.py",
            "parser.py",
            "retrieval.py",
            "transform.py",
        },
    }
    for provider_id, source_names in expected_source_files.items():
        source_dir = REFERENCE_ROOT / provider_id / "source"
        assert {path.name for path in source_dir.iterdir()} == source_names

    expected = {
        "ch_foen": {
            "switzerland_metadata_locations.json",
            "switzerland_2206_discharge_20250101.csv",
            "switzerland_2282_stage_20250101.csv",
            "switzerland_2016_temperature_20200101.csv",
        },
        "fr_hubeau": {
            "fr_hubeau_metadata.json",
            "fr_hubeau_temp_stations.json",
            "fr_hubeau_O0050010_QmnJ_2020.json",
            "fr_hubeau_O0050010_obs_tr_H.json",
            "fr_hubeau_T123456001_temperature.json",
        },
    }
    for provider_id, fixture_names in expected.items():
        fixture_dir = REFERENCE_ROOT / provider_id / "tests" / "test_data"
        assert {path.name for path in fixture_dir.iterdir()} == fixture_names
        if provider_id == "ch_foen":
            for fixture_name in fixture_names:
                if fixture_name.endswith(".csv"):
                    fixture_path = fixture_dir / fixture_name
                    assert fixture_path.is_file()
                    assert fixture_path.stat().st_size > 0

    active_fixture_dir = Path(__file__).parent / "test_data"
    for fixture_name in (
        "switzerland_metadata_locations.json",
        "cz_chmi_metadata.json",
        "fr_hubeau_metadata.json",
        "fr_hubeau_temp_stations.json",
        "lithuania_metadata_stations.json",
    ):
        assert (active_fixture_dir / fixture_name).is_file()

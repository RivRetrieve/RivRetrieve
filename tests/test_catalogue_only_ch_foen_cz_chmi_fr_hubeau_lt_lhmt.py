from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError

CATALOGUE_ONLY_PROVIDERS = (
    (
        "ch_foen",
        246,
        6,
        1476,
        "Switzerland",
        {
            "discharge_daily_mean",
            "discharge_instantaneous",
            "stage_daily_mean",
            "stage_instantaneous",
            "water_temperature_daily_mean",
            "water_temperature_instantaneous",
        },
        "Swiss Federal Office for the Environment FOEN / BAFU",
        {"unknown"},
        ("2016", "Brugg"),
    ),
    (
        "cz_chmi",
        831,
        5,
        4155,
        "Czech Republic",
        {
            "discharge_daily_mean",
            "discharge_instantaneous",
            "stage_daily_mean",
            "stage_instantaneous",
            "water_temperature_daily_mean",
        },
        "Czech Hydrometeorological Institute (CHMI) Open Data",
        {"unknown"},
        None,
    ),
    (
        "fr_hubeau",
        7289,
        6,
        32969,
        "France",
        {
            "discharge_daily_max",
            "discharge_daily_mean",
            "discharge_instantaneous",
            "stage_daily_max",
            "stage_instantaneous",
            "water_temperature_instantaneous",
        },
        "Hubeau / SCHAPI — French national hydrometric network",
        {"unknown"},
        None,
    ),
    (
        "lt_lhmt",
        97,
        2,
        194,
        "Lithuania",
        {"discharge_daily_mean", "stage_daily_mean"},
        "Lithuanian Hydrometeorological Service LHMT (Meteo.lt)",
        {"unknown"},
        None,
    ),
)
CATALOGUE_MODULE_FILES = {
    "__init__.py",
    "generate_catalogue.py",
    "issue_codes.py",
    "metadata.py",
    "module.py",
}
UNAVAILABLE_METHODS = ("row_annotation_schema", "series_annotation_schema")
REFERENCE_ROOT = Path(__file__).parents[1] / "reference" / "legacy_observations"


@pytest.mark.parametrize(
    (
        "provider_id",
        "station_count",
        "product_count",
        "station_product_count",
        "country",
        "product_ids",
        "provider_name",
        "availability",
        "named_station",
    ),
    CATALOGUE_ONLY_PROVIDERS,
)
def test_catalogue_only_provider_remains_discoverable_and_readable(
    provider_id: str,
    station_count: int,
    product_count: int,
    station_product_count: int,
    country: str,
    product_ids: set[str],
    provider_name: str,
    availability: set[str],
    named_station: tuple[str, str] | None,
) -> None:
    assert provider_id in rr.providers()

    handle = rr.provider(provider_id)
    info = handle.info()
    stations = handle.stations().data
    products = handle.products().data
    station_products = handle.station_products().data
    assert info.provider_id == provider_id
    assert info.name == provider_name
    assert stations.height == station_count
    assert stations["country"].unique().to_list() == [country]
    assert products.height == product_count
    assert set(products["product_id"].to_list()) == product_ids
    assert set(products["provider_id"].to_list()) == {provider_id}
    assert station_products.height == station_product_count
    assert set(station_products["availability"].cast(str).to_list()) == availability
    if named_station is not None:
        station_id, station_name = named_station
        assert stations.filter(stations["station_id"] == station_id).select("name").item() == station_name

    global_stations = rr.stations().data
    global_products = rr.products().data
    global_provider_info = rr.provider_info().data
    station_rows = global_stations.filter(global_stations["provider_id"] == provider_id)
    product_rows = global_products.filter(global_products["provider_id"] == provider_id)
    provider_rows = global_provider_info.filter(global_provider_info["provider_id"] == provider_id)
    assert station_rows.height == station_count
    assert station_rows["country"].unique().to_list() == [country]
    assert product_rows.height == product_count
    assert set(product_rows["product_id"].to_list()) == product_ids
    assert provider_rows.height == 1
    assert provider_rows.select("name").item() == provider_name
    if named_station is not None:
        station_id, station_name = named_station
        assert station_rows.filter(station_rows["station_id"] == station_id).select("name").item() == station_name


@pytest.mark.parametrize(
    (
        "provider_id",
        "station_count",
        "product_count",
        "station_product_count",
        "country",
        "product_ids",
        "provider_name",
        "availability",
        "named_station",
    ),
    CATALOGUE_ONLY_PROVIDERS,
)
def test_catalogue_only_module_retains_only_catalogue_surface(
    provider_id: str,
    station_count: int,
    product_count: int,
    station_product_count: int,
    country: str,
    product_ids: set[str],
    provider_name: str,
    availability: set[str],
    named_station: tuple[str, str] | None,
) -> None:
    module = import_module(f"rivretrieve._internal.providers.{provider_id}.module")

    info = module.info()
    stations = module.stations().data
    products = module.products().data
    station_products = module.station_products().data
    assert info.provider_id == provider_id
    assert info.name == provider_name
    assert stations.height == station_count
    assert stations["country"].unique().to_list() == [country]
    assert products.height == product_count
    assert set(products["product_id"].to_list()) == product_ids
    assert set(products["provider_id"].to_list()) == {provider_id}
    assert station_products.height == station_product_count
    assert set(station_products["availability"].cast(str).to_list()) == availability
    if named_station is not None:
        station_id, station_name = named_station
        assert stations.filter(stations["station_id"] == station_id).select("name").item() == station_name
    assert not hasattr(module, "observations")
    assert not hasattr(module, "row_annotation_schema")
    assert not hasattr(module, "series_annotation_schema")

    provider_directory = Path(module.__file__).parent
    assert {path.name for path in provider_directory.glob("*.py")} == CATALOGUE_MODULE_FILES
    assert module._CATALOGUE_PATH.exists()
    for artifact_name in (
        "provider.json",
        "stations.parquet",
        "products.parquet",
        "station_products.parquet",
    ):
        assert (module._CATALOGUE_PATH / artifact_name).exists()


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
    with pytest.raises(
        ObservationsUnavailableError,
        match=rf"Provider {provider_id} has no observation module registered",
    ):
        rr.provider(provider_id).observations(
            stations="not-consulted",
            products="not-consulted",
            start=None,
            end="2020-01-02",
        )


@pytest.mark.parametrize("provider_id", [row[0] for row in CATALOGUE_ONLY_PROVIDERS])
@pytest.mark.parametrize("method_name", UNAVAILABLE_METHODS)
def test_catalogue_only_provider_rejects_annotation_schema_requests(
    provider_id: str,
    method_name: str,
) -> None:
    method = getattr(rr.provider(provider_id), method_name)

    with pytest.raises(
        ObservationsUnavailableError,
        match=rf"Provider {provider_id} has no observation module registered",
    ):
        method()


def test_ch_foen_internal_metadata_import_does_not_leak_public_names() -> None:
    from rivretrieve._internal.providers.ch_foen import metadata

    assert metadata.ChFoenStationMetadata.__name__ == "ChFoenStationMetadata"
    for name in (
        "ChFoenStationMetadata",
        "ChFoenProductMetadata",
        "ChFoenStationProductMetadata",
    ):
        assert not hasattr(rr, name)


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
        "cz_chmi": {
            "issue_codes.py",
            "module.py",
            "observation_client.py",
            "parser.py",
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
        "lt_lhmt": {
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
        "cz_chmi": {
            "cz_chmi_metadata.json",
            "cz_chmi_0-203-1-016000_daily_2020.json",
        },
        "fr_hubeau": {
            "fr_hubeau_metadata.json",
            "fr_hubeau_temp_stations.json",
            "fr_hubeau_O0050010_QmnJ_2020.json",
            "fr_hubeau_O0050010_obs_tr_H.json",
            "fr_hubeau_T123456001_temperature.json",
        },
        "lt_lhmt": {
            "lithuania_metadata_stations.json",
            "lithuania_anyksciu_vms_2023_06.json",
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

    lt_test_dir = REFERENCE_ROOT / "lt_lhmt" / "tests"
    expected_fixture_line = 'FIXTURE_PATH = Path(__file__).parent / "test_data" / "lithuania_anyksciu_vms_2023_06.json"'
    for test_name in ("test_lt_lhmt_observation_parser.py", "test_lt_lhmt_observations.py"):
        assert expected_fixture_line in (lt_test_dir / test_name).read_text()

    active_fixture_dir = Path(__file__).parent / "test_data"
    for fixture_name in (
        "switzerland_metadata_locations.json",
        "cz_chmi_metadata.json",
        "fr_hubeau_metadata.json",
        "fr_hubeau_temp_stations.json",
        "lithuania_metadata_stations.json",
    ):
        assert (active_fixture_dir / fixture_name).is_file()

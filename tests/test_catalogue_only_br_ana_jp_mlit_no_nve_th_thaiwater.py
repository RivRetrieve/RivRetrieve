"""Catalogue-only contracts and archived-reference inventory for milestone 7 step 3."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.registry import _registry

CATALOGUE_ONLY_PROVIDERS = (
    (
        "br_ana",
        10429,
        5,
        52145,
        {
            "discharge_daily_mean",
            "discharge_instantaneous",
            "stage_daily_mean",
            "stage_instantaneous",
            "water_temperature_instantaneous",
        },
        "ANA Hidroweb — Brazilian National Water and Sanitation Agency",
        "2026-06-11",
        {"unknown"},
    ),
    (
        "jp_mlit",
        1023,
        4,
        4092,
        {"discharge_daily_mean", "discharge_hourly_mean", "stage_daily_mean", "stage_hourly_mean"},
        "MLIT Water Information System — Japan national hydrometric network",
        "2026-08-02",
        {"unknown"},
    ),
    (
        "no_nve",
        4889,
        9,
        44001,
        {
            "discharge_daily_mean",
            "discharge_hourly_mean",
            "discharge_instantaneous",
            "stage_daily_mean",
            "stage_hourly_mean",
            "stage_instantaneous",
            "water_temperature_daily_mean",
            "water_temperature_hourly_mean",
            "water_temperature_instantaneous",
        },
        "NVE HydAPI — Norwegian Water Resources and Energy Directorate",
        "2026-06-03",
        {"available", "unavailable"},
    ),
    (
        "th_thaiwater",
        825,
        2,
        1650,
        {"discharge_instantaneous", "stage_instantaneous"},
        "ThaiWater public API / Hydro-Informatics Institute (HII)",
        "2026-08-02",
        {"unknown"},
    ),
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
DEFERRED_CATALOGUE_MODULE_FILES = {"__init__.py", "generate_catalogue.py", "issue_codes.py", "module.py"}
THAI_CATALOGUE_MODULE_FILES = {"__init__.py", "generate_catalogue.py", "issue_codes.py", "module.py", "origins.py"}
DWS_CATALOGUE_MODULE_FILES = {"__init__.py", "generate_catalogue.py", "module.py", "origins.py"}
JAPAN_CATALOGUE_MODULE_FILES = {"__init__.py", "generate_catalogue.py", "issue_codes.py", "module.py", "origins.py"}
ENROLLED_CATALOGUE_MODULE_FILES = {
    "br_ana": DEFERRED_CATALOGUE_MODULE_FILES,
    "jp_mlit": JAPAN_CATALOGUE_MODULE_FILES,
    "no_nve": DEFERRED_CATALOGUE_MODULE_FILES,
    "th_thaiwater": THAI_CATALOGUE_MODULE_FILES,
    "za_dws": DWS_CATALOGUE_MODULE_FILES,
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
    catalogue_version: str,
    availability: set[str],
) -> None:
    assert provider_id in rr.providers()
    module = import_module(f"rivretrieve._internal.providers.{provider_id}.module")
    info = module.info()
    stations_result = module.stations()
    products_result = module.products()
    station_products_result = module.station_products()
    for result in (stations_result, products_result, station_products_result):
        assert hasattr(result, "data")
        assert hasattr(result, "provenance")
        assert hasattr(result, "issues")
    stations = stations_result.data
    products = products_result.data
    station_products = station_products_result.data
    assert info.provider_id == provider_id
    assert info.name == provider_name
    assert str(info.catalogue_version) == catalogue_version
    assert stations.height == station_count
    assert stations["crs"].unique().to_list() == ["unknown"]
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
        "catalogue_version",
        "availability",
    ),
    CATALOGUE_ONLY_PROVIDERS,
)
def test_catalogue_only_module_retains_only_catalogue_surface(
    provider_id: str,
    station_count: int,
    product_count: int,
    station_product_count: int,
    product_ids: set[str],
    provider_name: str,
    catalogue_version: str,
    availability: set[str],
) -> None:
    module = import_module(f"rivretrieve._internal.providers.{provider_id}.module")
    info = module.info()
    stations = module.stations().data
    products = module.products().data
    station_products = module.station_products().data
    assert info.provider_id == provider_id
    assert info.name == provider_name
    assert str(info.catalogue_version) == catalogue_version
    assert stations.height == station_count
    assert stations["crs"].unique().to_list() == ["unknown"]
    assert products.height == product_count
    assert set(products["product_id"].to_list()) == product_ids
    assert set(products["provider_id"].to_list()) == {provider_id}
    assert station_products.height == station_product_count
    assert set(station_products["availability"].cast(str).to_list()) == availability
    assert not hasattr(module, "observations")
    provider_directory = Path(module.__file__).parent
    assert set(ENROLLED_CATALOGUE_MODULE_FILES) == {row[0] for row in CATALOGUE_ONLY_PROVIDERS}
    expected_module_files = ENROLLED_CATALOGUE_MODULE_FILES[provider_id]
    assert {path.name for path in provider_directory.glob("*.py")} == expected_module_files | {"declaration.py"}
    assert module._CATALOGUE_PATH.exists()
    for artifact_name in ("provider.json", "stations.parquet", "products.parquet", "station_products.parquet"):
        assert (module._CATALOGUE_PATH / artifact_name).exists()


@pytest.mark.parametrize("provider_id", [row[0] for row in CATALOGUE_ONLY_PROVIDERS])
def test_catalogue_only_provider_rejects_observation_retrieval(provider_id: str) -> None:
    rr.providers()
    with pytest.raises(
        ObservationsUnavailableError, match=f"Provider {provider_id} has no observation module registered"
    ):
        _registry.get(provider_id).observations(stations="unused", products="unused", start=None, end=None)


def test_no_nve_packaged_availability_examples_are_retained() -> None:
    module = import_module("rivretrieve._internal.providers.no_nve.module")
    station_products = module.station_products().data
    for product_id in ("discharge_daily_mean", "discharge_instantaneous"):
        row = station_products.filter((pl.col("station_id") == "12.210.0") & (pl.col("product_id") == product_id))
        assert row.height == 1
        assert row.select(pl.col("availability").cast(str)).item() == "available"


def test_jp_mlit_packaged_source_coordinates_are_adopted() -> None:
    module = import_module("rivretrieve._internal.providers.jp_mlit.module")
    stations = module.stations().data
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


def test_reference_tree_preserves_complete_porting_evidence() -> None:
    expected_fixtures = {
        "br_ana": {
            "br_ana_12345000_telemetrica_adotada.json",
            "br_ana_12345000_telemetrica_detalhada.json",
            "br_ana_12345000_vazao_2020.json",
            "br_ana_60435000_cotas_2020.json",
            "br_ana_metadata.json",
        },
        "jp_mlit": {
            "jp_mlit_301011281104010_kind2_202301.dat",
            "jp_mlit_301011281104010_kind7_2023.dat",
            "jp_mlit_metadata.json",
        },
        "no_nve": {
            "no_nve_12.210.0_discharge_daily_2023.json",
            "no_nve_12.210.0_discharge_hourly_202301.json",
            "no_nve_metadata.json",
        },
        "th_thaiwater": {"th_thaiwater_S13A_waterlevel_graph.json", "th_thaiwater_metadata.json"},
    }
    endpoints = {
        "br_ana": (
            "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/HidroinfoanaSerieTelemetricaAdotada/v1"
        ),
        "jp_mlit": "http://www1.river.go.jp",
        "no_nve": "https://hydapi.nve.no/api/v1/",
        "th_thaiwater": "https://api-v3.thaiwater.net/api/v1/thaiwater30/public",
    }
    source_names = {
        "issue_codes.py",
        "module.py",
        "observation_client.py",
        "parser.py",
        "retrieval.py",
        "transform.py",
    }
    for provider_id, fixture_names in expected_fixtures.items():
        provider_root = REFERENCE_ROOT / provider_id
        assert {path.name for path in (provider_root / "source").iterdir()} == source_names
        assert {path.name for path in (provider_root / "tests").glob("test_*.py")} == {
            f"test_{provider_id}_module.py",
            f"test_{provider_id}_observations.py",
        }
        assert {path.name for path in (provider_root / "tests" / "test_data").iterdir()} == fixture_names
        client_text = (provider_root / "source" / "observation_client.py").read_text()
        assert endpoints[provider_id] in client_text
        readme = (provider_root / "README.md").read_text()
        assert "51ce7d87da140568ee4145cd41fef0ac9f39fc45" in readme
        for source_name in source_names:
            original = f"src/rivretrieve/_internal/providers/{provider_id}/{source_name}"
            assert f"- `{original}` -> `source/{source_name}`" in readme
        for test_name in (f"test_{provider_id}_module.py", f"test_{provider_id}_observations.py"):
            assert f"- `tests/{test_name}` -> `tests/{test_name}`" in readme
        for fixture_name in fixture_names:
            assert f"- `tests/test_data/{fixture_name}` -> `tests/test_data/{fixture_name}`" in readme


def test_active_catalogue_fixtures_remain_available() -> None:
    fixture_dir = Path(__file__).parent / "test_data"
    for fixture_name in (
        "br_ana_metadata.json",
        "jp_mlit_metadata.json",
        "no_nve_metadata.json",
        "th_thaiwater_metadata.json",
    ):
        assert (fixture_dir / fixture_name).is_file()

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError

CATALOGUE_ONLY_PROVIDERS = (
    ("ch_foen", 246, 6, 1476),
    ("cz_chmi", 831, 5, 4155),
    ("fr_hubeau", 7289, 6, 32969),
    ("lt_lhmt", 97, 2, 194),
)
CATALOGUE_MODULE_FILES = {
    "__init__.py",
    "generate_catalogue.py",
    "issue_codes.py",
    "metadata.py",
    "module.py",
}
UNAVAILABLE_METHODS = (
    "row_annotation_schema",
    "series_annotation_schema",
)


@pytest.mark.parametrize(
    ("provider_id", "station_count", "product_count", "station_product_count"),
    CATALOGUE_ONLY_PROVIDERS,
)
def test_catalogue_only_provider_remains_discoverable_and_readable(
    provider_id: str,
    station_count: int,
    product_count: int,
    station_product_count: int,
) -> None:
    assert provider_id in rr.providers()

    handle = rr.provider(provider_id)
    assert handle.info().provider_id == provider_id
    assert handle.stations().data.height == station_count
    assert handle.products().data.height == product_count
    assert handle.station_products().data.height == station_product_count

    provider_rows = rr.provider_info().data.filter(rr.provider_info().data["provider_id"] == provider_id)
    assert provider_rows.height == 1


@pytest.mark.parametrize(
    ("provider_id", "station_count", "product_count", "station_product_count"),
    CATALOGUE_ONLY_PROVIDERS,
)
def test_catalogue_only_module_retains_only_catalogue_surface(
    provider_id: str,
    station_count: int,
    product_count: int,
    station_product_count: int,
) -> None:
    module = import_module(f"rivretrieve._internal.providers.{provider_id}.module")

    assert module.info().provider_id == provider_id
    assert module.stations().data.height == station_count
    assert module.products().data.height == product_count
    assert module.station_products().data.height == station_product_count
    assert not hasattr(module, "observations")
    assert not hasattr(module, "row_annotation_schema")
    assert not hasattr(module, "series_annotation_schema")

    provider_directory = Path(module.__file__).parent
    assert {path.name for path in provider_directory.glob("*.py")} == CATALOGUE_MODULE_FILES


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

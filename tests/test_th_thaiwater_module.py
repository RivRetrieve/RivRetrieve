"""Catalogue-only contract tests for th_thaiwater."""

from __future__ import annotations

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.providers.th_thaiwater import module as th_thaiwater_module


def test_th_thaiwater_catalogue_remains_available() -> None:
    handle = rr.provider("th_thaiwater")
    assert handle.stations().data["provider_id"].unique().to_list() == ["th_thaiwater"]
    assert handle.station_products().data["provider_id"].unique().to_list() == ["th_thaiwater"]


def test_th_thaiwater_in_providers_list() -> None:
    assert "th_thaiwater" in rr.providers()


def test_th_thaiwater_stations_offline() -> None:
    result = rr.provider("th_thaiwater").stations()
    assert result.data.height == 754
    assert result.data["country"].unique().to_list() == ["Thailand"]


def test_th_thaiwater_products_offline() -> None:
    result = rr.provider("th_thaiwater").products()
    assert result.data.height == 4
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {
        "stage_daily_mean",
        "stage_instantaneous",
        "discharge_daily_mean",
        "discharge_instantaneous",
    }


def test_th_thaiwater_station_products_offline() -> None:
    result = rr.provider("th_thaiwater").station_products()
    assert result.data.height == 754 * 4


def test_th_thaiwater_info() -> None:
    info = rr.provider("th_thaiwater").info()
    assert info.provider_id == "th_thaiwater"
    assert "ThaiWater" in info.name or "HII" in info.name or "Thailand" in info.name


def test_th_thaiwater_module_catalogue_path_exists() -> None:
    assert th_thaiwater_module._CATALOGUE_PATH.exists()
    assert (th_thaiwater_module._CATALOGUE_PATH / "provider.json").exists()
    assert (th_thaiwater_module._CATALOGUE_PATH / "stations.parquet").exists()
    assert (th_thaiwater_module._CATALOGUE_PATH / "products.parquet").exists()
    assert (th_thaiwater_module._CATALOGUE_PATH / "station_products.parquet").exists()


def test_th_thaiwater_packaged_artifact_remains_loadable() -> None:
    assert th_thaiwater_module._artifact().provider_info["provider_id"] == "th_thaiwater"


def test_th_thaiwater_observations_are_unavailable() -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider th_thaiwater has no observation module registered",
    ):
        rr.provider("th_thaiwater").observations(
            stations="S13A",
            products="stage_instantaneous",
            start="2023-01-01",
            end="2023-01-02",
        )


@pytest.mark.parametrize("method_name", ["row_annotation_schema", "series_annotation_schema"])
def test_th_thaiwater_observation_schemas_are_unavailable(method_name: str) -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider th_thaiwater has no observation module registered",
    ):
        getattr(rr.provider("th_thaiwater"), method_name)()


def test_th_thaiwater_module_has_no_observation_surface() -> None:
    assert not hasattr(th_thaiwater_module, "observations")
    assert not hasattr(th_thaiwater_module, "row_annotation_schema")
    assert not hasattr(th_thaiwater_module, "series_annotation_schema")


def test_th_thaiwater_retired_and_unported_files_are_absent() -> None:
    provider_path = th_thaiwater_module._CATALOGUE_PATH.parent
    assert (provider_path / "issue_codes.py").exists()
    forbidden_files = (
        "observation_client.py",
        "parser.py",
        "retrieval.py",
        "transform.py",
        "fetch.py",
        "parse.py",
        "config.py",
    )
    assert [name for name in forbidden_files if (provider_path / name).exists()] == []

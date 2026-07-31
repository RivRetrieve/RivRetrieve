"""Catalogue-only contract tests for br_ana."""

from __future__ import annotations

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.providers.br_ana import module as br_ana_module


def test_br_ana_catalogue_remains_available() -> None:
    handle = rr.provider("br_ana")
    assert handle.stations().data["provider_id"].unique().to_list() == ["br_ana"]
    assert handle.station_products().data["provider_id"].unique().to_list() == ["br_ana"]


def test_br_ana_in_providers_list() -> None:
    assert "br_ana" in rr.providers()


def test_br_ana_products_offline() -> None:
    result = rr.provider("br_ana").products()
    assert result.data.height == 5
    product_ids = set(result.data["product_id"].to_list())
    assert product_ids == {
        "discharge_daily_mean",
        "stage_daily_mean",
        "discharge_instantaneous",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    }


def test_br_ana_info() -> None:
    info = rr.provider("br_ana").info()
    assert info.provider_id == "br_ana"
    assert "ANA" in info.name or "Brazil" in info.name


def test_br_ana_module_catalogue_path_exists() -> None:
    assert br_ana_module._CATALOGUE_PATH.exists()
    assert (br_ana_module._CATALOGUE_PATH / "provider.json").exists()
    assert (br_ana_module._CATALOGUE_PATH / "stations.parquet").exists()
    assert (br_ana_module._CATALOGUE_PATH / "products.parquet").exists()
    assert (br_ana_module._CATALOGUE_PATH / "station_products.parquet").exists()


def test_br_ana_station_no_coord_filtered() -> None:
    result = rr.provider("br_ana").stations()
    station_ids = set(result.data["station_id"].to_list())
    assert "99999999" not in station_ids


def test_br_ana_packaged_artifact_remains_loadable() -> None:
    assert br_ana_module._artifact().provider_info["provider_id"] == "br_ana"


def test_br_ana_observations_are_unavailable() -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider br_ana has no observation module registered",
    ):
        rr.provider("br_ana").observations(
            stations="12345000",
            products="discharge_daily_mean",
            start="2020-01-01",
            end="2020-01-02",
        )


@pytest.mark.parametrize("method_name", ["row_annotation_schema", "series_annotation_schema"])
def test_br_ana_observation_schemas_are_unavailable(method_name: str) -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider br_ana has no observation module registered",
    ):
        getattr(rr.provider("br_ana"), method_name)()


def test_br_ana_module_has_no_observation_surface() -> None:
    assert not hasattr(br_ana_module, "observations")
    assert not hasattr(br_ana_module, "row_annotation_schema")
    assert not hasattr(br_ana_module, "series_annotation_schema")


def test_br_ana_retired_and_unported_files_are_absent() -> None:
    provider_path = br_ana_module._CATALOGUE_PATH.parent
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

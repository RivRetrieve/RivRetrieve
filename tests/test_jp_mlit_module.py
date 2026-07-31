"""Catalogue-only contract tests for jp_mlit."""

from __future__ import annotations

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.providers.jp_mlit import module as jp_mlit_module


def test_jp_mlit_in_providers_list() -> None:
    assert "jp_mlit" in rr.providers()


def test_jp_mlit_provider_handle_returns() -> None:
    handle = rr.provider("jp_mlit")
    assert handle is not None


def test_jp_mlit_info_name() -> None:
    info = rr.provider("jp_mlit").info()
    assert "Japan" in info.name or "MLIT" in info.name


def test_jp_mlit_catalogue_version() -> None:
    info = rr.provider("jp_mlit").info()
    assert info.catalogue_version is not None


def test_jp_mlit_stations_returns_catalog_result() -> None:
    result = rr.provider("jp_mlit").stations()
    assert hasattr(result, "data")
    assert hasattr(result, "provenance")
    assert hasattr(result, "issues")


def test_jp_mlit_stations_count() -> None:
    result = rr.provider("jp_mlit").stations()
    assert len(result.data) == 1024


def test_jp_mlit_products_count() -> None:
    result = rr.provider("jp_mlit").products()
    assert len(result.data) == 4


def test_jp_mlit_station_products_count() -> None:
    result = rr.provider("jp_mlit").station_products()
    assert len(result.data) == 4096


def test_jp_mlit_global_stations_includes_provider() -> None:
    result = rr.stations()
    provider_ids = result.data["provider_id"].unique().to_list()
    assert "jp_mlit" in provider_ids


def test_jp_mlit_live_catalogue_unsupported() -> None:
    result = rr.provider("jp_mlit").stations(source="live")
    assert len(result.issues) > 0


def test_jp_mlit_packaged_artifact_remains_loadable() -> None:
    assert jp_mlit_module._artifact().provider_info["provider_id"] == "jp_mlit"


def test_jp_mlit_observations_are_unavailable() -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider jp_mlit has no observation module registered",
    ):
        rr.provider("jp_mlit").observations(
            stations="301011281104010",
            products="discharge_daily_mean",
            start="2023-01-01",
            end="2023-01-02",
        )


@pytest.mark.parametrize("method_name", ["row_annotation_schema", "series_annotation_schema"])
def test_jp_mlit_observation_schemas_are_unavailable(method_name: str) -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider jp_mlit has no observation module registered",
    ):
        getattr(rr.provider("jp_mlit"), method_name)()


def test_jp_mlit_module_has_no_observation_surface() -> None:
    assert not hasattr(jp_mlit_module, "observations")
    assert not hasattr(jp_mlit_module, "row_annotation_schema")
    assert not hasattr(jp_mlit_module, "series_annotation_schema")


def test_jp_mlit_retired_and_unported_files_are_absent() -> None:
    provider_path = jp_mlit_module._CATALOGUE_PATH.parent
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

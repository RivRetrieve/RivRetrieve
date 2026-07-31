"""Catalogue-only contract tests for no_nve."""

from __future__ import annotations

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.providers.no_nve import module as no_nve_module


def test_no_nve_in_providers_list() -> None:
    assert "no_nve" in rr.providers()


def test_no_nve_provider_handle_returns() -> None:
    handle = rr.provider("no_nve")
    assert handle is not None


def test_no_nve_info_name() -> None:
    info = rr.provider("no_nve").info()
    assert "Norway" in info.name or "NVE" in info.name


def test_no_nve_catalogue_version() -> None:
    info = rr.provider("no_nve").info()
    assert info.catalogue_version is not None


def test_no_nve_live_stations_capability() -> None:
    """no_nve live_stations=False: the live generator is not a runtime path."""
    info = rr.provider("no_nve").info()
    assert info.live_stations is False


def test_no_nve_stations_returns_catalog_result() -> None:
    result = rr.provider("no_nve").stations()
    assert hasattr(result, "data")
    assert hasattr(result, "provenance")
    assert hasattr(result, "issues")


def test_no_nve_stations_count() -> None:
    result = rr.provider("no_nve").stations()
    assert len(result.data) == 4889


def test_no_nve_products_count() -> None:
    result = rr.provider("no_nve").products()
    assert len(result.data) == 9


def test_no_nve_products_include_canonical_and_provider_specific() -> None:
    result = rr.provider("no_nve").products()
    product_ids = set(result.data["product_id"].to_list())
    assert "discharge_daily_mean" in product_ids
    assert "stage_daily_mean" in product_ids
    assert "water_temperature_daily_mean" in product_ids
    assert "discharge_instantaneous" in product_ids
    assert "stage_instantaneous" in product_ids
    assert "water_temperature_instantaneous" in product_ids
    assert "discharge_hourly_mean" in product_ids
    assert "stage_hourly_mean" in product_ids
    assert "water_temperature_hourly_mean" in product_ids


def test_no_nve_station_products_count() -> None:
    result = rr.provider("no_nve").station_products()
    assert len(result.data) == 44001


def test_no_nve_station_products_availability_from_series_list() -> None:
    result = rr.provider("no_nve").station_products()
    availabilities = set(result.data["availability"].cast(str).to_list())
    assert "unknown" not in availabilities


def test_no_nve_station_12_210_0_discharge_daily_available() -> None:
    import polars as pl

    result = rr.provider("no_nve").station_products()
    row = result.data.filter((pl.col("station_id") == "12.210.0") & (pl.col("product_id") == "discharge_daily_mean"))
    assert not row.is_empty()
    assert row["availability"].cast(str).to_list()[0] == "available"


def test_no_nve_station_12_210_0_discharge_instantaneous_available() -> None:
    import polars as pl

    result = rr.provider("no_nve").station_products()
    row = result.data.filter((pl.col("station_id") == "12.210.0") & (pl.col("product_id") == "discharge_instantaneous"))
    assert not row.is_empty()
    assert row["availability"].cast(str).to_list()[0] == "available"


def test_no_nve_global_stations_includes_provider() -> None:
    result = rr.stations()
    provider_ids = result.data["provider_id"].unique().to_list()
    assert "no_nve" in provider_ids


def test_no_nve_live_catalogue_returns_warning_issue() -> None:
    result = rr.provider("no_nve").stations(source="live", on_issue="ignore")
    assert len(result.issues) > 0


def test_no_nve_packaged_artifact_remains_loadable() -> None:
    assert no_nve_module._artifact().provider_info["provider_id"] == "no_nve"


def test_no_nve_observations_are_unavailable() -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider no_nve has no observation module registered",
    ):
        rr.provider("no_nve").observations(
            stations="12.210.0",
            products="discharge_daily_mean",
            start="2023-01-01",
            end="2023-01-02",
        )


@pytest.mark.parametrize("method_name", ["row_annotation_schema", "series_annotation_schema"])
def test_no_nve_observation_schemas_are_unavailable(method_name: str) -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider no_nve has no observation module registered",
    ):
        getattr(rr.provider("no_nve"), method_name)()


def test_no_nve_module_has_no_observation_surface() -> None:
    assert not hasattr(no_nve_module, "observations")
    assert not hasattr(no_nve_module, "row_annotation_schema")
    assert not hasattr(no_nve_module, "series_annotation_schema")


def test_no_nve_retired_and_unported_files_are_absent() -> None:
    provider_path = no_nve_module._CATALOGUE_PATH.parent
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

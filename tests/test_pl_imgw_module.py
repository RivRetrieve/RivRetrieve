from datetime import date

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.providers.pl_imgw import module as pl_imgw_module
from rivretrieve._internal.providers.pl_imgw.generate_catalogue import build_provider_info
from rivretrieve._internal.results import CatalogResult

BULK_OBSERVATIONS = (
    "true: the source publishes all-station yearly ZIP files; RivRetrieve's "
    "catalogue-only provider exposes neither observation retrieval nor cache controls"
)


def test_pl_imgw_registered_with_packaged_stations() -> None:
    assert "pl_imgw" in rr.providers()
    result = rr.provider("pl_imgw").stations()
    assert isinstance(result, CatalogResult)
    assert result.data.height == 1301


def test_pl_imgw_products_offline() -> None:
    result = rr.provider("pl_imgw").products()
    assert result.data.height == 3
    assert set(result.data["product_id"].to_list()) == {
        "discharge_daily_mean",
        "stage_daily_mean",
        "water_temperature_daily_mean",
    }


def test_pl_imgw_station_products_and_artifacts() -> None:
    assert rr.provider("pl_imgw").station_products().data.height > 0
    assert {path.name for path in pl_imgw_module._CATALOGUE_PATH.iterdir()} == {
        "native.parquet",
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
    }


def test_pl_imgw_generator_and_packaged_bulk_observations_match() -> None:
    generated = build_provider_info(date(2026, 6, 4), generator_input="fixture")
    assert generated["bulk_observations"] == BULK_OBSERVATIONS
    assert rr.provider("pl_imgw").info().bulk_observations == BULK_OBSERVATIONS


@pytest.mark.parametrize("method", ["row_annotation_schema", "series_annotation_schema"])
def test_pl_imgw_observation_schemas_unavailable(method: str) -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider pl_imgw has no observation module registered",
    ):
        getattr(rr.provider("pl_imgw"), method)()


def test_pl_imgw_observations_unavailable() -> None:
    with pytest.raises(
        ObservationsUnavailableError,
        match="Provider pl_imgw has no observation module registered",
    ):
        rr.provider("pl_imgw").observations(
            stations=["151140030"],
            products=["discharge_daily_mean"],
            start="2023-01-01",
            end="2023-01-02",
        )


@pytest.mark.parametrize("method", ["cache_status", "refresh_cache"])
def test_pl_imgw_handle_has_no_cache_controls(method: str) -> None:
    with pytest.raises(AttributeError, match=rf"Provider 'pl_imgw' has no attribute '{method}'"):
        getattr(rr.provider("pl_imgw"), method)


def test_pl_imgw_module_has_no_observation_or_cache_surface() -> None:
    assert not hasattr(pl_imgw_module, "observations")
    assert not hasattr(pl_imgw_module, "cache_status")
    assert not hasattr(pl_imgw_module, "refresh_cache")

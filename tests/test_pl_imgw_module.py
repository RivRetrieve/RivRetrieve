from datetime import date

import rivretrieve as rr
from rivretrieve._internal.providers.pl_imgw.generate_catalogue import build_provider_info
from rivretrieve._internal.results import CatalogResult
from tests._catalogue import catalogue_path, catalogue_reader, provider_info

BULK_OBSERVATIONS = (
    "true: the source publishes all-station yearly ZIP files; RivRetrieve's "
    "catalogue-only provider exposes neither observation retrieval nor cache controls"
)


def test_pl_imgw_registered_with_packaged_stations() -> None:
    assert "pl_imgw" in rr.providers().get_column("provider_id").to_list()
    result = catalogue_reader("pl_imgw").read_stations()
    assert isinstance(result, CatalogResult)
    assert result.data.height == 1301


def test_pl_imgw_products_offline() -> None:
    result = catalogue_reader("pl_imgw").read_products()
    assert result.data.height == 3
    assert set(result.data["product_id"].to_list()) == {
        "discharge_daily_mean",
        "stage_daily_mean",
        "water_temperature_daily_mean",
    }


def test_pl_imgw_station_products_and_artifacts() -> None:
    assert catalogue_reader("pl_imgw").read_station_products().data.height > 0
    assert {path.name for path in catalogue_path("pl_imgw").iterdir()} == {
        "native.parquet",
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "provenance.json",
    }


def test_pl_imgw_generator_and_packaged_bulk_observations_match() -> None:
    generated = build_provider_info(date(2026, 6, 4))
    assert generated["bulk_observations"] == BULK_OBSERVATIONS
    assert generated["catalogue_version"] == "2026-06-04"
    assert tuple(generated) == (
        "provider_id",
        "name",
        "live_stations",
        "live_products",
        "live_station_products",
        "bulk_observations",
        "catalogue_version",
        "license",
        "citation",
    )
    assert provider_info("pl_imgw").bulk_observations == BULK_OBSERVATIONS

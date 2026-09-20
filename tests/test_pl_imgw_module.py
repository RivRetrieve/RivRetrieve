from datetime import date

import rivretrieve as rr
from rivretrieve._internal.providers.pl_imgw.generate_catalogue import build_provider_info
from rivretrieve._internal.results import CatalogResult
from tests._catalogue import catalogue_path, catalogue_reader, provider_info

BULK_OBSERVATIONS = (
    "true: explicit download compiles the publisher's monthly or annual ZIP archives "
    "into a local native observation store; retrieval reads that store without network access"
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
        "discharge_daily",
        "stage_daily",
        "water_temperature_daily",
    }


def test_pl_imgw_station_products_and_artifacts() -> None:
    assert catalogue_reader("pl_imgw").read_station_products().data.height > 0
    assert {path.name for path in catalogue_path("pl_imgw").iterdir()} == {
        "croissant.json",
        "native.parquet",
        "provider.json",
        "products.parquet",
        "stations.parquet",
        "station_products.parquet",
        "provenance.json",
        "provenance_facts.parquet",
        "provenance_acquisitions.parquet",
        "provenance_bindings.parquet",
        "provenance_binding_facts.parquet",
        "provenance_external_inputs.parquet",
        "format.json",
        "source_series.json",
        "series_claims.parquet",
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


def test_provider_metadata_describes_explicit_compiled_store_access() -> None:
    from datetime import date

    from rivretrieve._internal.providers.pl_imgw.generate_catalogue import build_provider_info

    text = str(build_provider_info(date(2026, 9, 20))["bulk_observations"])
    assert "catalogue-only" not in text
    assert "explicit" in text
    assert "monthly" in text and "annual" in text


def test_precise_mean_filter_does_not_admit_unestablished_imgw_statistics() -> None:
    for quantity in ("discharge", "stage", "temperature"):
        broad = rr.find(provider="pl_imgw", station="154210010", quantity=quantity)
        descriptions = rr.series(broad)
        assert descriptions.height == 1
        assert descriptions["admission"].to_list() == ["supported"]
        precise = rr.pick(broad, frequency="daily", statistic="mean", on_issue="ignore")
        assert not precise.series
        direct = rr.find(
            provider="pl_imgw",
            station="154210010",
            quantity=quantity,
            frequency="daily",
            statistic="mean",
            on_issue="ignore",
        )
        assert not direct.series
        facts = broad.series[0].facts[0]
        assert facts.statistic.value is None
        assert facts.timestamp_anchor.value is None
        assert facts.time_zone.value is None


def test_catalogue_native_coordinates_use_publisher_field_codes() -> None:
    products = catalogue_reader("pl_imgw").read_products().data
    assert dict(products.select("product_id", "native_id").iter_rows()) == {
        "discharge_daily": "COPRZP",
        "stage_daily": "COSTAN",
        "water_temperature_daily": "COPTMP",
    }

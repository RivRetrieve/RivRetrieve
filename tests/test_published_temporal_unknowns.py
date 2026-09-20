"""Measurement-time and raw-resolution access do not establish sampling cadence.

HydAPI UserDocumentation (test_data/no_nve_terms_licence.html) defines raw/hour/day
resolutions, not raw-series cadence. ANA manual page 11 and the retained adopted
OpenAPI v1/v2 descriptions establish units and measurement-time labels, not an
instantaneous statistic or cadence. Daily dictionary evidence is independent.
"""

import pytest

import rivretrieve as rr


@pytest.mark.parametrize("provider,station", [("no_nve", "1.200.0"), ("br_ana", "15400000")])
def test_raw_measurement_access_does_not_match_irregular_frequency(provider, station):
    selected = rr.find(provider=provider, station=station, quantity="discharge", frequency="irregular")
    assert not selected.series


def test_ana_adopted_measurement_time_does_not_establish_instantaneous_statistic():
    selected = rr.find(provider="br_ana", station="15400000", quantity="discharge", statistic="instantaneous")
    assert not selected.series
    broad = rr.find(provider="br_ana", station="15400000", quantity="discharge")
    adopted = next(item for item in broad.series if item.variant == "Vazao_Adotada")
    assert adopted.facts[0].frequency.value is None
    assert adopted.facts[0].statistic.value is None
    assert adopted.facts[0].timestamp_anchor.value == "measurement_time"


def test_nve_raw_method_is_independent_of_unknown_frequency():
    selected = rr.find(provider="no_nve", station="1.200.0", quantity="discharge", statistic="instantaneous")
    raw = [item for item in selected.series if item.product_id == "discharge_instantaneous"]
    assert raw and all(item.facts[0].frequency.value is None for item in raw)


def test_nve_access_products_do_not_override_version_specific_methods():
    from pathlib import Path

    import polars as pl

    products = pl.read_parquet(
        Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/no_nve/catalogue/products.parquet"
    )
    assert products["statistic"].unique().to_list() == ["unknown"]
    assert products["period_type"].unique().to_list() == ["unknown"]
    assert products["period_anchor"].unique().to_list() == ["unknown"]
    broad = rr.find(provider="no_nve", station="1.46.0", quantity="stage", frequency="daily")
    assert {item.facts[0].statistic.value for item in broad.series} == {"mean", "instantaneous"}


def test_usgs_product_projection_does_not_invent_timestamp_anchor():
    from pathlib import Path

    import polars as pl

    from rivretrieve._internal.providers.usgs_nwis.generate_catalogue import build_products

    packaged = pl.read_parquet(
        Path(__file__).parents[1] / "src/rivretrieve/_internal/providers/usgs_nwis/catalogue/products.parquet"
    )
    for products in (packaged, build_products()):
        assert products["period_anchor"].unique().to_list() == ["unknown"]

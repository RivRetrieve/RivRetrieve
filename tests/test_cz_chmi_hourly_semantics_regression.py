"""Regression: CHMI hourly means must not be represented as instants."""

import polars as pl

from rivretrieve._internal.engine import Hourly, IntervalDefinition
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.cz_chmi.config import config
from tests._catalogue import catalogue_reader


def test_product_config_can_state_hourly_mean_with_unknown_interval_definition() -> None:
    assert config().products[ProductId("stage_hourly_mean")].semantics == Hourly(IntervalDefinition("unknown"))
    assert config().products[ProductId("discharge_hourly_mean")].semantics == Hourly(IntervalDefinition("unknown"))


def test_czech_catalogue_identifies_hourly_values_as_interval_means() -> None:
    products = catalogue_reader("cz_chmi").read_products().data
    hourly = products.filter(pl.col("native_id").is_in(["HH", "QH"])).sort("native_id")
    assert hourly.select("product_id", "frequency", "statistic", "period_type", "period_anchor").rows() == [
        ("stage_hourly_mean", "hourly", "mean", "interval", "unknown"),
        ("discharge_hourly_mean", "hourly", "mean", "interval", "unknown"),
    ]
    assert not products["product_id"].str.contains("instantaneous").any()
    station_products = catalogue_reader("cz_chmi").read_station_products().data
    assert set(station_products["product_id"].unique().to_list()) == set(products["product_id"].to_list())
    assert not station_products["product_id"].str.contains("instantaneous").any()

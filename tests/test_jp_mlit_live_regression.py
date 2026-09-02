"""Regression contract for corrected Japan MLIT live products."""

from rivretrieve._internal.providers.jp_mlit.config import config, window_declarations
from tests._catalogue import catalogue_reader


def test_japan_product_ids_and_unknown_source_semantics() -> None:
    provider = config()
    assert tuple(provider.products) == (
        "stage_hourly",
        "stage_daily",
        "discharge_hourly",
        "discharge_daily",
    )
    assert provider.zone.value == "unknown"
    assert {coordinates.value.kind for coordinates in (p.coordinates for p in provider.products.values())} == {
        2,
        3,
        6,
        7,
    }
    declarations = window_declarations().products
    assert set(declarations) == set(provider.products)
    assert [
        (declarations[product].granularity, declarations[product].stop_convention) for product in provider.products
    ] == [
        ("year-month", "inclusive"),
        ("year", "inclusive"),
        ("year-month", "inclusive"),
        ("year", "inclusive"),
    ]


def test_all_station_product_edges_use_only_corrected_selectable_ids() -> None:
    station_products = catalogue_reader("jp_mlit").read_station_products().data
    counts = station_products.group_by("product_id").len().sort("product_id")
    assert counts["product_id"].to_list() == ["discharge_daily", "discharge_hourly", "stage_daily", "stage_hourly"]
    assert counts["len"].to_list() == [1023, 1023, 1023, 1023]
    assert station_products.height == 4092
    assert not any(product.endswith("_mean") for product in station_products["product_id"])

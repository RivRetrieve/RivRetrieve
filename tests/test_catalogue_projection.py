"""Shared projection inputs remain detached across inspection tests."""

import polars as pl
from polars.testing import assert_frame_equal

from tests._catalogue_projection import CatalogueProjection, copy_catalogue_projection


def test_catalogue_projection_copies_all_mutable_carriers():
    frame = pl.DataFrame({"value": [1, 2]})
    original = CatalogueProjection({"nested": {"labels": ["source"]}}, frame, frame, frame)
    first = copy_catalogue_projection(original)
    first.provider_info["nested"]["labels"].append("changed")
    for table in (first.products, first.stations, first.station_products):
        table.replace_column(0, pl.Series("changed", [3, 4]))
    second = copy_catalogue_projection(original)
    assert second.provider_info == {"nested": {"labels": ["source"]}}
    assert second.provider_info is not original.provider_info
    for table in (second.products, second.stations, second.station_products):
        assert_frame_equal(table, frame)
        assert table is not frame
    # Mutating one table cannot affect another even when the original aliases them.
    second.products.replace_column(0, pl.Series("other", [5, 6]))
    assert_frame_equal(second.stations, frame)
    assert_frame_equal(second.station_products, frame)

"""NRFA advertised associations and source metadata survive catalogue projection."""

from datetime import UTC, datetime

import polars as pl
import polars.testing as pt

from rivretrieve._internal.catalogues.native import RetrievedAt, stamp_native_table
from rivretrieve._internal.providers.uk_nrfa.generate_catalogue import build_station_products, build_stations


def test_station_projection_keeps_closed_stations_and_missing_coordinates():
    native = stamp_native_table(
        pl.DataFrame(
            {
                "id": ["12345", "201234"],
                "latitude": [51.25, None],
                "longitude": [-1.5, None],
                "closed": ["2000-01-01", None],
            }
        ),
        RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
    )
    expected = pl.DataFrame(
        {
            "provider_id": ["uk_nrfa", "uk_nrfa"],
            "station_id": ["12345", "201234"],
            "latitude": [51.25, None],
            "longitude": [-1.5, None],
            "crs": ["EPSG:4326", "EPSG:4326"],
        }
    )
    pt.assert_frame_equal(build_stations(native), expected)


def test_only_advertised_products_are_published_with_unknown_bounds():
    native = stamp_native_table(
        pl.DataFrame(
            {
                "id": ["12345", "201234"],
                "data-summary": [
                    [
                        {"data-type": "gdf", "first": "1970-01-01", "last": "2025-01-01"},
                        {"data-type": "gmf", "first": "1970-01", "last": "2025-01"},
                        {"data-type": "rainfall", "first": None, "last": None},
                    ],
                    [{"data-type": "gauging-stage", "first": "2020-01-01T12:30:00", "last": None}],
                ],
            }
        ),
        RetrievedAt(datetime(2026, 11, 6, tzinfo=UTC)),
    )
    result = build_station_products(native)
    assert set(result.select("station_id", "product_id").iter_rows()) == {
        ("12345", "gdf"),
        ("12345", "gmf"),
        ("201234", "gauging-stage"),
    }
    assert result["availability"].to_list() == ["available"] * 3
    assert result["published_record_start_date"].null_count() == 3
    assert result["published_record_end_date"].null_count() == 3
    assert native.data["data-summary"][0][1]["first"] == "1970-01"

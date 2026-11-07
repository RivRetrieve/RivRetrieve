from __future__ import annotations

from tests._catalogue import catalogue_reader


def test_fi_syke_station_coordinates_in_finland_range() -> None:
    result = catalogue_reader("fi_syke").read_stations()
    assert result.data["latitude"].null_count() == 0
    assert result.data["longitude"].null_count() == 0
    assert result.data["crs"].drop_nulls().unique().to_list() == ["EPSG:4258"]
    lats = result.data["latitude"].to_list()
    lons = result.data["longitude"].to_list()
    assert all(59.5 <= lat <= 70.2 for lat in lats), "All latitudes should be in Finland's range"
    assert all(19.0 <= lon <= 31.6 for lon in lons), "All longitudes should be in Finland's range"


def test_fi_syke_products_cover_the_three_admitted_quantities() -> None:
    result = catalogue_reader("fi_syke").read_products()
    assert sorted(result.data["product_id"].to_list()) == [
        "discharge_reported",
        "stage_reported",
        "water_temperature_reported",
    ]
    assert result.data["frequency"].to_list() == ["daily"] * 3


def test_fi_syke_a_station_can_have_more_than_one_product() -> None:
    """A real gauge measuring both discharge and stage is one station (Nro), not two."""
    result = catalogue_reader("fi_syke").read_station_products()
    available = result.data.filter(result.data["availability"] == "available")
    counts = available.group_by("station_id").len()
    assert counts["len"].max() > 1

from __future__ import annotations

from tests._catalogue import catalogue_reader


def test_za_dws_station_x3h001_present() -> None:
    result = catalogue_reader("za_dws").read_stations()
    row = result.data.filter(result.data["station_id"] == "X3H001")
    assert row.height == 1
    lat = row["latitude"][0]
    lon = row["longitude"][0]
    assert lat is not None and lat < 0  # Southern Hemisphere
    assert lon is not None and lon > 0  # Eastern Hemisphere


def test_za_dws_station_coordinates_in_south_africa_range() -> None:
    result = catalogue_reader("za_dws").read_stations()
    assert result.data["latitude"].null_count() == 0
    assert result.data["longitude"].null_count() == 0
    lats = result.data["latitude"].to_list()
    lons = result.data["longitude"].to_list()
    assert all(-35.0 <= lat <= -22.0 for lat in lats), "All latitudes should be in South Africa range"
    assert all(16.0 <= lon <= 34.0 for lon in lons), "All longitudes should be in South Africa range"

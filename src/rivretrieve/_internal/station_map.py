"""station map = render(filter(StationCatalog, provider IDs × bounding box), station identity × coordinates)."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from typing import cast

import polars as pl

from rivretrieve._internal.issues import MissingOptionalDependencyError


@dataclass(frozen=True)
class StationMap:
    stations: pl.DataFrame

    def render(self) -> object:
        folium = _load_folium()
        center = _map_center(self.stations)
        station_map = folium.Map(location=center, zoom_start=8, control_scale=True)

        for station in self.stations.iter_rows(named=True):
            latitude = station["latitude"]
            longitude = station["longitude"]
            marker = folium.Marker(
                location=[latitude, longitude],
                tooltip=_station_label(station),
                popup=_station_popup(station),
                icon=folium.Icon(color="orange" if station["crs"] == "unknown" else "blue"),
            )
            marker.add_to(station_map)

        return station_map


def _load_folium() -> ModuleType:
    try:
        folium = import_module("folium")
    except ModuleNotFoundError as exc:
        raise MissingOptionalDependencyError(
            "Mapping stations requires optional dependency folium. Install it with: pip install rivretrieve[map]"
        ) from exc

    return folium


def _map_center(stations: pl.DataFrame) -> list[float]:
    if stations.is_empty():
        return [0.0, 0.0]

    latitude = cast(float, stations["latitude"].mean())
    longitude = cast(float, stations["longitude"].mean())
    return [
        latitude,
        longitude,
    ]


def _station_label(station: dict[str, object]) -> str:
    return f"{station['provider_id']} ({station['station_id']})"


def _station_popup(station: dict[str, object]) -> str:
    lines = [
        f"<strong>{station['provider_id']}</strong>",
        f"Station: {station['station_id']}",
        f"Latitude: {station['latitude']}",
        f"Longitude: {station['longitude']}",
        f"crs: {station['crs']}",
    ]
    return "<br>".join(lines)

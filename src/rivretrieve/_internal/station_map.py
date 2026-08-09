"""station map = render(filter(StationCatalog, provider IDs × bounding box), station identity × coordinates)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from typing import cast

import polars as pl

from rivretrieve._internal.issues import FatalContractError, MissingOptionalDependencyError


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


def _filter_stations(
    stations: pl.DataFrame,
    *,
    providers: str | Sequence[str] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> pl.DataFrame:
    expressions: list[pl.Expr] = []

    provider_values = _normalize_string_filter(providers, label="providers")
    if provider_values is not None:
        expressions.append(pl.col("provider_id").is_in(provider_values))

    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = _validate_bbox(bbox)
        expressions.append(
            (pl.col("longitude") >= min_lon)
            & (pl.col("longitude") <= max_lon)
            & (pl.col("latitude") >= min_lat)
            & (pl.col("latitude") <= max_lat)
        )

    if not expressions:
        return stations

    return stations.filter(*expressions)


def _load_folium() -> ModuleType:
    try:
        folium = import_module("folium")
    except ModuleNotFoundError as exc:
        raise MissingOptionalDependencyError(
            "Mapping stations requires optional dependency folium. Install it with: pip install rivretrieve[map]"
        ) from exc

    return folium


def _normalize_string_filter(value: str | Sequence[str] | None, *, label: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Sequence):
        raise FatalContractError(f"{label} must be a string, a sequence of strings, or None")

    values = tuple(value)
    if not all(isinstance(item, str) for item in values):
        raise FatalContractError(f"{label} must contain only strings")
    return values


def _validate_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if len(bbox) != 4:
        raise FatalContractError("bbox must be a 4-item tuple in (min_lon, min_lat, max_lon, max_lat) order")

    try:
        min_lon, min_lat, max_lon, max_lat = (float(value) for value in bbox)
    except (TypeError, ValueError) as exc:
        raise FatalContractError("bbox values must be numeric in (min_lon, min_lat, max_lon, max_lat) order") from exc

    if min_lon > max_lon or min_lat > max_lat:
        raise FatalContractError(
            "bbox bounds must satisfy min_lon <= max_lon and min_lat <= max_lat "
            "in (min_lon, min_lat, max_lon, max_lat) order"
        )

    return min_lon, min_lat, max_lon, max_lat


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

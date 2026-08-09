from __future__ import annotations

import inspect
from typing import Any

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import FatalContractError, IssuePolicyError, MissingOptionalDependencyError
from rivretrieve._internal.station_map import StationMap


class FakeMap:
    def __init__(self, *, location: list[float], zoom_start: int, control_scale: bool) -> None:
        self.location = location
        self.zoom_start = zoom_start
        self.control_scale = control_scale
        self.markers: list[FakeMarker] = []


class FakeIcon:
    def __init__(self, *, color: str) -> None:
        self.color = color


class FakeMarker:
    def __init__(
        self,
        *,
        location: list[float],
        tooltip: str,
        popup: str,
        icon: FakeIcon,
    ) -> None:
        self.location = location
        self.tooltip = tooltip
        self.popup = popup
        self.icon = icon

    def add_to(self, station_map: FakeMap) -> None:
        station_map.markers.append(self)


class FakeFolium:
    Map = FakeMap
    Marker = FakeMarker
    Icon = FakeIcon


def test_map_survives_map_stations_removal_with_only_required_selection() -> None:
    parameters = inspect.signature(rr.map).parameters

    assert tuple(parameters) == ("selection",)
    assert parameters["selection"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["selection"].default is inspect.Parameter.empty
    assert {"provider", "providers", "bbox", "bounding_box"}.isdisjoint(parameters)


def test_map_rejects_non_rivretrieve_selection() -> None:
    with pytest.raises(TypeError, match="^selection must be a RivRetrieve selection$"):
        rr.map(object())  # type: ignore[arg-type]


def test_map_missing_backend_raises_fatal_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    def import_without_folium(name: str) -> Any:
        if name == "folium":
            raise ModuleNotFoundError("No module named 'folium'")
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("rivretrieve._internal.station_map.import_module", import_without_folium)
    selection = rr.find(provider="ch_foen", station="2016")

    with pytest.raises(MissingOptionalDependencyError) as exc_info:
        rr.map(selection)

    assert isinstance(exc_info.value, FatalContractError)
    message = str(exc_info.value)
    assert "folium" in message
    assert "pip install rivretrieve[map]" in message
    chain: list[BaseException] = []
    current: BaseException | None = exc_info.value
    while current is not None:
        chain.append(current)
        current = current.__cause__
    assert not any(isinstance(exc, IssuePolicyError) for exc in chain)


def test_map_empty_selection_has_no_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rivretrieve._internal.station_map._load_folium", lambda: FakeFolium)
    selection = rr.find(
        provider="usgs_nwis",
        station="01646500",
        product="stage_daily_mean",
    )

    station_map = rr.map(selection)

    assert selection.empty_reason is not None
    assert selection.empty_reason.code == "no_catalogue_edge"
    assert isinstance(station_map, FakeMap)
    assert station_map.location == [0.0, 0.0]
    assert station_map.markers == []


def test_map_ch_foen_selection_renders_unique_unknown_crs_stations_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rivretrieve._internal.station_map._load_folium", lambda: FakeFolium)
    selection = rr.find(provider="ch_foen")
    before = rr.as_frame(selection)
    from rivretrieve._internal.catalogues.artifact import load_packaged_catalogue_artifact
    from rivretrieve._internal.providers.ch_foen import module as ch_foen_module

    stations_before = load_packaged_catalogue_artifact(ch_foen_module._CATALOGUE_PATH, on_issue="raise").stations

    assert before.height == 738
    assert before.select("provider_id", "station_id").unique().height == 246
    assert before.get_column("crs").unique().sort().to_list() == ["unknown"]

    station_map = rr.map(selection)

    assert isinstance(station_map, FakeMap)
    assert len(station_map.markers) == 246
    assert all(marker.popup.endswith("<br>crs: unknown") for marker in station_map.markers)
    assert all(marker.icon.color == "orange" for marker in station_map.markers)
    pl_testing.assert_frame_equal(rr.as_frame(selection), before, check_exact=True)
    stations_after = load_packaged_catalogue_artifact(ch_foen_module._CATALOGUE_PATH, on_issue="raise").stations
    pl_testing.assert_frame_equal(stations_after, stations_before, check_exact=True)
    assert stations_after.get_column("crs").unique().sort().to_list() == ["unknown"]


def test_map_established_crs_uses_distinct_marker_colour_and_exact_popup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rivretrieve._internal.station_map._load_folium", lambda: FakeFolium)
    selection = rr.find(
        provider="usgs_nwis",
        station="01646500",
        product="discharge_daily_mean",
    )

    station_map = rr.map(selection)

    assert isinstance(station_map, FakeMap)
    assert len(station_map.markers) == 1
    marker = station_map.markers[0]
    assert marker.location == [38.94977778, -77.12763889]
    assert marker.tooltip == "usgs_nwis (01646500)"
    assert marker.popup == (
        "<strong>usgs_nwis</strong><br>Station: 01646500"
        "<br>Latitude: 38.94977778<br>Longitude: -77.12763889"
        "<br>crs: EPSG:4269"
    )
    assert marker.icon.color == "blue"
    assert marker.icon.color != "orange"


def test_station_map_real_backend_returns_folium_map_for_selected_station() -> None:
    folium = pytest.importorskip("folium")

    selection = rr.find(provider="ch_foen", station="2016")
    station_map = rr.map(selection)

    assert isinstance(station_map, folium.Map)
    html = station_map.get_root().render()
    assert "ch_foen" in html
    assert "2016" in html


def test_station_map_real_backend_renders_five_column_station_frame() -> None:
    folium = pytest.importorskip("folium")

    station_map = StationMap(_five_column_station_frame()).render()

    assert isinstance(station_map, folium.Map)
    html = station_map.get_root().render()
    assert "stub_provider" in html
    assert "nullable-1" in html


def _five_column_station_frame() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "provider_id": "stub_provider",
                "station_id": "nullable-1",
                "latitude": 47.0,
                "longitude": 8.0,
                "crs": "unknown",
            }
        ],
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "crs": pl.Utf8,
        },
    )

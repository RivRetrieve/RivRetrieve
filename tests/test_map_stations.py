from __future__ import annotations

import inspect
from typing import Any, cast

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.catalogue_reader import CatalogueReader
from rivretrieve._internal.issues import FatalContractError, IssuePolicyError, MissingOptionalDependencyError
from rivretrieve._internal.primitives import CatalogSource, OnIssue
from rivretrieve._internal.results import CatalogResult
from rivretrieve._internal.station_map import StationMap, _filter_stations


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


def test_map_signature_accepts_only_required_selection_without_narrowing() -> None:
    parameters = inspect.signature(rr.map).parameters

    assert tuple(parameters) == ("selection",)
    assert parameters["selection"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["selection"].default is inspect.Parameter.empty
    assert {"provider", "providers", "bbox", "bounding_box"}.isdisjoint(parameters)


def test_map_rejects_non_rivretrieve_selection() -> None:
    with pytest.raises(TypeError, match="^selection must be a RivRetrieve selection$"):
        rr.map(object())  # type: ignore[arg-type]


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


def test_map_stations_signature_has_no_retired_parameters() -> None:
    parameters = inspect.signature(rr.map_stations).parameters

    assert "country" not in parameters
    assert "on_issue" not in parameters


def test_map_stations_missing_backend_raises_fatal_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    def import_without_folium(name: str) -> Any:
        if name == "folium":
            raise ModuleNotFoundError("No module named 'folium'")
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("rivretrieve._internal.station_map.import_module", import_without_folium)

    with pytest.raises(MissingOptionalDependencyError) as exc_info:
        rr.map_stations(providers="ch_foen")

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


def test_filter_stations_providers_uses_exact_provider_id(packaged_stations: pl.DataFrame) -> None:
    selected = _filter_stations(packaged_stations, providers="ch_foen")
    empty = _filter_stations(packaged_stations, providers="unknown_provider")

    assert selected.height == 246
    assert set(selected["provider_id"].unique().to_list()) == {"ch_foen"}
    assert empty.is_empty()


def test_filter_stations_bbox_uses_lon_lat_order_and_inclusive_bounds(packaged_stations: pl.DataFrame) -> None:
    brugg_bbox = (8.1948, 47.4824, 8.1950, 47.4826)
    outside_bbox = (0.0, 0.0, 1.0, 1.0)
    boundary_bbox = (8.1949, 47.4825, 8.1949, 47.4825)

    selected = _filter_stations(packaged_stations, bbox=brugg_bbox)
    outside = _filter_stations(packaged_stations, bbox=outside_bbox)
    boundary = _filter_stations(packaged_stations, bbox=boundary_bbox)

    assert selected["station_id"].to_list() == ["2016"]
    assert outside.is_empty()
    assert boundary["station_id"].to_list() == ["2016"]


def test_filter_stations_combines_provider_and_bbox_filters(packaged_stations: pl.DataFrame) -> None:
    bbox = (8.1948, 47.4824, 8.1950, 47.4826)

    selected = _filter_stations(packaged_stations, providers="ch_foen", bbox=bbox)
    wrong_provider = _filter_stations(packaged_stations, providers="unknown_provider", bbox=bbox)

    assert selected["station_id"].to_list() == ["2016"]
    assert wrong_provider.is_empty()


def test_filter_stations_rejects_invalid_inputs(packaged_stations: pl.DataFrame) -> None:
    with pytest.raises(FatalContractError, match="providers"):
        _filter_stations(packaged_stations, providers=cast(Any, object()))

    with pytest.raises(FatalContractError, match="bbox.*min_lon.*min_lat.*max_lon.*max_lat"):
        _filter_stations(packaged_stations, bbox=(8.2, 47.4, 8.1, 47.5))


def test_map_stations_empty_result_returns_empty_map(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rivretrieve._internal.station_map._load_folium", lambda: FakeFolium)

    station_map = rr.map_stations(providers="unknown_provider")

    assert isinstance(station_map, FakeMap)
    assert station_map.markers == []


def test_map_stations_fake_backend_receives_filtered_station_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rivretrieve._internal.station_map._load_folium", lambda: FakeFolium)

    station_map = rr.map_stations(bbox=(8.1948, 47.4824, 8.1950, 47.4826))

    assert isinstance(station_map, FakeMap)
    assert len(station_map.markers) == 1
    assert station_map.markers[0].tooltip == "ch_foen (2016)"
    assert station_map.markers[0].popup == (
        "<strong>ch_foen</strong><br>Station: 2016<br>Latitude: 47.4825<br>Longitude: 8.1949<br>crs: unknown"
    )
    assert station_map.markers[0].location == [47.4825, 8.1949]
    assert station_map.markers[0].icon.color == "orange"


def test_map_stations_uses_packaged_station_catalogue_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rivretrieve._internal.station_map._load_folium", lambda: FakeFolium)

    station_map = rr.map_stations(providers="ch_foen")

    assert isinstance(station_map, FakeMap)
    assert len(station_map.markers) == 246


def test_map_stations_reads_stations_not_products(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read_stations = CatalogueReader.read_stations
    calls = {"stations": 0, "products": 0, "station_products": 0}

    def read_stations(
        self: CatalogueReader,
        *,
        source: CatalogSource = "packaged",
        on_issue: OnIssue = "warn",
    ) -> CatalogResult[pl.DataFrame]:
        calls["stations"] += 1
        return original_read_stations(self, source=source, on_issue=on_issue)

    def read_products(self: CatalogueReader, **_kwargs: object) -> CatalogResult[pl.DataFrame]:
        calls["products"] += 1
        raise AssertionError("read_products touched")

    def read_station_products(self: CatalogueReader, *args: object, **kwargs: object) -> CatalogResult[pl.DataFrame]:
        calls["station_products"] += 1
        raise AssertionError("read_station_products touched")

    monkeypatch.setattr("rivretrieve._internal.station_map._load_folium", lambda: FakeFolium)
    monkeypatch.setattr(CatalogueReader, "read_stations", read_stations)
    monkeypatch.setattr(CatalogueReader, "read_products", read_products)
    monkeypatch.setattr(CatalogueReader, "read_station_products", read_station_products)

    rr.map_stations(providers="ch_foen")

    assert calls["products"] == 0
    assert calls["station_products"] == 0
    assert calls["stations"] >= 1


def test_station_map_real_backend_returns_folium_map_for_selected_station() -> None:
    folium = pytest.importorskip("folium")

    station_map = rr.map_stations(bbox=(8.1948, 47.4824, 8.1950, 47.4826))

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


@pytest.fixture
def packaged_stations() -> pl.DataFrame:
    return rr.stations().data


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

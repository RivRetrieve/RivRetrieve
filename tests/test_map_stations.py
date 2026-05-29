from __future__ import annotations

import inspect
from datetime import date
from typing import Any, cast

import polars as pl
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


class FakeMarker:
    def __init__(self, *, location: list[float], tooltip: str, popup: str) -> None:
        self.location = location
        self.tooltip = tooltip
        self.popup = popup

    def add_to(self, station_map: FakeMap) -> None:
        station_map.markers.append(self)


class FakeFolium:
    Map = FakeMap
    Marker = FakeMarker


def test_map_stations_signature_has_no_on_issue_parameter() -> None:
    assert "on_issue" not in inspect.signature(rr.map_stations).parameters


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


def test_filter_stations_country_uses_exact_catalogue_value(packaged_stations: pl.DataFrame) -> None:
    selected = _filter_stations(packaged_stations, country="Switzerland")
    case_mismatch = _filter_stations(packaged_stations, country="switzerland")
    absent_alias = _filter_stations(packaged_stations, country="CH")

    assert selected.height == 246
    assert set(selected["country"].unique().to_list()) == {"Switzerland"}
    assert case_mismatch.is_empty()
    assert absent_alias.is_empty()


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


def test_filter_stations_combines_filters_with_and(packaged_stations: pl.DataFrame) -> None:
    bbox = (8.1948, 47.4824, 8.1950, 47.4826)

    selected = _filter_stations(packaged_stations, providers="ch_foen", country="Switzerland", bbox=bbox)
    wrong_country = _filter_stations(packaged_stations, providers="ch_foen", country="CH", bbox=bbox)

    assert selected["station_id"].to_list() == ["2016"]
    assert wrong_country.is_empty()


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
    assert station_map.markers[0].tooltip == "Brugg (2016)"
    assert station_map.markers[0].location == [47.4825, 8.1949]


def test_map_stations_uses_packaged_station_catalogue_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from rivretrieve._internal.providers.ch_foen import module as ch_foen_module
    from rivretrieve._internal.providers.ch_foen import observation_client

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("observation path touched")

    monkeypatch.setattr("rivretrieve._internal.station_map._load_folium", lambda: FakeFolium)
    monkeypatch.setattr(ch_foen_module, "_observation_client_factory", forbidden)
    monkeypatch.setattr(observation_client, "_default_transport", forbidden)
    monkeypatch.setattr(observation_client.ChFoenObservationClient, "resolved_token", property(forbidden))

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

    assert calls == {"stations": 1, "products": 0, "station_products": 0}


def test_station_map_real_backend_returns_folium_map_for_selected_station() -> None:
    folium = pytest.importorskip("folium")

    station_map = rr.map_stations(bbox=(8.1948, 47.4824, 8.1950, 47.4826))

    assert isinstance(station_map, folium.Map)
    html = station_map.get_root().render()
    assert "Brugg" in html
    assert "2016" in html


def test_station_map_real_backend_renders_all_null_nullable_columns() -> None:
    folium = pytest.importorskip("folium")

    station_map = StationMap(_nullable_station_frame()).render()

    assert isinstance(station_map, folium.Map)
    html = station_map.get_root().render()
    assert "Null Station" in html


@pytest.fixture
def packaged_stations() -> pl.DataFrame:
    return rr.stations().data


def _nullable_station_frame() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "provider_id": "stub_provider",
                "station_id": "nullable-1",
                "name": "Null Station",
                "latitude": 47.0,
                "longitude": 8.0,
                "country": "Switzerland",
                "elevation_m": None,
                "drainage_area_km2": None,
                "start_date": date(2026, 1, 1),
                "end_date": None,
                "metadata": "{}",
            }
        ],
        schema={
            "provider_id": pl.Utf8,
            "station_id": pl.Utf8,
            "name": pl.Utf8,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "country": pl.Utf8,
            "elevation_m": pl.Float64,
            "drainage_area_km2": pl.Float64,
            "start_date": pl.Date,
            "end_date": pl.Date,
            "metadata": pl.Utf8,
        },
    )

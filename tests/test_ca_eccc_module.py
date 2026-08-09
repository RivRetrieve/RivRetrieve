"""Tests for ca_eccc provider registration and module contract."""

from __future__ import annotations

import rivretrieve as rr
from rivretrieve._internal.provider_module import ProviderModule
from rivretrieve._internal.providers.ca_eccc import module as ca_eccc_module
from rivretrieve._internal.providers.ca_eccc.config import config
from rivretrieve._internal.providers.ca_eccc.fetch import fetch
from rivretrieve._internal.providers.ca_eccc.parse import parse


def test_ca_eccc_in_providers_list() -> None:
    assert "ca_eccc" in rr.providers()


def test_ca_eccc_info_name() -> None:
    info = ca_eccc_module.info()
    assert "Canada" in info.name or "ECCC" in info.name


def test_ca_eccc_catalogue_version() -> None:
    info = ca_eccc_module.info()
    assert info.catalogue_version == "2026-08-02"


def test_ca_eccc_live_stations_capability() -> None:
    info = ca_eccc_module.info()
    assert info.live_stations is False


def test_ca_eccc_stations_returns_catalog_result() -> None:
    result = ca_eccc_module.stations()
    assert hasattr(result, "data")
    assert hasattr(result, "provenance")
    assert hasattr(result, "issues")


def test_ca_eccc_stations_count() -> None:
    result = ca_eccc_module.stations()
    assert len(result.data) == 8057


def test_ca_eccc_products_count() -> None:
    result = ca_eccc_module.products()
    assert len(result.data) == 2


def test_ca_eccc_products_include_canonical() -> None:
    result = ca_eccc_module.products()
    product_ids = set(result.data["product_id"].to_list())
    assert "discharge_daily_mean" in product_ids
    assert "stage_daily_mean" in product_ids


def test_ca_eccc_station_products_count() -> None:
    result = ca_eccc_module.station_products()
    assert len(result.data) == 16114


def test_ca_eccc_station_products_availability_unknown() -> None:
    """OGC endpoint does not expose per-variable availability → all unknown."""
    result = ca_eccc_module.station_products()
    availabilities = set(result.data["availability"].cast(str).to_list())
    assert availabilities == {"unknown"}


def test_ca_eccc_stations_schema_has_expected_columns() -> None:
    result = ca_eccc_module.stations()
    assert result.data.columns == ["provider_id", "station_id", "latitude", "longitude", "crs"]


def test_ca_eccc_station_grand_river_present() -> None:
    result = ca_eccc_module.stations()
    ids = result.data["station_id"].to_list()
    assert "02GA010" in ids


def test_ca_eccc_station_crs_is_documented_wgs84() -> None:
    result = ca_eccc_module.stations()
    assert result.data["crs"].null_count() == 0
    assert result.data["crs"].unique().to_list() == ["EPSG:4326"]


def test_ca_eccc_exposes_only_the_engine_stage_contract() -> None:
    assert ca_eccc_module.config is config
    assert ca_eccc_module.fetch is fetch
    assert ca_eccc_module.parse is parse
    assert ca_eccc_module.observation_source == "local"
    assert not hasattr(ca_eccc_module, "observations")
    assert isinstance(ca_eccc_module, ProviderModule)


def test_ca_eccc_cache_lifecycle_remains_reachable(monkeypatch) -> None:
    class FakeHydatClient:
        def cache_status(self) -> str:
            return "cache-status"

        def refresh_cache(self) -> list[str]:
            return ["cache-refresh"]

    monkeypatch.setattr(ca_eccc_module, "HydatClient", FakeHydatClient)

    assert ca_eccc_module.cache_status() == "cache-status"
    assert ca_eccc_module.refresh_cache() == ["cache-refresh"]

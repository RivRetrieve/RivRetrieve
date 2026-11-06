"""Offline public discovery and catalogue-only boundary checks for Argentina INA Alerta5."""

from __future__ import annotations

import socket

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def test_ar_ina_offline_discovery_stations_products_and_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbid_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("ar_ina discovery must not attempt network access")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(socket, "create_connection", forbid_network)

    providers = rr.providers()
    row = providers.filter(pl.col("provider_id") == "ar_ina").row(0, named=True)
    assert row["credentials"] == []
    assert row["access"] == "open"

    selection = rr.find(provider="ar_ina")
    frame = rr.as_frame(selection)
    assert frame["station_id"].n_unique() == 829
    assert len(selection.series) == 2611
    assert set(rr.products("ar_ina")) == {
        "discharge_daily_mean",
        "discharge_instantaneous",
        "discharge_monthly_max",
        "discharge_monthly_mean",
        "discharge_monthly_min",
        "stage_4hourly",
        "stage_daily_mean",
        "stage_hourly",
        "stage_instantaneous",
        "stage_monthly_max",
        "stage_monthly_mean",
        "stage_monthly_min",
        "stage_weekly_mean",
    }

    # Coordinate-less station 96 (Colorado on BERMEJO) remains discoverable with null coordinates.
    station_96 = frame.filter(pl.col("station_id") == "96")
    assert station_96.height == 5
    assert len(selection.locations) == 829
    loc_96 = next(loc for loc in selection.locations if loc.station_id == "96")
    assert loc_96.latitude is None
    assert loc_96.longitude is None

    # Shared border gauge 1699 (Nueva Palmira, CARU) is retained alongside Argentina gauges.
    station_1699 = rr.find(provider="ar_ina", station="1699")
    assert len(station_1699.series) >= 1

    # Station metadata projects nombre and rio verbatim while withholding drainage_area and elevation.
    meta_summary = rr.metadata(rr.find(provider="ar_ina", station="29"))
    assert meta_summary.height == 1
    meta_row = meta_summary.row(0, named=True)
    assert meta_row["station_name"] == "Paraná"
    assert meta_row["water_body_name_value"] == ["PARANAINF"]
    assert meta_row["drainage_area_value"] is None
    assert meta_row["elevation_value"] is None

    meta_source = rr.metadata(rr.find(provider="ar_ina", station="5904"), view="source")
    rio_5904 = meta_source.filter(pl.col("attribute_role") == "water_body_name").row(0, named=True)
    assert rio_5904["source_value"] == '"null"'
    assert rio_5904["state"] == "value"

    descriptor = rr.describe("ar_ina")
    assert descriptor["license"] == "Creative Commons Atribución 4.0 Internacional"

    # Step 2 registers ar_ina as CatalogueOnly; observation retrieval fails closed without network I/O.
    gauge = rr.find(provider="ar_ina", station="29", quantity="stage")
    with pytest.raises(ObservationsUnavailableError):
        rr.fetch(gauge, start="2024-01-01", end="2024-01-10")

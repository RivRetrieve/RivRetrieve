"""Offline public discovery checks for Belgium - Wallonia (`be_wal`)."""

from __future__ import annotations

import socket

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.providers.be_wal.series import PRODUCT_SPECS
from rivretrieve._internal.selection import UnknownStationError, _Selection

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def test_be_wal_offline_discovery_stations_products_metadata_and_predicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("be_wal discovery must not attempt network access")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(socket.socket, "connect_ex", forbid_network)
    monkeypatch.setattr(socket, "create_connection", forbid_network)

    providers = rr.providers()
    row = providers.filter(pl.col("provider_id") == "be_wal").row(0, named=True)
    assert row == {"provider_id": "be_wal", "credentials": [], "access": "open"}

    products = set(rr.products("be_wal"))
    assert products == {spec.product_id for spec in PRODUCT_SPECS}
    assert len(products) == 62

    selection = rr.find(provider="be_wal")
    frame = rr.as_frame(selection)
    assert frame["station_id"].n_unique() == 338
    assert len(selection.series) == 8_198
    assert len(selection.locations) == 338
    assert {loc.crs for loc in selection.locations} == {"EPSG:4326"}
    assert all(loc.latitude is not None and loc.longitude is not None for loc in selection.locations)

    # Single-source-per-field metadata at BIERGES (1046) and source_null drainage area at LIEGE (7102).
    meta_1046 = rr.metadata(rr.find(provider="be_wal", station="1046"))
    assert meta_1046.height == 1
    row_1046 = meta_1046.row(0, named=True)
    assert row_1046["station_name"] == "BIERGES"
    assert row_1046["water_body_name_value"] == ["Dyle"]
    assert row_1046["drainage_area_value"] == ["310.19"]
    assert row_1046["drainage_area_unit"] == ["km2"]
    assert row_1046["elevation_value"] is None

    source_meta_7102 = rr.metadata(rr.find(provider="be_wal", station="7102"), view="source")
    assert source_meta_7102.filter(pl.col("attribute_role") == "drainage_area")["state"].to_list() == ["source_null"]
    assert source_meta_7102.filter(pl.col("attribute_role") == "elevation")["state"].to_list() == ["no_metadata"]

    all_source_meta = rr.metadata(selection, view="source")
    assert (
        all_source_meta.filter(
            (pl.col("attribute_role") == "drainage_area") & (pl.col("state") == "source_null")
        ).height
        == 81
    )
    assert all_source_meta.filter(pl.col("attribute_role") == "elevation")["state"].unique().to_list() == [
        "no_metadata"
    ]

    # Physical predicate filtering: gauge-zero vs above-sea-level stage and complete cadence facts.
    daily_stage = rr.find(provider="be_wal", quantity="stage", frequency="daily", statistic="mean")
    daily_stage_df = rr.series(daily_stage)
    assert daily_stage_df.height >= 1
    assert set(daily_stage_df["product_id"]) == {"stage_daily_mean", "stage_absolute_daily_mean"}
    assert set(daily_stage_df["vertical_reference"]) == {"gauge_zero", "above_sea_level"}
    assert daily_stage_df["vertical_datum"].null_count() == daily_stage_df.height
    assert daily_stage_df["time_zone"].unique().to_list() == ["+01:00"]
    assert daily_stage_df["day_definition"].unique().to_list() == ["+01:00"]
    assert daily_stage_df["timestamp_anchor"].unique().to_list() == ["start"]
    assert daily_stage_df["temporal_support"].unique().to_list() == ["interval"]
    assert daily_stage_df["unit"].unique().to_list() == ["m"]

    liege_abs = rr.find(provider="be_wal", station="7102", quantity="stage", frequency="hourly", statistic="mean")
    liege_abs_df = rr.series(liege_abs)
    assert liege_abs_df["product_id"].to_list() == ["stage_absolute_hourly_mean"]
    assert liege_abs_df["vertical_reference"].to_list() == ["above_sea_level"]
    assert liege_abs_df["vertical_datum"].to_list() == [None]
    assert liege_abs_df["time_zone"].to_list() == ["+01:00"]

    complete_q = rr.find(provider="be_wal", station="1046", quantity="discharge", frequency=None, statistic=None)
    complete_q_df = rr.series(complete_q).filter(pl.col("product_id") == "discharge_complete")
    assert complete_q_df["temporal_support_state"].to_list() == ["not_established"]
    assert complete_q_df["day_definition_state"].to_list() == ["not_established"]
    assert complete_q_df["timestamp_anchor_state"].to_list() == ["not_established"]
    assert complete_q_df["time_zone"].to_list() == ["+01:00"]

    # Catalogue identity survives bundle serialization.
    q_daily = rr.find(provider="be_wal", station="1046", quantity="discharge", frequency="daily", statistic="mean")
    restored = rr.from_bundle(rr.to_bundle(q_daily))
    assert isinstance(restored, _Selection)
    assert restored.known_series == q_daily.known_series
    assert [(s.identity.namespace, s.identity.published_id) for s in restored.series] == [("KiWIS.ts_id", "296450010")]

    # Excluded reservoirs, virtual-only gauges, hydraulic-axis-only stations, zero-series shells, and coord-less shells.
    for excluded_station in ("640601", "640C01", "7406", "7326", "630201", "9109"):
        with pytest.raises(UnknownStationError):
            rr.find(provider="be_wal", station=excluded_station)

    descriptor = rr.describe("be_wal")
    assert descriptor.get("license") is None
    assert (
        descriptor["citation"]
        == "« Sources des données : Service public de Wallonie » ou « Sources des données : SPW »"
    )
    assert descriptor["creator"] == [
        {"@type": "sc:Organization", "name": "Service public de Wallonie (SPW) — Hydrométrie"}
    ]

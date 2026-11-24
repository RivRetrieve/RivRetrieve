"""Offline public discovery checks for Ireland Office of Public Works (`ie_opw`)."""

from __future__ import annotations

import socket

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.discovery import _Selection
from rivretrieve._internal.selection import UnknownStationError

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def test_ie_opw_offline_discovery_stations_products_metadata_and_predicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("ie_opw discovery must not attempt network access")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(socket, "create_connection", forbid_network)

    providers = rr.providers()
    row = providers.filter(pl.col("provider_id") == "ie_opw").row(0, named=True)
    assert row == {"provider_id": "ie_opw", "credentials": [], "access": "open"}

    products = set(rr.products("ie_opw"))
    assert products == {
        "discharge_daily_max",
        "discharge_daily_mean",
        "discharge_daily_min",
        "discharge_instantaneous",
        "stage_daily_max",
        "stage_daily_mean",
        "stage_daily_min",
        "stage_instantaneous",
        "water_temperature_daily_max",
        "water_temperature_daily_mean",
        "water_temperature_daily_min",
        "water_temperature_instantaneous",
    }

    selection = rr.find(provider="ie_opw")
    frame = rr.as_frame(selection)
    assert frame["station_id"].n_unique() == 385
    assert len(selection.series) == 4572
    assert len(selection.locations) == 385
    assert all(loc.latitude is not None and loc.longitude is not None for loc in selection.locations)

    # Single-source-per-field metadata at Sandy Mills (01041).
    meta_01041 = rr.metadata(rr.find(provider="ie_opw", station="01041"))
    assert meta_01041.height == 1
    row_01041 = meta_01041.row(0, named=True)
    assert row_01041["station_name"] == "Sandy Mills"
    assert row_01041["water_body_name_value"] == ["DEELE"]
    assert row_01041["drainage_area_value"] == ['"113.00"']
    assert row_01041["drainage_area_unit"] == ["km²"]
    assert row_01041["elevation_value"] is None

    # Physical predicate filtering, unit normalization, UTC time_zone, and Ordnance Datum stage reference.
    daily_stage = rr.find(provider="ie_opw", quantity="stage", frequency="P1D", statistic="mean")
    assert len(daily_stage.series) == 385
    daily_stage_df = rr.series(daily_stage)
    assert daily_stage_df["time_zone"].unique().to_list() == ["+00:00"]
    assert daily_stage_df["time_zone_state"].unique().to_list() == ["known"]
    assert daily_stage_df["vertical_reference"].unique().to_list() == ["above_sea_level"]
    assert daily_stage_df["vertical_datum"].null_count() == 385
    assert daily_stage_df["source_unit"].unique().to_list() == ["m"]
    assert daily_stage_df["unit"].unique().to_list() == ["m"]

    daily_q = rr.find(provider="ie_opw", quantity="discharge", frequency="P1D", statistic="mean")
    assert len(daily_q.series) == 372
    daily_q_df = rr.series(daily_q)
    assert daily_q_df["source_unit"].unique().to_list() == ["cumec"]
    assert daily_q_df["unit"].unique().to_list() == ["m3/s"]

    # Calendar P1D and elapsed PT24H belong to disjoint duration families; legacy aliases fail closed.
    assert rr.find(provider="ie_opw", station="01041", frequency="PT24H", on_issue="ignore").series == ()
    with pytest.raises(ValueError, match="Unsupported frequency"):
        rr.find(provider="ie_opw", station="01041", frequency="daily")

    # Lossless bundle roundtrip preserves catalogue source identity.
    s01041 = rr.find(provider="ie_opw", station="01041", quantity="stage", frequency="P1D", statistic="mean")
    s01041_restored = rr.from_bundle(rr.to_bundle(s01041))
    assert isinstance(s01041_restored, _Selection)
    assert s01041_restored.known_series == s01041.known_series
    assert [(s.identity.namespace, s.identity.published_id) for s in s01041_restored.series] == [
        ("ie_opw.hydro_data.S", "WEB.Day.Mean")
    ]

    # Excluded lake (30089), tidal (06062), and rainfall (>41000) gauges are absent from the river catalogue.
    for excluded in ("30089", "06062", "80101"):
        with pytest.raises(UnknownStationError):
            rr.find(provider="ie_opw", station=excluded)

    descriptor = rr.describe("ie_opw")
    assert descriptor["license"] == "CC BY 4.0"
    assert isinstance(descriptor["citation"], str)
    assert "Office of Public Works" in descriptor["citation"]

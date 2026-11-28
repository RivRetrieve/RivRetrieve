"""Offline public discovery checks for Estonia Keskkonnaagentuur (`ee_est`)."""

from __future__ import annotations

import socket

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.selection import UnknownStationError

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def test_ee_est_offline_discovery_stations_products_metadata_and_predicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("ee_est discovery must not attempt network access")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(socket, "create_connection", forbid_network)

    providers = rr.providers()
    row = providers.filter(pl.col("provider_id") == "ee_est").row(0, named=True)
    assert row == {"provider_id": "ee_est", "credentials": [], "access": "open"}

    products = set(rr.products("ee_est"))
    assert products == {
        "discharge_daily_max",
        "discharge_daily_mean",
        "discharge_daily_min",
        "discharge_hourly_max",
        "discharge_hourly_mean",
        "discharge_hourly_min",
        "stage_daily_max",
        "stage_daily_mean",
        "stage_daily_min",
        "stage_hourly_max",
        "stage_hourly_mean",
        "stage_hourly_min",
        "water_temperature_daily_max",
        "water_temperature_daily_mean",
        "water_temperature_daily_min",
        "water_temperature_hourly_max",
        "water_temperature_hourly_mean",
        "water_temperature_hourly_min",
    }

    selection = rr.find(provider="ee_est")
    frame = rr.as_frame(selection)
    assert frame["station_id"].n_unique() == 60
    assert len(selection.series) == 1032
    assert len(selection.locations) == 60
    assert all(loc.latitude is not None and loc.longitude is not None for loc in selection.locations)

    # Single-source-per-field metadata at Ahja HJ (SJA8821000) and Rannu-Jõesuu HJ (SJA5524000).
    meta_ahja = rr.metadata(rr.find(provider="ee_est", station="SJA8821000"))
    assert meta_ahja.height == 1
    ahja_row = meta_ahja.row(0, named=True)
    assert ahja_row["station_name"] == "Ahja HJ"
    assert ahja_row["water_body_name_value"] == ["Ahja jõgi"]
    assert ahja_row["drainage_area_value"] == ["896.51"]
    assert ahja_row["drainage_area_unit"] == ["km2"]
    assert ahja_row["elevation_value"] is None

    # Physical predicate filtering and vertical reference / time_zone facts.
    daily_stage = rr.find(provider="ee_est", quantity="stage", frequency="P1D", statistic="mean")
    assert len(daily_stage.series) == 59
    daily_series_df = rr.series(daily_stage)
    assert daily_series_df["time_zone"].unique().to_list() == [None]
    assert daily_series_df["time_zone_state"].unique().to_list() == ["not_established"]
    assert daily_series_df["vertical_reference"].unique().to_list() == ["gauge_zero"]
    assert daily_series_df["vertical_datum"].null_count() == 59

    hourly_stage = rr.find(provider="ee_est", quantity="stage", frequency="PT1H", statistic="mean")
    assert len(hourly_stage.series) == 56
    hourly_series_df = rr.series(hourly_stage)
    assert hourly_series_df["time_zone"].unique().to_list() == ["+00:00"]
    assert hourly_series_df["source_unit"].unique().to_list() == ["cm"]
    assert hourly_series_df["unit"].unique().to_list() == ["m"]

    # Equivalent elapsed ISO 8601 durations canonicalize to PT1H, while legacy spellings reject.
    equivalent_hourly = rr.find(provider="ee_est", quantity="stage", frequency="PT60M", statistic="mean")
    assert equivalent_hourly.series == hourly_stage.series
    for legacy_freq in ("daily", "hourly"):
        with pytest.raises(ValueError, match="Unsupported frequency"):
            rr.find(provider="ee_est", frequency=legacy_freq)

    # Dual-code Rannu-Jõesuu HJ (SJA5524000) carries active jaam_kood 41022 in catalogue identity.
    sja5524000 = rr.find(provider="ee_est", station="SJA5524000", quantity="stage", frequency="PT1H", statistic="mean")
    sja5524000_restored = rr.from_bundle(rr.to_bundle(sja5524000))
    assert sja5524000_restored.known_series == sja5524000.known_series
    assert [(s.identity.namespace, s.identity.published_id) for s in sja5524000_restored.series] == [
        ("EE_EST.f_hydroseire.series", "41022:WL avg")
    ]

    # Excluded lake gauge SJA4875000 (Tamula) is absent from the river catalogue.
    with pytest.raises(UnknownStationError):
        rr.find(provider="ee_est", station="SJA4875000")

    descriptor = rr.describe("ee_est")
    assert descriptor["license"] == "CC BY 4.0"
    assert descriptor["citation"] == "Estonian Environment Agency (Keskkonnaagentuur)"

    from rivretrieve._internal.providers.ee_est.declaration import _STATION_CODES, _load_station_codes, declaration

    assert len(_STATION_CODES) == 60
    assert _STATION_CODES["SJA5524000"] == (41022, 41960)
    assert _STATION_CODES["SJA8821000"] == (41061,)
    assert _load_station_codes(declaration.catalogue) == _STATION_CODES

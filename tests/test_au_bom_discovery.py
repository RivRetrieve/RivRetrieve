"""Offline discovery contracts for au_bom: find/pick/providers/as_frame stay network-free."""

from __future__ import annotations

import socket

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.providers.au_bom.declaration import declaration
from rivretrieve._internal.providers.registration import LiveStages


def _deny_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("au_bom discovery must not use the network")


def test_declaration_is_live_stages_with_no_credentials() -> None:
    assert isinstance(declaration.observations, LiveStages)
    assert declaration.required_credentials == ()
    assert declaration.optional_credentials == ()


def test_au_bom_is_registered_and_discoverable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _deny_network)
    monkeypatch.setattr(socket, "create_connection", _deny_network)

    providers = rr.providers()
    row = providers.filter(pl.col("provider_id") == "au_bom")
    assert row.height == 1
    assert row["access"].item() == "open"
    assert row["credentials"].to_list() == [[]]


def test_eighteen_products_across_three_quantities() -> None:
    selection = rr.find(provider="au_bom")
    frame = rr.as_frame(selection)
    product_ids = set(frame["product_id"].unique().to_list())
    assert len(product_ids) == 18

    discharge = rr.find(provider="au_bom", quantity="discharge")
    stage = rr.find(provider="au_bom", quantity="stage")
    temperature = rr.find(provider="au_bom", quantity="temperature")
    assert rr.as_frame(discharge)["product_id"].n_unique() == 7
    assert rr.as_frame(stage)["product_id"].n_unique() == 6
    assert rr.as_frame(temperature)["product_id"].n_unique() == 5


def test_stage_has_no_09hr_variant_and_temperature_has_no_hourly() -> None:
    frame = rr.as_frame(rr.find(provider="au_bom"))
    product_ids = set(frame["product_id"].unique().to_list())
    assert "stage_daily_mean_09hr" not in product_ids
    assert "water_temperature_hourly_mean" not in product_ids
    assert "discharge_daily_mean_09hr" in product_ids
    assert "discharge_hourly_mean" in product_ids

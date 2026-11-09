"""Offline discovery remains independent of the live Colombia IDEAM stages."""

import polars as pl
import pytest


def test_declaration_exposes_live_stages_without_credentials():
    from rivretrieve._internal.providers.co_ideam.declaration import declaration
    from rivretrieve._internal.providers.registration import LiveStages

    assert isinstance(declaration.observations, LiveStages)
    assert declaration.required_credentials == ()


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_discovery_and_metadata_remain_offline(policy, monkeypatch):
    import socket

    import rivretrieve as rr

    def refuse_network(*args, **kwargs):
        pytest.fail("IDEAM offline discovery workflow attempted network access")

    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_network)

    selection = rr.find(provider="co_ideam", on_issue=policy)
    frame = rr.as_frame(selection)
    assert len(selection.locations) == 1_372
    assert frame["station_id"].n_unique() == 1_372
    assert {loc.crs for loc in selection.locations} == {"unknown"}

    series = rr.series(selection)
    assert series.height == 19_690
    assert series["provider_id"].unique().to_list() == ["co_ideam"]
    assert set(series["quantity"]) == {"discharge", "stage"}
    assert all(inventory.completeness.value == "incomplete" for inventory in selection.inventories)

    meta_source = rr.metadata(selection, view="source")
    drainage = meta_source.filter(pl.col("attribute_role") == "drainage_area")
    assert drainage.height == 1_372
    assert set(drainage["state"]) == {"no_metadata"}

    elevations = meta_source.filter(pl.col("attribute_role") == "elevation")
    assert elevations.height == 1_372
    assert set(elevations["state"]) == {"value"}
    assert set(elevations["source_unit"]) == {None}
    assert set(elevations["source_datum"]) == {None}

    blank_waterbody = meta_source.filter(
        (pl.col("station_id") == "0013085010") & (pl.col("attribute_role") == "water_body_name")
    )
    assert blank_waterbody["state"].to_list() == ["source_null"]

    named_waterbody = meta_source.filter(
        (pl.col("station_id") == "0024017690") & (pl.col("attribute_role") == "water_body_name")
    )
    assert named_waterbody["state"].to_list() == ["value"]

    daily_mean_q = rr.find(
        provider="co_ideam",
        station="0011017010",
        quantity="discharge",
        frequency="daily",
        statistic="mean",
        on_issue=policy,
    )
    assert [item.product_id for item in daily_mean_q.series] == ["q_media_d"]
    assert [item.identity.published_id for item in daily_mean_q.series] == ["Q_MEDIA_D"]

    all_q = rr.find(provider="co_ideam", station="0011017010", quantity="discharge", on_issue=policy)
    by_product = {item.product_id: item for item in all_q.series}
    assert len(by_product) == 10
    assert by_product["caudal_h"].identity.published_id == "CAUDAL_H"
    assert by_product["caudal_h"].facts[0].frequency.value is None
    assert by_product["caudal_h"].facts[0].statistic.value is None
    assert by_product["caudal_h"].facts[0].time_zone.value is None

    tz_filtered = rr.find(provider="co_ideam", station="0011017010", time_zone="America/Bogota", on_issue=policy)
    assert tz_filtered.series == ()

    description = rr.describe("co_ideam")
    assert description["license"] == "Creative Commons Attribution | Share Alike 4.0 International"
    assert (
        description["citation"] == "Instituto de Hidrología, Meteorología y Estudios Ambientales - IDEAM, Bogotá D.C."
    )

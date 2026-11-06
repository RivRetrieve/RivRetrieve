"""Offline discovery and explicit retrieval refusal for the Colombia IDEAM catalogue."""

import polars as pl
import pytest


def test_declaration_exposes_catalogue_only_without_credentials():
    from rivretrieve._internal.providers.co_ideam.declaration import declaration
    from rivretrieve._internal.providers.registration import CatalogueOnly

    assert isinstance(declaration.observations, CatalogueOnly)
    assert declaration.required_credentials == ()


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_discovery_metadata_and_retrieval_refusal_remain_offline(policy, monkeypatch):
    import socket

    import rivretrieve as rr
    from rivretrieve._internal.issues import ObservationsUnavailableError

    def refuse_network(*args, **kwargs):
        pytest.fail("IDEAM catalogue-only workflow attempted network access")

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

    discharge = rr.find(provider="co_ideam", quantity="discharge", station="0024017690", on_issue=policy)
    for cache in ("bypass", "reuse", "refresh"):
        with pytest.raises(ObservationsUnavailableError, match="co_ideam"):
            rr.fetch(discharge, start="2020-01-01", end="2020-01-02", cache=cache, on_issue=policy)

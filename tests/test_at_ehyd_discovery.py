"""Offline discovery and explicit retrieval refusal for the Austria eHYD catalogue."""

import polars as pl
import pytest


def test_declaration_exposes_catalogue_only_without_credentials():
    from rivretrieve._internal.providers.at_ehyd.declaration import declaration
    from rivretrieve._internal.providers.registration import CatalogueOnly

    assert isinstance(declaration.observations, CatalogueOnly)
    assert declaration.required_credentials == ()


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_discovery_metadata_and_retrieval_refusal_remain_offline(policy, monkeypatch):
    import socket

    import rivretrieve as rr
    from rivretrieve._internal.issues import ObservationsUnavailableError

    def refuse_network(*args, **kwargs):
        pytest.fail("eHYD catalogue-only workflow attempted network access")

    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_network)

    selection = rr.find(provider="at_ehyd", on_issue=policy)
    frame = rr.as_frame(selection)
    assert len(selection.locations) == 746
    assert frame["station_id"].n_unique() == 744
    assert {loc.crs for loc in selection.locations} == {"EPSG:4326"}

    series = rr.series(selection)
    assert series.height == 4837
    assert series["provider_id"].unique().to_list() == ["at_ehyd"]
    assert set(series["quantity"]) == {"discharge", "stage", "temperature"}
    assert all(inventory.completeness.value == "incomplete" for inventory in selection.inventories)

    meta_source = rr.metadata(selection, view="source")
    telemetry_areas = meta_source.filter(
        (pl.col("station_id") == "200675") & (pl.col("attribute_role") == "drainage_area")
    )
    assert telemetry_areas["state"].to_list() == ["no_metadata"]

    owf_areas = meta_source.filter((pl.col("station_id") == "209486") & (pl.col("attribute_role") == "drainage_area"))
    assert owf_areas["state"].to_list() == ["value"]
    assert owf_areas["source_unit"].to_list() == ["km²"]

    discharge = rr.find(provider="at_ehyd", quantity="discharge", station="209486", on_issue=policy)
    for cache in ("bypass", "reuse", "refresh"):
        with pytest.raises(ObservationsUnavailableError, match="at_ehyd"):
            rr.fetch(discharge, start="2020-01-01", end="2020-01-02", cache=cache, on_issue=policy)

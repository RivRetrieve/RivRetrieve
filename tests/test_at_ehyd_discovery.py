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

    daily_mean_q = rr.find(
        provider="at_ehyd",
        station="209486",
        quantity="discharge",
        frequency="daily",
        statistic="mean",
        on_issue=policy,
    )
    assert [item.product_id for item in daily_mean_q.series] == ["owf_abfl_tagesmittel"]
    assert [item.identity.namespace for item in daily_mean_q.series] == ["ehyd.owf"]

    all_q_209486 = rr.find(provider="at_ehyd", station="209486", quantity="discharge", on_issue=policy)
    by_product = {item.product_id: item for item in all_q_209486.series}
    assert set(by_product) == {
        "owf_abfl_tagesmittel",
        "owf_abfl_monatsminima",
        "owf_abfl_monatsmaxima",
        "pegel_bgis_abfluss",
        "pegel_longterm_abfluss",
    }
    assert by_product["pegel_bgis_abfluss"].identity.published_id == "data"
    assert by_product["pegel_bgis_abfluss"].facts[0].time_zone.value == "UTC+01:00"
    assert by_product["pegel_longterm_abfluss"].identity.published_id == "current_value"
    assert by_product["pegel_longterm_abfluss"].facts[0].frequency.value == "daily"
    assert by_product["pegel_longterm_abfluss"].facts[0].statistic.value is None

    # 207340 Wilhering retains stage minimum identity while withholding monthly frequency
    min_w_207340 = rr.find(
        provider="at_ehyd",
        station="207340",
        quantity="stage",
        statistic="min",
        on_issue=policy,
    )
    assert [item.product_id for item in min_w_207340.series] == ["owf_wasserst_monatsminima"]
    assert min_w_207340.series[0].facts[0].vertical_reference.value == "gauge_zero"
    assert min_w_207340.series[0].facts[0].frequency.value is None

    monthly_min_w_207340 = rr.find(
        provider="at_ehyd",
        station="207340",
        quantity="stage",
        frequency="monthly",
        statistic="min",
        on_issue=policy,
    )
    assert monthly_min_w_207340.series == ()

    discharge = rr.find(provider="at_ehyd", quantity="discharge", station="209486", on_issue=policy)
    for cache in ("bypass", "reuse", "refresh"):
        with pytest.raises(ObservationsUnavailableError, match="at_ehyd"):
            rr.fetch(discharge, start="2020-01-01", end="2020-01-02", cache=cache, on_issue=policy)

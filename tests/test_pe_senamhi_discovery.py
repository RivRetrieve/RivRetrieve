"""Offline discovery and explicit retrieval refusal for the SENAMHI catalogue."""

import pytest


def test_declaration_exposes_catalogue_only_without_credentials():
    from rivretrieve._internal.providers.pe_senamhi.declaration import declaration
    from rivretrieve._internal.providers.registration import CatalogueOnly

    assert isinstance(declaration.observations, CatalogueOnly)
    assert declaration.required_credentials == ()


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_discovery_and_retrieval_refusal_remain_offline(policy, monkeypatch):
    import socket

    import rivretrieve as rr
    from rivretrieve._internal.issues import ObservationsUnavailableError

    def refuse_network(*args, **kwargs):
        pytest.fail("SENAMHI catalogue-only workflow attempted network access")

    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_network)
    selection = rr.find(provider="pe_senamhi", quantity="discharge", on_issue=policy)
    series = rr.series(selection)
    assert series.height > 0
    assert series["provider_id"].unique().to_list() == ["pe_senamhi"]
    assert all(inventory.completeness.value == "incomplete" for inventory in selection.inventories)
    for cache in ("bypass", "reuse", "refresh"):
        with pytest.raises(ObservationsUnavailableError, match="pe_senamhi"):
            rr.fetch(selection, start="2020-01-01", end="2020-01-02", cache=cache, on_issue=policy)

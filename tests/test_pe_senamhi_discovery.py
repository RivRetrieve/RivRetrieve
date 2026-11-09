"""Offline discovery remains independent of the live SENAMHI stages."""

import pytest


def test_declaration_exposes_live_stages_without_credentials():
    from rivretrieve._internal.providers.pe_senamhi.declaration import declaration
    from rivretrieve._internal.providers.registration import LiveStages

    assert isinstance(declaration.observations, LiveStages)
    assert declaration.required_credentials == ()


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_discovery_remains_offline(policy, monkeypatch):
    import socket

    import rivretrieve as rr

    def refuse_network(*args, **kwargs):
        pytest.fail("SENAMHI discovery attempted network access")

    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_network)
    selection = rr.find(provider="pe_senamhi", quantity="discharge", on_issue=policy)
    series = rr.series(selection)
    assert series.height > 0
    assert series["provider_id"].unique().to_list() == ["pe_senamhi"]
    assert all(inventory.completeness.value == "incomplete" for inventory in selection.inventories)

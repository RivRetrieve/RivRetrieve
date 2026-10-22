"""Swiss discovery does not route official identities to an observation service."""

import socket

import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import ObservationsUnavailableError
from rivretrieve._internal.providers.ch_foen.declaration import declaration
from rivretrieve._internal.providers.registration import CatalogueOnly


def test_swiss_catalogue_has_no_observation_route():
    assert isinstance(declaration.observations, CatalogueOnly)
    assert declaration.public_archive_access is None
    assert declaration.required_credentials == ()


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_swiss_discovery_and_fetch_refusal_are_offline(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Swiss catalogue access attempted network traffic")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    selection = rr.find(provider="ch_foen", station="2018", quantity="discharge")
    assert not rr.series(selection).is_empty()
    assert not rr.metadata(selection).is_empty()
    assert rr.describe("ch_foen")
    with pytest.raises(ObservationsUnavailableError, match="ch_foen"):
        rr.fetch(selection, start="2024-01-01", end="2024-01-02", cache="bypass", on_issue="ignore")

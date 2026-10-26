"""Swiss discovery stays offline while official observations use live stages."""

import socket

import pytest

import rivretrieve as rr
from rivretrieve._internal.providers.ch_foen.declaration import declaration
from rivretrieve._internal.providers.registration import LiveStages


def test_swiss_catalogue_has_anonymous_official_observations():
    assert isinstance(declaration.observations, LiveStages)
    assert declaration.public_archive_access is None
    assert declaration.required_credentials == ()


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_swiss_discovery_is_offline(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Swiss catalogue access attempted network traffic")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    selection = rr.find(provider="ch_foen", station="2018", quantity="discharge")
    assert not rr.series(selection).is_empty()
    assert not rr.metadata(selection).is_empty()
    assert rr.describe("ch_foen")

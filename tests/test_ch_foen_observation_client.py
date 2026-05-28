from __future__ import annotations

from rivretrieve._internal.providers.ch_foen.observation_client import ChFoenObservationClient


def test_ch_foen_observation_client_defaults_match_legacy_call_shape() -> None:
    client = ChFoenObservationClient(token="fake-token")

    assert client.endpoint == "https://influx.konzept.space/api/v2/query?org=api.existenz.ch"
    assert client.token == "fake-token"
    assert client.timeout_seconds == 60.0


def test_ch_foen_observation_client_repr_redacts_token() -> None:
    client = ChFoenObservationClient(token="fake-token")

    representation = repr(client)

    assert "fake-token" not in representation
    assert "<redacted>" in representation
    assert "Authorization" not in representation

from __future__ import annotations

from datetime import UTC, datetime

from rivretrieve._internal.providers.ch_foen.observation_client import (
    ChFoenObservationClient,
    ChFoenTransportRequest,
    ChFoenTransportResponse,
)


def test_ch_foen_observation_client_defaults_match_legacy_call_shape() -> None:
    client = ChFoenObservationClient()

    assert client.endpoint == "https://influx.konzept.space/api/v2/query?org=api.existenz.ch"
    assert client.token is None
    assert client.timeout_seconds == 60.0


def test_ch_foen_observation_client_repr_redacts_token() -> None:
    client = ChFoenObservationClient(token="fake-token")

    representation = repr(client)

    assert "fake-token" not in representation
    assert "<redacted>" in representation
    assert "Authorization" not in representation


def test_ch_foen_observation_client_uses_injected_transport() -> None:
    seen: list[ChFoenTransportRequest] = []

    def transport(request: ChFoenTransportRequest) -> ChFoenTransportResponse:
        seen.append(request)
        return ChFoenTransportResponse(
            content=b"csv",
            status_code=200,
            retrieved_at=datetime(2026, 5, 28, tzinfo=UTC),
        )

    client = ChFoenObservationClient(token="fake-token", transport=transport)

    response = client.fetch('from(bucket: "existenzApi")')

    assert response.content == b"csv"
    assert seen[0].endpoint == client.endpoint
    assert seen[0].query == 'from(bucket: "existenzApi")'
    assert seen[0].headers["Authorization"] == "Token fake-token"
    assert seen[0].timeout_seconds == 60.0


def test_ch_foen_observation_client_token_resolution_order(monkeypatch) -> None:
    monkeypatch.setenv("CH_FOEN_INFLUX_TOKEN", "env-token")

    assert ChFoenObservationClient(token="constructor-token").resolved_token == "constructor-token"
    assert ChFoenObservationClient().resolved_token == "env-token"

    monkeypatch.delenv("CH_FOEN_INFLUX_TOKEN")
    assert ChFoenObservationClient().resolved_token

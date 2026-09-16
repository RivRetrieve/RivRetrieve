"""record_observations credential path : CredentialHeader × fake sender → secret-free recording."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.record_observations import credential_value, record_observations
from rivretrieve._internal.recordings import RecordingTransport, read_recording
from rivretrieve._internal.transport import AuthenticatedTransport, CredentialHeader, HttpClient

_SECRET = "SENTINEL-NOT-A-REAL-KEY"
_ORIGIN = "https://hydapi.nve.no"
_EMPTY_SERIES = (
    b'{"currentLink":"https://hydapi.nve.no/api/v1/Observations","apiVersion":"1.0",'
    b'"license":"https://data.norge.no/nlod/en","createdAt":"2026-09-03T00:00:00Z","queryTime":"00:00:00.001",'
    b'"itemCount":1,"data":[{"stationId":"1.200.0","stationName":"Lierelv","parameter":1000,'
    b'"parameterName":"Vannstand","parameterNameEng":"Stage","serieVersionNo":1,"method":"Mean","unit":"m",'
    b'"observationCount":0,"observations":[]}]}'
)


def test_credential_value_prefers_environment_then_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('OTHER=1\nNVE_API_KEY="from-file"\n', encoding="utf-8")

    assert credential_value("NVE_API_KEY", {"NVE_API_KEY": "from-env"}, env_file) == "from-env"
    assert credential_value("NVE_API_KEY", {}, env_file) == "from-file"
    with pytest.raises(FatalContractError, match="NVE_API_KEY"):
        credential_value("NVE_API_KEY", {"NVE_API_KEY": "  "}, env_file)
    with pytest.raises(FatalContractError, match="NVE_API_KEY"):
        credential_value("NVE_API_KEY", {}, tmp_path / "absent")


def test_recording_transport_reports_the_wrapped_credential_scope() -> None:
    credentialed = AuthenticatedTransport(HttpClient(), (CredentialHeader("X-API-Key", _SECRET, (_ORIGIN,)),))

    assert RecordingTransport(credentialed).can_authenticate(f"{_ORIGIN}/api/v1/Observations") is True
    assert RecordingTransport(credentialed).can_authenticate("https://other.invalid/") is False
    assert RecordingTransport(HttpClient()).can_authenticate(f"{_ORIGIN}/api/v1/Observations") is False


def test_credentialed_recording_keeps_the_header_name_and_never_the_value(tmp_path: Path) -> None:
    seen_headers: list[dict[str, str]] = []

    def sender(request, timeout_seconds):
        seen_headers.append(dict(request.headers))
        return _EMPTY_SERIES, 200, "application/json; charset=utf-8"

    (written,) = record_observations(
        "no_nve",
        ("1.200.0",),
        ("stage_daily_mean",),
        "1900-01-03T00:00:00",
        "1900-01-05T00:00:00",
        tmp_path,
        "no_nve_probe",
        credentials=(CredentialHeader("X-API-Key", _SECRET, (_ORIGIN,)),),
        transport=HttpClient(sender=sender),
    )

    assert seen_headers[0]["X-API-Key"] == _SECRET
    text = written.read_text(encoding="utf-8")
    assert _SECRET not in text
    document = json.loads(text)
    assert document["request"]["credential_header_names"] == ["X-API-Key"]
    assert "X-API-Key" not in document["request"]["ordinary_headers"]
    recording = read_recording(written)
    assert recording.content == _EMPTY_SERIES
    assert recording.request.parameters is not None
    assert recording.request.parameters["ReferenceTime"] == "1900-01-01T00:00:00Z/1900-01-07T00:00:00Z"


def test_recording_main_resolves_declared_exchange_below_recorder(tmp_path, monkeypatch):
    from dataclasses import replace

    from rivretrieve._internal import record_observations as recorder
    from rivretrieve._internal.authentication import ExchangeSpec
    from rivretrieve._internal.providers.no_nve.declaration import declaration
    from rivretrieve._internal.providers.registration import (
        CredentialExchangeBinding,
        CredentialHeaderBinding,
        DeclaredProvider,
    )

    spec = ExchangeSpec(
        "https://auth.example.test/token",
        ("token",),
        "Bearer",
        3600,
        3300,
        _ORIGIN,
    )
    declared = replace(
        declaration,
        required_credentials=("TEST_IDENTIFIER", "TEST_PASSWORD"),
        credential_headers=(),
        credential_exchange=CredentialExchangeBinding(
            spec,
            (
                CredentialHeaderBinding("TEST_IDENTIFIER", "identifier", ("https://auth.example.test",)),
                CredentialHeaderBinding("TEST_PASSWORD", "password", ("https://auth.example.test",)),
            ),
        ),
    )
    monkeypatch.setattr(recorder, "load_manifest", lambda _: (DeclaredProvider("no_nve", declared),))
    monkeypatch.setenv("TEST_IDENTIFIER", "TEST-IDENTIFIER-SENTINEL")
    monkeypatch.setenv("TEST_PASSWORD", "TEST-PASSWORD-SENTINEL")
    token = "TEST-TOKEN-SENTINEL"
    seen = []
    payload = read_recording(
        Path(__file__).parent / "test_data/no_nve_1.200.0_1000_1440_1900-01-01_1900-01-07.recording.json"
    ).content

    def sender(request, timeout_seconds):
        seen.append(request)
        if request.url == spec.exchange_url:
            assert dict(request.headers)["identifier"] == "TEST-IDENTIFIER-SENTINEL"
            assert dict(request.headers)["password"] == "TEST-PASSWORD-SENTINEL"
            return json.dumps({"token": token}).encode(), 200, "application/json"
        assert dict(request.headers)["Authorization"] == f"Bearer {token}"
        return payload, 200, "application/json"

    monkeypatch.setattr(recorder, "HttpClient", lambda: HttpClient(sender=sender))
    assert (
        recorder.main(
            [
                "--provider",
                "no_nve",
                "--station",
                "1.200.0",
                "--product",
                "stage_daily_mean",
                "--start",
                "1900-01-03T00:00:00",
                "--end",
                "1900-01-05T00:00:00",
                "--out-dir",
                str(tmp_path),
                "--name",
                "declared_exchange",
            ]
        )
        == 0
    )
    assert len(seen) == 2
    (written,) = tuple(tmp_path.glob("*.recording.json"))
    recording = read_recording(written)
    assert recording.content == payload
    assert recording.request.url != spec.exchange_url
    assert recording.request.credential_header_names == ("Authorization",)
    for secret in ("TEST-IDENTIFIER-SENTINEL", "TEST-PASSWORD-SENTINEL", token):
        assert secret not in written.read_text()


@pytest.mark.parametrize("mode", ["direct", "exchange"])
def test_recording_main_preflights_declared_credentials(tmp_path, monkeypatch, mode):
    from dataclasses import replace

    from rivretrieve._internal import record_observations as recorder
    from rivretrieve._internal.authentication import ExchangeSpec
    from rivretrieve._internal.providers.no_nve.declaration import declaration
    from rivretrieve._internal.providers.registration import (
        CredentialExchangeBinding,
        CredentialHeaderBinding,
        DeclaredProvider,
    )

    binding = CredentialHeaderBinding("TEST_MISSING", "X-Token", (_ORIGIN,))
    declared = replace(declaration, required_credentials=("TEST_MISSING",), credential_headers=(binding,))
    if mode == "exchange":
        spec = ExchangeSpec(f"{_ORIGIN}/token", ("token",), "Bearer", 3600, 3300, _ORIGIN)
        declared = replace(
            declared, credential_headers=(), credential_exchange=CredentialExchangeBinding(spec, (binding,))
        )
    monkeypatch.setattr(recorder, "load_manifest", lambda _: (DeclaredProvider("no_nve", declared),))
    monkeypatch.delenv("TEST_MISSING", raising=False)
    monkeypatch.setattr(
        recorder, "HttpClient", lambda: pytest.fail("transport constructed before credential preflight")
    )
    with pytest.raises(FatalContractError, match="TEST_MISSING"):
        recorder.main(
            [
                "--provider",
                "no_nve",
                "--station",
                "1.200.0",
                "--product",
                "stage_daily_mean",
                "--start",
                "1900-01-03",
                "--end",
                "1900-01-05",
                "--out-dir",
                str(tmp_path),
                "--name",
                "missing",
            ]
        )
    assert not tuple(tmp_path.iterdir())

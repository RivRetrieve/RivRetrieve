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

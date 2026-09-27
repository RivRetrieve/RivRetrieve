"""record_observations credential path : CredentialHeader × fake sender → secret-free recording."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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


class _RecordingClock:
    def __init__(self):
        self.elapsed = 0.0

    def monotonic(self):
        return self.elapsed

    def utcnow(self):
        return datetime(2026, 9, 25, tzinfo=UTC) + timedelta(seconds=self.elapsed)

    def sleep(self, seconds):
        assert seconds >= 0
        self.elapsed += seconds


def _client(sender):
    # Keep real pacing/retry orchestration, but advance a coherent virtual clock.
    clock = _RecordingClock()
    return HttpClient(sender=sender, clock=clock, sleeper=clock.sleep)


def _nve_source_response(request, observation_body=_EMPTY_SERIES):
    """Match metadata to exact publisher bytes and observations to an authored empty control."""
    metadata = read_recording(Path(__file__).parent / "test_data/no_nve_series_1.200.0_1000.recording.json")
    if request.url == metadata.request.url:
        assert dict(request.params) == dict(metadata.request.parameters)
        return metadata.content, metadata.status_code, metadata.content_type
    assert request.url == f"{_ORIGIN}/api/v1/Observations"
    assert dict(request.params) == {
        "StationId": "1.200.0",
        "Parameter": "1000",
        "ResolutionTime": "1440",
        "VersionNumber": 1,
        "ReferenceTime": "1900-01-01T00:00:00Z/1900-01-07T23:59:59.999999Z",
    }
    return observation_body, 200, "application/json; charset=utf-8"


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
        return _nve_source_response(request)

    written = record_observations(
        "no_nve",
        ("1.200.0",),
        ("stage_daily_mean",),
        "1900-01-03T00:00:00",
        "1900-01-05T00:00:00",
        tmp_path,
        "no_nve_probe",
        credentials=(CredentialHeader("X-API-Key", _SECRET, (_ORIGIN,)),),
        transport=_client(sender),
    )

    assert len(written) == len(seen_headers) == 2
    for path, headers in zip(written, seen_headers, strict=True):
        assert headers["X-API-Key"] == _SECRET
        text = path.read_text(encoding="utf-8")
        assert _SECRET not in text
        document = json.loads(text)
        assert document["request"]["credential_header_names"] == ["X-API-Key"]
        assert "X-API-Key" not in document["request"]["ordinary_headers"]
    metadata, observation = map(read_recording, written)
    assert metadata.request.url == f"{_ORIGIN}/api/v1/Series"
    assert (
        metadata.content
        == read_recording(Path(__file__).parent / "test_data/no_nve_series_1.200.0_1000.recording.json").content
    )
    assert observation.content == _EMPTY_SERIES
    assert observation.request.parameters["VersionNumber"] == 1
    assert observation.request.parameters["ReferenceTime"] == "1900-01-01T00:00:00Z/1900-01-07T23:59:59.999999Z"


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
        return _nve_source_response(request, payload)

    monkeypatch.setattr(recorder, "HttpClient", lambda: _client(sender))
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
    assert [request.url for request in seen] == [
        spec.exchange_url,
        f"{_ORIGIN}/api/v1/Series",
        f"{_ORIGIN}/api/v1/Observations",
    ]
    written = sorted(tmp_path.glob("*.recording.json"))
    assert len(written) == 2
    assert read_recording(written[1]).content == payload
    for path in written:
        recording = read_recording(path)
        assert recording.request.url != spec.exchange_url
        assert recording.request.credential_header_names == ("Authorization",)
        assert "Authorization" not in recording.request.ordinary_headers
        for secret in ("TEST-IDENTIFIER-SENTINEL", "TEST-PASSWORD-SENTINEL", token):
            assert secret not in path.read_text()


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


@pytest.mark.parametrize("stations", [("1.200.0",), ("0.protocol", "1.200.0")])
def test_recording_main_reports_rejected_exchange_and_preserves_safe_partial_recordings(
    tmp_path,
    monkeypatch,
    capsys,
    stations,
):
    from dataclasses import replace

    from rivretrieve._internal import record_observations as recorder
    from rivretrieve._internal.authentication import ExchangeSpec
    from rivretrieve._internal.providers.no_nve.declaration import declaration
    from rivretrieve._internal.providers.registration import (
        CredentialExchangeBinding,
        CredentialHeaderBinding,
        DeclaredProvider,
    )

    spec = ExchangeSpec(f"{_ORIGIN}/token", ("token",), "Bearer", 3600, 3300, _ORIGIN)
    declared = replace(
        declaration,
        required_credentials=("TEST_PASSWORD",),
        credential_headers=(),
        credential_exchange=CredentialExchangeBinding(
            spec, (CredentialHeaderBinding("TEST_PASSWORD", "Password", (_ORIGIN,)),)
        ),
    )
    monkeypatch.setattr(recorder, "load_manifest", lambda _: (DeclaredProvider("no_nve", declared),))
    monkeypatch.setenv("TEST_PASSWORD", "REJECTED-PASSWORD-SENTINEL")
    calls = []
    payload = read_recording(
        Path(__file__).parent / "test_data/no_nve_1.200.0_1000_1440_1900-01-01_1900-01-07.recording.json"
    ).content

    def sender(request, timeout_seconds):
        calls.append(request.url)
        if len(calls) == 1:
            return b"REJECTED-PASSWORD-SENTINEL", 401, "text/plain"
        if request.url == spec.exchange_url:
            return b'{"token":"ACQUIRED-TOKEN-SENTINEL"}', 200, "application/json"
        return payload, 200, "application/json"

    monkeypatch.setattr(recorder, "HttpClient", lambda: _client(sender))
    args = [
        "--provider",
        "no_nve",
        "--product",
        "stage_daily_mean",
        # The protocol-only station is deliberately outside catalogue inventory.
        "--variant",
        "1",
        "--start",
        "1900-01-03",
        "--end",
        "1900-01-05",
        "--out-dir",
        str(tmp_path),
        "--name",
        "rejection",
    ]
    for station in stations:
        args.extend(("--station", station))
    assert recorder.main(args) == 1
    captured = capsys.readouterr()
    assert "TEST_PASSWORD" in captured.err
    assert "HTTP 401" in captured.err
    assert "recording failed" in captured.err
    recordings = tuple(tmp_path.glob("*.recording.json"))
    assert len(recordings) == len(stations) - 1
    assert len(calls) == (1 if len(stations) == 1 else 3)
    retained = captured.out + captured.err + "".join(path.read_text() for path in recordings)
    for secret in ("REJECTED-PASSWORD-SENTINEL", "ACQUIRED-TOKEN-SENTINEL"):
        assert secret not in retained
    assert "no source exchange was issued" not in captured.out


def test_recording_main_retains_not_found_response_without_error_exit(tmp_path, monkeypatch):
    from rivretrieve._internal import record_observations as recorder

    monkeypatch.setenv("NVE_API_KEY", _SECRET)
    recording = read_recording(
        Path(__file__).parent / "test_data/no_nve_12.210.0_1003_1440_2025-07-08_2025-07-14.recording.json"
    )

    def sender(request, timeout_seconds):
        return recording.content, recording.status_code, recording.content_type

    monkeypatch.setattr(recorder, "HttpClient", lambda: _client(sender))
    assert (
        recorder.main(
            [
                "--provider",
                "no_nve",
                "--station",
                "12.210.0",
                "--product",
                "water_temperature_daily_mean",
                "--variant",
                "1",
                "--start",
                "2025-07-10",
                "--end",
                "2025-07-12",
                "--out-dir",
                str(tmp_path),
                "--name",
                "not_found",
            ]
        )
        == 0
    )
    (written,) = tuple(tmp_path.glob("*.recording.json"))
    retained = read_recording(written)
    assert retained.status_code == 404
    assert retained.content == recording.content
    assert _SECRET not in written.read_text()


@pytest.mark.parametrize("current_inventory", ["published", "empty"])
def test_recorder_routes_catalogue_owned_versions_through_real_provider_fetch(tmp_path, current_inventory):
    """The recorder must compose source inventory before the versioned fetch stage."""
    sent = []

    def sender(request, timeout_seconds):
        sent.append(request)
        response = _nve_source_response(request)
        if request.url.endswith("/Series") and current_inventory == "empty":
            # Authored current absence cannot erase an acquired historical version.
            return b'{"itemCount":0,"data":[]}', 200, "application/json"
        return response

    paths = record_observations(
        "no_nve",
        ("1.200.0",),
        ("stage_daily_mean",),
        "1900-01-03T00:00:00",
        "1900-01-05T00:00:00",
        tmp_path,
        "catalogue_version",
        transport=_client(sender),
    )
    assert [request.url for request in sent] == [f"{_ORIGIN}/api/v1/Series", f"{_ORIGIN}/api/v1/Observations"]
    assert sent[1].params["VersionNumber"] == 1
    assert len(paths) == 2
    captured = read_recording(paths[1])
    assert read_recording(paths[0]).request.parameters == {"StationId": "1.200.0", "Parameter": 1000}
    assert captured.request.parameters["VersionNumber"] == 1
    assert captured.content == _EMPTY_SERIES
    assert captured.status_code == 200


def test_recorder_explicit_unknown_version_is_sent_without_catalogue_fallback(tmp_path):
    sent = []
    body = b"source reports no such version"

    def sender(request, timeout_seconds):
        sent.append(request)
        return body, 404, "text/plain"

    (written,) = record_observations(
        "no_nve",
        ("1.200.0",),
        ("stage_daily_mean",),
        "1900-01-03",
        "1900-01-05",
        tmp_path,
        "explicit_version",
        transport=_client(sender),
        variants=("99999",),
    )
    assert len(sent) == 1
    assert sent[0].params["VersionNumber"] == 99999
    captured = read_recording(written)
    assert captured.request.parameters["VersionNumber"] == 99999
    assert captured.status_code == 404
    assert captured.content == body


@pytest.mark.parametrize(
    "body,status",
    [
        (b'{"itemCount":0,"data":[]}', 200),
        (b'{"itemCount":1,"data":[{}]}', 200),
        (b"source reports no such station", 404),
    ],
)
def test_recorder_without_established_or_explicit_version_never_invents_default(tmp_path, body, status):
    """Authored absent/malformed inventory controls permit discovery, never a preferred version."""
    sent = []

    def inventory_only(request, timeout_seconds):
        sent.append(request)
        assert request.url == f"{_ORIGIN}/api/v1/Series"
        assert dict(request.params) == {"StationId": "0.protocol", "Parameter": 1000}
        return body, status, "application/json" if status == 200 else "text/plain"

    (written,) = record_observations(
        "no_nve",
        ("0.protocol",),
        ("stage_daily_mean",),
        "1900-01-03",
        "1900-01-05",
        tmp_path,
        "no_version",
        transport=_client(inventory_only),
    )
    assert len(sent) == 1
    assert tuple(tmp_path.glob("*.recording.json")) == (written,)
    captured = read_recording(written)
    assert captured.content == body
    assert captured.status_code == status
    assert "VersionNumber" not in captured.request.parameters

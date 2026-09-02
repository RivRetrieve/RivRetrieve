"""Recording envelope and exact replay lookup contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rivretrieve._internal.recordings import (
    InvalidRecordingError,
    RecordedRequest,
    RecordingEnvelope,
    ReplayTransport,
    UnmatchedRequestError,
    dry_run_recordings,
    read_recording,
)
from rivretrieve._internal.transport import HttpMethod, TransportRequest

_RECORDING = Path(__file__).parent / "test_data" / "observation_recording_synthetic.json"


def test_unmatched_request_names_exact_window_and_returns_nothing() -> None:
    replay = ReplayTransport([_RECORDING])
    unmatched = TransportRequest(
        method=HttpMethod.GET,
        url="https://example.test/observations",
        params={"station": "REAL-1", "start": "2026-01-01", "end": "2026-01-03"},
    )

    with pytest.raises(UnmatchedRequestError) as exc_info:
        replay.send(unmatched)

    message = str(exc_info.value)
    assert "No recording matches request" in message
    assert "https://example.test/observations" in message
    assert '"end":"2026-01-03"' in message


def test_replay_returns_recorded_response_only_for_exact_request() -> None:
    replay = ReplayTransport([_RECORDING])
    request = TransportRequest(
        method=HttpMethod.GET,
        url="https://example.test/observations",
        params={"start": "2026-01-01", "station": "REAL-1", "end": "2026-01-02"},
        headers={"Authorization": "not recorded"},
    )

    response = replay.send(request)

    assert response.content == b'{"values":[1]}\n'
    assert response.retrieved_at.isoformat() == "2026-01-03T04:05:06+00:00"


def test_changed_payload_is_refused_by_digest(tmp_path: Path) -> None:
    changed = json.loads(_RECORDING.read_text(encoding="utf-8"))
    changed["response"]["content_base64"] = "aW52ZW50ZWQ="
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(InvalidRecordingError, match="SHA-256 mismatch"):
        read_recording(path)


def test_duplicate_request_field_is_refused(tmp_path: Path) -> None:
    ambiguous = _RECORDING.read_text(encoding="utf-8").replace(
        '      "end": "2026-01-02",',
        '      "end": "2026-01-02",\n      "end": "2026-01-03",',
    )
    path = tmp_path / "ambiguous.json"
    path.write_text(ambiguous, encoding="utf-8")

    with pytest.raises(InvalidRecordingError, match="duplicate field 'end'"):
        read_recording(path)


def test_rerecord_dry_run_uses_recording_facts_only(capsys: pytest.CaptureFixture[str]) -> None:
    dry_run_recordings([_RECORDING])

    assert capsys.readouterr().out.splitlines() == [
        "url: https://example.test/observations",
        'parameters: {"end":"2026-01-02","start":"2026-01-01","station":"REAL-1"}',
        "retrieved_at: 2026-01-03T04:05:06.000000Z",
    ]


@pytest.mark.parametrize(
    ("url", "parameters"),
    [
        ("https://example.test/data?access_token=secret", None),
        ("https://example.test/data", {"api_key": "secret"}),
        ("https://user:password@example.test/data", None),
    ],
)
def test_recorded_requests_refuse_secret_bearing_request_locations(url: str, parameters: dict[str, str] | None) -> None:
    with pytest.raises(ValueError, match="secret-bearing"):
        RecordedRequest(HttpMethod.GET, url, parameters)


def test_every_committed_observation_recording_is_secret_safe_and_replayable() -> None:
    recordings = sorted((Path(__file__).parent / "test_data").rglob("*.recording.json"))
    assert recordings
    for recording in recordings:
        read_recording(recording)


def test_recording_response_refuses_secret_bearing_fields() -> None:
    with pytest.raises(ValueError, match="response contains a secret-bearing field"):
        RecordingEnvelope(
            request=RecordedRequest(HttpMethod.GET, "https://example.test/data"),
            content=b'{"access_token":"secret"}',
            status_code=200,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            content_type="application/json",
        )


def test_recorded_request_refuses_secret_in_utf8_multipart_body() -> None:
    body = b'--boundary\r\nContent-Disposition: form-data; name="access_token"\r\n\r\nsecret\r\n--boundary--\r\n'

    with pytest.raises(ValueError, match="secret-bearing body field"):
        RecordedRequest(HttpMethod.POST, "https://example.test/data", body=body)


def test_recording_response_refuses_secret_in_utf16_json() -> None:
    content = '{"access_token":"secret"}'.encode("utf-16")

    with pytest.raises(ValueError, match="response contains a secret-bearing field"):
        RecordingEnvelope(
            request=RecordedRequest(HttpMethod.GET, "https://example.test/data"),
            content=content,
            status_code=200,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            content_type="application/json; charset=utf-16",
        )


def test_opaque_binary_zip_response_is_not_treated_as_structured_secret_data() -> None:
    recording = RecordingEnvelope(
        request=RecordedRequest(HttpMethod.GET, "https://example.test/data.zip"),
        content=b"PK\x03\x04access_token=publisher-column-name",
        status_code=200,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_type="application/zip",
    )

    assert recording.content.startswith(b"PK")

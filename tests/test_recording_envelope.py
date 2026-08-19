"""Recording envelope and exact replay lookup contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rivretrieve._internal.recordings import (
    InvalidRecordingError,
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


def test_rerecord_dry_run_uses_recording_facts_only(capsys: pytest.CaptureFixture[str]) -> None:
    dry_run_recordings([_RECORDING])

    assert capsys.readouterr().out.splitlines() == [
        "url: https://example.test/observations",
        'parameters: {"end":"2026-01-02","start":"2026-01-01","station":"REAL-1"}',
        "retrieved_at: 2026-01-03T04:05:06.000000Z",
    ]

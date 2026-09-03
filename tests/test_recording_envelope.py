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
    write_recording,
)
from rivretrieve._internal.transport import AuthenticatedTransport, CredentialHeader, HttpMethod, TransportRequest

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
        headers={"Accept": "text/csv"},
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


@pytest.mark.parametrize(
    "content",
    [
        b'{"access_token":"secret"}',
        b"access_token=secret",
    ],
)
def test_textual_secret_mislabeled_as_zip_is_not_trusted(content: bytes) -> None:
    with pytest.raises(ValueError, match="secret-bearing field"):
        RecordingEnvelope(
            request=RecordedRequest(HttpMethod.GET, "https://example.test/data"),
            content=content,
            status_code=200,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            content_type="application/zip",
        )


def test_xml_element_name_is_screened_for_secrets() -> None:
    with pytest.raises(ValueError, match="secret-bearing field"):
        RecordingEnvelope(
            request=RecordedRequest(HttpMethod.GET, "https://example.test/data"),
            content=b"<response><access_token>secret</access_token></response>",
            status_code=200,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            content_type="application/xml",
        )


@pytest.mark.parametrize(
    ("content_type", "content"),
    [
        ("application/zip", b"PK\x03\x04\x00\xff"),
        (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            b"PK\x03\x04\x00\xff",
        ),
        ("application/vnd.ms-excel", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\x00\xff"),
        ("application/pdf", b"%PDF-1.7\x00\xff"),
        ("application/vnd.apache.parquet", b"PAR1\x00\xff"),
        ("application/gzip", b"\x1f\x8b\x00\xff"),
        ("application/octet-stream", b"\x00\xff\x00\xff"),
    ],
)
def test_coherent_opaque_binary_recordings_remain_supported(content_type: str, content: bytes) -> None:
    recording = RecordingEnvelope(
        request=RecordedRequest(HttpMethod.GET, "https://example.test/binary"),
        content=content,
        status_code=200,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_type=content_type,
    )

    assert recording.content == content


@pytest.mark.parametrize(
    ("content_type", "content", "message"),
    [
        ("application/json", b"not-json", "not valid JSON"),
        ("multipart/form-data; boundary=boundary", b"not-multipart", "multipart response evidence is unsupported"),
        ("application/x-custom", b"\x00\xff", "unsupported recording content type"),
    ],
)
def test_ambiguous_structured_and_unknown_response_content_is_rejected(
    content_type: str, content: bytes, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        RecordingEnvelope(
            request=RecordedRequest(HttpMethod.GET, "https://example.test/data"),
            content=content,
            status_code=200,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            content_type=content_type,
        )


@pytest.mark.parametrize("content", [b"null", b"42", b'"value"'])
def test_valid_json_scalars_without_fields_remain_recordable(content: bytes) -> None:
    recording = RecordingEnvelope(
        request=RecordedRequest(HttpMethod.GET, "https://example.test/data"),
        content=content,
        status_code=200,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_type="application/json",
    )

    assert recording.content == content


_V2_RECORDING = Path(__file__).parent / "test_data" / "observation_recording_v2_synthetic.recording.json"


def test_v2_matches_exact_safe_executed_headers_and_exposes_exact_origin_capability() -> None:
    replay = ReplayTransport([_V2_RECORDING])
    request = TransportRequest(
        HttpMethod.GET, "https://secure.example.test/data", {"station": "A"}, {"Accept": "application/json"}
    )
    response = replay.send(request)
    assert response.applied_credential_header_names == ("X-API-Key",)
    assert response.executed_request is not None
    assert len(response.prerequisite_calls) == 1
    assert response.prerequisite_calls[0].response_disposition.value == "secret_response_withheld"
    assert response.prerequisite_calls[0].credential_header_names == ("Identificador", "Senha")
    assert dict(response.executed_request.ordinary_headers) == {
        "Accept": "application/json",
        "User-Agent": "RivRetrieve",
    }
    assert replay.can_authenticate("https://secure.example.test/other")
    assert not replay.can_authenticate("https://sub.secure.example.test/other")
    with pytest.raises(UnmatchedRequestError):
        replay.send(TransportRequest(HttpMethod.GET, request.url, request.params, {"Accept": "text/csv"}))


def test_v2_round_trip_never_serializes_credential_values(tmp_path: Path) -> None:
    original = read_recording(_V2_RECORDING)
    output = tmp_path / "v2.json"
    write_recording(original, output)
    reread = read_recording(output)
    assert reread == original
    data = output.read_bytes()
    assert b"X-API-Key" in data
    assert b"SENTINEL-CREDENTIAL-VALUE" not in data


def test_v2_refuses_unknown_or_case_colliding_ordinary_headers() -> None:
    with pytest.raises(ValueError, match="explicitly"):
        RecordedRequest(HttpMethod.GET, "https://example.test", ordinary_headers={"X-Unclassified": "value"})
    with pytest.raises(ValueError, match="case-insensitively"):
        RecordedRequest(
            HttpMethod.GET, "https://example.test", ordinary_headers={"Accept": "text/csv", "accept": "text/csv"}
        )
    with pytest.raises(ValueError, match="collide"):
        RecordedRequest(
            HttpMethod.GET,
            "https://example.test",
            ordinary_headers={"Accept": "text/csv"},
            credential_header_names=("accept",),
        )


def test_mixed_v1_v2_replay_ambiguity_is_refused() -> None:
    legacy = read_recording(_RECORDING)
    v2 = RecordingEnvelope(
        request=RecordedRequest(
            legacy.request.method,
            legacy.request.url,
            legacy.request.parameters,
            legacy.request.body,
            {"User-Agent": "RivRetrieve"},
        ),
        content=legacy.content,
        status_code=legacy.status_code,
        retrieved_at=legacy.retrieved_at,
        content_type=legacy.content_type,
    )
    with pytest.raises(InvalidRecordingError, match="mixed v1/v2"):
        ReplayTransport([legacy, v2])


def test_writer_refuses_to_promote_legacy_recording(tmp_path: Path) -> None:
    with pytest.raises(InvalidRecordingError, match="v2 only"):
        write_recording(read_recording(_RECORDING), tmp_path / "promoted.json")


def test_v2_replays_through_exact_origin_authenticated_transport_without_using_secret_value() -> None:
    sentinel = "SENTINEL-REPLAY-MUST-NOT-PERSIST"
    replay = ReplayTransport([_V2_RECORDING])
    wrapped = AuthenticatedTransport(
        replay,
        (CredentialHeader("X-API-Key", sentinel, ("https://secure.example.test",)),),
    )
    response = wrapped.send(
        TransportRequest(
            HttpMethod.GET,
            "https://secure.example.test/data",
            {"station": "A"},
            {"Accept": "application/json"},
        )
    )
    scanned = (repr(replay), repr(wrapped), repr(response), str(response))
    assert response.content == b'{"value":1}\n'
    assert response.applied_credential_header_names == ("X-API-Key",)
    assert all(sentinel not in value for value in scanned)


def test_v2_refuses_oversized_header_values_and_trace_name_collisions() -> None:
    from rivretrieve._internal.transport import RequestBodyShape, SecretCallTrace

    with pytest.raises(ValueError, match="too large"):
        RecordedRequest(HttpMethod.GET, "https://example.test", ordinary_headers={"Accept": "x" * 1025})
    with pytest.raises(ValueError, match="collide"):
        SecretCallTrace(
            HttpMethod.GET,
            "https://auth.example.test/token",
            {"Accept": "application/json"},
            None,
            RequestBodyShape.NONE,
            ("accept",),
            200,
            datetime(2026, 1, 1, tzinfo=UTC),
            "application/json",
        )


def test_v1_recording_never_claims_authentication_capability() -> None:
    replay = ReplayTransport([_RECORDING])
    assert not replay.can_authenticate("https://example.test/observations")


@pytest.mark.parametrize(
    "url", ["https://secure.example.test:", "https://usér.example/path", "https://user@secure.example.test/path"]
)
def test_replay_authentication_capability_uses_live_exact_origin_refusals(url: str) -> None:
    replay = ReplayTransport([_V2_RECORDING])
    with pytest.raises(ValueError):
        replay.can_authenticate(url)


def test_private_authenticated_replay_requires_exact_recorded_credential_names() -> None:
    from rivretrieve._internal.transport import RedirectPolicy, _make_credential_transport_request

    replay = ReplayTransport([_V2_RECORDING])
    public = TransportRequest(
        HttpMethod.GET, "https://secure.example.test/data", {"station": "A"}, {"Accept": "application/json"}
    )
    private = _make_credential_transport_request(
        public,
        {"Accept": "application/json", "Authorization": "SENTINEL-PRIVATE"},
        ("Authorization",),
        redirect_policy=RedirectPolicy.REFUSE,
    )
    with pytest.raises(UnmatchedRequestError):
        replay._resolve(private)


def test_private_authenticated_request_cannot_match_unauthenticated_v2_recording() -> None:
    from rivretrieve._internal.transport import RedirectPolicy, _make_credential_transport_request

    public = TransportRequest(HttpMethod.GET, "https://plain.example.test/data", headers={"Accept": "application/json"})
    recording = RecordingEnvelope(
        RecordedRequest(
            HttpMethod.GET,
            public.url,
            ordinary_headers={"Accept": "application/json", "User-Agent": "RivRetrieve"},
        ),
        b'{"value":1}',
        200,
        datetime(2026, 1, 1, tzinfo=UTC),
        "application/json",
    )
    private = _make_credential_transport_request(
        public,
        {"Accept": "application/json", "X-API-Key": "SENTINEL-PRIVATE"},
        ("X-API-Key",),
        redirect_policy=RedirectPolicy.REFUSE,
    )
    with pytest.raises(UnmatchedRequestError):
        ReplayTransport([recording])._resolve(private)


def test_v2_recordings_differing_only_by_credential_names_are_ambiguous() -> None:
    first = read_recording(_V2_RECORDING)
    second = RecordingEnvelope(
        RecordedRequest(
            first.request.method,
            first.request.url,
            first.request.parameters,
            first.request.body,
            first.request.ordinary_headers,
            ("Authorization",),
        ),
        first.content,
        first.status_code,
        first.retrieved_at,
        first.content_type,
        first.prerequisite_calls,
    )
    with pytest.raises(InvalidRecordingError, match="multiple recordings"):
        ReplayTransport([first, second])


@pytest.mark.parametrize("recording", [_RECORDING, _V2_RECORDING])
def test_replay_refuses_provider_user_agent_before_any_v1_or_v2_lookup(recording: Path) -> None:
    replay = ReplayTransport([recording])
    loaded = read_recording(recording)
    with pytest.raises(ValueError, match="User-Agent"):
        replay.send(
            TransportRequest(
                loaded.request.method,
                loaded.request.url,
                loaded.request.parameters,
                headers={"User-Agent": "RivRetrieve"},
                body=loaded.request.body,
            )
        )


def test_v2_safe_ordinary_header_spelling_is_exact_while_v1_remains_header_insensitive() -> None:
    v2 = ReplayTransport([_V2_RECORDING])
    with pytest.raises(UnmatchedRequestError):
        v2.send(
            TransportRequest(
                HttpMethod.GET,
                "https://secure.example.test/data",
                {"station": "A"},
                {"accept": "application/json"},
            )
        )
    legacy = read_recording(_RECORDING)
    response = ReplayTransport([legacy]).send(
        TransportRequest(
            legacy.request.method,
            legacy.request.url,
            legacy.request.parameters,
            headers={"accept": "anything-safe"},
            body=legacy.request.body,
        )
    )
    assert response.content == legacy.content


@pytest.mark.parametrize(
    ("url", "body"),
    [
        ("https://example.test/data?access%255ftoken=value", None),
        ("https://example.test/data", "access%255ftoken=value"),
    ],
)
def test_recorded_request_refuses_double_encoded_secret_field_names(url: str, body: str | None) -> None:
    with pytest.raises(ValueError, match="secret-bearing"):
        RecordedRequest(HttpMethod.POST, url, body=body)


def test_recorded_request_refuses_percent_encoding_beyond_fixed_depth() -> None:
    encoded = "access_token"
    for _ in range(9):
        encoded = encoded.replace("%", "%25").replace("_", "%5f")
    with pytest.raises(ValueError, match="percent-decoding depth"):
        RecordedRequest(HttpMethod.GET, f"https://example.test/data?{encoded}=value")

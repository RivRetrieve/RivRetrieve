"""Credential exchange security boundary tests."""

import traceback
from datetime import UTC, datetime

import pytest

from rivretrieve._internal.authentication import (
    AuthenticationFailureReason,
    CredentialExchangeError,
    CredentialExchangeTransport,
    ExchangeSpec,
)
from rivretrieve._internal.transport import (
    CredentialHeader,
    ExecutedRequestEvidence,
    HttpMethod,
    TransportRequest,
    TransportResponse,
)

_IDENTIFIER = "SENTINEL-IDENTIFIER"
_PASSWORD = "SENTINEL-PASSWORD"
_TOKEN = "SENTINEL-BEARER-TOKEN"
_COLLISION_SENTINEL = "SENTINEL-CALLER-AUTHORIZATION"
_AUTH_BODY = f'{{"items":{{"tokenautenticacao":"{_TOKEN}"}},"sentinel":"FULL-AUTH-RESPONSE"}}'.encode()


class FakeClock:
    def __init__(self) -> None:
        self.value = 10.0

    def monotonic(self) -> float:
        return self.value

    def utcnow(self) -> datetime:
        return datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


class Scripted:
    def __init__(self, actions):
        self.actions = list(actions)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        content, status, *metadata = action
        content_type = metadata[0] if metadata else "application/json"
        response_url = metadata[1] if len(metadata) > 1 and metadata[1] is not None else request.url
        ordinary_override = metadata[2] if len(metadata) > 2 else None
        prerequisites = metadata[3] if len(metadata) > 3 else ()
        applied_names = getattr(request, "credential_header_names", ())
        credential_names = {name.casefold() for name in applied_names}
        ordinary = {name: value for name, value in request.headers.items() if name.casefold() not in credential_names}
        ordinary["User-Agent"] = "RivRetrieve"
        if ordinary_override is not None:
            ordinary = ordinary_override
        return TransportResponse(
            content,
            status,
            datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
            content_type,
            response_url,
            request.params or {},
            applied_credential_header_names=applied_names,
            prerequisite_calls=prerequisites,
            executed_request=ExecutedRequestEvidence(ordinary, applied_names),
        )


def wrapper(actions):
    raw = Scripted(actions)
    clock = FakeClock()
    spec = ExchangeSpec.ana()
    exchange_origin = "https://www.ana.gov.br"
    transport = CredentialExchangeTransport(
        raw,
        (
            CredentialHeader("Identificador", _IDENTIFIER, (exchange_origin,)),
            CredentialHeader("Senha", _PASSWORD, (exchange_origin,)),
        ),
        spec,
        clock,
    )
    return transport, raw, clock


def data_request():
    return TransportRequest(
        HttpMethod.GET, "https://www.ana.gov.br/hidrowebservice/data", headers={"Accept": "application/json"}
    )


def test_exchange_is_lazy_cached_refreshable_and_returns_only_ordered_redacted_trace() -> None:
    transport, raw, clock = wrapper(
        [(_AUTH_BODY, 200), (b'{"data":1}', 200), (b'{"data":2}', 200), (_AUTH_BODY, 200), (b'{"data":3}', 200)]
    )
    assert raw.requests == []
    first = transport.send(data_request())
    second = transport.send(data_request())
    assert len(first.prerequisite_calls) == 1
    trace = first.prerequisite_calls[0]
    assert trace.credential_header_names == ("Identificador", "Senha")
    assert trace.response_disposition.value == "secret_response_withheld"
    assert not any(name in {"content", "size", "sha256", "digest"} for name in trace.__dataclass_fields__)
    assert second.prerequisite_calls == ()
    clock.value += 3300
    third = transport.send(data_request())
    assert len(third.prerequisite_calls) == 1
    assert [request.url for request in raw.requests] == [
        ExchangeSpec.ana().exchange_url,
        data_request().url,
        data_request().url,
        ExchangeSpec.ana().exchange_url,
        data_request().url,
    ]
    assert raw.requests[0].headers == {"Identificador": _IDENTIFIER, "Senha": _PASSWORD}
    assert raw.requests[1].headers["Authorization"] == f"Bearer {_TOKEN}"


@pytest.mark.parametrize(
    ("auth_body", "status", "reason"),
    [
        (b"redirect", 302, AuthenticationFailureReason.EXCHANGE_REDIRECT_REFUSED),
        (b"denied", 401, AuthenticationFailureReason.EXCHANGE_HTTP_STATUS),
        (b"not-json", 200, AuthenticationFailureReason.RESPONSE_JSON_INVALID),
        (b"[]", 200, AuthenticationFailureReason.RESPONSE_ENVELOPE_INVALID),
        (b'{"items":{}}', 200, AuthenticationFailureReason.TOKEN_MISSING),
        (b'{"items":{"tokenautenticacao":""}}', 200, AuthenticationFailureReason.TOKEN_EMPTY),
        (b'{"items":{"tokenautenticacao":3}}', 200, AuthenticationFailureReason.TOKEN_WRONG_TYPE),
    ],
)
def test_exchange_failures_are_reason_bearing_and_secret_free(auth_body, status, reason) -> None:
    transport, _, _ = wrapper([(auth_body, status)])
    with pytest.raises(CredentialExchangeError) as raised:
        transport.send(data_request())
    assert raised.value.reason is reason
    rendered = "".join(traceback.TracebackException.from_exception(raised.value, capture_locals=True).format())
    for secret in (_IDENTIFIER, _PASSWORD, _TOKEN, "FULL-AUTH-RESPONSE"):
        assert secret not in rendered
        assert secret not in repr(raised.value)
    assert raised.value.__cause__ is None and raised.value.__context__ is None


def test_bearer_send_failure_withholds_token_and_auth_response_from_traceback() -> None:
    transport, _, _ = wrapper([(_AUTH_BODY, 200), RuntimeError("sender failed")])
    with pytest.raises(CredentialExchangeError) as raised:
        transport.send(data_request())
    assert raised.value.reason is AuthenticationFailureReason.DATA_SEND_FAILED
    rendered = "".join(traceback.TracebackException.from_exception(raised.value, capture_locals=True).format())
    for secret in (_IDENTIFIER, _PASSWORD, _TOKEN, "FULL-AUTH-RESPONSE"):
        assert secret not in rendered
    assert raised.value.__cause__ is None and raised.value.__context__ is None


def test_exchange_capability_is_exact_origin_only() -> None:
    transport, _, _ = wrapper([])
    assert transport.can_authenticate("https://www.ana.gov.br/path")
    assert not transport.can_authenticate("http://www.ana.gov.br/path")
    assert not transport.can_authenticate("https://sub.www.ana.gov.br/path")
    assert not transport.can_authenticate("https://www.ana.gov.br:444/path")


@pytest.mark.parametrize("redirected_call", ["exchange", "data"])
def test_real_cross_origin_redirect_never_forwards_exchange_or_bearer_credentials(redirected_call: str) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from rivretrieve._internal.transport import HttpClient

    target_credentials: list[tuple[str | None, str | None, str | None]] = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            target_credentials.append(
                (self.headers.get("Identificador"), self.headers.get("Senha"), self.headers.get("Authorization"))
            )
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    target_thread = Thread(target=target.serve_forever, daemon=True)
    target_thread.start()
    target_url = f"http://127.0.0.1:{target.server_port}/target"

    class Source(BaseHTTPRequestHandler):
        def do_GET(self):
            if (redirected_call == "exchange" and self.path == "/token") or (
                redirected_call == "data" and self.path == "/data"
            ):
                self.send_response(302)
                self.send_header("Location", target_url)
                self.end_headers()
                return
            if self.path == "/token":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"items":{"tokenautenticacao":"local-token"}}')
                return
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    source = ThreadingHTTPServer(("127.0.0.1", 0), Source)
    source_thread = Thread(target=source.serve_forever, daemon=True)
    source_thread.start()
    origin = f"http://127.0.0.1:{source.server_port}"

    class AdvancingClock:
        def __init__(self):
            self.value = 0.0

        def monotonic(self):
            self.value += 2.0
            return self.value

        def utcnow(self):
            return datetime(2026, 1, 1, tzinfo=UTC)

    try:
        clock = AdvancingClock()
        transport = CredentialExchangeTransport(
            HttpClient(clock=clock, sleeper=lambda _: None),
            (
                CredentialHeader("Identificador", "local-id", (origin,)),
                CredentialHeader("Senha", "local-password", (origin,)),
            ),
            ExchangeSpec(f"{origin}/token", ("items", "tokenautenticacao"), "Bearer", 3600, 3300, origin),
            clock,
        )
        expected = (
            AuthenticationFailureReason.EXCHANGE_REDIRECT_REFUSED
            if redirected_call == "exchange"
            else AuthenticationFailureReason.DATA_REDIRECT_REFUSED
        )
        with pytest.raises(CredentialExchangeError) as raised:
            transport.send(TransportRequest(HttpMethod.GET, f"{origin}/data"))
        assert raised.value.reason is expected
        assert target_credentials == []
    finally:
        source.shutdown()
        target.shutdown()
        source.server_close()
        target.server_close()


@pytest.mark.parametrize(
    ("action", "reason"),
    [
        (RuntimeError("exchange sender failed"), AuthenticationFailureReason.EXCHANGE_SEND_FAILED),
        ((b'{"items":{"tokenautenticacao":"   "}}', 200), AuthenticationFailureReason.TOKEN_EMPTY),
        ((b'{"items":{"tokenautenticacao":"bad\\nvalue"}}', 200), AuthenticationFailureReason.TOKEN_INVALID),
    ],
)
def test_additional_exchange_failures_are_sanitized(action, reason) -> None:
    transport, _, _ = wrapper([action])
    with pytest.raises(CredentialExchangeError) as raised:
        transport.send(data_request())
    assert raised.value.reason is reason
    assert raised.value.__cause__ is None and raised.value.__context__ is None


def test_success_state_recording_trace_and_response_contain_no_secret_values(tmp_path) -> None:
    from rivretrieve._internal.recordings import RecordingEnvelope, write_recording

    transport, _, _ = wrapper([(_AUTH_BODY, 200), (b'{"data":1}', 200)])
    request = data_request()
    response = transport.send(request)
    recording = RecordingEnvelope.from_transport(request, response)
    path = tmp_path / "data.recording.json"
    write_recording(recording, path)
    scanned = (repr(transport), repr(response), repr(recording), path.read_text())
    for secret in (_IDENTIFIER, _PASSWORD, _TOKEN, "FULL-AUTH-RESPONSE"):
        assert all(secret not in value for value in scanned)
    assert response.content == b'{"data":1}'
    assert len(response.prerequisite_calls) == 1


def test_public_bearer_header_is_rejected_before_exchange_without_secret_locals() -> None:
    transport, raw, _ = wrapper([])
    try:
        transport.send(
            TransportRequest(
                HttpMethod.GET,
                "https://www.ana.gov.br/hidrowebservice/data",
                headers={"Accept": "application/json", "aUtHoRiZaTiOn": _COLLISION_SENTINEL},
            )
        )
    except ValueError as error:
        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert _COLLISION_SENTINEL not in rendered
        assert _COLLISION_SENTINEL not in repr(error)
        assert error.__cause__ is None and error.__context__ is None
        assert raw.requests == []
    else:
        raise AssertionError("public bearer header was not refused")


@pytest.mark.parametrize("token_value", [None, True, False, [], {}, 3])
def test_non_string_token_forms_are_refused(token_value) -> None:
    import json

    transport, _, _ = wrapper([(json.dumps({"items": {"tokenautenticacao": token_value}}).encode(), 200)])
    with pytest.raises(CredentialExchangeError) as raised:
        transport.send(data_request())
    assert raised.value.reason is AuthenticationFailureReason.TOKEN_WRONG_TYPE


def test_duplicate_auth_json_keys_are_refused_as_ambiguous() -> None:
    transport, _, _ = wrapper([(b'{"items":{"tokenautenticacao":"one","tokenautenticacao":"two"}}', 200)])
    with pytest.raises(CredentialExchangeError) as raised:
        transport.send(data_request())
    assert raised.value.reason is AuthenticationFailureReason.RESPONSE_JSON_AMBIGUOUS


def test_exchange_response_url_must_equal_exact_request() -> None:
    transport, _, _ = wrapper([(_AUTH_BODY, 200, "application/json", "https://www.ana.gov.br/wrong")])
    with pytest.raises(CredentialExchangeError) as raised:
        transport.send(data_request())
    assert raised.value.reason is AuthenticationFailureReason.EXCHANGE_RESPONSE_MISMATCH


@pytest.mark.parametrize(
    "echo_kind",
    ["identifier", "password", "token", "bearer", "auth_response", "ordinary_header"],
)
def test_successful_bearer_response_rejects_every_known_secret_echo(echo_kind: str) -> None:
    actions = {
        "identifier": (b'{"data":1}', 200, _IDENTIFIER),
        "password": (b'{"data":1}', 200, _PASSWORD),
        "token": (b'{"data":1}', 200, _TOKEN),
        "bearer": (b'{"data":1}', 200, f"Bearer {_TOKEN}"),
        "auth_response": (_AUTH_BODY, 200, "application/json"),
        "ordinary_header": (
            b'{"data":1}',
            200,
            "application/json",
            None,
            {"Accept": _TOKEN, "User-Agent": "RivRetrieve"},
        ),
    }
    data_action = actions.pop(echo_kind)
    actions.clear()
    transport, _, _ = wrapper([(_AUTH_BODY, 200), data_action])
    try:
        transport.send(data_request())
    except CredentialExchangeError as error:
        del data_action
        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert error.reason is AuthenticationFailureReason.RETAINED_METADATA_UNSAFE
        for secret in (_IDENTIFIER, _PASSWORD, _TOKEN, "FULL-AUTH-RESPONSE"):
            assert secret not in rendered
        assert error.__cause__ is None and error.__context__ is None
    else:
        raise AssertionError("secret echo was not refused")


def test_acquisition_trace_survives_first_data_failure_until_one_success() -> None:
    transport, _, _ = wrapper(
        [(_AUTH_BODY, 200), RuntimeError("first data failure"), (b'{"data":2}', 200), (b'{"data":3}', 200)]
    )
    with pytest.raises(CredentialExchangeError):
        transport.send(data_request())
    second = transport.send(data_request())
    third = transport.send(data_request())
    assert len(second.prerequisite_calls) == 1
    assert third.prerequisite_calls == ()


def test_refresh_uses_injected_monotonic_clock_before_at_and_after_boundaries() -> None:
    transport, _, clock = wrapper(
        [
            (_AUTH_BODY, 200),
            (b'{"data":1}', 200),
            (b'{"data":2}', 200),
            (_AUTH_BODY, 200),
            (b'{"data":3}', 200),
            (_AUTH_BODY, 200),
            (b'{"data":4}', 200),
        ]
    )
    first = transport.send(data_request())
    assert len(first.prerequisite_calls) == 1
    clock.value = 3309.999
    before = transport.send(data_request())
    assert before.prerequisite_calls == ()
    clock.value = 3310.0
    at = transport.send(data_request())
    assert len(at.prerequisite_calls) == 1
    clock.value = 6610.001
    after = transport.send(data_request())
    assert len(after.prerequisite_calls) == 1


def test_sanitized_auth_failures_emit_no_logs(caplog) -> None:
    transport, _, _ = wrapper([RuntimeError("secret sender detail")])
    with pytest.raises(CredentialExchangeError):
        transport.send(data_request())
    assert caplog.records == []


def _non_data_origin_secret_request(value: str, location: str) -> TransportRequest:
    url = "https://other.example/data"
    params = None
    headers = {"Accept": "application/json"}
    body = None
    if location == "url":
        url += f"/{value}"
    elif location == "parameter":
        params = {"value": value}
    elif location == "ordinary_header":
        headers = {"Accept": value}
    elif location == "body":
        body = value
    return TransportRequest(HttpMethod.GET, url, params, headers, body)


@pytest.mark.parametrize("location", ["url", "parameter", "ordinary_header", "body"])
def test_exchange_wrapper_refuses_identifier_or_password_on_non_data_origin_before_delegation(location: str) -> None:
    transport, raw, _ = wrapper([])
    try:
        transport.send(_non_data_origin_secret_request(_IDENTIFIER, location))
    except CredentialExchangeError as error:
        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert _IDENTIFIER not in rendered
        assert _PASSWORD not in rendered
        assert raw.requests == []
        assert error.__cause__ is None and error.__context__ is None
    else:
        raise AssertionError("owned exchange secret crossed to another origin")


def test_exchange_wrapper_refuses_cached_token_on_non_data_origin_before_delegation() -> None:
    transport, raw, _ = wrapper([(_AUTH_BODY, 200), (b'{"data":1}', 200)])
    transport.send(data_request())
    assert len(raw.requests) == 2
    try:
        transport.send(_non_data_origin_secret_request(_TOKEN, "body"))
    except CredentialExchangeError as error:
        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert _TOKEN not in rendered
        assert len(raw.requests) == 2
    else:
        raise AssertionError("cached token crossed to another origin")


def _token_trace_data_action():
    from rivretrieve._internal.transport import RequestBodyShape, SecretCallTrace

    trace = SecretCallTrace(
        HttpMethod.GET,
        "https://prerequisite.example/token",
        {"Accept": _TOKEN},
        None,
        RequestBodyShape.NONE,
        ("X-Auth",),
        200,
        datetime(2026, 1, 1, tzinfo=UTC),
        "application/json",
    )
    return (b'{"data":1}', 200, "application/json", None, None, (trace,))


def test_exchange_wrapper_rejects_raw_token_echo_in_untrusted_prerequisite_trace() -> None:
    transport, _, _ = wrapper([(_AUTH_BODY, 200), _token_trace_data_action()])
    try:
        transport.send(data_request())
    except CredentialExchangeError as error:
        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert error.reason is AuthenticationFailureReason.RETAINED_METADATA_UNSAFE
        assert _TOKEN not in rendered
        assert error.__cause__ is None and error.__context__ is None
    else:
        raise AssertionError("token-bearing prerequisite trace was not refused")


def test_non_ascii_authentication_envelope_metadata_does_not_break_secret_scanning() -> None:
    authentication_body = '{"items":{"tokenautenticacao":"TOKEN-ABC-123","label":"á"}}'.encode()
    transport, _, _ = wrapper([(authentication_body, 200), (b'{"data":1}', 200)])
    response = transport.send(data_request())
    assert response.content == b'{"data":1}'


def _encoded_token_layers(count: int) -> str:
    from urllib.parse import quote

    encoded = "".join(f"%{byte:02X}" for byte in _TOKEN.encode())
    for _ in range(count - 1):
        encoded = quote(encoded, safe="")
    return encoded


@pytest.mark.parametrize("layers", [1, 2, 9])
def test_exchange_wrapper_refuses_encoded_cached_token_on_non_data_origin(layers: int) -> None:
    transport, raw, _ = wrapper([(_AUTH_BODY, 200), (b'{"data":1}', 200)])
    transport.send(data_request())
    encoded = _encoded_token_layers(layers)
    try:
        transport.send(TransportRequest(HttpMethod.GET, f"https://other.example/data?token={encoded}"))
    except CredentialExchangeError as error:
        encoded = ""
        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert _TOKEN not in rendered
        assert "%54%4F%4B%45%4E" not in rendered
        assert "%2554%254F%254B%2545%254E" not in rendered
        assert len(raw.requests) == 2
        assert error.request.url == "https://redacted.invalid"
    else:
        raise AssertionError("encoded cached token crossed to another origin")


def test_exchange_wrapper_rejects_double_encoded_token_in_response_metadata() -> None:
    transport, _, _ = wrapper([(_AUTH_BODY, 200), (b'{"data":1}', 200, _encoded_token_layers(2))])
    try:
        transport.send(data_request())
    except CredentialExchangeError as error:
        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert _TOKEN not in rendered
        assert "%2554%254F%254B%2545%254E" not in rendered
        assert error.reason is AuthenticationFailureReason.RETAINED_METADATA_UNSAFE
    else:
        raise AssertionError("encoded token response metadata escaped")

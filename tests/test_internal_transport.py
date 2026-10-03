from dataclasses import fields
from datetime import UTC, datetime
from typing import Any, cast, get_type_hints

import pytest
import requests

from rivretrieve._internal.transport import (
    TRANSPORT_POLICY,
    AuthenticatedTransport,
    Clock,
    CredentialHeader,
    HttpClient,
    HttpMethod,
    Sender,
    TransportFailure,
    TransportFailureReason,
    TransportPolicy,
    TransportRequest,
    TransportResponse,
)

_OTHER_ORIGIN_SECRET = "SENTINEL-OTHER-ORIGIN-SECRET"
_COLLISION_SENTINEL = "SENTINEL-STATIC-COLLISION"
_TRACE_SENTINEL = "SENTINEL-TRACEBACK-SECRET"


class FakeClock:
    def __init__(self) -> None:
        self.monotonic_time = 0.0
        self.utc_time = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.monotonic_time

    def utcnow(self) -> datetime:
        return self.utc_time


class FakeSleeper:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.calls: list[float] = []

    def __call__(self, duration: float) -> None:
        self.calls.append(duration)
        self.clock.monotonic_time += duration


Action = tuple[bytes, int, str | None] | BaseException


class RecordingSender:
    def __init__(self, actions: list[Action], clock: FakeClock | None = None) -> None:
        self.actions = actions
        self.clock = clock
        self.calls: list[tuple[TransportRequest, float]] = []
        self.started_at: list[float] = []

    def __call__(self, request: Any, timeout_seconds: float) -> tuple[bytes, int, str | None]:
        self.calls.append((request, timeout_seconds))
        if self.clock is not None:
            self.started_at.append(self.clock.monotonic())
        action = self.actions[len(self.calls) - 1]
        if isinstance(action, BaseException):
            raise action
        return action


def make_client(
    actions: list[Action],
) -> tuple[HttpClient, RecordingSender, FakeClock, FakeSleeper]:
    clock = FakeClock()
    sleeper = FakeSleeper(clock)
    sender = RecordingSender(actions, clock)
    return HttpClient(sender=sender, clock=clock, sleeper=sleeper), sender, clock, sleeper


@pytest.mark.parametrize(
    ("method", "body"),
    [(HttpMethod.GET, None), (HttpMethod.POST, b"payload"), (HttpMethod.POST, "text payload")],
)
def test_successful_get_and_post_preserve_source_request_and_byte_response(
    method: HttpMethod, body: bytes | str | None
) -> None:
    client, sender, clock, _ = make_client([(b"\x82\xa0", 201, "application/octet-stream; charset=binary")])
    params = {"station": "123", "limit": 2, "threshold": 1.5, "optional": None}
    request = TransportRequest(
        method=method,
        url="https://source.example/data",
        params=params,
        headers={
            "Accept": "application/octet-stream",
        },
        body=body,
    )

    response = client.send(request)

    sent_request, _ = sender.calls[0]
    assert sent_request == TransportRequest(
        method=method,
        url=request.url,
        params=request.params,
        headers={**request.headers, "User-Agent": TRANSPORT_POLICY.user_agent},
        body=body,
    )
    assert response == TransportResponse(
        content=b"\x82\xa0",
        status_code=201,
        retrieved_at=clock.utc_time,
        content_type="application/octet-stream; charset=binary",
        url="https://source.example/data",
        request_parameters={"station": "123", "limit": 2, "threshold": 1.5, "optional": None},
    )
    assert response.retrieved_at.tzinfo is UTC
    params["station"] = "mutated"
    assert response.request_parameters["station"] == "123"
    with pytest.raises(TypeError):
        cast("dict[str, object]", response.request_parameters)["station"] = "mutated"
    response_fields = fields(TransportResponse)
    scanned = (
        str(response),
        repr(response),
        *(str(getattr(response, field.name)) for field in response_fields),
    )
    for forbidden in (
        "Bearer transport-secret",
        "api-key-secret",
        "Authorization",
        "X-API-Key",
    ):
        assert all(forbidden not in candidate for candidate in scanned)
    assert "headers" not in {field.name for field in response_fields}


def test_policy_timeout_is_passed_to_every_sender_attempt() -> None:
    client, sender, _, _ = make_client([(b"retry", 503, "text/plain"), (b"ok", 200, "text/plain")])

    client.send(TransportRequest(HttpMethod.GET, "https://source.example"))

    assert [timeout for _, timeout in sender.calls] == [TRANSPORT_POLICY.timeout_seconds] * 2
    assert TRANSPORT_POLICY.timeout_seconds == 60.0


def test_absent_content_type_survives_transport() -> None:
    client, _, _, _ = make_client([(b"ok", 200, None)])

    response = client.send(TransportRequest(HttpMethod.GET, "https://source.example"))

    assert response.content_type is None


@pytest.mark.parametrize("override", ["User-Agent", "user-agent"])
def test_user_agent_is_mandatory_and_source_override_is_rejected(override: str) -> None:
    allowed_headers = {
        "Accept": "application/json",
        "Content-type": "application/vnd.flux",
    }
    client, sender, _, _ = make_client([(b"ok", 200, "text/plain")])
    client.send(TransportRequest(HttpMethod.GET, "https://source.example", headers=allowed_headers))
    assert sender.calls[0][0].headers == {**allowed_headers, "User-Agent": TRANSPORT_POLICY.user_agent}

    rejected_client, rejected_sender, _, _ = make_client([(b"unreachable", 200, "text/plain")])
    with pytest.raises(ValueError, match="User-Agent"):
        rejected_client.send(
            TransportRequest(HttpMethod.GET, "https://source.example", headers={override: "source-agent"})
        )
    assert rejected_sender.calls == []


@pytest.mark.parametrize("failure", [TimeoutError("timed out"), ConnectionError("disconnected")])
def test_retryable_sender_failure_is_retried_then_succeeds(failure: Exception) -> None:
    client, sender, _, _ = make_client([failure, (b"ok", 200, "text/plain")])

    response = client.send(TransportRequest(HttpMethod.GET, "https://source.example"))

    assert len(sender.calls) == 2
    assert response.status_code == 200


@pytest.mark.parametrize("status_code", [408, 429, 500, 502, 503, 504])
def test_retryable_http_status_is_retried_then_succeeds(status_code: int) -> None:
    client, sender, _, _ = make_client([(b"transient", status_code, "text/plain"), (b"ok", 200, "text/plain")])

    response = client.send(TransportRequest(HttpMethod.GET, "https://source.example"))

    assert len(sender.calls) == 2
    assert response == TransportResponse(b"ok", 200, FakeClock().utc_time, "text/plain", "https://source.example", {})


@pytest.mark.parametrize("status_code", [400, 401, 404, 422])
def test_non_retryable_status_is_immediately_inspectable_including_404(status_code: int) -> None:
    client, sender, clock, sleeper = make_client([(b"source response", status_code, "text/plain")])

    response = client.send(TransportRequest(HttpMethod.GET, "https://source.example"))

    assert len(sender.calls) == 1
    assert sleeper.calls == []
    assert response == TransportResponse(
        b"source response", status_code, clock.utc_time, "text/plain", "https://source.example", {}
    )
    if status_code == 404:
        assert response.status_code == 404


def test_retry_backoff_uses_the_exact_deterministic_schedule() -> None:
    client, _, _, sleeper = make_client([TimeoutError(), (b"retry", 503, "text/plain"), (b"ok", 200, "text/plain")])

    client.send(TransportRequest(HttpMethod.GET, "https://source.example"))

    assert sleeper.calls == list(TRANSPORT_POLICY.backoff_seconds) == [1.0, 2.0]


def test_rate_limit_waits_between_successive_calls_on_one_client() -> None:
    client, sender, _, sleeper = make_client([(b"first", 200, "text/plain"), (b"second", 200, "text/plain")])
    request = TransportRequest(HttpMethod.GET, "https://source.example")

    client.send(request)
    client.send(request)

    assert sender.started_at == [0.0, TRANSPORT_POLICY.minimum_interval_seconds]
    assert sleeper.calls == [TRANSPORT_POLICY.minimum_interval_seconds]

    other_client, other_sender, _, other_sleeper = make_client([(b"independent", 200, "text/plain")])
    other_client.send(request)
    assert other_sender.started_at == [0.0]
    assert other_sleeper.calls == []


@pytest.mark.parametrize(
    ("actions", "last_status"),
    [
        ([(b"retry", 503, "text/plain")] * TRANSPORT_POLICY.max_attempts, 503),
        ([TimeoutError()] * TRANSPORT_POLICY.max_attempts, None),
    ],
)
def test_retry_exhaustion_reports_attempts_and_last_status(actions: list[Action], last_status: int | None) -> None:
    client, sender, _, sleeper = make_client(actions)
    request = TransportRequest(HttpMethod.GET, "https://source.example")

    with pytest.raises(TransportFailure) as raised:
        client.send(request)

    assert raised.value.request == request
    assert raised.value.reason is TransportFailureReason.RETRY_EXHAUSTED
    assert raised.value.attempts == TRANSPORT_POLICY.max_attempts == 3
    assert raised.value.status_code == last_status
    assert len(sender.calls) == TRANSPORT_POLICY.max_attempts
    assert sleeper.calls == list(TRANSPORT_POLICY.backoff_seconds)


class TerminalRequestFailure(requests.RequestException):
    pass


@pytest.mark.parametrize("failure", [requests.Timeout(), requests.ConnectionError()])
def test_requests_exceptions_are_translated_to_transport_neutral_failures(failure: requests.RequestException) -> None:
    request = TransportRequest(HttpMethod.GET, "https://source.example")
    terminal_client, _, _, _ = make_client([TerminalRequestFailure("terminal")])

    with pytest.raises(TransportFailure) as terminal:
        terminal_client.send(request)
    assert terminal.value.reason is TransportFailureReason.TERMINAL_SENDER_FAILURE
    assert terminal.value.attempts == 1
    assert terminal.value.status_code is None
    assert isinstance(terminal.value.__cause__, TerminalRequestFailure)

    retry_client, _, _, _ = make_client([failure] * TRANSPORT_POLICY.max_attempts)
    with pytest.raises(TransportFailure) as exhausted:
        retry_client.send(request)
    assert exhausted.value.reason is TransportFailureReason.RETRY_EXHAUSTED
    assert exhausted.value.attempts == TRANSPORT_POLICY.max_attempts
    assert exhausted.value.status_code is None
    assert exhausted.value.__cause__ is failure

    public_objects: list[Any] = [
        HttpMethod,
        TransportRequest,
        TransportResponse,
        TransportFailureReason,
        TransportFailure,
        Sender,
        Clock,
        TransportPolicy,
        HttpClient,
        HttpClient.__init__,
        HttpClient.send,
    ]
    annotations = " ".join(str(get_type_hints(obj)) for obj in public_objects)
    assert "requests" not in annotations


def test_authenticated_transport_applies_sentinel_without_exposing_it() -> None:
    from datetime import UTC, datetime

    from rivretrieve._internal.transport import (
        AuthenticatedTransport,
        CredentialHeader,
        HttpMethod,
        TransportRequest,
        TransportResponse,
    )

    class Capture:
        request = None

        def send(self, request):
            self.request = request
            return TransportResponse(
                b"ok", 200, datetime(2026, 1, 1, tzinfo=UTC), "text/plain", request.url, request.params or {}
            )

    sentinel = "SENTINEL-NOT-A-REAL-TOKEN"
    capture = Capture()
    wrapped = AuthenticatedTransport(
        capture, (CredentialHeader("Authorization", f"Token {sentinel}", ("https://example.test",)),)
    )
    original = TransportRequest(HttpMethod.POST, "https://example.test", headers={"Accept": "text/csv"})
    wrapped.send(original)
    assert capture.request is not None
    assert capture.request.headers == {"Accept": "text/csv", "Authorization": f"Token {sentinel}"}
    assert original.headers == {"Accept": "text/csv"}
    assert sentinel not in repr(wrapped) and sentinel not in repr(wrapped.credentials)


def test_authenticated_transport_validates_headers_and_rejects_collisions() -> None:
    import pytest

    from rivretrieve._internal.transport import AuthenticatedTransport, CredentialHeader, HttpMethod, TransportRequest

    for invalid_name in ("Bad:Name", "Bad Name", "Bäd", "Bad\x01Name"):
        with pytest.raises(TypeError):
            CredentialHeader(invalid_name, "value", ("https://example.test",))
    for invalid_value in ("line\nvalue", "tab\tvalue", "välue", ""):
        with pytest.raises(TypeError):
            CredentialHeader("X-API-Key", invalid_value, ("https://example.test",))

    class Never:
        def send(self, request):
            raise AssertionError(request)

    with pytest.raises(ValueError, match="unique"):
        AuthenticatedTransport(
            Never(),
            (
                CredentialHeader("X-API-Key", "a", ("https://example.test",)),
                CredentialHeader("x-api-key", "b", ("https://example.test",)),
            ),
        )
    with pytest.raises(ValueError, match="explicitly safe ordinary"):
        TransportRequest(HttpMethod.GET, "https://example.test", headers={"x-api-key": "source"})


def test_authenticated_transport_failure_contains_only_original_safe_request() -> None:
    import pytest

    from rivretrieve._internal.transport import (
        AuthenticatedTransport,
        CredentialHeader,
        HttpMethod,
        TransportFailure,
        TransportFailureReason,
        TransportRequest,
    )

    sentinel = "SENTINEL-FAILURE-NOT-A-REAL-CREDENTIAL"

    class Failing:
        def send(self, request):
            raise TransportFailure(request, TransportFailureReason.RETRY_EXHAUSTED, 3, status_code=503)

    original = TransportRequest(HttpMethod.GET, "https://example.test", headers={"Accept": "application/json"})
    wrapped = AuthenticatedTransport(Failing(), (CredentialHeader("X-API-Key", sentinel, ("https://example.test",)),))
    with pytest.raises(TransportFailure) as info:
        wrapped.send(original)
    assert info.value.request == original
    assert info.value.request is not original
    assert info.value.__cause__ is None
    assert (
        sentinel not in repr(info.value)
        and sentinel not in str(info.value)
        and sentinel not in repr(info.value.request)
    )


def test_authenticated_transport_applies_only_to_exact_scoped_origin() -> None:
    from datetime import UTC, datetime

    from rivretrieve._internal.transport import (
        AuthenticatedTransport,
        CredentialHeader,
        HttpMethod,
        TransportRequest,
        TransportResponse,
    )

    sentinel = "SENTINEL-SCOPED-CREDENTIAL"

    class Capture:
        def __init__(self):
            self.requests = []

        def send(self, request):
            self.requests.append(request)
            return TransportResponse(b"ok", 200, datetime(2026, 1, 1, tzinfo=UTC), "text/plain", request.url, {})

    capture = Capture()
    wrapped = AuthenticatedTransport(
        capture, (CredentialHeader("Authorization", sentinel, ("https://influx.konzept.space",)),)
    )
    urls = (
        "https://influx.konzept.space/data",
        "https://api.existenz.ch/data",
        "https://sub.influx.konzept.space/data",
        "http://influx.konzept.space/data",
    )
    for url in urls:
        wrapped.send(TransportRequest(HttpMethod.GET, url))
    assert wrapped.can_authenticate(urls[0]) is True
    assert all(wrapped.can_authenticate(url) is False for url in urls[1:])
    assert capture.requests[0].headers == {"Authorization": sentinel}
    assert all("Authorization" not in request.headers for request in capture.requests[1:])
    with pytest.raises(ValueError):
        wrapped.send(TransportRequest(HttpMethod.GET, "https://user@influx.konzept.space/data"))


def test_scoped_credentials_do_not_cross_real_requests_redirect() -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from rivretrieve._internal.transport import (
        AuthenticatedTransport,
        CredentialHeader,
        HttpClient,
        HttpMethod,
        TransportFailure,
        TransportRequest,
    )

    observed = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            observed.append(self.headers.get("X-API-Key"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"target")

        def log_message(self, format, *args):
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    target_thread = Thread(target=target.serve_forever, daemon=True)
    target_thread.start()
    target_url = f"http://127.0.0.1:{target.server_port}/target"

    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", target_url)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    source = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    source_thread = Thread(target=source.serve_forever, daemon=True)
    source_thread.start()
    source_origin = f"http://127.0.0.1:{source.server_port}"
    try:
        transport = AuthenticatedTransport(HttpClient(), (CredentialHeader("X-API-Key", "SENTINEL", (source_origin,)),))
        with pytest.raises(TransportFailure) as info:
            transport.send(TransportRequest(HttpMethod.GET, f"{source_origin}/redirect"))
        assert info.value.status_code == 302
        assert info.value.reason is TransportFailureReason.REDIRECT_REFUSED
        assert info.value.request.headers == {}
        assert observed == []
    finally:
        source.shutdown()
        target.shutdown()
        source.server_close()
        target.server_close()


def test_same_credential_header_name_is_allowed_for_disjoint_origins() -> None:
    from datetime import UTC, datetime

    from rivretrieve._internal.transport import (
        AuthenticatedTransport,
        CredentialHeader,
        HttpMethod,
        TransportRequest,
        TransportResponse,
    )

    class Capture:
        def __init__(self):
            self.requests = []

        def send(self, request):
            self.requests.append(request)
            return TransportResponse(b"ok", 200, datetime(2026, 1, 1, tzinfo=UTC), None, request.url, {})

    capture = Capture()
    wrapped = AuthenticatedTransport(
        capture,
        (
            CredentialHeader("Authorization", "Token CH", ("https://influx.konzept.space",)),
            CredentialHeader("authorization", "Bearer OTHER", ("https://other.example",)),
        ),
    )
    wrapped.send(TransportRequest(HttpMethod.GET, "https://influx.konzept.space/data"))
    wrapped.send(TransportRequest(HttpMethod.GET, "https://other.example/data"))
    assert capture.requests[0].headers == {"Authorization": "Token CH"}
    assert capture.requests[1].headers == {"authorization": "Bearer OTHER"}


def test_credential_origin_normalizes_scheme_defaults_and_ipv6() -> None:
    from rivretrieve._internal.transport import AuthenticatedTransport, CredentialHeader

    class Never:
        def send(self, request):
            raise AssertionError(request)

    https_default = AuthenticatedTransport(
        Never(), (CredentialHeader("X-Key", "value", ("https://EXAMPLE.test:443",)),)
    )
    assert https_default.can_authenticate("https://example.test/path")
    assert not https_default.can_authenticate("https://example.test:80/path")
    assert AuthenticatedTransport(
        Never(), (CredentialHeader("X-Key", "value", ("https://example.test:80",)),)
    ).can_authenticate("https://example.test:80/path")
    ipv6 = AuthenticatedTransport(Never(), (CredentialHeader("X-Key", "value", ("https://[::1]:8443",)),))
    assert ipv6.can_authenticate("https://[::1]:8443/path")


def test_credential_failure_traceback_locals_never_expose_value() -> None:
    import traceback

    from rivretrieve._internal.transport import (
        AuthenticatedTransport,
        CredentialHeader,
        HttpMethod,
        TransportFailure,
        TransportFailureReason,
        TransportRequest,
    )

    class ExpectedFailure:
        def send(self, request):
            raise TransportFailure(request, TransportFailureReason.RETRY_EXHAUSTED, 2, status_code=503)

    class UnexpectedFailure:
        def send(self, request):
            raise RuntimeError(f"upstream failed while handling {request!r}")

    for underlying in (ExpectedFailure(), UnexpectedFailure()):
        wrapped = AuthenticatedTransport(
            underlying, (CredentialHeader("X-Key", _TRACE_SENTINEL, ("https://example.test",)),)
        )
        try:
            wrapped.send(TransportRequest(HttpMethod.GET, "https://example.test/data"))
        except TransportFailure as error:
            rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
            assert _TRACE_SENTINEL not in rendered
            assert error.__cause__ is None and error.__context__ is None
        else:
            raise AssertionError("credentialed failure was not sanitized")


@pytest.mark.parametrize(
    ("origin", "matching", "separate"),
    [
        ("HTTP://EXAMPLE.test:80", "http://example.test/path", "http://example.test:8080/path"),
        ("HTTPS://EXAMPLE.test:443", "https://example.test/path", "https://example.test:80/path"),
        ("https://127.0.0.1:8443", "https://127.0.0.1:8443/path", "https://127.0.0.1/path"),
        ("https://[::1]:443", "https://[::1]/path", "https://[::1]:8443/path"),
        ("https://example.test.", "https://example.test./path", "https://example.test/path"),
    ],
)
def test_credential_origin_normalization_table(origin: str, matching: str, separate: str) -> None:
    class Never:
        def send(self, request):
            raise AssertionError(request)

    wrapped = AuthenticatedTransport(Never(), (CredentialHeader("X-Key", "value", (origin,)),))
    assert wrapped.can_authenticate(matching)
    assert not wrapped.can_authenticate(separate)


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.test:",
        "https://usér.example",
        "https://user@example.test",
        "https://user:password@example.test",
        "https://example.test/path",
        "https://example.test?query=1",
        "https://example.test#fragment",
        "ftp://example.test",
        "https:///missing",
    ],
)
def test_credential_origins_reject_ambiguous_authorities_and_non_origins(origin: str) -> None:
    with pytest.raises(ValueError):
        CredentialHeader("X-Key", "value", (origin,))


def test_transport_request_rejects_case_colliding_or_control_character_headers_before_send() -> None:
    with pytest.raises(ValueError, match="case-insensitively"):
        TransportRequest(HttpMethod.GET, "https://example.test", headers={"Accept": "text/csv", "accept": "text/csv"})
    with pytest.raises(ValueError, match="visible ASCII"):
        TransportRequest(HttpMethod.GET, "https://example.test", headers={"Accept": "text/csv\nsecret"})


def test_http_client_rejects_unclassified_execution_metadata_before_sender_call() -> None:
    client, sender, _, _ = make_client([(b"unreachable", 200, "text/plain")])
    with pytest.raises(ValueError, match="explicitly safe ordinary"):
        client.send(TransportRequest(HttpMethod.GET, "https://example.test", headers={"X-Unknown": "value"}))
    assert sender.calls == []


def test_public_mixed_case_credential_header_refusal_retains_no_caller_value() -> None:
    class Never:
        def send(self, request):
            raise AssertionError(request)

    wrapped = AuthenticatedTransport(
        Never(), (CredentialHeader("Authorization", "actual-secret", ("https://example.test",)),)
    )
    try:
        wrapped.send(
            TransportRequest(
                HttpMethod.GET,
                "https://example.test/data",
                headers={"Accept": "application/json", "aUtHoRiZaTiOn": _COLLISION_SENTINEL},
            )
        )
    except ValueError as error:
        import traceback

        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert _COLLISION_SENTINEL not in rendered
        assert error.__cause__ is None and error.__context__ is None
    else:
        raise AssertionError("collision was not refused")


def test_static_success_metadata_echo_is_sanitized_without_secret_traceback_locals() -> None:
    class Echo:
        def send(self, request):
            return TransportResponse(
                b"safe data",
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                _COLLISION_SENTINEL,
                request.url,
                {},
            )

    wrapped = AuthenticatedTransport(
        Echo(), (CredentialHeader("X-API-Key", _COLLISION_SENTINEL, ("https://example.test",)),)
    )
    try:
        wrapped.send(
            TransportRequest(HttpMethod.GET, "https://example.test/data", headers={"Accept": "application/json"})
        )
    except TransportFailure as error:
        import traceback

        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert error.reason is TransportFailureReason.RETAINED_METADATA_UNSAFE
        assert _COLLISION_SENTINEL not in rendered
        assert error.__cause__ is None and error.__context__ is None
    else:
        raise AssertionError("credential metadata echo was not refused")


def test_public_transport_request_has_no_credential_tagging_constructor_channel() -> None:
    import inspect

    assert "credential_header_names" not in inspect.signature(TransportRequest).parameters
    with pytest.raises(TypeError):
        TransportRequest(
            HttpMethod.GET,
            "https://example.test",
            credential_header_names=("Authorization",),  # ty: ignore[unknown-argument]
        )


@pytest.mark.parametrize("kind", ["mapping_proxy", "custom_mapping"])
def test_immutable_credential_header_mappings_are_detached_before_constructor_failure(kind: str) -> None:
    from collections.abc import Mapping
    from types import MappingProxyType

    class SecretMapping(Mapping):
        def __iter__(self):
            return iter(("Authorization",))

        def __len__(self):
            return 1

        def __getitem__(self, key):
            if key != "Authorization":
                raise KeyError(key)
            return _COLLISION_SENTINEL

        def __repr__(self):
            return f"SecretMapping({_COLLISION_SENTINEL})"

    try:
        if kind == "mapping_proxy":
            TransportRequest(
                HttpMethod.GET,
                "https://example.test",
                headers=MappingProxyType({"Authorization": _COLLISION_SENTINEL}),
            )
        else:
            TransportRequest(HttpMethod.GET, "https://example.test", headers=SecretMapping())
    except ValueError as error:
        import traceback

        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert _COLLISION_SENTINEL not in rendered
        assert error.__cause__ is None and error.__context__ is None
    else:
        raise AssertionError("credential-like mapping was not refused")


def test_unknown_and_control_header_refusals_detach_values_from_traceback() -> None:
    import traceback

    for make_headers in (
        lambda: {"X-Unknown": _COLLISION_SENTINEL},
        lambda: {"Accept": f"application/json\n{_COLLISION_SENTINEL}"},
    ):
        try:
            TransportRequest(HttpMethod.GET, "https://example.test", headers=make_headers())
        except ValueError as error:
            rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
            assert _COLLISION_SENTINEL not in rendered
        else:
            raise AssertionError("unsafe ordinary header was not refused")


def _cross_origin_secret_request(location: str) -> TransportRequest:
    url = "https://a.example.test/data"
    params = None
    headers = {"Accept": "application/json"}
    body = None
    if location == "url":
        url += f"/{_OTHER_ORIGIN_SECRET}"
    elif location == "parameter_name":
        params = {_OTHER_ORIGIN_SECRET: "value"}
    elif location == "parameter_value":
        params = {"value": _OTHER_ORIGIN_SECRET}
    elif location == "ordinary_header":
        headers = {"Accept": _OTHER_ORIGIN_SECRET}
    elif location == "body":
        body = _OTHER_ORIGIN_SECRET
    return TransportRequest(HttpMethod.GET, url, params, headers, body)


@pytest.mark.parametrize("location", ["url", "parameter_name", "parameter_value", "ordinary_header", "body"])
def test_static_transport_refuses_any_owned_secret_cross_origin_before_delegation(location: str) -> None:
    import traceback

    class Capture:
        def __init__(self):
            self.calls = []

        def send(self, request):
            self.calls.append(request)
            raise AssertionError("must not delegate")

    capture = Capture()
    wrapped = AuthenticatedTransport(
        capture,
        (
            CredentialHeader("X-A", "secret-a", ("https://a.example.test",)),
            CredentialHeader("X-B", _OTHER_ORIGIN_SECRET, ("https://b.example.test",)),
        ),
    )
    try:
        wrapped.send(_cross_origin_secret_request(location))
    except TransportFailure as error:
        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert _OTHER_ORIGIN_SECRET not in rendered
        assert _OTHER_ORIGIN_SECRET not in repr(error.request)
        assert error.__cause__ is None and error.__context__ is None
        assert capture.calls == []
    else:
        raise AssertionError("cross-origin owned secret was not refused")


def test_static_transport_scans_untrusted_prerequisite_trace_fields_for_owned_secrets() -> None:
    import traceback

    from rivretrieve._internal.transport import RequestBodyShape, SecretCallTrace

    trace = SecretCallTrace(
        HttpMethod.GET,
        "https://auth.example.test/token",
        {"Accept": _COLLISION_SENTINEL},
        None,
        RequestBodyShape.NONE,
        ("X-Auth",),
        200,
        datetime(2026, 1, 1, tzinfo=UTC),
        "application/json",
    )

    class Echo:
        def __init__(self, call):
            self.call = call

        def send(self, request):
            return TransportResponse(
                b"data",
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
                prerequisite_calls=(self.call,),
            )

    wrapped = AuthenticatedTransport(
        Echo(trace), (CredentialHeader("X-API-Key", _COLLISION_SENTINEL, ("https://example.test",)),)
    )
    try:
        wrapped.send(TransportRequest(HttpMethod.GET, "https://example.test/data"))
    except TransportFailure as error:
        del trace
        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert _COLLISION_SENTINEL not in rendered
        assert error.reason is TransportFailureReason.RETAINED_METADATA_UNSAFE
    else:
        raise AssertionError("secret-bearing prerequisite trace was not refused")


def _percent_encode_every_byte(value: str) -> str:
    return "".join(f"%{byte:02X}" for byte in value.encode())


def _percent_layers(value: str, count: int) -> str:
    from urllib.parse import quote

    encoded = _percent_encode_every_byte(value)
    for _ in range(count - 1):
        encoded = quote(encoded, safe="")
    return encoded


@pytest.mark.parametrize(("location", "layers"), [("url", 1), ("url", 2), ("url", 9), ("body", 1), ("body", 2)])
def test_static_transport_refuses_encoded_owned_secret_before_cross_origin_delegation(
    location: str, layers: int
) -> None:
    import traceback

    class Capture:
        def __init__(self):
            self.calls = []

        def send(self, request):
            self.calls.append(request)
            raise AssertionError("must not delegate")

    encoded = _percent_layers(_OTHER_ORIGIN_SECRET, layers)
    capture = Capture()
    wrapped = AuthenticatedTransport(
        capture,
        (CredentialHeader("X-B", _OTHER_ORIGIN_SECRET, ("https://b.example.test",)),),
    )
    try:
        request = (
            TransportRequest(HttpMethod.GET, f"https://a.example.test/data?value={encoded}")
            if location == "url"
            else TransportRequest(
                HttpMethod.POST,
                "https://a.example.test/data",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=f"value={encoded}",
            )
        )
        wrapped.send(request)
    except TransportFailure as error:
        request = None
        encoded = ""
        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert _OTHER_ORIGIN_SECRET not in rendered
        assert "%53%45%4E%54" not in rendered
        assert "%2553%2545%254E%2554" not in rendered
        assert capture.calls == []
        assert "redacted.invalid" in error.request.url or error.request.body is None
    else:
        raise AssertionError("encoded secret was delegated")


def test_encoded_secret_in_untrusted_response_metadata_never_escapes_wrapper() -> None:
    import traceback

    class Echo:
        def send(self, request):
            return TransportResponse(
                b"safe",
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                _percent_layers(_OTHER_ORIGIN_SECRET, 2),
                request.url,
                {},
            )

    wrapped = AuthenticatedTransport(
        Echo(), (CredentialHeader("X-B", _OTHER_ORIGIN_SECRET, ("https://b.example.test",)),)
    )
    try:
        wrapped.send(TransportRequest(HttpMethod.GET, "https://a.example.test/data"))
    except TransportFailure as error:
        rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
        assert _OTHER_ORIGIN_SECRET not in rendered
        assert "%2553%2545%254E%2554" not in rendered
        assert error.reason is TransportFailureReason.RETAINED_METADATA_UNSAFE
    else:
        raise AssertionError("encoded response secret escaped")


@pytest.mark.parametrize("consumer", ["http", "replay"])
def test_forged_private_credential_request_lacks_internal_authority(consumer: str) -> None:
    from rivretrieve._internal.transport import RedirectPolicy, _CredentialTransportRequest

    forged = object.__new__(_CredentialTransportRequest)
    object.__setattr__(forged, "method", HttpMethod.GET)
    object.__setattr__(forged, "url", "https://example.test/data")
    object.__setattr__(forged, "params", None)
    object.__setattr__(forged, "headers", {"X-Key": _COLLISION_SENTINEL})
    object.__setattr__(forged, "body", None)
    object.__setattr__(forged, "redirect_policy", RedirectPolicy.REFUSE)
    object.__setattr__(forged, "credential_header_names", ("X-Key",))
    with pytest.raises(TypeError, match="lacks internal transport authority"):
        if consumer == "http":
            HttpClient(
                sender=lambda request, timeout_seconds: (_ for _ in ()).throw(AssertionError("must not send"))
            ).send(forged)
        else:
            from rivretrieve._internal.recordings import ReplayTransport

            ReplayTransport([])._resolve(forged)

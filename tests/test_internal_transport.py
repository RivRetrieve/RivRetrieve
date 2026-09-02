from dataclasses import fields
from datetime import UTC, datetime
from typing import Any, get_type_hints

import pytest
import requests

from rivretrieve._internal.transport import (
    TRANSPORT_POLICY,
    Clock,
    HttpClient,
    HttpMethod,
    Sender,
    TransportFailure,
    TransportFailureReason,
    TransportPolicy,
    TransportRequest,
    TransportResponse,
)


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

    def __call__(self, request: TransportRequest, timeout_seconds: float) -> tuple[bytes, int, str | None]:
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
            "Referer": "https://source.example/",
            "Authorization": "Bearer transport-secret",
            "X-API-Key": "api-key-secret",
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
        response.request_parameters["station"] = "mutated"  # type: ignore[index]
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
        "Referer",
        "Accept",
        "User-Agent",
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
        "Authorization": "Bearer secret",
        "X-API-Key": "secret",
        "Accept": "application/json",
        "Content-type": "application/vnd.flux",
        "Referer": "https://source.example/",
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


@pytest.mark.parametrize("status_code", sorted(TRANSPORT_POLICY.retryable_status_codes))
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
    wrapped = AuthenticatedTransport(Never(), (CredentialHeader("X-API-Key", "secret", ("https://example.test",)),))
    with pytest.raises(ValueError, match="already provides"):
        wrapped.send(TransportRequest(HttpMethod.GET, "https://example.test", headers={"x-api-key": "source"}))


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
    assert info.value.request is original
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
    for malformed in ("https://user@influx.konzept.space/data", "https://influx.konzept.space:443/data"):
        with pytest.raises(ValueError):
            wrapped.send(TransportRequest(HttpMethod.GET, malformed))

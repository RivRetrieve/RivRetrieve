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


Action = tuple[bytes, int] | BaseException


class RecordingSender:
    def __init__(self, actions: list[Action], clock: FakeClock | None = None) -> None:
        self.actions = actions
        self.clock = clock
        self.calls: list[tuple[TransportRequest, float]] = []
        self.started_at: list[float] = []

    def __call__(self, request: TransportRequest, timeout_seconds: float) -> tuple[bytes, int]:
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
    client, sender, clock, _ = make_client([(b"\x82\xa0", 201)])
    request = TransportRequest(
        method=method,
        url="https://source.example/data",
        params={"station": "123", "limit": 2, "threshold": 1.5, "optional": None},
        headers={"Accept": "application/octet-stream", "Referer": "https://source.example/"},
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
    assert response == TransportResponse(content=b"\x82\xa0", status_code=201, retrieved_at=clock.utc_time)
    assert response.retrieved_at.tzinfo is UTC


def test_policy_timeout_is_passed_to_every_sender_attempt() -> None:
    client, sender, _, _ = make_client([(b"retry", 503), (b"ok", 200)])

    client.send(TransportRequest(HttpMethod.GET, "https://source.example"))

    assert [timeout for _, timeout in sender.calls] == [TRANSPORT_POLICY.timeout_seconds] * 2
    assert TRANSPORT_POLICY.timeout_seconds == 60.0


@pytest.mark.parametrize("override", ["User-Agent", "user-agent"])
def test_user_agent_is_mandatory_and_source_override_is_rejected(override: str) -> None:
    allowed_headers = {
        "Authorization": "Bearer secret",
        "X-API-Key": "secret",
        "Accept": "application/json",
        "Content-type": "application/vnd.flux",
        "Referer": "https://source.example/",
    }
    client, sender, _, _ = make_client([(b"ok", 200)])
    client.send(TransportRequest(HttpMethod.GET, "https://source.example", headers=allowed_headers))
    assert sender.calls[0][0].headers == {**allowed_headers, "User-Agent": TRANSPORT_POLICY.user_agent}

    rejected_client, rejected_sender, _, _ = make_client([(b"unreachable", 200)])
    with pytest.raises(ValueError, match="User-Agent"):
        rejected_client.send(
            TransportRequest(HttpMethod.GET, "https://source.example", headers={override: "source-agent"})
        )
    assert rejected_sender.calls == []


@pytest.mark.parametrize("failure", [TimeoutError("timed out"), ConnectionError("disconnected")])
def test_retryable_sender_failure_is_retried_then_succeeds(failure: Exception) -> None:
    client, sender, _, _ = make_client([failure, (b"ok", 200)])

    response = client.send(TransportRequest(HttpMethod.GET, "https://source.example"))

    assert len(sender.calls) == 2
    assert response.status_code == 200


@pytest.mark.parametrize("status_code", sorted(TRANSPORT_POLICY.retryable_status_codes))
def test_retryable_http_status_is_retried_then_succeeds(status_code: int) -> None:
    client, sender, _, _ = make_client([(b"transient", status_code), (b"ok", 200)])

    response = client.send(TransportRequest(HttpMethod.GET, "https://source.example"))

    assert len(sender.calls) == 2
    assert response == TransportResponse(b"ok", 200, FakeClock().utc_time)


@pytest.mark.parametrize("status_code", [400, 401, 404, 422])
def test_non_retryable_status_is_immediately_inspectable_including_404(status_code: int) -> None:
    client, sender, clock, sleeper = make_client([(b"source response", status_code)])

    response = client.send(TransportRequest(HttpMethod.GET, "https://source.example"))

    assert len(sender.calls) == 1
    assert sleeper.calls == []
    assert response == TransportResponse(b"source response", status_code, clock.utc_time)
    if status_code == 404:
        assert response.status_code == 404


def test_retry_backoff_uses_the_exact_deterministic_schedule() -> None:
    client, _, _, sleeper = make_client([TimeoutError(), (b"retry", 503), (b"ok", 200)])

    client.send(TransportRequest(HttpMethod.GET, "https://source.example"))

    assert sleeper.calls == list(TRANSPORT_POLICY.backoff_seconds) == [1.0, 2.0]


def test_rate_limit_waits_between_successive_calls_on_one_client() -> None:
    client, sender, _, sleeper = make_client([(b"first", 200), (b"second", 200)])
    request = TransportRequest(HttpMethod.GET, "https://source.example")

    client.send(request)
    client.send(request)

    assert sender.started_at == [0.0, TRANSPORT_POLICY.minimum_interval_seconds]
    assert sleeper.calls == [TRANSPORT_POLICY.minimum_interval_seconds]

    other_client, other_sender, _, other_sleeper = make_client([(b"independent", 200)])
    other_client.send(request)
    assert other_sender.started_at == [0.0]
    assert other_sleeper.calls == []


@pytest.mark.parametrize(
    ("actions", "last_status"),
    [
        ([(b"retry", 503)] * TRANSPORT_POLICY.max_attempts, 503),
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

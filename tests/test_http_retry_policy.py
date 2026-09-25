"""Retry policy and credential boundaries, with no external HTTP service."""

import traceback
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from http.client import IncompleteRead
from typing import Any

import pytest
import requests
from urllib3.exceptions import ProtocolError

from rivretrieve._internal.transport import (
    TRANSPORT_POLICY,
    AuthenticatedTransport,
    CredentialHeader,
    HttpClient,
    HttpMethod,
    RedirectPolicy,
    ReplaySafety,
    SenderResponse,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
)

_ORIGIN = "https://source.example"
_SECRET = "SENTINEL-RETRY-CREDENTIAL"


class PolicyClock:
    def __init__(self):
        self.elapsed = 0.0
        self.start = datetime(2026, 9, 25, 12, tzinfo=UTC)
        self.sleeps = []

    def monotonic(self):
        return self.elapsed

    def utcnow(self):
        return self.start + timedelta(seconds=self.elapsed)

    def sleep(self, seconds):
        assert 0 <= seconds <= TRANSPORT_POLICY.max_retry_delay_seconds
        self.sleeps.append(seconds)
        self.elapsed += seconds


class ScriptedSender:
    def __init__(self, actions, clock):
        self.actions = iter(actions)
        self.clock = clock
        self.calls = []
        self.starts = []

    def __call__(self, request: Any, timeout_seconds):
        self.calls.append(request)
        self.starts.append(self.clock.monotonic())
        assert timeout_seconds == TRANSPORT_POLICY.timeout_seconds
        action = next(self.actions)
        if isinstance(action, BaseException):
            raise action
        return action


def client_for(actions):
    clock = PolicyClock()
    sender = ScriptedSender(actions, clock)
    return HttpClient(sender=sender, clock=clock, sleeper=clock.sleep), sender, clock


def interrupted(message="response ended"):
    return requests.exceptions.ChunkedEncodingError(ProtocolError(message, IncompleteRead(b"partial", 10)))


def authenticated(client):
    return AuthenticatedTransport(client, (CredentialHeader("Authorization", f"Bearer {_SECRET}", (_ORIGIN,)),))


@pytest.mark.parametrize("status", sorted(TRANSPORT_POLICY.retryable_status_codes))
def test_head_retries_status_without_a_response_body(status):
    client, sender, clock = client_for([(b"", status, None), (b"", 200, None)])
    response = client.send(TransportRequest(HttpMethod.HEAD, _ORIGIN))
    assert response.content == b""
    assert response.status_code == 200
    assert sender.starts == [0.0, 1.0]
    assert clock.sleeps == [1.0]


@pytest.mark.parametrize("trigger", ["timeout", "status", "interruption"])
@pytest.mark.parametrize("safe", [False, True])
@pytest.mark.parametrize("credentialed", [False, True])
def test_post_replay_safety_applies_to_every_retry_trigger(trigger, safe, credentialed):
    first = {"timeout": requests.Timeout("timeout"), "status": (b"busy", 503, None), "interruption": interrupted()}[
        trigger
    ]
    client, sender, clock = client_for([first, (b"complete", 200, "text/csv")])
    transport = authenticated(client) if credentialed else client
    request = TransportRequest(
        HttpMethod.POST,
        _ORIGIN,
        body=b"read-only query",
        replay_safety=ReplaySafety.SAFE if safe else ReplaySafety.METHOD_DEFAULT,
    )
    if safe:
        response = transport.send(request)
        assert response.content == b"complete"
        assert len(sender.calls) == 2
        assert clock.sleeps == [1.0]
    else:
        with pytest.raises(TransportFailure) as caught:
            transport.send(request)
        assert caught.value.reason is TransportFailureReason.REPLAY_UNSAFE
        assert caught.value.attempts == 1
        assert caught.value.status_code == (503 if trigger == "status" else None)
        assert (
            caught.value.category
            is {
                "timeout": TransportFailureCategory.TIMEOUT,
                "status": TransportFailureCategory.HTTP_STATUS,
                "interruption": TransportFailureCategory.INCOMPLETE_RESPONSE,
            }[trigger]
        )
        assert len(sender.calls) == 1
        assert clock.sleeps == []
    for sent in sender.calls:
        assert sent.replay_safety is request.replay_safety
        assert sent.body == request.body
        if credentialed:
            assert sent.redirect_policy is RedirectPolicy.REFUSE
            assert sent.headers["Authorization"] == f"Bearer {_SECRET}"


def test_legacy_three_tuple_sender_keeps_retry_schedule_and_content_type():
    client, sender, clock = client_for([(b"busy", 429, "text/plain"), (b"complete", 200, "text/csv")])
    response = client.send(TransportRequest(HttpMethod.GET, _ORIGIN))
    assert (response.content, response.status_code, response.content_type) == (b"complete", 200, "text/csv")
    assert sender.starts == [0.0, 1.0]
    assert clock.sleeps == [1.0]


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("delay", [0, 1, 7, 60])
@pytest.mark.parametrize("form", ["delta", "date"])
def test_retry_after_valid_guidance_respects_backoff_and_boundary(status, delay, form):
    clock = PolicyClock()
    guidance = str(delay) if form == "delta" else format_datetime(clock.start + timedelta(seconds=delay), usegmt=True)
    client, sender, clock = client_for([SenderResponse(b"busy", status, None, guidance), (b"complete", 200, None)])
    response = client.send(TransportRequest(HttpMethod.GET, _ORIGIN))
    assert response.content == b"complete"
    assert sender.starts == [0.0, float(max(1, delay))]
    assert sum(clock.sleeps) == max(1, delay)


@pytest.mark.parametrize(
    "guidance",
    [
        "",
        "garbage",
        "-1",
        "+4",
        "1.5",
        "NaN",
        "inf",
        "１２",
        "1, 2",
        "Fri, 25 Sep 2026 12:00:07 GMT, 8",
        "Wed, 99 Sep 2026 12:00:00 GMT",
        "Fri, 25 Sep 2026 11:59:59 GMT",
    ],
)
def test_invalid_or_past_retry_after_uses_bounded_normal_backoff(guidance):
    client, sender, clock = client_for([SenderResponse(b"busy", 503, None, guidance), (b"complete", 200, None)])
    assert client.send(TransportRequest(HttpMethod.GET, _ORIGIN)).content == b"complete"
    assert sender.starts == [0.0, 1.0]
    assert clock.sleeps == [1.0]


@pytest.mark.parametrize(
    "guidance",
    [
        "61",
        "99999999999999999999999999999999999999",
        pytest.param("9" * 10000, id="ten-thousand-digits"),
        "Fri, 25 Sep 2026 12:01:01 GMT",
        "Fri, 31 Dec 9999 23:59:59 GMT",
    ],
)
@pytest.mark.parametrize("credentialed", [False, True])
def test_excessive_valid_retry_after_fails_without_sleep_or_early_retry(guidance, credentialed):
    client, sender, clock = client_for([SenderResponse(b"busy", 429, None, guidance)])
    transport = authenticated(client) if credentialed else client
    with pytest.raises(TransportFailure) as caught:
        transport.send(TransportRequest(HttpMethod.GET, _ORIGIN))
    error = caught.value
    assert error.reason is TransportFailureReason.RETRY_DELAY_EXCEEDED
    assert error.category is TransportFailureCategory.HTTP_STATUS
    assert error.status_code == 429
    assert error.attempts == 1
    assert len(sender.calls) == 1
    assert clock.sleeps == []
    assert guidance not in str(error)


@pytest.mark.parametrize(
    "trigger,category,status",
    [
        ("timeout", TransportFailureCategory.TIMEOUT, None),
        ("connection", TransportFailureCategory.CONNECTION, None),
        ("interruption", TransportFailureCategory.INCOMPLETE_RESPONSE, None),
        ("status", TransportFailureCategory.HTTP_STATUS, 503),
    ],
)
def test_auth_exhaustion_retains_category_and_identity_without_exception_secrets(trigger, category, status):
    action = {
        "timeout": requests.Timeout(_SECRET),
        "connection": requests.ConnectionError(_SECRET),
        "interruption": interrupted(_SECRET),
        "status": (b"busy", 503, None),
    }[trigger]
    client, sender, clock = client_for([action] * TRANSPORT_POLICY.max_attempts)
    request = TransportRequest(
        HttpMethod.POST,
        f"{_ORIGIN}/query",
        params={"station": "123"},
        body=b"read-only",
        replay_safety=ReplaySafety.SAFE,
    )
    with pytest.raises(TransportFailure) as caught:
        authenticated(client).send(request)
    error = caught.value
    assert error.request == request
    assert error.request.replay_safety is ReplaySafety.SAFE
    assert error.reason is TransportFailureReason.RETRY_EXHAUSTED
    assert error.category is category
    assert error.attempts == len(sender.calls) == TRANSPORT_POLICY.max_attempts
    assert error.status_code == status
    assert error.__cause__ is None
    assert error.__context__ is None
    assert _SECRET not in "".join(traceback.format_exception(error))
    assert _SECRET not in repr(error.request)
    assert clock.sleeps == [1.0, 2.0]


@pytest.mark.parametrize(
    "exception,category",
    [
        (requests.exceptions.SSLError, TransportFailureCategory.TLS),
        (requests.exceptions.InvalidURL, TransportFailureCategory.INVALID_REQUEST),
        (requests.exceptions.ContentDecodingError, TransportFailureCategory.DECODING),
    ],
)
def test_auth_terminal_failure_retains_category_without_raw_cause(exception, category):
    client, sender, clock = client_for([exception(_SECRET)])
    with pytest.raises(TransportFailure) as caught:
        authenticated(client).send(TransportRequest(HttpMethod.GET, _ORIGIN))
    error = caught.value
    assert error.reason is TransportFailureReason.TERMINAL_SENDER_FAILURE
    assert error.category is category
    assert error.attempts == len(sender.calls) == 1
    assert error.status_code is None
    assert error.__cause__ is None and error.__context__ is None
    assert _SECRET not in "".join(traceback.format_exception(error))
    assert clock.sleeps == []


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_authenticated_safe_post_still_refuses_redirects(status):
    client, sender, clock = client_for([(b"redirect", status, None)])
    with pytest.raises(TransportFailure) as caught:
        authenticated(client).send(TransportRequest(HttpMethod.POST, _ORIGIN, replay_safety=ReplaySafety.SAFE))
    assert caught.value.reason is TransportFailureReason.REDIRECT_REFUSED
    assert caught.value.status_code == status
    assert caught.value.attempts == 1
    assert len(sender.calls) == 1
    assert sender.calls[0].redirect_policy is RedirectPolicy.REFUSE
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "last,category,status",
    [
        (requests.Timeout("last timed out"), TransportFailureCategory.TIMEOUT, None),
        ((b"busy", 503, None), TransportFailureCategory.HTTP_STATUS, 503),
        (interrupted(), TransportFailureCategory.INCOMPLETE_RESPONSE, None),
    ],
)
def test_retry_after_and_mixed_failures_share_budget_and_final_diagnostics(last, category, status):
    client, sender, clock = client_for([SenderResponse(b"busy", 429, None, "7"), requests.ConnectionError(), last])
    with pytest.raises(TransportFailure) as caught:
        client.send(TransportRequest(HttpMethod.GET, _ORIGIN))
    assert caught.value.reason is TransportFailureReason.RETRY_EXHAUSTED
    assert caught.value.category is category
    assert caught.value.status_code == status
    assert caught.value.attempts == len(sender.calls) == 3
    assert sender.starts == [0.0, 7.0, 9.0]
    assert clock.sleeps == [7.0, 2.0]


def test_http_date_uses_current_wall_clock_after_prior_request():
    client, sender, clock = client_for(
        [
            (b"first", 200, None),
            SenderResponse(b"busy", 503, None, "Fri, 25 Sep 2026 12:00:07 GMT"),
            (b"second", 200, None),
        ]
    )
    request = TransportRequest(HttpMethod.GET, _ORIGIN)
    assert client.send(request).content == b"first"
    assert client.send(request).content == b"second"
    assert sender.starts == [0.0, 1.0, 7.0]
    assert clock.sleeps == [1.0, 6.0]


@pytest.mark.parametrize("status", [200, 404])
def test_retry_after_does_not_change_nonretryable_response_meaning(status):
    client, sender, clock = client_for([SenderResponse(b"source answer", status, None, "99999999999999999999")])
    response = client.send(TransportRequest(HttpMethod.GET, _ORIGIN))
    assert response.status_code == status
    assert response.content == b"source answer"
    assert len(sender.calls) == 1
    assert clock.sleeps == []

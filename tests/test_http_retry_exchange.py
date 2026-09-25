"""Credential exchange keeps safe retry diagnostics across both secret calls."""

import http.client
import traceback
from datetime import UTC, datetime

import pytest
import requests

from rivretrieve._internal.authentication import (
    AuthenticationFailureReason,
    CredentialExchangeError,
    CredentialExchangeTransport,
    ExchangeSpec,
)
from rivretrieve._internal.transport import (
    CredentialHeader,
    HttpClient,
    HttpMethod,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
)

_ORIGIN = "https://example.test"
_PASSWORD = "PRIVATE-EXCHANGE-PASSWORD"
_TOKEN = "PRIVATE-ACQUIRED-TOKEN"
_RAW = "PRIVATE-SENDER-DETAILS"


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def utcnow(self):
        return datetime(2026, 1, 1, tzinfo=UTC)

    def sleep(self, seconds):
        self.now += seconds


def make_transport(stage, failure):
    counts = {"exchange": 0, "data": 0}

    def sender(request, timeout_seconds):
        current = "exchange" if request.url.endswith("/token") else "data"
        counts[current] += 1
        if current == stage:
            secret = _PASSWORD if current == "exchange" else _TOKEN
            if failure == "timeout":
                raise requests.exceptions.ReadTimeout(f"{_RAW} {secret}")
            if failure == "incomplete":
                raise requests.exceptions.ChunkedEncodingError(http.client.IncompleteRead(secret.encode(), 20))
            if failure == "tls":
                raise requests.exceptions.SSLError(f"{_RAW} {secret}")
            if failure == "status":
                return b"unavailable", 503, "text/plain"
            if failure == "invalid_json":
                return b"not json", 200, "application/json"
        if current == "exchange":
            return f'{{"token":"{_TOKEN}"}}'.encode(), 200, "application/json"
        return b"complete data", 200, "text/plain"

    clock = Clock()
    transport = CredentialExchangeTransport(
        HttpClient(sender=sender, clock=clock, sleeper=clock.sleep),
        (CredentialHeader("Password", _PASSWORD, (_ORIGIN,)),),
        ExchangeSpec(f"{_ORIGIN}/token", ("token",), "Bearer", 3600, 3300, _ORIGIN),
        clock,
    )
    return transport, counts


def capture_failure(transport):
    try:
        transport.send(TransportRequest(HttpMethod.GET, f"{_ORIGIN}/data"))
    except CredentialExchangeError as error:
        return error
    pytest.fail("expected credential exchange failure")


@pytest.mark.parametrize("stage", ["exchange", "data"])
@pytest.mark.parametrize(
    ("failure", "category", "reason", "attempts", "status"),
    [
        ("timeout", TransportFailureCategory.TIMEOUT, TransportFailureReason.RETRY_EXHAUSTED, 3, None),
        ("incomplete", TransportFailureCategory.INCOMPLETE_RESPONSE, TransportFailureReason.RETRY_EXHAUSTED, 3, None),
        ("tls", TransportFailureCategory.TLS, TransportFailureReason.TERMINAL_SENDER_FAILURE, 1, None),
        ("status", TransportFailureCategory.HTTP_STATUS, TransportFailureReason.RETRY_EXHAUSTED, 3, 503),
    ],
)
def test_exchange_transport_retains_sanitized_failure_metadata(stage, failure, category, reason, attempts, status):
    transport, counts = make_transport(stage, failure)
    error = capture_failure(transport)
    assert error.reason is (
        AuthenticationFailureReason.EXCHANGE_SEND_FAILED
        if stage == "exchange"
        else AuthenticationFailureReason.DATA_SEND_FAILED
    )
    assert error.category is category
    assert error.transport_reason is reason
    assert error.attempts == attempts
    assert error.status_code == status
    assert error.request.url == f"{_ORIGIN}/data"
    assert not error.request.headers
    assert counts[stage] == attempts
    assert counts["data" if stage == "exchange" else "exchange"] == (0 if stage == "exchange" else 1)
    assert error.__cause__ is None
    assert error.__context__ is None
    rendered = "".join(traceback.TracebackException.from_exception(error, capture_locals=True).format())
    for secret in (_PASSWORD, _TOKEN, _RAW):
        assert secret not in rendered
        assert secret not in repr(vars(error))


def test_exchange_parse_failure_does_not_invent_transport_failure_metadata():
    transport, counts = make_transport("exchange", "invalid_json")
    error = capture_failure(transport)
    assert error.reason is AuthenticationFailureReason.RESPONSE_JSON_INVALID
    assert error.category is None
    assert error.attempts is None
    assert error.transport_reason is None
    assert error.status_code == 200
    assert counts == {"exchange": 1, "data": 0}

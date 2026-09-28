"""Actual HTTP attempts retain independent, byte-free evidence."""

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import requests

from rivretrieve._internal.transport import (
    AuthenticatedTransport,
    CredentialHeader,
    HttpClient,
    HttpMethod,
    SenderResponse,
    TransportAttempt,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
)


class AttemptClock:
    def __init__(self):
        self.instant = datetime(2026, 1, 1, tzinfo=UTC)

    def monotonic(self):
        return 0.0

    def utcnow(self):
        return self.instant


def client_for(actions):
    clock = AttemptClock()
    outcomes = iter(actions)
    instants = []

    def sender(request, timeout_seconds):
        clock.instant += timedelta(seconds=7)
        instants.append(clock.instant)
        action = next(outcomes)
        if isinstance(action, Exception):
            raise action
        return action

    return HttpClient(sender=sender, clock=clock, sleeper=lambda _: None), instants


def request(method=HttpMethod.GET):
    return TransportRequest(method, "https://source.example/data", {"station": "123"})


def assert_trace_metadata(traces, instants):
    assert [trace.retrieved_at for trace in traces] == instants
    assert len({trace.attempt_id for trace in traces}) == len(traces)
    assert all(UUID(trace.attempt_id).version == 4 for trace in traces)
    assert all(trace.url == request().url for trace in traces)
    assert all(trace.request_parameters == {"station": "123"} for trace in traces)


def test_retry_response_preserves_each_actual_status_and_time():
    client, instants = client_for([(b"temporary", 503, "text/plain"), (b"ok", 200, "application/json")])
    result = client.send(request())
    assert result.attempts == 2
    assert [trace.status_code for trace in result.attempt_traces] == [503, 200]
    assert [trace.content_type for trace in result.attempt_traces] == ["text/plain", "application/json"]
    assert result.attempt_traces[0].failure_category is TransportFailureCategory.HTTP_STATUS
    assert result.attempt_traces[1].failure_category is None
    assert result.retrieved_at == result.attempt_traces[-1].retrieved_at
    assert_trace_metadata(result.attempt_traces, instants)


@pytest.mark.parametrize("action", [(b"unavailable", 503, None), TimeoutError("not retained")])
def test_exhausted_retries_keep_all_actual_attempts(action):
    client, instants = client_for([action] * 3)
    with pytest.raises(TransportFailure) as caught:
        client.send(request())
    failure = caught.value
    assert failure.attempts == len(failure.attempt_traces) == 3
    assert failure.reason is TransportFailureReason.RETRY_EXHAUSTED
    if failure.response is not None:
        assert failure.response.attempt_traces == failure.attempt_traces
    else:
        assert all(trace.status_code is None for trace in failure.attempt_traces)
    assert_trace_metadata(failure.attempt_traces, instants)


def test_sender_exception_then_success_has_no_invented_http_status():
    client, instants = client_for([ConnectionError("private exception message"), (b"ok", 200, None)])
    result = client.send(request())
    failed, success = result.attempt_traces
    assert failed.status_code is None
    assert failed.content_type is None
    assert failed.failure_category is TransportFailureCategory.CONNECTION
    assert success.status_code == 200
    assert "private exception message" not in repr(result.attempt_traces)
    assert_trace_metadata(result.attempt_traces, instants)


@pytest.mark.parametrize(
    ("actions", "method", "reason"),
    [
        (
            [(b"retry", 503, None), requests.exceptions.SSLError("secret")],
            HttpMethod.GET,
            TransportFailureReason.TERMINAL_SENDER_FAILURE,
        ),
        ([(b"retry", 503, None)], HttpMethod.POST, TransportFailureReason.REPLAY_UNSAFE),
        ([SenderResponse(b"retry", 503, None, "1000")], HttpMethod.GET, TransportFailureReason.RETRY_DELAY_EXCEEDED),
    ],
)
def test_terminal_failures_preserve_previous_attempts(actions, method, reason):
    client, instants = client_for(actions)
    with pytest.raises(TransportFailure) as caught:
        client.send(request(method))
    assert caught.value.reason is reason
    assert len(caught.value.attempt_traces) == len(actions)
    assert_trace_metadata(caught.value.attempt_traces, instants)


def test_attempt_is_frozen_and_copies_parameter_mapping():
    params = {"station": "123"}
    trace = TransportAttempt("id", "https://source.example", params, datetime(2026, 1, 1, tzinfo=UTC))
    params["station"] = "changed"
    assert trace.request_parameters == {"station": "123"}
    with pytest.raises(FrozenInstanceError):
        trace.status_code = 200
    with pytest.raises(TypeError):
        trace.request_parameters["station"] = "changed"
    assert {field.name for field in fields(trace)} == {
        "attempt_id",
        "url",
        "request_parameters",
        "retrieved_at",
        "status_code",
        "content_type",
        "failure_category",
    }


@pytest.mark.parametrize("terminal", [False, True])
def test_authenticated_wrapper_keeps_attempts_without_credentials(terminal):
    actions = [
        (b"retry", 503, None),
        requests.exceptions.SSLError("SENTINEL-secret") if terminal else (b"ok", 200, None),
    ]
    client, instants = client_for(actions)
    wrapped = AuthenticatedTransport(
        client, (CredentialHeader("Authorization", "Bearer SENTINEL-secret", ("https://source.example",)),)
    )
    if terminal:
        with pytest.raises(TransportFailure) as caught:
            wrapped.send(request())
        traces = caught.value.attempt_traces
    else:
        traces = wrapped.send(request()).attempt_traces
    assert_trace_metadata(traces, instants)
    assert "SENTINEL-secret" not in repr(traces)


def test_authenticated_wrapper_refuses_secret_in_intermediate_trace():
    client, _ = client_for([(b"retry", 503, "SENTINEL-secret"), (b"ok", 200, None)])
    wrapped = AuthenticatedTransport(
        client, (CredentialHeader("Authorization", "Bearer SENTINEL-secret", ("https://source.example",)),)
    )
    with pytest.raises(TransportFailure) as caught:
        wrapped.send(request())
    assert caught.value.reason is TransportFailureReason.RETAINED_METADATA_UNSAFE
    assert caught.value.attempt_traces == ()


@pytest.mark.parametrize("origin", ["https://source.example", "https://other.example"])
def test_authenticated_wrapper_preserves_exhausted_response_traces(origin):
    client, instants = client_for([(b"retry", 503, "text/plain")] * 3)
    wrapped = AuthenticatedTransport(client, (CredentialHeader("Authorization", "Bearer SENTINEL-secret", (origin,)),))
    with pytest.raises(TransportFailure) as caught:
        wrapped.send(request())
    assert caught.value.response is not None
    assert caught.value.attempt_traces == caught.value.response.attempt_traces
    assert_trace_metadata(caught.value.attempt_traces, instants)


def test_authenticated_redirect_failure_preserves_response_trace():
    client, instants = client_for([(b"redirect", 302, "text/plain")])
    wrapped = AuthenticatedTransport(
        client, (CredentialHeader("Authorization", "Bearer SENTINEL-secret", ("https://source.example",)),)
    )
    with pytest.raises(TransportFailure) as caught:
        wrapped.send(request())
    assert caught.value.reason is TransportFailureReason.REDIRECT_REFUSED
    assert caught.value.attempt_traces[0].status_code == 302
    assert_trace_metadata(caught.value.attempt_traces, instants)

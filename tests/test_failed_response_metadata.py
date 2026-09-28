"""Received HTTP failures retain evidence; sender failures do not invent it."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import requests

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.recordings import read_recording
from rivretrieve._internal.transport import (
    AuthenticatedTransport,
    CredentialHeader,
    ExecutedRequestEvidence,
    HttpClient,
    HttpMethod,
    SenderResponse,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

NOW = datetime(2026, 9, 27, tzinfo=UTC)
SECRET = "private-token-value"


class FixedClock:
    def monotonic(self):
        return 0.0

    def utcnow(self):
        return NOW


def client(sender):
    return HttpClient(sender=sender, clock=FixedClock(), sleeper=lambda _: None)


@pytest.mark.parametrize("delay,attempts,reason", [(None, 3, "retry_exhausted"), ("999", 1, "retry_delay_exceeded")])
def test_public_monthly_failure_retains_received_metadata(monkeypatch, delay, attempts, reason):
    recording = read_recording(Path(__file__).parent / "test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json")
    sent = []

    def sender(request, timeout):
        month = request.url.rsplit("/", 1)[-1]
        sent.append(month)
        return (
            SenderResponse(recording.content, 200, "application/json")
            if month == "2023-06"
            else SenderResponse(b"unavailable", 500, "text/plain", delay)
        )

    monkeypatch.setattr(discovery, "HttpClient", lambda: client(sender))
    selection = rr.find(
        provider="lt_lhmt", station="anyksciu-vms", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2023-05-03", end="2023-06-28", cache="bypass", receipts=True, on_issue="ignore")
    assert result.data.height == 28
    assert sent == ["2023-05"] * attempts + ["2023-06"]
    calls = result.provenance.calls_made
    assert len(calls) == attempts + 1
    failed_calls, success = calls[:-1], calls[-1]
    assert len({call["call_id"] for call in calls}) == attempts + 1
    assert len({call["acquisition_id"] for call in failed_calls}) == 1
    assert success["acquisition_id"] != failed_calls[0]["acquisition_id"]
    for ordinal, failed in enumerate(failed_calls, 1):
        assert failed["attempt"] == ordinal
        assert failed["retrieved_at"] == NOW
        assert failed["content_type"] == "text/plain"
        assert failed["status_code"] == 500
        assert failed["failure_reason"] == failed["failure_category"] == "http_status"
        assert failed["acquisition_failure_reason"] == reason
        assert failed["request_parameters"] == {}
        assert failed["window"] == {
            "start": "2023-05-01T00:00:00",
            "end": "2023-05-31T23:59:59.999999",
            "axis": "native",
        }
        assert failed["url"].endswith("/2023-05")
        assert set(map(tuple, failed["station_products"])) == {("anyksciu-vms", "discharge_daily_mean")}
    outcomes = [item for item in result.outcomes if item.status.value == "failed"]
    assert len(outcomes) == 1
    assert outcomes[0].calls == tuple(call["call_id"] for call in failed_calls)
    assert outcomes[0].station_id == "anyksciu-vms"
    assert outcomes[0].product_id == "discharge_daily_mean"
    assert outcomes[0].reason
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.details["failure_reason"] == reason
    assert issue.details["failure_category"] == "http_status"
    assert issue.details["attempts"] == attempts
    assert issue.details["status_code"] == 500
    assert issue.details["station_id"] == "anyksciu-vms"
    assert issue.details["product_id"] == "discharge_daily_mean"
    assert issue.details["request_url"] == failed_calls[0]["url"]
    assert issue.details["window"] == failed_calls[0]["window"]
    assert success["retrieved_at"] == NOW
    assert success["status_code"] == 200
    assert success["url"].endswith("/2023-06")
    assert len(result.receipts.entries) == 1
    assert result.receipts.entries[0].content == recording.content


@pytest.mark.parametrize(
    "method,delay,reason,attempts",
    [
        (HttpMethod.GET, None, "retry_exhausted", 3),
        (HttpMethod.GET, "999", "retry_delay_exceeded", 1),
        (HttpMethod.POST, None, "replay_unsafe", 1),
    ],
)
@pytest.mark.parametrize("authenticated", [False, True])
def test_http_failure_keeps_exact_response(method, delay, reason, attempts, authenticated):
    request = TransportRequest(method, "https://example.test/data", {"month": "May"})
    transport = client(lambda *_: SenderResponse(b"unavailable", 500, "text/plain", delay))
    names = ("Authorization",) if authenticated else ()
    if authenticated:
        transport = AuthenticatedTransport(
            transport, (CredentialHeader("Authorization", f"Bearer {SECRET}", ("https://example.test",)),)
        )
    with pytest.raises(TransportFailure) as caught:
        transport.send(request)
    error = caught.value
    assert error.reason == reason
    assert error.category is TransportFailureCategory.HTTP_STATUS
    assert error.attempts == attempts
    assert error.response == TransportResponse(
        b"unavailable",
        500,
        NOW,
        "text/plain",
        request.url,
        request.params,
        applied_credential_header_names=names,
        attempts=attempts,
    )
    assert error.response.attempts == attempts
    assert error.response.executed_request == ExecutedRequestEvidence({"User-Agent": "RivRetrieve"}, names)
    assert SECRET not in repr(error.request)
    assert SECRET not in repr(error.response)


@pytest.mark.parametrize("applicable", [True, False])
@pytest.mark.parametrize("unsafe", [None, "content", "content_type", "url", "request_parameters", "executed_request"])
def test_authenticated_failed_response_is_retained_only_when_safe(applicable, unsafe):
    request = TransportRequest(HttpMethod.GET, "https://example.test/data")
    response = TransportResponse(b"unavailable", 500, NOW, "text/plain", request.url, {})
    if unsafe:
        values = {
            "content": SECRET.encode(),
            "content_type": SECRET,
            "url": f"https://example.test/{SECRET}",
            "request_parameters": {"token": SECRET},
            "executed_request": ExecutedRequestEvidence({"Accept": SECRET}),
        }
        response = replace(response, **{unsafe: values[unsafe]})

    class Failed:
        def send(self, request):
            raise TransportFailure(
                request,
                TransportFailureReason.RETRY_EXHAUSTED,
                3,
                status_code=500,
                category=TransportFailureCategory.HTTP_STATUS,
                response=response,
            )

    transport = AuthenticatedTransport(
        Failed(),
        (
            CredentialHeader(
                "Authorization", f"Bearer {SECRET}", ("https://example.test" if applicable else "https://other.test",)
            ),
        ),
    )
    with pytest.raises(TransportFailure) as caught:
        transport.send(request)
    error = caught.value
    assert error.reason == ("retained_metadata_unsafe" if unsafe else "retry_exhausted")
    assert error.response is None if unsafe else error.response is not None
    assert SECRET not in repr(error.request)
    assert SECRET not in repr(error.response)
    assert error.__context__ is None
    if not unsafe:
        assert error.response.content == response.content
        assert error.response.retrieved_at == NOW
        assert error.category is TransportFailureCategory.HTTP_STATUS


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("exception", [requests.Timeout, requests.exceptions.InvalidURL, FatalContractError])
def test_sender_exception_has_no_response(authenticated, exception):
    def sender(*_):
        raise exception("sender failed")

    transport = client(sender)
    if authenticated:
        transport = AuthenticatedTransport(
            transport, (CredentialHeader("Authorization", f"Bearer {SECRET}", ("https://example.test",)),)
        )
    with pytest.raises(FatalContractError if exception is FatalContractError else TransportFailure) as caught:
        transport.send(TransportRequest(HttpMethod.GET, "https://example.test/data"))
    if exception is not FatalContractError:
        assert caught.value.response is None
        assert caught.value.status_code is None

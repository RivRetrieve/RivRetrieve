"""Exercise the unmodified Requests sender against deterministic loopback faults."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from socketserver import BaseRequestHandler, TCPServer
from threading import Thread

import pytest
import requests

from rivretrieve._internal.transport import (
    HttpClient,
    HttpMethod,
    ReplaySafety,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
)


@dataclass
class VirtualClock:
    now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def utcnow(self) -> datetime:
        return datetime(2026, 9, 25, tzinfo=UTC) + timedelta(seconds=self.now)

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.now += seconds


@dataclass
class ScriptedSource:
    url: str
    clock: VirtualClock
    calls: list[tuple[str, bytes, float]]

    def client(self) -> HttpClient:
        # Deliberately do not inject a sender: Requests must parse the wire bytes.
        return HttpClient(clock=self.clock, sleeper=self.clock.sleep)


@contextmanager
def source(responses: list[bytes]) -> Iterator[ScriptedSource]:
    clock = VirtualClock()
    calls: list[tuple[str, bytes, float]] = []

    class Exchange(BaseRequestHandler):
        def handle(self) -> None:
            self.request.settimeout(2)
            stream = self.request.makefile("rb")
            with stream:
                line = stream.readline().decode("ascii")
                headers: dict[str, str] = {}
                while (header := stream.readline()) not in (b"\r\n", b""):
                    name, value = header.decode("ascii").split(":", 1)
                    headers[name.lower()] = value.strip()
                body = stream.read(int(headers.get("content-length", "0")))
            index = len(calls)
            calls.append((line.split()[0], body, clock.now))
            # An unexpected retry gets a complete response and fails call-count assertions.
            response = responses[index] if index < len(responses) else complete(b"unexpected retry")
            self.request.sendall(response)

    with TCPServer(("127.0.0.1", 0), Exchange) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield ScriptedSource(f"http://127.0.0.1:{server.server_address[1]}/data", clock, calls)
        finally:
            server.shutdown()
            thread.join(timeout=2)
            assert not thread.is_alive()


def complete(body: bytes = b"complete source bytes", status: int = 200, headers: bytes = b"") -> bytes:
    return (
        f"HTTP/1.1 {status} Result\r\nContent-Length: {len(body)}\r\n".encode()
        + b"Connection: close\r\n"
        + headers
        + b"\r\n"
        + body
    )


FIXED_INTERRUPTION = b"HTTP/1.1 200 OK\r\nContent-Length: 20\r\nConnection: close\r\n\r\nab"
CHUNKED_INTERRUPTION = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n5\r\nab"
BETWEEN_CHUNKS_INTERRUPTION = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n2\r\nab\r\n"
INTERRUPTIONS = [FIXED_INTERRUPTION, CHUNKED_INTERRUPTION, BETWEEN_CHUNKS_INTERRUPTION]


@pytest.fixture(autouse=True)
def loopback_bypasses_environment_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")


@pytest.mark.parametrize("interruption", INTERRUPTIONS, ids=["fixed-length", "chunked", "between-chunks"])
def test_interrupted_response_restarts_and_returns_only_complete_bytes(interruption: bytes) -> None:
    with source([interruption, complete()]) as server:
        response = server.client().send(TransportRequest(HttpMethod.GET, server.url))
        assert response.content == b"complete source bytes"
        assert response.status_code == 200
        assert server.calls == [("GET", b"", 0.0), ("GET", b"", 1.0)]
        assert server.clock.sleeps == [1.0]


@pytest.mark.parametrize("interruption", INTERRUPTIONS, ids=["fixed-length", "chunked", "between-chunks"])
def test_repeated_interruption_exhausts_shared_budget(interruption: bytes) -> None:
    with source([interruption] * 3) as server:
        request = TransportRequest(HttpMethod.GET, server.url)
        with pytest.raises(TransportFailure) as caught:
            server.client().send(request)
        failure = caught.value
        assert failure.reason is TransportFailureReason.RETRY_EXHAUSTED
        assert failure.attempts == 3
        assert failure.request is request
        assert failure.category is TransportFailureCategory.INCOMPLETE_RESPONSE
        assert failure.status_code is None
        assert isinstance(failure.__cause__, requests.exceptions.ChunkedEncodingError)
        assert [call[2] for call in server.calls] == [0.0, 1.0, 3.0]
        assert server.clock.sleeps == [1.0, 2.0]


@pytest.mark.parametrize("last", [FIXED_INTERRUPTION, complete(b"busy", 503)], ids=["interruption", "status"])
def test_mixed_status_and_interruption_use_one_budget(last: bytes) -> None:
    with source([CHUNKED_INTERRUPTION, complete(b"busy", 503), last]) as server:
        with pytest.raises(TransportFailure) as caught:
            server.client().send(TransportRequest(HttpMethod.GET, server.url))
        failure = caught.value
        assert failure.reason is TransportFailureReason.RETRY_EXHAUSTED
        assert failure.attempts == 3
        assert failure.status_code == (None if last == FIXED_INTERRUPTION else 503)
        assert [call[2] for call in server.calls] == [0.0, 1.0, 3.0]
        assert server.clock.sleeps == [1.0, 2.0]


@pytest.mark.parametrize("method", [HttpMethod.GET, HttpMethod.HEAD])
def test_safe_methods_retry_status_without_inventing_head_body(method: HttpMethod) -> None:
    with source([complete(b"", 503), complete(b"")]) as server:
        response = server.client().send(TransportRequest(method, server.url))
        assert response.status_code == 200
        assert response.content == b""
        assert server.calls == [(method.value, b"", 0.0), (method.value, b"", 1.0)]


def test_complete_404_retains_response_and_does_not_retry() -> None:
    with source([complete(b"not published", 404)]) as server:
        response = server.client().send(TransportRequest(HttpMethod.GET, server.url))
        assert response.status_code == 404
        assert response.content == b"not published"
        assert len(server.calls) == 1
        assert server.clock.sleeps == []


@pytest.mark.parametrize(
    ("response", "cause"),
    [
        (complete(b"not gzip", headers=b"Content-Encoding: gzip\r\n"), requests.exceptions.ContentDecodingError),
        (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\nNOT-HEX\r\nab\r\n",
            requests.exceptions.ChunkedEncodingError,
        ),
    ],
    ids=["invalid-gzip", "invalid-chunk-framing"],
)
def test_permanent_wire_corruption_is_not_retried(response: bytes, cause: type[Exception]) -> None:
    with source([response]) as server:
        with pytest.raises(TransportFailure) as caught:
            server.client().send(TransportRequest(HttpMethod.GET, server.url))
        assert caught.value.reason is TransportFailureReason.TERMINAL_SENDER_FAILURE
        assert caught.value.attempts == 1
        assert isinstance(caught.value.__cause__, cause)
        assert len(server.calls) == 1
        assert server.clock.sleeps == []


def test_complete_malformed_source_payload_is_not_reinterpreted_by_transport() -> None:
    with source([complete(b"{invalid json", headers=b"Content-Type: application/json\r\n")]) as server:
        response = server.client().send(TransportRequest(HttpMethod.GET, server.url))
        assert response.content == b"{invalid json"
        assert response.content_type == "application/json"
        assert len(server.calls) == 1


@pytest.mark.parametrize("url", ["unsupported://127.0.0.1/data", "http://[invalid"])
def test_invalid_request_is_terminal_before_network_access(url: str) -> None:
    clock = VirtualClock()
    with pytest.raises(TransportFailure) as caught:
        HttpClient(clock=clock, sleeper=clock.sleep).send(TransportRequest(HttpMethod.GET, url))
    assert caught.value.reason is TransportFailureReason.TERMINAL_SENDER_FAILURE
    assert caught.value.attempts == 1
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "trigger", [*INTERRUPTIONS, complete(b"busy", 503)], ids=["fixed", "chunked", "between-chunks", "status"]
)
@pytest.mark.parametrize("safety", [ReplaySafety.METHOD_DEFAULT, ReplaySafety.SAFE])
def test_post_replay_requires_explicit_semantic_safety(trigger: bytes, safety: ReplaySafety) -> None:
    with source([trigger, complete()]) as server:
        request = TransportRequest(HttpMethod.POST, server.url, body=b"read-only query", replay_safety=safety)
        if safety is ReplaySafety.SAFE:
            response = server.client().send(request)
            assert response.content == b"complete source bytes"
            assert server.calls == [("POST", b"read-only query", 0.0), ("POST", b"read-only query", 1.0)]
        else:
            with pytest.raises(TransportFailure) as caught:
                server.client().send(request)
            assert caught.value.reason is TransportFailureReason.REPLAY_UNSAFE
            assert caught.value.attempts == 1
            expected_category = (
                TransportFailureCategory.INCOMPLETE_RESPONSE
                if trigger in INTERRUPTIONS
                else TransportFailureCategory.HTTP_STATUS
            )
            assert caught.value.category is expected_category
            assert server.calls == [("POST", b"read-only query", 0.0)]
            assert server.clock.sleeps == []


@pytest.mark.parametrize(
    ("guidance", "delay"),
    [
        (b"5", 5.0),
        (b"Fri, 25 Sep 2026 00:00:07 GMT", 7.0),
        (b"0", 1.0),
        (b"-1", 1.0),
        (b"nonsense", 1.0),
        (b"1.5", 1.0),
        (b"Thu, 24 Sep 2026 23:59:59 GMT", 1.0),
    ],
)
@pytest.mark.parametrize("status", [429, 503])
def test_retry_after_from_wire_respects_guidance_and_pacing(guidance: bytes, delay: float, status: int) -> None:
    with source([complete(b"busy", status, b"Retry-After: " + guidance + b"\r\n"), complete()]) as server:
        response = server.client().send(TransportRequest(HttpMethod.GET, server.url))
        assert response.content == b"complete source bytes"
        assert [call[2] for call in server.calls] == [0.0, delay]
        assert server.clock.sleeps == [delay]


@pytest.mark.parametrize("guidance", [b"61", b"9" * 5000, b"Fri, 25 Sep 2026 01:00:00 GMT"])
def test_retry_after_exceeding_delay_budget_does_not_retry_early(guidance: bytes) -> None:
    with source([complete(b"busy", 503, b"Retry-After: " + guidance + b"\r\n")]) as server:
        with pytest.raises(TransportFailure) as caught:
            server.client().send(TransportRequest(HttpMethod.GET, server.url))
        assert caught.value.reason is TransportFailureReason.RETRY_DELAY_EXCEEDED
        assert caught.value.category is TransportFailureCategory.HTTP_STATUS
        assert caught.value.status_code == 503
        assert caught.value.attempts == 1
        assert len(server.calls) == 1
        assert server.clock.sleeps == []


def test_successful_requests_share_start_pacing_after_recovery() -> None:
    with source([FIXED_INTERRUPTION, complete(b"first"), complete(b"second")]) as server:
        client = server.client()
        request = TransportRequest(HttpMethod.GET, server.url)
        assert client.send(request).content == b"first"
        assert client.send(request).content == b"second"
        assert [call[2] for call in server.calls] == [0.0, 1.0, 2.0]
        assert server.clock.sleeps == [1.0, 1.0]


@pytest.mark.parametrize("method", [HttpMethod.GET, HttpMethod.HEAD])
def test_disconnect_before_response_retries_safe_methods(method: HttpMethod) -> None:
    with source([b"", complete(b"")]) as server:
        response = server.client().send(TransportRequest(method, server.url))
        assert response.status_code == 200
        assert response.content == b""
        assert server.calls == [(method.value, b"", 0.0), (method.value, b"", 1.0)]


def test_invalid_http_status_line_is_terminal_protocol_failure() -> None:
    with source([b"NOT HTTP\r\n\r\n"]) as server:
        with pytest.raises(TransportFailure) as caught:
            server.client().send(TransportRequest(HttpMethod.GET, server.url))
        assert caught.value.reason is TransportFailureReason.TERMINAL_SENDER_FAILURE
        assert caught.value.category is TransportFailureCategory.PROTOCOL
        assert caught.value.attempts == 1
        assert len(server.calls) == 1
        assert server.clock.sleeps == []


@pytest.mark.parametrize("status", [307, 308])
@pytest.mark.parametrize("safety", [ReplaySafety.METHOD_DEFAULT, ReplaySafety.SAFE])
def test_post_redirect_does_not_replay_without_semantic_safety(status: int, safety: ReplaySafety) -> None:
    with source([complete(b"", status, b"Location: /redirected\r\n"), complete()]) as server:
        request = TransportRequest(HttpMethod.POST, server.url, body=b"source operation", replay_safety=safety)
        response = server.client().send(request)
        if safety is ReplaySafety.SAFE:
            assert response.status_code == 200
            assert response.content == b"complete source bytes"
            assert [(method, body) for method, body, _ in server.calls] == [("POST", b"source operation")] * 2
        else:
            assert response.status_code == status
            assert response.content == b""
            assert server.calls == [("POST", b"source operation", 0.0)]
        assert server.clock.sleeps == []

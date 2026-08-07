"""HTTP transport = execute : TransportRequest × TransportPolicy → TransportResponse | TransportFailure"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

import requests


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"


RequestParameter = str | int | float | None


@dataclass(frozen=True)
class TransportRequest:
    method: HttpMethod
    url: str
    params: Mapping[str, RequestParameter] | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | str | None = None


@dataclass(frozen=True)
class TransportResponse:
    content: bytes
    status_code: int
    retrieved_at: datetime
    content_type: str | None
    url: str
    request_parameters: Mapping[str, RequestParameter]

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_parameters", MappingProxyType(dict(self.request_parameters)))


class TransportFailureReason(StrEnum):
    TERMINAL_SENDER_FAILURE = "terminal_sender_failure"
    RETRY_EXHAUSTED = "retry_exhausted"


class TransportFailure(Exception):  # noqa: N818 - exact transport-neutral contract name
    request: TransportRequest
    reason: TransportFailureReason
    attempts: int
    status_code: int | None

    def __init__(
        self,
        request: TransportRequest,
        reason: TransportFailureReason,
        attempts: int,
        *,
        status_code: int | None = None,
    ) -> None:
        self.request = request
        self.reason = reason
        self.attempts = attempts
        self.status_code = status_code
        super().__init__(f"HTTP transport failed after {attempts} attempt(s): {reason}")


class Sender(Protocol):
    def __call__(
        self,
        request: TransportRequest,
        timeout_seconds: float,
    ) -> tuple[bytes, int, str | None]: ...


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def utcnow(self) -> datetime: ...


Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class TransportPolicy:
    timeout_seconds: float
    user_agent: str
    retryable_status_codes: frozenset[int]
    backoff_seconds: tuple[float, ...]
    minimum_interval_seconds: float

    @property
    def max_attempts(self) -> int:
        return len(self.backoff_seconds) + 1


TRANSPORT_POLICY = TransportPolicy(
    timeout_seconds=60.0,
    user_agent="RivRetrieve",
    retryable_status_codes=frozenset({408, 429, 500, 502, 503, 504}),
    backoff_seconds=(1.0, 2.0),
    minimum_interval_seconds=1.0,
)


class _SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def utcnow(self) -> datetime:
        return datetime.now(UTC)


def _send_with_requests(request: TransportRequest, timeout_seconds: float) -> tuple[bytes, int, str | None]:
    params = dict(request.params) if request.params is not None else None
    headers = dict(request.headers)
    if request.method is HttpMethod.GET:
        response = requests.get(
            request.url,
            params=params,
            headers=headers,
            data=request.body,
            timeout=timeout_seconds,
        )
    else:
        response = requests.post(
            request.url,
            params=params,
            headers=headers,
            data=request.body,
            timeout=timeout_seconds,
        )
    return response.content, response.status_code, response.headers.get("Content-Type")


def _is_retryable_sender_exception(exception: BaseException) -> bool:
    return isinstance(exception, (requests.Timeout, requests.ConnectionError, TimeoutError, ConnectionError))


class HttpClient:
    def __init__(
        self,
        *,
        sender: Sender = _send_with_requests,
        clock: Clock | None = None,
        sleeper: Sleeper = time.sleep,
    ) -> None:
        self._sender = sender
        self._clock = clock if clock is not None else _SystemClock()
        self._sleeper = sleeper
        self._last_attempt_started_at: float | None = None

    def send(self, request: TransportRequest) -> TransportResponse:
        prepared_request = self._with_policy_headers(request)
        for attempt in range(1, TRANSPORT_POLICY.max_attempts + 1):
            if attempt > 1:
                self._sleeper(TRANSPORT_POLICY.backoff_seconds[attempt - 2])
            self._wait_for_rate_limit()

            try:
                content, status_code, content_type = self._sender(prepared_request, TRANSPORT_POLICY.timeout_seconds)
            except (requests.RequestException, TimeoutError, ConnectionError) as exception:
                if not _is_retryable_sender_exception(exception):
                    raise TransportFailure(
                        request,
                        TransportFailureReason.TERMINAL_SENDER_FAILURE,
                        attempt,
                    ) from exception
                if attempt == TRANSPORT_POLICY.max_attempts:
                    raise TransportFailure(
                        request,
                        TransportFailureReason.RETRY_EXHAUSTED,
                        attempt,
                    ) from exception
                continue

            if status_code not in TRANSPORT_POLICY.retryable_status_codes:
                return TransportResponse(
                    content=content,
                    status_code=status_code,
                    retrieved_at=self._clock.utcnow(),
                    content_type=content_type,
                    url=request.url,
                    request_parameters={} if request.params is None else request.params,
                )
            if attempt == TRANSPORT_POLICY.max_attempts:
                raise TransportFailure(
                    request,
                    TransportFailureReason.RETRY_EXHAUSTED,
                    attempt,
                    status_code=status_code,
                )

        raise AssertionError("retry loop exhausted without a terminal result")

    @staticmethod
    def _with_policy_headers(request: TransportRequest) -> TransportRequest:
        headers = dict(request.headers)
        if any(name.lower() == "user-agent" for name in headers):
            raise ValueError("Source request must not provide a User-Agent header")
        headers["User-Agent"] = TRANSPORT_POLICY.user_agent
        return TransportRequest(request.method, request.url, request.params, headers, request.body)

    def _wait_for_rate_limit(self) -> None:
        now = self._clock.monotonic()
        if self._last_attempt_started_at is not None:
            elapsed = now - self._last_attempt_started_at
            remaining = TRANSPORT_POLICY.minimum_interval_seconds - elapsed
            if remaining > 0:
                self._sleeper(remaining)
                now = self._clock.monotonic()
        self._last_attempt_started_at = now

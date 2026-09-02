"""HTTP transport = execute : TransportRequest × TransportPolicy → TransportResponse | TransportFailure"""

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

import requests


class HttpMethod(StrEnum):
    GET = "GET"
    HEAD = "HEAD"
    POST = "POST"


RequestParameter = str | int | float | None


class RedirectPolicy(StrEnum):
    METHOD_DEFAULT = "method_default"
    REFUSE = "refuse"


@dataclass(frozen=True)
class TransportRequest:
    method: HttpMethod
    url: str
    params: Mapping[str, RequestParameter] | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | str | None = None
    redirect_policy: RedirectPolicy = RedirectPolicy.METHOD_DEFAULT


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
    REDIRECT_REFUSED = "redirect_refused"


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


class Transport(Protocol):
    """Execute one fully rendered source request."""

    def send(self, request: TransportRequest) -> TransportResponse: ...


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
            allow_redirects=request.redirect_policy is not RedirectPolicy.REFUSE,
        )
    elif request.method is HttpMethod.HEAD:
        response = requests.head(
            request.url,
            params=params,
            headers=headers,
            timeout=timeout_seconds,
            allow_redirects=False,
        )
    else:
        response = requests.post(
            request.url,
            params=params,
            headers=headers,
            data=request.body,
            timeout=timeout_seconds,
            allow_redirects=request.redirect_policy is not RedirectPolicy.REFUSE,
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
        return TransportRequest(
            request.method,
            request.url,
            request.params,
            headers,
            request.body,
            request.redirect_policy,
        )

    def _wait_for_rate_limit(self) -> None:
        now = self._clock.monotonic()
        if self._last_attempt_started_at is not None:
            elapsed = now - self._last_attempt_started_at
            remaining = TRANSPORT_POLICY.minimum_interval_seconds - elapsed
            if remaining > 0:
                self._sleeper(remaining)
                now = self._clock.monotonic()
        self._last_attempt_started_at = now


@runtime_checkable
class AuthenticationCapability(Protocol):
    """Report whether credentials are scoped to one exact request origin."""

    def can_authenticate(self, url: str) -> bool: ...


@dataclass(frozen=True, slots=True, repr=False)
class CredentialHeader:
    """One redacted credential header scoped to exact HTTP origins."""

    name: str
    _value: str
    origins: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", self.name) is None:
            raise TypeError("credential header name must use the HTTP field-name token grammar")
        if not isinstance(self._value, str) or re.fullmatch(r"[\x20-\x7e]+", self._value) is None:
            raise TypeError("credential header value must contain only visible ASCII or spaces")
        if not isinstance(self.origins, tuple) or not self.origins:
            raise TypeError("credential origins must be a non-empty tuple")
        normalized = tuple(_credential_origin(value) for value in self.origins)
        if len(normalized) != len(set(normalized)):
            raise ValueError("credential origins must be unique")
        object.__setattr__(self, "origins", normalized)

    def __repr__(self) -> str:
        return f"CredentialHeader(name={self.name!r}, value=[REDACTED], origins={self.origins!r})"


@dataclass(frozen=True, slots=True)
class _CredentialSendFailure:
    reason: TransportFailureReason
    attempts: int
    status_code: int | None


@dataclass(frozen=True, slots=True, repr=False)
class AuthenticatedTransport:
    """Apply credentials only to requests matching their exact origin scope."""

    transport: Transport
    credentials: tuple[CredentialHeader, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.credentials, tuple) or not self.credentials:
            raise TypeError("credentials must be a non-empty tuple of CredentialHeader values")
        if not all(isinstance(value, CredentialHeader) for value in self.credentials):
            raise TypeError("credentials must contain only CredentialHeader values")
        for index, credential in enumerate(self.credentials):
            for other in self.credentials[index + 1 :]:
                if credential.name.lower() == other.name.lower() and set(credential.origins) & set(other.origins):
                    raise ValueError("credential header names must be unique within each origin scope")

    def __repr__(self) -> str:
        names = tuple(value.name for value in self.credentials)
        return f"AuthenticatedTransport(transport={self.transport!r}, credential_headers={names!r}, values=[REDACTED])"

    def can_authenticate(self, url: str) -> bool:
        origin = _request_origin(url)
        return any(origin in credential.origins for credential in self.credentials)

    def send(self, request: TransportRequest) -> TransportResponse:
        origin = _request_origin(request.url)
        applicable = tuple(credential for credential in self.credentials if origin in credential.origins)
        if not applicable:
            return self.transport.send(request)
        existing = {name.lower() for name in request.headers}
        names = tuple(value.name.lower() for value in applicable)
        if len(names) != len(set(names)):
            raise ValueError("applicable credential header names must be unique case-insensitively")
        collisions = tuple(value.name for value in applicable if value.name.lower() in existing)
        if collisions:
            raise ValueError(f"source request already provides credential header: {collisions[0]}")
        result = _send_with_credentials(self.transport, request, applicable)
        if isinstance(result, TransportResponse):
            return result
        raise TransportFailure(
            request,
            result.reason,
            result.attempts,
            status_code=result.status_code,
        ) from None


def _send_with_credentials(
    transport: Transport,
    request: TransportRequest,
    credentials: tuple[CredentialHeader, ...],
) -> TransportResponse | _CredentialSendFailure:
    headers = dict(request.headers)
    headers.update((value.name, value._value) for value in credentials)
    authenticated = TransportRequest(
        request.method,
        request.url,
        request.params,
        headers,
        request.body,
        RedirectPolicy.REFUSE,
    )
    try:
        response = transport.send(authenticated)
        if 300 <= response.status_code < 400:
            return _CredentialSendFailure(TransportFailureReason.REDIRECT_REFUSED, 1, response.status_code)
        return response
    except TransportFailure as error:
        return _CredentialSendFailure(error.reason, error.attempts, error.status_code)
    except Exception:
        return _CredentialSendFailure(TransportFailureReason.TERMINAL_SENDER_FAILURE, 1, None)


def _credential_origin(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("credential origin must be a string")
    split = urlsplit(value)
    if split.scheme.lower() not in {"http", "https"} or split.hostname is None:
        raise ValueError("credential origin must use http or https with an authority")
    if (
        split.username is not None
        or split.password is not None
        or split.query
        or split.fragment
        or split.path not in {"", "/"}
    ):
        raise ValueError("credential origin must contain only scheme and authority")
    try:
        port = split.port
    except ValueError as error:
        raise ValueError("credential origin has an invalid port") from error
    scheme = split.scheme.lower()
    default_port = 80 if scheme == "http" else 443
    normalized_port = None if port == default_port else port
    authority = _serialize_authority(split.hostname.lower(), normalized_port)
    return f"{scheme}://{authority}"


def _request_origin(url: str) -> str:
    split = urlsplit(url)
    if split.scheme.lower() not in {"http", "https"} or split.hostname is None or split.username is not None:
        raise ValueError("request URL has no safe HTTP origin")
    try:
        port = split.port
    except ValueError as error:
        raise ValueError("request URL has an invalid port") from error
    scheme = split.scheme.lower()
    default_port = 80 if scheme == "http" else 443
    normalized_port = None if port == default_port else port
    authority = _serialize_authority(split.hostname.lower(), normalized_port)
    return f"{scheme}://{authority}"


def _serialize_authority(hostname: str, port: int | None) -> str:
    host = f"[{hostname}]" if ":" in hostname else hostname
    return host if port is None else f"{host}:{port}"

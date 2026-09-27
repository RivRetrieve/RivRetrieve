"""HTTP transport = execute : TransportRequest × TransportPolicy → TransportResponse | TransportFailure

credential application : CredentialHeader* × TransportRequest → TransportResponse | sanitized TransportFailure.

The trust boundary is this package's `_internal` namespace plus static provider-import tests. The private request seal prevents accidental construction and ordinary `object.__new__` forgery; it is not cryptographic isolation from hostile same-process reflection.
"""

from __future__ import annotations

import http.client
import math
import re
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

import requests
from urllib3 import exceptions as urllib3_exceptions

from rivretrieve._internal.issues import FatalContractError


class HttpMethod(StrEnum):
    GET = "GET"
    HEAD = "HEAD"
    POST = "POST"


RequestParameter = str | int | float | None


class ReplaySafety(StrEnum):
    METHOD_DEFAULT = "method_default"
    SAFE = "safe"


class RedirectPolicy(StrEnum):
    METHOD_DEFAULT = "method_default"
    REFUSE = "refuse"


_EMPTY_HEADERS: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True, repr=False, init=False)
class TransportRequest:
    method: HttpMethod
    url: str
    params: Mapping[str, RequestParameter] | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | str | None = None
    redirect_policy: RedirectPolicy = RedirectPolicy.METHOD_DEFAULT
    replay_safety: ReplaySafety = ReplaySafety.METHOD_DEFAULT

    def __init__(
        self,
        method: HttpMethod,
        url: str,
        params: Mapping[str, RequestParameter] | None = None,
        headers: Mapping[str, str] = _EMPTY_HEADERS,
        body: bytes | str | None = None,
        redirect_policy: RedirectPolicy = RedirectPolicy.METHOD_DEFAULT,
        replay_safety: ReplaySafety = ReplaySafety.METHOD_DEFAULT,
    ) -> None:
        if not isinstance(replay_safety, ReplaySafety):
            raise TypeError("replay safety must be ReplaySafety")
        validated, error = _validated_public_headers(headers)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "params", params)
        object.__setattr__(self, "headers", MappingProxyType(validated))
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "redirect_policy", redirect_policy)
        object.__setattr__(self, "replay_safety", replay_safety)
        if error is not None:
            if isinstance(headers, dict):
                headers.clear()
            headers = _EMPTY_HEADERS
            validated = {}
            raise ValueError(error) from None

    def __repr__(self) -> str:
        headers = {
            name: value if name.casefold() in _SAFE_ORDINARY_HEADER_NAMES else "[REDACTED]"
            for name, value in self.headers.items()
        }
        return (
            f"TransportRequest(method={self.method!r}, url={self.url!r}, params={self.params!r}, "
            f"headers={headers!r}, body={self.body!r}, redirect_policy={self.redirect_policy!r}, "
            f"replay_safety={self.replay_safety!r})"
        )


@dataclass(frozen=True, slots=True, init=False, repr=False)
class _CredentialTransportRequest:
    method: HttpMethod
    url: str
    params: Mapping[str, RequestParameter] | None
    headers: Mapping[str, str]
    body: bytes | str | None
    redirect_policy: RedirectPolicy
    replay_safety: ReplaySafety
    credential_header_names: tuple[str, ...]
    _authority_seal: object

    def __repr__(self) -> str:
        return (
            f"_CredentialTransportRequest(method={self.method!r}, url={self.url!r}, "
            f"params={self.params!r}, headers={tuple(self.headers)!r}, values=[REDACTED], "
            f"body={self.body!r}, redirect_policy={self.redirect_policy!r}, replay_safety={self.replay_safety!r}, "
            f"credential_header_names={self.credential_header_names!r})"
        )


def _credential_request_authority():
    seal = object()

    def make(
        request: TransportRequest,
        headers: Mapping[str, str],
        credential_header_names: tuple[str, ...],
        *,
        redirect_policy: RedirectPolicy,
    ) -> _CredentialTransportRequest:
        value = object.__new__(_CredentialTransportRequest)
        object.__setattr__(value, "method", request.method)
        object.__setattr__(value, "url", request.url)
        object.__setattr__(value, "params", request.params)
        object.__setattr__(value, "headers", MappingProxyType(dict(headers)))
        object.__setattr__(value, "body", request.body)
        object.__setattr__(value, "redirect_policy", redirect_policy)
        object.__setattr__(value, "replay_safety", request.replay_safety)
        object.__setattr__(
            value, "credential_header_names", _validated_header_names(credential_header_names, kind="credential")
        )
        object.__setattr__(value, "_authority_seal", seal)
        return value

    def is_authorized(value: object) -> bool:
        return isinstance(value, _CredentialTransportRequest) and getattr(value, "_authority_seal", None) is seal

    return make, is_authorized


_make_credential_transport_request, _is_authorized_credential_request = _credential_request_authority()
del _credential_request_authority


type _ExecutableTransportRequest = TransportRequest | _CredentialTransportRequest

_HTTP_FIELD_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_SAFE_ORDINARY_HEADER_NAMES = frozenset({"accept", "content-type", "user-agent"})


class SecretResponseDisposition(StrEnum):
    SECRET_RESPONSE_WITHHELD = "secret_response_withheld"


class RequestBodyShape(StrEnum):
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ExecutedRequestEvidence:
    """Executed request evidence = safe ordinary headers × typed credential names."""

    ordinary_headers: Mapping[str, str]
    credential_header_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordinary_headers", MappingProxyType(_safe_ordinary_headers(self.ordinary_headers)))
        names = _validated_header_names(self.credential_header_names, kind="credential")
        if {name.casefold() for name in names} & {name.casefold() for name in self.ordinary_headers}:
            raise ValueError("ordinary and credential header names must not collide")
        object.__setattr__(self, "credential_header_names", names)


@dataclass(frozen=True, slots=True)
class SecretCallTrace:
    """SecretCallTrace ≔ ordered non-secret facts about one withheld-response call."""

    method: HttpMethod
    url: str
    ordinary_headers: Mapping[str, str]
    request_parameters: Mapping[str, RequestParameter] | None
    request_body_shape: RequestBodyShape
    credential_header_names: tuple[str, ...]
    status_code: int
    retrieved_at: datetime
    content_type: str | None
    response_disposition: SecretResponseDisposition = SecretResponseDisposition.SECRET_RESPONSE_WITHHELD

    def __post_init__(self) -> None:
        if not isinstance(self.method, HttpMethod) or not isinstance(self.url, str) or not self.url:
            raise TypeError("secret call method and URL must be typed and non-empty")
        split = urlsplit(self.url)
        _request_origin(self.url)
        if split.query or split.fragment:
            raise ValueError("secret call URL must not contain query or fragment data")
        evidence = ExecutedRequestEvidence(self.ordinary_headers, self.credential_header_names)
        object.__setattr__(self, "ordinary_headers", evidence.ordinary_headers)
        object.__setattr__(self, "credential_header_names", evidence.credential_header_names)
        if self.request_parameters is not None:
            raise ValueError("secret call traces currently support no request parameters")
        if not isinstance(self.request_body_shape, RequestBodyShape):
            raise TypeError("secret call body shape must be RequestBodyShape")
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise ValueError("secret call status must be an HTTP status integer")
        if (
            not isinstance(self.retrieved_at, datetime)
            or self.retrieved_at.tzinfo is None
            or self.retrieved_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("secret call retrieval instant must be timezone-aware UTC")
        if self.content_type is not None and (
            not isinstance(self.content_type, str)
            or not self.content_type
            or len(self.content_type) > 256
            or re.fullmatch(r"[\x20-\x7e]+", self.content_type) is None
        ):
            raise TypeError("secret call content type must be safe visible ASCII or None")
        if self.response_disposition is not SecretResponseDisposition.SECRET_RESPONSE_WITHHELD:
            raise ValueError("secret call response must be withheld")


@dataclass(frozen=True)
class TransportResponse:
    content: bytes
    status_code: int
    retrieved_at: datetime
    content_type: str | None
    url: str
    request_parameters: Mapping[str, RequestParameter]
    applied_credential_header_names: tuple[str, ...] = ()
    prerequisite_calls: tuple[SecretCallTrace, ...] = ()
    executed_request: ExecutedRequestEvidence | None = field(default=None, compare=False, repr=False)
    attempts: int = field(default=1, compare=False)

    def __post_init__(self) -> None:
        if type(self.attempts) is not int or self.attempts < 1:
            raise FatalContractError("response attempts must be a positive integer")
        object.__setattr__(self, "request_parameters", MappingProxyType(dict(self.request_parameters)))
        names = _validated_header_names(self.applied_credential_header_names, kind="applied credential")
        object.__setattr__(self, "applied_credential_header_names", names)
        if not isinstance(self.prerequisite_calls, tuple) or any(
            not isinstance(call, SecretCallTrace) for call in self.prerequisite_calls
        ):
            raise TypeError("prerequisite calls must be a tuple of SecretCallTrace values")
        if self.executed_request is not None and not isinstance(self.executed_request, ExecutedRequestEvidence):
            raise TypeError("executed request must be ExecutedRequestEvidence or None")


class TransportFailureReason(StrEnum):
    HTTP_STATUS = "http_status"
    TERMINAL_SENDER_FAILURE = "terminal_sender_failure"
    RETRY_EXHAUSTED = "retry_exhausted"
    REDIRECT_REFUSED = "redirect_refused"
    RETAINED_METADATA_UNSAFE = "retained_metadata_unsafe"
    REPLAY_UNSAFE = "replay_unsafe"
    RETRY_DELAY_EXCEEDED = "retry_delay_exceeded"


class TransportFailureCategory(StrEnum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    INCOMPLETE_RESPONSE = "incomplete_response"
    TLS = "tls"
    INVALID_REQUEST = "invalid_request"
    DECODING = "decoding"
    PROTOCOL = "protocol"
    HTTP_STATUS = "http_status"
    UNKNOWN = "unknown"


class TransportFailure(Exception):  # noqa: N818 - exact transport-neutral contract name
    request: _ExecutableTransportRequest
    reason: TransportFailureReason
    attempts: int
    status_code: int | None
    response: TransportResponse | None

    def __init__(
        self,
        request: _ExecutableTransportRequest,
        reason: TransportFailureReason,
        attempts: int,
        *,
        status_code: int | None = None,
        category: TransportFailureCategory = TransportFailureCategory.UNKNOWN,
        response: TransportResponse | None = None,
    ) -> None:
        if response is not None and not isinstance(response, TransportResponse):
            raise TypeError("failure response must be a TransportResponse or None")
        self.response = response
        self.request = request
        self.reason = reason
        self.attempts = attempts
        self.status_code = status_code
        self.category = category
        super().__init__(f"HTTP transport failed after {attempts} attempt(s): {reason}")


class Transport(Protocol):
    """Execute one fully rendered source request."""

    def send(self, request: TransportRequest) -> TransportResponse: ...


@dataclass(frozen=True, slots=True)
class SenderResponse:
    """Complete response bytes and scheduling metadata from the HTTP boundary."""

    content: bytes
    status_code: int
    content_type: str | None
    retry_after: str | None = None


class Sender(Protocol):
    def __call__(
        self,
        request: _ExecutableTransportRequest,
        timeout_seconds: float,
    ) -> SenderResponse | tuple[bytes, int, str | None]: ...


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
    max_retry_delay_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout must be finite and positive")
        if not math.isfinite(self.max_retry_delay_seconds) or self.max_retry_delay_seconds < 0:
            raise ValueError("retry delay limit must be finite and nonnegative")
        for delay in (*self.backoff_seconds, self.minimum_interval_seconds):
            if not math.isfinite(delay) or not 0 <= delay <= self.max_retry_delay_seconds:
                raise ValueError("retry and pacing delays must be finite and within the retry delay limit")

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


def _send_with_requests(request: _ExecutableTransportRequest, timeout_seconds: float) -> SenderResponse:
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
            allow_redirects=(
                request.redirect_policy is not RedirectPolicy.REFUSE and request.replay_safety is ReplaySafety.SAFE
            ),
        )
    return SenderResponse(
        response.content,
        response.status_code,
        response.headers.get("Content-Type"),
        response.headers.get("Retry-After"),
    )


def _exception_chain(exception: BaseException) -> tuple[BaseException, ...]:
    """Inspect explicit wrapped causes, not incidental exception contexts."""
    pending = [exception]
    found: list[BaseException] = []
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        found.append(current)
        pending.extend(value for value in current.args if isinstance(value, BaseException))
        cause = current.__cause__
        if cause is not None:
            pending.append(cause)
        reason = getattr(current, "reason", None)
        if isinstance(reason, BaseException):
            pending.append(reason)
    return tuple(found)


def _sender_failure_category(exception: BaseException) -> TransportFailureCategory:
    chain = _exception_chain(exception)
    if any(
        isinstance(item, (requests.exceptions.SSLError, ssl.SSLError, urllib3_exceptions.SSLError)) for item in chain
    ):
        return TransportFailureCategory.TLS
    if any(
        isinstance(item, (requests.exceptions.ContentDecodingError, urllib3_exceptions.DecodeError)) for item in chain
    ):
        return TransportFailureCategory.DECODING
    if any(
        isinstance(
            item,
            (
                requests.exceptions.InvalidURL,
                requests.exceptions.InvalidSchema,
                requests.exceptions.MissingSchema,
                requests.exceptions.InvalidHeader,
                requests.exceptions.URLRequired,
            ),
        )
        for item in chain
    ):
        return TransportFailureCategory.INVALID_REQUEST
    # InvalidChunkLength inherits IncompleteRead, but is malformed framing, not truncation.
    if any(
        isinstance(item, (urllib3_exceptions.InvalidChunkLength, http.client.BadStatusLine))
        and not isinstance(item, http.client.RemoteDisconnected)
        for item in chain
    ):
        return TransportFailureCategory.PROTOCOL
    if any(isinstance(item, (http.client.IncompleteRead, urllib3_exceptions.IncompleteRead)) for item in chain):
        return TransportFailureCategory.INCOMPLETE_RESPONSE
    # urllib3 emits this exact sentinel on EOF while awaiting the next chunk size.
    # Unlike invalid chunk lengths, it carries no typed IncompleteRead cause.
    if any(
        type(item) is urllib3_exceptions.ProtocolError and item.args == ("Response ended prematurely",)
        for item in chain
    ):
        return TransportFailureCategory.INCOMPLETE_RESPONSE
    # urllib3's connection-establishment errors inherit ConnectTimeoutError,
    # although refused connections and DNS failures are not timeouts.
    if any(isinstance(item, urllib3_exceptions.NewConnectionError) for item in chain):
        return TransportFailureCategory.CONNECTION
    if any(isinstance(item, (requests.Timeout, TimeoutError, urllib3_exceptions.TimeoutError)) for item in chain):
        return TransportFailureCategory.TIMEOUT
    if any(isinstance(item, (ConnectionError, http.client.RemoteDisconnected)) for item in chain):
        return TransportFailureCategory.CONNECTION
    if any(
        isinstance(item, (requests.exceptions.ChunkedEncodingError, urllib3_exceptions.ProtocolError)) for item in chain
    ):
        return TransportFailureCategory.PROTOCOL
    if isinstance(exception, requests.ConnectionError):
        return TransportFailureCategory.CONNECTION
    return TransportFailureCategory.UNKNOWN


def _is_retryable_sender_exception(exception: BaseException) -> bool:
    return _sender_failure_category(exception) in {
        TransportFailureCategory.TIMEOUT,
        TransportFailureCategory.CONNECTION,
        TransportFailureCategory.INCOMPLETE_RESPONSE,
    }


def _retry_after_seconds(value: str | None, now: datetime) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if re.fullmatch(r"[0-9]+", value):
        # Avoid unbounded integer conversion, including Python's integer digit limit.
        digits = value.lstrip("0") or "0"
        if len(digits) > 308:
            return math.inf
        return float(digits)
    http_date = (
        r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), [0-9]{2} [A-Z][a-z]{2} [0-9]{4} "
        r"[0-9]{2}:[0-9]{2}:[0-9]{2} GMT"
        r"|(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
        r"[0-9]{2}-[A-Z][a-z]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT"
        r"|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Z][a-z]{2} [ 0-9][0-9] "
        r"[0-9]{2}:[0-9]{2}:[0-9]{2} [0-9]{4}"
    )
    if re.fullmatch(http_date, value) is None:
        return None
    try:
        instant = parsedate_to_datetime(value)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        seconds = (instant - now).total_seconds()
    except (ValueError, TypeError, OverflowError):
        return None
    return seconds if seconds >= 0 else None


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

    def send(self, request: _ExecutableTransportRequest) -> TransportResponse:
        if isinstance(request, _CredentialTransportRequest) and not _is_authorized_credential_request(request):
            raise TypeError("credential request lacks internal transport authority")
        prepared_request = self._with_policy_headers(request)
        credential_header_names = _request_credential_header_names(prepared_request)
        credential_names = {item.casefold() for item in credential_header_names}
        executed_request = ExecutedRequestEvidence(
            {
                name: value
                for name, value in prepared_request.headers.items()
                if name.casefold() not in credential_names
            },
            credential_header_names,
        )
        replay_safe = request.method in {HttpMethod.GET, HttpMethod.HEAD} or request.replay_safety is ReplaySafety.SAFE
        retry_delay = 0.0
        for attempt in range(1, TRANSPORT_POLICY.max_attempts + 1):
            if attempt > 1:
                self._sleeper(retry_delay)
            if attempt < TRANSPORT_POLICY.max_attempts:
                retry_delay = TRANSPORT_POLICY.backoff_seconds[attempt - 1]
            self._wait_for_rate_limit()

            try:
                sent = self._sender(prepared_request, TRANSPORT_POLICY.timeout_seconds)
                response = sent if isinstance(sent, SenderResponse) else SenderResponse(*sent)
            except (requests.RequestException, TimeoutError, ConnectionError) as exception:
                category = _sender_failure_category(exception)
                if not _is_retryable_sender_exception(exception):
                    reason = TransportFailureReason.TERMINAL_SENDER_FAILURE
                elif not replay_safe:
                    reason = TransportFailureReason.REPLAY_UNSAFE
                elif attempt == TRANSPORT_POLICY.max_attempts:
                    reason = TransportFailureReason.RETRY_EXHAUSTED
                else:
                    continue
                raise TransportFailure(request, reason, attempt, category=category) from exception

            content, status_code, content_type = response.content, response.status_code, response.content_type
            if status_code not in TRANSPORT_POLICY.retryable_status_codes:
                return TransportResponse(
                    content=content,
                    status_code=status_code,
                    retrieved_at=self._clock.utcnow(),
                    content_type=content_type,
                    url=request.url,
                    request_parameters={} if request.params is None else request.params,
                    applied_credential_header_names=credential_header_names,
                    executed_request=executed_request,
                    attempts=attempt,
                )
            if not replay_safe or attempt == TRANSPORT_POLICY.max_attempts:
                raise TransportFailure(
                    request,
                    TransportFailureReason.RETRY_EXHAUSTED if replay_safe else TransportFailureReason.REPLAY_UNSAFE,
                    attempt,
                    status_code=status_code,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            guidance = _retry_after_seconds(response.retry_after, self._clock.utcnow())
            if guidance is not None:
                if guidance > TRANSPORT_POLICY.max_retry_delay_seconds:
                    raise TransportFailure(
                        request,
                        TransportFailureReason.RETRY_DELAY_EXCEEDED,
                        attempt,
                        status_code=status_code,
                        category=TransportFailureCategory.HTTP_STATUS,
                    )
                retry_delay = max(retry_delay, guidance)

        raise AssertionError("retry loop exhausted without a terminal result")

    @staticmethod
    def _with_policy_headers(request: _ExecutableTransportRequest) -> _ExecutableTransportRequest:
        headers = dict(request.headers)
        if any(name.lower() == "user-agent" for name in headers):
            raise ValueError("Source request must not provide a User-Agent header")
        headers["User-Agent"] = TRANSPORT_POLICY.user_agent
        if isinstance(request, _CredentialTransportRequest):
            public = TransportRequest(
                request.method, request.url, request.params, {}, request.body, replay_safety=request.replay_safety
            )
            return _make_credential_transport_request(
                public,
                headers,
                request.credential_header_names,
                redirect_policy=request.redirect_policy,
            )
        return TransportRequest(
            request.method,
            request.url,
            request.params,
            headers,
            request.body,
            request.redirect_policy,
            request.replay_safety,
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
    category: TransportFailureCategory = TransportFailureCategory.UNKNOWN


class _CredentialContractFailure(StrEnum):
    FATAL = "fatal"


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
        return f"AuthenticatedTransport(transport=[REDACTED], credential_headers={names!r}, values=[REDACTED])"

    def can_authenticate(self, url: str) -> bool:
        origin = _request_origin(url)
        return any(origin in credential.origins for credential in self.credentials)

    def send(self, request: TransportRequest) -> TransportResponse:
        sanitized_request = _sanitize_if_request_contains_credentials(request, self.credentials)
        if sanitized_request is not None:
            request = sanitized_request
            raise TransportFailure(request, TransportFailureReason.TERMINAL_SENDER_FAILURE, 1) from None
        origin = _request_origin(request.url)
        applicable = tuple(credential for credential in self.credentials if origin in credential.origins)
        if not applicable:
            result = self.transport.send(request)
            if _response_contains_credentials(result, self.credentials):
                status_code = result.status_code
                attempts = result.attempts
                result = None
                request = _sanitized_request_for_credentials(request, self.credentials)
                raise TransportFailure(
                    request,
                    TransportFailureReason.RETAINED_METADATA_UNSAFE,
                    attempts,
                    status_code=status_code,
                ) from None
            return result
        existing = {name.lower() for name in request.headers}
        names = tuple(value.name.lower() for value in applicable)
        if len(names) != len(set(names)):
            raise ValueError("applicable credential header names must be unique case-insensitively")
        collisions = tuple(value.name for value in applicable if value.name.lower() in existing)
        if collisions:
            request = _sanitized_source_request(
                request,
                remove_names=tuple(value.name for value in applicable),
                forbidden_values=_credential_redaction_values(applicable),
            )
            raise ValueError(f"source request already provides credential header: {collisions[0]}") from None
        if _request_contains_values(request, _credential_redaction_values(applicable)):
            request = _sanitized_source_request(
                request,
                forbidden_values=_credential_redaction_values(applicable),
            )
            raise ValueError("source request ordinary header contains a credential value") from None
        result = _send_with_credentials(self.transport, request, applicable)
        if result is _CredentialContractFailure.FATAL:
            raise FatalContractError("Authenticated transport contract failed") from None
        if isinstance(result, TransportResponse):
            names = tuple(value.name for value in applicable)
            evidence = result.executed_request or ExecutedRequestEvidence(request.headers, names)
            if evidence.credential_header_names != tuple(sorted(names, key=lambda name: (name.casefold(), name))):
                attempts = result.attempts
                result = None
                evidence = ExecutedRequestEvidence({}, names)
                request = _sanitized_request_for_credentials(request, applicable)
                raise TransportFailure(
                    request,
                    TransportFailureReason.TERMINAL_SENDER_FAILURE,
                    attempts,
                ) from None
            unsafe = _response_contains_credentials(result, applicable)
            if unsafe:
                status_code = result.status_code
                attempts = result.attempts
                result = None
                evidence = ExecutedRequestEvidence({}, names)
                request = _sanitized_request_for_credentials(request, applicable)
                raise TransportFailure(
                    request,
                    TransportFailureReason.RETAINED_METADATA_UNSAFE,
                    attempts,
                    status_code=status_code,
                ) from None
            return replace(
                result,
                applied_credential_header_names=names,
                executed_request=evidence,
            )
        request = _sanitized_source_request(
            request,
            forbidden_values=_credential_redaction_values(applicable),
        )
        raise TransportFailure(
            request,
            result.reason,
            result.attempts,
            status_code=result.status_code,
            category=result.category,
        ) from None


def _send_with_credentials(
    transport: Transport,
    request: TransportRequest,
    credentials: tuple[CredentialHeader, ...],
) -> TransportResponse | _CredentialSendFailure | _CredentialContractFailure:
    headers = dict(request.headers)
    headers.update((value.name, value._value) for value in credentials)
    authenticated = _make_credential_transport_request(
        request,
        headers,
        tuple(value.name for value in credentials),
        redirect_policy=RedirectPolicy.REFUSE,
    )
    try:
        response = transport.send(authenticated)
        if 300 <= response.status_code < 400:
            return _CredentialSendFailure(
                TransportFailureReason.REDIRECT_REFUSED,
                response.attempts,
                response.status_code,
                TransportFailureCategory.HTTP_STATUS,
            )
        return response
    except TransportFailure as error:
        return _CredentialSendFailure(error.reason, error.attempts, error.status_code, error.category)
    except FatalContractError:
        return _CredentialContractFailure.FATAL
    except Exception:
        return _CredentialSendFailure(TransportFailureReason.TERMINAL_SENDER_FAILURE, 1, None)


def _request_credential_header_names(request: _ExecutableTransportRequest) -> tuple[str, ...]:
    if isinstance(request, _CredentialTransportRequest):
        if not _is_authorized_credential_request(request):
            raise TypeError("credential request lacks internal transport authority")
        return request.credential_header_names
    return ()


def _validated_public_headers(headers: Mapping[str, str]) -> tuple[dict[str, str], str | None]:
    if not isinstance(headers, Mapping):
        return {}, "request headers must be a mapping"
    names = tuple(name for name in headers if isinstance(name, str))
    folded = tuple(name.casefold() for name in names)
    if len(folded) != len(set(folded)):
        return {}, "request header names must be unique case-insensitively"
    if "user-agent" in folded:
        for name, value in headers.items():
            if isinstance(name, str) and name.casefold() == "user-agent" and value != TRANSPORT_POLICY.user_agent:
                return {}, "Source request must not provide a User-Agent header"
    try:
        return _safe_ordinary_headers(headers), None
    except TypeError:
        return {}, "request headers must have HTTP-token string names and string values"
    except ValueError:
        if any(isinstance(value, str) and re.fullmatch(r"[\x20-\x7e]+", value) is None for value in headers.values()):
            return {}, "request header values must contain only visible ASCII or spaces"
        return {}, "request headers must be explicitly safe ordinary metadata"


def _credential_redaction_values(credentials: tuple[CredentialHeader, ...]) -> tuple[str, ...]:
    """Protect both a complete authentication header and its source token.

    Publishers can echo a token without its HTTP authentication scheme. Such an
    echo must not become observation bytes, retained metadata, or diagnostics.
    """
    values: list[str] = []
    for credential in credentials:
        values.append(credential._value)
        scheme, separator, token = credential._value.partition(" ")
        if (
            credential.name.casefold() == "authorization"
            and scheme.casefold() in {"token", "bearer"}
            and separator
            and token
        ):
            values.append(token)
    return tuple(dict.fromkeys(values))


def _response_contains_credentials(response: TransportResponse, credentials: tuple[CredentialHeader, ...]) -> bool:
    return _response_contains_values(response, _credential_redaction_values(credentials))


def _sanitized_request_for_credentials(
    request: TransportRequest, credentials: tuple[CredentialHeader, ...]
) -> TransportRequest:
    return _sanitized_source_request(request, forbidden_values=_credential_redaction_values(credentials))


_PERCENT_TRIPLET = re.compile(rb"%[0-9A-Fa-f]{2}")
_MALFORMED_PERCENT = re.compile(rb"%(?![0-9A-Fa-f]{2})")
_MAX_PERCENT_DECODE_DEPTH = 8


def _encoded_candidate_contains_values(
    candidate: str | bytes,
    values: tuple[str, ...],
    *,
    refuse_malformed: bool,
) -> bool:
    from urllib.parse import unquote_to_bytes

    current = candidate.encode("utf-8") if isinstance(candidate, str) else candidate
    secrets = tuple(value.encode("utf-8") for value in values if value)
    for _ in range(_MAX_PERCENT_DECODE_DEPTH):
        if any(secret in current for secret in secrets):
            return True
        if refuse_malformed and _MALFORMED_PERCENT.search(current):
            return True
        decoded = unquote_to_bytes(current.replace(b"+", b" "))
        if decoded == current:
            return False
        current = decoded
    return bool(_PERCENT_TRIPLET.search(current)) or any(secret in current for secret in secrets)


def _request_contains_values(request: TransportRequest, values: tuple[str, ...]) -> bool:
    strict_form_candidates: tuple[str | bytes, ...] = (
        request.url,
        *(str(name) for name in (request.params or {})),
        *(str(value) for value in (request.params or {}).values()),
    )
    content_type = next((value for name, value in request.headers.items() if name.casefold() == "content-type"), "")
    body_is_form = content_type.partition(";")[0].strip().casefold() == "application/x-www-form-urlencoded"
    metadata_candidates: tuple[str | bytes, ...] = (
        request.method.value,
        *request.headers.keys(),
        *request.headers.values(),
        *((request.body,) if request.body is not None and not body_is_form else ()),
    )
    if request.body is not None and body_is_form:
        strict_form_candidates = (*strict_form_candidates, request.body)
    return any(
        _encoded_candidate_contains_values(candidate, values, refuse_malformed=True)
        for candidate in strict_form_candidates
    ) or any(
        _encoded_candidate_contains_values(candidate, values, refuse_malformed=False)
        for candidate in metadata_candidates
    )


def _response_contains_values(response: TransportResponse, values: tuple[str, ...]) -> bool:
    retained_text: list[str] = [
        response.url,
        response.content_type or "",
        *(str(name) for name in response.request_parameters),
        *(str(value) for value in response.request_parameters.values()),
        *response.applied_credential_header_names,
    ]
    if response.executed_request is not None:
        retained_text.extend(response.executed_request.ordinary_headers.keys())
        retained_text.extend(response.executed_request.ordinary_headers.values())
        retained_text.extend(response.executed_request.credential_header_names)
    for call in response.prerequisite_calls:
        retained_text.extend(
            (
                call.method.value,
                call.url,
                *call.ordinary_headers.keys(),
                *call.ordinary_headers.values(),
                *call.credential_header_names,
                *(str(name) for name in (call.request_parameters or {})),
                *(str(value) for value in (call.request_parameters or {}).values()),
                call.request_body_shape.value,
                str(call.status_code),
                call.retrieved_at.isoformat(),
                call.content_type or "",
                call.response_disposition.value,
            )
        )
    return any(
        _encoded_candidate_contains_values(candidate, values, refuse_malformed=False)
        for candidate in (*retained_text, response.content)
    )


def _sanitize_if_request_contains_credentials(
    request: TransportRequest, credentials: tuple[CredentialHeader, ...]
) -> TransportRequest | None:
    values = _credential_redaction_values(credentials)
    if not _request_contains_values(request, values):
        return None
    return _sanitized_source_request(request, forbidden_values=values)


def _sanitized_source_request(
    request: _ExecutableTransportRequest,
    *,
    remove_names: tuple[str, ...] = (),
    forbidden_values: tuple[str, ...] = (),
) -> TransportRequest:
    removed = {name.casefold() for name in (*remove_names, *_request_credential_header_names(request))}
    safe_url = (
        "https://redacted.invalid"
        if _encoded_candidate_contains_values(request.url, forbidden_values, refuse_malformed=True)
        else request.url
    )
    safe_params = {
        name: value
        for name, value in (request.params or {}).items()
        if not _encoded_candidate_contains_values(str(name), forbidden_values, refuse_malformed=True)
        and not _encoded_candidate_contains_values(str(value), forbidden_values, refuse_malformed=True)
    }
    safe_headers = {
        name: value
        for name, value in request.headers.items()
        if name.casefold() not in removed
        and not _encoded_candidate_contains_values(name, forbidden_values, refuse_malformed=False)
        and not _encoded_candidate_contains_values(value, forbidden_values, refuse_malformed=False)
    }
    content_type = next((value for name, value in request.headers.items() if name.casefold() == "content-type"), "")
    body_is_form = content_type.partition(";")[0].strip().casefold() == "application/x-www-form-urlencoded"
    safe_body = (
        None
        if request.body is not None
        and _encoded_candidate_contains_values(request.body, forbidden_values, refuse_malformed=body_is_form)
        else request.body
    )
    return TransportRequest(
        request.method,
        safe_url,
        safe_params or None,
        safe_headers,
        safe_body,
        request.redirect_policy,
        request.replay_safety,
    )


def _validated_header_names(names: tuple[str, ...], *, kind: str) -> tuple[str, ...]:
    if not isinstance(names, tuple) or any(
        not isinstance(name, str) or _HTTP_FIELD_NAME.fullmatch(name) is None for name in names
    ):
        raise TypeError(f"{kind} header names must be an HTTP-token tuple")
    ordered = tuple(sorted(names, key=lambda name: (name.casefold(), name)))
    if len({name.casefold() for name in ordered}) != len(ordered):
        raise ValueError(f"{kind} header names must be unique case-insensitively")
    return ordered


def _safe_ordinary_headers(headers: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(headers, Mapping):
        raise TypeError("ordinary request headers must be a mapping")
    result: dict[str, str] = {}
    seen: set[str] = set()
    for name, value in headers.items():
        if not isinstance(name, str) or _HTTP_FIELD_NAME.fullmatch(name) is None or not isinstance(value, str):
            raise TypeError("ordinary request headers must have HTTP-token string names and string values")
        folded = name.casefold()
        if folded in seen:
            raise ValueError("ordinary request header names must be unique case-insensitively")
        if folded not in _SAFE_ORDINARY_HEADER_NAMES:
            raise ValueError(f"request header is not explicitly safe ordinary metadata: {name}")
        if len(value) > 1024 or re.fullmatch(r"[\x20-\x7e]+", value) is None:
            raise ValueError("ordinary request header value is ambiguous or too large")
        if folded == "user-agent" and value != TRANSPORT_POLICY.user_agent:
            raise ValueError("only the engine User-Agent is safe ordinary metadata")
        result[name] = value
        seen.add(folded)
    return dict(sorted(result.items(), key=lambda item: (item[0].casefold(), item[0])))


def _credential_origin(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("credential origin must be a string")
    split = urlsplit(value)
    if split.scheme.lower() not in {"http", "https"} or split.hostname is None:
        raise ValueError("credential origin must use http or https with an authority")
    if (
        split.username is not None
        or split.password is not None
        or split.netloc.endswith(":")
        or not split.hostname.isascii()
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
    if (
        split.scheme.lower() not in {"http", "https"}
        or split.hostname is None
        or split.username is not None
        or split.password is not None
        or split.netloc.endswith(":")
        or not split.hostname.isascii()
    ):
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

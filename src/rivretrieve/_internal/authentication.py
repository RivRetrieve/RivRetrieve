"""credential exchange : SecretHeaders × ExchangeSpec × Transport × Clock → credentialed Transport + SecretCallTrace | SanitizedFailure."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import cast
from urllib.parse import urlsplit  # noqa: TID251 - URL parsing only; no network access

from rivretrieve._internal.transport import (
    Clock,
    CredentialHeader,
    HttpMethod,
    RedirectPolicy,
    RequestBodyShape,
    SecretCallTrace,
    Transport,
    TransportFailure,
    TransportRequest,
    TransportResponse,
    _credential_origin,
    _request_contains_values,
    _request_origin,
    _response_contains_values,
    _sanitized_source_request,
)


@dataclass(frozen=True, slots=True)
class ExchangeSpec:
    """ExchangeSpec ≔ public facts needed to turn a secret exchange into a scoped bearer header."""

    exchange_url: str
    token_json_path: tuple[str, ...]
    output_scheme: str
    lifetime_seconds: float
    refresh_after_seconds: float
    allowed_data_origin: str
    method: HttpMethod = HttpMethod.GET

    def __post_init__(self) -> None:
        if self.method is not HttpMethod.GET:
            raise ValueError("credential exchange supports exact GET only")
        _require_exact_origin_url(self.exchange_url, allow_path=True)
        if (
            not isinstance(self.token_json_path, tuple)
            or not self.token_json_path
            or any(not isinstance(p, str) or not p for p in self.token_json_path)
        ):
            raise TypeError("token JSON path must be a non-empty tuple")
        if (
            not isinstance(self.output_scheme, str)
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9._~-]*", self.output_scheme) is None
        ):
            raise TypeError("output scheme must be a non-empty authentication scheme")
        if type(self.lifetime_seconds) not in (int, float) or self.lifetime_seconds <= 0:
            raise ValueError("credential lifetime must be positive")
        if (
            type(self.refresh_after_seconds) not in (int, float)
            or not 0 < self.refresh_after_seconds < self.lifetime_seconds
        ):
            raise ValueError("refresh point must be positive and earlier than lifetime")
        normalized = _require_exact_origin_url(self.allowed_data_origin, allow_path=False)
        object.__setattr__(self, "allowed_data_origin", normalized)

    @classmethod
    def ana(cls) -> ExchangeSpec:
        return cls(
            exchange_url="https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas/OAUth/v1",
            token_json_path=("items", "tokenautenticacao"),
            output_scheme="Bearer",
            lifetime_seconds=3600,
            refresh_after_seconds=3300,
            allowed_data_origin="https://www.ana.gov.br",
        )


class AuthenticationFailureReason(StrEnum):
    EXCHANGE_SEND_FAILED = "exchange_send_failed"
    EXCHANGE_REDIRECT_REFUSED = "exchange_redirect_refused"
    EXCHANGE_HTTP_STATUS = "exchange_http_status"
    RESPONSE_JSON_INVALID = "response_json_invalid"
    RESPONSE_JSON_AMBIGUOUS = "response_json_ambiguous"
    EXCHANGE_RESPONSE_MISMATCH = "exchange_response_mismatch"
    RESPONSE_ENVELOPE_INVALID = "response_envelope_invalid"
    TOKEN_MISSING = "token_missing"
    TOKEN_EMPTY = "token_empty"
    TOKEN_WRONG_TYPE = "token_wrong_type"
    TOKEN_INVALID = "token_invalid"
    RETAINED_METADATA_UNSAFE = "retained_metadata_unsafe"
    DATA_REDIRECT_REFUSED = "data_redirect_refused"
    DATA_SEND_FAILED = "data_send_failed"


class CredentialExchangeError(Exception):
    def __init__(
        self, request: TransportRequest, reason: AuthenticationFailureReason, *, status_code: int | None = None
    ) -> None:
        self.request = request
        self.reason = reason
        self.status_code = status_code
        super().__init__(f"credential exchange failed: {reason}")


@dataclass(frozen=True, slots=True, repr=False)
class _Acquired:
    token: str = field(repr=False)
    refresh_at: float
    trace: SecretCallTrace | None
    auth_response: bytes | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        return "_Acquired(token=[REDACTED], refresh_at=[REDACTED], trace=[REDACTED], auth_response=[REDACTED])"


@dataclass(frozen=True, slots=True)
class _Failure:
    reason: AuthenticationFailureReason
    status_code: int | None = None


@dataclass(slots=True, repr=False)
class CredentialExchangeTransport:
    """Acquire, cache, and apply one scoped bearer credential without exposing secret responses."""

    transport: Transport
    secret_headers: tuple[CredentialHeader, ...]
    spec: ExchangeSpec
    clock: Clock
    _cached: _Acquired | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.secret_headers, tuple) or not self.secret_headers:
            raise TypeError("exchange secret headers must be a non-empty tuple")
        if not all(isinstance(value, CredentialHeader) for value in self.secret_headers):
            raise TypeError("exchange secret headers must contain CredentialHeader values")
        exchange_origin = _request_origin(self.spec.exchange_url)
        if any(exchange_origin not in header.origins for header in self.secret_headers):
            raise ValueError("every exchange credential must include the exact exchange origin")

    def __repr__(self) -> str:
        return f"CredentialExchangeTransport(transport=[REDACTED], secret_headers={tuple(h.name for h in self.secret_headers)!r}, spec={self.spec!r}, clock=[REDACTED], cache=[REDACTED])"

    def can_authenticate(self, url: str) -> bool:
        return _request_origin(url) == self.spec.allowed_data_origin

    def send(self, request: TransportRequest) -> TransportResponse:
        sanitized_request = _sanitize_if_contains_exchange_secrets(request, self.secret_headers, self._cached)
        if sanitized_request is not None:
            request = sanitized_request
            raise CredentialExchangeError(request, AuthenticationFailureReason.DATA_SEND_FAILED) from None
        if not self.can_authenticate(request.url):
            result = self.transport.send(request)
            if _exchange_response_contains_secrets(result, self.secret_headers, self._cached):
                result = None
                request = _sanitized_exchange_request(request, self.secret_headers, self._cached)
                raise CredentialExchangeError(request, AuthenticationFailureReason.RETAINED_METADATA_UNSAFE) from None
            return result
        now = self.clock.monotonic()
        acquired = (
            self._cached
            if self._cached is not None and now < self._cached.refresh_at
            else _acquire(self.transport, self.secret_headers, self.spec, self.clock)
        )
        if isinstance(acquired, _Failure):
            raise CredentialExchangeError(request, acquired.reason, status_code=acquired.status_code) from None
        result = _send_acquired(self.transport, request, acquired, self.spec, self.secret_headers)
        if isinstance(result, _Failure):
            self._cached = _Acquired(acquired.token, acquired.refresh_at, acquired.trace)
            request = _sanitized_source_request(
                request,
                remove_names=("Authorization",),
                forbidden_values=tuple(header._value for header in self.secret_headers) + (acquired.token,),
            )
            raise CredentialExchangeError(request, result.reason, status_code=result.status_code) from None
        self._cached = _Acquired(acquired.token, acquired.refresh_at, None)
        return result


def _exchange_secret_values(headers: tuple[CredentialHeader, ...], cached: _Acquired | None) -> tuple[str, ...]:
    return tuple(header._value for header in headers) + (() if cached is None else (cached.token,))


def _exchange_response_contains_secrets(
    response: TransportResponse,
    headers: tuple[CredentialHeader, ...],
    cached: _Acquired | None,
) -> bool:
    return _response_contains_values(response, _exchange_secret_values(headers, cached))


def _sanitized_exchange_request(
    request: TransportRequest,
    headers: tuple[CredentialHeader, ...],
    cached: _Acquired | None,
) -> TransportRequest:
    return _sanitized_source_request(request, forbidden_values=_exchange_secret_values(headers, cached))


def _sanitize_if_contains_exchange_secrets(
    request: TransportRequest,
    headers: tuple[CredentialHeader, ...],
    cached: _Acquired | None,
) -> TransportRequest | None:
    values = _exchange_secret_values(headers, cached)
    if not _request_contains_values(request, values):
        return None
    return _sanitized_source_request(request, forbidden_values=values)


class _DuplicateJsonKeyError(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise _DuplicateJsonKeyError
        result[name] = value
    return result


def _acquire(
    transport: Transport, headers: tuple[CredentialHeader, ...], spec: ExchangeSpec, clock: Clock
) -> _Acquired | _Failure:
    try:
        from rivretrieve._internal.transport import AuthenticatedTransport

        request = TransportRequest(spec.method, spec.exchange_url, redirect_policy=RedirectPolicy.REFUSE)
        response = AuthenticatedTransport(transport, headers).send(request)
        expected_names = tuple(sorted((header.name for header in headers), key=lambda name: (name.casefold(), name)))
        if (
            response.url != spec.exchange_url
            or dict(response.request_parameters)
            or response.applied_credential_header_names != expected_names
            or response.executed_request is None
            or response.executed_request.credential_header_names != expected_names
        ):
            return _Failure(AuthenticationFailureReason.EXCHANGE_RESPONSE_MISMATCH, response.status_code)
        if 300 <= response.status_code < 400:
            return _Failure(AuthenticationFailureReason.EXCHANGE_REDIRECT_REFUSED, response.status_code)
        if not 200 <= response.status_code < 300:
            return _Failure(AuthenticationFailureReason.EXCHANGE_HTTP_STATUS, response.status_code)
        try:
            envelope = json.loads(response.content, object_pairs_hook=_unique_json_object)
        except _DuplicateJsonKeyError:
            return _Failure(AuthenticationFailureReason.RESPONSE_JSON_AMBIGUOUS, response.status_code)
        except Exception:
            return _Failure(AuthenticationFailureReason.RESPONSE_JSON_INVALID, response.status_code)
        value: object = envelope
        for index, part in enumerate(spec.token_json_path):
            if not isinstance(value, Mapping):
                return _Failure(AuthenticationFailureReason.RESPONSE_ENVELOPE_INVALID, response.status_code)
            mapping = cast("Mapping[str, object]", value)
            if part not in mapping:
                return _Failure(
                    AuthenticationFailureReason.TOKEN_MISSING
                    if index == len(spec.token_json_path) - 1
                    else AuthenticationFailureReason.RESPONSE_ENVELOPE_INVALID,
                    response.status_code,
                )
            value = mapping[part]
        if not isinstance(value, str):
            return _Failure(AuthenticationFailureReason.TOKEN_WRONG_TYPE, response.status_code)
        if not value.strip():
            return _Failure(AuthenticationFailureReason.TOKEN_EMPTY, response.status_code)
        try:
            CredentialHeader("Authorization", f"{spec.output_scheme} {value}", (spec.allowed_data_origin,))
        except (TypeError, ValueError):
            return _Failure(AuthenticationFailureReason.TOKEN_INVALID, response.status_code)
        secrets = tuple(header._value for header in headers) + (value,)
        metadata_only_response = replace(response, content=b"")
        if _response_contains_values(metadata_only_response, secrets):
            status_code = response.status_code
            metadata_only_response = None
            response = None
            secrets = ()
            envelope = None
            mapping = None
            value = None
            return _Failure(AuthenticationFailureReason.RETAINED_METADATA_UNSAFE, status_code)
        trace = SecretCallTrace(
            method=spec.method,
            url=spec.exchange_url,
            ordinary_headers=response.executed_request.ordinary_headers if response.executed_request else {},
            request_parameters=None,
            request_body_shape=RequestBodyShape.NONE,
            credential_header_names=tuple(header.name for header in headers),
            status_code=response.status_code,
            retrieved_at=response.retrieved_at,
            content_type=response.content_type,
        )
        return _Acquired(value, clock.monotonic() + spec.refresh_after_seconds, trace, response.content)
    except TransportFailure as error:
        reason = (
            AuthenticationFailureReason.EXCHANGE_REDIRECT_REFUSED
            if error.reason.value == "redirect_refused"
            else AuthenticationFailureReason.RETAINED_METADATA_UNSAFE
            if error.reason.value == "retained_metadata_unsafe"
            else AuthenticationFailureReason.EXCHANGE_SEND_FAILED
        )
        return _Failure(reason, error.status_code)
    except Exception:
        return _Failure(AuthenticationFailureReason.EXCHANGE_SEND_FAILED)


def _send_acquired(
    transport: Transport,
    request: TransportRequest,
    acquired: _Acquired,
    spec: ExchangeSpec,
    secret_headers: tuple[CredentialHeader, ...],
) -> TransportResponse | _Failure:
    try:
        from rivretrieve._internal.transport import AuthenticatedTransport

        known_request_values = tuple(header._value for header in secret_headers) + (acquired.token,)
        if _request_contains_values(request, known_request_values):
            return _Failure(AuthenticationFailureReason.DATA_SEND_FAILED)
        bearer = CredentialHeader(
            "Authorization", f"{spec.output_scheme} {acquired.token}", (spec.allowed_data_origin,)
        )
        response = AuthenticatedTransport(transport, (bearer,)).send(request)
        auth_response_text = (
            () if acquired.auth_response is None else (acquired.auth_response.decode("utf-8", errors="ignore"),)
        )
        known_text = tuple(header._value for header in secret_headers) + (
            acquired.token,
            f"{spec.output_scheme} {acquired.token}",
            *auth_response_text,
        )
        if _response_contains_values(response, known_text) or (
            acquired.auth_response is not None and acquired.auth_response in response.content
        ):
            return _Failure(AuthenticationFailureReason.RETAINED_METADATA_UNSAFE, response.status_code)
        traces = () if acquired.trace is None else (acquired.trace,)
        return replace(response, prerequisite_calls=traces)
    except TransportFailure as error:
        if error.reason.value == "redirect_refused":
            reason = AuthenticationFailureReason.DATA_REDIRECT_REFUSED
        elif error.reason.value == "retained_metadata_unsafe":
            reason = AuthenticationFailureReason.RETAINED_METADATA_UNSAFE
        else:
            reason = AuthenticationFailureReason.DATA_SEND_FAILED
        return _Failure(reason, error.status_code)
    except Exception:
        return _Failure(AuthenticationFailureReason.DATA_SEND_FAILED)


def _require_exact_origin_url(url: str, *, allow_path: bool) -> str:
    split = urlsplit(url)
    origin = _request_origin(url) if allow_path else _credential_origin(url)
    if split.query or split.fragment or (not allow_path and split.path not in {"", "/"}):
        raise ValueError("URL contains facts outside the permitted exact origin/path contract")
    return origin

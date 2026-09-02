"""Recording replay = exact lookup : RecordedInteraction* × TransportRequest → TransportResponse | UnmatchedRequest."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Self, TextIO, cast

from rivretrieve._internal.transport import (
    HttpMethod,
    RequestParameter,
    TransportRequest,
    TransportResponse,
)

RECORDING_FORMAT_VERSION = 1
_SHA256_HEX_LENGTH = 64
_SECRET_FIELD_NAMES = frozenset(
    {
        "authorization",
        "proxyauthorization",
        "cookie",
        "setcookie",
        "apikey",
        "xapikey",
        "token",
        "apitoken",
        "accesstoken",
        "refreshtoken",
        "clientsecret",
        "password",
        "passwd",
        "secret",
        "subscriptionkey",
        "credentials",
        "privatekey",
    }
)


class InvalidRecordingError(ValueError):
    """A recording is incomplete, inconsistent, or has changed bytes."""


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    """The non-secret parts of the exact HTTP request issued to a source."""

    method: HttpMethod
    url: str
    parameters: Mapping[str, RequestParameter] | None = None
    body: bytes | str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.method, HttpMethod):
            raise TypeError("recorded request method must be HttpMethod")
        if not isinstance(self.url, str) or not self.url:
            raise TypeError("recorded request URL must be a non-empty string")
        if self.parameters is not None:
            if not isinstance(self.parameters, Mapping):
                raise TypeError("recorded request parameters must be a mapping or None")
            if any(not isinstance(name, str) for name in self.parameters):
                raise TypeError("recorded request parameter names must be strings")
            if any(not _is_request_parameter(value) for value in self.parameters.values()):
                raise TypeError("recorded request parameters contain an unsupported value")
            object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        if not isinstance(self.body, bytes | str | None):
            raise TypeError("recorded request body must be bytes, string, or None")
        _require_secret_safe_request(self)

    @classmethod
    def from_transport_request(cls, request: TransportRequest) -> Self:
        """Discard request headers, which may contain credentials and never enter recordings."""
        return cls(request.method, request.url, request.params, request.body)

    def describe(self) -> str:
        parameters = "null" if self.parameters is None else _compact_json(dict(self.parameters))
        return f"{self.method.value} {self.url} parameters={parameters}"


@dataclass(frozen=True, slots=True)
class RecordingEnvelope:
    """One source interaction with enough facts to replay and audit it."""

    request: RecordedRequest
    content: bytes
    status_code: int
    retrieved_at: datetime
    content_type: str | None
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, RecordedRequest):
            raise TypeError("recording request must be RecordedRequest")
        if type(self.content) is not bytes:
            raise TypeError("recording content must be bytes")
        if type(self.status_code) is not int:
            raise TypeError("recording status code must be an integer")
        if not isinstance(self.retrieved_at, datetime):
            raise TypeError("recording retrieval instant must be a datetime")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() != timedelta(0):
            raise ValueError("recording retrieval instant must be timezone-aware UTC")
        if self.content_type is not None and (not isinstance(self.content_type, str) or not self.content_type):
            raise TypeError("recording content type must be a non-empty string or None")
        if _payload_has_secret_field(self.content, content_type=self.content_type):
            raise ValueError("recording response contains a secret-bearing field")
        object.__setattr__(self, "sha256", hashlib.sha256(self.content).hexdigest())

    @classmethod
    def from_transport(cls, request: TransportRequest, response: TransportResponse) -> Self:
        """Capture the request and the response facts returned by the shared transport."""
        recorded_request = RecordedRequest.from_transport_request(request)
        if response.url != request.url or dict(response.request_parameters) != dict(request.params or {}):
            raise InvalidRecordingError("transport response does not describe the request being recorded")
        return cls(
            request=recorded_request,
            content=response.content,
            status_code=response.status_code,
            retrieved_at=response.retrieved_at,
            content_type=response.content_type,
        )

    def to_transport_response(self) -> TransportResponse:
        return TransportResponse(
            content=self.content,
            status_code=self.status_code,
            retrieved_at=self.retrieved_at,
            content_type=self.content_type,
            url=self.request.url,
            request_parameters={} if self.request.parameters is None else self.request.parameters,
        )


# A shorter name for callers that treat the envelope as one recording.
Recording = RecordingEnvelope


class UnmatchedRequestError(LookupError):
    """Replay has no recording for the exact requested interaction."""

    request: RecordedRequest

    def __init__(self, request: TransportRequest | RecordedRequest) -> None:
        self.request = (
            request if isinstance(request, RecordedRequest) else RecordedRequest.from_transport_request(request)
        )
        super().__init__(f"No recording matches request: {self.request.describe()}")


class ReplayTransport:
    """An offline transport that returns only an exact committed interaction."""

    def __init__(self, recordings: Iterable[RecordingEnvelope | str | Path]) -> None:
        resolved = tuple(_coerce_recording(recording) for recording in recordings)
        by_request: dict[tuple[object, ...], RecordingEnvelope] = {}
        for recording in resolved:
            key = _request_key(recording.request)
            if key in by_request:
                raise InvalidRecordingError(f"multiple recordings match request: {recording.request.describe()}")
            by_request[key] = recording
        self._recordings = MappingProxyType(by_request)

    def send(self, request: TransportRequest) -> TransportResponse:
        recorded_request = RecordedRequest.from_transport_request(request)
        key = _request_key(recorded_request)
        try:
            recording = self._recordings[key]
        except KeyError as exc:
            raise UnmatchedRequestError(request) from exc
        return recording.to_transport_response()


ReplayHttpClient = ReplayTransport


def write_recording(recording: RecordingEnvelope, path: str | Path) -> None:
    """Write one deterministic recording envelope."""
    destination = Path(path)
    destination.write_text(
        json.dumps(_recording_to_object(recording), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def read_recording(path: str | Path) -> RecordingEnvelope:
    """Read and verify one recording envelope without consulting provider code."""
    source = Path(path)
    try:
        value = json.loads(
            source.read_text(encoding="utf-8"),
            object_pairs_hook=lambda pairs: _unique_json_object(pairs, source),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidRecordingError(f"cannot read recording {source}: {exc}") from exc
    return _recording_from_object(value, source)


def dry_run_recordings(paths: Sequence[str | Path], *, output: TextIO | None = None) -> None:
    """Print replayable request facts without issuing a network request."""
    if not paths:
        raise ValueError("at least one recording path is required")
    destination = sys.stdout if output is None else output
    for path in paths:
        recording = read_recording(path)
        parameters = (
            "null" if recording.request.parameters is None else _compact_json(dict(recording.request.parameters))
        )
        print(f"url: {recording.request.url}", file=destination)
        print(f"parameters: {parameters}", file=destination)
        print(f"retrieved_at: {_format_utc(recording.retrieved_at)}", file=destination)


def main(argv: Sequence[str] | None = None) -> int:
    """Inspect the exact interactions a later live re-record job would issue."""
    parser = argparse.ArgumentParser(
        prog="rivretrieve-rerecord",
        description="Inspect observation recordings without network access.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="print recorded request facts and issue no network request",
    )
    parser.add_argument("recordings", nargs="+", metavar="RECORDING")
    arguments = parser.parse_args(argv)
    dry_run_recordings(arguments.recordings)
    return 0


def _request_key(request: RecordedRequest) -> tuple[object, ...]:
    parameters = (
        None
        if request.parameters is None
        else tuple((name, _parameter_key(value)) for name, value in sorted(request.parameters.items()))
    )
    return request.method, request.url, parameters, request.body


def _parameter_key(value: RequestParameter) -> tuple[str, object]:
    if value is None:
        return "none", ""
    if type(value) is float:
        return "float", value.hex()
    return type(value).__name__, value


def _coerce_recording(recording: RecordingEnvelope | str | Path) -> RecordingEnvelope:
    if isinstance(recording, RecordingEnvelope):
        return recording
    return read_recording(recording)


def _recording_to_object(recording: RecordingEnvelope) -> dict[str, object]:
    return {
        "format_version": RECORDING_FORMAT_VERSION,
        "request": {
            "method": recording.request.method.value,
            "url": recording.request.url,
            "parameters": None if recording.request.parameters is None else dict(recording.request.parameters),
            "body": _encode_body(recording.request.body),
        },
        "response": {
            "status_code": recording.status_code,
            "content_type": recording.content_type,
            "retrieved_at": _format_utc(recording.retrieved_at),
            "content_base64": base64.b64encode(recording.content).decode("ascii"),
            "sha256": recording.sha256,
        },
    }


def _recording_from_object(value: object, source: Path) -> RecordingEnvelope:
    root = _require_object(value, "recording", source)
    _require_exact_keys(root, {"format_version", "request", "response"}, "recording", source)
    if root["format_version"] != RECORDING_FORMAT_VERSION:
        raise InvalidRecordingError(f"recording {source} has unsupported format_version {root['format_version']!r}")

    request_value = _require_object(root["request"], "request", source)
    _require_exact_keys(request_value, {"method", "url", "parameters", "body"}, "request", source)
    try:
        method = HttpMethod(request_value["method"])
    except (TypeError, ValueError) as exc:
        raise InvalidRecordingError(f"recording {source} has an invalid request method") from exc
    parameters = request_value["parameters"]
    if parameters is not None and not isinstance(parameters, dict):
        raise InvalidRecordingError(f"recording {source} request parameters must be an object or null")
    try:
        request = RecordedRequest(
            method=method,
            url=cast("str", request_value["url"]),
            parameters=cast("Mapping[str, RequestParameter] | None", parameters),
            body=_decode_body(request_value["body"], source),
        )
    except (TypeError, ValueError) as exc:
        raise InvalidRecordingError(f"recording {source} has an invalid request: {exc}") from exc

    response = _require_object(root["response"], "response", source)
    _require_exact_keys(
        response,
        {"status_code", "content_type", "retrieved_at", "content_base64", "sha256"},
        "response",
        source,
    )
    content = _decode_base64(response["content_base64"], "response content", source)
    expected_digest = response["sha256"]
    if (
        not isinstance(expected_digest, str)
        or len(expected_digest) != _SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in expected_digest)
    ):
        raise InvalidRecordingError(f"recording {source} has an invalid response SHA-256")
    actual_digest = hashlib.sha256(content).hexdigest()
    if actual_digest != expected_digest:
        raise InvalidRecordingError(
            f"recording {source} response SHA-256 mismatch: expected {expected_digest}, got {actual_digest}"
        )
    try:
        retrieved_at = _parse_utc(response["retrieved_at"])
        recording = RecordingEnvelope(
            request=request,
            content=content,
            status_code=cast("int", response["status_code"]),
            retrieved_at=retrieved_at,
            content_type=cast("str | None", response["content_type"]),
        )
    except (TypeError, ValueError) as exc:
        raise InvalidRecordingError(f"recording {source} has an invalid response: {exc}") from exc
    return recording


def _unique_json_object(pairs: list[tuple[str, object]], source: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise InvalidRecordingError(f"recording {source} contains duplicate field {name!r}")
        result[name] = value
    return result


def _require_object(value: object, name: str, source: Path) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise InvalidRecordingError(f"recording {source} {name} must be an object")
    return cast("dict[str, object]", value)


def _require_exact_keys(value: Mapping[str, object], expected: set[str], name: str, source: Path) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise InvalidRecordingError(f"recording {source} {name} fields differ: missing={missing}, extra={extra}")


def _require_secret_safe_request(request: RecordedRequest) -> None:
    authority = request.url.partition("://")[2].split("/", 1)[0]
    if "@" in authority:
        raise ValueError("recorded request contains secret-bearing URL credentials")
    names = _form_field_names(request.url.partition("?")[2].partition("#")[0])
    if request.parameters is not None:
        names.extend(request.parameters)
    sensitive = sorted(name for name in names if _is_secret_field_name(name))
    if sensitive:
        raise ValueError(f"recorded request contains secret-bearing parameter(s): {sensitive}")
    if request.body is not None and _payload_has_secret_field(request.body):
        raise ValueError("recorded request contains a secret-bearing body field")


def _form_field_names(value: str) -> list[str]:
    names: list[str] = []
    for form_field in value.split("&"):
        if not form_field:
            continue
        encoded_name = form_field.partition("=")[0].replace("+", " ")
        names.append(re.sub(r"%([0-9a-fA-F]{2})", lambda match: chr(int(match.group(1), 16)), encoded_name))
    return names


def _normalise_secret_name(name: str) -> str:
    return "".join(character for character in name.casefold() if character.isalnum())


def _is_secret_field_name(name: str) -> bool:
    normalised = _normalise_secret_name(name)
    return normalised in _SECRET_FIELD_NAMES or normalised.endswith(
        ("authtoken", "apitoken", "apikey", "password", "passwd", "secret", "subscriptionkey", "privatekey")
    )


def _payload_has_secret_field(
    payload: bytes | str,
    *,
    content_type: str | None = None,
) -> bool:
    media_type = _media_type(content_type)
    opaque_signature_mismatch = False
    if isinstance(payload, str):
        text = payload
    else:
        signatures = _opaque_signatures(media_type)
        if signatures is not None:
            if payload.startswith(signatures):
                return False
            text = _decode_text_payload(payload, content_type=content_type, structured=True)
            opaque_signature_mismatch = True
        elif _is_generic_binary_media_type(media_type):
            if _has_opaque_magic(payload):
                return False
            text = _decode_text_payload(payload, content_type=content_type, structured=False)
            if text is None:
                return False
        elif content_type is None and _has_opaque_magic(payload):
            return False
        else:
            text = _decode_text_payload(
                payload,
                content_type=content_type,
                structured=_is_structured_media_type(media_type),
            )
            if text is None:
                return False
    if text is None:  # All nullable decode paths return above.
        raise AssertionError("unreachable text decoding state")
    has_secret = _text_has_secret_field(text, media_type=media_type)
    if opaque_signature_mismatch and not has_secret:
        raise ValueError("recording content type does not match its binary signature")
    return has_secret


def _media_type(content_type: str | None) -> str | None:
    if content_type is None:
        return None
    return content_type.partition(";")[0].strip().casefold()


def _is_structured_media_type(media_type: str | None) -> bool:
    if media_type is None:
        return False
    return (
        media_type.startswith("text/")
        or media_type.endswith("+json")
        or media_type.endswith("+xml")
        or media_type
        in {
            "application/json",
            "application/xml",
            "application/x-www-form-urlencoded",
        }
        or media_type.startswith("multipart/")
    )


def _opaque_signatures(media_type: str | None) -> tuple[bytes, ...] | None:
    if media_type in {
        "application/zip",
        "application/x-zip-compressed",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }:
        return (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
    if media_type == "application/pdf":
        return (b"%PDF-",)
    if media_type == "application/vnd.apache.parquet":
        return (b"PAR1",)
    if media_type == "application/gzip":
        return (b"\x1f\x8b",)
    return None


def _is_generic_binary_media_type(media_type: str | None) -> bool:
    return media_type == "application/octet-stream" or (
        media_type is not None and media_type.startswith(("image/", "audio/", "video/"))
    )


def _has_opaque_magic(payload: bytes) -> bool:
    return payload.startswith(
        (
            b"PK\x03\x04",
            b"PK\x05\x06",
            b"PK\x07\x08",
            b"PAR1",
            b"%PDF-",
            b"\x1f\x8b",
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        )
    )


def _decode_text_payload(
    payload: bytes,
    *,
    content_type: str | None,
    structured: bool,
) -> str | None:
    charset_match = None if content_type is None else re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type, re.I)
    encoding = charset_match.group(1) if charset_match is not None else None
    if encoding is None:
        if payload.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
            encoding = "utf-32"
        elif payload.startswith((b"\xff\xfe", b"\xfe\xff")):
            encoding = "utf-16"
        elif payload.startswith(b"\xef\xbb\xbf"):
            encoding = "utf-8-sig"
        else:
            encoding = "utf-8"
    try:
        return payload.decode(encoding)
    except (LookupError, UnicodeDecodeError) as exc:
        if structured:
            raise ValueError("structured recording content cannot be decoded safely") from exc
        return None


def _text_has_secret_field(text: str, *, media_type: str | None) -> bool:
    stripped = text.lstrip("\ufeff \t\r\n")
    if stripped.startswith(("{", "[")):
        try:
            return _object_has_secret_field(json.loads(stripped))
        except json.JSONDecodeError as exc:
            if _is_structured_media_type(media_type):
                raise ValueError("structured recording content is not valid JSON") from exc

    if media_type == "application/xml" or (media_type is not None and media_type.endswith("+xml")):
        try:
            root = ET.fromstring(stripped)
        except ET.ParseError as exc:
            raise ValueError("structured recording content is not valid XML") from exc
        if any(
            _is_secret_field_name(_xml_local_name(name))
            for element in root.iter()
            for name in (element.tag, *element.attrib)
            if isinstance(name, str)
        ):
            return True

    declared_names = re.findall(
        r"(?:content-disposition:[^\r\n;]*;[^\r\n]*?\bname|\bname)\s*=\s*[\"']?([^\"';\s\r\n]+)",
        text,
        flags=re.I,
    )
    keyed_names = re.findall(r"[\"']?([A-Za-z][A-Za-z0-9_.-]*)[\"']?\s*[:=]", text)
    element_names = re.findall(r"<\s*/?\s*([A-Za-z_][A-Za-z0-9_.:-]*)", text)
    names = [*_form_field_names(text), *declared_names, *keyed_names, *element_names]
    return any(_is_secret_field_name(_xml_local_name(name)) for name in names)


def _xml_local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _object_has_secret_field(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            (isinstance(name, str) and _is_secret_field_name(name)) or _object_has_secret_field(child)
            for name, child in value.items()
        )
    if isinstance(value, list):
        return any(_object_has_secret_field(child) for child in value)
    return False


def _is_request_parameter(value: object) -> bool:
    return value is None or type(value) in (str, int, float)


def _encode_body(body: bytes | str | None) -> dict[str, str] | None:
    if body is None:
        return None
    if isinstance(body, bytes):
        return {"encoding": "base64", "value": base64.b64encode(body).decode("ascii")}
    return {"encoding": "utf-8", "value": body}


def _decode_body(value: object, source: Path) -> bytes | str | None:
    if value is None:
        return None
    body = _require_object(value, "request body", source)
    _require_exact_keys(body, {"encoding", "value"}, "request body", source)
    encoding = body["encoding"]
    if encoding == "base64":
        return _decode_base64(body["value"], "request body", source)
    if encoding == "utf-8" and isinstance(body["value"], str):
        return body["value"]
    raise InvalidRecordingError(f"recording {source} has an invalid request body encoding")


def _decode_base64(value: object, name: str, source: Path) -> bytes:
    if not isinstance(value, str):
        raise InvalidRecordingError(f"recording {source} {name} must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidRecordingError(f"recording {source} {name} is not valid base64") from exc


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("retrieved_at must be an RFC 3339 UTC string ending in Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("retrieved_at must be UTC")
    return parsed


def _compact_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())

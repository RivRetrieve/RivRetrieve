"""Lossless JSON encoding of sanitized source-call provenance values."""

from __future__ import annotations

from datetime import datetime
from typing import cast

_MARKER = "__rivretrieve_value_type__"


def encode_source_call(call: dict[str, object]) -> dict[str, object]:
    encoded = _encode(call)
    assert isinstance(encoded, dict)
    return cast(dict[str, object], encoded)


def decode_source_call(call: dict[str, object]) -> dict[str, object]:
    decoded = _decode(call)
    if not isinstance(decoded, dict):
        raise ValueError("Source call must be an object")
    return cast(dict[str, object], decoded)


def _encode(value: object) -> object:
    if isinstance(value, datetime):
        return {_MARKER: "datetime", "value": value.isoformat(timespec="microseconds")}
    if isinstance(value, tuple):
        return {_MARKER: "tuple", "value": [_encode(item) for item in value]}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        if _MARKER in value or any(not isinstance(key, str) for key in value):
            raise ValueError("Source-call mapping contains a reserved marker or non-string key")
        return {key: _encode(item) for key, item in value.items()}
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"Unsupported source-call provenance value: {type(value).__name__}")


def _decode(value: object) -> object:
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Source-call mapping keys must be strings")
        mapping = cast(dict[str, object], value)
        if _MARKER in mapping:
            if set(mapping) != {_MARKER, "value"}:
                raise ValueError("Malformed typed source-call value")
            if mapping[_MARKER] == "datetime" and isinstance(mapping["value"], str):
                return datetime.fromisoformat(mapping["value"])
            if mapping[_MARKER] == "tuple" and isinstance(mapping["value"], list):
                return tuple(_decode(item) for item in mapping["value"])
            raise ValueError("Unknown typed source-call value")
        return {key: _decode(item) for key, item in mapping.items()}
    return value

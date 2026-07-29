"""Generic JSON and CSV syntax decoders.

decode_json : (bytes | str) × str → JsonValue; decode_csv : (bytes | str) × str × (str | csv.Dialect) × (str | None) → list[list[str]]
"""

from __future__ import annotations

import csv
import io
import json
from typing import cast

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


def decode_json(content: bytes | str, *, encoding: str = "utf-8") -> JsonValue:
    """Decode JSON syntax from byte or text content."""
    text = content.decode(encoding) if isinstance(content, bytes) else content
    return cast(JsonValue, json.loads(text))


def decode_csv(
    content: bytes | str,
    *,
    encoding: str = "utf-8",
    dialect: str | csv.Dialect = "excel",
    delimiter: str | None = None,
) -> list[list[str]]:
    """Decode CSV syntax from byte or text content."""
    text = content.decode(encoding) if isinstance(content, bytes) else content
    stream = io.StringIO(text, newline="")
    if delimiter is None:
        reader = csv.reader(stream, dialect=dialect, strict=True)
    else:
        reader = csv.reader(
            stream,
            dialect=dialect,
            delimiter=delimiter,
            strict=True,
        )
    return list(reader)

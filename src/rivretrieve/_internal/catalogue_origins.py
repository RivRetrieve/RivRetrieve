"""CatalogueOrigin ≔ Field(NativeColumn) | NotPublished(Evidence)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HTTP_DOCUMENTATION_URL = re.compile(r"https?://[^\s/?#]+(?:[/?#][^\s]*)?")


class NativeColumn(str):
    """An exact, non-empty column name in a provider's native table."""

    def __new__(cls, value: str) -> NativeColumn:
        if not isinstance(value, str):
            raise TypeError("native column name must be a string")
        if not value.strip():
            raise ValueError("native column name must not be empty")
        return super().__new__(cls, value)


class Evidence(str):
    """An absolute HTTP(S) link to a provider's own documentation."""

    def __new__(cls, value: str) -> Evidence:
        if not isinstance(value, str):
            raise TypeError("evidence must be a string")
        if _HTTP_DOCUMENTATION_URL.fullmatch(value) is None:
            raise ValueError("evidence must be an absolute HTTP(S) documentation link")
        return super().__new__(cls, value)


@dataclass(frozen=True, slots=True)
class Field:
    native_column: NativeColumn

    def __post_init__(self) -> None:
        if not isinstance(self.native_column, NativeColumn):
            raise TypeError("Field.native_column must be a NativeColumn")


@dataclass(frozen=True, slots=True)
class NotPublished:
    evidence: Evidence

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, Evidence):
            raise TypeError("NotPublished.evidence must be Evidence")


type CatalogueOrigin = Field | NotPublished

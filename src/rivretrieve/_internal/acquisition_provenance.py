"""acquisition provenance : ProvenanceDocument → AcquisitionProvenance (pure).

The model records who issued facts, how RivRetrieve acquired them, and what
source words were established. Documentation evidence and acquisition records
are separate domain objects because they answer different questions.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from datetime import datetime
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator
from pypdf import PdfReader

from rivretrieve._internal.issues import FatalContractError

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitRevision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class _ProvenanceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RecordingReference(_ProvenanceModel):
    """Identity and retrieval context for recorded public source bytes."""

    recording_id: str
    repository_path: str
    source_url: str
    retrieved_at: datetime
    media_type: str
    sha256: Sha256

    @field_validator("repository_path")
    @classmethod
    def _relative_repository_path(cls, value: str) -> str:
        return _validate_repository_path(value)


class EvidenceReference(_ProvenanceModel):
    """Publisher documentation used to establish a factual source claim."""

    evidence_id: str
    description: str
    recording: RecordingReference


class AcquisitionRecord(_ProvenanceModel):
    """RivRetrieve's record of how it came to hold source material."""

    acquisition_id: str
    method: Literal["http_campaign", "http_request", "repository_recovery", "runtime_http_request"]
    description: str
    requested_from: tuple[str, ...]
    retrieved_at_start: datetime | None = None
    retrieved_at_end: datetime | None = None
    recording_ids: tuple[str, ...] = ()


class SourceStatement(_ProvenanceModel):
    """Exact source words about licence, citation, terms, or access."""

    kind: Literal["license", "citation", "terms", "access"]
    exact_text: str
    recording_id: str


class SourceRecord(_ProvenanceModel):
    """One issuing body, its operator, acquisition, and established words."""

    source_id: str
    issuer: str
    operator: str | None = None
    acquisitions: tuple[AcquisitionRecord, ...]
    evidence: tuple[EvidenceReference, ...] = ()
    statements: tuple[SourceStatement, ...] = ()


class FactBinding(_ProvenanceModel):
    """Bind one coherent group of externally visible facts to one source."""

    fact_group: str
    facts: tuple[str, ...]
    source_id: str
    acquisition_id: str


class WithheldFact(_ProvenanceModel):
    """Name a fact excluded because no acquisition record was established."""

    fact: str
    reason: Literal["acquisition_not_established"]


class SemanticDigest(_ProvenanceModel):
    """Named semantic digest that supplements, but never replaces, raw identity."""

    name: str
    sha256: Sha256


class NativeTableIdentity(_ProvenanceModel):
    """Immutable repository identity of a committed native build input."""

    repository_path: str
    revision: GitRevision
    sha256: Sha256
    semantic_digest: SemanticDigest | None = None

    @field_validator("repository_path")
    @classmethod
    def _relative_repository_path(cls, value: str) -> str:
        return _validate_repository_path(value)


class AcquisitionProvenance(_ProvenanceModel):
    """Shared provider acquisition provenance stored once per catalogue."""

    schema_version: Literal[1]
    provider_id: str
    native_table: NativeTableIdentity
    source_records: tuple[SourceRecord, ...]
    fact_bindings: tuple[FactBinding, ...]
    withheld_facts: tuple[WithheldFact, ...] = ()

    @model_validator(mode="after")
    def _references_are_closed(self) -> Self:
        source_ids = [record.source_id for record in self.source_records]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source record ids must be unique")
        recording_ids = {
            evidence.recording.recording_id for record in self.source_records for evidence in record.evidence
        }
        acquisition_keys: set[tuple[str, str]] = set()
        for record in self.source_records:
            acquisition_ids = [acquisition.acquisition_id for acquisition in record.acquisitions]
            if len(acquisition_ids) != len(set(acquisition_ids)):
                raise ValueError(f"source {record.source_id} acquisition ids must be unique")
            acquisition_keys.update((record.source_id, acquisition_id) for acquisition_id in acquisition_ids)
            for acquisition in record.acquisitions:
                acquisition_recordings = set(acquisition.recording_ids)
                if not acquisition_recordings <= recording_ids:
                    raise ValueError(f"source {record.source_id} acquisition references an unknown recording")
                if acquisition.method != "runtime_http_request" and acquisition.retrieved_at_start is None:
                    raise ValueError(f"source {record.source_id} recorded acquisition has no retrieval instant")
            for statement in record.statements:
                if statement.recording_id not in recording_ids:
                    raise ValueError(f"source {record.source_id} statement references an unknown recording")
        if any(not record.acquisitions for record in self.source_records):
            raise ValueError("every source record must contain an acquisition")
        if any(not binding.facts for binding in self.fact_bindings):
            raise ValueError("fact bindings must contain at least one fact")
        fact_groups = [binding.fact_group for binding in self.fact_bindings]
        if len(fact_groups) != len(set(fact_groups)):
            raise ValueError("fact group ids must be unique")
        bound_facts = {fact for binding in self.fact_bindings for fact in binding.facts}
        withheld = {item.fact for item in self.withheld_facts}
        if overlap := bound_facts & withheld:
            raise ValueError(f"facts cannot be both bound and withheld: {sorted(overlap)!r}")
        unknown_sources = {binding.source_id for binding in self.fact_bindings} - set(source_ids)
        if unknown_sources:
            raise ValueError(f"fact bindings reference unknown sources: {sorted(unknown_sources)!r}")
        unknown_acquisitions = {
            (binding.source_id, binding.acquisition_id)
            for binding in self.fact_bindings
            if (binding.source_id, binding.acquisition_id) not in acquisition_keys
        }
        if unknown_acquisitions:
            raise ValueError(f"fact bindings reference unknown acquisitions: {sorted(unknown_acquisitions)!r}")
        return self


def _validate_repository_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not value:
        raise ValueError("repository paths must be non-empty relative paths without parent traversal")
    return value


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def verify_recorded_statement(
    *,
    recording_name: str,
    body: bytes,
    expected_sha256: str,
    media_type: str,
    exact_text: str,
) -> None:
    """Verify a source statement against the exact recorded bytes.

    Parameters
    ----------
    recording_name
        Stable name used in all rejection messages.
    body
        Complete recorded response bytes.
    expected_sha256
        Expected raw-byte SHA-256.
    media_type
        Recorded response content type, including an HTML charset when known.
    exact_text
        Exact source statement that must occur after mechanical text normalization.

    Raises
    ------
    FatalContractError
        If byte identity differs, the media type cannot be read, or the named
        quotation is absent.
    """
    observed = hashlib.sha256(body).hexdigest()
    if observed != expected_sha256:
        raise FatalContractError(
            f"source recording {recording_name} digest mismatch: expected {expected_sha256}, observed {observed}"
        )
    normalized_page = _recording_text(recording_name, body, media_type)
    if _normalize_source_text(exact_text) not in normalized_page:
        raise FatalContractError(f"source recording {recording_name}: quotation is absent from recorded bytes")


def _recording_text(recording_name: str, body: bytes, media_type: str) -> str:
    if "pdf" in media_type.casefold():
        try:
            return _normalize_source_text(
                "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(body)).pages)
            )
        except Exception as exc:
            raise FatalContractError(f"source recording {recording_name}: PDF text cannot be read") from exc
    if "html" in media_type.casefold() or media_type.casefold().startswith("text/"):
        parser = _HtmlText()
        parser.feed(body.decode(_declared_encoding(body, media_type), errors="replace"))
        return _normalize_source_text("".join(parser.parts))
    raise FatalContractError(f"source recording {recording_name}: unsupported media type {media_type!r}")


def _declared_encoding(body: bytes, media_type: str) -> str:
    for source in (media_type.encode("ascii", "replace"), body[:8192]):
        match = re.search(rb"charset=[\"']?\s*([\w.:-]+)", source, re.IGNORECASE)
        if match is None:
            continue
        candidate = match.group(1).decode("ascii", "replace").strip().lower()
        try:
            "".encode(candidate)
        except LookupError:
            continue
        return candidate
    return "utf-8"


def _normalize_source_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for fancy, plain in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), (" ", " ")):
        text = text.replace(fancy, plain)
    return re.sub(r"\s+", " ", text).strip().casefold()

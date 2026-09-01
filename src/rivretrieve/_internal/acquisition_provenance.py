"""acquisition provenance : ProvenanceDocument → AcquisitionProvenance (pure).

The model records who issued facts, how RivRetrieve acquired them, and what
source words were established. Documentation evidence and acquisition records
are separate domain objects because they answer different questions.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator
from pydantic import Field as PydanticField
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


class MaterialIdentity(_ProvenanceModel):
    """Raw identity of one acquired or corroborating source artifact."""

    filename: str
    byte_count: int
    sha256: Sha256


class AcquisitionRecord(_ProvenanceModel):
    """RivRetrieve's record of how it came to hold source material."""

    acquisition_id: str
    method: Literal[
        "http_campaign",
        "http_request",
        "repository_recovery",
        "runtime_http_request",
        "corroborating_receipt",
    ]
    instant_type: (
        Literal[
            "retrieval",
            "retrieval_interval",
            "provenance_lower_bound",
            "corroborating_receipt",
            "runtime",
        ]
        | None
    ) = None
    description: str
    requested_from: tuple[str, ...]
    retrieved_at_start: datetime | None = None
    retrieved_at_end: datetime | None = None
    recording_ids: tuple[str, ...] = ()
    material: MaterialIdentity | None = None

    @model_validator(mode="after")
    def _instant_semantics_are_explicit(self) -> Self:
        if self.instant_type is None:
            # Schema-v1 records written before instant semantics were explicit remain readable.
            return self
        if self.method == "runtime_http_request":
            if self.instant_type != "runtime" or self.retrieved_at_start is not None:
                raise ValueError("runtime acquisitions must use the runtime instant type without a fixed instant")
            return self
        if self.retrieved_at_start is None:
            raise ValueError("recorded acquisitions require a start instant")
        if self.instant_type == "runtime":
            raise ValueError("recorded acquisitions cannot use the runtime instant type")
        if self.method == "repository_recovery" and self.instant_type != "provenance_lower_bound":
            raise ValueError("repository recovery must name a provenance lower-bound instant")
        if self.method == "corroborating_receipt" and self.instant_type != "corroborating_receipt":
            raise ValueError("corroborating receipt must name a corroborating-receipt instant")
        return self


class PrivateStatementVerification(_ProvenanceModel):
    """Redacted digest-bound result of an external private-byte verification."""

    schema_version: Literal[1]
    statement_id: str
    original_email_sha256: Sha256
    original_email_byte_count: int
    workbook_sha256: Sha256
    workbook_byte_count: int
    verified: Literal[True]


class SourceStatement(_ProvenanceModel):
    """Exact source words plus an explicit mechanical-verification state."""

    kind: Literal["license", "citation", "terms", "access"]
    exact_text: str
    recording_id: str | None = None
    verification_status: Literal[
        "verified_public_recording",
        "verified_private_original",
        "unverified_private_original_required",
    ] = "verified_public_recording"
    private_verification: PrivateStatementVerification | None = PydanticField(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def _verification_reference_is_truthful(self) -> Self:
        if self.verification_status == "verified_public_recording":
            if self.recording_id is None or self.private_verification is not None:
                raise ValueError("verified public statements require only a public recording id")
        elif self.verification_status == "verified_private_original":
            if self.recording_id is not None or self.private_verification is None:
                raise ValueError("verified private statements require only a redacted private verification")
        elif self.recording_id is not None or self.private_verification is not None:
            raise ValueError("unverified private statements cannot claim a verification record")
        return self


class SourceRecord(_ProvenanceModel):
    """One issuing body, its operator, acquisition, and established words."""

    source_id: str
    issuer: str
    operator: str | None = None
    acquisitions: tuple[AcquisitionRecord, ...]
    evidence: tuple[EvidenceReference, ...] = ()
    statements: tuple[SourceStatement, ...] = ()


class ExternalFactReference(_ProvenanceModel):
    """Reference an attributed external fact, including a withheld source fact."""

    source_id: str
    fact: str


class Transformation(_ProvenanceModel):
    """Name a RivRetrieve-authored knowledge state and its external lineage."""

    name: str
    external_inputs: tuple[ExternalFactReference, ...]


class FactBinding(_ProvenanceModel):
    """Bind facts to an issuing source or a RivRetrieve-authored transformation."""

    fact_group: str
    facts: tuple[str, ...]
    source_id: str | None
    acquisition_id: str | None
    transformation: Transformation | None = PydanticField(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def _source_shape_is_coherent(self) -> Self:
        if (self.source_id is None) != (self.acquisition_id is None):
            raise ValueError("source_id and acquisition_id must both be present or both be absent")
        if self.source_id is None and (self.transformation is None or not self.transformation.external_inputs):
            raise ValueError("RivRetrieve-authored bindings require external fact references")
        return self


class WithheldFact(_ProvenanceModel):
    """Name a coherent source fact group excluded for absent acquisition provenance."""

    fact_group: str
    facts: tuple[str, ...]
    reason: Literal["no_acquisition_record_established"]
    source_id: str | None = PydanticField(default=None, exclude_if=lambda value: value is None)


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

    schema_version: Literal[2]
    provider_id: str
    native_table: NativeTableIdentity | None = None
    fact_universe: tuple[str, ...]
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
                if (
                    statement.verification_status == "verified_public_recording"
                    and statement.recording_id not in recording_ids
                ):
                    raise ValueError(f"source {record.source_id} statement references an unknown recording")
        if any(not record.acquisitions for record in self.source_records):
            raise ValueError("every source record must contain an acquisition")
        if not self.fact_universe or len(self.fact_universe) != len(set(self.fact_universe)):
            raise ValueError("fact universe must contain unique facts")
        if any(not binding.facts for binding in self.fact_bindings):
            raise ValueError("fact bindings must contain at least one fact")
        fact_groups = [binding.fact_group for binding in self.fact_bindings]
        if len(fact_groups) != len(set(fact_groups)):
            raise ValueError("fact group ids must be unique")
        bound_fact_list = [fact for binding in self.fact_bindings for fact in binding.facts]
        if len(bound_fact_list) != len(set(bound_fact_list)):
            raise ValueError("each fact may be bound only once")
        bound_facts = set(bound_fact_list)
        catalogue_prefixes = ("provider.", "product.", "station.", "station_product.")
        if self.native_table is None and any(fact.startswith(catalogue_prefixes) for fact in bound_facts):
            raise ValueError("catalogue facts cannot be bound without native-table identity")
        withheld_groups = [item.fact_group for item in self.withheld_facts]
        if len(withheld_groups) != len(set(withheld_groups)):
            raise ValueError("withheld fact group ids must be unique")
        if any(not item.facts for item in self.withheld_facts):
            raise ValueError("withheld fact groups must contain at least one fact")
        withheld_list = [fact for item in self.withheld_facts for fact in item.facts]
        if len(withheld_list) != len(set(withheld_list)):
            raise ValueError("each fact may be withheld only once")
        withheld = set(withheld_list)
        if overlap := bound_facts & withheld:
            raise ValueError(f"facts cannot be both bound and withheld: {sorted(overlap)!r}")
        universe = set(self.fact_universe)
        unknown_facts = (bound_facts | withheld) - universe
        if unknown_facts:
            raise ValueError(f"provenance accounts for undeclared facts: {sorted(unknown_facts)!r}")
        unaccounted = universe - bound_facts - withheld
        if unaccounted:
            raise ValueError(f"fact universe contains unaccounted facts: {sorted(unaccounted)!r}")
        binding_sources = {binding.source_id for binding in self.fact_bindings if binding.source_id is not None}
        withheld_sources = {item.source_id for item in self.withheld_facts if item.source_id is not None}
        unknown_sources = (binding_sources | withheld_sources) - set(source_ids)
        if unknown_sources:
            raise ValueError(f"facts reference unknown sources: {sorted(unknown_sources)!r}")
        unknown_acquisitions = {
            (binding.source_id, binding.acquisition_id)
            for binding in self.fact_bindings
            if binding.source_id is not None and (binding.source_id, binding.acquisition_id) not in acquisition_keys
        }
        if unknown_acquisitions:
            raise ValueError(f"fact bindings reference unknown acquisitions: {sorted(unknown_acquisitions)!r}")
        fact_sources = {
            (fact, binding.source_id)
            for binding in self.fact_bindings
            if binding.source_id is not None
            for fact in binding.facts
        } | {
            (fact, withheld_group.source_id)
            for withheld_group in self.withheld_facts
            if withheld_group.source_id is not None
            for fact in withheld_group.facts
        }
        for binding in self.fact_bindings:
            if binding.transformation is None:
                continue
            for reference in binding.transformation.external_inputs:
                if (reference.fact, reference.source_id) not in fact_sources:
                    raise ValueError(
                        f"transformation {binding.fact_group} references a dangling or misattributed fact: "
                        f"{reference.source_id}.{reference.fact}"
                    )
                if binding.source_id is not None and reference.source_id != binding.source_id:
                    raise ValueError(f"transformation {binding.fact_group} external facts must have the binding source")
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


def serialize_acquisition_provenance(provenance: AcquisitionProvenance) -> str:
    """Serialize provenance while preserving schema-v1 compatibility fields."""
    value = provenance.model_dump(mode="json")
    for source in value["source_records"]:
        for acquisition in source["acquisitions"]:
            if acquisition.get("instant_type") is None:
                acquisition.pop("instant_type", None)
            if acquisition.get("material") is None:
                acquisition.pop("material", None)
        for statement in source["statements"]:
            if statement.get("verification_status") == "verified_public_recording":
                statement.pop("verification_status", None)
    for binding in value["fact_bindings"]:
        if binding.get("transformation") is None:
            binding.pop("transformation", None)
    for withheld_group in value["withheld_facts"]:
        if withheld_group.get("source_id") is None:
            withheld_group.pop("source_id", None)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def verify_acquisition_provenance_statements(
    provenance: AcquisitionProvenance,
    recording_bytes: Mapping[str, bytes],
) -> None:
    """Verify every declared source statement against supplied recording bytes.

    Parameters
    ----------
    provenance
        Closed provenance document whose statements must be certified.
    recording_bytes
        Exact public recording bytes keyed by recording id.

    Raises
    ------
    FatalContractError
        If a statement recording is absent, changed, unreadable, or does not
        contain the exact named statement.
    """
    for source in provenance.source_records:
        references = {evidence.recording.recording_id: evidence.recording for evidence in source.evidence}
        for statement in source.statements:
            if statement.verification_status != "verified_public_recording":
                continue
            statement_name = f"{provenance.provider_id}.{statement.kind}"
            recording_id = statement.recording_id
            if recording_id is None:
                raise FatalContractError(f"{statement_name}: verified statement has no recording id")
            try:
                body = recording_bytes[recording_id]
            except KeyError as exc:
                raise FatalContractError(f"{statement_name}: recording {recording_id} bytes are absent") from exc
            recording = references[recording_id]
            verify_recorded_statement(
                recording_name=statement_name,
                body=body,
                expected_sha256=recording.sha256,
                media_type=recording.media_type,
                exact_text=statement.exact_text,
            )


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

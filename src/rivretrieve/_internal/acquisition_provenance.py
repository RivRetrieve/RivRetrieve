"""acquisition provenance : ProvenanceDocument → AcquisitionProvenance (pure).

The model records who issued facts, how RivRetrieve acquired them, and what
source words were established. Documentation evidence and acquisition records
are separate domain objects because they answer different questions.
"""

from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit  # noqa: TID251  # Structural parsing only; no network access.

from pydantic import BaseModel, ConfigDict, PositiveInt, StringConstraints, field_validator, model_validator
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


_PRIVATE_REDACTED_EVIDENCE_LOCATION = "private://grdc-bfg/correspondence"
_HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_TEMPLATE_TOKEN = re.compile(r"(?:\{[A-Za-z0-9_-]+\}|<[A-Za-z0-9_-]+>)")
_URI_PCHAR_ASCII = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~!$&'()*+,;=:@%")


def _validate_http_hostname(hostname: str) -> None:
    """Reject malformed HTTP host names while accepting DNS and IP authorities."""
    try:
        ipaddress.ip_address(hostname)
        return
    except ValueError:
        pass
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError("requested_from location has an invalid hostname") from error
    unqualified_hostname = ascii_hostname.removesuffix(".")
    labels = unqualified_hostname.split(".")
    if len(unqualified_hostname) > 253 or not labels or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise ValueError("requested_from location has an invalid hostname")


def _validate_uri_component(value: str, allowed_ascii: frozenset[str]) -> None:
    """Validate one path, query, or fragment while allowing complete template tokens."""
    without_templates = _TEMPLATE_TOKEN.sub("template", value)
    if any(ord(character) < 128 and character not in allowed_ascii for character in without_templates):
        raise ValueError("requested_from location contains malformed URI component characters")


def _validate_requested_location(location: str) -> str:
    """Return one valid public URL or the sole private redacted-evidence URI."""
    if not location or any(
        character.isspace() or unicodedata.category(character).startswith("C") for character in location
    ):
        raise ValueError("requested_from must contain only valid typed locations without whitespace or controls")
    if location == _PRIVATE_REDACTED_EVIDENCE_LOCATION:
        return location
    if _INVALID_PERCENT_ESCAPE.search(location):
        raise ValueError("requested_from location contains malformed percent escapes")
    try:
        parsed = urlsplit(location)
        port = parsed.port
    except ValueError as error:
        raise ValueError("requested_from location has a malformed authority or port") from error
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ValueError("requested_from locations must use HTTP, HTTPS, or the private redacted-evidence URI")
    if not parsed.netloc or parsed.hostname is None or parsed.username is not None or parsed.password is not None:
        raise ValueError("requested_from HTTP locations require a valid authority")
    if any(character in parsed.netloc for character in "{}<>"):
        raise ValueError("requested_from HTTP authority cannot be a template")
    if parsed.netloc.endswith(":"):
        raise ValueError("requested_from location has a malformed authority or port")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("requested_from location has a malformed authority or port")
    _validate_http_hostname(parsed.hostname)
    _validate_uri_component(parsed.path, _URI_PCHAR_ASCII | frozenset("/"))
    _validate_uri_component(parsed.query, _URI_PCHAR_ASCII | frozenset("/?"))
    _validate_uri_component(parsed.fragment, _URI_PCHAR_ASCII | frozenset("/?"))
    return location


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
    instant_type: Literal[
        "retrieval",
        "retrieval_interval",
        "provenance_lower_bound",
        "corroborating_receipt",
        "private_redacted_corroborating_receipt",
        "runtime",
    ]
    description: str
    requested_from: tuple[str, ...]

    @field_validator("description")
    @classmethod
    def _description_names_acquired_material(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("acquisition description must be non-empty")
        return value

    @field_validator("requested_from")
    @classmethod
    def _requested_from_names_locations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("requested_from must contain at least one valid typed location")
        for location in value:
            _validate_requested_location(location)
        return value

    retrieved_at_start: datetime | None = None
    retrieved_at_end: datetime | None = None
    recording_ids: tuple[str, ...] = ()
    material: MaterialIdentity | None = None

    @model_validator(mode="after")
    def _instant_semantics_are_explicit(self) -> Self:
        if self.method == "runtime_http_request":
            if (
                self.instant_type != "runtime"
                or self.retrieved_at_start is not None
                or self.retrieved_at_end is not None
            ):
                raise ValueError("runtime acquisitions must use the runtime instant type without a fixed instant")
            return self
        if self.instant_type == "private_redacted_corroborating_receipt":
            if (
                self.method != "corroborating_receipt"
                or self.retrieved_at_start is not None
                or self.retrieved_at_end is not None
            ):
                raise ValueError("private-redacted corroborating receipts must omit their exact instant")
            return self
        if self.retrieved_at_start is None:
            raise ValueError("recorded acquisitions require a start instant")
        if self.instant_type == "runtime":
            raise ValueError("recorded acquisitions cannot use the runtime instant type")
        if self.instant_type == "retrieval_interval" and self.retrieved_at_end is None:
            raise ValueError("retrieval intervals require an end instant")
        if self.instant_type != "retrieval_interval" and self.retrieved_at_end is not None:
            raise ValueError("only retrieval intervals may use an end instant")
        if self.method in {"http_campaign", "http_request"} and self.instant_type not in {
            "retrieval",
            "retrieval_interval",
        }:
            raise ValueError("HTTP acquisitions must use a retrieval instant or retrieval interval")
        if self.method == "repository_recovery" and self.instant_type != "provenance_lower_bound":
            raise ValueError("repository recovery must name a provenance lower-bound instant")
        if self.method == "corroborating_receipt" and self.instant_type != "corroborating_receipt":
            raise ValueError("corroborating receipt must name a corroborating-receipt instant")
        return self


class PrivateStatementVerification(_ProvenanceModel):
    """Redacted digest-bound result of an external private-byte verification."""

    schema_version: Literal[2]
    statement_id: str
    evidence_kind: Literal["forwarded_copy"]
    limitation: Literal["original_byte_identity_not_established"]
    evidence_sha256: Sha256
    evidence_byte_count: int
    workbook_sha256: Sha256
    workbook_byte_count: int
    statement_sha256: Sha256
    decoded_text_plain_occurrence_count: Literal[1]
    decoded_text_html_occurrence_count: Literal[1]
    verified: Literal[True]

    @model_validator(mode="after")
    def _forbids_original_identity_claims(self) -> Self:
        if self.evidence_kind != "forwarded_copy" or self.limitation != "original_byte_identity_not_established":
            raise ValueError("only forwarded-copy evidence without original byte identity is valid")
        return self


class SourceStatement(_ProvenanceModel):
    """Public source words or a redacted private mechanical-verification state."""

    kind: Literal["license", "citation", "terms", "access"]
    exact_text: str | None = PydanticField(default=None, exclude_if=lambda value: value is None)
    recording_id: str | None = None
    fact: str | None = PydanticField(default=None, exclude_if=lambda value: value is None)
    verification_status: Literal[
        "verified_public_recording",
        "verified_private_forwarded_copy",
        "unverified_private_evidence_required",
    ] = "verified_public_recording"
    private_verification: PrivateStatementVerification | None = PydanticField(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @field_validator("exact_text")
    @classmethod
    def _exact_text_is_nonblank_when_present(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("source statement exact_text must be non-empty when present")
        return value

    @model_validator(mode="after")
    def _verification_reference_is_truthful(self) -> Self:
        if self.verification_status == "verified_public_recording":
            if (
                self.exact_text is None
                or self.recording_id is None
                or self.fact is None
                or self.private_verification is not None
            ):
                raise ValueError(
                    "verified public statements require exact words, a public recording id, and a source fact"
                )
            if not self.fact.startswith("source."):
                raise ValueError("verified public statement facts must name source facts")
        elif self.verification_status == "verified_private_forwarded_copy":
            if (
                self.exact_text is not None
                or self.recording_id is not None
                or self.fact is not None
                or self.private_verification is None
            ):
                raise ValueError("verified private statements expose only a redacted private verification")
            if self.private_verification.evidence_kind != "forwarded_copy":
                raise ValueError("private verification status requires forwarded-copy evidence")
        elif (
            self.exact_text is not None
            or self.recording_id is not None
            or self.fact is not None
            or self.private_verification is not None
        ):
            raise ValueError("unverified private statements must be fully redacted")
        return self


class SourceRecord(_ProvenanceModel):
    """One issuing body, its operator, acquisition, and established words."""

    source_id: str
    issuer: str
    operator: str | None = None
    acquisitions: tuple[AcquisitionRecord, ...]
    evidence: tuple[EvidenceReference, ...] = ()
    statements: tuple[SourceStatement, ...] = ()

    @field_validator("issuer", "operator")
    @classmethod
    def _identity_names_are_stripped_and_nonblank(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("source issuer and operator must be stripped nonblank names")
        return value


def verified_source_terms(source_records: tuple[SourceRecord, ...]) -> dict[str, str]:
    """verified source terms : SourceRecords → VerbatimLicenseAndCitation (pure).

    Aggregate terms belong only to one issuer. Private verification does not
    make private words public, and different statements cannot be merged by guess.
    """
    if len({source.issuer for source in source_records}) != 1:
        return {}
    terms: dict[str, str] = {}
    for source in source_records:
        for statement in source.statements:
            if statement.kind not in ("license", "citation"):
                continue
            if statement.verification_status != "verified_public_recording":
                continue
            text = statement.exact_text
            if text is None:
                raise FatalContractError("Verified public source statement has no exact text")
            if statement.kind in terms and terms[statement.kind] != text:
                raise FatalContractError(f"Conflicting verified {statement.kind} statements for {source.issuer}")
            terms[statement.kind] = text
    return terms


class ExternalFactReference(_ProvenanceModel):
    """Reference an attributed external fact, including a withheld source fact."""

    source_id: str | None
    fact: str


class AbsenceMarkerValue(StrEnum):
    """Canonical carrier values that explicitly represent factual absence."""

    NULL = "null"
    UNKNOWN = "unknown"


class Transformation(_ProvenanceModel):
    """Name a RivRetrieve-authored output and its external lineage."""

    name: str
    kind: Literal["derived_value", "absence_marker", "authored_constant"] = PydanticField(
        default="derived_value", exclude_if=lambda value: value == "derived_value"
    )
    marker_value: AbsenceMarkerValue | None = PydanticField(default=None, exclude_if=lambda value: value is None)
    external_inputs: tuple[ExternalFactReference, ...]

    @model_validator(mode="after")
    def _marker_value_matches_transformation_kind(self) -> Self:
        if self.kind == "absence_marker" and self.marker_value is None:
            raise ValueError("absence-marker transformations must declare a marker value")
        if self.kind != "absence_marker" and self.marker_value is not None:
            raise ValueError("only absence-marker transformations may declare a marker value")
        if self.kind == "authored_constant":
            if self.external_inputs:
                raise ValueError("authored-constant transformations require zero external inputs")
        elif not self.external_inputs:
            raise ValueError("derived and absence-marker transformations require external inputs")
        return self


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
        if self.transformation is None:
            if self.source_id is None:
                raise ValueError("direct source bindings require a source acquisition")
            if any(not fact.startswith(("source.", "native.")) for fact in self.facts):
                raise ValueError("external direct bindings must name source or native facts")
            return self
        if self.source_id is not None:
            raise ValueError("derived bindings cannot attribute outputs to a source acquisition")
        if any(fact.startswith(("source.", "native.")) for fact in self.facts):
            raise ValueError("RivRetrieve transformations cannot produce source or native facts")
        return self


def _catalogue_fact_identity(fact: str) -> tuple[str, str, str | None] | None:
    """Extract a typed row identity from a row-scoped source fact name."""
    station_product = re.fullmatch(r"(?:source[.:])?station_product[.:]([^.:]+)[.:]([^.:]+)[.:].+", fact)
    if station_product is not None:
        return ("station_product", station_product.group(1), station_product.group(2))
    station = re.fullmatch(r"(?:source[.:])?station[.:]([^.:]+)[.:].+", fact)
    if station is not None:
        return ("station", station.group(1), None)
    return None


class CatalogueRowLocator(_ProvenanceModel):
    """Identify one canonical catalogue row removed with a withheld fact group."""

    carrier: Literal["station", "station_product"]
    station_id: str
    product_id: str | None = None

    @model_validator(mode="after")
    def _key_matches_carrier(self) -> Self:
        if self.carrier == "station" and self.product_id is not None:
            raise ValueError("station row locators cannot contain product_id")
        if self.carrier == "station_product" and self.product_id is None:
            raise ValueError("station-product row locators require product_id")
        return self


class WithheldFact(_ProvenanceModel):
    """Name a coherent source fact group excluded for absent acquisition provenance."""

    fact_group: str
    facts: tuple[str, ...]
    reason: Literal["no_acquisition_record_established"]
    source_id: str | None = PydanticField(default=None, exclude_if=lambda value: value is None)
    catalogue_rows: tuple[CatalogueRowLocator, ...] = PydanticField(default=(), exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def _catalogue_row_locator_matches_scoped_fact_identity(self) -> Self:
        scoped_identities = {
            identity for fact in self.facts if (identity := _catalogue_fact_identity(fact)) is not None
        }
        located_identities = {
            (locator.carrier, locator.station_id, locator.product_id) for locator in self.catalogue_rows
        }
        if len(located_identities) != len(self.catalogue_rows) or located_identities != scoped_identities:
            raise ValueError("catalogue row locators must correspond one-to-one with every scoped fact identity")
        return self


def verified_provider_terms(
    source_records: tuple[SourceRecord, ...],
    fact_bindings: tuple[FactBinding, ...],
    withheld_facts: tuple[WithheldFact, ...],
) -> dict[str, str]:
    """provider terms : SourceRecords × FactBindings × WithheldFacts → VerbatimLicenseAndCitation (pure).

    Canonical provider-field lineage selects the issuing service. Catalogue
    contributors do not acquire authority over that service's terms. Explicit
    absence markers and withheld fields retain their established absence.
    """
    terms: dict[str, str] = {}
    for kind in ("license", "citation"):
        fact = f"provider.{kind}"
        if any(fact in group.facts for group in withheld_facts):
            continue
        bindings = tuple(binding for binding in fact_bindings if fact in binding.facts)
        if not bindings:
            continue
        if len(bindings) != 1:
            raise FatalContractError(f"Multiple bindings for {fact}")
        transformation = bindings[0].transformation
        if transformation is None or transformation.kind != "derived_value":
            continue
        source_ids = {reference.source_id for reference in transformation.external_inputs}
        sources = tuple(source for source in source_records if source.source_id in source_ids)
        value = verified_source_terms(sources).get(kind)
        if value is not None:
            terms[kind] = value
    return terms


class SemanticDigest(_ProvenanceModel):
    """Named semantic digest that supplements, but never replaces, raw identity."""

    name: str
    sha256: Sha256


class NativeTableIdentity(_ProvenanceModel):
    """Immutable repository identity of a committed native build input."""

    repository_path: str
    revision: GitRevision
    sha256: Sha256
    byte_size: PositiveInt | None = PydanticField(default=None, exclude_if=lambda value: value is None)
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
        recording_id_list = [
            evidence.recording.recording_id for record in self.source_records for evidence in record.evidence
        ]
        if len(recording_id_list) != len(set(recording_id_list)):
            raise ValueError("recording ids must be unique across the provenance artifact")
        acquisition_keys: set[tuple[str, str]] = set()
        for record in self.source_records:
            issuer_recording_ids = {evidence.recording.recording_id for evidence in record.evidence}
            acquisition_ids = [acquisition.acquisition_id for acquisition in record.acquisitions]
            if len(acquisition_ids) != len(set(acquisition_ids)):
                raise ValueError(f"source {record.source_id} acquisition ids must be unique")
            acquisition_keys.update((record.source_id, acquisition_id) for acquisition_id in acquisition_ids)
            claimed_recording_ids = [
                recording_id for acquisition in record.acquisitions for recording_id in acquisition.recording_ids
            ]
            if len(claimed_recording_ids) != len(set(claimed_recording_ids)):
                raise ValueError(f"source {record.source_id} recordings may be claimed by only one acquisition")
            for acquisition in record.acquisitions:
                acquisition_recordings = set(acquisition.recording_ids)
                if not acquisition_recordings <= issuer_recording_ids:
                    raise ValueError(f"source {record.source_id} acquisition must reference issuer-local recordings")
                if (
                    acquisition.method != "runtime_http_request"
                    and acquisition.instant_type != "private_redacted_corroborating_receipt"
                    and acquisition.retrieved_at_start is None
                ):
                    raise ValueError(f"source {record.source_id} recorded acquisition has no retrieval instant")
            for statement in record.statements:
                if (
                    statement.verification_status == "verified_public_recording"
                    and statement.recording_id not in issuer_recording_ids
                ):
                    raise ValueError(f"source {record.source_id} statement must reference an issuer-local recording")
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
        if self.native_table is None:
            non_authored_catalogue_facts = {
                fact
                for binding in self.fact_bindings
                if binding.transformation is None or binding.transformation.kind != "authored_constant"
                for fact in binding.facts
                if fact.startswith(catalogue_prefixes)
            }
            if non_authored_catalogue_facts:
                raise ValueError("catalogue facts cannot be bound without native-table identity")
        withheld_groups = [item.fact_group for item in self.withheld_facts]
        if len(withheld_groups) != len(set(withheld_groups)):
            raise ValueError("withheld fact group ids must be unique")
        if any(not item.facts for item in self.withheld_facts):
            raise ValueError("withheld fact groups must contain at least one fact")
        withheld_list = [fact for item in self.withheld_facts for fact in item.facts]
        if len(withheld_list) != len(set(withheld_list)):
            raise ValueError("each fact may be withheld only once")
        row_locators = [locator for item in self.withheld_facts for locator in item.catalogue_rows]
        row_locator_keys = [(locator.carrier, locator.station_id, locator.product_id) for locator in row_locators]
        if len(row_locator_keys) != len(set(row_locator_keys)):
            raise ValueError("each catalogue row may be withheld only once")
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
        acquisitions_by_key = {
            (record.source_id, acquisition.acquisition_id): acquisition
            for record in self.source_records
            for acquisition in record.acquisitions
        }
        direct_fact_acquisitions = {
            (fact, binding.source_id): binding.acquisition_id
            for binding in self.fact_bindings
            if binding.transformation is None
            for fact in binding.facts
        }
        for record in self.source_records:
            for statement in record.statements:
                if statement.verification_status != "verified_public_recording":
                    continue
                if statement.fact is None:  # pragma: no cover - rejected by SourceStatement
                    raise AssertionError("verified public statement has no source fact")
                acquisition_id = direct_fact_acquisitions.get((statement.fact, record.source_id))
                acquisition = (
                    acquisitions_by_key.get((record.source_id, acquisition_id)) if acquisition_id is not None else None
                )
                if acquisition is None or statement.recording_id not in acquisition.recording_ids:
                    raise ValueError(
                        f"source {record.source_id} statement recording must be claimed by its fact acquisition"
                    )
                recording = next(
                    evidence.recording
                    for evidence in record.evidence
                    if evidence.recording.recording_id == statement.recording_id
                )
                if (
                    acquisition.method != "http_request"
                    or acquisition.instant_type != "retrieval"
                    or acquisition.retrieved_at_start != recording.retrieved_at
                    or acquisition.retrieved_at_end is not None
                    or acquisition.requested_from != (recording.source_url,)
                ):
                    raise ValueError(
                        f"source {record.source_id} statement acquisition must match its exact recording URL and instant"
                    )
        runtime_observation_facts = {
            "source.observation.request",
            "source.observation.response",
            "source.observation.value",
            "source.observation.quality",
        }
        for binding in self.fact_bindings:
            if binding.source_id is None:
                continue
            if binding.acquisition_id is None:  # pragma: no cover - rejected by FactBinding
                raise AssertionError("direct binding has no acquisition id")
            acquisition = acquisitions_by_key[(binding.source_id, binding.acquisition_id)]
            if acquisition.instant_type == "runtime" or acquisition.method == "runtime_http_request":
                invalid_runtime_facts = {
                    fact
                    for fact in binding.facts
                    if not (
                        fact in runtime_observation_facts
                        or fact.startswith("source.observation")
                        or (fact.startswith("source.station:") and ".observation." in fact)
                    )
                }
                if invalid_runtime_facts:
                    raise ValueError("runtime acquisitions may bind only runtime observation source facts")
        fact_producers = {
            (fact, binding.source_id if binding.transformation is None else None): index
            for index, binding in enumerate(self.fact_bindings)
            for fact in binding.facts
        }
        withheld_fact_keys = {
            (fact, withheld_group.source_id) for withheld_group in self.withheld_facts for fact in withheld_group.facts
        }
        referenceable_facts = set(fact_producers) | withheld_fact_keys
        lineage_edges: dict[int, set[int]] = {index: set() for index in range(len(self.fact_bindings))}
        for index, binding in enumerate(self.fact_bindings):
            if binding.transformation is None:
                continue
            if binding.transformation.kind == "authored_constant":
                allowed_authored_facts = {
                    "provider.provider_id",
                    "provider.name",
                    "provider.live_stations",
                    "provider.live_products",
                    "provider.live_station_products",
                    "provider.bulk_observations",
                    "provider.catalogue_version",
                    "product.provider_id",
                    "product.product_id",
                    "product.observed_property",
                    "product.frequency",
                    "product.statistic",
                    "product.period_type",
                    "product.period_anchor",
                    "product.unit",
                    "product.native_id",
                }
                if not set(binding.facts) <= allowed_authored_facts:
                    raise ValueError(
                        "authored-constant transformations may produce only explicit canonical code-defined outputs"
                    )
            withheld_inputs = {
                (reference.fact, reference.source_id)
                for reference in binding.transformation.external_inputs
                if (reference.fact, reference.source_id) in withheld_fact_keys
            }
            if withheld_inputs:
                absence_marker_facts = {"provider.license", "provider.citation", "station.crs"}
                if binding.transformation.kind != "absence_marker" or not set(binding.facts) <= absence_marker_facts:
                    raise ValueError("withheld external inputs may only produce absence markers")
            if binding.transformation.kind == "absence_marker":
                allowed_marker_facts = {
                    AbsenceMarkerValue.NULL: {"provider.license", "provider.citation"},
                    AbsenceMarkerValue.UNKNOWN: {"station.crs"},
                }
                marker_value = binding.transformation.marker_value
                if marker_value is None or not set(binding.facts) <= allowed_marker_facts[marker_value]:
                    raise ValueError("absence-marker value is incompatible with its output facts")
            for reference in binding.transformation.external_inputs:
                reference_key = (reference.fact, reference.source_id)
                if reference_key not in referenceable_facts:
                    raise ValueError(
                        f"transformation {binding.fact_group} references a dangling or misattributed fact: "
                        f"{reference.source_id}.{reference.fact}"
                    )
                producer = fact_producers.get(reference_key)
                if producer == index:
                    raise ValueError(f"transformation {binding.fact_group} cannot reference its own output")
                if producer is not None:
                    lineage_edges[index].add(producer)

        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(index: int) -> None:
            if index in visiting:
                raise ValueError("transformation lineage contains a cycle")
            if index in visited:
                return
            visiting.add(index)
            for dependency in lineage_edges[index]:
                visit(dependency)
            visiting.remove(index)
            visited.add(index)

        for index in lineage_edges:
            visit(index)

        runtime_producers = {
            index
            for index, binding in enumerate(self.fact_bindings)
            if binding.transformation is None
            and binding.source_id is not None
            and binding.acquisition_id is not None
            and (
                acquisitions_by_key[(binding.source_id, binding.acquisition_id)].instant_type == "runtime"
                or acquisitions_by_key[(binding.source_id, binding.acquisition_id)].method == "runtime_http_request"
            )
        }
        runtime_lineage_cache: dict[int, bool] = {}

        def has_runtime_ancestor(index: int) -> bool:
            if index not in runtime_lineage_cache:
                runtime_lineage_cache[index] = index in runtime_producers or any(
                    has_runtime_ancestor(dependency) for dependency in lineage_edges[index]
                )
            return runtime_lineage_cache[index]

        packaged_prefixes = ("provider.", "product.", "station.", "station_product.")
        for index, binding in enumerate(self.fact_bindings):
            if any(fact.startswith(packaged_prefixes) for fact in binding.facts) and has_runtime_ancestor(index):
                raise ValueError(f"packaged fact binding {binding.fact_group} has a runtime acquisition ancestor")
        return self


def complete_transformed_fact_universe(
    provenance: AcquisitionProvenance,
    required_facts: tuple[str, ...],
    *,
    transformation: Transformation,
    fact_group: str = "canonical_catalogue_carrier",
) -> AcquisitionProvenance:
    """Account for missing canonical carrier facts as RivRetrieve transforms.

    Parameters
    ----------
    provenance
        Provider provenance whose provider-specific facts are already closed.
    required_facts
        Canonical carrier facts that every packaged catalogue must declare.
    transformation
        Named RivRetrieve computation and its external inputs.

    Returns
    -------
    AcquisitionProvenance
        A newly validated document with every missing carrier fact bound.
    """
    required = set(required_facts)
    carrier_prefixes = {fact.partition(".")[0] for fact in required_facts}

    def reserve_source_fact(fact: str) -> str:
        prefix, separator, _ = fact.partition(".")
        if separator and prefix in carrier_prefixes and fact not in required:
            return f"source.{fact}"
        return fact

    payload = provenance.model_dump(mode="python")
    payload["fact_universe"] = tuple(reserve_source_fact(fact) for fact in provenance.fact_universe)
    payload["fact_bindings"] = tuple(
        {
            **binding,
            "facts": tuple(reserve_source_fact(fact) for fact in binding["facts"]),
            "transformation": (
                {
                    **binding["transformation"],
                    "external_inputs": tuple(
                        {**reference, "fact": reserve_source_fact(reference["fact"])}
                        for reference in binding["transformation"]["external_inputs"]
                    ),
                }
                if binding.get("transformation") is not None
                else None
            ),
        }
        for binding in payload["fact_bindings"]
    )
    payload["withheld_facts"] = tuple(
        {**withheld, "facts": tuple(reserve_source_fact(fact) for fact in withheld["facts"])}
        for withheld in payload["withheld_facts"]
    )
    normalized = AcquisitionProvenance.model_validate(payload)
    accounted = {fact for binding in normalized.fact_bindings for fact in binding.facts} | {
        fact for item in normalized.withheld_facts for fact in item.facts
    }
    missing = tuple(fact for fact in required_facts if fact not in accounted)
    if not missing:
        return normalized
    payload = normalized.model_dump(mode="python")
    payload["fact_universe"] = (*normalized.fact_universe, *missing)
    payload["fact_bindings"] = (
        *normalized.fact_bindings,
        FactBinding(
            fact_group=fact_group,
            facts=missing,
            source_id=None,
            acquisition_id=None,
            transformation=transformation,
        ),
    )
    return AcquisitionProvenance.model_validate(payload)


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
    """Serialize closed schema-v2 acquisition provenance deterministically."""
    value = provenance.model_dump(mode="json")
    for source in value["source_records"]:
        for acquisition in source["acquisitions"]:
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


def verify_provenance_recordings(
    provenance: AcquisitionProvenance,
    repository_root: Path,
) -> None:
    """Verify every public recording and exact statement in a provenance document.

    Parameters
    ----------
    provenance
        Closed provenance document whose public evidence must be checked.
    repository_root
        Repository root containing each declared relative recording path.

    Raises
    ------
    FatalContractError
        If a declared recording cannot be read, its raw digest differs, or an
        exact statement is absent from its recorded bytes.
    """
    recordings = {
        evidence.recording.recording_id: evidence.recording
        for source in provenance.source_records
        for evidence in source.evidence
    }
    bodies: dict[str, bytes] = {}
    for recording_id, recording in recordings.items():
        path = repository_root / recording.repository_path
        try:
            body = path.read_bytes()
        except OSError as exc:
            raise FatalContractError(f"source recording {recording_id} cannot be read: {path}") from exc
        observed = hashlib.sha256(body).hexdigest()
        if observed != recording.sha256:
            raise FatalContractError(
                f"source recording {recording_id} digest mismatch: expected {recording.sha256}, observed {observed}"
            )
        bodies[recording_id] = body
    verify_acquisition_provenance_statements(provenance, bodies)


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
            if recording_id is None or statement.exact_text is None:
                raise FatalContractError(f"{statement_name}: verified statement has no recording id or exact words")
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
    normalized_quotation = _normalize_source_text(exact_text)
    if not normalized_quotation:
        raise FatalContractError(f"source recording {recording_name}: quotation must be non-empty")
    if normalized_quotation not in normalized_page:
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

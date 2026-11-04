"""catalogue evidence : EvidenceHeader × EvidenceRelations → CatalogueEvidence (pure).

Bulk facts and lineage remain Polars relations. Only shared declarations are models.
"""

from __future__ import annotations

import io
import re
import weakref
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from typing import Literal, Self, cast

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_serializer, field_validator, model_validator

from rivretrieve._internal.acquisition_provenance import (
    AbsenceMarkerValue,
    AcquisitionProvenance,
    ArchiveMemberReference,
    CatalogueBuildInputs,
    CodeReference,
    EvidenceReference,
    NativeTableIdentity,
    RetainedInputUse,
    RetainedSupportUse,
    Sha256,
    SourceStatement,
    WithheldFact,
    _canonical_relative_path,
    _public_archive_reference,
    _retained_fact_names,
    _validate_requested_location,
    absence_marker_accepts_fact,
    validate_build_input_code_references,
    validate_build_input_facts,
)

EVIDENCE_FILENAMES = {
    name: f"provenance_{name}.parquet"
    for name in ("facts", "acquisitions", "bindings", "binding_facts", "external_inputs")
}
EVIDENCE_SCHEMAS = {
    "facts": pl.Schema(
        {
            "fact_id": pl.UInt32,
            "name": pl.String,
            "carrier": pl.String,
            "station_id": pl.String,
            "product_id": pl.String,
            "locator_role": pl.String,
        }
    ),
    "acquisitions": pl.Schema(
        {
            "acquisition_key": pl.UInt32,
            "source_ordinal": pl.UInt32,
            "acquisition_ordinal": pl.UInt32,
            "acquisition_id": pl.String,
            "method": pl.String,
            "instant_type": pl.String,
            "description_id": pl.UInt32,
            "requested_from": pl.List(pl.String),
            "retrieved_at_start": pl.String,
            "retrieved_at_end": pl.String,
            "recording_ids": pl.List(pl.String),
            "material_filename": pl.String,
            "material_sha256": pl.String,
            "material_byte_count": pl.Int64,
        }
    ),
    "bindings": pl.Schema(
        {
            "binding_id": pl.UInt32,
            "fact_group": pl.String,
            "source_ordinal": pl.UInt32,
            "acquisition_key": pl.UInt32,
            "transformation_id": pl.UInt32,
        }
    ),
    "binding_facts": pl.Schema({"binding_id": pl.UInt32, "position": pl.UInt32, "fact_id": pl.UInt32}),
    "external_inputs": pl.Schema(
        {"binding_id": pl.UInt32, "position": pl.UInt32, "source_ordinal": pl.UInt32, "fact_id": pl.UInt32}
    ),
}
_NULLABLE = {
    "facts": {"carrier", "station_id", "product_id", "locator_role"},
    "acquisitions": {
        "retrieved_at_start",
        "retrieved_at_end",
        "material_filename",
        "material_sha256",
        "material_byte_count",
    },
    "bindings": {"source_ordinal", "acquisition_key", "transformation_id"},
    "binding_facts": set(),
    "external_inputs": {"source_ordinal"},
}


class _EvidenceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _RetainedSupportEncoding(_EvidenceModel):
    reference: int = Field(strict=True, ge=0)
    verifier: int = Field(strict=True, ge=0)
    facts: tuple[str, ...]
    verification_kind: Literal["full_positive"]
    member_selector: str | None = None


class _BuildInputsEncoding(_EvidenceModel):
    """Normalized-header encoding; the build/CLI model remains uninterned."""

    encoding_version: Literal[1]
    build: CodeReference
    declarations: tuple[CodeReference, ...]
    inputs: tuple[RetainedInputUse, ...]
    support_references: tuple[ArchiveMemberReference, ...]
    support_verifiers: tuple[CodeReference, ...]
    support: tuple[_RetainedSupportEncoding, ...]

    @field_validator("encoding_version", mode="before")
    @classmethod
    def _version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("build input encoding_version must be an integer")
        return value

    @model_validator(mode="after")
    def _pools(self) -> Self:
        for pool, indices in (
            (self.support_references, [edge.reference for edge in self.support]),
            (self.support_verifiers, [edge.verifier for edge in self.support]),
        ):
            if len(pool) != len(set(pool)):
                raise ValueError("support identity pools must contain unique exact identities")
            if set(indices) != set(range(len(pool))):
                raise ValueError("support identity pool references must resolve and use every pool member")
        return self


def _encode_build_inputs(value: CatalogueBuildInputs) -> _BuildInputsEncoding:
    references: dict[ArchiveMemberReference, int] = {}
    verifiers: dict[CodeReference, int] = {}
    support = tuple(
        _RetainedSupportEncoding(
            reference=references.setdefault(item.reference, len(references)),
            verifier=verifiers.setdefault(item.verifier, len(verifiers)),
            facts=item.facts,
            verification_kind=item.verification_kind,
            member_selector=item.member_selector,
        )
        for item in value.support
    )
    return _BuildInputsEncoding(
        encoding_version=1,
        build=value.build,
        declarations=value.declarations,
        inputs=value.inputs,
        support_references=tuple(references),
        support_verifiers=tuple(verifiers),
        support=support,
    )


def _decode_build_inputs(value: object) -> CatalogueBuildInputs:
    encoded = _BuildInputsEncoding.model_validate(value)
    refs = encoded.support_references
    verifiers = encoded.support_verifiers
    try:
        for ref in refs:
            _public_archive_reference(ref)
        validated_facts: set[tuple[str, ...]] = set()
        support: list[RetainedSupportUse] = []
        for edge in encoded.support:
            facts = edge.facts
            if facts not in validated_facts:
                _retained_fact_names(facts)
                validated_facts.add(facts)
            selector = edge.member_selector
            if selector is not None:
                _canonical_relative_path(selector)
            support.append(
                RetainedSupportUse.model_construct(
                    reference=refs[edge.reference],
                    verifier=verifiers[edge.verifier],
                    facts=facts,
                    verification_kind=edge.verification_kind,
                    member_selector=selector,
                )
            )
    except ValueError:
        support = [
            RetainedSupportUse(
                reference=refs[edge.reference],
                verifier=verifiers[edge.verifier],
                facts=edge.facts,
                verification_kind=edge.verification_kind,
                member_selector=edge.member_selector,
            )
            for edge in encoded.support
        ]
    return CatalogueBuildInputs(
        build=encoded.build,
        declarations=encoded.declarations,
        inputs=encoded.inputs,
        support=tuple(support),
    )


class IssuingSource(_EvidenceModel):
    """An issuing body and its exact established evidence and words."""

    source_id: str
    issuer: str
    operator: str | None = None
    evidence: tuple[EvidenceReference, ...] = ()
    statements: tuple[SourceStatement, ...] = ()

    @field_validator("issuer", "operator")
    @classmethod
    def _names(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("source issuer and operator must be stripped nonblank names")
        return value


class TransformationDeclaration(_EvidenceModel):
    """Shared computation identity, without any union of its individual inputs."""

    name: str
    kind: Literal["derived_value", "absence_marker", "authored_constant"]
    marker_value: AbsenceMarkerValue | None = None
    executable: CodeReference | None = Field(default=None, exclude_if=lambda value: value is None)
    declaration: CodeReference | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def _marker(self) -> Self:
        if (self.kind == "absence_marker") != (self.marker_value is not None):
            raise ValueError("marker value must match transformation kind")
        return self


class RowLocatorRequirement(_EvidenceModel):
    """A row role required for every actual canonical key of one carrier."""

    carrier: Literal["station", "station_product"]
    role: str = Field(min_length=1)


_VALIDATED_FILE_IDENTITIES: dict[int, weakref.ref[EvidenceFileIdentity]] = {}
_VALIDATED_HEADERS: dict[int, tuple[weakref.ref[EvidenceHeader], tuple[tuple[str, int], ...]]] = {}
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")


def _mark_validated_file_identity(identity: EvidenceFileIdentity) -> None:
    obj_id = id(identity)
    _VALIDATED_FILE_IDENTITIES[obj_id] = weakref.ref(
        identity, lambda _ref, key=obj_id: _VALIDATED_FILE_IDENTITIES.pop(key, None)
    )


def _mark_validated_header(header: EvidenceHeader) -> None:
    obj_id = id(header)
    files_snapshot = tuple((k, id(v)) for k, v in header.files.items())
    _VALIDATED_HEADERS[obj_id] = (
        weakref.ref(header, lambda _ref, key=obj_id: _VALIDATED_HEADERS.pop(key, None)),
        files_snapshot,
    )


def _ensure_validated_header(header: EvidenceHeader) -> EvidenceHeader:
    entry = _VALIDATED_HEADERS.get(id(header))
    if entry is not None:
        ref, files_snapshot = entry
        if (
            ref() is header
            and tuple((k, id(v)) for k, v in header.files.items()) == files_snapshot
            and all(
                (f_ref := _VALIDATED_FILE_IDENTITIES.get(v_id)) is not None and f_ref() is header.files[k]
                for k, v_id in files_snapshot
            )
        ):
            return header
    return EvidenceHeader.model_validate(header.model_dump(mode="json"))


class EvidenceFileIdentity(_EvidenceModel):
    """Identity of an exact public evidence file, not authority over arbitrary paths."""

    path: str
    sha256: Sha256
    byte_count: int = Field(strict=True, gt=0)
    row_count: int = Field(strict=True, ge=0)
    schema_version: Literal[3] = 3

    @model_validator(mode="after")
    def _track_validated(self) -> Self:
        _mark_validated_file_identity(self)
        return self


class EvidenceHeader(_EvidenceModel):
    """Versioned source declarations and identities of the five public relations."""

    schema_version: Literal[3]
    provider_id: str
    native_table: NativeTableIdentity | None = None
    build_inputs: CatalogueBuildInputs | None = Field(default=None, exclude_if=lambda value: value is None)
    source_records: tuple[IssuingSource, ...]
    descriptions: tuple[str, ...]
    transformations: tuple[TransformationDeclaration, ...]
    withheld_facts: tuple[WithheldFact, ...] = ()
    row_locator_requirements: tuple[RowLocatorRequirement, ...] = ()
    files: dict[str, EvidenceFileIdentity]

    @field_validator("build_inputs", mode="before", json_schema_input_type=_BuildInputsEncoding | None)
    @classmethod
    def _build_inputs_value(cls, value: object, info: ValidationInfo) -> CatalogueBuildInputs | None:
        if value is None:
            return None
        if isinstance(value, dict) and "encoding_version" in value:
            return _decode_build_inputs(value)
        if info.mode == "json":
            raise ValueError("normalized build inputs require an explicit encoding_version")
        logical = value if isinstance(value, CatalogueBuildInputs) else CatalogueBuildInputs.model_validate(value)
        # Revalidate pooled values once, then share those typed identities across
        # all support edges. Never expand identities during normalized decoding.
        return _decode_build_inputs(_encode_build_inputs(logical).model_dump(mode="python"))

    @field_serializer("build_inputs", when_used="json")
    def _serialize_build_inputs(self, value: CatalogueBuildInputs | None) -> _BuildInputsEncoding | None:
        return _encode_build_inputs(value) if value is not None else None

    @model_validator(mode="after")
    def _identities(self) -> Self:
        if set(self.files) != set(EVIDENCE_FILENAMES.values()):
            raise ValueError("evidence files must name exactly the five fixed basenames")
        if any(key != identity.path for key, identity in self.files.items()):
            raise ValueError("evidence file path must equal its fixed basename")
        if len(set(self.descriptions)) != len(self.descriptions) or any(not text.strip() for text in self.descriptions):
            raise ValueError("descriptions must be unique nonblank exact strings")
        for transformation in self.transformations:
            validate_build_input_code_references(
                self.build_inputs, transformation.executable, transformation.declaration
            )
        if len(set(self.transformations)) != len(self.transformations):
            raise ValueError("transformation declarations must be unique")
        if len(set(self.row_locator_requirements)) != len(self.row_locator_requirements):
            raise ValueError("row locator requirements must be unique")
        _mark_validated_header(self)
        return self


class CatalogueEvidence(_EvidenceModel):
    """Validated catalogue evidence in normalized Polars relations.

    Attributes
    ----------
    header : EvidenceHeader
        Versioned source declarations, exact terms, acquisition descriptions,
        transformations, withheld facts and identities of the five relations.
    facts : polars.DataFrame
        Fact identities and station/product locators.
    acquisitions : polars.DataFrame
        Source-local acquisition identities, methods, times and recordings.
    bindings : polars.DataFrame
        Links between output groups, sources, acquisitions and transformations.
    binding_facts : polars.DataFrame
        Ordered fact membership for each binding.
    external_inputs : polars.DataFrame
        Exact ordered input facts for transformations. JSON serialization uses
        one array per physical column and is explicit, not part of discovery.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)
    header: EvidenceHeader
    facts: pl.DataFrame = Field(repr=False)
    acquisitions: pl.DataFrame = Field(repr=False)
    bindings: pl.DataFrame = Field(repr=False)
    binding_facts: pl.DataFrame = Field(repr=False)
    external_inputs: pl.DataFrame = Field(repr=False)

    @field_validator("header", mode="before")
    @classmethod
    def _header_value(cls, value: object) -> object:
        if isinstance(value, EvidenceHeader):
            return _ensure_validated_header(value)
        return value

    @field_validator(*EVIDENCE_SCHEMAS, mode="before")
    @classmethod
    def _columns(cls, value: object, info: ValidationInfo) -> pl.DataFrame:
        name = info.field_name
        assert name is not None
        schema = EVIDENCE_SCHEMAS[name]
        nullable_cols = _NULLABLE[name]
        if isinstance(value, pl.DataFrame):
            frame = value
        elif info.mode == "json" and isinstance(value, dict):
            if list(value) != list(schema) or any(not isinstance(column, list) for column in value.values()):
                raise ValueError(f"{name} requires exact ordered column arrays")
            columns = cast(dict[str, list], value)
            if len({len(column) for column in columns.values()}) != 1:
                raise ValueError(f"{name} columns have unequal lengths")
            # Polars accepts booleans as integers; the JSON boundary must not.
            for column, dtype in schema.items():
                col_items = columns[column]
                is_nullable = column in nullable_cols
                if dtype in (pl.UInt32, pl.Int64):
                    ok = (
                        all(item is None or type(item) is int for item in col_items)
                        if is_nullable
                        else all(type(item) is int for item in col_items)
                    )
                    if not ok:
                        raise ValueError(f"{name}.{column} requires integer keys/counts")
                elif dtype == pl.String:
                    ok = (
                        all(item is None or isinstance(item, str) for item in col_items)
                        if is_nullable
                        else all(isinstance(item, str) for item in col_items)
                    )
                    if not ok:
                        raise ValueError(f"{name}.{column} requires strings")
                elif dtype == pl.List(pl.String):
                    for item in col_items:
                        if item is None:
                            continue
                        if not isinstance(item, list) or not all(isinstance(x, str) for x in item):
                            raise ValueError(f"{name}.{column} requires string arrays")
            try:
                frame = pl.DataFrame(value, schema=schema, strict=True)
            except (TypeError, ValueError, pl.exceptions.PolarsError) as error:
                raise ValueError(f"invalid {name} column arrays: {error}") from error
        else:
            raise ValueError(f"{name} requires an exact-schema DataFrame")
        if frame.schema != schema or frame.columns != list(schema):
            raise ValueError(f"{name} has invalid columns or dtypes")
        if any(frame[column].null_count() for column in schema if column not in nullable_cols):
            raise ValueError(f"{name} required columns contain null")
        return frame

    @field_serializer(*EVIDENCE_SCHEMAS, when_used="json")
    def _serialize_columns(self, frame: pl.DataFrame) -> dict[str, list]:
        return frame.to_dict(as_series=False)

    @model_validator(mode="after")
    def _closed(self) -> Self:
        _validate_relations(self)
        return self

    def __repr_args__(self):
        yield "provider_id", self.header.provider_id
        for name in EVIDENCE_SCHEMAS:
            yield name, getattr(self, name).shape


def encode_evidence_tables(frames: Mapping[str, pl.DataFrame]) -> dict[str, bytes]:
    """encode evidence tables : EvidenceRelations → EvidenceTableBytes (pure)."""
    if set(frames) != set(EVIDENCE_SCHEMAS):
        raise ValueError("exactly five evidence relations required")
    result = {}
    for name, filename in EVIDENCE_FILENAMES.items():
        buffer = io.BytesIO()
        frames[name].write_parquet(buffer, compression="zstd", statistics=True)
        result[filename] = buffer.getvalue()
    return result


def evidence_file_identities(
    frames: Mapping[str, pl.DataFrame], files: Mapping[str, bytes]
) -> dict[str, EvidenceFileIdentity]:
    """file identities : EvidenceRelations × EvidenceTableBytes → EvidenceFileIdentities (pure)."""
    return {
        filename: EvidenceFileIdentity(
            path=filename,
            sha256=sha256(files[filename]).hexdigest(),
            byte_count=len(files[filename]),
            row_count=frames[name].height,
        )
        for name, filename in EVIDENCE_FILENAMES.items()
    }


def _contiguous(values: list[int], name: str) -> None:
    if values != list(range(len(values))):
        raise ValueError(f"{name} must be ordered unique zero-based contiguous ordinals")


def _validate_relations(e: CatalogueEvidence) -> None:
    h = e.header
    for name, filename in EVIDENCE_FILENAMES.items():
        if getattr(e, name).height != h.files[filename].row_count:
            raise ValueError(f"{name} row count disagrees with header")
    for name, key in (("facts", "fact_id"), ("acquisitions", "acquisition_key"), ("bindings", "binding_id")):
        _contiguous(getattr(e, name)[key].to_list(), key)
    names = e.facts["name"].to_list()
    num_names = len(names)
    if not names or len(set(names)) != num_names:
        raise ValueError("fact universe must contain unique facts")
    name_ids = {name: index for index, name in enumerate(names)}
    sources = h.source_records
    num_sources = len(sources)
    source_ids = [s.source_id for s in sources]
    if len(set(source_ids)) != num_sources:
        raise ValueError("source record ids must be unique")
    source_ordinals = {name: i for i, name in enumerate(source_ids)}
    recordings = [{ev.recording.recording_id: ev.recording for ev in s.evidence} for s in sources]
    recording_ids = [ev.recording.recording_id for s in sources for ev in s.evidence]
    if len(set(recording_ids)) != len(recording_ids):
        raise ValueError("recording ids must be unique across the provenance artifact")

    acq_cols = e.acquisitions.to_dict(as_series=False)
    acq_src_ord = acq_cols["source_ordinal"]
    acq_ord = acq_cols["acquisition_ordinal"]
    acq_id = acq_cols["acquisition_id"]
    acq_method = acq_cols["method"]
    acq_instant = acq_cols["instant_type"]
    acq_desc_id = acq_cols["description_id"]
    acq_req_from = acq_cols["requested_from"]
    acq_start = acq_cols["retrieved_at_start"]
    acq_end = acq_cols["retrieved_at_end"]
    acq_rec_ids = acq_cols["recording_ids"]
    acq_mat_fn = acq_cols["material_filename"]
    acq_mat_sha = acq_cols["material_sha256"]
    acq_mat_bytes = acq_cols["material_byte_count"]
    num_acquisitions = len(acq_src_ord)

    local_ordinals: dict[int, list[int]] = defaultdict(list)
    local_ids: set[tuple[int, str]] = set()
    claimed: set[tuple[int, str]] = set()
    used_descriptions: list[int] = []
    used_descriptions_set: set[int] = set()
    validated_locations: set[str] = set()
    num_descriptions = len(h.descriptions)
    for idx in range(num_acquisitions):
        s = acq_src_ord[idx]
        desc_id = acq_desc_id[idx]
        if s >= num_sources or desc_id >= num_descriptions:
            raise ValueError("acquisition source/description foreign key does not resolve")
        local_ordinals[s].append(acq_ord[idx])
        key = (s, acq_id[idx])
        if key in local_ids:
            raise ValueError("source acquisition ids must be unique")
        local_ids.add(key)
        if desc_id not in used_descriptions_set:
            used_descriptions_set.add(desc_id)
            used_descriptions.append(desc_id)
        _validate_acquisition_fields(
            acq_method[idx],
            acq_instant[idx],
            acq_req_from[idx],
            acq_rec_ids[idx],
            acq_start[idx],
            acq_end[idx],
            acq_mat_fn[idx],
            acq_mat_sha[idx],
            acq_mat_bytes[idx],
            validated_locations,
        )
        src_recordings = recordings[s]
        for rid in acq_rec_ids[idx]:
            if rid not in src_recordings:
                raise ValueError("acquisition must reference issuer-local recordings")
            if (s, rid) in claimed:
                raise ValueError("recordings may be claimed by only one acquisition")
            claimed.add((s, rid))
    pairs_order = list(zip(acq_src_ord, acq_ord, strict=True))
    if pairs_order != sorted(pairs_order):
        raise ValueError("acquisition keys disagree with source-local order")
    for s in range(num_sources):
        if not local_ordinals[s]:
            raise ValueError("every source record must contain an acquisition")
        _contiguous(local_ordinals[s], "source-local acquisition ordinal")
    _contiguous(used_descriptions, "description first occurrence")
    if len(used_descriptions) != num_descriptions:
        raise ValueError("unused description declaration")

    bind_cols = e.bindings.to_dict(as_series=False)
    bind_groups = bind_cols["fact_group"]
    bind_sources = bind_cols["source_ordinal"]
    bind_acqs = bind_cols["acquisition_key"]
    bind_transforms = bind_cols["transformation_id"]
    num_bindings = len(bind_groups)
    if len(set(bind_groups)) != num_bindings:
        raise ValueError("fact group ids must be unique")
    outputs: list[list[int]] = [[] for _ in range(num_bindings)]
    inputs: list[list[tuple[int | None, int]]] = [[] for _ in range(num_bindings)]
    producer: list[int] = [-1] * num_names
    bound_count = 0

    bf_cols = e.binding_facts.to_dict(as_series=False)
    prev_b = -1
    prev_pos = -1
    for b, position, fact in zip(bf_cols["binding_id"], bf_cols["position"], bf_cols["fact_id"], strict=True):
        if b >= num_bindings or fact >= num_names:
            raise ValueError("membership/input foreign keys or ordered positions are invalid")
        out_b = outputs[b]
        if position != len(out_b) or b < prev_b or (b == prev_b and position <= prev_pos):
            raise ValueError("membership/input foreign keys or ordered positions are invalid")
        prev_b = b
        prev_pos = position
        if producer[fact] != -1:
            raise ValueError("each fact may be bound only once")
        producer[fact] = b
        bound_count += 1
        out_b.append(fact)

    ei_cols = e.external_inputs.to_dict(as_series=False)
    prev_b = -1
    prev_pos = -1
    for b, position, source, fact in zip(
        ei_cols["binding_id"], ei_cols["position"], ei_cols["source_ordinal"], ei_cols["fact_id"], strict=True
    ):
        if b >= num_bindings or fact >= num_names:
            raise ValueError("membership/input foreign keys or ordered positions are invalid")
        in_b = inputs[b]
        if position != len(in_b) or b < prev_b or (b == prev_b and position <= prev_pos):
            raise ValueError("membership/input foreign keys or ordered positions are invalid")
        prev_b = b
        prev_pos = position
        if source is not None and source >= num_sources:
            raise ValueError("external input source foreign key does not resolve")
        in_b.append((source, fact))

    if h.build_inputs is not None:
        validate_build_input_facts(h.build_inputs, {names[idx] for idx, p in enumerate(producer) if p != -1})
    withheld: dict[int, int | None] = {}
    withheld_groups: set[str] = set()
    withheld_rows: set[tuple] = set()
    for group in h.withheld_facts:
        if group.fact_group in withheld_groups or not group.facts:
            raise ValueError("withheld groups must be unique and nonempty")
        withheld_groups.add(group.fact_group)
        if group.source_id is not None and group.source_id not in source_ordinals:
            raise ValueError("withheld facts reference unknown source")
        for locator in group.catalogue_rows:
            key = (locator.carrier, locator.station_id, locator.product_id)
            if key in withheld_rows:
                raise ValueError("each catalogue row may be withheld only once")
            withheld_rows.add(key)
        w_owner = source_ordinals[group.source_id] if group.source_id is not None else None
        for name in group.facts:
            fid = name_ids.get(name)
            if fid is None or fid in withheld or producer[fid] != -1:
                raise ValueError("withheld facts must be declared, unique and disjoint from bound facts")
            withheld[fid] = w_owner
    if bound_count + len(withheld) != num_names:
        unaccounted = [names[f] for f in range(num_names) if producer[f] == -1 and f not in withheld]
        raise ValueError(f"fact universe contains unaccounted facts: {sorted(unaccounted)!r}")

    edges: list[set[int]] = [set() for _ in range(num_bindings)]
    runtime: set[int] = set()
    used_transforms: list[int] = []
    used_transforms_set: set[int] = set()
    has_withheld = bool(withheld)
    has_native_table = h.native_table is not None
    transformations = h.transformations
    num_transforms = len(transformations)
    for b in range(num_bindings):
        out_ids = outputs[b]
        if not out_ids:
            raise ValueError("fact bindings must contain at least one fact")
        facts = [names[f] for f in out_ids]
        source = bind_sources[b]
        acquisition = bind_acqs[b]
        transformation = bind_transforms[b]
        in_b = inputs[b]
        if transformation is None:
            if source is None or acquisition is None or source >= num_sources or acquisition >= num_acquisitions:
                raise ValueError("direct source bindings require a source acquisition")
            if acq_src_ord[acquisition] != source:
                raise ValueError("binding acquisition belongs to another source")
            if in_b or any(not f.startswith(("source.", "native.")) for f in facts):
                raise ValueError("external direct bindings must name source or native facts without inputs")
            if acq_method[acquisition] == "runtime_http_request" or acq_instant[acquisition] == "runtime":
                runtime.add(b)
                if any(
                    not (
                        f.startswith("source.observation") or (f.startswith("source.station:") and ".observation." in f)
                    )
                    for f in facts
                ):
                    raise ValueError("runtime acquisitions may bind only runtime observation source facts")
        else:
            if source is not None or acquisition is not None or transformation >= num_transforms:
                raise ValueError("derived bindings cannot attribute outputs to a source acquisition")
            if any(f.startswith(("source.", "native.")) for f in facts):
                raise ValueError("RivRetrieve transformations cannot produce source or native facts")
            if transformation not in used_transforms_set:
                used_transforms_set.add(transformation)
                used_transforms.append(transformation)
            t = transformations[transformation]
            if (t.kind == "authored_constant") != (not in_b):
                raise ValueError("authored constants require zero inputs; other transforms require external inputs")
            _validate_transformation(t, facts, has_withheld and any(f in withheld for _, f in in_b))
            edges_b = edges[b]
            for input_source, fact in in_b:
                if has_withheld and fact in withheld:
                    owner = withheld[fact]
                else:
                    parent = producer[fact]
                    owner = bind_sources[parent]
                    edges_b.add(parent)
                if owner != input_source:
                    raise ValueError("transformation references a dangling or misattributed fact")
        if (
            not has_native_table
            and any(f.startswith(("provider.", "product.", "station.", "station_product.")) for f in facts)
            and (transformation is None or transformations[transformation].kind != "authored_constant")
        ):
            raise ValueError("catalogue facts cannot be bound without native-table identity")
    _contiguous(used_transforms, "transformation first occurrence")
    if len(used_transforms) != num_transforms:
        raise ValueError("unused transformation declaration")
    # Iterative postorder avoids both national objects and Python recursion limits.
    state = [0] * num_bindings
    runtime_ancestor = [False] * num_bindings
    has_runtime = bool(runtime)
    for start in range(num_bindings):
        if state[start] != 2:
            stack = [(start, False)]
            while stack:
                b, finishing = stack.pop()
                if finishing:
                    state[b] = 2
                    if has_runtime:
                        runtime_ancestor[b] = b in runtime or any(runtime_ancestor[x] for x in edges[b])
                    continue
                if state[b] == 2:
                    continue
                if state[b] == 1:
                    raise ValueError("transformation lineage contains a cycle")
                state[b] = 1
                stack.append((b, True))
                stack.extend((x, False) for x in edges[b])
        if (
            has_runtime
            and runtime_ancestor[start]
            and any(
                names[f].startswith(("provider.", "product.", "station.", "station_product.")) for f in outputs[start]
            )
        ):
            raise ValueError("packaged fact binding has a runtime acquisition ancestor")
    for s, source_rec in enumerate(sources):
        for statement in source_rec.statements:
            if statement.verification_status != "verified_public_recording":
                continue
            if statement.recording_id not in recordings[s]:
                raise ValueError("statement must reference an issuer-local recording")
            fact = name_ids.get(statement.fact)
            b = producer[fact] if fact is not None and producer[fact] != -1 else None
            if b is None or bind_sources[b] != s:
                raise ValueError("statement recording must be claimed by its fact acquisition")
            acq_idx = bind_acqs[b]
            if statement.recording_id not in acq_rec_ids[acq_idx]:
                raise ValueError("statement recording must be claimed by its fact acquisition")
            recording = recordings[s][statement.recording_id]
            if (
                acq_method[acq_idx] != "http_request"
                or acq_instant[acq_idx] != "retrieval"
                or _instant(acq_start[acq_idx]) != recording.retrieved_at
                or acq_end[acq_idx] is not None
                or acq_req_from[acq_idx] != [recording.source_url]
            ):
                raise ValueError("statement acquisition must match its exact recording URL and instant")
    _validate_locator_shapes(e.facts)


def _instant(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


_VALID_ACQ_METHODS = frozenset(
    {
        "http_campaign",
        "http_request",
        "repository_recovery",
        "runtime_http_request",
        "corroborating_receipt",
    }
)
_VALID_ACQ_INSTANTS = frozenset(
    {
        "retrieval",
        "retrieval_interval",
        "provenance_lower_bound",
        "corroborating_receipt",
        "private_redacted_corroborating_receipt",
        "runtime",
    }
)


def _validate_acquisition_fields(
    method: str,
    instant: str,
    requested_from: list[str],
    recording_ids: list[str],
    retrieved_at_start: str | None,
    retrieved_at_end: str | None,
    material_filename: str | None,
    material_sha256: str | None,
    material_byte_count: int | None,
    validated_locations: set[str],
) -> None:
    if method not in _VALID_ACQ_METHODS:
        raise ValueError("invalid acquisition method")
    if instant not in _VALID_ACQ_INSTANTS:
        raise ValueError("invalid acquisition instant type")
    if not requested_from:
        raise ValueError("requested_from must contain at least one valid typed location")
    for location in requested_from:
        if not isinstance(location, str):
            raise ValueError("requested_from has null/non-string member")
        if location not in validated_locations:
            _validate_requested_location(location)
            validated_locations.add(location)
    if not all(isinstance(r, str) for r in recording_ids):
        raise ValueError("recording_ids has null/non-string member")
    start, end = _instant(retrieved_at_start), _instant(retrieved_at_end)
    if method == "runtime_http_request":
        if instant != "runtime" or start is not None or end is not None:
            raise ValueError("runtime acquisitions must use runtime without a fixed instant")
    elif instant == "private_redacted_corroborating_receipt":
        if method != "corroborating_receipt" or start is not None or end is not None:
            raise ValueError("private-redacted corroborating receipts must omit their exact instant")
    else:
        if start is None or instant == "runtime":
            raise ValueError("recorded acquisitions require a start instant and cannot use runtime")
        if (instant == "retrieval_interval") != (end is not None):
            raise ValueError("only retrieval intervals require an end instant")
        if method in {"http_campaign", "http_request"} and instant not in {"retrieval", "retrieval_interval"}:
            raise ValueError("HTTP acquisitions must use a retrieval instant or retrieval interval")
        if method == "repository_recovery" and instant != "provenance_lower_bound":
            raise ValueError("repository recovery must name a provenance lower-bound instant")
        if method == "corroborating_receipt" and instant != "corroborating_receipt":
            raise ValueError("corroborating receipt must name a corroborating-receipt instant")
    if (material_filename is not None or material_sha256 is not None or material_byte_count is not None) and (
        material_filename is None
        or material_sha256 is None
        or material_byte_count is None
        or _SHA256_HEX_RE.fullmatch(material_sha256) is None
    ):
        raise ValueError("material requires filename, SHA-256 and integer byte count together")


_AUTHORED = {
    "provider." + x
    for x in (
        "provider_id",
        "name",
        "live_stations",
        "live_products",
        "live_station_products",
        "bulk_observations",
        "catalogue_version",
    )
} | {
    "product." + x
    for x in (
        "provider_id",
        "product_id",
        "observed_property",
        "frequency",
        "statistic",
        "period_type",
        "period_anchor",
        "unit",
        "native_id",
    )
}


def _validate_transformation(t: TransformationDeclaration, facts: list[str], withheld: bool) -> None:
    if t.kind == "authored_constant" and not set(facts) <= _AUTHORED:
        raise ValueError("authored-constant transformations may produce only explicit canonical code-defined outputs")
    if withheld and (
        t.kind != "absence_marker"
        or not all(any(absence_marker_accepts_fact(marker, fact) for marker in AbsenceMarkerValue) for fact in facts)
    ):
        raise ValueError("withheld external inputs may only produce absence markers")
    if t.kind == "absence_marker" and not all(absence_marker_accepts_fact(t.marker_value, fact) for fact in facts):
        raise ValueError("absence-marker value is incompatible with its output facts")


def _locator_names(carrier: str, station: str, product: str | None, role: str) -> tuple[str, str]:
    key = f"{carrier}:{station}" + (f":{product}" if product is not None else "")
    return f"{key}.{role}", f"source.{key}.{role}"


def _validate_locator_shapes(facts: pl.DataFrame) -> None:
    if facts.filter(
        pl.col("carrier").is_null()
        & (
            pl.col("station_id").is_not_null()
            | pl.col("product_id").is_not_null()
            | pl.col("locator_role").is_not_null()
        )
    ).height:
        raise ValueError("partial null row locator")
    non_null = facts.filter(pl.col("carrier").is_not_null())
    if non_null.is_empty():
        return
    seen: set[tuple[str, str, str | None, str]] = set()
    cols = non_null.to_dict(as_series=False)
    for name, carrier, station, product, role in zip(
        cols["name"], cols["carrier"], cols["station_id"], cols["product_id"], cols["locator_role"], strict=True
    ):
        if (
            carrier not in {"station", "station_product"}
            or station is None
            or not role
            or (carrier == "station_product") != (product is not None)
        ):
            raise ValueError("row locator does not match carrier")
        key = (carrier, station, product, role)
        if key in seen:
            raise ValueError("duplicate or swapped fact row locator")
        base = f"{carrier}:{station}:{product}.{role}" if product is not None else f"{carrier}:{station}.{role}"
        if name != base and name != f"source.{base}":
            raise ValueError("duplicate or swapped fact row locator")
        seen.add(key)


def validate_catalogue_locators(
    evidence: CatalogueEvidence, *, stations: pl.DataFrame, station_products: pl.DataFrame
) -> None:
    """validate locators : CatalogueEvidence × CanonicalRowKeys → None (pure)."""
    tables = {"station": stations, "station_product": station_products}
    for table in tables.values():
        if table.height and set(table["provider_id"].unique().to_list()) != {evidence.header.provider_id}:
            raise ValueError("locator canonical provider identity mismatch")
    actual_stations = {(sid,) for sid in stations["station_id"].to_list()}
    actual_sp = set(
        zip(station_products["station_id"].to_list(), station_products["product_id"].to_list(), strict=True)
    )
    actual: dict[str, set[tuple]] = {"station": actual_stations, "station_product": actual_sp}
    located: dict[tuple[str, str], set[tuple]] = defaultdict(set)
    non_null = evidence.facts.filter(pl.col("carrier").is_not_null())
    if non_null.height:
        cols = non_null.to_dict(as_series=False)
        for carrier, station, product, role in zip(
            cols["carrier"], cols["station_id"], cols["product_id"], cols["locator_role"], strict=True
        ):
            key = (station, product) if carrier == "station_product" else (station,)
            if key not in actual[carrier]:
                raise ValueError("row locator names an absent canonical row")
            located[(carrier, role)].add(key)
    names = set(evidence.facts["name"].to_list())
    availability_candidates = {
        key
        for key in actual_sp
        if f"station_product:{key[0]}:{key[1]}.availability" in names
        or f"source.station_product:{key[0]}:{key[1]}.availability" in names
    }
    if availability_candidates:
        requirement = RowLocatorRequirement(carrier="station_product", role="availability")
        if requirement not in evidence.header.row_locator_requirements:
            raise ValueError("availability facts require explicit row locator completeness")
        if located[("station_product", "availability")] != availability_candidates:
            raise ValueError("required row locators do not exactly cover established availability facts")
    for requirement in evidence.header.row_locator_requirements:
        if located[(requirement.carrier, requirement.role)] != actual[requirement.carrier]:
            raise ValueError("required row locators do not exactly cover canonical keys")


def normalize_provenance(
    provenance: AcquisitionProvenance,
    *,
    stations: pl.DataFrame,
    station_products: pl.DataFrame,
    row_locator_requirements: tuple[RowLocatorRequirement, ...] = (),
) -> CatalogueEvidence:
    """normalize provenance : AcquisitionProvenance × CanonicalRowKeys → CatalogueEvidence (pure build boundary)."""
    header, frames = _normalize_provenance_relations(
        provenance,
        stations=stations,
        station_products=station_products,
        row_locator_requirements=row_locator_requirements,
    )
    # The construction scope has returned: raw rows and temporary lookup indexes
    # no longer overlap the complete scientific evidence-closure validation.
    result = CatalogueEvidence(header=header, **frames)
    validate_catalogue_locators(result, stations=stations, station_products=station_products)
    return result


def _normalize_provenance_relations(
    provenance: AcquisitionProvenance,
    *,
    stations: pl.DataFrame,
    station_products: pl.DataFrame,
    row_locator_requirements: tuple[RowLocatorRequirement, ...],
) -> tuple[EvidenceHeader, dict[str, pl.DataFrame]]:
    """Build the header and bulk relations within one bounded temporary scope."""
    names = {name: i for i, name in enumerate(provenance.fact_universe)}
    locators: dict[int, tuple[str, str, str | None, str]] = {}
    requirements = list(row_locator_requirements)
    availability = RowLocatorRequirement(carrier="station_product", role="availability")
    candidates = requirements + ([] if availability in requirements else [availability])
    station_ids_list = stations["station_id"].to_list()
    sp_pairs_list = list(
        zip(station_products["station_id"].to_list(), station_products["product_id"].to_list(), strict=True)
    )
    for requirement in candidates:
        found = False
        role = requirement.role
        if requirement.carrier == "station":
            for station in station_ids_list:
                n1 = f"station:{station}.{role}"
                n2 = f"source.{n1}"
                in1 = n1 in names
                in2 = n2 in names
                if in1 and in2:
                    raise ValueError("multiple facts claim the same canonical row role")
                if in1 or in2:
                    locators[names[n1 if in1 else n2]] = ("station", station, None, role)
                    found = True
        else:
            for station, product in sp_pairs_list:
                n1 = f"station_product:{station}:{product}.{role}"
                n2 = f"source.{n1}"
                in1 = n1 in names
                in2 = n2 in names
                if in1 and in2:
                    raise ValueError("multiple facts claim the same canonical row role")
                if in1 or in2:
                    locators[names[n1 if in1 else n2]] = ("station_product", station, product, role)
                    found = True
        if found and requirement not in requirements:
            requirements.append(requirement)

    num_facts = len(names)
    f_carriers: list[str | None] = [None] * num_facts
    f_stations: list[str | None] = [None] * num_facts
    f_products: list[str | None] = [None] * num_facts
    f_roles: list[str | None] = [None] * num_facts
    for idx, (c_val, s_val, p_val, r_val) in locators.items():
        f_carriers[idx] = c_val
        f_stations[idx] = s_val
        f_products[idx] = p_val
        f_roles[idx] = r_val
    locators.clear()
    frames: dict[str, pl.DataFrame] = {
        "facts": pl.DataFrame(
            {
                "fact_id": list(range(num_facts)),
                "name": list(provenance.fact_universe),
                "carrier": f_carriers,
                "station_id": f_stations,
                "product_id": f_products,
                "locator_role": f_roles,
            },
            schema=EVIDENCE_SCHEMAS["facts"],
        )
    }
    del f_carriers, f_stations, f_products, f_roles

    sources = {source.source_id: i for i, source in enumerate(provenance.source_records)}
    descriptions: dict[str, int] = {}
    acquisitions: dict[tuple[str, str], int] = {}
    acq_rows = []
    for source in provenance.source_records:
        src_ord = sources[source.source_id]
        for ordinal, a in enumerate(source.acquisitions):
            key = len(acq_rows)
            acquisitions[(source.source_id, a.acquisition_id)] = key
            description_id = descriptions.setdefault(a.description, len(descriptions))
            material = (
                (a.material.filename, a.material.sha256, a.material.byte_count) if a.material else (None, None, None)
            )
            acq_rows.append(
                (
                    key,
                    src_ord,
                    ordinal,
                    a.acquisition_id,
                    a.method,
                    a.instant_type,
                    description_id,
                    list(a.requested_from),
                    a.retrieved_at_start.isoformat() if a.retrieved_at_start else None,
                    a.retrieved_at_end.isoformat() if a.retrieved_at_end else None,
                    list(a.recording_ids),
                    *material,
                )
            )
    frames["acquisitions"] = pl.DataFrame(acq_rows, schema=EVIDENCE_SCHEMAS["acquisitions"], orient="row")
    del acq_rows

    transformations: dict[TransformationDeclaration, int] = {}
    transform_cache: dict[tuple, int] = {}
    num_bindings = len(provenance.fact_bindings)
    b_ids = list(range(num_bindings))
    b_groups: list[str] = []
    b_sources: list[int | None] = []
    b_acqs: list[int | None] = []
    b_tids: list[int | None] = []
    bf_b: list[int] = []
    bf_pos: list[int] = []
    bf_fact: list[int] = []
    ei_b: list[int] = []
    ei_pos: list[int] = []
    ei_src: list[int | None] = []
    ei_fact: list[int] = []

    for b, binding in enumerate(provenance.fact_bindings):
        t = binding.transformation
        tid = None
        if t is not None:
            t_key = (t.name, t.kind, t.marker_value, t.executable, t.declaration)
            tid = transform_cache.get(t_key)
            if tid is None:
                declaration = TransformationDeclaration(
                    name=t.name,
                    kind=t.kind,
                    marker_value=t.marker_value,
                    executable=t.executable,
                    declaration=t.declaration,
                )
                tid = transformations.setdefault(declaration, len(transformations))
                transform_cache[t_key] = tid
            ext_inputs = t.external_inputs
            n_ext = len(ext_inputs)
            if n_ext:
                ei_b.extend([b] * n_ext)
                ei_pos.extend(range(n_ext))
                for r in ext_inputs:
                    ei_src.append(sources[r.source_id] if r.source_id is not None else None)
                    ei_fact.append(names[r.fact])
        b_groups.append(binding.fact_group)
        if binding.source_id is not None and binding.acquisition_id is not None:
            b_sources.append(sources[binding.source_id])
            b_acqs.append(acquisitions[(binding.source_id, binding.acquisition_id)])
        else:
            b_sources.append(None)
            b_acqs.append(None)
        b_tids.append(tid)
        b_facts = binding.facts
        n_bf = len(b_facts)
        if n_bf == 1:
            bf_b.append(b)
            bf_pos.append(0)
            bf_fact.append(names[b_facts[0]])
        elif n_bf:
            bf_b.extend([b] * n_bf)
            bf_pos.extend(range(n_bf))
            for f in b_facts:
                bf_fact.append(names[f])

    frames["bindings"] = pl.DataFrame(
        {
            "binding_id": b_ids,
            "fact_group": b_groups,
            "source_ordinal": b_sources,
            "acquisition_key": b_acqs,
            "transformation_id": b_tids,
        },
        schema=EVIDENCE_SCHEMAS["bindings"],
    )
    del b_ids, b_groups, b_sources, b_acqs, b_tids
    frames["binding_facts"] = pl.DataFrame(
        {"binding_id": bf_b, "position": bf_pos, "fact_id": bf_fact},
        schema=EVIDENCE_SCHEMAS["binding_facts"],
    )
    del bf_b, bf_pos, bf_fact
    frames["external_inputs"] = pl.DataFrame(
        {"binding_id": ei_b, "position": ei_pos, "source_ordinal": ei_src, "fact_id": ei_fact},
        schema=EVIDENCE_SCHEMAS["external_inputs"],
    )
    del ei_b, ei_pos, ei_src, ei_fact

    encoded = encode_evidence_tables(frames)
    header = EvidenceHeader(
        schema_version=3,
        provider_id=provenance.provider_id,
        native_table=provenance.native_table,
        build_inputs=provenance.build_inputs,
        source_records=tuple(
            IssuingSource(
                source_id=s.source_id,
                issuer=s.issuer,
                operator=s.operator,
                evidence=s.evidence,
                statements=s.statements,
            )
            for s in provenance.source_records
        ),
        descriptions=tuple(descriptions),
        transformations=tuple(transformations),
        withheld_facts=provenance.withheld_facts,
        row_locator_requirements=tuple(requirements),
        files=evidence_file_identities(frames, encoded),
    )
    return header, frames

"""catalogue evidence : EvidenceHeader × EvidenceRelations → CatalogueEvidence (pure).

Bulk facts and lineage remain Polars relations. Only shared declarations are models.
"""

from __future__ import annotations

import io
import re
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
    CatalogueBuildInputs,
    CodeReference,
    EvidenceReference,
    NativeTableIdentity,
    Sha256,
    SourceStatement,
    WithheldFact,
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


class EvidenceFileIdentity(_EvidenceModel):
    """Identity of an exact public evidence file, not authority over arbitrary paths."""

    path: str
    sha256: Sha256
    byte_count: int = Field(strict=True, gt=0)
    row_count: int = Field(strict=True, ge=0)
    schema_version: Literal[3] = 3


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
            return EvidenceHeader.model_validate(value.model_dump(mode="python"))
        return value

    @field_validator(*EVIDENCE_SCHEMAS, mode="before")
    @classmethod
    def _columns(cls, value: object, info: ValidationInfo) -> pl.DataFrame:
        name = info.field_name
        assert name is not None
        schema = EVIDENCE_SCHEMAS[name]
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
                for item in columns[column]:
                    if item is None:
                        continue
                    if dtype in (pl.UInt32, pl.Int64) and type(item) is not int:
                        raise ValueError(f"{name}.{column} requires integer keys/counts")
                    if dtype == pl.String and not isinstance(item, str):
                        raise ValueError(f"{name}.{column} requires strings")
                    if dtype == pl.List(pl.String) and (
                        not isinstance(item, list) or any(not isinstance(x, str) for x in item)
                    ):
                        raise ValueError(f"{name}.{column} requires string arrays")
            try:
                frame = pl.DataFrame(value, schema=schema, strict=True)
            except (TypeError, ValueError, pl.exceptions.PolarsError) as error:
                raise ValueError(f"invalid {name} column arrays: {error}") from error
        else:
            raise ValueError(f"{name} requires an exact-schema DataFrame")
        if frame.schema != schema or frame.columns != list(schema):
            raise ValueError(f"{name} has invalid columns or dtypes")
        if any(frame[column].null_count() for column in schema if column not in _NULLABLE[name]):
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
    if not names or len(set(names)) != len(names):
        raise ValueError("fact universe must contain unique facts")
    name_ids = {name: index for index, name in enumerate(names)}
    sources = h.source_records
    source_ids = [s.source_id for s in sources]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("source record ids must be unique")
    source_ordinals = {name: i for i, name in enumerate(source_ids)}
    recordings = [{ev.recording.recording_id: ev.recording for ev in s.evidence} for s in sources]
    recording_ids = [ev.recording.recording_id for s in sources for ev in s.evidence]
    if len(set(recording_ids)) != len(recording_ids):
        raise ValueError("recording ids must be unique across the provenance artifact")
    acquisitions = list(e.acquisitions.iter_rows(named=True))
    local_ordinals: dict[int, list[int]] = defaultdict(list)
    local_ids: set[tuple[int, str]] = set()
    claimed: set[tuple[int, str]] = set()
    used_descriptions = []
    for a in acquisitions:
        s = a["source_ordinal"]
        if s >= len(sources) or a["description_id"] >= len(h.descriptions):
            raise ValueError("acquisition source/description foreign key does not resolve")
        local_ordinals[s].append(a["acquisition_ordinal"])
        key = (s, a["acquisition_id"])
        if key in local_ids:
            raise ValueError("source acquisition ids must be unique")
        local_ids.add(key)
        if a["description_id"] not in used_descriptions:
            used_descriptions.append(a["description_id"])
        _validate_acquisition(a)
        for rid in a["recording_ids"]:
            if rid not in recordings[s]:
                raise ValueError("acquisition must reference issuer-local recordings")
            if (s, rid) in claimed:
                raise ValueError("recordings may be claimed by only one acquisition")
            claimed.add((s, rid))
    if [(a["source_ordinal"], a["acquisition_ordinal"]) for a in acquisitions] != sorted(
        (a["source_ordinal"], a["acquisition_ordinal"]) for a in acquisitions
    ):
        raise ValueError("acquisition keys disagree with source-local order")
    for s in range(len(sources)):
        if not local_ordinals[s]:
            raise ValueError("every source record must contain an acquisition")
        _contiguous(local_ordinals[s], "source-local acquisition ordinal")
    _contiguous(used_descriptions, "description first occurrence")
    if len(used_descriptions) != len(h.descriptions):
        raise ValueError("unused description declaration")
    bindings = list(e.bindings.iter_rows())
    groups = [b[1] for b in bindings]
    if len(set(groups)) != len(groups):
        raise ValueError("fact group ids must be unique")
    outputs: list[list[int]] = [[] for _ in bindings]
    inputs: list[list[tuple[int | None, int]]] = [[] for _ in bindings]
    producer: dict[int, int] = {}
    for relation, target in ((e.binding_facts, outputs), (e.external_inputs, inputs)):
        previous = (-1, -1)
        for row in relation.iter_rows():
            b, position = row[:2]
            fact = row[-1]
            if b >= len(bindings) or fact >= len(names) or position != len(target[b]) or (b, position) <= previous:
                raise ValueError("membership/input foreign keys or ordered positions are invalid")
            previous = (b, position)
            if relation is e.binding_facts:
                if fact in producer:
                    raise ValueError("each fact may be bound only once")
                producer[fact] = b
                outputs[b].append(fact)
            else:
                source = row[2]
                if source is not None and source >= len(sources):
                    raise ValueError("external input source foreign key does not resolve")
                inputs[b].append((source, fact))
    validate_build_input_facts(h.build_inputs, {names[fact] for fact in producer})
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
        for name in group.facts:
            if name not in name_ids or name_ids[name] in withheld or name_ids[name] in producer:
                raise ValueError("withheld facts must be declared, unique and disjoint from bound facts")
            withheld[name_ids[name]] = source_ordinals[group.source_id] if group.source_id is not None else None
    if unaccounted := set(range(len(names))) - set(producer) - set(withheld):
        raise ValueError(f"fact universe contains unaccounted facts: {sorted(names[f] for f in unaccounted)!r}")
    edges: list[set[int]] = [set() for _ in bindings]
    runtime: set[int] = set()
    used_transforms: list[int] = []
    for b, _, source, acquisition, transformation in bindings:
        facts = [names[f] for f in outputs[b]]
        if not facts:
            raise ValueError("fact bindings must contain at least one fact")
        if transformation is None:
            if source is None or acquisition is None or source >= len(sources) or acquisition >= len(acquisitions):
                raise ValueError("direct source bindings require a source acquisition")
            a = acquisitions[acquisition]
            if a["source_ordinal"] != source:
                raise ValueError("binding acquisition belongs to another source")
            if inputs[b] or any(not f.startswith(("source.", "native.")) for f in facts):
                raise ValueError("external direct bindings must name source or native facts without inputs")
            if a["method"] == "runtime_http_request" or a["instant_type"] == "runtime":
                runtime.add(b)
                if any(
                    not (
                        f.startswith("source.observation") or (f.startswith("source.station:") and ".observation." in f)
                    )
                    for f in facts
                ):
                    raise ValueError("runtime acquisitions may bind only runtime observation source facts")
        else:
            if source is not None or acquisition is not None or transformation >= len(h.transformations):
                raise ValueError("derived bindings cannot attribute outputs to a source acquisition")
            if any(f.startswith(("source.", "native.")) for f in facts):
                raise ValueError("RivRetrieve transformations cannot produce source or native facts")
            if transformation not in used_transforms:
                used_transforms.append(transformation)
            t = h.transformations[transformation]
            if (t.kind == "authored_constant") != (not inputs[b]):
                raise ValueError("authored constants require zero inputs; other transforms require external inputs")
            _validate_transformation(t, facts, any(f in withheld for _, f in inputs[b]))
            for input_source, fact in inputs[b]:
                if fact in withheld:
                    owner = withheld[fact]
                else:
                    parent = producer[fact]
                    owner = bindings[parent][2]
                    edges[b].add(parent)
                if owner != input_source:
                    raise ValueError("transformation references a dangling or misattributed fact")
        if (
            h.native_table is None
            and any(f.startswith(("provider.", "product.", "station.", "station_product.")) for f in facts)
            and (transformation is None or h.transformations[transformation].kind != "authored_constant")
        ):
            raise ValueError("catalogue facts cannot be bound without native-table identity")
    _contiguous(used_transforms, "transformation first occurrence")
    if len(used_transforms) != len(h.transformations):
        raise ValueError("unused transformation declaration")
    # Iterative postorder avoids both national objects and Python recursion limits.
    state = [0] * len(bindings)
    runtime_ancestor = [False] * len(bindings)
    for start in range(len(bindings)):
        stack = [(start, False)]
        while stack:
            b, finishing = stack.pop()
            if finishing:
                state[b] = 2
                runtime_ancestor[b] = b in runtime or any(runtime_ancestor[x] for x in edges[b])
                continue
            if state[b] == 2:
                continue
            if state[b] == 1:
                raise ValueError("transformation lineage contains a cycle")
            state[b] = 1
            stack.append((b, True))
            stack.extend((x, False) for x in edges[b])
        if runtime_ancestor[start] and any(
            names[f].startswith(("provider.", "product.", "station.", "station_product.")) for f in outputs[start]
        ):
            raise ValueError("packaged fact binding has a runtime acquisition ancestor")
    for s, source in enumerate(sources):
        for statement in source.statements:
            if statement.verification_status != "verified_public_recording":
                continue
            if statement.recording_id not in recordings[s]:
                raise ValueError("statement must reference an issuer-local recording")
            fact = name_ids.get(statement.fact)
            b = producer.get(fact) if fact is not None else None
            if b is None or bindings[b][2] != s:
                raise ValueError("statement recording must be claimed by its fact acquisition")
            a = acquisitions[bindings[b][3]]
            if statement.recording_id not in a["recording_ids"]:
                raise ValueError("statement recording must be claimed by its fact acquisition")
            recording = recordings[s][statement.recording_id]
            if (
                a["method"] != "http_request"
                or a["instant_type"] != "retrieval"
                or _instant(a["retrieved_at_start"]) != recording.retrieved_at
                or a["retrieved_at_end"] is not None
                or a["requested_from"] != [recording.source_url]
            ):
                raise ValueError("statement acquisition must match its exact recording URL and instant")
    _validate_locator_shapes(e.facts)


def _instant(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _validate_acquisition(a: dict) -> None:
    method, instant = a["method"], a["instant_type"]
    if method not in {
        "http_campaign",
        "http_request",
        "repository_recovery",
        "runtime_http_request",
        "corroborating_receipt",
    }:
        raise ValueError("invalid acquisition method")
    if instant not in {
        "retrieval",
        "retrieval_interval",
        "provenance_lower_bound",
        "corroborating_receipt",
        "private_redacted_corroborating_receipt",
        "runtime",
    }:
        raise ValueError("invalid acquisition instant type")
    if not a["requested_from"]:
        raise ValueError("requested_from must contain at least one valid typed location")
    for location in a["requested_from"]:
        if not isinstance(location, str):
            raise ValueError("requested_from has null/non-string member")
        _validate_requested_location(location)
    if any(not isinstance(r, str) for r in a["recording_ids"]):
        raise ValueError("recording_ids has null/non-string member")
    start, end = _instant(a["retrieved_at_start"]), _instant(a["retrieved_at_end"])
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
    material = [a[key] for key in ("material_filename", "material_sha256", "material_byte_count")]
    if any(x is not None for x in material) and (
        any(x is None for x in material) or re.fullmatch(r"[0-9a-f]{64}", a["material_sha256"]) is None
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
    seen = set()
    for _, name, carrier, station, product, role in facts.iter_rows():
        if carrier is None:
            if station is not None or product is not None or role is not None:
                raise ValueError("partial null row locator")
            continue
        if (
            carrier not in {"station", "station_product"}
            or station is None
            or not role
            or (carrier == "station_product") != (product is not None)
        ):
            raise ValueError("row locator does not match carrier")
        key = (carrier, station, product, role)
        if key in seen or name not in _locator_names(*key):
            raise ValueError("duplicate or swapped fact row locator")
        seen.add(key)


def validate_catalogue_locators(
    evidence: CatalogueEvidence, *, stations: pl.DataFrame, station_products: pl.DataFrame
) -> None:
    """validate locators : CatalogueEvidence × CanonicalRowKeys → None (pure)."""
    tables = {"station": stations, "station_product": station_products}
    for table in tables.values():
        if table.height and set(table["provider_id"].to_list()) != {evidence.header.provider_id}:
            raise ValueError("locator canonical provider identity mismatch")
    actual = {
        "station": set(stations.select("station_id").iter_rows()),
        "station_product": set(station_products.select("station_id", "product_id").iter_rows()),
    }
    located: dict[tuple[str, str], set[tuple]] = defaultdict(set)
    for _, _, carrier, station, product, role in evidence.facts.iter_rows():
        if carrier is None:
            continue
        key = (station, product) if carrier == "station_product" else (station,)
        if key not in actual[carrier]:
            raise ValueError("row locator names an absent canonical row")
        located[(carrier, role)].add(key)
    names = set(evidence.facts["name"].to_list())
    availability_candidates = {
        key
        for key in actual["station_product"]
        if any(name in names for name in _locator_names("station_product", key[0], key[1], "availability"))
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
    locators = {}
    requirements = list(row_locator_requirements)
    availability = RowLocatorRequirement(carrier="station_product", role="availability")
    candidates = requirements + ([] if availability in requirements else [availability])
    for requirement in candidates:
        table = stations if requirement.carrier == "station" else station_products
        keys = ("station_id",) if requirement.carrier == "station" else ("station_id", "product_id")
        found = False
        for row in table.select(*keys).iter_rows():
            station, product = row[0], row[1] if len(row) == 2 else None
            locator = (requirement.carrier, station, product, requirement.role)
            matched = [name for name in _locator_names(*locator) if name in names]
            if len(matched) > 1:
                raise ValueError("multiple facts claim the same canonical row role")
            if matched:
                locators[names[matched[0]]] = locator
                found = True
        if found and requirement not in requirements:
            requirements.append(requirement)
    rows: dict[str, list] = {name: [] for name in EVIDENCE_SCHEMAS}
    rows["facts"] = [(i, name, *locators.get(i, (None, None, None, None))) for name, i in names.items()]
    sources = {source.source_id: i for i, source in enumerate(provenance.source_records)}
    descriptions: dict[str, int] = {}
    acquisitions = {}
    for source in provenance.source_records:
        for ordinal, a in enumerate(source.acquisitions):
            key = len(rows["acquisitions"])
            acquisitions[(source.source_id, a.acquisition_id)] = key
            description_id = descriptions.setdefault(a.description, len(descriptions))
            material = (
                (a.material.filename, a.material.sha256, a.material.byte_count) if a.material else (None, None, None)
            )
            rows["acquisitions"].append(
                (
                    key,
                    sources[source.source_id],
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
    transformations: dict[TransformationDeclaration, int] = {}
    for b, binding in enumerate(provenance.fact_bindings):
        t = binding.transformation
        tid = None
        if t is not None:
            declaration = TransformationDeclaration(
                name=t.name,
                kind=t.kind,
                marker_value=t.marker_value,
                executable=t.executable,
                declaration=t.declaration,
            )
            tid = transformations.setdefault(declaration, len(transformations))
            rows["external_inputs"].extend(
                (b, position, sources[r.source_id] if r.source_id is not None else None, names[r.fact])
                for position, r in enumerate(t.external_inputs)
            )
        rows["bindings"].append(
            (
                b,
                binding.fact_group,
                sources[binding.source_id] if binding.source_id is not None else None,
                acquisitions[(binding.source_id, binding.acquisition_id)] if binding.source_id is not None else None,
                tid,
            )
        )
        rows["binding_facts"].extend((b, position, names[f]) for position, f in enumerate(binding.facts))
    frames = {name: pl.DataFrame(data, schema=EVIDENCE_SCHEMAS[name], orient="row") for name, data in rows.items()}
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

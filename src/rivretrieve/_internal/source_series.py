"""Evidence, identity, inventory and outcomes for source observation series.

These values describe independent responsibilities. Inventory is not coverage,
and a published identifier is not a physical classification.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, model_serializer, model_validator

from rivretrieve._internal.issues import FatalContractError, Issue


class EvidenceState(StrEnum):
    """Whether a physical fact is known, absent from the source, or not established here."""

    KNOWN = "known"
    SOURCE_SILENT = "source_silent"
    NOT_ESTABLISHED = "not_established"


class EvidenceFact(BaseModel):
    """One independently established physical fact and its evidence.

    ``known`` requires a nonempty value and evidence. ``source_silent`` means
    the source does not state the fact; ``not_established`` means it has not
    been established here. Both unknown states retain a null value."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    value: str | None = None
    state: EvidenceState = EvidenceState.NOT_ESTABLISHED
    evidence: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check(self) -> EvidenceFact:
        if (self.state is EvidenceState.KNOWN) != (self.value is not None):
            raise ValueError("Only established facts carry a value")
        if self.value == "":
            raise ValueError("A known physical fact cannot be empty")
        if self.state is EvidenceState.KNOWN and not self.evidence:
            raise ValueError("An established fact requires evidence")
        return self


def known(value: str, evidence: str) -> EvidenceFact:
    return EvidenceFact(value=value, state=EvidenceState.KNOWN, evidence=(evidence,))


class ClippingAxis(StrEnum):
    """Whether a request clips daily calendar labels or source wall-clock timestamps."""

    CALENDAR_DATE = "calendar_date"
    SOURCE_TIMESTAMP = "source_timestamp"


class SourceUnitCodeDefinition(BaseModel):
    """Published meaning of a unit code for one provider access namespace."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    provider_id: str
    namespace: str
    code: str
    unit: str
    evidence: tuple[str, ...]

    @model_validator(mode="after")
    def check(self) -> SourceUnitCodeDefinition:
        if not all((self.provider_id, self.namespace, self.code, self.unit)):
            raise ValueError("A source-unit code definition requires nonempty context, code, and unit")
        if not self.evidence or any(not item for item in self.evidence):
            raise ValueError("A source-unit code definition requires nonempty evidence")
        return self


class PhysicalFacts(BaseModel):
    """Physical meaning for one fact segment within a source series.

    Each EvidenceFact retains its own knowledge state. Frequency and statistic
    describe observations, not how often the service updates. Temporal support
    describes the interval represented by a value. Day definition, timestamp
    anchor and time zone remain independent facts; none is inferred from another.
    ``normalized_unit`` preserves the source unit scale and zero. Conversion
    to the output unit is described by Admission, not by unit normalization.
    ``facts_id`` joins this segment to observation rows and retrieval outcomes."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    facts_id: str
    quantity: EvidenceFact = EvidenceFact()
    source_unit: EvidenceFact = EvidenceFact()
    normalized_unit: str | None = None
    source_unit_definition: SourceUnitCodeDefinition | None = None
    frequency: EvidenceFact = EvidenceFact()
    statistic: EvidenceFact = EvidenceFact()
    temporal_support: EvidenceFact = EvidenceFact()
    day_definition: EvidenceFact = EvidenceFact()
    timestamp_anchor: EvidenceFact = EvidenceFact()
    time_zone: EvidenceFact = EvidenceFact()
    vertical_reference: EvidenceFact = EvidenceFact()
    vertical_datum: EvidenceFact = EvidenceFact()
    clipping_axis: ClippingAxis = ClippingAxis.SOURCE_TIMESTAMP
    label_time: str | None = None

    @model_serializer(mode="wrap")
    def serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        values: dict[str, object] = handler(self)
        if self.source_unit_definition is None:
            values.pop("source_unit_definition", None)
        return values

    @model_validator(mode="after")
    def check(self) -> PhysicalFacts:
        if not self.facts_id:
            raise ValueError("facts_id is required")
        if self.normalized_unit is not None and self.source_unit.state is not EvidenceState.KNOWN:
            raise ValueError("A normalized unit requires an established source unit")
        if self.source_unit_definition is not None and (
            self.source_unit.state is not EvidenceState.KNOWN
            or self.source_unit_definition.code != self.source_unit.value
        ):
            raise ValueError("Source-unit code definition must match the known published source-unit code")
        defect = _normalization_defect(
            self.source_unit.value, self.normalized_unit, self.source_unit.evidence, self.source_unit_definition
        )
        if defect is not None:
            raise ValueError(defect)
        if self.clipping_axis is ClippingAxis.CALENDAR_DATE and self.frequency.value != "daily":
            raise ValueError("Calendar-date clipping requires established daily frequency")
        return self


# Conversion factors are dimensional mappings, not source-series classifications.
_UNIT_DIMENSIONS = {
    "m3/s": ("discharge", 1.0),
    "ft3/s": ("discharge", 0.028316846592),
    "l/s": ("discharge", 0.001),
    "m": ("stage", 1.0),
    "cm": ("stage", 0.01),
    "mm": ("stage", 0.001),
    "ft": ("stage", 0.3048),
    "degC": ("temperature", 1.0),
}
_TARGET_UNITS = {"discharge": "m3/s", "stage": "m", "temperature": "degC"}

# These are spelling equivalences, never physical conversions. Kelvin is named
# only to distinguish its zero from Celsius; this does not add Kelvin retrieval.
_UNIT_SPELLINGS = {unit: unit for unit in _UNIT_DIMENSIONS} | {
    "m³/s": "m3/s",
    "m^3/s": "m3/s",
    "ft³/s": "ft3/s",
    "ft^3/s": "ft3/s",
    "L/s": "l/s",
    "M3_S": "m3/s",
    "CM": "cm",
    "0C": "degC",
    "°C": "degC",
    "K": "K",
    # Litres are a volume here, never an unqualified rate alias.
    "l": "l",
    "L": "l",
}


def _normalization_defect(
    source_unit: str | None,
    normalized_unit: str | None,
    evidence: tuple[str, ...],
    definition: SourceUnitCodeDefinition | None = None,
) -> str | None:
    """Normalization must preserve unit identity, including scale and zero."""
    if normalized_unit is None:
        return None
    if not evidence:
        return "unit normalization requires source-unit evidence"
    if definition is not None and definition.code != source_unit:
        return "source-unit code definition does not match the published code"
    source_identity = _UNIT_SPELLINGS.get(definition.unit if definition is not None else source_unit or "")
    normalized_identity = _UNIT_SPELLINGS.get(normalized_unit)
    # A publisher can use a documented source-specific code rather than a unit
    # spelling. Its explicit normalized meaning is supplied at that source
    # boundary; an unrecognized spelling alone cannot establish a contradiction.
    # Unknown units still lack a normalized meaning or a KNOWN source-unit fact.
    if source_identity is None or normalized_identity is None:
        return None
    if source_identity != normalized_identity:
        return "unit normalization changes the published scale, offset, or physical dimension"
    return None


class Admission(BaseModel):
    """Whether established quantity and unit facts permit harmonised numeric rows.

    ``supported`` carries the target unit and multiplicative conversion factor.
    ``unsupported`` carries a reason. Admission does not rank source quality or
    require every temporal fact to be known."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    status: Literal["supported", "unsupported"]
    reason: str | None = None
    target_unit: str | None = None
    factor: float | None = None


def admission(facts: PhysicalFacts) -> Admission:
    if facts.quantity.state is not EvidenceState.KNOWN:
        return Admission(status="unsupported", reason="physical quantity is not established")
    if facts.source_unit.state is not EvidenceState.KNOWN:
        return Admission(status="unsupported", reason=f"source unit is {facts.source_unit.state.value}")
    defect = _normalization_defect(
        facts.source_unit.value, facts.normalized_unit, facts.source_unit.evidence, facts.source_unit_definition
    )
    if defect is not None:
        return Admission(status="unsupported", reason=defect)
    conversion = _UNIT_DIMENSIONS.get(_UNIT_SPELLINGS.get(facts.normalized_unit or "", ""))
    if conversion is None:
        return Admission(status="unsupported", reason=f"conversion is not established for {facts.source_unit.value!r}")
    quantity, factor = conversion
    if quantity != facts.quantity.value:
        return Admission(
            status="unsupported", reason="source unit is dimensionally incompatible with physical quantity"
        )
    return Admission(status="supported", target_unit=_TARGET_UNITS[quantity], factor=factor)


class SourceIdentity(BaseModel):
    """Agency-published identity within a source namespace, with origin and evidence.

    ``published_id`` and description can be absent. Origin records whether the
    identity was acquired from a catalogue, response or established mapping.
    An identity is not a harmonised quality score."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    namespace: str
    published_id: str | None = None
    description: str | None = None
    origin: Literal["catalogue", "response", "mapping"]
    evidence: tuple[str, ...]

    @model_validator(mode="after")
    def check(self) -> SourceIdentity:
        if not self.namespace or not self.evidence:
            raise ValueError("Source identity requires a namespace and evidence")
        return self


def stable_id(*components: str | None) -> str:
    encoded = json.dumps(components, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class SourceSeries(BaseModel):
    """One concrete source identity at a provider, station and access route.

    ``series_id`` joins the definition to rows, inventories and outcomes.
    ``product_id`` is an internal access route, not a physical classification.
    ``variant`` preserves a selectable source alternative when established.
    ``facts`` contains independently identified physical-fact segments.
    Matching physical facts do not establish scientific interchangeability."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    series_id: str
    provider_id: str
    station_id: str
    product_id: str
    identity: SourceIdentity
    variant: str | None = None
    facts: tuple[PhysicalFacts, ...]

    @model_validator(mode="after")
    def check(self) -> SourceSeries:
        if not all((self.series_id, self.provider_id, self.station_id, self.product_id)):
            raise ValueError("Source series requires nonempty identifiers")
        if not self.facts or len({fact.facts_id for fact in self.facts}) != len(self.facts):
            raise ValueError("Source series requires unique physical-fact segments")
        for fact in self.facts:
            definition = fact.source_unit_definition
            if definition is not None and (
                definition.provider_id != self.provider_id or definition.namespace != self.identity.namespace
            ):
                raise ValueError("Source-unit code definition does not apply to this provider and source namespace")
        return self


class PhysicalPredicate(BaseModel):
    """An exact filter on a known physical fact; unknown facts do not match."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    field: Literal[
        "quantity",
        "frequency",
        "statistic",
        "temporal_support",
        "day_definition",
        "timestamp_anchor",
        "time_zone",
        "vertical_reference",
        "vertical_datum",
    ]
    value: str


class RestrictionKind(StrEnum):
    """All matching identities, or an explicit variant or series-ID restriction."""

    ALL = "all"
    EXPLICIT = "explicit"


class ScopeState(StrEnum):
    """An active request scope or an empty intersection of filters."""

    ACTIVE = "active"
    EMPTY = "empty"


class SeriesScope(BaseModel):
    """Physical filters and source restrictions retained by a selection or result.

    Empty coordinate tuples impose no coordinate restriction. ``all`` includes
    matching identities discovered during retrieval, not only packaged members.
    ``explicit`` retains requested variants or series IDs without fallback to
    other identities. Variant matching accepts a variant or published source ID.
    All physical predicates must match known facts within a fact segment.
    An ``empty`` scope matches nothing."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    state: ScopeState = ScopeState.ACTIVE
    provider_ids: tuple[str, ...] = ()
    station_ids: tuple[str, ...] = ()
    product_ids: tuple[str, ...] = ()
    predicates: tuple[PhysicalPredicate, ...] = ()
    restriction: RestrictionKind = RestrictionKind.ALL
    variants: tuple[str, ...] = ()
    series_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check(self) -> SeriesScope:
        if self.restriction is RestrictionKind.ALL and (self.variants or self.series_ids):
            raise ValueError("An all-matching scope cannot carry explicit source restrictions")
        if (
            self.restriction is RestrictionKind.EXPLICIT
            and self.state is ScopeState.ACTIVE
            and not self.variants
            and not self.series_ids
        ):
            raise ValueError("An active explicit scope requires an identity restriction")
        return self

    def matches(self, series: SourceSeries) -> bool:
        if self.state is ScopeState.EMPTY:
            return False
        if any(
            allowed and value not in allowed
            for allowed, value in (
                (self.provider_ids, series.provider_id),
                (self.station_ids, series.station_id),
                (self.product_ids, series.product_id),
            )
        ):
            return False
        if self.restriction is RestrictionKind.EXPLICIT:
            if self.series_ids and series.series_id not in self.series_ids:
                return False
            if (
                self.variants
                and series.variant not in self.variants
                and series.identity.published_id not in self.variants
            ):
                return False
        return any(self.matches_facts(facts) for facts in series.facts)

    def matches_facts(self, facts: PhysicalFacts) -> bool:
        return all(
            getattr(facts, predicate.field).state is EvidenceState.KNOWN
            and getattr(facts, predicate.field).value == predicate.value
            for predicate in self.predicates
        )


class SeriesWindow(BaseModel):
    """Closed request interval with ordered, naive source wall-clock endpoints."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def check(self) -> SeriesWindow:
        if self.start.tzinfo is not None or self.end.tzinfo is not None or self.start > self.end:
            raise ValueError("Series window requires ordered naive wall-clock endpoints")
        return self


class InventoryCompleteness(StrEnum):
    """Completeness of one scoped inventory: complete, incomplete or unresolved."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNRESOLVED = "unresolved"


class CatalogueSeriesClaim(BaseModel):
    """A scoped publisher catalogue claim, not an alias for a response series."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    provider_id: str
    station_id: str
    product_id: str
    identity: SourceIdentity
    native_coordinates: tuple[tuple[str, str | None], ...] = ()


class InventorySnapshot(BaseModel):
    """What is known about source-series membership for a scope and access route.

    ``members`` holds concrete series IDs; ``member_facts`` can identify their
    fact segments. Catalogue claims retain separately published catalogue
    identities rather than pretending they are response series.
    Completeness applies only to this scope, access and optional window, not
    countrywide coverage or a full historical census. Incomplete and unresolved
    snapshots carry a reason. Acquisition time and catalogue check date record
    evidence timing, not continuous observation coverage."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot_id: str
    scope: SeriesScope
    members: tuple[str, ...]
    member_facts: tuple[tuple[str, tuple[str, ...]], ...] = ()
    completeness: InventoryCompleteness
    access: str
    origin: Literal["catalogue", "response", "compiled"]
    acquired_at: datetime | None = None
    catalogue_check_date: date | None = None
    catalogue_claims: tuple[CatalogueSeriesClaim, ...] = ()
    window: SeriesWindow | None = None
    evidence: tuple[str, ...]
    reason: str | None = None

    @model_validator(mode="after")
    def check(self) -> InventorySnapshot:
        if not self.snapshot_id or not self.access or not self.evidence:
            raise ValueError("Inventory requires identity, supported access and evidence")
        keys = [key for key, _ in self.member_facts]
        if len(set(self.members)) != len(self.members):
            raise ValueError("Inventory members must be unique")
        if len(set(keys)) != len(keys) or any(key not in self.members for key in keys):
            raise ValueError("Inventory fact membership must reference unique inventory members")
        if any(
            not facts or len(set(facts)) != len(facts) or any(not fact for fact in facts)
            for _, facts in self.member_facts
        ):
            raise ValueError("Inventory fact membership requires unique nonempty physical fact identities")
        if self.completeness is not InventoryCompleteness.COMPLETE and not self.reason:
            raise ValueError("Incomplete inventory requires a reason")
        return self


class OutcomeStatus(StrEnum):
    """Result of one retrieval: success, empty, failed, unsupported, unresolved or no_match.

    ``success`` and ``empty`` retain a concrete series and fact IDs. ``empty``
    means no observation rows, not a row with a null value. ``failed`` records
    a source failure; ``unsupported`` records an unsupported series.
    ``unresolved`` means availability cannot be established. ``no_match`` means
    the available evidence establishes that nothing matches the request."""

    SUCCESS = "success"
    EMPTY = "empty"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    UNRESOLVED = "unresolved"
    NO_MATCH = "no_match"


class RequestedSelector(BaseModel):
    """A caller restriction, not an assertion of published source identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["variant", "series_id"]
    value: str

    @model_validator(mode="after")
    def check(self) -> RequestedSelector:
        if not self.value:
            raise ValueError("A requested selector requires a nonempty value")
        return self


class RetrievalOutcome(BaseModel):
    """Retrieval status for one source series over the interval in ``window``.

    An outcome can instead describe a requested station, access route or
    selector that has no concrete series identity. A series can have several
    outcomes for different intervals or fact segments.

    ``series_id`` can be absent when no concrete identity is established.
    ``requested_selector`` preserves the caller restriction without inventing
    a source identity. Unsuccessful outcomes retain a reason. ``calls`` links
    source-call evidence; ``retrieved_at`` records retrieval timing when known.
    Outcomes remain present even when there are no observation rows."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    outcome_id: str
    series_id: str | None
    station_id: str
    product_id: str
    window: SeriesWindow
    status: OutcomeStatus
    facts_ids: tuple[str, ...] = ()
    reason: str | None = None
    retrieved_at: datetime | None = None
    calls: tuple[str, ...] = ()
    requested_selector: RequestedSelector | None = None

    @model_validator(mode="after")
    def check(self) -> RetrievalOutcome:
        if self.status in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY):
            if self.series_id is None or not self.facts_ids:
                raise ValueError("A successful outcome requires a concrete series and physical facts")
        elif not self.reason:
            raise ValueError("An unsuccessful outcome requires a reason")
        return self


@dataclass(frozen=True, slots=True)
class ParsedSeries:
    rows: pl.DataFrame
    series: tuple[SourceSeries, ...]
    inventories: tuple[InventorySnapshot, ...]
    outcomes: tuple[RetrievalOutcome, ...]
    issues: tuple[Issue, ...] = ()


def validate_series_rows(rows: pl.DataFrame, series: tuple[SourceSeries, ...]) -> None:
    definitions = {item.series_id: item for item in series}
    if len(definitions) != len(series):
        raise FatalContractError("Duplicate concrete series definitions")
    facts_by_identity: dict[str, PhysicalFacts] = {}
    for definition in series:
        # Stage output may contain unchecked internal model_copy values. Rebuild
        # domain validation from data even when no numeric rows were returned.
        try:
            SourceSeries.model_validate(definition.model_dump(mode="python"))
        except ValueError as error:
            raise FatalContractError(
                f"Native series requires valid admitted physical facts and context: {error}"
            ) from error
        for facts in definition.facts:
            existing = facts_by_identity.get(facts.facts_id)
            if existing is not None and existing != facts:
                raise FatalContractError("Conflicting physical facts under one fact identity")
            facts_by_identity[facts.facts_id] = facts
    for row in rows.iter_rows(named=True):
        definition = definitions.get(row["series_id"])
        if definition is None:
            raise FatalContractError("Native row references an unknown source series")
        facts = next((item for item in definition.facts if item.facts_id == row.get("facts_id")), None)
        if facts is None:
            raise FatalContractError("Native row references unknown physical facts")
        if row["station_id"] != definition.station_id or row["product_id"] != definition.product_id:
            raise FatalContractError("Native row contradicts its source-series coordinates")
        decision = admission(facts)
        if decision.status != "supported" or row.get("source_unit") != facts.source_unit.value:
            raise FatalContractError("Native numeric rows require admitted, matching source-unit facts")

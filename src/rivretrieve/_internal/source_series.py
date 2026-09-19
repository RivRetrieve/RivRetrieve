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
from pydantic import BaseModel, ConfigDict, model_validator

from rivretrieve._internal.issues import FatalContractError, Issue


class EvidenceState(StrEnum):
    KNOWN = "known"
    SOURCE_SILENT = "source_silent"
    NOT_ESTABLISHED = "not_established"


class EvidenceFact(BaseModel):
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
    CALENDAR_DATE = "calendar_date"
    SOURCE_TIMESTAMP = "source_timestamp"


class PhysicalFacts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    facts_id: str
    quantity: EvidenceFact = EvidenceFact()
    source_unit: EvidenceFact = EvidenceFact()
    normalized_unit: str | None = None
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

    @model_validator(mode="after")
    def check(self) -> PhysicalFacts:
        if not self.facts_id:
            raise ValueError("facts_id is required")
        if self.normalized_unit is not None and self.source_unit.state is not EvidenceState.KNOWN:
            raise ValueError("A normalized unit requires an established source unit")
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


class Admission(BaseModel):
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
    conversion = _UNIT_DIMENSIONS.get(facts.normalized_unit or "")
    if conversion is None:
        return Admission(status="unsupported", reason=f"conversion is not established for {facts.source_unit.value!r}")
    quantity, factor = conversion
    published_dimension = _UNIT_DIMENSIONS.get(facts.source_unit.value or "")
    if published_dimension is not None and published_dimension[0] != quantity:
        return Admission(status="unsupported", reason="unit normalization changes the published physical dimension")
    if quantity != facts.quantity.value:
        return Admission(
            status="unsupported", reason="source unit is dimensionally incompatible with physical quantity"
        )
    return Admission(status="supported", target_unit=_TARGET_UNITS[quantity], factor=factor)


class SourceIdentity(BaseModel):
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
        return self


class PhysicalPredicate(BaseModel):
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
    ALL = "all"
    EXPLICIT = "explicit"


class ScopeState(StrEnum):
    ACTIVE = "active"
    EMPTY = "empty"


class SeriesScope(BaseModel):
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
    model_config = ConfigDict(frozen=True, extra="forbid")
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def check(self) -> SeriesWindow:
        if self.start.tzinfo is not None or self.end.tzinfo is not None or self.start > self.end:
            raise ValueError("Series window requires ordered naive wall-clock endpoints")
        return self


class InventoryCompleteness(StrEnum):
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
    SUCCESS = "success"
    EMPTY = "empty"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    UNRESOLVED = "unresolved"
    NO_MATCH = "no_match"


class RetrievalOutcome(BaseModel):
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

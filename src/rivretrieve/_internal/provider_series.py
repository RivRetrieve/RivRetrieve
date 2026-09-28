"""Attach explicit provider mapping evidence at native parser boundaries."""

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
    EvidenceState,
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    SourceUnitCodeDefinition,
    stable_id,
)

NATIVE_SCHEMA = {k: v for k, v in RowsSchema.polars_schema.items() if k not in ("series_id", "facts_id", "source_unit")}


class UnsupportedSourceStructureError(ValueError):
    """Publisher bytes do not satisfy the supported source mapping."""


@dataclass(frozen=True)
class SeriesMapping:
    """Published access identity and independently established physical facts."""

    namespace: str
    quantity: str
    source_unit: str
    normalized_unit: str
    frequency: str | None = None
    statistic: str | None = None
    published_id: str | None = None
    time_zone: str | None = None
    source_unit_definition: SourceUnitCodeDefinition | None = None
    evidence: tuple[str, ...] = field(default=(), kw_only=True)
    identity_evidence: tuple[str, ...] = field(default=(), kw_only=True)
    temporal_support: str | None = field(default=None, kw_only=True)
    day_definition: str | None = field(default=None, kw_only=True)
    timestamp_anchor: str | None = field(default=None, kw_only=True)
    vertical_reference: str | None = field(default=None, kw_only=True)
    vertical_datum: str | None = field(default=None, kw_only=True)
    label_time: str | None = field(default=None, kw_only=True)

    def physical_facts(self) -> PhysicalFacts:
        """Use the same publisher-backed facts in discovery and observation parsing."""
        if not self.evidence or any(not value for value in self.evidence):
            raise FatalContractError(f"Source mapping {self.namespace!r} requires publisher evidence")

        def fact(value: str | None) -> EvidenceFact:
            return (
                EvidenceFact(value=value, state=EvidenceState.KNOWN, evidence=self.evidence)
                if value is not None
                else EvidenceFact()
            )

        unit_evidence = () if self.source_unit_definition is None else self.source_unit_definition.evidence
        facts = PhysicalFacts(
            facts_id="unidentified",
            quantity=fact(self.quantity),
            source_unit=EvidenceFact(
                value=self.source_unit, state=EvidenceState.KNOWN, evidence=(*self.evidence, *unit_evidence)
            ),
            normalized_unit=self.normalized_unit,
            source_unit_definition=self.source_unit_definition,
            frequency=fact(self.frequency),
            statistic=fact(self.statistic),
            temporal_support=fact(self.temporal_support),
            day_definition=fact(self.day_definition),
            timestamp_anchor=fact(self.timestamp_anchor),
            time_zone=fact(self.time_zone),
            vertical_reference=fact(self.vertical_reference),
            vertical_datum=fact(self.vertical_datum),
            clipping_axis=ClippingAxis.CALENDAR_DATE if self.frequency == "daily" else ClippingAxis.SOURCE_TIMESTAMP,
            label_time=self.label_time,
        )
        return facts.model_copy(update={"facts_id": stable_id(facts.model_dump_json(exclude={"facts_id"}))})

    def source_series(self, provider: str, station: str, product: str) -> SourceSeries:
        """Resolve a mapped source identity without requiring observation bytes."""
        return SourceSeries(
            series_id=stable_id(provider, station, self.namespace, self.published_id),
            provider_id=provider,
            station_id=station,
            product_id=product,
            identity=self.identity(),
            facts=(self.physical_facts(),),
        )

    def identity(self) -> SourceIdentity:
        """Describe the published selector without manufacturing a variant label."""
        return SourceIdentity(
            namespace=self.namespace,
            published_id=self.published_id,
            origin="mapping",
            evidence=self.identity_evidence or self.evidence,
        )


def parse_mapped_series(
    payload: Payload,
    config: ProviderConfig,
    *,
    provider: str,
    mappings: Mapping[str, SeriesMapping],
    native_parse: Callable[[Payload, ProviderConfig], WithIssues[pl.DataFrame]],
    narrow_payload: Callable[[Payload, str], Payload] | None = None,
) -> ParsedSeries:
    if not payload.station_products or len({s for s, _ in payload.station_products}) != 1:
        raise FatalContractError("Mapped payload must identify one station and at least one product")
    response_hash = hashlib.sha256(payload.content).hexdigest()
    rows = []
    definitions = []
    outcomes = []
    issues = []
    window = SeriesWindow(
        start=datetime.fromisoformat(payload.fetch_window.start.isoformat()),
        end=datetime.fromisoformat(payload.fetch_window.end.isoformat()),
        axis=payload.acquisition_axis,
    )
    acquired = payload.origin.retrieved_at if isinstance(payload.origin.retrieved_at, datetime) else None
    scope = payload.scope or SeriesScope(
        provider_ids=(provider,),
        station_ids=tuple({s for s, _ in payload.station_products}),
        product_ids=tuple(p for _, p in payload.station_products),
    )
    for station, product in payload.station_products:
        if product not in mappings or product not in config.products:
            raise FatalContractError("Product has no explicit source-series mapping")
        mapping = mappings[product]
        facts = mapping.physical_facts()
        fact_id = facts.facts_id
        series = mapping.source_series(provider, station, product)
        definitions.append(series)
        if not scope.matches(series):
            continue
        tagged = replace(payload, station_products=((station, product),))
        if narrow_payload is not None:
            tagged = narrow_payload(tagged, product)
        reason = None
        try:
            parsed = native_parse(tagged, config)
            issues.extend(parsed.issues)
            failures = [i for i in parsed.issues if i.severity == "error"]
            if failures:
                status = OutcomeStatus.FAILED
                reason = "; ".join(i.message for i in failures)
            else:
                status = OutcomeStatus.EMPTY if parsed.value.is_empty() else OutcomeStatus.SUCCESS
                rows.append(
                    parsed.value.with_columns(
                        pl.lit(series.series_id).alias("series_id"),
                        pl.lit(fact_id).alias("facts_id"),
                        pl.lit(mapping.source_unit).alias("source_unit"),
                    )
                )
        except UnsupportedSourceStructureError as error:
            status = OutcomeStatus.UNSUPPORTED
            reason = str(error)
            issues.append(
                Issue(
                    severity="error",
                    code="unsupported_source_structure",
                    message=reason,
                    provider_id=ProviderId(provider),
                    details={"station_id": station, "product_id": product, "series_id": series.series_id},
                )
            )
        outcomes.append(
            RetrievalOutcome(
                outcome_id=stable_id(
                    payload.acquisition_id,
                    series.series_id,
                    window.model_dump_json(),
                    status,
                    response_hash,
                    str(acquired),
                ),
                series_id=series.series_id,
                station_id=station,
                product_id=product,
                window=window,
                status=status,
                facts_ids=(fact_id,),
                reason=reason,
                retrieved_at=acquired,
                calls=tuple(item.attempt_id for item in payload.attempt_traces) or (payload.acquisition_id,),
            )
        )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(
            payload.acquisition_id,
            provider,
            scope.model_dump_json(),
            window.model_dump_json(),
            response_hash,
            str(acquired),
        ),
        scope=scope,
        members=tuple(s.series_id for s in definitions),
        completeness=InventoryCompleteness.INCOMPLETE,
        access=f"{provider} supported source mapping",
        origin="response",
        acquired_at=acquired,
        window=window,
        evidence=(f"{provider} parsed payload",),
        reason="Supported access does not establish exhaustive source-series inventory",
    )
    return ParsedSeries(
        pl.concat(rows) if rows else pl.DataFrame(schema=RowsSchema.polars_schema),
        tuple(definitions),
        (inventory,),
        tuple(outcomes),
        tuple(issues),
    )

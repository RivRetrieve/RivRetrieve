"""Attach explicit provider mapping evidence at native parser boundaries."""

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProductId, ProviderId
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


def _mapped_pair_outcome_and_rows(
    payload: Payload,
    *,
    provider: str,
    station: str,
    product: str,
    mapping: SeriesMapping,
    series: SourceSeries,
    fact_id: str,
    window: SeriesWindow,
    acquired: datetime | None,
    response_hash: str,
    result: WithIssues[pl.DataFrame] | UnsupportedSourceStructureError,
) -> tuple[pl.DataFrame | None, RetrievalOutcome, tuple[Issue, ...]]:
    if isinstance(result, UnsupportedSourceStructureError):
        status = OutcomeStatus.UNSUPPORTED
        reason: str | None = str(result)
        row_frame: pl.DataFrame | None = None
        pair_issues: tuple[Issue, ...] = (
            Issue(
                severity="error",
                code="unsupported_source_structure",
                message=reason,
                provider_id=ProviderId(provider),
                details={"station_id": station, "product_id": product, "series_id": series.series_id},
            ),
        )
    else:
        pair_issues = tuple(result.issues)
        failures = [item for item in result.issues if item.severity == "error"]
        if failures:
            status = OutcomeStatus.FAILED
            reason = "; ".join(item.message for item in failures)
            row_frame = None
        else:
            status = OutcomeStatus.EMPTY if result.value.is_empty() else OutcomeStatus.SUCCESS
            reason = None
            row_frame = result.value.with_columns(
                pl.lit(series.series_id).alias("series_id"),
                pl.lit(fact_id).alias("facts_id"),
                pl.lit(mapping.source_unit).alias("source_unit"),
            )
    outcome = RetrievalOutcome(
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
    return row_frame, outcome, pair_issues


def _mapped_inventory(
    payload: Payload,
    *,
    provider: str,
    scope: SeriesScope,
    members: tuple[str, ...],
    window: SeriesWindow,
    acquired: datetime | None,
    response_hash: str,
) -> InventorySnapshot:
    return InventorySnapshot(
        snapshot_id=stable_id(
            payload.acquisition_id,
            provider,
            scope.model_dump_json(),
            window.model_dump_json(),
            response_hash,
            str(acquired),
        ),
        scope=scope,
        members=members,
        completeness=InventoryCompleteness.INCOMPLETE,
        access=f"{provider} supported source mapping",
        origin="response",
        acquired_at=acquired,
        window=window,
        evidence=(f"{provider} parsed payload",),
        reason="Supported access does not establish exhaustive source-series inventory",
    )


def _run_native_group(
    payload: Payload,
    matched_payloads: Mapping[tuple[str, ProductId], Payload],
    config: ProviderConfig,
    native_parse_group: Callable[
        [Payload, Mapping[tuple[str, ProductId], Payload], ProviderConfig],
        Mapping[tuple[str, ProductId], WithIssues[pl.DataFrame] | UnsupportedSourceStructureError],
    ],
) -> tuple[
    Mapping[tuple[str, ProductId], WithIssues[pl.DataFrame] | UnsupportedSourceStructureError],
    UnsupportedSourceStructureError | None,
]:
    if not matched_payloads:
        return {}, None
    try:
        native_results = native_parse_group(payload, matched_payloads, config)
    except UnsupportedSourceStructureError as error:
        return {}, error
    if set(native_results.keys()) != set(matched_payloads.keys()):
        raise FatalContractError("Mapped native_parse_group keys must match its matched pair payloads")
    return native_results, None


def parse_mapped_series(
    payload: Payload,
    config: ProviderConfig,
    *,
    provider: str,
    mappings: Mapping[str, SeriesMapping],
    native_parse: Callable[[Payload, ProviderConfig], WithIssues[pl.DataFrame]] | None = None,
    narrow_payload: Callable[[Payload, str], Payload] | None = None,
    native_parse_group: Callable[
        [Payload, Mapping[tuple[str, ProductId], Payload], ProviderConfig],
        Mapping[tuple[str, ProductId], WithIssues[pl.DataFrame] | UnsupportedSourceStructureError],
    ]
    | None = None,
    response_hash: str | None = None,
) -> ParsedSeries:
    if not payload.station_products or len({s for s, _ in payload.station_products}) != 1:
        raise FatalContractError("Mapped payload must identify one station and at least one product")
    if native_parse is None and native_parse_group is None:
        raise FatalContractError("Mapped parse requires native_parse or native_parse_group")
    resolved_hash = response_hash if response_hash is not None else hashlib.sha256(payload.content).hexdigest()
    rows: list[pl.DataFrame] = []
    definitions: list[SourceSeries] = []
    outcomes: list[RetrievalOutcome] = []
    issues: list[Issue] = []
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
    matched_items: list[tuple[tuple[str, ProductId], SeriesMapping, SourceSeries, str, Payload]] = []
    for station, product in payload.station_products:
        if product not in mappings or product not in config.products:
            raise FatalContractError("Product has no explicit source-series mapping")
        mapping = mappings[product]
        series = mapping.source_series(provider, station, product)
        fact_id = series.facts[0].facts_id
        definitions.append(series)
        if not scope.matches(series):
            continue
        tagged = replace(payload, station_products=((station, product),))
        if narrow_payload is not None:
            tagged = narrow_payload(tagged, product)
        matched_items.append(((station, product), mapping, series, fact_id, tagged))

    native_results: Mapping[tuple[str, ProductId], WithIssues[pl.DataFrame] | UnsupportedSourceStructureError] = {}
    shared_error: UnsupportedSourceStructureError | None = None
    if native_parse_group is not None and matched_items:
        matched_payloads = {key: tagged for key, _, _, _, tagged in matched_items}
        native_results, shared_error = _run_native_group(payload, matched_payloads, config, native_parse_group)

    for (station, product), mapping, series, fact_id, tagged in matched_items:
        if native_parse_group is not None:
            native_result = shared_error if shared_error is not None else native_results[(station, product)]
        else:
            assert native_parse is not None
            try:
                native_result = native_parse(tagged, config)
            except UnsupportedSourceStructureError as error:
                native_result = error
        row_frame, outcome, pair_issues = _mapped_pair_outcome_and_rows(
            payload,
            provider=provider,
            station=station,
            product=product,
            mapping=mapping,
            series=series,
            fact_id=fact_id,
            window=window,
            acquired=acquired,
            response_hash=resolved_hash,
            result=native_result,
        )
        if row_frame is not None:
            rows.append(row_frame)
        outcomes.append(outcome)
        issues.extend(pair_issues)
    inventory = _mapped_inventory(
        payload,
        provider=provider,
        scope=scope,
        members=tuple(s.series_id for s in definitions),
        window=window,
        acquired=acquired,
        response_hash=resolved_hash,
    )
    return ParsedSeries(
        pl.concat(rows) if rows else pl.DataFrame(schema=RowsSchema.polars_schema),
        tuple(definitions),
        (inventory,),
        tuple(outcomes),
        tuple(issues),
    )


def parse_mapped_group(
    payload: Payload,
    pair_payloads: Mapping[tuple[str, ProductId], Payload],
    config: ProviderConfig,
    *,
    provider: str,
    mappings: Mapping[str, SeriesMapping],
    native_parse_group: Callable[
        [Payload, Mapping[tuple[str, ProductId], Payload], ProviderConfig],
        Mapping[tuple[str, ProductId], WithIssues[pl.DataFrame] | UnsupportedSourceStructureError],
    ],
    response_hash: str | None = None,
) -> dict[tuple[str, ProductId], ParsedSeries]:
    """Build per-pair ``ParsedSeries`` results from one shared mapped response decode."""
    if not pair_payloads:
        raise FatalContractError("Mapped group parse requires at least one pair payload")
    stations = {station for station, _ in pair_payloads}
    if len(stations) != 1:
        raise FatalContractError("Mapped payload must identify one station and at least one product")

    resolved_hash = response_hash if response_hash is not None else hashlib.sha256(payload.content).hexdigest()
    empty_rows = pl.DataFrame(schema=RowsSchema.polars_schema)
    prepared: dict[
        tuple[str, ProductId],
        tuple[Payload, SeriesMapping, SourceSeries, str, SeriesWindow, datetime | None, SeriesScope],
    ] = {}
    matched_payloads: dict[tuple[str, ProductId], Payload] = {}
    for key, pair_payload in pair_payloads.items():
        station, product = key
        if pair_payload.station_products != ((station, product),):
            raise FatalContractError("Pair payload station_products does not match its group key")
        if product not in mappings or product not in config.products:
            raise FatalContractError("Product has no explicit source-series mapping")
        mapping = mappings[product]
        series = mapping.source_series(provider, station, product)
        fact_id = series.facts[0].facts_id
        window = SeriesWindow(
            start=datetime.fromisoformat(pair_payload.fetch_window.start.isoformat()),
            end=datetime.fromisoformat(pair_payload.fetch_window.end.isoformat()),
            axis=pair_payload.acquisition_axis,
        )
        acquired = pair_payload.origin.retrieved_at if isinstance(pair_payload.origin.retrieved_at, datetime) else None
        pair_scope = pair_payload.scope or SeriesScope(
            provider_ids=(provider,),
            station_ids=(station,),
            product_ids=(str(product),),
        )
        prepared[key] = (pair_payload, mapping, series, fact_id, window, acquired, pair_scope)
        if pair_scope.matches(series):
            matched_payloads[key] = pair_payload

    native_results: Mapping[tuple[str, ProductId], WithIssues[pl.DataFrame] | UnsupportedSourceStructureError] = {}
    shared_error: UnsupportedSourceStructureError | None = None
    if matched_payloads:
        try:
            native_results = native_parse_group(payload, matched_payloads, config)
        except UnsupportedSourceStructureError as error:
            shared_error = error
        else:
            if set(native_results.keys()) != set(matched_payloads.keys()):
                raise FatalContractError("Mapped native_parse_group keys must match its matched pair payloads")

    results: dict[tuple[str, ProductId], ParsedSeries] = {}
    for key, (pair_payload, mapping, series, fact_id, window, acquired, pair_scope) in prepared.items():
        station, product = key
        inventory = _mapped_inventory(
            pair_payload,
            provider=provider,
            scope=pair_scope,
            members=(series.series_id,),
            window=window,
            acquired=acquired,
            response_hash=resolved_hash,
        )
        if key not in matched_payloads:
            results[key] = ParsedSeries(empty_rows, (series,), (inventory,), (), ())
            continue
        native_result = shared_error if shared_error is not None else native_results[key]
        row_frame, outcome, pair_issues = _mapped_pair_outcome_and_rows(
            pair_payload,
            provider=provider,
            station=station,
            product=str(product),
            mapping=mapping,
            series=series,
            fact_id=fact_id,
            window=window,
            acquired=acquired,
            response_hash=resolved_hash,
            result=native_result,
        )
        results[key] = ParsedSeries(
            row_frame if row_frame is not None else empty_rows,
            (series,),
            (inventory,),
            (outcome,),
            pair_issues,
        )
    return results

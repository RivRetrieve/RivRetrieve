"""Attach explicit provider mapping evidence at native parser boundaries."""

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime

import polars as pl

from rivretrieve._internal.engine import Payload, ProviderConfig, RowsSchema, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceFact,
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
    known,
    stable_id,
)

NATIVE_SCHEMA = {k: v for k, v in RowsSchema.polars_schema.items() if k not in ("series_id", "facts_id", "source_unit")}


class UnsupportedSourceStructureError(ValueError):
    """Publisher bytes do not satisfy the supported source mapping."""


@dataclass(frozen=True)
class SeriesMapping:
    namespace: str
    quantity: str
    source_unit: str
    normalized_unit: str
    frequency: str | None = None
    statistic: str | None = None
    published_id: str | None = None
    time_zone: str | None = None


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
        evidence = f"{provider}/config.py and catalogue/products.parquet: {product}"
        fact_id = stable_id(provider, product, mapping.source_unit)
        facts = PhysicalFacts(
            facts_id=fact_id,
            quantity=known(mapping.quantity, evidence),
            source_unit=known(mapping.source_unit, evidence),
            normalized_unit=mapping.normalized_unit,
            frequency=known(mapping.frequency, evidence) if mapping.frequency else EvidenceFact(),
            statistic=known(mapping.statistic, evidence) if mapping.statistic else EvidenceFact(),
            time_zone=known(mapping.time_zone, evidence) if mapping.time_zone else EvidenceFact(),
            clipping_axis=ClippingAxis.CALENDAR_DATE if mapping.frequency == "daily" else ClippingAxis.SOURCE_TIMESTAMP,
            label_time="00:00" if mapping.frequency == "daily" else None,
        )
        identity = SourceIdentity(
            namespace=mapping.namespace, published_id=mapping.published_id, origin="mapping", evidence=(evidence,)
        )
        series = SourceSeries(
            series_id=stable_id(provider, station, mapping.namespace, mapping.published_id),
            provider_id=provider,
            station_id=station,
            product_id=product,
            identity=identity,
            facts=(facts,),
        )
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
                outcome_id=stable_id(series.series_id, window.model_dump_json(), status, response_hash, str(acquired)),
                series_id=series.series_id,
                station_id=station,
                product_id=product,
                window=window,
                status=status,
                facts_ids=(fact_id,),
                reason=reason,
                retrieved_at=acquired,
            )
        )
    inventory = InventorySnapshot(
        snapshot_id=stable_id(
            provider, scope.model_dump_json(), window.model_dump_json(), response_hash, str(acquired)
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

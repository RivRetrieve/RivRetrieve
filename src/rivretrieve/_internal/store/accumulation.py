"""Atomically retain native series successes, inventory evidence and retrieval outcomes."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import polars as pl

from rivretrieve._internal.coverage import CoverageInterval, remainder
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import (
    InventorySnapshot,
    OutcomeStatus,
    RetrievalOutcome,
    SourceSeries,
    validate_series_rows,
)
from rivretrieve._internal.store.provenance import encode_source_call
from rivretrieve._internal.store.reader import StoreReader
from rivretrieve._internal.store.validation import AccumulatedStoreManifest, StoreRoot, validate_store


@dataclass(frozen=True, slots=True)
class SuccessfulReplacement:
    coverage: CoverageInterval
    rows: pl.DataFrame
    replaced_facts_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StoreUpdate:
    series: tuple[SourceSeries, ...]
    inventories: tuple[InventorySnapshot, ...]
    outcomes: tuple[RetrievalOutcome, ...]
    replacements: tuple[SuccessfulReplacement, ...]
    issues: tuple[Issue, ...] = ()
    source_calls: tuple[dict[str, object], ...] = ()


def _coverage_json(item: CoverageInterval) -> dict[str, object]:
    return {
        "series_id": item.series_id,
        "start": item.interval.start.isoformat(timespec="microseconds"),
        "end": item.interval.end.isoformat(timespec="microseconds"),
        "retrieved_at": item.retrieved_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
        if item.retrieved_at is not None
        else None,
        "outcome_id": item.outcome_id,
        "facts_ids": list(item.facts_ids),
    }


def _merge_series(held: tuple[SourceSeries, ...], additions: tuple[SourceSeries, ...]) -> tuple[SourceSeries, ...]:
    definitions = {item.series_id: item for item in held}
    for item in additions:
        previous = definitions.get(item.series_id)
        if previous is None:
            definitions[item.series_id] = item
            continue
        if (
            previous.provider_id,
            previous.station_id,
            previous.product_id,
            previous.identity.namespace,
            previous.identity.published_id,
        ) != (item.provider_id, item.station_id, item.product_id, item.identity.namespace, item.identity.published_id):
            raise FatalContractError("Store update contradicts an existing concrete source identity")
        facts = {fact.facts_id: fact for fact in previous.facts}
        for fact in item.facts:
            if fact.facts_id in facts and fact != facts[fact.facts_id]:
                raise FatalContractError("Store update reinterprets existing physical facts")
            facts[fact.facts_id] = fact
        definitions[item.series_id] = item.model_copy(update={"facts": tuple(facts.values())})
    return tuple(definitions.values())


def _merge_records(held: tuple, additions: tuple, key: str, *, move_reobserved: bool = False) -> tuple:
    records = {getattr(item, key): item for item in held}
    for item in additions:
        identity = getattr(item, key)
        if identity in records and records[identity] != item:
            raise FatalContractError(f"Store update contradicts existing {key}")
        if move_reobserved:
            # Arrival order is knowledge about reacquisition, not an invented
            # source timestamp or a change to the immutable snapshot itself.
            records.pop(identity, None)
        records[identity] = item
    return tuple(records.values())


def accumulate(store: StoreRoot, provider_id: ProviderId, update: StoreUpdate) -> AccumulatedStoreManifest:
    """Replace only proven successful concrete-series intervals in one atomic batch.

    Inventory and unsuccessful outcomes are durable even without successful rows.
    Failed refreshes do not remove held native rows or successful coverage.
    """
    root = Path(store)
    root.parent.mkdir(parents=True, exist_ok=True)
    lock = root.with_name(f".{root.name}.write-lock")
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise FatalContractError(
            f'Store writer already active at "{lock}"; preserve and inspect before recovery'
        ) from error
    stage = root.with_name(f".{root.name}.pending-{uuid4().hex}")
    backup = root.with_name(f".{root.name}.backup-{uuid4().hex}")
    try:
        status = StoreReader().status(store, provider_id)
        previous = status.manifest
        if previous is not None and not isinstance(previous, AccumulatedStoreManifest):
            raise FatalContractError(f'Expected an accumulated store at "{store}"; refusing to modify a compiled store')
        held = previous.coverage if previous else ()
        counts = {str(key): value for key, value in previous.partition_row_counts.items()} if previous else {}
        series = _merge_series(previous.series if previous else (), update.series)
        inventories = _merge_records(
            previous.inventories if previous else (), update.inventories, "snapshot_id", move_reobserved=True
        )
        outcomes = _merge_records(previous.outcomes if previous else (), update.outcomes, "outcome_id")
        definitions = {item.series_id: item for item in series}
        outcome_by_id = {item.outcome_id: item for item in outcomes}
        replacements: list[SuccessfulReplacement] = []
        for replacement in update.replacements:
            coverage = replacement.coverage
            outcome = outcome_by_id.get(coverage.outcome_id)
            # Empty constructor facts mean the explicitly cited successful outcome's facts.
            # Persist the resolved facts; readers never infer missing on-disk coverage facts.
            coverage = replace(coverage, facts_ids=coverage.facts_ids or (outcome.facts_ids if outcome else ()))
            if (
                coverage.series_id not in definitions
                or outcome is None
                or outcome.series_id != coverage.series_id
                or outcome.status not in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY)
                or outcome.window.start != coverage.interval.start
                or outcome.window.end != coverage.interval.end
                or outcome.retrieved_at != coverage.retrieved_at
                or not coverage.facts_ids
                or not set(coverage.facts_ids).issubset(outcome.facts_ids)
            ):
                raise FatalContractError("Replacement requires an explicit successful concrete-series outcome")
            replaced_facts = replacement.replaced_facts_ids or coverage.facts_ids
            known_facts = {fact.facts_id for fact in definitions[coverage.series_id].facts}
            if (
                len(set(replaced_facts)) != len(replaced_facts)
                or not set(replaced_facts).issubset(known_facts)
                or not set(coverage.facts_ids).issubset(replaced_facts)
            ):
                raise FatalContractError("Replacement scope must identify known old and newly covered physical facts")
            rows = replacement.rows
            validate_series_rows(rows, series)
            if not rows.is_empty() and (
                rows.filter(pl.col("series_id") != coverage.series_id).height
                or rows.filter(~pl.col("time").is_between(coverage.interval.start, coverage.interval.end)).height
                or rows.filter(~pl.col("facts_id").is_in(coverage.facts_ids)).height
            ):
                raise FatalContractError("Replacement rows exceed their successful series interval or physical facts")
            if (outcome.status is OutcomeStatus.EMPTY) != rows.is_empty():
                raise FatalContractError("Successful empty and nonempty outcomes must match their native rows")
            replacements.append(replace(replacement, coverage=coverage))
        if root.exists():
            shutil.copytree(root, stage)
        else:
            stage.mkdir()
        for replacement in replacements:
            coverage, rows = replacement.coverage, replacement.rows
            definition = definitions[coverage.series_id]
            replaced_facts = replacement.replaced_facts_ids or coverage.facts_ids
            retained: list[CoverageInterval] = []
            for item in held:
                overlap_facts = tuple(fact_id for fact_id in item.facts_ids if fact_id in replaced_facts)
                if item.series_id != coverage.series_id or not overlap_facts:
                    retained.append(item)
                    continue
                unaffected = tuple(fact_id for fact_id in item.facts_ids if fact_id not in replaced_facts)
                if unaffected:
                    retained.append(replace(item, facts_ids=unaffected))
                retained.extend(
                    replace(item, interval=interval, facts_ids=overlap_facts)
                    for interval in remainder(item.interval, (coverage.interval,))
                )
            retained.append(coverage)
            held = tuple(retained)
            for year in range(coverage.interval.start.year, coverage.interval.end.year + 1):
                identifier = f"product={definition.product_id}/year={year:04d}"
                directory = stage / identifier
                additions = rows.filter(pl.col("time").dt.year() == year).select(
                    "station_id",
                    "time",
                    "time_zone",
                    "value",
                    pl.when(pl.col("value").is_null())
                    .then(pl.lit("published_null"))
                    .otherwise(pl.lit("published_value"))
                    .alias("value_state"),
                    "series_id",
                    "facts_id",
                    "source_unit",
                )
                if identifier in counts:
                    existing = next(directory.glob("*.parquet"))
                    retained_rows = pl.read_parquet(existing).filter(
                        ~(
                            (pl.col("series_id") == coverage.series_id)
                            & pl.col("facts_id").is_in(replaced_facts)
                            & pl.col("time").is_between(coverage.interval.start, coverage.interval.end)
                        )
                    )
                    additions = pl.concat([retained_rows, additions])
                    existing.unlink()
                if additions.is_empty():
                    counts.pop(identifier, None)
                    if directory.exists():
                        directory.rmdir()
                    continue
                directory.mkdir(parents=True, exist_ok=True)
                additions.sort("station_id", maintain_order=True).write_parquet(directory / "rows.parquet")
                counts[identifier] = additions.height
        issues = tuple(
            dict.fromkeys(item.model_dump_json() for item in (*(previous.issues if previous else ()), *update.issues))
        )
        calls = tuple(
            dict.fromkeys(
                json.dumps(encode_source_call(item), sort_keys=True)
                for item in (*(previous.source_calls if previous else ()), *update.source_calls)
            )
        )
        manifest = {
            "format_version": 7,
            "provider_id": str(provider_id),
            "built_at": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "coverage": [_coverage_json(item) for item in held],
            "partition_row_counts": counts,
            "series": [item.model_dump(mode="json") for item in series],
            "inventories": [item.model_dump(mode="json") for item in inventories],
            "outcomes": [item.model_dump(mode="json") for item in outcomes],
            "issues": [json.loads(item) for item in issues],
            "source_calls": [json.loads(item) for item in calls],
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        candidate = validate_store(StoreRoot(stage), provider_id).manifest
        assert isinstance(candidate, AccumulatedStoreManifest)
        if root.exists():
            root.rename(backup)
        try:
            stage.rename(root)
        except OSError:
            if backup.exists():
                backup.rename(root)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return candidate
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        lock.rmdir()

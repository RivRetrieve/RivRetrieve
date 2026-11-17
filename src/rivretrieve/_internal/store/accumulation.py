"""Atomically retain native series successes, inventory evidence and retrieval outcomes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from rivretrieve._internal.coverage import CoverageInterval, remainder
from rivretrieve._internal.engine import RowsSchema
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.publication_identity import publication_identity_fields
from rivretrieve._internal.source_annotations import (
    AnnotationBundle,
    AnnotationSchema,
    ObservationAnnotationTable,
    SeriesAnnotationTable,
    anti_join_native_with_annotations,
    concat_native_with_annotations,
    decode_observation_table_from_parquet,
    dump_annotation_schema,
    dump_series_annotations,
    encode_observation_table_for_parquet,
    filter_native_with_annotations_by_expr,
    merge_series_tables,
    sort_native_by_station_with_annotations,
    validate_bundle_for_result,
)
from rivretrieve._internal.source_series import (
    InventorySnapshot,
    OutcomeStatus,
    RetrievalOutcome,
    SourceSeries,
    stable_id,
    validate_series_rows,
)
from rivretrieve._internal.store.authority import compact_evidence
from rivretrieve._internal.store.integrity import (
    inspect_integrity,
    link_partition,
    refresh_witnesses,
    seal_store,
    verify_files,
)
from rivretrieve._internal.store.lifecycle import store_transaction
from rivretrieve._internal.store.provenance import encode_source_call
from rivretrieve._internal.store.validation import (
    AccumulatedStoreManifest,
    PartitionIdentifier,
    StoreRoot,
    _validate_metadata,
)
from rivretrieve._internal.time_axis import TimeAxis, axis_time_expression


@dataclass(frozen=True, slots=True)
class SuccessfulReplacement:
    coverage: CoverageInterval
    rows: pl.DataFrame
    replaced_facts_ids: tuple[str, ...] = ()
    annotations: AnnotationBundle = field(default_factory=AnnotationBundle.empty)


@dataclass(frozen=True, slots=True)
class StoreUpdate:
    """One live update with separate active and inventory-support acquisitions.

    ``supporting_outcomes`` cannot authorize rows, coverage or current issues.
    Publication discards support that no retained inventory references.
    """

    series: tuple[SourceSeries, ...]
    inventories: tuple[InventorySnapshot, ...]
    outcomes: tuple[RetrievalOutcome, ...]
    replacements: tuple[SuccessfulReplacement, ...]
    issues: tuple[Issue, ...] = ()
    source_calls: tuple[dict[str, object], ...] = ()
    supporting_outcomes: tuple[RetrievalOutcome, ...] = ()
    series_annotations: tuple[SeriesAnnotationTable, ...] = ()


def _coverage_json(item: CoverageInterval) -> dict[str, object]:
    return {
        "series_id": item.series_id,
        "axis": item.interval.axis.value,
        "start": item.interval.start.isoformat(timespec="microseconds"),
        "end": item.interval.end.isoformat(timespec="microseconds"),
        "retrieved_at": item.retrieved_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
        if item.retrieved_at is not None
        else None,
        "outcome_id": item.outcome_id,
        "facts_ids": list(item.facts_ids),
    }


_IDENTITY_ORIGIN_RANK = {"mapping": 0, "catalogue": 1, "response": 2}


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
        base = (
            previous
            if _IDENTITY_ORIGIN_RANK.get(previous.identity.origin, -1)
            > _IDENTITY_ORIGIN_RANK.get(item.identity.origin, -1)
            else item
        )
        definitions[item.series_id] = base.model_copy(update={"facts": tuple(facts.values())})
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


def _within_retention(instant: datetime | None, cutoff_utc: datetime) -> bool:
    return instant is not None and instant.astimezone(UTC) >= cutoff_utc


def _outcome_expired(item: RetrievalOutcome, cutoff_utc: datetime) -> bool:
    if item.status in (OutcomeStatus.SUCCESS, OutcomeStatus.EMPTY):
        return not _within_retention(item.retrieved_at, cutoff_utc)
    return item.retrieved_at is not None and not _within_retention(item.retrieved_at, cutoff_utc)


def manifest_has_expired_retention(manifest: AccumulatedStoreManifest, cutoff: datetime) -> bool:
    """Return whether any cached coverage, outcome, or live inventory predates ``cutoff``."""
    if cutoff.tzinfo is None:
        raise FatalContractError("Retention cutoff must be timezone-aware")
    cutoff_utc = cutoff.astimezone(UTC)
    if any(not _within_retention(item.retrieved_at, cutoff_utc) for item in manifest.coverage):
        return True
    if any(_outcome_expired(item, cutoff_utc) for item in manifest.outcomes):
        return True
    return any(
        item.origin != "catalogue" and not _within_retention(item.acquired_at, cutoff_utc)
        for item in manifest.inventories
    )


def _prepare_partition_links(
    store: StoreRoot,
    provider_id: ProviderId,
    stage: Path,
    sealed,
    affected_partitions: set[str],
    is_remote: bool,
    transaction,
):
    from rivretrieve._internal.store.remote import RemoteStoreTransaction, materialize_verified_remote_partitions

    reused = {}
    remote_reused = {}
    materialized_updates: dict[PartitionIdentifier, Path] = {}
    if sealed is None:
        return reused, remote_reused, materialized_updates
    obs_updated = tuple(key for key in sealed.store.partition_files if str(key) in affected_partitions)
    ann_updated = tuple(
        key
        for key in sealed.store.annotation_partition_files
        if "/".join(str(key).split("/")[:2]) in affected_partitions
    )
    updated_keys = (*obs_updated, *ann_updated)
    if is_remote:
        from rivretrieve._internal.store.integrity import _fail as _integrity_fail

        current = inspect_integrity(store, provider_id)
        if current.generation_id != sealed.generation_id:
            _integrity_fail(store, provider_id, "generation_changed")
        materialized_updates = materialize_verified_remote_partitions(current, updated_keys, transaction.workspace)
    else:
        verify_files(sealed, updated_keys)
    for identifier, source in sealed.store.all_partition_files.items():
        parent_id = "/".join(str(identifier).split("/")[:2])
        if parent_id not in affected_partitions:
            rel = source.relative_to(store).as_posix()
            if is_remote:
                remote_reused[identifier] = (rel, sealed.files[rel])
            else:
                destination = stage / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                reused[identifier] = link_partition(sealed, identifier, destination)
    if isinstance(transaction, RemoteStoreTransaction):
        transaction.set_reused_relpaths(rel for rel, _ in remote_reused.values())
    return reused, remote_reused, materialized_updates


def _read_sealed_partition(
    identifier: str,
    product: str,
    sealed,
    materialized_updates: dict[PartitionIdentifier, Path],
    is_remote: bool,
    schemas_by_id: dict[str, AnnotationSchema],
    ann_counts: dict[str, int],
) -> tuple[pl.DataFrame, AnnotationBundle]:
    key = PartitionIdentifier(identifier)
    existing_rows = pl.DataFrame(schema=RowsSchema.polars_schema)
    if sealed is not None and key in sealed.store.partition_files:
        source_parquet = materialized_updates[key] if is_remote else sealed.store.partition_files[key]
        physical = pl.read_parquet(source_parquet)
        existing_rows = physical.select(
            "station_id",
            pl.lit(product).alias("product_id"),
            "time",
            "value",
            "time_zone",
            "series_id",
            "facts_id",
            "source_unit",
        )
    existing_obs_tables: dict[str, ObservationAnnotationTable] = {}
    if sealed is not None:
        for ann_key, ann_path in sealed.store.annotation_partition_files.items():
            if "/".join(str(ann_key).split("/")[:2]) != identifier:
                continue
            ann_counts.pop(str(ann_key), None)
            schema_id = str(ann_key).split("/", 2)[2].removeprefix("annotations=")
            ann_source = materialized_updates[ann_key] if is_remote else ann_path
            existing_obs_tables[schema_id] = decode_observation_table_from_parquet(
                pl.read_parquet(ann_source), schemas_by_id[schema_id], existing_rows
            )
    return existing_rows, AnnotationBundle(observation_tables=existing_obs_tables)


def _write_partition_bundle(
    identifier: str,
    stage: Path,
    existing_rows: pl.DataFrame,
    existing_bundle: AnnotationBundle,
    counts: dict[str, int],
    ann_counts: dict[str, int],
    active_schemas: dict[str, AnnotationSchema],
) -> None:
    sorted_rows, sorted_bundle = sort_native_by_station_with_annotations(existing_rows, existing_bundle)
    if sorted_rows.is_empty():
        counts.pop(identifier, None)
    else:
        directory = stage / identifier
        directory.mkdir(parents=True, exist_ok=True)
        physical_out = sorted_rows.select(
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
        physical_out.write_parquet(directory / "rows.parquet")
        counts[identifier] = physical_out.height
    for schema_id, obs_table in sorted(sorted_bundle.observation_tables.items()):
        if obs_table.row_count == 0:
            continue
        ann_id = f"{identifier}/annotations={schema_id}"
        ann_dir = stage / ann_id
        ann_dir.mkdir(parents=True, exist_ok=True)
        encode_observation_table_for_parquet(obs_table, sorted_rows).write_parquet(ann_dir / "rows.parquet")
        ann_counts[ann_id] = obs_table.row_count
        active_schemas[schema_id] = obs_table.schema


def _publish_accumulated_stage(
    *,
    stage: Path,
    store: StoreRoot,
    provider_id: ProviderId,
    held: tuple[CoverageInterval, ...],
    counts: dict[str, int],
    retained_schemas: list[AnnotationSchema],
    ann_counts: dict[str, int],
    merged_series: dict[str, SeriesAnnotationTable],
    series: tuple[SourceSeries, ...],
    evidence,
    sealed,
    reused: dict[PartitionIdentifier, object],
    remote_reused: dict[PartitionIdentifier, object],
):
    from rivretrieve._internal.store.remote import RemoteStoreRoot, seal_remote_stage

    manifest = {
        "format_version": 9,
        "provider_id": str(provider_id),
        "built_at": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "coverage": [_coverage_json(item) for item in held],
        "partition_row_counts": counts,
        "annotation_schemas": [dump_annotation_schema(item) for item in retained_schemas],
        "annotation_partition_row_counts": ann_counts,
        "series_annotations": dump_series_annotations(merged_series),
        "series": [item.model_dump(mode="json") for item in series],
        "inventories": [item.model_dump(mode="json") for item in evidence.inventories],
        "outcomes": [item.model_dump(mode="json") for item in evidence.outcomes],
        "supporting_outcomes": [item.model_dump(mode="json") for item in evidence.supporting_outcomes],
        "issues": [item.model_dump(mode="json") for item in evidence.issues],
        "source_calls": [encode_source_call(item) for item in evidence.source_calls],
    }
    manifest.update(publication_identity_fields((provider_id,)))
    (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if isinstance(store, RemoteStoreRoot):
        certified = seal_remote_stage(stage, store, provider_id, previous=sealed, reused_identities=remote_reused)  # ty: ignore[invalid-argument-type]
    else:
        certified = seal_store(StoreRoot(stage), provider_id, previous=sealed, reused=reused)  # ty: ignore[invalid-argument-type]
    candidate = certified.store.manifest
    assert isinstance(candidate, AccumulatedStoreManifest)
    return certified, candidate


def evict_expired_retention(
    store: StoreRoot,
    provider_id: ProviderId,
    *,
    cutoff: datetime,
) -> AccumulatedStoreManifest | None:
    """Atomically evict cached records and physical rows whose retrieval predates ``cutoff``."""
    from rivretrieve._internal.store.remote import RemoteStoreRoot, RemoteStoreTransaction, remote_store_transaction

    if cutoff.tzinfo is None:
        raise FatalContractError("Retention cutoff must be timezone-aware")
    cutoff_utc = cutoff.astimezone(UTC)
    is_remote = isinstance(store, RemoteStoreRoot)
    tx_cm = remote_store_transaction(store) if is_remote else store_transaction(Path(store))
    with tx_cm as transaction:
        stage = transaction.stage
        store_exists = bool(store.client.list_objects(store.prefix)) if is_remote else Path(store).exists()
        if not store_exists:
            return None
        lease = None if isinstance(transaction, RemoteStoreTransaction) else transaction.lease
        sealed = inspect_integrity(store, provider_id, lease=lease)
        previous = sealed.store.manifest
        certified = None
        if not is_remote:

            def refresh_link_witnesses(path: Path) -> None:
                if transaction.committed and certified is not None:
                    refresh_witnesses(certified, StoreRoot(path))

            transaction.after_cleanup = refresh_link_witnesses
        if not isinstance(previous, AccumulatedStoreManifest):
            raise FatalContractError(f'Expected an accumulated store at "{store}"; refusing to modify a compiled store')
        kept_outcomes = tuple(item for item in previous.outcomes if not _outcome_expired(item, cutoff_utc))
        expired_outcomes = tuple(item for item in previous.outcomes if _outcome_expired(item, cutoff_utc))
        kept_outcome_ids = {item.outcome_id for item in kept_outcomes}
        kept_supporting = tuple(item for item in sealed.supporting_outcomes if not _outcome_expired(item, cutoff_utc))
        kept_all_outcome_ids = kept_outcome_ids | {item.outcome_id for item in kept_supporting}
        kept_coverage = tuple(
            item
            for item in previous.coverage
            if _within_retention(item.retrieved_at, cutoff_utc) and item.outcome_id in kept_outcome_ids
        )
        expired_coverage = tuple(item for item in previous.coverage if item not in kept_coverage)
        surviving_inventories = [
            item
            for item in previous.inventories
            if item.origin == "catalogue" or _within_retention(item.acquired_at, cutoff_utc)
        ]
        changed = True
        while changed:
            changed = False
            inv_ids = {item.snapshot_id for item in surviving_inventories}
            filtered_inventories = []
            for item in surviving_inventories:
                missing_ref = any(
                    (
                        ref.startswith("retrieval-outcome:")
                        and ref.removeprefix("retrieval-outcome:") not in kept_all_outcome_ids
                    )
                    or (ref.startswith("source-inventory:") and ref.removeprefix("source-inventory:") not in inv_ids)
                    for ref in item.evidence
                )
                if missing_ref:
                    changed = True
                    continue
                filtered_inventories.append(item)
            surviving_inventories = filtered_inventories
        referenced_catalogue = {
            ref.removeprefix("source-inventory:")
            for item in surviving_inventories
            if item.origin != "catalogue"
            for ref in item.evidence
            if ref.startswith("source-inventory:")
        }
        kept_inventories = tuple(
            item
            for item in surviving_inventories
            if item.origin != "catalogue" or item.snapshot_id in referenced_catalogue
        )
        if (
            len(kept_coverage) == len(previous.coverage)
            and len(kept_outcomes) == len(previous.outcomes)
            and len(kept_inventories) == len(previous.inventories)
            and len(kept_supporting) == len(sealed.supporting_outcomes)
        ):
            return previous

        expired_outcome_ids = {item.outcome_id for item in expired_outcomes}

        def _issue_expired_only(issue: Issue) -> bool:
            details = issue.details or {}
            explicit = details.get("outcome_id")
            if explicit is not None:
                return explicit in expired_outcome_ids
            matches_expired = any(
                item.reason == issue.message
                and all(
                    details.get(key) is None or details[key] == getattr(item, key)
                    for key in ("station_id", "product_id", "series_id")
                )
                for item in expired_outcomes
            )
            if not matches_expired:
                return False
            matches_kept = any(
                item.reason == issue.message
                and all(
                    details.get(key) is None or details[key] == getattr(item, key)
                    for key in ("station_id", "product_id", "series_id")
                )
                for item in kept_outcomes
            )
            return not matches_kept

        surviving_issues = tuple(item for item in previous.issues if not _issue_expired_only(item))
        evidence = compact_evidence(
            kept_coverage,
            kept_outcomes,
            kept_inventories,
            surviving_issues,
            previous.source_calls,
            supporting_outcomes=kept_supporting,
        )

        series_by_id = {item.series_id: item for item in previous.series}
        active_series_ids = (
            {item.series_id for item in kept_coverage}
            | {
                item.series_id
                for item in (*evidence.outcomes, *evidence.supporting_outcomes)
                if item.series_id is not None
            }
            | {member for inv in evidence.inventories for member in inv.members}
        )
        kept_series = tuple(item for item in previous.series if item.series_id in active_series_ids)
        dropped_series_products = {
            item.product_id for item in previous.series if item.series_id not in active_series_ids
        }

        affected_partitions: set[str] = set()
        for coverage in expired_coverage:
            product = series_by_id[coverage.series_id].product_id
            margin = 1 if coverage.interval.axis is TimeAxis.UTC else 0
            for year in range(coverage.interval.start.year - margin, coverage.interval.end.year + margin + 1):
                affected_partitions.add(f"product={product}/year={year:04d}")
        for outcome in expired_outcomes:
            if outcome.coverage == "observations" and outcome.status is OutcomeStatus.SUCCESS:
                for _, timestamp, _ in outcome.observation_keys:
                    affected_partitions.add(f"product={outcome.product_id}/year={timestamp.year:04d}")
        existing_partitions = set(map(str, previous.partition_row_counts)) | {
            "/".join(str(key).split("/")[:2]) for key in previous.annotation_partition_row_counts
        }
        affected_partitions = {
            identifier
            for identifier in existing_partitions
            if identifier in affected_partitions
            or identifier.split("/", 1)[0].removeprefix("product=") in dropped_series_products
        }

        stage.mkdir()
        counts = {str(key): value for key, value in previous.partition_row_counts.items()}
        ann_counts = {str(key): value for key, value in previous.annotation_partition_row_counts.items()}
        reused, remote_reused, materialized_updates = _prepare_partition_links(
            store, provider_id, stage, sealed, affected_partitions, is_remote, transaction
        )
        schemas_by_id = {item.schema_id: item for item in previous.annotation_schemas}
        active_schemas = dict(schemas_by_id)
        for identifier in sorted(affected_partitions):
            product = identifier.split("/", 1)[0].removeprefix("product=")
            year = int(identifier.rsplit("=", 1)[1])
            existing_rows, existing_bundle = _read_sealed_partition(
                identifier, product, sealed, materialized_updates, is_remote, schemas_by_id, ann_counts
            )
            part_cov = tuple(
                item
                for item in kept_coverage
                if series_by_id[item.series_id].product_id == product
                and (item.interval.start.year - (1 if item.interval.axis is TimeAxis.UTC else 0))
                <= year
                <= (item.interval.end.year + (1 if item.interval.axis is TimeAxis.UTC else 0))
            )
            part_obs_keys: dict[tuple[str, str, str], list[datetime]] = {}
            for outcome in evidence.outcomes:
                if (
                    outcome.coverage == "observations"
                    and outcome.status is OutcomeStatus.SUCCESS
                    and outcome.series_id is not None
                    and outcome.product_id == product
                ):
                    for facts_id, timestamp, time_zone in outcome.observation_keys:
                        if timestamp.year == year:
                            part_obs_keys.setdefault((outcome.series_id, facts_id, time_zone), []).append(timestamp)
            if not part_cov and not part_obs_keys:
                counts.pop(identifier, None)
                continue
            keep_expr = pl.lit(False)
            for cov in part_cov:
                keep_expr = keep_expr | (
                    (pl.col("series_id") == cov.series_id)
                    & pl.col("facts_id").is_in(cov.facts_ids)
                    & axis_time_expression(cov.interval.axis).is_between(cov.interval.start, cov.interval.end)
                )
            for (sid, fid, tz), times in part_obs_keys.items():
                keep_expr = keep_expr | (
                    (pl.col("series_id") == sid)
                    & (pl.col("facts_id") == fid)
                    & (pl.col("time_zone") == tz)
                    & pl.col("time").is_in(times)
                )
            filtered_rows, filtered_bundle = filter_native_with_annotations_by_expr(
                existing_rows,
                existing_bundle,
                keep_expr,
                allowed_series_ids=active_series_ids,
            )
            _write_partition_bundle(
                identifier, stage, filtered_rows, filtered_bundle, counts, ann_counts, active_schemas
            )

        merged_series = merge_series_tables(
            list(previous.series_annotations),
            conflict="prefer_last",
            allowed_series_ids=active_series_ids,
        )
        for table in merged_series.values():
            active_schemas[table.schema.schema_id] = table.schema
        used_schema_ids = {ann_key.split("/", 2)[2].removeprefix("annotations=") for ann_key in ann_counts} | set(
            merged_series
        )
        retained_schemas = [active_schemas[sid] for sid in sorted(used_schema_ids)]
        certified, candidate = _publish_accumulated_stage(
            stage=stage,
            store=store,
            provider_id=provider_id,
            held=kept_coverage,
            counts=counts,
            retained_schemas=retained_schemas,
            ann_counts=ann_counts,
            merged_series=merged_series,
            series=kept_series,
            evidence=evidence,
            sealed=sealed,
            reused=reused,
            remote_reused=remote_reused,
        )
        transaction.publish(lambda _: certified)
        return candidate


def accumulate(store: StoreRoot, provider_id: ProviderId, update: StoreUpdate) -> AccumulatedStoreManifest:
    """Replace only proven successful concrete-series intervals in one atomic batch.

    Inventory and unsuccessful outcomes are durable even without successful rows.
    Failed refreshes do not remove held native rows or successful coverage.
    """
    from rivretrieve._internal.store.remote import (
        RemoteStoreRoot,
        RemoteStoreTransaction,
        remote_store_transaction,
    )

    is_remote = isinstance(store, RemoteStoreRoot)
    tx_cm = remote_store_transaction(store) if is_remote else store_transaction(Path(store))
    with tx_cm as transaction:
        stage = transaction.stage
        store_exists = bool(store.client.list_objects(store.prefix)) if is_remote else Path(store).exists()
        lease = None if isinstance(transaction, RemoteStoreTransaction) else transaction.lease
        sealed = inspect_integrity(store, provider_id, lease=lease) if store_exists else None
        previous = sealed.store.manifest if sealed else None
        certified = None

        if not is_remote:

            def refresh_link_witnesses(path: Path) -> None:
                # An aborted attempt may have discovered pre-existing ctime drift.
                # Never refresh that unverified prior witness. Retry hashes the
                # original digest before it can inherit an unchanged partition.
                if transaction.committed and certified is not None:
                    refresh_witnesses(certified, StoreRoot(path))

            transaction.after_cleanup = refresh_link_witnesses
        if previous is not None and not isinstance(previous, AccumulatedStoreManifest):
            raise FatalContractError(f'Expected an accumulated store at "{store}"; refusing to modify a compiled store')
        held = previous.coverage if previous else ()
        held_by_series: dict[str, list[CoverageInterval]] = {}
        for item in held:
            held_by_series.setdefault(item.series_id, []).append(item)
        counts = {str(key): value for key, value in previous.partition_row_counts.items()} if previous else {}
        ann_counts = (
            {str(key): value for key, value in previous.annotation_partition_row_counts.items()} if previous else {}
        )
        series = _merge_series(previous.series if previous else (), update.series)
        inventories = _merge_records(
            previous.inventories if previous else (), update.inventories, "snapshot_id", move_reobserved=True
        )
        accepted_keys = {
            item.coverage.outcome_id: tuple(
                dict.fromkeys(item.rows.select("facts_id", "time", "time_zone").iter_rows())
            )
            for item in update.replacements
        }
        durable_outcomes = tuple(
            item.model_copy(
                update={
                    "observation_keys": accepted_keys.get(item.outcome_id, ()),
                    "outcome_id": item.outcome_id
                    if item.observation_keys == accepted_keys.get(item.outcome_id, ())
                    else stable_id(item.outcome_id, "unretained-observations"),
                }
            )
            if item.coverage == "observations"
            else item
            for item in update.outcomes
        )
        outcomes = _merge_records(previous.outcomes if previous else (), durable_outcomes, "outcome_id")
        outcome_by_id = {item.outcome_id: item for item in outcomes}
        supporting_outcomes = _merge_records(
            sealed.supporting_outcomes if sealed else (), update.supporting_outcomes, "outcome_id"
        )
        # Support is immutable source evidence, not an admitted row snapshot.
        for item in supporting_outcomes:
            if item.outcome_id in outcome_by_id and outcome_by_id[item.outcome_id] != item:
                raise FatalContractError("Conflicting current and inventory-support acquisition identities")
        # Validate incoming evidence before compaction can remove a record. A
        # malformed stage result must remain fatal even when it has no live support.
        _validate_metadata(
            {
                "series": [item.model_dump(mode="json") for item in series],
                "inventories": [item.model_dump(mode="json") for item in inventories],
                "outcomes": [item.model_dump(mode="json") for item in outcomes],
                "supporting_outcomes": [
                    item.model_dump(mode="json") for item in supporting_outcomes if item.outcome_id not in outcome_by_id
                ],
                "issues": [
                    item.model_dump(mode="json") for item in (*(previous.issues if previous else ()), *update.issues)
                ],
                "source_calls": [
                    encode_source_call(item)
                    for item in (*(previous.source_calls if previous else ()), *update.source_calls)
                ],
            },
            store,
            provider_id,
        )
        definitions = {item.series_id: item for item in series}
        replacements: list[SuccessfulReplacement] = []
        snapshot_keys: set[tuple[str, str, datetime, str]] = set()
        acquisition_axes: dict[tuple[str, str], TimeAxis] = {}
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
            for facts_id in replaced_facts:
                key = coverage.series_id, facts_id
                previous_axis = acquisition_axes.setdefault(key, coverage.interval.axis)
                if previous_axis is not coverage.interval.axis:
                    raise FatalContractError("One source series cannot mix acquisition time axes")
            if any(
                item.series_id == coverage.series_id
                and set(item.facts_ids).intersection(replaced_facts)
                and item.interval.axis is not coverage.interval.axis
                for item in held_by_series.get(coverage.series_id, ())
            ):
                raise FatalContractError("Stored source series cannot change its acquisition time axis")
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
                rows.select(axis_time_expression(coverage.interval.axis).is_null().any()).item()
                or rows.filter(pl.col("series_id") != coverage.series_id).height
                or rows.filter(
                    ~axis_time_expression(coverage.interval.axis).is_between(
                        coverage.interval.start, coverage.interval.end
                    )
                ).height
                or rows.filter(~pl.col("facts_id").is_in(coverage.facts_ids)).height
            ):
                raise FatalContractError("Replacement rows exceed their successful series interval or physical facts")
            if outcome.coverage == "observations":
                keys = tuple(rows.select("facts_id", "time", "time_zone").iter_rows())
                if set(outcome.observation_keys) != set(keys):
                    raise FatalContractError("Snapshot outcome keys must identify exactly its acquired rows")
                identities = {(coverage.series_id, *key) for key in keys}
                if snapshot_keys.intersection(identities):
                    raise FatalContractError("Independent snapshot replacements overlap observation keys")
                snapshot_keys.update(identities)
            if (outcome.status is OutcomeStatus.EMPTY) != rows.is_empty():
                raise FatalContractError("Successful empty and nonempty outcomes must match their native rows")
            validate_bundle_for_result(replacement.annotations, rows, series)
            for table in replacement.annotations.observation_tables.values():
                if table.row_count > 0 and (
                    table.rows.select(axis_time_expression(coverage.interval.axis).is_null().any()).item()
                    or table.rows.filter(pl.col("series_id") != coverage.series_id).height
                    or table.rows.filter(
                        ~axis_time_expression(coverage.interval.axis).is_between(
                            coverage.interval.start, coverage.interval.end
                        )
                    ).height
                    or table.rows.filter(~pl.col("facts_id").is_in(coverage.facts_ids)).height
                ):
                    raise FatalContractError(
                        "Replacement annotations exceed their successful series interval or physical facts"
                    )
            replacements.append(replace(replacement, coverage=coverage))
        stage.mkdir()
        partition_updates: dict[str, list[SuccessfulReplacement]] = {}
        for replacement in replacements:
            coverage, rows = replacement.coverage, replacement.rows
            definition = definitions[coverage.series_id]
            replaced_facts = replacement.replaced_facts_ids or coverage.facts_ids
            retained: list[CoverageInterval] = []
            existing_coverage = held_by_series.get(coverage.series_id, [])
            for item in existing_coverage:
                overlap_facts = tuple(fact_id for fact_id in item.facts_ids if fact_id in replaced_facts)
                if (
                    item.series_id != coverage.series_id
                    or not overlap_facts
                    or item.interval.axis is not coverage.interval.axis
                ):
                    retained.append(item)
                    continue
                unaffected = tuple(fact_id for fact_id in item.facts_ids if fact_id not in replaced_facts)
                if unaffected:
                    retained.append(replace(item, facts_ids=unaffected))
                retained.extend(
                    replace(item, interval=interval, facts_ids=overlap_facts)
                    for interval in remainder(item.interval, (coverage.interval,))
                )
            observation_only = outcome_by_id[coverage.outcome_id].coverage == "observations"
            if observation_only:
                retained = existing_coverage
            else:
                retained.append(coverage)
            held_by_series[coverage.series_id] = retained
            margin = 1 if coverage.interval.axis is TimeAxis.UTC else 0
            for year in range(coverage.interval.start.year - margin, coverage.interval.end.year + margin + 1):
                identifier = f"product={definition.product_id}/year={year:04d}"
                partition_updates.setdefault(identifier, []).append(replacement)
        active_schemas: dict[str, AnnotationSchema] = (
            {item.schema_id: item for item in previous.annotation_schemas} if previous else {}
        )
        reused, remote_reused, materialized_updates = _prepare_partition_links(
            store, provider_id, stage, sealed, set(partition_updates), is_remote, transaction
        )
        schemas_by_id = {item.schema_id: item for item in previous.annotation_schemas} if previous else {}
        for identifier, changes in partition_updates.items():
            product = identifier.split("/", 1)[0].removeprefix("product=")
            year = int(identifier.rsplit("=", 1)[1])
            existing_rows, existing_bundle = _read_sealed_partition(
                identifier, product, sealed, materialized_updates, is_remote, schemas_by_id, ann_counts
            )
            for replacement in changes:
                coverage = replacement.coverage
                replaced_facts = replacement.replaced_facts_ids or coverage.facts_ids
                part_rows, part_bundle = filter_native_with_annotations_by_expr(
                    replacement.rows,
                    replacement.annotations,
                    pl.col("time").dt.year() == year,
                    allowed_series_ids={coverage.series_id},
                )
                part_obs_bundle = AnnotationBundle(observation_tables=part_bundle.observation_tables)
                if outcome_by_id[coverage.outcome_id].coverage == "observations":
                    existing_rows, existing_bundle = anti_join_native_with_annotations(
                        existing_rows, existing_bundle, part_rows
                    )
                else:
                    keep_expr = ~(
                        (pl.col("series_id") == coverage.series_id)
                        & pl.col("facts_id").is_in(replaced_facts)
                        & axis_time_expression(coverage.interval.axis).is_between(
                            coverage.interval.start, coverage.interval.end
                        )
                    )
                    existing_rows, existing_bundle = filter_native_with_annotations_by_expr(
                        existing_rows, existing_bundle, keep_expr
                    )
                existing_rows, existing_bundle = concat_native_with_annotations(
                    [(existing_rows, existing_bundle), (part_rows, part_obs_bundle)],
                    empty_schema=RowsSchema.polars_schema,
                )
            _write_partition_bundle(
                identifier, stage, existing_rows, existing_bundle, counts, ann_counts, active_schemas
            )
        merged_series = merge_series_tables(
            [
                *(previous.series_annotations if previous else ()),
                *update.series_annotations,
                *(table for rep in replacements for table in rep.annotations.series_tables.values()),
            ],
            conflict="prefer_last",
            allowed_series_ids=set(definitions),
        )
        for table in merged_series.values():
            active_schemas[table.schema.schema_id] = table.schema
        used_schema_ids = {ann_key.split("/", 2)[2].removeprefix("annotations=") for ann_key in ann_counts} | set(
            merged_series
        )
        retained_schemas = [active_schemas[sid] for sid in sorted(used_schema_ids)]
        held = tuple(item for records in held_by_series.values() for item in records)
        all_issues = {item.model_dump_json(): item for item in (*(previous.issues if previous else ()), *update.issues)}
        all_calls = {
            json.dumps(encode_source_call(item), sort_keys=True): item
            for item in (*(previous.source_calls if previous else ()), *update.source_calls)
        }
        evidence = compact_evidence(
            held,
            outcomes,
            inventories,
            tuple(all_issues.values()),
            tuple(all_calls.values()),
            supporting_outcomes=supporting_outcomes,
            new_outcome_ids=frozenset(item.outcome_id for item in durable_outcomes),
            new_inventory_ids=frozenset(item.snapshot_id for item in update.inventories),
        )
        certified, candidate = _publish_accumulated_stage(
            stage=stage,
            store=store,
            provider_id=provider_id,
            held=held,
            counts=counts,
            retained_schemas=retained_schemas,
            ann_counts=ann_counts,
            merged_series=merged_series,
            series=series,
            evidence=evidence,
            sealed=sealed,
            reused=reused,
            remote_reused=remote_reused,
        )
        transaction.publish(lambda _: certified)
        return candidate

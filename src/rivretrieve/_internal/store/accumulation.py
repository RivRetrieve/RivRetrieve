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
    from rivretrieve._internal.store.remote import (
        RemoteStoreRoot,
        RemoteStoreTransaction,
        materialize_verified_remote_partitions,
        remote_store_transaction,
        seal_remote_stage,
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
        reused = {}
        remote_reused = {}
        materialized_updates: dict[PartitionIdentifier, Path] = {}
        if sealed is not None:
            obs_updated = tuple(key for key in sealed.store.partition_files if str(key) in partition_updates)
            ann_updated = tuple(
                key
                for key in sealed.store.annotation_partition_files
                if "/".join(str(key).split("/")[:2]) in partition_updates
            )
            updated_keys = (*obs_updated, *ann_updated)
            if is_remote:
                from rivretrieve._internal.store.integrity import _fail as _integrity_fail

                current = inspect_integrity(store, provider_id)
                if current.generation_id != sealed.generation_id:
                    _integrity_fail(store, provider_id, "generation_changed")
                materialized_updates = materialize_verified_remote_partitions(
                    current, updated_keys, transaction.workspace
                )
            else:
                verify_files(sealed, updated_keys)
        if sealed is not None:
            for identifier, source in sealed.store.all_partition_files.items():
                parent_id = "/".join(str(identifier).split("/")[:2])
                if parent_id not in partition_updates:
                    rel = source.relative_to(store).as_posix()
                    if is_remote:
                        remote_reused[identifier] = (rel, sealed.files[rel])
                    else:
                        destination = stage / rel
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        reused[identifier] = link_partition(sealed, identifier, destination)
            if isinstance(transaction, RemoteStoreTransaction):
                transaction.set_reused_relpaths(rel for rel, _ in remote_reused.values())
        schemas_by_id = {item.schema_id: item for item in previous.annotation_schemas} if previous else {}
        for identifier, changes in partition_updates.items():
            product = identifier.split("/", 1)[0].removeprefix("product=")
            year = int(identifier.rsplit("=", 1)[1])
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
            existing_bundle = AnnotationBundle(observation_tables=existing_obs_tables)
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
            certified = seal_remote_stage(stage, store, provider_id, previous=sealed, reused_identities=remote_reused)
        else:
            certified = seal_store(StoreRoot(stage), provider_id, previous=sealed, reused=reused)
        candidate = certified.store.manifest
        assert isinstance(candidate, AccumulatedStoreManifest)
        transaction.publish(lambda _: certified)
        return candidate

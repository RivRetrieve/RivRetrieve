"""accumulate : StoreRoot × ProviderId × Rows × CoverageInterval → AccumulatedStoreManifest (atomic write)."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import polars as pl

from rivretrieve._internal.coverage import CoverageInterval, remainder
from rivretrieve._internal.engine import Rows
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.store.reader import StoreReader
from rivretrieve._internal.store.validation import (
    AccumulatedStoreManifest,
    StoreRoot,
    validate_store,
)


def _coverage_json(item: CoverageInterval) -> dict[str, str]:
    return {
        "station_id": item.station_id,
        "product_id": str(item.product_id),
        "start": item.interval.start.isoformat(timespec="microseconds"),
        "end": item.interval.end.isoformat(timespec="microseconds"),
        "retrieved_at": item.retrieved_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
    }


def accumulate(
    store: StoreRoot, provider_id: ProviderId, rows: Rows, coverage: CoverageInterval
) -> AccumulatedStoreManifest:
    """Replace one successfully retrieved interval, retaining source duplicates and all other intervals."""
    root = Path(store)
    StoreReader().status(store, provider_id)
    held: tuple[CoverageInterval, ...] = ()
    counts: dict[str, int] = {}
    if root.exists():
        validated = validate_store(store, provider_id)
        if not isinstance(validated.manifest, AccumulatedStoreManifest):
            raise FatalContractError(f'Expected an accumulated store at "{store}"; refusing to modify a compiled store')
        held = validated.manifest.coverage
        counts = {str(key): value for key, value in validated.manifest.partition_row_counts.items()}
    retained: list[CoverageInterval] = []
    for item in held:
        if item.station_id != coverage.station_id or item.product_id != coverage.product_id:
            retained.append(item)
        else:
            retained.extend(
                CoverageInterval(item.station_id, item.product_id, interval, item.retrieved_at)
                for interval in remainder(item.interval, (coverage.interval,))
            )
    retained.append(coverage)
    rows = rows.filter(
        (pl.col("station_id") == coverage.station_id)
        & (pl.col("product_id") == coverage.product_id)
        & pl.col("time").is_between(coverage.interval.start, coverage.interval.end)
    )
    root.parent.mkdir(parents=True, exist_ok=True)
    stage = root.with_name(f".{root.name}.pending-{uuid4().hex}")
    backup = root.with_name(f".{root.name}.backup-{uuid4().hex}")
    try:
        if root.exists():
            shutil.copytree(root, stage)
        else:
            stage.mkdir()
        for year in range(coverage.interval.start.year, coverage.interval.end.year + 1):
            identifier = f"product={coverage.product_id}/year={year:04d}"
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
            )
            if identifier in counts:
                existing = next(directory.glob("*.parquet"))
                previous = pl.read_parquet(existing).filter(
                    ~(
                        (pl.col("station_id") == coverage.station_id)
                        & pl.col("time").is_between(coverage.interval.start, coverage.interval.end)
                    )
                )
                additions = pl.concat([previous, additions])
                existing.unlink()
            if additions.is_empty():
                counts.pop(identifier, None)
                if directory.exists():
                    directory.rmdir()
                continue
            directory.mkdir(parents=True, exist_ok=True)
            additions.sort("station_id", maintain_order=True).write_parquet(directory / "rows.parquet")
            counts[identifier] = additions.height
        manifest = {
            "format_version": 4,
            "provider_id": str(provider_id),
            "built_at": datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "coverage": [_coverage_json(item) for item in retained],
            "partition_row_counts": counts,
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

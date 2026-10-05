"""Measure authored live updates without network or persistent stores.

Run ``uv run python tests/benchmarks/accumulation.py`` from the revision under test.
The same script supplies identical inline fixtures to both revisions. Every case
starts from a fresh store. Read metrics sum logical file sizes per open, not
physical I/O or decoded column bytes. Hash metrics count complete file contents.
Timing includes instrumentation and warm filesystem caches, with no time threshold.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import polars as pl

from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval
from rivretrieve._internal.engine import RowsSchema
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import (
    OutcomeStatus,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    known,
)
from rivretrieve._internal.store import StoreRoot, validate_store, validation
from rivretrieve._internal.store import accumulation as implementation
from rivretrieve._internal.store.accumulation import StoreUpdate, SuccessfulReplacement, accumulate

PROVIDER = ProviderId("fixture_live")
STAMP = datetime(2026, 9, 1, tzinfo=UTC)
FIXTURE = {
    "years": [1, 10, 30],
    "first_year": 2000,
    "rows_per_partition": 1000,
    "repeats": 5,
    "initial_value": 1.0,
    "time_zone": "unknown",
    "source_unit": "cm",
}
METRICS = (
    "validation_opened_file_bytes",
    "validation_opens",
    "data_copied_bytes",
    "data_read_file_bytes",
    "partition_reads",
    "data_written_bytes",
    "partition_writes",
    "data_hashed_bytes",
    "metadata_hashed_bytes",
)


def _update(year, identity, stamp, values, *, month=None, failed=False):
    facts = PhysicalFacts(
        facts_id="benchmark-facts",
        quantity=known("stage", "authored"),
        source_unit=known("cm", "authored"),
        normalized_unit="cm",
    )
    definition = SourceSeries(
        series_id="benchmark-series",
        provider_id=str(PROVIDER),
        station_id="a",
        product_id="level",
        identity=SourceIdentity(namespace="authored", origin="mapping", evidence=("authored",)),
        facts=(facts,),
    )
    start = datetime(year, month or 1, 1)
    end = datetime(year, month or 12, 28 if month else 31, 23, 59, 59, 999999)
    outcome = RetrievalOutcome(
        outcome_id=identity,
        series_id=definition.series_id,
        station_id="a",
        product_id="level",
        window=SeriesWindow(start=start, end=end),
        status=OutcomeStatus.FAILED if failed else OutcomeStatus.SUCCESS,
        facts_ids=(facts.facts_id,),
        retrieved_at=stamp,
        calls=(identity,),
        reason="Authored transport failure" if failed else None,
    )
    rows = pl.DataFrame(
        {
            "station_id": ["a"] * len(values),
            "product_id": ["level"] * len(values),
            "time": [start] * len(values),
            "value": values,
            "time_zone": ["unknown"] * len(values),
            "series_id": [definition.series_id] * len(values),
            "facts_id": [facts.facts_id] * len(values),
            "source_unit": ["cm"] * len(values),
        },
        schema=RowsSchema.polars_schema,
    )
    coverage = CoverageInterval(definition.series_id, RequestedInterval(start, end), stamp, identity)
    issue = Issue(
        severity="error",
        code="source.request_failed",
        message="Authored transport failure",
        details={"outcome_id": identity},
    )
    return StoreUpdate(
        (definition,),
        (),
        (outcome,),
        () if failed else (SuccessfulReplacement(coverage, rows),),
        (issue,) if failed else (),
        ({"call_id": identity, "retrieved_at": stamp, "url": "https://example.invalid/authored"},),
    )


def _measure(store, updates):
    counts = Counter(dict.fromkeys(METRICS, 0))
    read, write, opened, copy = pl.read_parquet, pl.DataFrame.write_parquet, validation._open_parquet, shutil.copyfile
    try:
        from rivretrieve._internal.store import integrity
    except ImportError:
        integrity = None
    digest = integrity._digest if integrity is not None else None

    def read_count(path, *args, **kwargs):
        counts["data_read_file_bytes"] += Path(path).stat().st_size
        counts["partition_reads"] += 1
        return read(path, *args, **kwargs)

    def write_count(frame, path, *args, **kwargs):
        result = write(frame, path, *args, **kwargs)
        counts["data_written_bytes"] += Path(path).stat().st_size
        counts["partition_writes"] += 1
        return result

    def open_count(path):
        counts["validation_opened_file_bytes"] += Path(path).stat().st_size
        counts["validation_opens"] += 1
        return opened(path)

    def copy_count(src, dst, *args, **kwargs):
        if Path(src).suffix == ".parquet":
            counts["data_copied_bytes"] += Path(src).stat().st_size
        return copy(src, dst, *args, **kwargs)

    def digest_count(path):
        counts["data_hashed_bytes" if Path(path).suffix == ".parquet" else "metadata_hashed_bytes"] += (
            Path(path).stat().st_size
        )
        assert digest is not None
        return digest(path)

    with ExitStack() as stack:
        stack.enter_context(patch.object(pl, "read_parquet", read_count))
        stack.enter_context(patch.object(pl.DataFrame, "write_parquet", write_count))
        stack.enter_context(patch.object(validation, "_open_parquet", open_count))
        stack.enter_context(patch.object(shutil, "copyfile", copy_count))
        if integrity is not None:
            stack.enter_context(patch.object(integrity, "_digest", digest_count))
        start = time.perf_counter()
        for update in updates:
            manifest = accumulate(store, PROVIDER, update)
        elapsed = time.perf_counter() - start
    return manifest, elapsed, dict(counts)


def main():
    checkout = Path(implementation.__file__).resolve().parents[4]
    commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    hardware = platform.processor()
    if sys.platform == "darwin":
        hardware = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
    print(
        json.dumps(
            {
                "python": sys.version,
                "python_executable": sys.executable,
                "polars": pl.__version__,
                "platform": platform.platform(),
                "machine": platform.machine(),
                "cpu": hardware,
                "logical_cpus": os.cpu_count(),
                "commit": commit,
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "fixture_sha256": hashlib.sha256(
                    (json.dumps(FIXTURE, sort_keys=True) + inspect.getsource(_update)).encode()
                ).hexdigest(),
                "fixture": FIXTURE,
                "accumulation_source": implementation.__file__,
                "validation_source": validation.__file__,
            }
        ),
        flush=True,
    )
    for years in FIXTURE["years"]:
        for scenario in ("small", "metadata", "repeated", "metadata_repeated", "two_replacements"):
            with tempfile.TemporaryDirectory(prefix="rr-accumulation-bench-") as temporary:
                store = StoreRoot(Path(temporary) / "store")
                for year in range(2000, 2000 + years):
                    accumulate(store, PROVIDER, _update(year, f"initial-{year}", STAMP, [1.0] * 1000))
                updates = []
                count = 5 if "repeated" in scenario else 1
                for index in range(count):
                    stamp = STAMP + timedelta(days=index + 1)
                    updates.append(
                        _update(
                            2000, f"update-{index}", stamp, [float(index + 2)], failed=scenario.startswith("metadata")
                        )
                    )
                if scenario == "two_replacements":
                    parts = [
                        _update(
                            2000, f"replacement-{month}", STAMP + timedelta(days=1), [float(month + 1)], month=month
                        )
                        for month in (1, 2)
                    ]
                    updates = [
                        StoreUpdate(
                            parts[0].series,
                            (),
                            tuple(p.outcomes[0] for p in parts),
                            tuple(p.replacements[0] for p in parts),
                            (),
                            tuple(p.source_calls[0] for p in parts),
                        )
                    ]
                manifest, elapsed, counts = _measure(store, updates)
                # Independent row/support checks occur outside the measured interval.
                checked = validate_store(store, PROVIDER)
                target = pl.read_parquet(next((store / "product=level/year=2000").glob("*.parquet")))
                expected = (
                    [1.0] * 1000
                    if scenario.startswith("metadata")
                    else [2.0, 3.0]
                    if scenario == "two_replacements"
                    else [float(count + 1)]
                )
                assert target["value"].to_list() == expected
                expected_times = (
                    [datetime(2000, 1, 1), datetime(2000, 2, 1)]
                    if scenario == "two_replacements"
                    else [datetime(2000, 1, 1)] * len(expected)
                )
                assert target["time"].to_list() == expected_times
                assert target["time_zone"].to_list() == ["unknown"] * len(expected)
                assert target["source_unit"].to_list() == ["cm"] * len(expected)
                assert sum(checked.manifest.partition_row_counts.values()) == 1000 * (years - 1) + len(expected)
                expected_stamp = STAMP if scenario.startswith("metadata") else STAMP + timedelta(days=count)
                coverage = [item for item in manifest.coverage if item.interval.start.year == 2000]
                if scenario != "two_replacements":
                    assert {item.retrieved_at for item in coverage} == {expected_stamp}
                else:
                    replaced = [item for item in coverage if item.outcome_id.startswith("replacement-")]
                    assert len(replaced) == 2
                    assert {item.retrieved_at for item in replaced} == {STAMP + timedelta(days=1)}
                for identifier, path in checked.partition_files.items():
                    if "year=2000" not in str(identifier):
                        assert pl.read_parquet(path)["value"].to_list() == [1.0] * 1000
                print(
                    json.dumps(
                        {
                            "scenario": scenario,
                            "partitions": years,
                            "elapsed": elapsed,
                            "counts": counts,
                            "outcomes": len(manifest.outcomes),
                            "supporting_outcomes": len(
                                json.loads((store / "manifest.json").read_text()).get("supporting_outcomes", ())
                            ),
                            "inventories": len(manifest.inventories),
                            "issues": len(manifest.issues),
                            "calls": len(manifest.source_calls),
                            "coverage": len(manifest.coverage),
                            "rows_and_acquisition_times_checked": True,
                        }
                    ),
                    flush=True,
                )


if __name__ == "__main__":
    main()

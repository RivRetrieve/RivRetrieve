"""Old identity-collapsed stores must be refused without opening their rows."""

import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    known,
)
from rivretrieve._internal.store import ObservationStoreRefusedError, StoreReader, StoreRoot, validation
from rivretrieve._internal.store.accumulation import StoreUpdate, SuccessfulReplacement, accumulate
from rivretrieve._internal.store.reader import StoreQuery


@pytest.mark.parametrize(
    ("fixture", "provider", "revision"),
    [
        ("valid_future_austria", "fixture_bulk", 2),
        ("accumulated/valid_native_rows", "fixture_live", 4),
    ],
)
def test_collapsed_store_revision_refused_before_parquet_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture: str, provider: str, revision: int
) -> None:
    original = Path(__file__).parent / "test_data/observation_store_conformance" / fixture
    store = tmp_path / "held-store"
    shutil.copytree(original, store)
    before = {p.relative_to(store): hashlib.sha256(p.read_bytes()).hexdigest() for p in store.rglob("*") if p.is_file()}
    opened: list[Path] = []
    native_open = validation._open_parquet

    def record_open(path: Path):
        opened.append(path)
        return native_open(path)

    monkeypatch.setattr(validation, "_open_parquet", record_open)
    try:
        with pytest.raises(ObservationStoreRefusedError, match=f"unsupported format revision {revision}"):
            StoreReader().status(StoreRoot(store), ProviderId(provider))
    finally:
        print(f"revision={revision}; actual parquet opens={len(opened)}")
    assert opened == []
    after = {p.relative_to(store): hashlib.sha256(p.read_bytes()).hexdigest() for p in store.rglob("*") if p.is_file()}
    assert after == before


def _definition(identity: str) -> SourceSeries:
    return SourceSeries(
        series_id=identity,
        provider_id="fixture_live",
        station_id="a",
        product_id="level",
        identity=SourceIdentity(
            namespace="recorded-field", published_id=identity, origin="response", evidence=("fixture",)
        ),
        facts=(
            PhysicalFacts(
                facts_id="facts",
                quantity=known("stage", "fixture"),
                source_unit=known("cm", "fixture"),
                normalized_unit="cm",
            ),
        ),
    )


def _success(identity: str, answer: str, values: list[float | None], day: int = 1):
    window = SeriesWindow(start=datetime(2020, 1, day), end=datetime(2020, 1, day, 23, 59, 59, 999999))
    outcome = RetrievalOutcome(
        outcome_id=answer,
        series_id=identity,
        station_id="a",
        product_id="level",
        window=window,
        status=OutcomeStatus.SUCCESS if values else OutcomeStatus.EMPTY,
        facts_ids=("facts",),
        retrieved_at=datetime(2026, 9, 1, tzinfo=UTC),
        calls=("source-call",),
    )
    rows = pl.DataFrame(
        {
            "station_id": ["a"] * len(values),
            "product_id": ["level"] * len(values),
            "time": [window.start] * len(values),
            "value": values,
            "time_zone": ["unknown"] * len(values),
            "series_id": [identity] * len(values),
            "facts_id": ["facts"] * len(values),
            "source_unit": ["cm"] * len(values),
        },
        schema={
            "station_id": pl.String,
            "product_id": pl.String,
            "time": pl.Datetime("us"),
            "value": pl.Float64,
            "time_zone": pl.String,
            "series_id": pl.String,
            "facts_id": pl.String,
            "source_unit": pl.String,
        },
    )
    return outcome, SuccessfulReplacement(
        CoverageInterval(identity, RequestedInterval(window.start, window.end), outcome.retrieved_at, answer), rows
    )


def _update(definitions, pairs=(), inventories=(), outcomes=(), issues=()):
    return StoreUpdate(
        tuple(definitions),
        tuple(inventories),
        tuple(pair[0] for pair in pairs) + tuple(outcomes),
        tuple(pair[1] for pair in pairs),
        tuple(issues),
    )


def _query(store: Path, identities=()):
    return StoreReader().query(
        StoreQuery(
            StoreRoot(store),
            ProviderId("fixture_live"),
            ("a",),
            ("level",),
            datetime(2020, 1, 1),
            datetime(2020, 1, 31),
            series_ids=identities,
        )
    )


def test_concrete_refresh_preserves_sibling_duplicates_and_failed_refresh(tmp_path: Path) -> None:
    store = StoreRoot(tmp_path / "store")
    a, b = _definition("a-series"), _definition("b-series")
    first_a, first_b = _success(a.series_id, "first-a", [12.4, 12.4]), _success(b.series_id, "first-b", [99.0, None])
    accumulate(store, ProviderId("fixture_live"), _update((a, b), (first_a, first_b)))
    snapshot = InventorySnapshot(
        snapshot_id="all-at-first",
        scope=SeriesScope(provider_ids=("fixture_live",)),
        members=(a.series_id, b.series_id),
        completeness=InventoryCompleteness.COMPLETE,
        access="recorded response",
        origin="response",
        window=first_a[0].window,
        evidence=("fixture",),
    )
    changed = _success(a.series_id, "refresh-a", [8.0])
    accumulate(store, ProviderId("fixture_live"), _update((a,), (changed,), (snapshot,)))
    assert_frame_equal(_query(store, (b.series_id,)).rows, first_b[1].rows)
    assert_frame_equal(_query(store, (a.series_id,)).rows, changed[1].rows)
    failed = RetrievalOutcome(
        outcome_id="failed-refresh-b",
        series_id=b.series_id,
        station_id="a",
        product_id="level",
        window=first_b[0].window,
        status=OutcomeStatus.FAILED,
        reason="source unavailable",
    )
    issue = Issue(
        severity="error", code="source_failure", message="source unavailable", details={"series_id": b.series_id}
    )
    before = _query(store, (b.series_id,)).rows
    manifest = accumulate(store, ProviderId("fixture_live"), _update((b,), outcomes=(failed,), issues=(issue,)))
    assert_frame_equal(_query(store, (b.series_id,)).rows, before)
    assert failed in manifest.outcomes and issue in manifest.issues
    assert {coverage.outcome_id for coverage in manifest.coverage} == {"first-b", "refresh-a"}
    assert manifest.inventories == (snapshot,)
    assert _query(store).physical_rows["value"].to_list() == [99.0, None, 8.0]


def test_inventory_only_late_identity_has_no_implied_coverage_and_empty_success_is_explicit(tmp_path: Path) -> None:
    store = StoreRoot(tmp_path / "store")
    a, late = _definition("a-series"), _definition("late-series")
    first = _success(a.series_id, "first-a", [1.0])
    accumulate(store, ProviderId("fixture_live"), _update((a,), (first,)))
    snapshot = InventorySnapshot(
        snapshot_id="late-inventory",
        scope=SeriesScope(provider_ids=("fixture_live",)),
        members=(a.series_id, late.series_id),
        completeness=InventoryCompleteness.INCOMPLETE,
        access="recorded response",
        origin="response",
        window=first[0].window,
        evidence=("fixture",),
        reason="scope unresolved",
    )
    manifest = accumulate(store, ProviderId("fixture_live"), _update((late,), inventories=(snapshot,)))
    assert {item.series_id for item in manifest.coverage} == {a.series_id}
    empty = _success(late.series_id, "empty-late", [], day=2)
    manifest = accumulate(store, ProviderId("fixture_live"), _update((late,), (empty,)))
    assert any(item.series_id == late.series_id and item.interval.start.day == 2 for item in manifest.coverage)
    assert _query(store, (late.series_id,)).rows.is_empty()
    assert manifest.inventories[0].completeness is InventoryCompleteness.INCOMPLETE


def test_failed_outcome_cannot_authorize_replacement_or_empty_coverage(tmp_path: Path) -> None:
    store = StoreRoot(tmp_path / "store")
    a = _definition("a-series")
    outcome, replacement = _success(a.series_id, "failure", [])
    failed = outcome.model_copy(update={"status": OutcomeStatus.FAILED, "reason": "unreadable source"})
    with pytest.raises(FatalContractError, match="explicit successful"):
        accumulate(store, ProviderId("fixture_live"), StoreUpdate((a,), (), (failed,), (replacement,)))
    assert not store.exists()


def test_store_excerpt_is_exact_concrete_selected_native_rows(tmp_path: Path) -> None:
    from io import BytesIO

    from rivretrieve._internal.store.receipts import encode_store_excerpt

    store = StoreRoot(tmp_path / "store")
    a, b = _definition("a-series"), _definition("b-series")
    accumulate(
        store,
        ProviderId("fixture_live"),
        _update((a, b), (_success(a.series_id, "a", [1.0, 1.0]), _success(b.series_id, "b", [2.0]))),
    )
    read = _query(store, (a.series_id,))
    excerpt = encode_store_excerpt(read)
    assert_frame_equal(pl.read_parquet(BytesIO(excerpt.content)), read.physical_rows)
    assert excerpt.executed_query.series_ids == (a.series_id,)
    assert read.physical_rows["source_unit"].to_list() == ["cm", "cm"]


def test_source_call_vintage_and_tuples_roundtrip_without_receipts(tmp_path: Path) -> None:
    store = StoreRoot(tmp_path / "store")
    definition = _definition("a-series")
    pair = _success(definition.series_id, "a", [1.0])
    call = {
        "retrieved_at": datetime(2026, 9, 2, 11, 12, 13, tzinfo=UTC),
        "url": "https://example.invalid/source",
        "request_parameters": {"station": "a"},
        "query": {"parameters": (1, "a")},
    }
    update = StoreUpdate((definition,), (), (pair[0],), (pair[1],), source_calls=(call,))
    accumulate(store, ProviderId("fixture_live"), update)
    assert _query(store).manifest.source_calls == (call,)


def test_fact_segment_addition_preserves_old_evidence_and_refuses_reinterpretation(tmp_path: Path) -> None:
    store = StoreRoot(tmp_path / "store")
    definition = _definition("a-series")
    pair = _success(definition.series_id, "a", [1.0])
    accumulate(store, ProviderId("fixture_live"), _update((definition,), (pair,)))
    revised_fact = definition.facts[0].model_copy(
        update={
            "facts_id": "later-facts",
            "source_unit": known("m", "later source documentation"),
            "normalized_unit": "m",
        }
    )
    later = definition.model_copy(update={"facts": (revised_fact,)})
    manifest = accumulate(store, ProviderId("fixture_live"), _update((later,)))
    assert manifest.series[0].facts == (*definition.facts, revised_fact)
    assert_frame_equal(_query(store).rows, pair[1].rows)
    changed_same_id = definition.model_copy(update={"facts": (revised_fact.model_copy(update={"facts_id": "facts"}),)})
    with pytest.raises(FatalContractError, match="reinterprets existing physical facts"):
        accumulate(store, ProviderId("fixture_live"), _update((changed_same_id,)))
    assert _query(store).manifest.series[0].facts == (*definition.facts, revised_fact)


def test_narrow_fact_refresh_keeps_sibling_physical_rows_and_success_vintage(tmp_path: Path) -> None:
    from dataclasses import replace

    store = StoreRoot(tmp_path / "store")
    first = _definition("shared-series")
    other_facts = first.facts[0].model_copy(
        update={
            "facts_id": "other-facts",
            "source_unit": known("mm", "other physical segment"),
            "normalized_unit": "mm",
        }
    )
    definition = first.model_copy(update={"facts": (*first.facts, other_facts)})
    original, replacement = _success(definition.series_id, "both-facts", [1.0])
    sibling = replacement.rows.with_columns(
        pl.lit("other-facts").alias("facts_id"), pl.lit("mm").alias("source_unit"), pl.lit(20.0).alias("value")
    )
    original = original.model_copy(update={"facts_ids": ("facts", "other-facts")})
    both = SuccessfulReplacement(replacement.coverage, pl.concat([replacement.rows, sibling]))
    accumulate(store, ProviderId("fixture_live"), StoreUpdate((definition,), (), (original,), (both,)))
    refreshed, refresh_rows = _success(definition.series_id, "only-first-facts", [3.0])
    refreshed = refreshed.model_copy(update={"retrieved_at": datetime(2026, 9, 2, tzinfo=UTC)})
    refresh_rows = SuccessfulReplacement(
        replace(refresh_rows.coverage, retrieved_at=refreshed.retrieved_at), refresh_rows.rows
    )
    manifest = accumulate(
        store, ProviderId("fixture_live"), StoreUpdate((definition,), (), (refreshed,), (refresh_rows,))
    )
    result = _query(store)
    assert_frame_equal(result.rows.filter(pl.col("facts_id") == "other-facts"), sibling)
    assert_frame_equal(result.rows.filter(pl.col("facts_id") == "facts"), refresh_rows.rows)
    old_coverage = next(item for item in manifest.coverage if "other-facts" in item.facts_ids)
    new_coverage = next(item for item in manifest.coverage if "facts" in item.facts_ids)
    assert old_coverage.retrieved_at == original.retrieved_at
    assert new_coverage.retrieved_at == refreshed.retrieved_at
    assert old_coverage.facts_ids == ("other-facts",)
    assert new_coverage.facts_ids == ("facts",)
    read = StoreReader().query(
        StoreQuery(
            store,
            ProviderId("fixture_live"),
            ("a",),
            ("level",),
            original.window.start,
            original.window.end,
            facts_ids=("other-facts",),
        )
    )
    assert_frame_equal(read.rows, sibling)
    assert read.executed_query.facts_ids == ("other-facts",)


def test_explicit_broad_replacement_retires_previous_fact_rows_without_rewriting_history(tmp_path: Path) -> None:
    store = StoreRoot(tmp_path / "store")
    original_definition = _definition("same-series")
    first, first_rows = _success(original_definition.series_id, "original", [1.0])
    accumulate(store, ProviderId("fixture_live"), StoreUpdate((original_definition,), (), (first,), (first_rows,)))
    next_facts = original_definition.facts[0].model_copy(
        update={"facts_id": "new-source-facts", "statistic": known("minimum", "new established source facts")}
    )
    latest = original_definition.model_copy(update={"facts": (next_facts,)})
    success = first.model_copy(update={"outcome_id": "replacement", "facts_ids": (next_facts.facts_id,)})
    rows = first_rows.rows.with_columns(pl.lit(next_facts.facts_id).alias("facts_id"), pl.lit(0.5).alias("value"))
    coverage = CoverageInterval(
        latest.series_id, first_rows.coverage.interval, success.retrieved_at, success.outcome_id
    )
    replacement = SuccessfulReplacement(coverage, rows, replaced_facts_ids=("facts", next_facts.facts_id))
    manifest = accumulate(store, ProviderId("fixture_live"), StoreUpdate((latest,), (), (success,), (replacement,)))
    assert_frame_equal(_query(store).rows, rows)
    assert tuple(item.facts_ids for item in manifest.coverage) == ((next_facts.facts_id,),)
    assert manifest.series[0].facts == (*original_definition.facts, next_facts)
    assert first in manifest.outcomes and success in manifest.outcomes

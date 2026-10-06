"""Rolling source rows do not resolve an earlier interval failure."""

from dataclasses import replace
from datetime import datetime

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
from rivretrieve._internal.source_series import OutcomeStatus
from tests import test_independent_fact_cache as fact_tests
from tests.test_independent_fact_cache import NEW, OLD, PROVIDER, ROW_TIME

fact_cache = fact_tests.fact_cache


def test_rolling_success_retains_active_failure_but_excludes_unrelated_acquisition(fact_cache):
    stages, selection, _ = fact_cache
    stages.members = ("mean",)
    stages.snapshot = True
    selected = rr.pick(selection, statistic="mean")

    def fetch(day):
        return rr.fetch(selected, start=day, end=day, cache="refresh", on_issue="ignore")

    fetch("2026-01-01")
    stages.snapshot = False
    stages.status["mean"] = OutcomeStatus.FAILED
    failed_result = fetch("2026-01-01")
    failure = next(item for item in failed_result.outcomes if item.status is OutcomeStatus.FAILED)
    failure_issue = next(item for item in failed_result.issues if item.code == "source.request_failed")
    assert failure.calls == ("2-mean",)

    # A separate acquisition remains useful in the store, but not for this
    # request's rows, interval diagnostics or inventory conclusions.
    stages.snapshot = True
    stages.status["mean"] = OutcomeStatus.SUCCESS
    stages.row_times = (datetime(2026, 1, 10, 12),)
    fetch("2026-01-10")

    stages.row_times = (ROW_TIME.replace(hour=13),)
    stages.stamps["mean"] = NEW
    stages.value = 2.0
    result = fetch("2026-01-01")
    expected = pl.DataFrame({"time": [ROW_TIME, ROW_TIME.replace(hour=13)], "value": [1.0, 2.0]})
    pt.assert_frame_equal(result.data.select(expected.columns).sort("time"), expected)

    persisted = rr.cache_status(PROVIDER).manifest
    assert failure in persisted.outcomes
    assert failure_issue in persisted.issues
    assert any(call.get("call_id") == "3-mean" for call in persisted.source_calls)
    assert {call.get("call_id") for call in result.provenance.calls_made} == {"1-mean", "2-mean", "4-mean"}
    assert failure in result.outcomes
    assert failure_issue in result.issues
    assert failure not in result.supporting_outcomes
    assert {
        (key[1], item.retrieved_at)
        for item in result.outcomes
        if item.status is OutcomeStatus.SUCCESS
        for key in item.observation_keys
    } == {(ROW_TIME, OLD), (ROW_TIME.replace(hour=13), NEW)}


@pytest.mark.parametrize("linked", [False, True], ids=["acquisition-note", "outcome-note"])
@pytest.mark.parametrize("policy", ["ignore", "raise"])
def test_held_snapshot_notes_keep_original_counts_and_issue_policy(fact_cache, monkeypatch, linked, policy):
    from rivretrieve._internal.issues import Issue, IssuePolicyError
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.source_series import InventoryCompleteness, InventorySnapshot
    from rivretrieve._internal.store import StoreRoot
    from rivretrieve._internal.store.accumulation import StoreUpdate, accumulate

    stages, selection, root = fact_cache
    stages.members = ("mean",)
    stages.snapshot = True
    selected = rr.pick(selection, statistic="mean")
    stages.row_times = (ROW_TIME, ROW_TIME.replace(hour=13))
    original_parse = stages.parse
    unrelated_note = Issue(
        severity="warning", code="source.note", message="Other acquisition count", details={"count": 99}
    )

    def parse(payload, config):
        parsed = original_parse(payload, config)
        if payload.acquisition_id == "1-mean":
            note = Issue(
                severity="warning",
                code="source.note",
                message="Original acquisition count",
                details={"count": 7, **({"outcome_id": parsed.outcomes[0].outcome_id} if linked else {})},
            )
            return replace(parsed, issues=(note,))
        if payload.acquisition_id == "2-mean":
            return replace(parsed, issues=(unrelated_note,))
        # Require a historical failed outcome to interpret the current inventory,
        # without making that old failure an active diagnostic.
        return replace(
            parsed,
            inventories=tuple(
                item.model_copy(update={"evidence": (*item.evidence, "source-inventory:historical-support")})
                for item in parsed.inventories
            ),
        )

    monkeypatch.setattr(stages, "parse", parse)
    fresh = rr.fetch(selected, start="2026-01-01", end="2026-01-01", cache="refresh", on_issue="ignore")
    original_note = next(issue for issue in fresh.issues if issue.message == "Original acquisition count")
    assert original_note.details["count"] == 7
    original_outcome = next(item for item in fresh.outcomes if item.status is OutcomeStatus.SUCCESS)

    stages.row_times = (datetime(2026, 1, 10, 12),)
    rr.fetch(selected, start="2026-01-10", end="2026-01-10", cache="refresh", on_issue="ignore")
    failure = original_outcome.model_copy(
        update={
            "outcome_id": "historical-failure",
            "status": OutcomeStatus.FAILED,
            "reason": "Resolved historical failure",
            "coverage": "interval",
            "observation_keys": (),
            "calls": ("historical-call",),
        }
    )
    support_inventory = InventorySnapshot(
        snapshot_id="historical-support",
        scope=selected.scope,
        members=(),
        completeness=InventoryCompleteness.INCOMPLETE,
        reason="Historical acquisition evidence",
        access="authored historical support",
        origin="response",
        evidence=("retrieval-outcome:historical-failure",),
    )
    support_issue = Issue(
        severity="error",
        code="source.request_failed",
        message=failure.reason,
        details={"outcome_id": failure.outcome_id},
    )
    accumulate(
        StoreRoot(root / PROVIDER / "store"),
        ProviderId(PROVIDER),
        StoreUpdate(
            (), (support_inventory,), (), (), (), ({"call_id": "historical-call"},), supporting_outcomes=(failure,)
        ),
    )
    persisted = rr.cache_status(PROVIDER).manifest
    assert not any(item.status is OutcomeStatus.FAILED for item in persisted.outcomes)
    assert support_issue not in persisted.issues
    assert any(issue.message == unrelated_note.message for issue in persisted.issues)

    # One original key survives. The other is replaced, so an outcome-linked
    # source note must follow its acquisition rather than the projected key ID.
    stages.row_times = (ROW_TIME.replace(hour=13),)
    stages.value = 2.0
    stages.stamps["mean"] = NEW
    if policy == "raise":
        with pytest.raises(IssuePolicyError) as raised:
            rr.fetch(selected, start="2026-01-01", end="2026-01-01", cache="refresh", on_issue=policy)
        assert original_note in raised.value.issues
        assert unrelated_note not in raised.value.issues
        assert support_issue not in raised.value.issues
        return
    result = rr.fetch(selected, start="2026-01-01", end="2026-01-01", cache="refresh", on_issue=policy)
    expected = pl.DataFrame({"time": [ROW_TIME, ROW_TIME.replace(hour=13)], "value": [1.0, 2.0]})
    pt.assert_frame_equal(result.data.select(expected.columns).sort("time"), expected)
    assert original_outcome in result.outcomes
    assert failure in result.supporting_outcomes
    assert failure not in result.outcomes
    assert support_issue not in result.issues
    assert unrelated_note not in result.issues
    assert "2-mean" not in {call.get("call_id") for call in result.provenance.calls_made}
    assert original_note in result.issues
    assert [issue.details["count"] for issue in result.issues if issue.message == original_note.message] == [7]

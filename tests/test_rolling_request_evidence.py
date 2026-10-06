"""Rolling source rows do not resolve an earlier interval failure."""

from datetime import datetime

import polars as pl
import polars.testing as pt

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

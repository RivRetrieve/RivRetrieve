"""Current evidence follows retained scope rather than acquisition history."""

from datetime import UTC, datetime, timedelta

import pytest

from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
)
from rivretrieve._internal.store.authority import compact_evidence, compact_inventories
from rivretrieve._internal.time_axis import TimeAxis

_START = datetime(2020, 1, 1)
_END = datetime(2020, 1, 31)


def _outcome(
    name,
    *,
    status=OutcomeStatus.SUCCESS,
    start=_START,
    end=_END,
    facts=("f",),
    series="s",
    axis=TimeAxis.NATIVE,
    keys=(),
):
    return RetrievalOutcome(
        outcome_id=name,
        series_id=series,
        station_id="a",
        product_id="q",
        window=SeriesWindow(start=start, end=end, axis=axis),
        status=status,
        facts_ids=facts,
        reason="failed acquisition" if status == OutcomeStatus.FAILED else None,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        calls=(name,),
        coverage="observations" if keys else "interval",
        observation_keys=keys,
    )


def _cover(item):
    return CoverageInterval(
        item.series_id,
        RequestedInterval(item.window.start, item.window.end, axis=item.window.axis),
        item.retrieved_at,
        item.outcome_id,
        item.facts_ids,
    )


def _issue(item):
    return Issue(
        severity="error",
        code="source.request_failed",
        message=item.reason,
        details={"outcome_id": item.outcome_id, "station_id": "a", "product_id": "q"},
    )


def _compact(outcomes, coverage=(), issues=()):
    return compact_evidence(
        coverage,
        outcomes,
        (),
        issues,
        tuple({"call_id": call} for call in dict.fromkeys(call for item in outcomes for call in item.calls)),
        new_outcome_ids=frozenset((outcomes[-1].outcome_id,)) if outcomes else frozenset(),
    )


def test_full_recovery_removes_failed_diagnosis_and_unsupported_success_history():
    old, failed, recovered = _outcome("old"), _outcome("fail", status=OutcomeStatus.FAILED), _outcome("new")
    current = _compact((old, failed, recovered), (_cover(recovered),), (_issue(failed),))
    assert current.outcomes == (recovered,)
    assert current.issues == ()
    assert current.source_calls == ({"call_id": "new"},)


def test_partial_recovery_retains_exact_failure_remainder_original_time_and_reason():
    failed = _outcome("fail", status=OutcomeStatus.FAILED)
    recovered = _outcome("new", end=datetime(2020, 1, 15))
    current = _compact((failed, recovered), (_cover(recovered),), (_issue(failed),))
    remaining = current.outcomes[0]
    assert remaining.status == OutcomeStatus.FAILED
    assert remaining.window.start == datetime(2020, 1, 15) + timedelta(microseconds=1)
    assert remaining.window.end == _END
    assert remaining.retrieved_at == failed.retrieved_at
    assert remaining.reason == failed.reason
    assert remaining.calls == failed.calls
    assert current.issues[0].details["outcome_id"] == remaining.outcome_id
    assert current.source_calls == ({"call_id": "fail"}, {"call_id": "new"})


def test_other_identity_facts_and_axis_do_not_recover_failure():
    failed = _outcome("fail", status=OutcomeStatus.FAILED)
    others = (
        _outcome("other-series", series="other"),
        _outcome("other-fact", facts=("other",)),
        _outcome("utc", axis=TimeAxis.UTC),
    )
    current = _compact((failed, *others), tuple(_cover(item) for item in others), (_issue(failed),))
    assert current.outcomes[0] == failed
    assert current.issues == (_issue(failed),)


def test_recovery_of_one_fact_keeps_other_fact_failure():
    failed = _outcome("fail", status=OutcomeStatus.FAILED, facts=("f", "g"))
    new = _outcome("new")
    current = _compact((failed, new), (_cover(new),), (_issue(failed),))
    assert current.outcomes[0].facts_ids == ("g",)
    assert current.outcomes[0].window == failed.window
    assert current.issues[0].details["facts_ids"] == ["g"]


def test_failed_refresh_retains_held_success_and_compacts_repeated_failure():
    held = _outcome("old")
    first = _outcome("failure-one", status=OutcomeStatus.FAILED)
    second = _outcome("failure-two", status=OutcomeStatus.FAILED)
    current = _compact((held, first, second), (_cover(held),), (_issue(first), _issue(second)))
    assert current.outcomes == (held, second)
    assert current.issues == (_issue(second),)
    assert current.source_calls == ({"call_id": "old"}, {"call_id": "failure-two"})


def test_rolling_keys_keep_older_absent_keys_and_drop_fully_replaced_acquisition():
    a, b = ("f", _START, "unknown"), ("f", datetime(2020, 1, 2), "unknown")
    old = _outcome("old", keys=(a, b))
    new = _outcome("new", keys=(a,))
    current = _compact((old, new))
    assert current.outcomes[0].observation_keys == (b,)
    assert current.outcomes[0].retrieved_at == old.retrieved_at
    assert current.outcomes[1] == new
    last = _outcome("last", keys=(b,))
    final = _compact((*current.outcomes, last))
    assert tuple(item.outcome_id for item in final.outcomes) == ("new", "last")


def test_interval_empty_success_replaces_snapshot_keys_only_on_established_axis():
    old = _outcome("old", keys=(("f", _START, "unknown"),))
    utc = _outcome("utc", status=OutcomeStatus.EMPTY, axis=TimeAxis.UTC)
    current = _compact((old, utc), (_cover(utc),))
    assert current.outcomes[0] == old
    native = _outcome("native", status=OutcomeStatus.EMPTY)
    final = _compact((old, native), (_cover(native),))
    assert final.outcomes == (native,)


def test_latest_inventory_scope_preserves_uncovered_windows_and_independent_access():
    def inventory(name, start, end, access="daily"):
        return InventorySnapshot(
            snapshot_id=name,
            scope=SeriesScope(station_ids=("a",)),
            members=("s",),
            completeness=InventoryCompleteness.COMPLETE,
            access=access,
            origin="response",
            evidence=(name,),
            window=SeriesWindow(start=start, end=end),
        )

    old = inventory("old", _START, _END)
    partial = inventory("partial", _START, datetime(2020, 1, 15))
    other = inventory("other", _START, _END, "instantaneous")
    assert compact_inventories((old, partial, other)) == (old, partial, other)
    new = inventory("new", _START, _END)
    assert compact_inventories((old, partial, other, new)) == (other, new)


def test_snapshot_does_not_establish_failure_interval_recovery():
    failed = _outcome("fail", status=OutcomeStatus.FAILED)
    snapshot = _outcome("snap", keys=(("f", _START, "unknown"),))
    current = _compact((failed, snapshot), issues=(_issue(failed),))
    assert current.outcomes[0] == failed
    assert current.issues == (_issue(failed),)


def test_unknown_facts_require_complete_inventory_for_the_recorded_failure_scope():
    from rivretrieve._internal.source_series import PhysicalPredicate, RestrictionKind

    failed = _outcome("fail", status=OutcomeStatus.FAILED, facts=())
    recovered = _outcome("new")
    scope = SeriesScope(
        station_ids=("a",),
        product_ids=("q",),
        restriction=RestrictionKind.EXPLICIT,
        series_ids=("s",),
        predicates=(PhysicalPredicate(field="quantity", value="discharge"),),
    )
    inventory = InventorySnapshot(
        snapshot_id="inventory",
        scope=scope,
        members=("s",),
        member_facts=(("s", ("f",)),),
        completeness=InventoryCompleteness.COMPLETE,
        access="daily",
        origin="response",
        evidence=("retrieval-outcome:new",),
        window=recovered.window,
        acquired_at=recovered.retrieved_at,
    )
    issue = _issue(failed).model_copy(
        update={"details": {"outcome_id": failed.outcome_id, "inventory_scope": scope.model_dump(mode="json")}}
    )
    retained = compact_evidence((_cover(recovered),), (failed, recovered), (), (issue,), ())
    assert retained.outcomes[0] == failed
    current = compact_evidence((_cover(recovered),), (failed, recovered), (inventory,), (issue,), ())
    assert current.outcomes == (recovered,)
    assert current.issues == ()
    narrower = inventory.model_copy(update={"scope": scope.model_copy(update={"predicates": ()})})
    assert compact_evidence((_cover(recovered),), (failed, recovered), (narrower,), (issue,), ()).outcomes[0] == failed


def test_inventory_dependencies_keep_support_without_reactivating_old_failure():
    scope = SeriesScope(station_ids=("a",), product_ids=("q",))
    old = InventorySnapshot(
        snapshot_id="old",
        scope=scope,
        members=("s",),
        completeness=InventoryCompleteness.COMPLETE,
        access="daily",
        origin="response",
        evidence=("retrieval-outcome:old-success",),
        window=SeriesWindow(start=_START, end=_END),
    )
    newer = old.model_copy(update={"snapshot_id": "new", "evidence": ("source-inventory:old",)})
    original = _outcome("old-success")
    failure = _outcome("failure", status=OutcomeStatus.FAILED)
    recovery = _outcome("recovery")
    current = compact_evidence(
        (_cover(recovery),),
        (original, failure, recovery),
        (old, newer),
        (_issue(failure),),
        ({"call_id": "old-success"}, {"call_id": "failure"}, {"call_id": "recovery"}),
    )
    assert current.inventories == (old, newer)
    assert current.outcomes == (recovery,)
    assert current.supporting_outcomes == (original,)
    assert current.issues == ()
    assert current.source_calls == ({"call_id": "old-success"}, {"call_id": "recovery"})


def test_unknown_identity_recovers_only_complete_acquired_scope_and_leaves_remainder():
    failed = _outcome("fail", status=OutcomeStatus.FAILED, facts=(), series=None)
    scope = SeriesScope(station_ids=("a",), product_ids=("q",))
    issue = _issue(failed).model_copy(
        update={"details": {"outcome_id": failed.outcome_id, "inventory_scope": scope.model_dump(mode="json")}}
    )
    recovered = _outcome("new", end=datetime(2020, 1, 15))
    inventory = InventorySnapshot(
        snapshot_id="known",
        scope=scope,
        members=("s",),
        member_facts=(("s", ("f",)),),
        completeness=InventoryCompleteness.COMPLETE,
        access="daily",
        origin="response",
        evidence=("retrieval-outcome:new",),
        window=recovered.window,
        acquired_at=recovered.retrieved_at,
    )
    current = compact_evidence((_cover(recovered),), (failed, recovered), (inventory,), (issue,), ())
    assert current.outcomes[0].window.start == recovered.window.end + timedelta(microseconds=1)
    assert current.outcomes[0].window.end == failed.window.end
    assert current.issues[0].details["original_outcome_id"] == failed.outcome_id
    incomplete = inventory.model_copy(
        update={"completeness": InventoryCompleteness.INCOMPLETE, "reason": "An identity remains unresolved"}
    )
    unchanged = compact_evidence((_cover(recovered),), (failed, recovered), (incomplete,), (issue,), ())
    assert unchanged.outcomes[0] == failed


def test_empty_complete_inventory_can_resolve_identity_unknown_failure():
    failed = _outcome("fail", status=OutcomeStatus.FAILED, facts=(), series=None)
    scope = SeriesScope(station_ids=("a",), product_ids=("q",))
    inventory = InventorySnapshot(
        snapshot_id="empty",
        scope=scope,
        members=(),
        completeness=InventoryCompleteness.COMPLETE,
        access="daily",
        origin="response",
        evidence=("published empty scope",),
        window=failed.window,
        acquired_at=failed.retrieved_at + timedelta(days=1),
    )
    current = compact_evidence((), (failed,), (inventory,), (_issue(failed),), ())
    assert current.outcomes == ()
    assert current.issues == ()
    assert current.inventories == (inventory,)


def test_public_repeated_usgs_refresh_retains_only_current_acquisitions(tmp_path, monkeypatch):
    import json
    from dataclasses import replace

    import rivretrieve as rr
    from rivretrieve._internal import discovery
    from tests.test_usgs_continuous_cache_axis import STATION, _Spans

    selected = rr.find(provider="usgs_nwis", station=STATION, quantity="discharge")
    continuous = next(item for item in selected.series if item.product_id == "discharge_instantaneous")
    selected = rr.pick(selected, series_id=continuous.series_id)
    transport = _Spans(continuous.identity.published_id)
    send = transport.send
    stamp = datetime(2026, 9, 20, tzinfo=UTC)

    def stamped(request):
        return replace(send(request), retrieved_at=stamp)

    monkeypatch.setattr(transport, "send", stamped)
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    counts = []
    for day in range(20, 24):
        stamp = datetime(2026, 9, day, tzinfo=UTC)
        transport.value = day
        rr.fetch(selected, start="2000-01-03", end="2003-02-01", cache="refresh", on_issue="raise")
        document = json.loads((tmp_path / "usgs_nwis/store/manifest.json").read_text())
        counts.append(
            (
                len(document["outcomes"]),
                len(document["inventories"]),
                len(document["source_calls"]),
                len(document["issues"]),
            )
        )
    assert counts == [counts[0]] * 4
    assert counts[-1][0] == 2
    assert counts[-1][2:] == (2, 0)
    assert all(call.get("call_id") or call.get("acquisition_id") for call in document["source_calls"])
    transport.failed_first = transport.failed_second = True
    failure_counts = []
    for day in range(24, 27):
        stamp = datetime(2026, 9, day, tzinfo=UTC)
        partial = rr.fetch(selected, start="2000-01-03", end="2003-02-01", cache="refresh", on_issue="ignore")
        assert partial.data.height == 2
        document = json.loads((tmp_path / "usgs_nwis/store/manifest.json").read_text())
        failure_counts.append(
            (
                len(document["outcomes"]),
                len(document["inventories"]),
                len(document["source_calls"]),
                len(document["issues"]),
            )
        )
    assert failure_counts == [failure_counts[0]] * 3
    # Each failed span has its transport failure and unresolved membership diagnosis.
    assert failure_counts[-1][0] == 6
    assert failure_counts[-1][2:] == (4, 2)
    supporting = [item for item in document["outcomes"] if item["status"] == "success"]
    assert {item["retrieved_at"] for item in supporting} == {"2026-09-23T00:00:00Z"}
    transport.failed_first = transport.failed_second = False
    stamp = datetime(2026, 9, 27, tzinfo=UTC)
    rr.fetch(selected, start="2000-01-03", end="2003-02-01", cache="refresh", on_issue="raise")
    document = json.loads((tmp_path / "usgs_nwis/store/manifest.json").read_text())
    assert len(document["outcomes"]) == len(document["source_calls"]) == 2
    assert document["issues"] == []


def test_referenced_attempt_keeps_its_acquisition_prerequisites_and_retries():
    outcome = _outcome("attempt")
    calls = (
        {"acquisition_id": "payload", "url": "https://example.invalid/credential"},
        {"call_id": "retry", "acquisition_id": "payload", "status_code": 503},
        {"call_id": "attempt", "acquisition_id": "payload", "status_code": 200},
        {"call_id": "old", "acquisition_id": "superseded", "status_code": 200},
        {"acquisition_id": "superseded", "url": "https://example.invalid/credential"},
    )
    current = compact_evidence((_cover(outcome),), (outcome,), (), (), calls)
    assert current.source_calls == calls[:3]


def test_inventory_only_call_dependency_keeps_metadata_acquisition_without_outcomes():
    inventory = InventorySnapshot(
        snapshot_id="metadata",
        scope=SeriesScope(station_ids=("a",)),
        members=(),
        completeness=InventoryCompleteness.COMPLETE,
        access="daily",
        origin="response",
        evidence=("source-call:metadata-call",),
    )
    call = {"call_id": "metadata-call", "url": "https://example.invalid/metadata"}
    current = compact_evidence((), (), (inventory,), (), (call, {"call_id": "old-metadata"}))
    assert current.source_calls == (call,)


@pytest.mark.parametrize("with_observations", [False, True])
def test_public_repeated_nve_metadata_origins_have_bounded_explicit_dependencies(
    tmp_path, monkeypatch, with_observations
):
    import json

    import rivretrieve as rr
    from rivretrieve._internal import discovery
    from rivretrieve._internal.transport import TransportResponse

    selected = rr.find(provider="no_nve", station="1.200.0", quantity="discharge", frequency="daily", statistic="mean")
    versions = sorted({int(item.identity.published_id) for item in selected.series})
    stamp = datetime(2026, 9, 20, tzinfo=UTC)
    requests = []
    metadata_failed = False

    class AuthoredHydAPI:
        def send(self, request):
            requests.append(request)
            if request.url.endswith("/Series"):
                if metadata_failed:
                    from rivretrieve._internal.transport import TransportFailure, TransportFailureReason

                    raise TransportFailure(request, TransportFailureReason.RETRY_EXHAUSTED, 3, status_code=503)
                entries = [
                    {
                        "stationId": "1.200.0",
                        "parameter": 1001,
                        "versionNo": version,
                        "unit": "m³/s",
                        "resolutionList": [{"resTime": 1440, "method": "Mean"}],
                    }
                    for version in versions
                ]
                body = {"data": entries, "itemCount": len(entries)}
            else:
                assert request.url.endswith("/Observations")
                observations = (
                    [{"time": "2025-07-10T00:00:00Z", "value": float(stamp.day), "quality": stamp.day, "correction": 1}]
                    if with_observations
                    else []
                )
                body = {
                    "data": [
                        {
                            "stationId": "1.200.0",
                            "parameter": 1001,
                            "serieVersionNo": int(request.params["VersionNumber"]),
                            "unit": "m³/s",
                            "method": "Mean",
                            "observationCount": len(observations),
                            "observations": observations,
                        }
                    ]
                }
            return TransportResponse(
                json.dumps(body).encode(), 200, stamp, "application/json", request.url, request.params
            )

    monkeypatch.setenv("NVE_API_KEY", "authored-not-a-real-credential")
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "HttpClient", AuthoredHydAPI)
    counts = []
    for day in range(20, 24):
        stamp = datetime(2026, 9, day, tzinfo=UTC)
        result = rr.fetch(selected, start="2025-07-10", end="2025-07-10", cache="refresh", on_issue="raise")
        assert result.data.height == (len(versions) if with_observations else 0)
        document = json.loads((tmp_path / "no_nve/store/manifest.json").read_text())
        counts.append(
            (
                len(document["inventories"]),
                len(document["outcomes"]),
                len(document["source_calls"]),
                len(document["issues"]),
            )
        )
        metadata_calls = [call for call in document["source_calls"] if call["url"].endswith("/Series")]
        assert len(metadata_calls) == 1
        metadata_id = metadata_calls[0]["call_id"]
        assert any("source-call:" + metadata_id in item["evidence"] for item in document["inventories"])
        assert metadata_calls[0]["retrieved_at"]["value"].startswith(f"2026-09-{day}")
        observation_calls = [call for call in document["source_calls"] if call["url"].endswith("/Observations")]
        assert len(observation_calls) == len(versions)
        active_calls = {identity for item in document["outcomes"] for identity in item["calls"]}
        assert all(call["call_id"] in active_calls for call in observation_calls)
        if with_observations:
            assert all("acquisition_ids" not in (issue.details or {}) for issue in result.issues)
            assert {
                issue["details"]["source_quality_code"]
                for issue in document["issues"]
                if "source_quality_code" in (issue["details"] or {})
            } == {day}
            active_ids = {call for item in document["outcomes"] for call in item["calls"]}
            assert all(set(issue["details"]["acquisition_ids"]).issubset(active_ids) for issue in document["issues"])

    assert counts == [counts[0]] * 4
    assert len(requests) == 4 * (len(versions) + 1)

    metadata_failed = True
    failed_ids = []
    failed_counts = []
    for day in range(24, 27):
        stamp = datetime(2026, 9, day, tzinfo=UTC)
        result = rr.fetch(selected, start="2025-07-10", end="2025-07-10", cache="refresh", on_issue="ignore")
        assert any(issue.code == "source.inventory_unresolved" for issue in result.issues)
        document = json.loads((tmp_path / "no_nve/store/manifest.json").read_text())
        metadata_calls = [call for call in document["source_calls"] if call["url"].endswith("/Series")]
        failed_metadata = [call for call in metadata_calls if call["retrieved_at"].get("status") == "unknown"]
        assert len(failed_metadata) == 1
        assert len(metadata_calls) <= 2
        current_id = failed_metadata[0]["call_id"]
        assert not set(failed_ids).intersection(call["call_id"] for call in metadata_calls)
        failed_ids.append(current_id)
        # A still-retained complete inventory can cite the last successful census.
        # Every retained origin must have an explicit inventory dependency.
        inventory_calls = {
            reference.removeprefix("source-call:")
            for item in document["inventories"]
            for reference in item["evidence"]
            if reference.startswith("source-call:")
        }
        assert {call["call_id"] for call in metadata_calls}.issubset(inventory_calls)
        assert all(call["call_id"] in {metadata_id, current_id} for call in metadata_calls)
        failed_counts.append(
            (
                len(document["inventories"]),
                len(document["outcomes"]),
                len(document["source_calls"]),
                len(document["issues"]),
            )
        )
    assert len(set(failed_ids)) == 3
    assert failed_counts == [failed_counts[0]] * 3
    metadata_failed = False
    stamp = datetime(2026, 9, 27, tzinfo=UTC)
    recovered = rr.fetch(selected, start="2025-07-10", end="2025-07-10", cache="refresh", on_issue="raise")
    assert not any(issue.code == "source.inventory_unresolved" for issue in recovered.issues)
    document = json.loads((tmp_path / "no_nve/store/manifest.json").read_text())
    assert not set(failed_ids).intersection(call.get("call_id") for call in document["source_calls"])


def test_independent_diagnoses_from_one_acquisition_do_not_supersede_each_other():
    unsupported = _outcome("unsupported", status=OutcomeStatus.FAILED).model_copy(
        update={
            "status": OutcomeStatus.UNSUPPORTED,
            "reason": "Conflicting source values",
            "calls": ("one-acquisition",),
        }
    )
    unresolved = unsupported.model_copy(
        update={
            "outcome_id": "unresolved",
            "status": OutcomeStatus.UNRESOLVED,
            "reason": "Transaction could not establish successful interval",
        }
    )
    current = _compact((unsupported, unresolved))
    assert current.outcomes == (unsupported, unresolved)


def test_unaccepted_success_cannot_remove_active_diagnosis():
    failed = _outcome("failed", status=OutcomeStatus.FAILED)
    unaccepted = _outcome("unaccepted")
    current = _compact((failed, unaccepted), issues=(_issue(failed),))
    assert current.outcomes == (failed,)
    assert current.issues == (_issue(failed),)


def test_success_resolves_diagnosis_only_over_its_retained_coverage_fragments():
    from dataclasses import replace

    failed = _outcome("failed", status=OutcomeStatus.FAILED)
    success = _outcome("successful-response")
    fragment = replace(_cover(success), interval=RequestedInterval(datetime(2020, 1, 10), datetime(2020, 1, 20)))
    current = _compact((failed, success), (fragment,), (_issue(failed),))
    unresolved = tuple(item for item in current.outcomes if item.status == OutcomeStatus.FAILED)
    assert tuple((item.window.start, item.window.end) for item in unresolved) == (
        (_START, datetime(2020, 1, 10) - timedelta(microseconds=1)),
        (datetime(2020, 1, 20) + timedelta(microseconds=1), _END),
    )


def test_partial_recovery_keeps_inventory_acquisition_dependency_separate_from_active_diagnosis(tmp_path):
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.store import StoreRoot
    from rivretrieve._internal.store.accumulation import StoreUpdate, accumulate
    from tests.test_accumulated_store import _coverage, _rows, _rows_update

    provider = ProviderId("fixture_live")
    store = StoreRoot(tmp_path / "store")
    seed = _rows_update(provider, _rows([_START], [1.0]), _coverage("2020-01-01", "2020-01-31"))
    accumulate(store, provider, seed)
    failed = seed.outcomes[0].model_copy(
        update={
            "outcome_id": "failed-acquisition",
            "status": OutcomeStatus.FAILED,
            "reason": "Authored source failure",
            "calls": ("failed-call",),
        }
    )
    scope = SeriesScope(provider_ids=(str(provider),), station_ids=("a",), product_ids=("level",))
    inventory = InventorySnapshot(
        snapshot_id="incomplete-month",
        scope=scope,
        members=(failed.series_id,),
        member_facts=((failed.series_id, failed.facts_ids),),
        completeness=InventoryCompleteness.INCOMPLETE,
        reason=failed.reason,
        access="daily",
        origin="response",
        window=failed.window,
        evidence=("retrieval-outcome:failed-acquisition",),
    )
    issue = Issue(
        severity="error",
        code="source.request_failed",
        message=failed.reason,
        details={"outcome_id": failed.outcome_id, "inventory_scope": scope.model_dump(mode="json")},
    )
    accumulate(store, provider, StoreUpdate((), (inventory,), (failed,), (), (issue,), ({"call_id": "failed-call"},)))
    fresh = _rows_update(
        provider,
        _rows([datetime(2020, 1, 15)], [2.0]),
        _coverage("2020-01-10", "2020-01-20", datetime(2026, 9, 3, tzinfo=UTC)),
    )
    new_inventory = inventory.model_copy(
        update={
            "snapshot_id": "recovered-middle",
            "window": fresh.outcomes[0].window,
            "completeness": InventoryCompleteness.COMPLETE,
            "reason": None,
            "evidence": ("retrieval-outcome:" + fresh.outcomes[0].outcome_id,),
        }
    )
    result = accumulate(
        store, provider, StoreUpdate(fresh.series, (new_inventory,), fresh.outcomes, fresh.replacements)
    )
    failures = tuple(item for item in result.outcomes if item.status == OutcomeStatus.FAILED)
    assert len(failures) == 2
    assert all(not item.window.start <= datetime(2020, 1, 15) <= item.window.end for item in failures)
    assert inventory in result.inventories

    from rivretrieve._internal.driver import _issue_in_scope, _reusable_snapshot
    from rivretrieve._internal.issues import apply_on_issue
    from rivretrieve._internal.store.integrity import inspect_integrity

    sealed = inspect_integrity(store, provider)
    assert sealed.supporting_outcomes == (failed,)
    assert failed.outcome_id not in {item.outcome_id for item in result.outcomes}
    # The narrower inventory cannot replace knowledge of the whole month.
    assert _reusable_snapshot(result, scope, fresh.outcomes[0].window) is not None
    middle = RequestedInterval(datetime(2020, 1, 10), datetime(2020, 1, 20))
    active_issues = tuple(
        item
        for item in result.issues
        if _issue_in_scope(item, "a", "level", (failed.series_id,), interval=middle, outcomes=result.outcomes)
    )
    assert active_issues == ()
    apply_on_issue(active_issues, "raise")
    reused = accumulate(store, provider, StoreUpdate((), (), (), ()))
    assert reused.outcomes == result.outcomes
    assert inspect_integrity(store, provider).supporting_outcomes == (failed,)

    complete = _rows_update(
        provider, _rows([_START], [3.0]), _coverage("2020-01-01", "2020-01-31", datetime(2026, 9, 4, tzinfo=UTC))
    )
    full_inventory = new_inventory.model_copy(
        update={
            "snapshot_id": "recovered-month",
            "window": failed.window,
            "evidence": ("retrieval-outcome:" + complete.outcomes[0].outcome_id,),
        }
    )
    final = accumulate(
        store, provider, StoreUpdate(complete.series, (full_inventory,), complete.outcomes, complete.replacements)
    )
    assert final.outcomes == complete.outcomes
    assert final.inventories == (full_inventory,)
    assert final.issues == ()
    assert inspect_integrity(store, provider).supporting_outcomes == ()
    assert not any(call.get("call_id") == "failed-call" for call in final.source_calls)


def test_support_only_outcome_never_becomes_an_active_diagnosis_and_releases_with_inventory():
    failed = _outcome("historical-failure", status=OutcomeStatus.FAILED)
    inventory = InventorySnapshot(
        snapshot_id="held",
        scope=SeriesScope(station_ids=("a",)),
        members=(),
        completeness=InventoryCompleteness.INCOMPLETE,
        reason="Historical acquisition incomplete",
        access="daily",
        origin="response",
        evidence=("retrieval-outcome:historical-failure",),
    )
    current = compact_evidence(
        (), (), (inventory,), (), ({"call_id": failed.outcome_id},), supporting_outcomes=(failed,)
    )
    assert current.outcomes == ()
    assert current.issues == ()
    assert current.supporting_outcomes == (failed,)
    assert current.source_calls == ({"call_id": failed.outcome_id},)
    complete = inventory.model_copy(
        update={
            "snapshot_id": "complete",
            "completeness": InventoryCompleteness.COMPLETE,
            "reason": None,
            "evidence": ("new independent acquired inventory",),
        }
    )
    compacted = compact_evidence((), (), (inventory, complete), (), current.source_calls, supporting_outcomes=(failed,))
    assert compacted.supporting_outcomes == ()
    assert compacted.source_calls == ()


def test_conflicting_support_and_active_acquisition_id_refuses():
    import pytest

    from rivretrieve._internal.issues import FatalContractError

    original = _outcome("identity")
    changed = original.model_copy(update={"retrieved_at": original.retrieved_at + timedelta(days=1)})
    with pytest.raises(FatalContractError, match="Conflicting current"):
        compact_evidence((), (changed,), (), (), (), supporting_outcomes=(original,))


def test_simultaneous_same_status_diagnoses_survive_until_next_acquisition():
    first = _outcome("first-call", status=OutcomeStatus.FAILED).model_copy(
        update={"reason": "First independent failure"}
    )
    second = _outcome("second-call", status=OutcomeStatus.FAILED).model_copy(
        update={"reason": "Second independent failure"}
    )
    together = compact_evidence(
        (),
        (first, second),
        (),
        (_issue(first), _issue(second)),
        ({"call_id": first.outcome_id}, {"call_id": second.outcome_id}),
        new_outcome_ids=frozenset((first.outcome_id, second.outcome_id)),
    )
    assert together.outcomes == (first, second)
    assert together.issues == (_issue(first), _issue(second))
    latest = _outcome("latest", status=OutcomeStatus.FAILED)
    refreshed = compact_evidence(
        (),
        (*together.outcomes, latest),
        (),
        (*together.issues, _issue(latest)),
        (*together.source_calls, {"call_id": latest.outcome_id}),
        new_outcome_ids=frozenset((latest.outcome_id,)),
    )
    assert refreshed.outcomes == (latest,)
    assert refreshed.issues == (_issue(latest),)


def test_anonymous_persisted_call_is_refused_rather_than_archived_forever():
    import pytest

    from rivretrieve._internal.issues import FatalContractError

    with pytest.raises(FatalContractError, match="explicit call or acquisition identity"):
        compact_evidence((), (), (), (), ({"url": "https://example.invalid/no-acquisition-link"},))


def test_complete_inventory_does_not_resolve_observation_failure_sharing_its_prerequisite():
    metadata = _outcome("metadata", status=OutcomeStatus.FAILED, facts=(), series=None).model_copy(
        update={"status": OutcomeStatus.UNRESOLVED, "calls": ("census",)}
    )
    observation = _outcome("observations", status=OutcomeStatus.FAILED).model_copy(
        update={"status": OutcomeStatus.UNRESOLVED, "calls": ("census",)}
    )
    metadata_issue = _issue(metadata).model_copy(update={"code": "source.inventory_unresolved"})
    observation_issue = _issue(observation)
    old = InventorySnapshot(
        snapshot_id="old",
        scope=SeriesScope(station_ids=("a",), product_ids=("q",)),
        members=("s",),
        member_facts=(("s", ("f",)),),
        completeness=InventoryCompleteness.INCOMPLETE,
        reason=metadata.reason,
        access="daily",
        origin="response",
        evidence=("source-call:census",),
        window=metadata.window,
    )
    new = old.model_copy(
        update={
            "snapshot_id": "new",
            "completeness": InventoryCompleteness.COMPLETE,
            "reason": None,
            "evidence": ("source-call:new-census",),
        }
    )
    current = compact_evidence(
        (),
        (metadata, observation),
        (old, new),
        (metadata_issue, observation_issue),
        ({"call_id": "census"}, {"call_id": "new-census"}),
        new_inventory_ids=frozenset(("new",)),
    )
    assert current.outcomes == (observation,)
    assert current.issues == (observation_issue,)
    held_only = compact_evidence(
        (), (metadata,), (old, new), (metadata_issue,), ({"call_id": "census"}, {"call_id": "new-census"})
    )
    assert held_only.outcomes == (metadata,)


def test_sibling_complete_inventory_cannot_erase_new_inventory_failure():
    metadata = _outcome("metadata", status=OutcomeStatus.FAILED, facts=(), series=None).model_copy(
        update={"status": OutcomeStatus.UNRESOLVED, "calls": ("census",)}
    )
    issue = _issue(metadata).model_copy(update={"code": "source.inventory_unresolved"})
    old = InventorySnapshot(
        snapshot_id="old",
        scope=SeriesScope(station_ids=("a",), product_ids=("q",)),
        members=("s",),
        member_facts=(("s", ("f",)),),
        completeness=InventoryCompleteness.INCOMPLETE,
        reason=metadata.reason,
        access="daily",
        origin="response",
        evidence=("source-call:census",),
        window=metadata.window,
    )
    new = old.model_copy(
        update={
            "snapshot_id": "new",
            "completeness": InventoryCompleteness.COMPLETE,
            "reason": None,
            "evidence": ("source-call:new-census",),
        }
    )
    current = compact_evidence(
        (),
        (metadata,),
        (old, new),
        (issue,),
        ({"call_id": "census"}, {"call_id": "new-census"}),
        new_inventory_ids=frozenset(("new",)),
        new_outcome_ids=frozenset((metadata.outcome_id,)),
    )
    assert current.outcomes == (metadata,)
    assert current.issues == (issue,)


def test_acquisition_linked_source_notes_follow_retained_support_without_interpreting_codes():
    old, fresh = _outcome("old"), _outcome("fresh")
    old_note = Issue(
        severity="info",
        code="source.quality",
        message="Published code A",
        details={"acquisition_ids": ("old",), "source_quality_code": "A"},
    )
    fresh_note = old_note.model_copy(
        update={"message": "Published code B", "details": {"acquisition_ids": ("fresh",), "source_quality_code": "B"}}
    )
    calls = ({"call_id": "old"}, {"call_id": "fresh"})
    current = compact_evidence((_cover(fresh),), (old, fresh), (), (old_note, fresh_note), calls)
    assert current.issues == (fresh_note,)
    assert current.source_calls == calls[1:]
    from dataclasses import replace

    held_part = replace(_cover(old), interval=RequestedInterval(_START, datetime(2020, 1, 14)))
    new_part = replace(_cover(fresh), interval=RequestedInterval(datetime(2020, 1, 15), _END))
    partial = compact_evidence((held_part, new_part), (old, fresh), (), (old_note, fresh_note), calls)
    assert partial.issues == (old_note, fresh_note)


def test_support_only_failure_issue_never_reactivates_through_retained_call():
    failed = _outcome("old-failure", status=OutcomeStatus.FAILED)
    inventory = InventorySnapshot(
        snapshot_id="inventory",
        scope=SeriesScope(),
        members=(),
        completeness=InventoryCompleteness.INCOMPLETE,
        reason="Acquisition support",
        access="daily",
        origin="response",
        evidence=("retrieval-outcome:old-failure",),
    )
    current = compact_evidence(
        (), (), (inventory,), (_issue(failed),), ({"call_id": "old-failure"},), supporting_outcomes=(failed,)
    )
    assert current.supporting_outcomes == (failed,)
    assert current.issues == ()


def test_acquisition_notes_keep_active_fragments_once_and_never_support_only():
    failed = _outcome("failed", status=OutcomeStatus.FAILED)
    recovered = _outcome("recovered", start=datetime(2020, 1, 10), end=datetime(2020, 1, 20))
    issue = Issue(
        severity="info",
        code="source.quality",
        message="Uninterpreted source vocabulary",
        details={"acquisition_ids": (failed.outcome_id,), "source_code": "raw"},
    )
    current = compact_evidence(
        (_cover(recovered),), (failed, recovered), (), (issue,), ({"call_id": "failed"}, {"call_id": "recovered"})
    )
    fragments = tuple(item.outcome_id for item in current.outcomes if item.status == OutcomeStatus.FAILED)
    assert len(fragments) == 2
    assert len(current.issues) == 1
    assert current.issues[0].details == {"acquisition_ids": (failed.outcome_id,), "source_code": "raw"}
    inventory = InventorySnapshot(
        snapshot_id="history",
        scope=SeriesScope(),
        members=(),
        completeness=InventoryCompleteness.INCOMPLETE,
        reason="Original acquisition",
        access="daily",
        origin="response",
        evidence=("retrieval-outcome:failed",),
    )
    historical = compact_evidence(
        (), (), (inventory,), (issue,), ({"call_id": "failed"},), supporting_outcomes=(failed,)
    )
    assert historical.issues == ()


def test_issue_acquisition_links_follow_retry_aliases_but_not_support_only():
    outcome = _outcome("final-attempt")
    note = Issue(
        severity="info",
        code="source.quality",
        message="Published vocabulary",
        details={"acquisition_ids": ("first-attempt", "unrelated")},
    )
    calls = (
        {"call_id": "first-attempt", "acquisition_id": "payload"},
        {"call_id": "final-attempt", "acquisition_id": "payload"},
        {"call_id": "unrelated"},
    )
    current = compact_evidence((_cover(outcome),), (outcome,), (), (note,), calls)
    assert current.issues[0].details["acquisition_ids"] == ("first-attempt",)
    assert current.source_calls == calls[:2]

"""Authored acquisition identities stay distinct when response facts repeat."""

from dataclasses import replace
from datetime import UTC, datetime

import polars.testing as pt
import pytest

from rivretrieve._internal.driver import _bind_acquisition_evidence, drive
from rivretrieve._internal.engine import SourceCoordinates, WithIssues
from rivretrieve._internal.issues import FatalContractError, Issue
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.store import StoreRoot, validate_store
from rivretrieve._internal.store.accumulation import _merge_records
from tests.test_internal_driver import (
    _LEVEL_WINDOW_DECLARATIONS,
    _config,
    _parsed,
    _payload,
    _provenance,
    _request,
    _rows,
    _windows,
)


@pytest.mark.parametrize("failed", [False, True])
def test_reacquired_identical_parser_outcomes_keep_distinct_call_identity(tmp_path, failed):
    requested, fetched = _windows()
    request = _request(requested, ("station-1",))
    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    rows = _rows("station-1", 12, 10.0)
    calls = []

    class Provider:
        window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def fetch(self, *args, **kwargs):
            payload = _payload("station-1", coordinates, fetched)
            calls.append(payload.acquisition_id)
            return WithIssues((payload,))

        def parse(self, payload, config):
            parsed = _parsed(rows.clear() if failed else rows, payload, config)
            outcome = parsed.outcomes[0].model_copy(
                update={
                    "retrieved_at": datetime(2026, 1, 5, tzinfo=UTC),
                    **({"status": OutcomeStatus.FAILED, "reason": "authored failure"} if failed else {}),
                }
            )
            snapshot = parsed.inventories[0].model_copy(
                update={
                    "evidence": ("retrieval-outcome:" + outcome.outcome_id,),
                }
            )
            issues = (
                (
                    Issue(
                        severity="warning",
                        code="source.request_failed",
                        message="authored failure",
                        details={"outcome_id": outcome.outcome_id},
                    ),
                )
                if failed
                else ()
            )
            return replace(parsed, outcomes=(outcome,), inventories=(snapshot,), issues=issues)

    provider = Provider()
    provider.config = config
    store = StoreRoot(tmp_path / "store")

    def run(cache):
        return drive(request, provider, provenance=_provenance(request), cache=cache, store=store)

    first = run("refresh")
    second = run("refresh")
    assert calls[0] != calls[1]
    assert first.outcomes[0].outcome_id != second.outcomes[0].outcome_id
    pt.assert_frame_equal(first.canonical_rows, second.canonical_rows)
    manifest = validate_store(store, request.provider_id).manifest
    assert len(manifest.outcomes) == 1
    assert manifest.outcomes[0].calls == (calls[-1],)
    if not failed:
        cached = run("reuse")
        assert len(calls) == 2
        pt.assert_frame_equal(cached.canonical_rows, second.canonical_rows)


def test_binding_remaps_inventory_and_explicit_issue_links():
    _, fetched = _windows()
    coordinates = SourceCoordinates({"parameter": "height"})
    parsed = _parsed(_rows("station-1", 12, 10.0), _payload("station-1", coordinates, fetched), _config(coordinates))
    original = parsed.outcomes[0]
    snapshot = parsed.inventories[0]
    snapshot = snapshot.model_copy(
        update={
            "evidence": (
                "retrieval-outcome:" + original.outcome_id,
                "source-inventory:" + snapshot.snapshot_id,
            )
        }
    )
    issue = Issue(
        severity="warning",
        code="source.request_failed",
        message="authored failure",
        details={"outcome_id": original.outcome_id, "snapshot_id": snapshot.snapshot_id},
    )
    outcomes, inventories, issues = _bind_acquisition_evidence((original,), (snapshot,), (issue,), ("authored-call",))
    assert outcomes[0].calls == ("authored-call",)
    assert inventories[0].evidence == (
        "retrieval-outcome:" + outcomes[0].outcome_id,
        "source-inventory:" + inventories[0].snapshot_id,
        "source-call:authored-call",
    )
    assert issues[0].details == {"outcome_id": outcomes[0].outcome_id, "snapshot_id": inventories[0].snapshot_id}
    assert outcomes[0].window == original.window
    assert outcomes[0].retrieved_at == original.retrieved_at
    with pytest.raises(FatalContractError, match="contradicts existing outcome_id"):
        _merge_records(outcomes, (outcomes[0].model_copy(update={"calls": ("other-call",)}),), "outcome_id")


@pytest.mark.parametrize("conflict", ["window", "facts", "status", "inventory"])
def test_binding_rejects_conflicting_raw_identity_before_projection(conflict):
    _, fetched = _windows()
    coordinates = SourceCoordinates({"parameter": "height"})
    parsed = _parsed(_rows("station-1", 12, 10.0), _payload("station-1", coordinates, fetched), _config(coordinates))
    outcome = parsed.outcomes[0]
    snapshot = parsed.inventories[0]
    outcomes = (outcome, outcome)
    inventories = (snapshot, snapshot)
    if conflict == "inventory":
        inventories = (snapshot, snapshot.model_copy(update={"access": "different authored access"}))
    else:
        updates = {
            "window": {"window": outcome.window.model_copy(update={"end": outcome.window.start})},
            "facts": {"facts_ids": ("different-authored-facts",)},
            "status": {"status": OutcomeStatus.EMPTY},
        }
        outcomes = (outcome, outcome.model_copy(update=updates[conflict]))
    with pytest.raises(FatalContractError, match="Acquisition contradicts existing"):
        _bind_acquisition_evidence(outcomes, inventories, (), ("one-authored-acquisition",))


def test_binding_accepts_identical_records_within_one_acquisition():
    _, fetched = _windows()
    coordinates = SourceCoordinates({"parameter": "height"})
    parsed = _parsed(_rows("station-1", 12, 10.0), _payload("station-1", coordinates, fetched), _config(coordinates))
    outcome = parsed.outcomes[0]
    snapshot = parsed.inventories[0]
    outcomes, inventories, _ = _bind_acquisition_evidence(
        (outcome, outcome), (snapshot, snapshot), (), ("one-authored-acquisition",)
    )
    assert outcomes[0] == outcomes[1]
    assert inventories[0] == inventories[1]


def test_auxiliary_overflow_call_retains_attempts_through_assembled_driver(tmp_path):
    from rivretrieve._internal.engine import SourceAcquisition
    from rivretrieve._internal.transport import TransportAttempt, TransportFailureCategory

    requested, fetched = _windows()
    request = _request(requested, ("station-1",))
    coordinates = SourceCoordinates({"parameter": "height"})
    config = _config(coordinates)
    payload = _payload("station-1", coordinates, fetched)
    attempts = (
        TransportAttempt(
            "retry",
            "https://example.test/overflow",
            {},
            datetime(2026, 1, 1, tzinfo=UTC),
            status_code=503,
            failure_category=TransportFailureCategory.HTTP_STATUS,
        ),
        TransportAttempt(
            "overflow", "https://example.test/overflow", {}, datetime(2026, 1, 1, tzinfo=UTC), status_code=200
        ),
    )
    parent = replace(
        payload.origin,
        url="https://example.test/overflow",
        attempts=2,
        attempt_traces=attempts,
        acquisition_id="parent-overflow",
    )
    payload = replace(payload, prerequisite_acquisition_ids=("parent-overflow",))
    sibling = replace(
        parent,
        url="https://example.test/failed-sibling",
        acquisition_id="failed-sibling",
        prerequisite_acquisition_ids=("parent-overflow",),
        attempt_traces=(),
        attempts=1,
    )

    class Provider:
        window_declarations = _LEVEL_WINDOW_DECLARATIONS

        def fetch(self, *args, **kwargs):
            return SourceAcquisition((payload,), calls=(parent, sibling))

        def parse(self, payload, config):
            return _parsed(_rows("station-1", 12, 10.0), payload, config)

    provider = Provider()
    provider.config = config
    store = StoreRoot(tmp_path / "store")
    result = drive(request, provider, provenance=_provenance(request), cache="refresh", store=store)
    cached = drive(request, provider, provenance=_provenance(request), cache="reuse", store=store)
    assert not any(call["url"] == "https://example.test/failed-sibling" for call in cached.provenance.calls_made)
    assert any(call["url"] == "https://example.test/overflow" for call in cached.provenance.calls_made)
    parent_calls = [call for call in result.provenance.calls_made if call["url"] == "https://example.test/overflow"]
    assert len(parent_calls) == 1
    assert [(item["call_id"], item["status_code"]) for item in parent_calls[0]["attempt_traces"]] == [
        ("retry", 503),
        ("overflow", 200),
    ]
    assert all(outcome.status is not OutcomeStatus.FAILED for outcome in result.outcomes)

"""Reuse must retain newest scoped inventory knowledge and isolate held diagnostics."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.driver import _reusable_snapshot
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    RetrievalOutcome,
    SeriesScope,
    SourceIdentity,
    stable_id,
)
from rivretrieve._internal.store import StoreReader, StoreRoot
from rivretrieve._internal.store.accumulation import StoreUpdate, accumulate
from tests.test_source_series_store import _definition, _success, _update


def test_newest_complete_inventory_with_uncovered_late_member_prevents_older_snapshot_reuse(tmp_path: Path) -> None:
    store = StoreRoot(tmp_path / "store")
    first, late = _definition("first"), _definition("late")
    answer = _success(first.series_id, "first-answer", [12.0])
    scope = SeriesScope(provider_ids=("fixture_live",), station_ids=("a",), product_ids=("level",))
    old = InventorySnapshot(
        snapshot_id="old",
        scope=scope,
        members=(first.series_id,),
        completeness=InventoryCompleteness.COMPLETE,
        access="recorded supported scope",
        origin="response",
        acquired_at=datetime(2026, 9, 1, tzinfo=UTC),
        window=answer[0].window,
        evidence=("first inventory",),
    )
    accumulate(store, ProviderId("fixture_live"), _update((first,), (answer,), (old,)))
    newest = old.model_copy(
        update={
            "snapshot_id": "newest",
            "members": (first.series_id, late.series_id),
            "acquired_at": old.acquired_at + timedelta(days=1),
            "evidence": ("later inventory",),
        }
    )
    manifest = accumulate(store, ProviderId("fixture_live"), _update((late,), inventories=(newest,)))
    assert {item.series_id for item in manifest.coverage} == {first.series_id}
    chosen = _reusable_snapshot(manifest, scope, answer[0].window)
    assert chosen is None, "known late member has no coverage; older inventory must not hide it"


@pytest.mark.parametrize("policy", ["raise", "ignore"])
@pytest.mark.parametrize("contamination", ["issue", "provenance"])
def test_public_healthy_subset_reuse_excludes_unrelated_stored_failure_and_source_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, policy: str, contamination: str
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    recording = read_recording(
        Path(__file__).parent / "test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
    )
    replay = ReplayTransport((recording,))
    calls = []

    class CountedReplay:
        def send(self, request):
            calls.append(request)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", lambda: CountedReplay())
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    first = rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="reuse", on_issue="ignore")
    store = StoreRoot(next(tmp_path.rglob("manifest.json")).parent)
    manifest = StoreReader().status(store, ProviderId("usgs_nwis")).manifest
    assert manifest is not None
    healthy = next(item for item in manifest.series if item.station_id == "07374000")
    failing = healthy.model_copy(
        update={
            "series_id": stable_id("unrelated controlled failure"),
            "station_id": "unrelated-station",
            "identity": SourceIdentity(
                namespace="controlled failing access", origin="mapping", evidence=("controlled failed source request",)
            ),
        }
    )
    failure = RetrievalOutcome(
        outcome_id="unrelated-failure",
        series_id=failing.series_id,
        station_id=failing.station_id,
        product_id=failing.product_id,
        window=manifest.outcomes[0].window,
        status=OutcomeStatus.FAILED,
        reason="unrelated request unavailable",
        calls=("unrelated-call",),
    )
    issue = Issue(
        severity="error",
        code="source_failure",
        message=failure.reason,
        provider_id=ProviderId("usgs_nwis"),
        details={"series_id": failing.series_id, "station_id": failing.station_id, "product_id": failing.product_id},
    )
    source_call = {
        "call_id": "unrelated-call",
        "url": "https://example.invalid/unrelated-source",
        "request_parameters": {"sites": failing.station_id},
        "retrieved_at": datetime(2026, 9, 2, tzinfo=UTC),
    }
    accumulate(
        store,
        ProviderId("usgs_nwis"),
        StoreUpdate((failing,), (), (failure,), (), (issue,) if contamination == "issue" else (), (source_call,)),
    )
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="reuse", on_issue=policy)
    assert len(calls) == 1, "healthy recorded series must remain a local reuse"
    assert issue not in result.issues
    assert source_call not in result.provenance.calls_made
    assert result.provenance.calls_made == first.provenance.calls_made
    retained = StoreReader().status(store, ProviderId("usgs_nwis")).manifest
    assert retained is not None and source_call in retained.source_calls
    if contamination == "issue":
        assert issue in retained.issues


def test_known_explicit_series_reuses_success_without_claiming_incomplete_inventory_is_all(tmp_path: Path) -> None:
    from rivretrieve._internal.source_series import RestrictionKind

    store = StoreRoot(tmp_path / "store")
    definition = _definition("known-explicit")
    answer = _success(definition.series_id, "explicit-answer", [12.0])
    broad = SeriesScope(provider_ids=("fixture_live",), station_ids=("a",), product_ids=("level",))
    incomplete = InventorySnapshot(
        snapshot_id="incomplete",
        scope=broad,
        members=(definition.series_id,),
        completeness=InventoryCompleteness.INCOMPLETE,
        access="scoped source request",
        origin="response",
        window=answer[0].window,
        evidence=("known requested identity",),
        reason="other alternatives not established",
    )
    manifest = accumulate(store, ProviderId("fixture_live"), _update((definition,), (answer,), (incomplete,)))
    explicit = broad.model_copy(update={"restriction": RestrictionKind.EXPLICIT, "series_ids": (definition.series_id,)})
    reused = _reusable_snapshot(manifest, explicit, answer[0].window)
    assert reused is not None, "successful concrete restriction does not require complete ALL membership"
    assert reused.inventories[0].completeness is InventoryCompleteness.INCOMPLETE
    assert tuple(item.series_id for item in reused.series) == (definition.series_id,)
    assert _reusable_snapshot(manifest, broad, answer[0].window) is None

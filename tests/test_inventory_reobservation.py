"""Re-observing an immutable inventory snapshot updates acquisition order, not source facts."""

from pathlib import Path

from rivretrieve._internal.driver import _reusable_snapshot
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import InventoryCompleteness, InventorySnapshot, SeriesScope
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.store.accumulation import accumulate
from tests.test_source_series_store import _definition, _success, _update


def test_reobserved_snapshot_moves_to_latest_without_inventing_source_timestamp(tmp_path: Path) -> None:
    store = StoreRoot(tmp_path / "store")
    a, b = _definition("a-series"), _definition("b-series")
    a_answer, b_answer = _success(a.series_id, "a-answer", [1.0]), _success(b.series_id, "b-answer", [2.0])
    scope = SeriesScope(provider_ids=("fixture_live",), station_ids=("a",), product_ids=("level",))
    first = InventorySnapshot(
        snapshot_id="A",
        scope=scope,
        members=(a.series_id,),
        completeness=InventoryCompleteness.COMPLETE,
        access="recorded complete scoped response",
        origin="response",
        acquired_at=None,
        window=a_answer[0].window,
        evidence=("immutable source inventory A",),
    )
    second = first.model_copy(
        update={
            "snapshot_id": "B",
            "members": (a.series_id, b.series_id),
            "evidence": ("immutable source inventory B",),
        }
    )
    accumulate(store, ProviderId("fixture_live"), _update((a,), (a_answer,), (first,)))
    accumulate(store, ProviderId("fixture_live"), _update((b,), (b_answer,), (second,)))
    manifest = accumulate(store, ProviderId("fixture_live"), _update((), inventories=(first,)))
    plan = _reusable_snapshot(manifest, scope, a_answer[0].window)
    assert plan is not None
    assert tuple(item.series_id for item in plan.series) == (a.series_id,), (
        "latest observed A must not serve B's absent member"
    )
    assert tuple(item.snapshot_id for item in manifest.inventories) == ("B", "A")
    assert manifest.inventories == (second, first)
    assert manifest.inventories[-1] == first
    assert manifest.inventories[-1].acquired_at is None
    assert {item.series_id for item in manifest.series} == {a.series_id, b.series_id}

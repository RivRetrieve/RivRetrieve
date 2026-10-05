"""Authored source notes and inventory uncertainty retain their public scope."""

import json
from datetime import UTC, datetime

import polars.testing as pt
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse


@pytest.fixture
def authored_cache(monkeypatch, tmp_path):
    selected = rr.find(provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean")
    versions = sorted({int(item.identity.published_id) for item in selected.series})

    class AuthoredHydAPI:
        metadata_failed = False
        observations_failed = False
        forbid_network = False

        def __init__(self):
            self.calls = []

        def send(self, request):
            self.calls.append(request)
            assert not self.forbid_network, "Covered explicit members must not fetch again"
            if request.url.endswith("/Series"):
                if self.metadata_failed:
                    raise TransportFailure(request, TransportFailureReason.RETRY_EXHAUSTED, 3, status_code=503)
                entries = [
                    {
                        "stationId": "109.42.0",
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
                if self.observations_failed:
                    raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
                body = {
                    "data": [
                        {
                            "stationId": "109.42.0",
                            "parameter": 1001,
                            "serieVersionNo": int(request.params["VersionNumber"]),
                            "unit": "m³/s",
                            "method": "Mean",
                            "observationCount": 1,
                            "observations": [
                                {"time": "2025-07-10T00:00:00Z", "value": 7.0, "quality": 41, "correction": 1}
                            ],
                        }
                    ]
                }
            return TransportResponse(
                json.dumps(body).encode(),
                200,
                datetime(2026, 9, 20, tzinfo=UTC),
                "application/json",
                request.url,
                request.params,
            )

    transport = AuthoredHydAPI()
    monkeypatch.setenv("NVE_API_KEY", "authored-not-a-real-credential")
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    return selected, versions, transport


def _fetch(selected, **kwargs):
    return rr.fetch(selected, start="2025-07-10", end="2025-07-10", **kwargs)


def test_cached_source_notes_equal_fresh_notes_after_unrequested_failure(authored_cache):
    selected, versions, transport = authored_cache
    selected = rr.pick(selected, variant=str(versions[0]))
    fresh = _fetch(selected, cache="refresh", on_issue="raise")
    assert fresh.issues
    assert any((issue.details or {}).get("source_quality_code") == 41 for issue in fresh.issues)
    assert all("acquisition_ids" not in (issue.details or {}) for issue in fresh.issues)
    transport.forbid_network = True
    reused = _fetch(selected, cache="reuse", on_issue="raise")
    assert reused.issues == fresh.issues
    pt.assert_frame_equal(reused.data, fresh.data)
    transport.forbid_network = False
    transport.observations_failed = True
    failed = rr.fetch(selected, start="2025-07-15", end="2025-07-15", cache="refresh", on_issue="ignore")
    assert any(issue.code == "source.request_failed" for issue in failed.issues)
    transport.forbid_network = True
    restored = _fetch(selected, cache="reuse", on_issue="raise")
    assert restored.issues == fresh.issues
    assert restored.provenance.calls_made == fresh.provenance.calls_made
    pt.assert_frame_equal(restored.data, fresh.data)


@pytest.mark.parametrize("member_count", [1, 2])
def test_explicit_members_reuse_independent_inventories_despite_all_uncertainty(authored_cache, member_count):
    selected, versions, transport = authored_cache
    assert len(versions) >= member_count
    transport.metadata_failed = True
    counts = []
    for _ in range(3):
        initial = _fetch(selected, cache="refresh", on_issue="ignore")
        manifest = rr.cache_status("no_nve").manifest
        assert manifest is not None
        counts.append((len(manifest.inventories), len(manifest.outcomes), len(manifest.source_calls)))
    assert counts[1:] == counts[:1] * 2
    inventory_issues = tuple(issue for issue in initial.issues if issue.code == "source.inventory_unresolved")
    assert inventory_issues
    explicit = rr.pick(selected, variant=tuple(str(version) for version in versions[:member_count]))
    expected = rr.pick(initial, variant=tuple(str(version) for version in versions[:member_count]), on_issue="ignore")
    before = len(transport.calls)
    transport.forbid_network = True
    try:
        reused = _fetch(explicit, cache="reuse", on_issue="raise")
    finally:
        assert len(transport.calls) == before
    pt.assert_frame_equal(reused.data, expected.data)
    assert not any(issue.code == "source.inventory_unresolved" for issue in reused.issues)
    assert all(item.completeness.value == "incomplete" for item in reused.inventories if item.origin != "catalogue")
    # Compare against the same explicit acquisition, not broad-result notes
    # whose station-only source context cannot identify a particular member.
    transport.forbid_network = False
    fresh_explicit = _fetch(explicit, cache="bypass", on_issue="ignore")
    assert reused.issues == tuple(
        issue for issue in fresh_explicit.issues if issue.code != "source.inventory_unresolved"
    )


def test_all_and_unknown_scopes_keep_inventory_uncertainty(authored_cache):
    selected, _, transport = authored_cache
    transport.metadata_failed = True
    initial = _fetch(selected, cache="refresh", on_issue="ignore")
    assert any(issue.code == "source.inventory_unresolved" for issue in initial.issues)
    before_all = len(transport.calls)
    with pytest.raises(IssuePolicyError) as all_error:
        _fetch(selected, cache="reuse", on_issue="raise")
    assert len(transport.calls) > before_all
    assert any(issue.code == "source.inventory_unresolved" for issue in all_error.value.issues)
    unknown = rr.pick(selected, series_id="authored-unknown-member", on_issue="ignore")
    before = len(transport.calls)
    transport.forbid_network = True
    with pytest.raises(IssuePolicyError) as unknown_error:
        _fetch(unknown, cache="reuse", on_issue="raise")
    assert any(issue.code == "source.inventory_unresolved" for issue in unknown_error.value.issues)
    assert len(transport.calls) == before


def _inventory(name, members, *, facts=(), complete=False, start=1, end=10):
    from rivretrieve._internal.source_series import InventoryCompleteness, InventorySnapshot, SeriesScope, SeriesWindow

    return InventorySnapshot(
        snapshot_id=name,
        scope=SeriesScope(station_ids=("authored-station",)),
        members=members,
        member_facts=facts,
        completeness=InventoryCompleteness.COMPLETE if complete else InventoryCompleteness.INCOMPLETE,
        access="authored-response",
        origin="response",
        evidence=(name,),
        reason=None if complete else "Only the requested members are established",
        window=SeriesWindow(start=datetime(2020, 1, start), end=datetime(2020, 1, end)),
    )


def test_incomplete_sibling_members_and_facts_survive_compaction():
    from rivretrieve._internal.store.authority import compact_inventories

    first = _inventory("first", ("a",), facts=(("a", ("f",)),))
    sibling = _inventory("sibling", ("b",), facts=(("b", ("f",)),))
    other_fact = _inventory("other-fact", ("a",), facts=(("a", ("g",)),))
    assert compact_inventories((first, sibling, other_fact)) == (first, sibling, other_fact)
    unknown_fact = _inventory("unknown-fact", ("a",))
    assert compact_inventories((first, unknown_fact)) == (first, unknown_fact)
    assert compact_inventories((unknown_fact, first)) == (first,)


def test_later_incomplete_siblings_together_replace_positive_support_without_completeness():
    from rivretrieve._internal.source_series import InventoryCompleteness
    from rivretrieve._internal.store.authority import compact_inventories

    old = _inventory("old", ("a", "b"), facts=(("a", ("f", "g")), ("b", ("f",))))
    first = _inventory("first", ("a",), facts=(("a", ("f",)),))
    second = _inventory("second", ("a",), facts=(("a", ("g",)),))
    third = _inventory("third", ("b",), facts=(("b", ("f",)),))
    assert compact_inventories((old, first, second)) == (old, first, second)
    current = compact_inventories((old, first, second, third))
    assert current == (first, second, third)
    assert all(item.completeness is InventoryCompleteness.INCOMPLETE for item in current)
    repeated = tuple(item.model_copy(update={"snapshot_id": "new-" + item.snapshot_id}) for item in current)
    assert compact_inventories((*current, *repeated)) == repeated


def test_partial_window_does_not_replace_incomplete_member_support():
    from rivretrieve._internal.store.authority import compact_inventories

    old = _inventory("old", ("a",), facts=(("a", ("f",)),))
    partial = _inventory("partial", ("a",), facts=(("a", ("f",)),), end=5)
    assert compact_inventories((old, partial)) == (old, partial)


def test_new_complete_census_replaces_incomplete_members_and_remains_a_boundary():
    from rivretrieve._internal.store.authority import compact_inventories

    old = _inventory("old", ("a",), facts=(("a", ("f",)),))
    complete = _inventory("complete", ("b",), complete=True)
    incomplete = _inventory("incomplete", ("c",))
    assert compact_inventories((old, complete)) == (complete,)
    # The newest incomplete census invalidates complete ALL reuse. It does not
    # resurrect members excluded by the intervening complete census.
    assert compact_inventories((old, complete, incomplete)) == (incomplete,)

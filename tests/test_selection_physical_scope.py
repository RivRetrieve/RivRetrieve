"""Public offline selection preserves physical intent and published alternatives."""

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery


def test_daily_discharge_discovery_includes_both_ana_consistency_series(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_transport():
        raise AssertionError("offline discovery must not acquire observations")

    monkeypatch.setattr(discovery, "HttpClient", forbidden_transport)
    selected = rr.find(provider="br_ana", station="15400000", quantity="discharge", frequency="daily", statistic="mean")
    inspected = rr.series(selected)
    assert set(inspected["variant"].to_list()) == {"bruto", "consistido"}
    assert inspected["series_id"].n_unique() == 2
    narrowed = rr.pick(selected, variant="consistido")
    assert rr.series(narrowed)["variant"].to_list() == ["consistido"]
    assert rr.series(selected).height == 2


def test_physical_find_and_pick_have_identical_matching_series() -> None:
    broad = rr.find(provider="br_ana", station="15400000", quantity="discharge")
    narrowed = rr.pick(broad, frequency="daily", statistic="mean")
    direct = rr.find(provider="br_ana", station="15400000", quantity="discharge", frequency="daily", statistic="mean")
    pl_testing.assert_frame_equal(rr.series(narrowed), rr.series(direct))


def test_legacy_triple_import_is_refused_instead_of_rebuilding_scientific_facts() -> None:
    frame = pl.DataFrame(
        {"provider_id": ["usgs_nwis"], "station_id": ["01646500"], "product_id": ["discharge_daily_mean"]}
    )
    with pytest.raises((ValueError, TypeError), match="(?i)(bundle|format|version)"):
        rr.from_frame(frame)


def test_selection_bundle_preserves_scope_and_explicit_restriction() -> None:
    selection = rr.find(
        provider="br_ana", station="15400000", quantity="discharge", frequency="daily", statistic="mean"
    )
    narrowed = rr.pick(selection, variant="consistido")
    restored = rr.from_bundle(rr.to_bundle(narrowed))
    assert restored.scope == narrowed.scope
    assert restored.known_series == narrowed.known_series
    assert restored.inventories == narrowed.inventories
    assert restored.issues == narrowed.issues
    pl_testing.assert_frame_equal(rr.series(restored), rr.series(narrowed))


def test_disjoint_pick_is_named_empty_not_widened_scope() -> None:
    from rivretrieve._internal.source_series import ScopeState

    selection = rr.find(
        provider="br_ana", station="15400000", quantity="discharge", frequency="daily", statistic="mean"
    )
    narrowed = rr.pick(rr.pick(selection, variant="bruto"), variant="consistido", on_issue="ignore")
    assert narrowed.scope.state is ScopeState.EMPTY
    assert rr.series(narrowed).is_empty()
    restored = rr.from_bundle(rr.to_bundle(narrowed))
    assert restored.scope.state is ScopeState.EMPTY
    assert rr.series(restored).is_empty()
    assert restored.issues == narrowed.issues


def test_explicit_unresolved_identity_survives_round_trip_without_sibling_fallback() -> None:
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    unresolved = rr.pick(selection, variant="response-owned-unseen-method", on_issue="ignore")
    assert unresolved.series == ()
    assert unresolved.scope.variants == ("response-owned-unseen-method",)
    assert unresolved.issues[-1].code == "selection.unresolved_inventory"
    restored = rr.from_bundle(rr.to_bundle(unresolved))
    assert restored.scope == unresolved.scope
    assert restored.known_series == unresolved.known_series
    assert restored.issues == unresolved.issues


@pytest.mark.parametrize("policy", ["raise", "warn", "ignore"])
def test_established_no_match_uses_issue_policy_without_fallback(policy: str) -> None:
    from dataclasses import replace

    from rivretrieve._internal.issues import IssuePolicyError
    from rivretrieve._internal.source_series import InventoryCompleteness, InventorySnapshot

    # This authored scope-completeness assertion tests policy mechanics, not ANA inventory evidence.
    selection = rr.find(
        provider="br_ana", station="15400000", quantity="discharge", frequency="daily", statistic="mean"
    )
    complete = InventorySnapshot(
        snapshot_id="test-complete-scope",
        scope=selection.scope,
        members=tuple(item.series_id for item in selection.series),
        completeness=InventoryCompleteness.COMPLETE,
        access="test-policy-contract",
        origin="response",
        evidence=("authored-policy-contract",),
    )
    selection = replace(selection, inventories=(complete,))
    if policy == "raise":
        with pytest.raises(IssuePolicyError):
            rr.pick(selection, variant="not-a-source-series", on_issue=policy)
    elif policy == "warn":
        with pytest.warns(RuntimeWarning, match="No source series"):
            result = rr.pick(selection, variant="not-a-source-series", on_issue=policy)
        assert result.series == ()
        assert result.issues[-1].code == "selection.no_match"
    else:
        result = rr.pick(selection, variant="not-a-source-series", on_issue=policy)
        assert result.series == ()
        assert result.issues[-1].code == "selection.no_match"


def test_complete_inventory_remains_complete_for_more_precise_physical_restriction() -> None:
    from dataclasses import replace

    from rivretrieve._internal.source_series import InventoryCompleteness, InventorySnapshot

    # Authored scope proof isolates containment semantics; it does not certify ANA inventory.
    broad = rr.find(provider="br_ana", station="15400000", quantity="discharge")
    inventory = InventorySnapshot(
        snapshot_id="contract-broad-scope",
        scope=broad.scope,
        members=tuple(item.series_id for item in broad.known_series),
        completeness=InventoryCompleteness.COMPLETE,
        access="contract-scope-containment",
        origin="response",
        evidence=("authored-contract",),
    )
    complete = replace(broad, inventories=(inventory,))
    selected = rr.pick(complete, frequency="daily", statistic="mean", variant="not-published", on_issue="ignore")
    assert selected.series == ()
    assert selected.issues[-1].code == "selection.no_match"


def test_imported_selection_narrows_its_own_evidence_without_reloading_packaged_catalogues(monkeypatch) -> None:
    from rivretrieve._internal.registry import _registry

    selection = rr.find(
        provider="br_ana", station="15400000", quantity="discharge", frequency="daily", statistic="mean"
    )
    restored = rr.from_bundle(rr.to_bundle(selection))
    _registry.clear()
    calls = []
    original = discovery._ensure_default_providers_registered

    def counted_registration():
        calls.append("registration")
        return original()

    monkeypatch.setattr(discovery, "_ensure_default_providers_registered", counted_registration)
    narrowed = rr.pick(restored, variant="consistido")
    assert rr.series(narrowed)["variant"].to_list() == ["consistido"]
    assert calls == []


def test_series_inspection_only_visits_inventory_members_for_each_identity(monkeypatch) -> None:
    import rivretrieve._internal.selection as selection_module

    selection = rr.find(provider="usgs_nwis", station="01646500")
    visited = []
    original = selection_module._inventory_contains_facts

    def counted_membership(inventory, series_id, facts_id):
        visited.append((inventory.snapshot_id, series_id))
        assert series_id in inventory.members, "Inspection scanned an unrelated inventory for this identity"
        return original(inventory, series_id, facts_id)

    monkeypatch.setattr(selection_module, "_inventory_contains_facts", counted_membership)
    inspected = rr.series(selection)
    assert inspected.height >= 3
    inspected_ids = set(inspected["series_id"].to_list())
    has_associated_inventory = any(inspected_ids.intersection(item.members) for item in selection.inventories)
    assert bool(visited) == has_associated_inventory


def test_public_product_shorthand_is_refused_instead_of_misclassifying_physical_meaning() -> None:
    with pytest.raises(TypeError, match="product"):
        rr.find(provider="br_ana", product="discharge_daily_mean")
    selection = rr.find(provider="br_ana", station="15400000", quantity="discharge")
    with pytest.raises(TypeError, match="product"):
        rr.pick(selection, product="discharge_daily_mean")


def test_explicit_catalogue_identity_routes_only_its_source_access(monkeypatch, tmp_path) -> None:
    from tests.test_br_ana_public_daily import _authenticated_replay

    monkeypatch.chdir(tmp_path)
    transport = _authenticated_replay(monkeypatch, "stage_daily_mean_consistido")
    selected = rr.pick(
        rr.find(provider="br_ana", station="15400000", quantity="stage", frequency="daily", statistic="mean"),
        variant="consistido",
    )
    result = rr.fetch(selected, start="2020-01-10", end="2020-01-20", on_issue="ignore")
    assert result.data.height == 11
    assert transport.observation_calls == 1


def test_nve_daily_resolution_does_not_make_instantaneous_version_a_mean() -> None:
    # Real packaged source inventory: parameter1000 at station1.46.0 has daily Mean v1 and Instantaneous v2.
    daily = rr.find(provider="no_nve", station="1.46.0", quantity="stage", frequency="daily")
    inspected = rr.series(daily)
    assert set(inspected.select("published_id", "statistic").iter_rows()) == {("1", "mean"), ("2", "instantaneous")}
    mean = rr.pick(daily, statistic="mean")
    assert rr.series(mean)["published_id"].to_list() == ["1"]
    direct = rr.find(provider="no_nve", station="1.46.0", quantity="stage", frequency="daily", statistic="mean")
    pl_testing.assert_frame_equal(rr.series(mean), rr.series(direct))


def test_prefetch_station_narrowing_exports_only_relevant_independent_inventory(monkeypatch) -> None:
    import json
    from io import BytesIO
    from zipfile import ZipFile

    broad = rr.find(provider="ch_foen", quantity="discharge")
    station_ids = rr.series(broad)["station_id"].unique().sort().to_list()[:2]
    assert len(station_ids) == 2
    two_stations = rr.pick(broad, station=station_ids)
    original_definitions = two_stations.known_series
    original_snapshots = two_stations.inventories
    selected = rr.pick(two_stations, station=station_ids[0])
    with ZipFile(BytesIO(rr.to_bundle(selected))) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert {item["station_id"] for item in manifest["series"]} == {station_ids[0]}
    assert {station for item in manifest["inventories"] for station in item["scope"]["station_ids"]} == {station_ids[0]}
    assert {item["station_id"] for item in manifest["locations"]} == {station_ids[0]}
    assert two_stations.known_series == original_definitions
    assert two_stations.inventories == original_snapshots
    restored = rr.from_bundle(rr.to_bundle(selected))
    assert restored.known_series == selected.known_series
    assert restored.inventories == selected.inventories


def test_prefetch_coordinate_pruning_keeps_every_member_of_retained_broader_snapshot() -> None:
    from dataclasses import replace

    from rivretrieve._internal.source_series import InventoryCompleteness, InventorySnapshot

    broad = rr.find(provider="ch_foen", quantity="discharge")
    stations = rr.series(broad)["station_id"].unique().sort().to_list()[:2]
    two = rr.pick(broad, station=stations)
    # Authored wider snapshot proves reference closure, not Swiss source completeness.
    snapshot = InventorySnapshot(
        snapshot_id="contract-two-station-snapshot",
        scope=two.scope,
        members=tuple(item.series_id for item in two.known_series),
        completeness=InventoryCompleteness.INCOMPLETE,
        access="authored-coordinate-closure",
        origin="catalogue",
        evidence=("authored-coordinate-closure",),
        reason="Broader acquired scope retained unchanged for this contract test",
    )
    coupled = replace(two, inventories=(snapshot,))
    narrowed = rr.pick(coupled, station=stations[0])
    assert narrowed.inventories == (snapshot,)
    assert set(snapshot.members).issubset({item.series_id for item in narrowed.known_series})
    assert {item.station_id for item in narrowed.known_series} == set(stations)
    assert set(rr.series(narrowed)["station_id"].to_list()) == {stations[0]}
    restored = rr.from_bundle(rr.to_bundle(narrowed))
    assert restored.known_series == narrowed.known_series
    assert restored.inventories == narrowed.inventories


def test_source_series_inspection_bounds_python_record_batches(monkeypatch) -> None:
    selected = rr.find(provider="ch_foen")
    expected_rows = sum(len(item.facts) for item in selected.known_series if selected.scope.matches(item))
    assert expected_rows > 512
    original = pl.DataFrame.__init__
    sizes = []

    def counted_constructor(self, data=None, *args, **kwargs):
        if isinstance(data, list) and data and isinstance(data[0], dict) and "series_id" in data[0]:
            sizes.append(len(data))
            assert len(data) <= 512, "Inspection accumulated an unbounded Python record batch"
        return original(self, data, *args, **kwargs)

    monkeypatch.setattr(pl.DataFrame, "__init__", counted_constructor)
    inspected = rr.series(selected)
    assert inspected.height == expected_rows
    assert sum(sizes) == expected_rows
    assert len(sizes) > 1


def test_inspection_orders_descriptors_without_sorting_a_wide_materialized_frame(monkeypatch) -> None:
    selected = rr.find(provider="ch_foen")
    original = pl.DataFrame.sort

    def checked_sort(self, *args, **kwargs):
        assert not (self.height > 512 and "series_id" in self.columns), (
            "Inspection sorted a fully materialized wide frame"
        )
        return original(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(pl.DataFrame, "sort", checked_sort)
        inspected = rr.series(selected)
    keys = ["provider_id", "station_id", "product_id", "series_id", "facts_id"]
    pl_testing.assert_frame_equal(inspected, inspected.sort(keys))

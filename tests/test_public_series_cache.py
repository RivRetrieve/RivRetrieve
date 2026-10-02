"""Public recorded source-series retrieval and scoped cache reuse."""

import json
from datetime import datetime
from pathlib import Path

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from tests.usgs_modern_recordings import ModernReplay, body, manifest

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

RECORDING = "daily-07374000-discharge-mean"
CURRENT = "0df18b246e8f48ec8e6547a92070e94a"
ENDED = "4d186669708e4dc18f84d271efb953a1"


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_recorded_singleton_identity_units_export_and_native_cache(monkeypatch, tmp_path, retained_evidence_root: Path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    content = body(RECORDING, evidence_root=retained_evidence_root)
    replay = ModernReplay(RECORDING, evidence_root=retained_evidence_root)
    calls = []

    class Counting:
        def send(self, request):
            calls.append(request)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", lambda: Counting())
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    restored_selection = rr.from_bundle(rr.to_bundle(selection))
    assert restored_selection.scope == selection.scope
    assert restored_selection.known_series == selection.known_series
    assert restored_selection.inventories == selection.inventories
    pt.assert_frame_equal(rr.series(restored_selection), rr.series(selection))
    result = rr.fetch(
        restored_selection, start="2024-01-01", end="2024-01-07", receipts=True, cache="reuse", on_issue="raise"
    )
    expected_native = sorted(
        float(f["properties"]["value"])
        for f in json.loads(content)["features"]
        if "2024-01-01" <= f["properties"]["time"] <= "2024-01-07"
    )
    assert len(calls) == 1
    assert set(result.data["unit"]) == {"m3/s"}
    assert set(result.data["source_unit"]) == {"ft^3/s"}
    pt.assert_frame_equal(
        result.data.select("value").sort("value"),
        pl.DataFrame({"value": [v * 0.028316846592 for v in expected_native]}),
    )
    assert result.receipts.entries[0].content == content
    assert all(
        item.identity.published_id is not None and item.identity.namespace == "USGS.WaterData.time_series_id"
        for item in result.source_series
    )
    reused = rr.fetch(selection, start="2024-01-01", end="2024-01-07", receipts=True, cache="reuse", on_issue="raise")
    assert len(calls) == 1
    pt.assert_frame_equal(result.data, reused.data)
    assert reused.provenance.served_intervals
    assert reused.outcomes
    native = pl.read_parquet(next(rr.cache_status("usgs_nwis").store.rglob("*.parquet")))
    pt.assert_frame_equal(native.select("value").sort("value"), pl.DataFrame({"value": expected_native}))
    assert set(native["source_unit"]) == {"ft^3/s"}
    bundle = tmp_path / "result.rrbundle"
    bundle.write_bytes(rr.to_bundle(result))
    restored = rr.from_bundle(bundle.read_bytes())
    pt.assert_frame_equal(restored.data, result.data)
    assert restored.source_series == result.source_series
    assert restored.inventories == result.inventories
    assert restored.outcomes == result.outcomes
    assert restored.receipts.entries[0].content == content
    standalone = tmp_path / "observations.parquet"
    result.data.write_parquet(standalone)
    pt.assert_frame_equal(pl.read_parquet(standalone), result.data)


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_authored_unknown_explicit_series_remains_unresolved_not_successful_empty(
    monkeypatch, retained_evidence_root: Path
):
    """Authored empty response for an unknown ID; not a recorded publisher availability claim."""
    from rivretrieve._internal.transport import TransportResponse

    calls = []

    class AuthoredEmpty:
        def send(self, request):
            calls.append(request)
            assert request.params["time_series_id"] == "authored-unknown-series"
            return TransportResponse(
                b'{"type":"FeatureCollection","features":[],"links":[]}',
                200,
                datetime.fromisoformat(manifest(retained_evidence_root)[RECORDING]["acquired_utc"]),
                "application/json",
                request.url,
                request.params,
            )

    monkeypatch.setattr(discovery, "HttpClient", AuthoredEmpty)
    selection = rr.pick(
        rr.find(provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"),
        variant="authored-unknown-series",
        on_issue="ignore",
    )
    result = rr.fetch(selection, start="2024-01-01", end="2024-01-07", on_issue="ignore")
    assert len(calls) == 1
    assert result.data.is_empty()
    assert any(item.status.value == "unresolved" for item in result.outcomes)
    assert not any(item.status.value in ("success", "empty") for item in result.outcomes)
    assert any(item.code == "source.inventory_unresolved" for item in result.issues)


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_narrowed_public_request_does_not_persist_unrelated_catalogue_claims(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    import rivretrieve._internal.driver as driver

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "HttpClient", lambda: ModernReplay(RECORDING, evidence_root=retained_evidence_root))
    selection = rr.pick(
        rr.find(
            provider="usgs_nwis",
            station=["07374000", "02196000"],
            quantity="discharge",
            frequency="daily",
            statistic="mean",
        ),
        station="07374000",
    )
    actual = driver.accumulate
    inspected = []

    def scoped(store, provider, update):
        inspected.append(update)
        assert all(
            not inventory.scope.station_ids or inventory.scope.station_ids == ("07374000",)
            for inventory in update.inventories
        )
        return actual(store, provider, update)

    monkeypatch.setattr(driver, "accumulate", scoped)
    result = rr.fetch(selection, start="2024-01-01", end="2024-01-07", cache="reuse", on_issue="raise")
    assert result.data.height == 7
    assert inspected


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_known_explicit_series_across_access_routes_reuse_independently(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    recordings = (RECORDING, "daily-07374000-stage-mean")
    monkeypatch.setattr(
        discovery, "HttpClient", lambda: ModernReplay(*recordings, evidence_root=retained_evidence_root)
    )
    selection = rr.find(provider="usgs_nwis", station="07374000", frequency="daily", statistic="mean")
    broad = rr.fetch(selection, start="2024-01-01", end="2024-01-07", cache="refresh", on_issue="raise")
    assert broad.data["series_id"].n_unique() == 2
    explicit = rr.pick(selection, series_id=tuple(broad.data["series_id"].unique()), on_issue="ignore")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    reused = rr.fetch(explicit, start="2024-01-01", end="2024-01-07", cache="reuse", on_issue="raise")
    pt.assert_frame_equal(reused.data, broad.data)


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_usgs_subset_cache_cannot_satisfy_all_and_refresh_preserves_peer(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    from rivretrieve._internal.transport import TransportFailure, TransportFailureReason

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    recordings = tuple(f"daily-02196000-2000-{name}" for name in ("all", "current", "ended"))
    replay = ModernReplay(*recordings, evidence_root=retained_evidence_root)
    calls = []

    class Counting:
        def send(self, request):
            calls.append(request)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", Counting)
    selection = rr.find(
        provider="usgs_nwis", station="02196000", quantity="discharge", frequency="daily", statistic="mean"
    )
    assert {s.variant for s in selection.series} == {CURRENT, ENDED}
    explicit = rr.pick(selection, variant=CURRENT)
    narrow = rr.fetch(explicit, start="2000-01-01", end="2000-01-07", cache="reuse", on_issue="raise")
    assert narrow.data.height == 7
    broad = rr.fetch(selection, start="2000-01-01", end="2000-01-07", cache="reuse", on_issue="raise")
    assert len(calls) == 2
    assert "time_series_id" not in calls[-1].params
    assert broad.data.height == 14
    assert broad.data["series_id"].n_unique() == 2
    refreshed = rr.fetch(explicit, start="2000-01-01", end="2000-01-07", cache="refresh", on_issue="raise")
    assert len(calls) == 3
    pt.assert_frame_equal(refreshed.data, narrow.data)

    class Failed:
        def send(self, request):
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)

    monkeypatch.setattr(discovery, "HttpClient", Failed)
    failed = rr.fetch(explicit, start="2000-01-01", end="2000-01-07", cache="refresh", on_issue="ignore")
    assert failed.issues
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    ended = rr.fetch(
        rr.pick(selection, variant=ENDED), start="2000-01-01", end="2000-01-07", cache="reuse", on_issue="raise"
    )
    pt.assert_frame_equal(ended.data, rr.pick(broad, variant=ENDED).data)
    restored = rr.fetch(explicit, start="2000-01-01", end="2000-01-07", cache="reuse", on_issue="ignore")
    pt.assert_frame_equal(restored.data, narrow.data)


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_recorded_ended_series_successful_empty_is_reusable(monkeypatch, tmp_path, retained_evidence_root: Path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    name = "daily-02196000-ended-empty"
    content = body(name, evidence_root=retained_evidence_root)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ModernReplay(name, evidence_root=retained_evidence_root))
    selection = rr.pick(
        rr.find(provider="usgs_nwis", station="02196000", quantity="discharge", frequency="daily", statistic="mean"),
        variant=ENDED,
    )
    result = rr.fetch(selection, start="2024-01-01", end="2024-01-07", cache="refresh", receipts=True, on_issue="raise")
    assert result.data.is_empty()
    assert {outcome.status.value for outcome in result.outcomes} == {"empty"}
    assert result.receipts.entries[0].content == content
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    reused = rr.fetch(selection, start="2024-01-01", end="2024-01-07", cache="reuse", on_issue="raise")
    assert reused.data.is_empty()
    assert {outcome.status.value for outcome in reused.outcomes} == {"empty"}
    assert reused.provenance.served_intervals


@pytest.mark.recorded(
    "tests/test_data/no_nve_109.42.0_1001_1440_version-1_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-3_engine_2024-01-02.recording.json",
)
def test_nve_cached_explicit_subset_does_not_freeze_later_all_known_versions(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    data = retained_evidence_root / "tests" / "test_data"
    recordings = tuple(
        read_recording(data / f"no_nve_109.42.0_1001_1440_version-{version}_engine_2024-01-02.recording.json")
        for version in (1, 2, 3)
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    replay = ReplayTransport(recordings)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(
        provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"
    )
    explicit = rr.pick(selection, variant="2")
    narrow = rr.fetch(explicit, start="2024-01-02", end="2024-01-02", cache="reuse", on_issue="ignore")
    assert narrow.data["series_id"].n_unique() == 1
    broad = rr.fetch(selection, start="2024-01-02", end="2024-01-02", cache="reuse", on_issue="ignore")
    assert broad.data["series_id"].n_unique() == 3
    assert {item.variant for item in broad.source_series if item.series_id in broad.data["series_id"]} == {
        "1",
        "2",
        "3",
    }


@pytest.mark.recorded(
    "tests/test_data/no_nve_109.42.0_1001_1440_version-1_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-3_engine_2024-01-02.recording.json",
)
@pytest.mark.parametrize("variants", [("2",), ("1", "2", "3")])
def test_nve_explicit_versions_reuse_independent_acquired_inventories(
    monkeypatch, tmp_path, variants, retained_evidence_root: Path
):
    data = retained_evidence_root / "tests" / "test_data"
    recordings = tuple(
        read_recording(data / f"no_nve_109.42.0_1001_1440_version-{version}_engine_2024-01-02.recording.json")
        for version in (1, 2, 3)
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    # Authored current-metadata failure keeps the acquired all-series inventory incomplete.
    # Exact observation bytes still establish each independently reusable version.
    from rivretrieve._internal.transport import TransportFailure, TransportFailureReason

    replay = ReplayTransport(recordings)

    class FailedMetadata:
        def send(self, request):
            if request.url.endswith("/Series"):
                raise TransportFailure(request, TransportFailureReason.RETRY_EXHAUSTED, 3, status_code=503)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", FailedMetadata)
    selection = rr.find(
        provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"
    )
    initial = rr.fetch(selection, start="2024-01-02", end="2024-01-02", cache="refresh", on_issue="ignore")
    explicit = rr.pick(selection, variant=variants)
    attempted = []

    class NoNetwork:
        def send(self, request):
            attempted.append(request)
            raise AssertionError("Explicit covered versions must not make new source calls")

    monkeypatch.setattr(discovery, "HttpClient", lambda: NoNetwork())
    reused = rr.fetch(explicit, start="2024-01-02", end="2024-01-02", cache="reuse", on_issue="raise")
    assert attempted == []
    pt.assert_frame_equal(reused.data, rr.pick(initial, variant=variants, on_issue="ignore").data)
    assert {
        int(call["request_parameters"]["VersionNumber"])
        for call in reused.provenance.calls_made
        if call["url"].endswith("/Observations")
    } == {int(v) for v in variants}

    assert not any(issue.code == "source.inventory_unresolved" for issue in reused.issues)
    assert all(item.completeness.value == "incomplete" for item in reused.inventories if item.origin != "catalogue")
    persisted = [json.loads(path.read_text()) for path in (tmp_path / "cache").rglob("*.json")]
    assert any("source.inventory_unresolved" in json.dumps(value) for value in persisted)
    from rivretrieve._internal.issues import IssuePolicyError

    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(recordings))
    with pytest.raises(IssuePolicyError) as caught:
        rr.fetch(selection, start="2024-01-02", end="2024-01-02", cache="reuse", on_issue="raise")
    assert any(issue.code == "source.inventory_unresolved" for issue in caught.value.issues)
    unresolved = rr.pick(selection, series_id="unresolved-source-identity", on_issue="ignore")
    monkeypatch.setattr(discovery, "HttpClient", lambda: NoNetwork())
    with pytest.raises(IssuePolicyError) as unresolved_error:
        rr.fetch(unresolved, start="2024-01-02", end="2024-01-02", cache="reuse", on_issue="raise")
    assert any(issue.code == "source.inventory_unresolved" for issue in unresolved_error.value.issues)
    assert attempted == []


@pytest.mark.recorded("tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json")
def test_cached_success_does_not_inherit_failure_for_an_unrequested_window(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    from rivretrieve._internal.transport import TransportFailure, TransportFailureReason

    data = retained_evidence_root / "tests" / "test_data"
    recording = read_recording(data / "no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.pick(
        rr.find(provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"),
        variant="2",
    )
    healthy = rr.fetch(selection, start="2024-01-02", end="2024-01-02", cache="reuse", on_issue="raise")

    class Failed:
        def send(self, request):
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)

    monkeypatch.setattr(discovery, "HttpClient", lambda: Failed())
    failed = rr.fetch(selection, start="2024-01-05", end="2024-01-05", cache="refresh", on_issue="ignore")
    assert failed.issues
    restored = rr.fetch(selection, start="2024-01-02", end="2024-01-02", cache="reuse", on_issue="raise")
    pt.assert_frame_equal(restored.data, healthy.data)
    assert restored.issues == healthy.issues
    assert restored.provenance.calls_made == healthy.provenance.calls_made


@pytest.mark.recorded("tests/recordings/br_ana")
def test_public_authenticated_source_provenance_excludes_request_headers(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    from tests.test_br_ana_public_daily import _authenticated_replay

    monkeypatch.chdir(tmp_path)
    _authenticated_replay(retained_evidence_root, monkeypatch, "stage_daily_mean_consistido")
    selection = rr.pick(
        rr.find(provider="br_ana", station="15400000", quantity="stage", frequency="daily", statistic="mean"),
        variant="consistido",
    )
    result = rr.fetch(selection, start="2020-01-10", end="2020-01-20", receipts=True, on_issue="ignore")
    assert result.provenance.calls_made
    assert all(
        not {"headers", "request_headers", "ordinary_headers"}.intersection(call)
        for call in result.provenance.calls_made
    )


@pytest.mark.recorded("tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json")
def test_mixed_nve_finite_variant_cannot_silently_drop_unknown_selector(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    recording = read_recording(
        retained_evidence_root
        / "tests"
        / "test_data"
        / "no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.pick(
        rr.find(provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"),
        variant=("2", "unresolved-selector"),
        on_issue="ignore",
    )
    result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", on_issue="ignore")
    assert result.data.height == 1
    assert any(
        outcome.requested_selector is not None and outcome.requested_selector.value == "unresolved-selector"
        for outcome in result.outcomes
    )

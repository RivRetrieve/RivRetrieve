"""Public recorded source-series retrieval and scoped cache reuse."""

import json
from pathlib import Path

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.recordings import ReplayTransport, read_recording

RECORDING = Path("tests/test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json")


def test_recorded_singleton_identity_units_export_and_native_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    recording = read_recording(RECORDING)
    replay = ReplayTransport((recording,))
    calls = []

    class Counting:
        def send(self, request):
            calls.append(request)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", lambda: Counting())
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", receipts=True, cache="reuse", on_issue="ignore")
    assert len(calls) == 1
    assert result.data["unit"].to_list() == ["m3/s"]
    assert result.data["source_unit"].to_list() == ["ft3/s"]
    assert result.data["value"].item() == pytest.approx(373000 * 0.028316846592)
    assert result.receipts.entries[0].content == recording.content
    assert all(
        item.identity.published_id is not None
        for item in result.source_series
        if any(outcome.series_id == item.series_id for outcome in result.outcomes)
    )
    reused = rr.fetch(selection, start="2023-01-01", end="2023-01-01", receipts=True, cache="reuse", on_issue="ignore")
    assert len(calls) == 1
    pt.assert_frame_equal(result.data, reused.data)
    assert reused.provenance.served_intervals
    assert reused.outcomes
    native = pl.read_parquet(next(rr.cache_status("usgs_nwis").store.rglob("*.parquet")))
    assert native["value"].to_list() == [373000.0]
    assert native["source_unit"].to_list() == ["ft3/s"]
    bundle = tmp_path / "result.rrbundle"
    bundle.write_bytes(rr.to_bundle(result))
    restored = rr.from_bundle(bundle.read_bytes())
    pt.assert_frame_equal(restored.data, result.data)
    assert restored.source_series == result.source_series
    assert restored.inventories == result.inventories
    assert restored.outcomes == result.outcomes
    assert restored.receipts.entries[0].content == recording.content
    standalone = tmp_path / "observations.parquet"
    result.data.write_parquet(standalone)
    pt.assert_frame_equal(pl.read_parquet(standalone), result.data)


def test_unavailable_explicit_method_is_no_match_not_successful_empty(monkeypatch):
    recording = read_recording(RECORDING)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.pick(
        rr.find(provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"),
        variant="99999999",
    )
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", on_issue="ignore")
    assert result.data.is_empty()
    assert any(item.status.value == "no_match" for item in result.outcomes)
    assert not any(item.status.value in ("success", "empty") for item in result.outcomes)
    assert any(item.code == "source.no_match" for item in result.issues)


def test_narrowed_public_request_does_not_persist_unrelated_catalogue_claims(monkeypatch, tmp_path):
    import rivretrieve._internal.driver as driver

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    recording = read_recording(RECORDING)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    # Two actual catalogue stations retain independent source inventory evidence.
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
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="reuse", on_issue="ignore")
    assert result.data.height == 1
    assert inspected


def test_known_explicit_series_across_access_routes_reuse_independently(monkeypatch, tmp_path):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    recordings = (
        read_recording(RECORDING),
        read_recording(Path("tests/test_data/usgs_nwis_07374000_iv_00060_2023-01-01.recording.json")),
    )
    replay = ReplayTransport(recordings)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(provider="usgs_nwis", station="07374000", quantity="discharge")
    broad = rr.fetch(selection, start="2023-01-01T00:00", end="2023-01-01T00:15", cache="refresh", on_issue="ignore")
    assert broad.data["series_id"].n_unique() == 2
    explicit = rr.pick(selection, series_id=tuple(broad.data["series_id"].unique()), on_issue="ignore")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    reused = rr.fetch(explicit, start="2023-01-01T00:00", end="2023-01-01T00:15", cache="reuse", on_issue="raise")
    pt.assert_frame_equal(reused.data, broad.data)


def test_nve_cached_explicit_subset_does_not_freeze_later_all_known_versions(monkeypatch, tmp_path):
    data = Path(__file__).parent / "test_data"
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


@pytest.mark.parametrize("variants", [("2",), ("1", "2", "3")])
def test_nve_explicit_versions_reuse_independent_acquired_inventories(monkeypatch, tmp_path, variants):
    data = Path(__file__).parent / "test_data"
    recordings = tuple(
        read_recording(data / f"no_nve_109.42.0_1001_1440_version-{version}_engine_2024-01-02.recording.json")
        for version in (1, 2, 3)
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(recordings))
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
    assert {int(call["request_parameters"]["VersionNumber"]) for call in reused.provenance.calls_made} == {
        int(v) for v in variants
    }

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


def test_cached_success_does_not_inherit_failure_for_an_unrequested_window(monkeypatch, tmp_path):
    from rivretrieve._internal.transport import TransportFailure, TransportFailureReason

    data = Path(__file__).parent / "test_data"
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


def test_public_authenticated_source_provenance_excludes_request_headers(monkeypatch, tmp_path):
    from tests.test_br_ana_public_daily import _authenticated_replay

    monkeypatch.chdir(tmp_path)
    _authenticated_replay(monkeypatch, "stage_daily_mean_consistido")
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

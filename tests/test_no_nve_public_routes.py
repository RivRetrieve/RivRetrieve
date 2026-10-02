"""Exact explicit-version HydAPI public routes and native cache receipts."""

import json
from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.observations import ReceiptAuthorship
from rivretrieve._internal.recordings import ReplayTransport, read_recording

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_DATA = Path("tests/test_data")


@pytest.mark.parametrize("parameter,quantity", [(1000, "stage"), (1001, "discharge"), (1003, "temperature")])
@pytest.mark.parametrize(
    "resolution,frequency,statistic",
    [(0, None, "instantaneous"), (60, "hourly", "mean"), (1440, "daily", "mean")],
)
@pytest.mark.recorded(
    "tests/test_data/no_nve_observations_1.200.0_1000_0_v1_engine_2025-07-10.recording.json",
    "tests/test_data/no_nve_observations_1.200.0_1000_1440_v1_engine_2025-07-10.recording.json",
    "tests/test_data/no_nve_observations_1.200.0_1000_60_v1_engine_2025-07-10.recording.json",
    "tests/test_data/no_nve_observations_1.200.0_1001_0_v1_engine_2025-07-10.recording.json",
    "tests/test_data/no_nve_observations_1.200.0_1001_1440_v1_engine_2025-07-10.recording.json",
    "tests/test_data/no_nve_observations_1.200.0_1001_60_v1_engine_2025-07-10.recording.json",
    "tests/test_data/no_nve_observations_1.200.0_1003_0_v1_engine_2025-07-10.recording.json",
    "tests/test_data/no_nve_observations_1.200.0_1003_1440_v1_engine_2025-07-10.recording.json",
    "tests/test_data/no_nve_observations_1.200.0_1003_60_v1_engine_2025-07-10.recording.json",
    "tests/test_data/no_nve_series_1.200.0_1000.recording.json",
    "tests/test_data/no_nve_series_1.200.0_1001.recording.json",
    "tests/test_data/no_nve_series_1.200.0_1003.recording.json",
)
def test_every_enrolled_route_replays_current_inventory_explicit_version_and_cache(
    retained_evidence_root, monkeypatch, tmp_path, parameter, quantity, resolution, frequency, statistic
):
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    metadata = read_recording(retained_evidence_root / _DATA / f"no_nve_series_1.200.0_{parameter}.recording.json")
    observation = read_recording(
        retained_evidence_root
        / _DATA
        / f"no_nve_observations_1.200.0_{parameter}_{resolution}_v1_engine_2025-07-10.recording.json"
    )
    requests = []
    replay = ReplayTransport((metadata, observation))

    class Observed:
        def send(self, request):
            requests.append(request)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", Observed)
    selection = rr.find(
        provider="no_nve", station="1.200.0", quantity=quantity, frequency=frequency, statistic=statistic
    )

    def fetch(mode):
        return rr.fetch(selection, start="2025-07-10", end="2025-07-10", cache=mode, receipts=True, on_issue="raise")

    result = fetch("bypass")
    raw = json.loads(observation.content)["data"][0]
    assert all(f.frequency.value == frequency for item in result.source_series for f in item.facts)
    expected = pl.DataFrame(
        {"value": [item["value"] for item in raw["observations"] if item["time"].startswith("2025-07-10")]}
    )
    pl_testing.assert_frame_equal(result.data.select("value"), expected)
    assert result.data.height == (1 if resolution == 1440 else 24)
    assert result.data["time_zone"].unique().to_list() == ["+00:00"]
    assert result.data["source_unit"].unique().to_list() == [raw["unit"]]
    assert result.data["unit"].unique().to_list() == [{1000: "m", 1001: "m3/s", 1003: "degC"}[parameter]]
    assert result.data["quantity"].unique().to_list() == [quantity]
    assert {item.identity.published_id for item in result.source_series} == {"1"}
    assert all(receipt.content == observation.content for receipt in result.receipts.entries)
    assert len(requests) == 2
    metadata_call = next(call for call in result.provenance.calls_made if call["url"].endswith("/Series"))
    assert metadata_call["station_products"] == (("1.200.0", selection.series[0].product_id),)
    refresh = fetch("refresh")
    assert len(requests) == 4
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    reuse = fetch("reuse")
    pl_testing.assert_frame_equal(reuse.data, refresh.data)
    assert reuse.provenance.served_intervals
    assert all(receipt.authorship is ReceiptAuthorship.STORE_EXCERPT for receipt in reuse.receipts.entries)
    assert all(
        dict(call["request_parameters"])["VersionNumber"] == 1
        for call in result.provenance.calls_made
        if call["url"].endswith("/Observations")
    )
    assert "protocol-only-nve-key" not in repr(result)


@pytest.mark.recorded(
    "tests/test_data/no_nve_observations_1.46.0_1000_1440_v1_engine_2024-10-01.recording.json",
    "tests/test_data/no_nve_observations_1.46.0_1000_1440_v2_engine_2024-10-01.recording.json",
    "tests/test_data/no_nve_series_1.46.0_1000.recording.json",
)
def test_current_version_specific_method_obeys_original_physical_predicate(
    retained_evidence_root, monkeypatch, tmp_path
):
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    metadata = read_recording(retained_evidence_root / _DATA / "no_nve_series_1.46.0_1000.recording.json")
    observations = tuple(
        read_recording(
            retained_evidence_root
            / _DATA
            / f"no_nve_observations_1.46.0_1000_1440_v{v}_engine_2024-10-01.recording.json"
        )
        for v in (1, 2)
    )
    replay = ReplayTransport((metadata, *observations))
    requests = []

    class Observed:
        def send(self, request):
            requests.append(request)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", Observed)
    selection = rr.find(provider="no_nve", station="1.46.0", quantity="stage", frequency="daily", statistic="mean")
    result = rr.fetch(selection, start="2024-10-01", end="2024-10-01", on_issue="raise")
    assert {
        dict(call["request_parameters"])["VersionNumber"]
        for call in result.provenance.calls_made
        if call["url"].endswith("/Observations")
    } == {1}
    assert result.data.height == 1
    broad = rr.find(provider="no_nve", station="1.46.0", quantity="stage", frequency="daily")
    both = rr.fetch(broad, start="2024-10-01", end="2024-10-01", on_issue="raise")
    assert {item.identity.published_id for item in both.source_series} == {"1", "2"}
    assert {facts.statistic.value for item in both.source_series for facts in item.facts} == {"mean", "instantaneous"}


@pytest.mark.recorded(
    "tests/test_data/no_nve_109.42.0_1001_1440_version-1_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-3_engine_2024-01-02.recording.json",
)
def test_failed_current_inventory_retains_known_results_and_cannot_satisfy_all_cache(
    retained_evidence_root, monkeypatch, tmp_path
):
    from rivretrieve._internal.transport import TransportFailure, TransportFailureReason

    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    recordings = tuple(
        read_recording(
            retained_evidence_root / _DATA / f"no_nve_109.42.0_1001_1440_version-{v}_engine_2024-01-02.recording.json"
        )
        for v in (1, 2, 3)
    )
    requests = []
    replay = ReplayTransport(recordings)

    class FailedMetadata:
        def send(self, request):
            requests.append(request)
            if request.url.endswith("/Series"):
                raise TransportFailure(request, TransportFailureReason.RETRY_EXHAUSTED, 3, status_code=503)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", FailedMetadata)
    selected = rr.find(provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean")

    def fetch():
        return rr.fetch(selected, start="2024-01-02", end="2024-01-02", cache="reuse", receipts=True, on_issue="ignore")

    first = fetch()
    assert first.data.height == 3
    assert first.data["value"].null_count() == 1
    assert any(issue.code == "source.inventory_unresolved" and "503" in issue.message for issue in first.issues)
    assert any(outcome.status == "unresolved" for outcome in first.outcomes)
    assert not any(inv.completeness == "complete" for inv in first.inventories)
    again = fetch()
    assert len(requests) == 8
    pl_testing.assert_frame_equal(first.data, again.data)
    restored = rr.from_bundle(rr.to_bundle(again))
    assert restored.issues == again.issues
    assert restored.inventories == again.inventories
    assert restored.outcomes == again.outcomes


@pytest.mark.recorded(
    "tests/test_data/no_nve_109.42.0_1001_1440_version-1_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-3_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_series.recording.json",
)
def test_subset_cannot_satisfy_all_current_versions_and_refresh_keeps_siblings(
    retained_evidence_root, monkeypatch, tmp_path
):
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    metadata = read_recording(retained_evidence_root / _DATA / "no_nve_109.42.0_1001_series.recording.json")
    observations = tuple(
        read_recording(
            retained_evidence_root / _DATA / f"no_nve_109.42.0_1001_1440_version-{v}_engine_2024-01-02.recording.json"
        )
        for v in (1, 2, 3)
    )
    requests = []
    replay = ReplayTransport((metadata, *observations))

    class Observed:
        def send(self, request):
            requests.append(request)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", Observed)
    all_series = rr.find(
        provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"
    )
    two = rr.pick(all_series, variant="2")

    def fetch(selection, mode):
        return rr.fetch(selection, start="2024-01-02", end="2024-01-02", cache=mode, receipts=True, on_issue="raise")

    subset = fetch(two, "reuse")
    assert subset.data.height == 1 and len(requests) == 1
    complete = fetch(all_series, "reuse")
    assert complete.data.height == 3 and len(requests) == 5
    fetch(two, "refresh")
    assert len(requests) == 6
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    third = fetch(rr.pick(all_series, variant="3"), "reuse")
    pl_testing.assert_frame_equal(third.data, rr.pick(complete, variant="3").data)
    assert all(entry.authorship is ReceiptAuthorship.STORE_EXCERPT for entry in third.receipts.entries)
    # A later independently refreshed subset cannot renew the older ALL inventory proof.
    monkeypatch.setattr(discovery, "HttpClient", Observed)
    reacquired = fetch(all_series, "reuse")
    assert reacquired.data.height == 3
    assert len(requests) == 10


@pytest.mark.recorded(
    "tests/test_data/no_nve_109.42.0_1001_1440_version-1_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_1440_version-3_engine_2024-01-02.recording.json",
    "tests/test_data/no_nve_109.42.0_1001_series.recording.json",
)
def test_failed_version_refresh_retains_old_success_without_fresh_all_coverage(
    retained_evidence_root, monkeypatch, tmp_path
):
    from dataclasses import replace
    from datetime import timedelta

    from rivretrieve._internal.transport import TransportFailure, TransportFailureReason

    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    metadata = read_recording(retained_evidence_root / _DATA / "no_nve_109.42.0_1001_series.recording.json")
    observations = tuple(
        read_recording(
            retained_evidence_root / _DATA / f"no_nve_109.42.0_1001_1440_version-{v}_engine_2024-01-02.recording.json"
        )
        for v in (1, 2, 3)
    )
    replay = ReplayTransport((metadata, *observations))
    requests = []
    fail = False

    class Observed:
        def send(self, request):
            requests.append(request)
            if fail and request.url.endswith("/Observations") and request.params["VersionNumber"] == 3:
                raise TransportFailure(request, TransportFailureReason.RETRY_EXHAUSTED, 3, status_code=503)
            response = replay.send(request)
            return replace(response, retrieved_at=response.retrieved_at + timedelta(days=1)) if fail else response

    monkeypatch.setattr(discovery, "HttpClient", Observed)
    selection = rr.find(
        provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"
    )

    def fetch(mode):
        return rr.fetch(selection, start="2024-01-02", end="2024-01-02", cache=mode, on_issue="ignore")

    first = fetch("refresh")
    assert len(requests) == 4 and first.data.height == 3
    third = next(item for item in first.source_series if item.variant == "3")
    fail = True
    failed = fetch("refresh")
    assert len(requests) == 8
    # Refresh retains the failed version at its original vintage alongside fresh siblings.
    pl_testing.assert_frame_equal(failed.data, first.data)
    assert {item.series_id for item in failed.provenance.served_intervals} == {third.series_id}
    assert all(item.retrieved_at == observations[2].retrieved_at for item in failed.provenance.served_intervals)
    assert {item.series_id: item for item in failed.source_series} == {
        item.series_id: item for item in first.source_series
    }
    held_calls = [
        call
        for call in failed.provenance.calls_made
        if call.get("request_parameters", {}).get("VersionNumber") == 3
        and call.get("retrieved_at") == observations[2].retrieved_at
    ]
    assert held_calls
    for variant in ("1", "2"):
        sibling = next(item for item in first.source_series if item.variant == variant)
        assert any(
            outcome.series_id == sibling.series_id
            and outcome.status == "success"
            and outcome.retrieved_at == observations[int(variant) - 1].retrieved_at + timedelta(days=1)
            for outcome in failed.outcomes
        )
    assert any(outcome.series_id == third.series_id and outcome.status == "failed" for outcome in failed.outcomes)
    retained = rr.fetch(
        rr.pick(selection, variant="3"), start="2024-01-02", end="2024-01-02", cache="reuse", on_issue="ignore"
    )
    pl_testing.assert_frame_equal(retained.data, rr.pick(first, variant="3").data)
    assert len(requests) == 8
    assert retained.provenance.served_intervals
    prior_coverage = [item for item in retained.provenance.served_intervals if item.series_id == third.series_id]
    assert prior_coverage
    assert all(item.retrieved_at == observations[2].retrieved_at for item in prior_coverage)
    held_outcomes = [
        outcome
        for outcome in failed.outcomes
        if outcome.series_id == third.series_id and outcome.status in ("success", "empty")
    ]
    assert held_outcomes
    assert all(outcome.retrieved_at == observations[2].retrieved_at for outcome in held_outcomes)
    settled = [item for item in failed.inventories if "reconciled" in item.access]
    assert settled[-1].completeness == "incomplete"
    fetch("reuse")
    assert len(requests) == 12

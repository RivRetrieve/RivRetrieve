"""Durable public exports retain response-owned identity and exact receipt bytes."""

import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from tests.usgs_modern_recordings import ModernReplay, body, coordinates, manifest

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_RECORDING = "daily-07374000-docs-2023"
_KNOWN = "c9d823a2491f4b639656a11b35a7625d"


def _result(monkeypatch, tmp_path, retained_evidence_root: Path):
    replay = ModernReplay(_RECORDING, evidence_root=retained_evidence_root)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", receipts=True, on_issue="ignore")
    return result, body(_RECORDING, evidence_root=retained_evidence_root)


def test_recorded_result_round_trip_keeps_response_identity_facts_outcomes_and_receipts(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    result, content = _result(monkeypatch, tmp_path, retained_evidence_root=retained_evidence_root)
    assert result.data.height == 1
    assert result.source_series
    assert all(item.identity.namespace == "USGS.WaterData.time_series_id" for item in result.source_series)
    assert {item.identity.published_id for item in result.source_series} == {_KNOWN}
    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(restored.data, result.data)
    pl_testing.assert_frame_equal(rr.series(restored), rr.series(result))
    assert restored.scope == result.scope
    assert restored.source_series == result.source_series
    assert restored.outcomes == result.outcomes
    assert restored.inventories == result.inventories
    assert restored.provenance.calls_made == result.provenance.calls_made
    assert restored.receipts.entries[0].content == content


def test_post_fetch_pick_preserves_original_request_and_publisher_receipt(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    result, content = _result(monkeypatch, tmp_path, retained_evidence_root=retained_evidence_root)
    concrete = result.data["series_id"][0]
    narrowed = rr.pick(result, series_id=concrete, on_issue="ignore")
    assert narrowed.scope == result.scope
    assert narrowed.view_scope.series_ids == (concrete,)
    assert narrowed.provenance == result.provenance
    assert narrowed.receipts.entries[0].content == content
    restored = rr.from_bundle(rr.to_bundle(narrowed))
    assert restored.view_scope == narrowed.view_scope
    pl_testing.assert_frame_equal(restored.data, narrowed.data)


def test_bundle_refuses_unknown_format_before_scientific_decode(monkeypatch, tmp_path, retained_evidence_root: Path):
    result, _ = _result(monkeypatch, tmp_path, retained_evidence_root=retained_evidence_root)
    original = rr.to_bundle(result)
    output = BytesIO()
    with ZipFile(BytesIO(original)) as source, ZipFile(output, "w", compression=ZIP_DEFLATED) as destination:
        for name in source.namelist():
            content = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(content)
                manifest["version"] = 999
                content = json.dumps(manifest).encode()
            destination.writestr(name, content)
    with pytest.raises(ValueError, match="format version"):
        rr.from_bundle(output.getvalue())


def test_catalogue_known_explicit_restriction_reuses_without_stale_policy_failure(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = ModernReplay(_RECORDING, evidence_root=retained_evidence_root)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache="reuse", on_issue="raise")
    pending = rr.pick(selection, variant=_KNOWN, on_issue="raise")
    result = rr.fetch(pending, start="2023-01-01", end="2023-01-01", cache="reuse", on_issue="raise")
    assert len(replay.calls) == 1
    assert result.data.height == 1
    assert {item.identity.published_id for item in result.source_series if pending.scope.matches(item)} == {_KNOWN}
    assert not any(issue.code == "selection.unresolved_inventory" for issue in result.issues)
    assert pending.scope.variants == (_KNOWN,)


@pytest.mark.parametrize("variant", ["0df18b246e8f48ec8e6547a92070e94a", "authored-unknown"])
def test_before_fetch_restriction_bundle_retains_acquired_scoped_inventory(
    monkeypatch, tmp_path, variant, retained_evidence_root: Path
):
    """Exact selected-series response; unknown-ID empty response is an authored control."""
    from rivretrieve._internal.transport import TransportResponse

    name = "daily-02196000-2000-current"
    current = "0df18b246e8f48ec8e6547a92070e94a"
    replay = ModernReplay(name, evidence_root=retained_evidence_root)
    empty = b'{"type":"FeatureCollection","features":[],"links":[]}'

    class UnknownSelectorControl:
        def send(self, request):
            if variant == current:
                return replay.send(request)
            expected_url, expected_params = coordinates(manifest(retained_evidence_root)[name]["original_url"])
            expected_params = tuple(
                sorted((key, variant if key == "time_series_id" else value) for key, value in expected_params)
            )
            assert coordinates(request.url, request.params) == (expected_url, expected_params)
            return TransportResponse(
                empty,
                200,
                datetime.fromisoformat(manifest(retained_evidence_root)[name]["acquired_utc"]),
                "application/json",
                request.url,
                request.params,
            )

    monkeypatch.setattr(discovery, "HttpClient", UnknownSelectorControl)
    selection = rr.find(
        provider="usgs_nwis", station="02196000", quantity="discharge", frequency="daily", statistic="mean"
    )
    restricted = rr.from_bundle(rr.to_bundle(rr.pick(selection, variant=variant, on_issue="ignore")))
    result = rr.fetch(restricted, start="2000-01-01", end="2000-01-07", receipts=True, on_issue="ignore")
    assert result.data.height == (7 if variant == current else 0)
    assert result.receipts.entries[0].content == (
        body(name, evidence_root=retained_evidence_root) if variant == current else empty
    )
    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(restored.data, result.data)
    assert restored.inventories == result.inventories
    assert restored.scope == restricted.scope
    all_known_ids = {item.series_id for item in restored.source_series}
    assert all(set(inventory.members).issubset(all_known_ids) for inventory in restored.inventories)
    inspected = rr.series(restored)
    assert set(inspected["published_id"].drop_nulls().to_list()) == ({current} if variant == current else set())
    if variant != current:
        assert {item.status.value for item in restored.outcomes} == {"unresolved"}


def test_recorded_ended_empty_result_bundle_retains_inventory_definition(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    name = "daily-02196000-ended-empty"
    ended = "4d186669708e4dc18f84d271efb953a1"
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: ModernReplay(name, evidence_root=retained_evidence_root))
    selection = rr.find(
        provider="usgs_nwis", station="02196000", quantity="discharge", frequency="daily", statistic="mean"
    )
    restricted = rr.pick(selection, variant=ended, on_issue="raise")
    result = rr.fetch(restricted, start="2024-01-01", end="2024-01-07", on_issue="raise")
    assert result.data.is_empty()
    assert {item.status.value for item in result.outcomes} == {"empty"}
    restored = rr.from_bundle(rr.to_bundle(result))
    assert restored.scope == restricted.scope
    assert restored.inventories == result.inventories
    assert {item.identity.published_id for item in restored.source_series} == {ended}


def test_bundle_container_is_deterministic_without_rewriting_source_timestamps(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    result, content = _result(monkeypatch, tmp_path, retained_evidence_root=retained_evidence_root)
    monkeypatch.setattr("zipfile.time.localtime", lambda *args: (2020, 1, 2, 3, 4, 6, 3, 2, -1))
    first = rr.to_bundle(result)
    monkeypatch.setattr("zipfile.time.localtime", lambda *args: (2026, 9, 19, 12, 30, 22, 5, 262, -1))
    second = rr.to_bundle(result)
    assert first == second
    restored = rr.from_bundle(first)
    assert restored.receipts.entries[0].origin.retrieved_at == datetime.fromisoformat(
        manifest(retained_evidence_root)[_RECORDING]["acquired_utc"]
    )
    assert restored.provenance.calls_made == result.provenance.calls_made


def test_bundle_rejects_inventory_fact_membership_missing_from_its_source_definition(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    result, _ = _result(monkeypatch, tmp_path, retained_evidence_root=retained_evidence_root)
    output = BytesIO()
    with (
        ZipFile(BytesIO(rr.to_bundle(result))) as source,
        ZipFile(output, "w", compression=ZIP_DEFLATED) as destination,
    ):
        for name in source.namelist():
            content = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(content)
                inventory = next(
                    item for item in manifest["inventories"] if item["origin"] == "response" and item["members"]
                )
                inventory["member_facts"] = [[inventory["members"][0], ["not-an-acquired-fact-segment"]]]
                content = json.dumps(manifest).encode()
            destination.writestr(name, content)
    with pytest.raises(ValueError, match="(?i)inventory.*physical fact"):
        rr.from_bundle(output.getvalue())


def test_failed_explicit_identity_remains_inspectable_without_claiming_unknown_physical_facts(
    monkeypatch, tmp_path, retained_evidence_root: Path
):
    data = retained_evidence_root / "tests" / "test_data"
    recordings = tuple(
        read_recording(data / f"no_nve_109.42.0_1001_1440_version-{version}_engine_2024-01-02.recording.json")
        for version in (1, 99999)
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(recordings))
    selection = rr.pick(
        rr.find(provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily"),
        variant=("1", "99999"),
        on_issue="ignore",
    )
    result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", on_issue="ignore")
    failed_outcome = next(item for item in result.outcomes if item.status.value == "failed")
    inspected = rr.series(result)
    failed = inspected.filter(pl.col("series_id") == failed_outcome.series_id)
    assert failed.height == 1
    assert failed["quantity"].to_list() == [None]
    assert failed["published_id"].to_list() == [None]
    assert failed["outcomes"].to_list() == [["failed"]]

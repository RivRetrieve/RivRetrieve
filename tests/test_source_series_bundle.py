"""Durable public exports retain response-owned identity and exact receipt bytes."""

import json
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport, read_recording

_RECORDING = Path(__file__).parent / "test_data/usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"


def _result(monkeypatch, tmp_path):
    recording = read_recording(_RECORDING)
    replay = ReplayTransport((recording,))
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", receipts=True, on_issue="ignore")
    return result, recording


def test_recorded_result_round_trip_keeps_response_identity_facts_outcomes_and_receipts(monkeypatch, tmp_path):
    result, recording = _result(monkeypatch, tmp_path)
    assert result.data.height == 1
    assert result.source_series
    assert any(item.identity.origin == "response" for item in result.source_series)
    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(restored.data, result.data)
    pl_testing.assert_frame_equal(rr.series(restored), rr.series(result))
    assert restored.scope == result.scope
    assert restored.source_series == result.source_series
    assert restored.outcomes == result.outcomes
    assert restored.inventories == result.inventories
    assert restored.provenance.calls_made == result.provenance.calls_made
    assert restored.receipts.entries[0].content == recording.content


def test_post_fetch_pick_preserves_original_request_and_publisher_receipt(monkeypatch, tmp_path):
    result, recording = _result(monkeypatch, tmp_path)
    concrete = result.data["series_id"][0]
    narrowed = rr.pick(result, series_id=concrete, on_issue="ignore")
    assert narrowed.scope == result.scope
    assert narrowed.view_scope.series_ids == (concrete,)
    assert narrowed.provenance == result.provenance
    assert narrowed.receipts.entries[0].content == recording.content
    restored = rr.from_bundle(rr.to_bundle(narrowed))
    assert restored.view_scope == narrowed.view_scope
    pl_testing.assert_frame_equal(restored.data, narrowed.data)


def test_bundle_refuses_unknown_format_before_scientific_decode(monkeypatch, tmp_path):
    result, _ = _result(monkeypatch, tmp_path)
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


def test_response_owned_explicit_restriction_is_settled_without_stale_policy_failure(monkeypatch, tmp_path):
    recording = read_recording(_RECORDING)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    pending = rr.pick(selection, variant="61176", on_issue="ignore")
    result = rr.fetch(pending, start="2023-01-01", end="2023-01-01", on_issue="raise")
    assert result.data.height == 1
    assert {item.identity.published_id for item in result.source_series if pending.scope.matches(item)} == {"61176"}
    assert not any(issue.code == "selection.unresolved_inventory" for issue in result.issues)
    assert pending.scope.variants == ("61176",)


@pytest.mark.parametrize("variant", ["126801", "99999999"])
def test_before_fetch_restriction_bundle_retains_complete_acquired_inventory(monkeypatch, tmp_path, variant):
    from tests.test_source_series_usgs import _original_capture_public_access

    selection, content, _, _ = _original_capture_public_access(monkeypatch, tmp_path)
    restricted = rr.pick(selection, variant=variant, on_issue="ignore")
    result = rr.fetch(restricted, start="1980-01-01", end="2025-12-31", receipts=True, on_issue="ignore")
    assert result.data.height == (15386 if variant == "126801" else 0)
    assert result.receipts.entries[0].content == content
    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(restored.data, result.data)
    assert restored.inventories == result.inventories
    assert restored.scope == restricted.scope
    all_known_ids = {item.series_id for item in restored.source_series}
    assert all(set(inventory.members).issubset(all_known_ids) for inventory in restored.inventories)
    inspected = rr.series(restored)
    assert set(inspected["published_id"].drop_nulls().to_list()) == ({"126801"} if variant == "126801" else set())


def test_recorded_singleton_no_match_result_bundle_retains_inventory_definition(monkeypatch, tmp_path):
    recording = read_recording(_RECORDING)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    restricted = rr.pick(selection, variant="99999999", on_issue="ignore")
    result = rr.fetch(restricted, start="2023-01-01", end="2023-01-01", on_issue="ignore")
    assert result.data.is_empty()
    restored = rr.from_bundle(rr.to_bundle(result))
    assert restored.scope == restricted.scope
    assert restored.inventories == result.inventories
    assert {item.identity.published_id for item in restored.source_series} == {"61176"}


def test_bundle_container_is_deterministic_without_rewriting_source_timestamps(monkeypatch, tmp_path):
    result, recording = _result(monkeypatch, tmp_path)
    monkeypatch.setattr("zipfile.time.localtime", lambda *args: (2020, 1, 2, 3, 4, 6, 3, 2, -1))
    first = rr.to_bundle(result)
    monkeypatch.setattr("zipfile.time.localtime", lambda *args: (2026, 9, 19, 12, 30, 22, 5, 262, -1))
    second = rr.to_bundle(result)
    assert first == second
    restored = rr.from_bundle(first)
    assert restored.receipts.entries[0].origin.retrieved_at == recording.retrieved_at
    assert restored.provenance.calls_made == result.provenance.calls_made


def test_bundle_rejects_inventory_fact_membership_missing_from_its_source_definition(monkeypatch, tmp_path):
    result, _ = _result(monkeypatch, tmp_path)
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


def test_failed_explicit_identity_remains_inspectable_without_claiming_unknown_physical_facts(monkeypatch, tmp_path):
    data = Path(__file__).parent / "test_data"
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

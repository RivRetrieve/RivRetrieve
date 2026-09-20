"""Public source-series workflow replays exact engine-planned publisher interactions."""

from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport, read_recording

_DATA = Path(__file__).parent / "test_data"


def test_public_swiss_litre_series_preserves_identity_unit_and_unknown_time(monkeypatch, tmp_path):
    recording = read_recording(_DATA / "ch_foen_2251_rest_engine_2026-09-19.recording.json")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.find(provider="ch_foen", station="2251", quantity="discharge")
    result = rr.fetch(
        selection, start="2026-09-19T00:00:00", end="2026-09-19T03:00:00", receipts=True, on_issue="ignore"
    )
    assert result.data.height == 4
    assert result.data["series_id"].n_unique() == 1
    assert result.data["source_unit"].unique().to_list() == ["l/s"]
    assert result.data["unit"].unique().to_list() == ["m3/s"]
    pl_testing.assert_frame_equal(
        result.data.select("value"), pl.DataFrame({"value": [0.00264, 0.00264, 0.00264, 0.00273]})
    )
    assert any(entry.content == recording.content for entry in result.receipts.entries)
    assert (
        rr.find(provider="ch_foen", station="2251", quantity="discharge", frequency="daily", statistic="mean").series
        == ()
    )


def test_public_nve_all_versions_include_null_series_without_upstream_selection(monkeypatch, tmp_path):
    recordings = tuple(
        read_recording(_DATA / f"no_nve_109.42.0_1001_1440_version-{v}_engine_2024-01-02.recording.json")
        for v in (1, 2, 3)
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(recordings))
    selection = rr.find(
        provider="no_nve", station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", receipts=True, on_issue="ignore")
    assert result.data.height == 3
    assert result.data["series_id"].n_unique() == 3
    assert result.data["value"].null_count() == 1
    assert sorted(result.data["value"].drop_nulls().to_list()) == [26.9778, 74.33918]
    assert {dict(call["request_parameters"])["VersionNumber"] for call in result.provenance.calls_made} == {1, 2, 3}
    assert {entry.content for entry in result.receipts.entries} == {recording.content for recording in recordings}
    assert "protocol-only-nve-key" not in repr(result)


def test_public_ana_physical_daily_scope_returns_both_consistencies_and_narrows(monkeypatch, tmp_path):
    # Token response is protocol-only test input; every observation byte is a real recording.
    from tests.test_br_ana_public_daily import _authenticated_replay

    monkeypatch.chdir(tmp_path)
    transport = _authenticated_replay(monkeypatch, "stage_daily_mean_bruto")
    selection = rr.find(provider="br_ana", station="15400000", quantity="stage", frequency="daily", statistic="mean")
    assert {item.variant for item in selection.series} == {"bruto", "consistido"}
    result = rr.fetch(selection, start="2020-01-10", end="2020-01-20", receipts=True, on_issue="ignore")
    assert result.data.height == 22
    assert result.data["series_id"].n_unique() == 2
    narrowed = rr.pick(result, variant="consistido")
    assert narrowed.data.height == 11
    before = rr.pick(selection, variant="consistido")
    explicitly_fetched = rr.fetch(before, start="2020-01-10", end="2020-01-20", on_issue="ignore")
    pl_testing.assert_frame_equal(narrowed.data, explicitly_fetched.data)
    assert all(entry.content == transport.recording.content for entry in result.receipts.entries)
    assert narrowed.provenance.calls_made == result.provenance.calls_made


def test_public_explicit_swiss_field_does_not_diagnose_unrequested_sibling(monkeypatch, tmp_path):
    recording = read_recording(_DATA / "ch_foen_2251_rest_engine_2026-09-19.recording.json")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.pick(rr.find(provider="ch_foen", station="2251", quantity="discharge"), variant="flow_ls")
    result = rr.fetch(selection, start="2026-09-19T00:00:00", end="2026-09-19T03:00:00", on_issue="raise")
    assert result.data.height == 4
    assert not any(issue.severity in ("warning", "error") for issue in result.issues)


def test_public_nve_failed_explicit_version_survives_physical_predicate(monkeypatch, tmp_path):
    recordings = tuple(
        read_recording(_DATA / f"no_nve_109.42.0_1001_1440_version-{v}_engine_2024-01-02.recording.json")
        for v in (1, 99999)
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(recordings))
    selection = rr.pick(
        rr.find(provider="no_nve", station="109.42.0", quantity="discharge"), variant=("1", "99999"), on_issue="ignore"
    )
    # Narrow the documented daily access coordinate without inventing failed-version facts.
    selection = rr.pick(selection, frequency="daily", on_issue="ignore")
    result = rr.fetch(selection, start="2024-01-02", end="2024-01-02", on_issue="ignore")
    assert result.data.height == 1
    failed = [outcome for outcome in result.outcomes if outcome.status.value == "failed"]
    assert len(failed) == 1
    assert "99999" in failed[0].reason
    definition = next(item for item in result.source_series if item.series_id == failed[0].series_id)
    assert definition.variant == "99999"
    assert definition.identity.published_id is None
    assert definition.facts[0].quantity.value is None
    inspected = rr.series(result)
    failed_rows = inspected.filter(pl.col("variant") == "99999")
    assert failed_rows.height == 1
    assert failed_rows.item(0, "outcomes").to_list() == ["failed"]


@pytest.mark.parametrize("provider", ["ch_foen", "no_nve", "br_ana"])
def test_public_explicit_series_cache_and_bundle_preserve_identity(provider, monkeypatch, tmp_path):
    from rivretrieve._internal.observations import ReceiptAuthorship

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    if provider == "br_ana":
        from tests.test_br_ana_public_daily import _authenticated_replay

        _authenticated_replay(monkeypatch, "stage_daily_mean_consistido")
        selection = rr.pick(
            rr.find(provider=provider, station="15400000", quantity="stage", frequency="daily", statistic="mean"),
            variant="consistido",
        )
        start, end = "2020-01-10", "2020-01-20"
    elif provider == "ch_foen":
        recording = read_recording(_DATA / "ch_foen_2251_rest_engine_2026-09-19.recording.json")
        monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
        selection = rr.pick(rr.find(provider=provider, station="2251", quantity="discharge"), variant="flow_ls")
        start, end = "2026-09-19T00:00:00", "2026-09-19T03:00:00"
    else:
        recording = read_recording(_DATA / "no_nve_109.42.0_1001_1440_version-2_engine_2024-01-02.recording.json")
        monkeypatch.setenv("NVE_API_KEY", "protocol-only-nve-key")
        monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
        selection = rr.pick(
            rr.find(provider=provider, station="109.42.0", quantity="discharge", frequency="daily", statistic="mean"),
            variant="2",
        )
        start = end = "2024-01-02"
    imported_selection = rr.from_bundle(rr.to_bundle(selection))
    assert rr.to_bundle(imported_selection) == rr.to_bundle(selection)
    live = rr.fetch(imported_selection, start=start, end=end, cache="refresh", receipts=True, on_issue="ignore")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    cached = rr.fetch(imported_selection, start=start, end=end, cache="reuse", receipts=True, on_issue="ignore")
    pl_testing.assert_frame_equal(cached.data, live.data)
    assert cached.data["series_id"].n_unique() == 1
    assert cached.provenance.served_intervals
    assert all(item.authorship is ReceiptAuthorship.STORE_EXCERPT for item in cached.receipts.entries)
    restored = rr.from_bundle(rr.to_bundle(cached))
    pl_testing.assert_frame_equal(restored.data, cached.data)
    assert restored.source_series == cached.source_series
    assert restored.outcomes == cached.outcomes
    assert restored.inventories == cached.inventories


def test_public_nve_daily_mean_excludes_published_instantaneous_version():
    broad = rr.find(provider="no_nve", station="1.46.0", quantity="stage", frequency="daily")
    assert {item.variant for item in broad.series} == {"1", "2"}
    means = rr.pick(broad, statistic="mean")
    assert {item.variant for item in means.series} == {"1"}
    assert next(item for item in broad.series if item.variant == "2").facts[0].statistic.value == "instantaneous"

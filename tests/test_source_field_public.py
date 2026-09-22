"""Public conformance uses exact permitted publisher interactions."""

from pathlib import Path

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.observations import ReceiptAuthorship
from rivretrieve._internal.recordings import ReplayTransport, read_recording
from rivretrieve._internal.transport import AuthenticatedTransport, CredentialHeader

DATA = Path(__file__).parent / "test_data"


def test_public_authenticated_flux_normal_padding_cache_and_receipts(monkeypatch, tmp_path):
    recording = read_recording(DATA / "ch_foen_2135_flux_engine_2020-01-01.recording.json")
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    def transport():
        return AuthenticatedTransport(
            ReplayTransport((recording,)),
            (CredentialHeader("Authorization", "Token PROTOCOL-SENTINEL", ("https://influx.konzept.space",)),),
        )

    monkeypatch.setattr(discovery, "HttpClient", transport)
    selection = rr.pick(rr.find(provider="ch_foen", station="2135", quantity="discharge"), variant="flow")
    live = rr.fetch(selection, start="2020-01-01T00:00:00", end="2020-01-01T00:50:00", cache="refresh", receipts=True)
    assert live.data.height == 6
    pl_testing.assert_series_equal(live.data["value"], pl.Series("value", [67.6, 67.6, 67.6, 67.5, 67.5, 67.39]))
    assert live.receipts.entries[0].content == recording.content
    assert live.provenance.endpoints == ("https://influx.konzept.space/api/v2/query",)
    assert "PROTOCOL-SENTINEL" not in repr(live)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    cached = rr.fetch(selection, start="2020-01-01T00:00:00", end="2020-01-01T00:50:00", cache="reuse", receipts=True)
    pl_testing.assert_frame_equal(cached.data, live.data)
    assert cached.provenance.served_intervals
    assert all(receipt.authorship is ReceiptAuthorship.STORE_EXCERPT for receipt in cached.receipts.entries)
    restored = rr.from_bundle(rr.to_bundle(cached))
    pl_testing.assert_frame_equal(restored.data, live.data)
    assert restored.source_series == cached.source_series
    # Explicit flow coverage cannot certify an unrestricted field inventory.
    monkeypatch.setattr(discovery, "HttpClient", transport)
    unrestricted = rr.fetch(
        rr.find(provider="ch_foen", station="2135", quantity="discharge"),
        start="2020-01-01T00:00:00",
        end="2020-01-01T00:50:00",
        cache="reuse",
        receipts=True,
        on_issue="ignore",
    )
    assert any(receipt.authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD for receipt in unrestricted.receipts.entries)
    assert any(outcome.status == "unresolved" for outcome in unrestricted.outcomes)


@pytest.mark.parametrize(
    "provider,station,quantity,variant,recordings,start,end",
    [
        (
            "ba_fhmzbih",
            "2101-B",
            "stage",
            "81 Web Kontinuirani",
            ("ba_fhmzbih_metadata_index.recording.json", "ba_fhmzbih_2101-B_H_1Y.recording.json"),
            "2026-09-01",
            "2026-09-03",
        ),
        (
            "fr_hydroportail",
            "1232000101",
            "discharge",
            "raw",
            ("fr_hydroportail_station_Q_padded.recording.json",),
            "2026-06-01",
            "2026-06-02",
        ),
    ],
)
def test_named_source_selection_cache_and_bundle(
    monkeypatch, tmp_path, provider, station, quantity, variant, recordings, start, end
):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    captures = tuple(read_recording(DATA / name) for name in recordings)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(captures))
    selection = rr.pick(rr.find(provider=provider, station=station, quantity=quantity), variant=variant)
    live = rr.fetch(selection, start=start, end=end, cache="refresh", receipts=True)
    assert not live.data.is_empty()
    assert live.data["series_id"].n_unique() == 1
    assert tuple(item.content for item in live.receipts.entries) == tuple(item.content for item in captures)
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    cached = rr.fetch(selection, start=start, end=end, cache="reuse", receipts=True)
    pl_testing.assert_frame_equal(cached.data, live.data)
    assert all(receipt.authorship is ReceiptAuthorship.STORE_EXCERPT for receipt in cached.receipts.entries)
    restored = rr.from_bundle(rr.to_bundle(cached))
    pl_testing.assert_frame_equal(restored.data, cached.data)
    assert restored.source_series == cached.source_series


def test_published_instantaneous_support_has_one_cross_provider_predicate():
    for provider, station in (("fr_hydroportail", "1232000101"), ("usgs_nwis", "07374000")):
        selected = rr.find(provider=provider, station=station, quantity="discharge", temporal_support="instantaneous")
        assert selected.series
        assert all(
            facts.temporal_support.value == "instantaneous" for series in selected.series for facts in series.facts
        )


@pytest.mark.parametrize("code,quantity,expected", [("QIXnJ", "discharge", 0.823), ("HIXnJ", "stage", 0.449)])
def test_french_daily_maxima_keep_distinct_published_physics(monkeypatch, code, quantity, expected):
    recording = read_recording(DATA / f"fr_hubeau_1011000101_{code}_padded.recording.json")
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selected = rr.find(
        provider="fr_hubeau", station="1011000101", quantity=quantity, frequency="daily", statistic="max"
    )
    result = rr.fetch(selected, start="2025-01-03", end="2025-01-03", receipts=True)
    pl_testing.assert_frame_equal(result.data.select("value"), pl.DataFrame({"value": [expected]}))
    assert result.data["time_zone"].unique().to_list() == ["unknown"]
    assert result.receipts.entries[0].content == recording.content
    assert result.source_series[0].facts[0].day_definition.value is None

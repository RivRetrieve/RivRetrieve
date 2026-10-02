"""Offline modern series discovery, exact finite paging, and unknown source facts."""

import gzip
import hashlib
import importlib
import json
from datetime import datetime

import polars.testing as pt
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse
from tests.usgs_modern_recordings import ModernReplay, body, coordinates

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def test_offline_discovery_exposes_both_siblings_and_exact_descriptions(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline discovery must not resolve transport")

    monkeypatch.setattr(discovery, "HttpClient", forbidden)
    for station, expected in (
        ("07374000", {"c9d823a2491f4b639656a11b35a7625d"}),
        ("02196000", {"0df18b246e8f48ec8e6547a92070e94a", "4d186669708e4dc18f84d271efb953a1"}),
    ):
        selection = rr.find(
            provider="usgs_nwis", station=station, quantity="discharge", frequency="daily", statistic="mean"
        )
        assert {item.variant for item in selection.series} == expected
        assert all(item.identity.description is None for item in selection.series)
        assert rr.series(selection).height == len(expected)
        restored = rr.from_bundle(rr.to_bundle(selection))
        assert restored.series == selection.series
        assert restored.scope == selection.scope


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_v1_pagination_keeps_exact_pages_clips_and_reuses_all(monkeypatch, tmp_path, retained_evidence_root):
    fetch_module = importlib.import_module("rivretrieve._internal.providers.usgs_nwis.fetch")
    original = fetch_module._request

    def small_page(*args, **kwargs):
        from dataclasses import replace

        request = original(*args, **kwargs)
        return replace(request, params={**request.params, "limit": 5})

    monkeypatch.setattr(fetch_module, "_request", small_page)
    names = tuple(f"daily-02196000-v1-pagination-page{i:02}" for i in range(1, 6))
    replay = ModernReplay(*names, evidence_root=retained_evidence_root)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    selection = rr.find(
        provider="usgs_nwis", station="02196000", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2000-01-01", end="2000-01-07", receipts=True, cache="reuse", on_issue="raise")
    assert result.data.height == 14
    assert result.data["series_id"].n_unique() == 2
    assert [receipt.content for receipt in result.receipts.entries] == [
        body(name, retained_evidence_root) for name in names
    ]
    assert len(replay.calls) == 5
    reused = rr.fetch(selection, start="2000-01-01", end="2000-01-07", cache="reuse", on_issue="raise")
    assert len(replay.calls) == 5
    pt.assert_frame_equal(result.data, reused.data)


@pytest.mark.recorded(
    "research/usgs-modern-coverage/probes/modern-02246518-discharge_instantaneous-start.json.gz",
    "research/usgs-modern-coverage/probes/modern-02246518-discharge_instantaneous-start.receipt.json",
)
def test_unknown_continuous_statistic_is_broad_compatible_not_instantaneous(
    retained_evidence_root, monkeypatch, tmp_path
):
    station = "02246518"
    selection = rr.find(provider="usgs_nwis", station=station, quantity="discharge")
    unknown = tuple(
        item
        for item in selection.series
        if item.product_id == "discharge_instantaneous" and item.facts[0].statistic.value is None
    )
    assert unknown
    assert not rr.find(provider="usgs_nwis", station=station, quantity="discharge", statistic="instantaneous").series
    path = retained_evidence_root / "research/usgs-modern-coverage/probes/modern-02246518-discharge_instantaneous-start"
    receipt = json.loads(path.with_suffix(".receipt.json").read_text())
    content = gzip.decompress(path.with_suffix(".json.gz").read_bytes())
    assert hashlib.sha256(content).hexdigest() == receipt["sha256"]
    calls = []

    class Replay:
        def send(self, request):
            calls.append(request)
            if "/daily/" in request.url:
                # Authored independent access failure, not publisher evidence.
                raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
            assert coordinates(request.url, request.params) == coordinates(receipt["url"])
            return TransportResponse(
                content,
                receipt["status"],
                datetime.fromisoformat(receipt["retrieved_at"]),
                receipt["headers"]["Content-Type"],
                request.url,
                request.params,
            )

    monkeypatch.setattr(discovery, "HttpClient", Replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    result = rr.fetch(
        selection,
        start="2015-10-02T00:00:00",
        end="2015-10-04T23:59:59",
        cache="reuse",
        receipts=True,
        on_issue="ignore",
    )
    assert result.data.height > 0
    assert all(
        f.statistic.value is None
        for item in result.source_series
        if item.product_id == "discharge_instantaneous"
        for f in item.facts
    )
    assert rr.pick(result, statistic="instantaneous", on_issue="ignore").data.is_empty()
    restored = rr.from_bundle(rr.to_bundle(result))
    pt.assert_frame_equal(restored.data, result.data)
    assert restored.source_series == result.source_series
    reused = rr.fetch(
        rr.pick(selection, variant=unknown[0].variant),
        start="2015-10-02T00:00:00",
        end="2015-10-04T23:59:59",
        cache="reuse",
        on_issue="raise",
    )
    assert len(calls) == 2
    pt.assert_frame_equal(result.data, reused.data)


@pytest.mark.recorded("tests/test_data/usgs_modern")
def test_unrestricted_snapshot_does_not_hide_newly_encountered_real_identity(
    monkeypatch, tmp_path, retained_evidence_root
):
    """Authored older-inventory control; the replayed publisher response is untouched."""
    from dataclasses import replace

    complete = rr.find(
        provider="usgs_nwis", station="02196000", quantity="discharge", frequency="daily", statistic="mean"
    )
    retained = tuple(item for item in complete.known_series if item.variant == "0df18b246e8f48ec8e6547a92070e94a")
    snapshot = replace(
        complete,
        known_series=retained,
        inventories=tuple(
            inventory.model_copy(update={"members": tuple(item.series_id for item in retained), "member_facts": ()})
            for inventory in complete.inventories
        ),
    )
    assert len(snapshot.series) == 1
    replay = ModernReplay("daily-02196000-2000-all", evidence_root=retained_evidence_root)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    result = rr.fetch(snapshot, start="2000-01-01", end="2000-01-07", cache="reuse", receipts=True, on_issue="raise")
    assert result.scope.restriction.value == "all"
    assert result.data.height == 14
    assert {item.variant for item in result.source_series} == {
        "0df18b246e8f48ec8e6547a92070e94a",
        "4d186669708e4dc18f84d271efb953a1",
    }
    assert result.receipts.entries[0].content == body("daily-02196000-2000-all", retained_evidence_root)
    reused = rr.fetch(snapshot, start="2000-01-01", end="2000-01-07", cache="reuse", on_issue="raise")
    assert len(replay.calls) == 1
    pt.assert_frame_equal(result.data, reused.data)

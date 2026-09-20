"""Exact public replay for every enrolled USGS observation route."""

import json
from pathlib import Path

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.providers.usgs_nwis.config import config
from rivretrieve._internal.recordings import ReplayTransport, read_recording

ROUTES = {
    "discharge_daily_mean": ("dv_00060_00003_2022-12-30_2023-01-03", "discharge", "mean", 0.028316846592),
    "discharge_instantaneous": ("iv_00060_2023-01-01", "discharge", "instantaneous", 0.028316846592),
    "stage_daily_mean": ("dv_00065_00003_2022-12-30_2023-01-03", "stage", "mean", 0.3048),
    "stage_daily_max": ("dv_00065_00001_2022-12-30_2023-01-03", "stage", "max", 0.3048),
    "stage_daily_min": ("dv_00065_00002_2022-12-30_2023-01-03", "stage", "min", 0.3048),
    "stage_instantaneous": ("iv_00065_2022-12-30_2023-01-03", "stage", "instantaneous", 0.3048),
}


def test_public_route_recordings_cover_exact_active_declaration():
    assert set(ROUTES) == set(config().products)


@pytest.mark.parametrize("product", ROUTES)
def test_recorded_public_route_identity_physics_cache_and_receipt(monkeypatch, tmp_path, product):
    suffix, quantity, statistic, factor = ROUTES[product]
    recording = read_recording(Path(__file__).with_name("test_data") / f"usgs_nwis_07374000_{suffix}.recording.json")
    replay = ReplayTransport((recording,))
    calls = []

    class CountingReplay:
        def send(self, request):
            calls.append(request)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", CountingReplay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    selection = rr.find(provider="usgs_nwis", station="07374000", quantity=quantity, statistic=statistic)
    assert {s.product_id for s in selection.series} == {product}
    source = json.loads(recording.content)["value"]["timeSeries"]
    expected = []
    identities = set()
    for item in source:
        for block in item["values"]:
            (method,) = block["method"]
            identities.add((str(method["methodID"]), method["methodDescription"]))
            expected.extend(
                float(entry["value"]) * factor
                for entry in block["value"]
                if entry["dateTime"].startswith("2023-01-01T")
            )
    assert expected

    def fetch(mode):
        return rr.fetch(selection, start="2023-01-01", end="2023-01-01", cache=mode, receipts=True, on_issue="raise")

    bypass = fetch("bypass")
    pt.assert_frame_equal(bypass.data.select("value").sort("value"), pl.DataFrame({"value": expected}).sort("value"))
    assert {(s.identity.published_id, s.identity.description) for s in bypass.source_series} == identities
    assert all(s.identity.namespace == "methodID" for s in bypass.source_series)
    assert set(bypass.data["source_unit"]) == ({"ft3/s"} if quantity == "discharge" else {"ft"})
    assert set(bypass.data["unit"]) == ({"m3/s"} if quantity == "discharge" else {"m"})
    assert set(bypass.data["time_zone"]) == ({"-06:00"} if statistic == "instantaneous" else {"unknown"})
    assert bypass.receipts.entries[0].content == recording.content
    assert bypass.receipts.entries[0].origin.retrieved_at == recording.retrieved_at
    for mode in ("reuse", "reuse", "refresh", "reuse"):
        result = fetch(mode)
        pt.assert_frame_equal(result.data, bypass.data)
        assert all(o.status == "success" for o in result.outcomes)
    assert len(calls) == 3


def test_daily_response_label_does_not_establish_filterable_timestamp_anchor(monkeypatch):
    recording = read_recording(
        Path(__file__).with_name("test_data") / "usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport((recording,)))
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", on_issue="raise")
    assert result.data.height == 1
    assert result.data["time"][0].hour == 0
    for series in result.source_series:
        for facts in series.facts:
            assert facts.timestamp_anchor.state == "not_established"
            assert facts.timestamp_anchor.value is None
            assert facts.label_time == "00:00"
            assert facts.clipping_axis == "calendar_date"
    narrowed = rr.pick(result, timestamp_anchor="00:00", on_issue="ignore")
    assert narrowed.data.is_empty()


def test_daily_catalogue_does_not_promote_label_representation_to_anchor():
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    assert selection.series
    assert all(f.timestamp_anchor.value is None for s in selection.series for f in s.facts)
    narrowed = rr.pick(selection, timestamp_anchor="00:00", on_issue="ignore")
    assert not narrowed.series


def test_authored_nonmidnight_offset_daily_method_is_unsupported_with_peer_preserved(monkeypatch):
    """Structural mutation of a recording, not evidence of a nonmidnight USGS product."""
    from copy import deepcopy

    from rivretrieve._internal.transport import TransportResponse

    recording = read_recording(
        Path(__file__).with_name("test_data") / "usgs_nwis_07374000_dv_00060_00003_2022-12-30_2023-01-03.recording.json"
    )
    document = json.loads(recording.content)
    blocks = document["value"]["timeSeries"][0]["values"]
    supported = deepcopy(blocks[0])
    supported["method"][0]["methodID"] = 0
    blocks.append(supported)
    invalid = next(e for e in blocks[0]["value"] if e["dateTime"].startswith("2023-01-01T"))
    invalid["dateTime"] = "2023-01-01T12:00:00-06:00"
    content = json.dumps(document).encode()

    class AuthoredTransport:
        def send(self, request):
            assert request.url == recording.request.url
            assert dict(request.params) == dict(recording.request.parameters)
            return TransportResponse(
                content, 200, recording.retrieved_at, recording.content_type, request.url, request.params
            )

    monkeypatch.setattr(discovery, "HttpClient", AuthoredTransport)
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2023-01-01", end="2023-01-01", receipts=True, on_issue="ignore")
    assert result.data.height == 1
    healthy = next(s for s in result.source_series if s.identity.published_id == "0")
    failed = next(s for s in result.source_series if s.identity.published_id != "0")
    assert result.data["series_id"].to_list() == [healthy.series_id]
    assert any(o.series_id == healthy.series_id and o.status == "success" for o in result.outcomes)
    unsupported = [o for o in result.outcomes if o.series_id == failed.series_id]
    assert len(unsupported) == 1
    assert unsupported[0].status == "unsupported"
    assert "midnight" in unsupported[0].reason
    assert any(i.details["series_id"] == failed.series_id for i in result.issues)
    assert result.receipts.entries[0].content == content

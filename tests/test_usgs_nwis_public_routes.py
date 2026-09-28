"""Exact public replay for every enrolled modern USGS observation route."""

import json
from datetime import datetime

import polars as pl
import polars.testing as pt
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.providers.usgs_nwis.config import config
from tests.usgs_modern_recordings import MANIFEST, ModernReplay, body, coordinates

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

ROUTES = {
    "discharge_daily_mean": ("daily-07374000-discharge-mean", "discharge", "mean", 0.028316846592),
    "discharge_instantaneous": ("continuous-07374000-2010-discharge", "discharge", "instantaneous", 0.028316846592),
    "stage_daily_mean": ("daily-07374000-stage-mean", "stage", "mean", 0.3048),
    "stage_daily_max": ("daily-07374000-stage-maximum", "stage", "max", 0.3048),
    "stage_daily_min": ("daily-07374000-stage-minimum", "stage", "min", 0.3048),
    "stage_instantaneous": ("continuous-07374000-2010-stage", "stage", "instantaneous", 0.3048),
}


def test_public_route_recordings_cover_exact_active_declaration():
    assert set(ROUTES) == set(config().products)


@pytest.mark.parametrize("product", ROUTES)
def test_recorded_public_route_identity_physics_cache_and_receipt(monkeypatch, tmp_path, product):
    suffix, quantity, statistic, factor = ROUTES[product]
    content = body(suffix)
    replay = ModernReplay(suffix)
    calls = []

    class CountingReplay:
        def send(self, request):
            calls.append(request)
            return replay.send(request)

    monkeypatch.setattr(discovery, "HttpClient", CountingReplay)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    daily = statistic != "instantaneous"
    start, end = ("2024-01-01", "2024-01-07") if daily else ("2010-06-01T05:00:00", "2010-06-02T04:59:59")
    selection = rr.find(provider="usgs_nwis", station="07374000", quantity=quantity, statistic=statistic)
    assert {s.product_id for s in selection.series} == {product}
    source = json.loads(content)["features"]
    expected = []
    identities = set()
    for feature in source:
        item = feature["properties"]
        identities.add(item["time_series_id"])
        stamp = datetime.fromisoformat(item["time"].replace("Z", "+00:00")).replace(tzinfo=None)
        if datetime.fromisoformat(start) <= stamp <= datetime.fromisoformat(end):
            expected.append(float(item["value"]) * factor)
    assert len(expected) == (7 if daily else 96)

    def fetch(mode):
        return rr.fetch(selection, start=start, end=end, cache=mode, receipts=True, on_issue="raise")

    bypass = fetch("bypass")
    pt.assert_frame_equal(bypass.data.select("value").sort("value"), pl.DataFrame({"value": expected}).sort("value"))
    assert {s.identity.published_id for s in bypass.source_series} == identities
    assert all(s.identity.namespace == "USGS.WaterData.time_series_id" for s in bypass.source_series)
    assert all(s.identity.description is None for s in bypass.source_series)
    assert set(bypass.data["source_unit"]) == ({"ft^3/s"} if quantity == "discharge" else {"ft"})
    assert set(bypass.data["unit"]) == ({"m3/s"} if quantity == "discharge" else {"m"})
    assert set(bypass.data["time_zone"]) == ({"unknown"} if daily else {"+00:00"})
    assert bypass.receipts.entries[0].content == content
    assert bypass.receipts.entries[0].origin.retrieved_at == datetime.fromisoformat(MANIFEST[suffix]["acquired_utc"])
    for mode in ("reuse", "reuse", "refresh", "reuse"):
        result = fetch(mode)
        pt.assert_frame_equal(result.data, bypass.data)
        assert all(o.status == "success" for o in result.outcomes)
    assert len(calls) == 3


def test_daily_response_label_does_not_establish_filterable_timestamp_anchor(monkeypatch):
    monkeypatch.setattr(discovery, "HttpClient", lambda: ModernReplay("daily-07374000-discharge-mean"))
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2024-01-01", end="2024-01-07", on_issue="raise")
    assert result.data.height == 7
    assert result.data["time"][0].hour == 0
    for series in result.source_series:
        for facts in series.facts:
            assert facts.timestamp_anchor.state == "source_silent"
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


def test_authored_non_date_daily_series_is_unsupported_with_peer_preserved(monkeypatch):
    """Authored mutation of exact modern bytes, not evidence of a nonmidnight USGS product."""
    from copy import deepcopy

    from rivretrieve._internal.transport import TransportResponse

    name = "daily-07374000-discharge-mean"
    content = body(name)
    document = json.loads(content)
    original = document["features"]
    healthy_id = "authored-independent-series"
    peers = deepcopy(original)
    for feature in peers:
        feature["properties"]["time_series_id"] = healthy_id
    invalid = next(feature["properties"] for feature in original if feature["properties"]["time"] == "2024-01-01")
    invalid["time"] = "2024-01-01T12:00:00-06:00"
    document["features"].extend(peers)
    content = json.dumps(document).encode()

    class AuthoredTransport:
        def send(self, request):
            assert coordinates(request.url, request.params) == coordinates(MANIFEST[name]["original_url"])
            return TransportResponse(
                content,
                200,
                datetime.fromisoformat(MANIFEST[name]["acquired_utc"]),
                "application/json",
                request.url,
                request.params,
            )

    monkeypatch.setattr(discovery, "HttpClient", AuthoredTransport)
    selection = rr.find(
        provider="usgs_nwis", station="07374000", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2024-01-01", end="2024-01-07", receipts=True, on_issue="ignore")
    assert result.data.height == 7
    healthy = next(s for s in result.source_series if s.identity.published_id == healthy_id)
    failed = next(s for s in result.source_series if s.identity.published_id != healthy_id)
    assert set(result.data["series_id"]) == {healthy.series_id}
    assert any(o.series_id == healthy.series_id and o.status == "success" for o in result.outcomes)
    assert any(
        o.series_id == failed.series_id and o.status == "unsupported" and "date-only" in o.reason
        for o in result.outcomes
    )
    assert any(i.details.get("series_id") == failed.series_id for i in result.issues)
    assert result.receipts.entries[0].content == content

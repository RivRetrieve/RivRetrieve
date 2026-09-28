"""UTC acquisitions retain native offset labels across cache span boundaries."""

from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse
from tests.test_usgs_observation_acquisition import STATION, feature, page

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


class _Spans:
    def __init__(self, series_id):
        self.series_id = series_id
        self.second_series_id = series_id
        self.calls = []
        self.failed_first = False
        self.failed_second = False
        self.value = 10
        self.second_unit = "ft^3/s"
        self.second_statistic = "00011"

    def send(self, request):
        index = len(self.calls) % 2
        self.calls.append(request)
        if (self.failed_second and index == 1) or (self.failed_first and index == 0):
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
        begin, end = [
            datetime.fromisoformat(value.removesuffix("Z")) for value in request.params["datetime"].split("/")
        ]
        # Both labels cross the naive UTC span boundary in opposite directions.
        # Offsets are explicit publisher fields; one physical fact has both.
        stamp = (
            (end + timedelta(hours=3)).isoformat() + "+03:00"
            if index == 0
            else (begin - timedelta(hours=5)).isoformat() + "-05:00"
        )
        observation = feature(self.series_id if index == 0 else self.second_series_id)
        observation["properties"].update(
            statistic_id="00011" if index == 0 else self.second_statistic,
            unit_of_measure="ft^3/s" if index == 0 else self.second_unit,
            time=stamp,
            value=str(self.value + index),
        )
        return TransportResponse(
            page(observation),
            200,
            datetime(2026, 9, 28, tzinfo=UTC),
            "application/geo+json",
            request.url,
            request.params or {},
        )


def test_public_continuous_offset_boundaries_persist_refresh_and_reuse(monkeypatch, tmp_path):
    selected = rr.find(provider="usgs_nwis", station=STATION, quantity="discharge")
    continuous = next(item for item in selected.series if item.product_id == "discharge_instantaneous")
    selected = rr.pick(selected, series_id=continuous.series_id)

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    transport = _Spans(continuous.identity.published_id)
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    def fetch(cache):
        return rr.fetch(selected, start="2000-01-03", end="2003-02-01", cache=cache, receipts=True, on_issue="ignore")

    first = fetch("refresh")
    assert len(transport.calls) == 2
    assert first.data.height == 2
    assert set(first.data["time_zone"]) == {"+03:00", "-05:00"}
    assert len(set(first.data["facts_id"])) == 1
    stored = pl.concat([pl.read_parquet(path) for path in (tmp_path / "usgs_nwis/store").rglob("*.parquet")])
    assert_frame_equal(
        stored.select("time", "time_zone").sort("time"), first.data.select("time", "time_zone").sort("time")
    )
    assert_frame_equal(fetch("reuse").data, first.data)
    assert len(transport.calls) == 2

    transport.value = 20
    transport.failed_second = True
    refreshed = fetch("refresh")
    assert len(transport.calls) == 4
    np.testing.assert_allclose(refreshed.data.sort("time")["value"], np.array([11, 20]) * 0.028316846592)
    assert set(refreshed.data["time_zone"]) == {"+03:00", "-05:00"}
    assert any(item.status == "failed" for item in refreshed.outcomes)
    assert_frame_equal(fetch("reuse").data, refreshed.data)
    assert len(transport.calls) == 4


@pytest.mark.parametrize("failed_span", [0, 1])
def test_public_single_successful_utc_span_validates_native_offset_rows(monkeypatch, tmp_path, failed_span):
    selected = rr.find(provider="usgs_nwis", station=STATION, quantity="discharge")
    continuous = next(item for item in selected.series if item.product_id == "discharge_instantaneous")
    selected = rr.pick(selected, series_id=continuous.series_id)
    transport = _Spans(continuous.identity.published_id)
    transport.failed_first = failed_span == 0
    transport.failed_second = failed_span == 1
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    def fetch(cache):
        return rr.fetch(selected, start="2000-01-03", end="2003-02-01", cache=cache, on_issue="ignore")

    partial = fetch("refresh")
    assert partial.data.height == 1
    assert partial.data["time_zone"].to_list() == (["-05:00"] if failed_span == 0 else ["+03:00"])
    stored = pl.concat([pl.read_parquet(path) for path in (tmp_path / "usgs_nwis/store").rglob("*.parquet")])
    assert_frame_equal(stored.select("time", "time_zone"), partial.data.select("time", "time_zone"))
    assert_frame_equal(fetch("reuse").data, partial.data)
    assert len(transport.calls) == 4


def test_public_all_series_completed_spans_reuse_complete_inventory_union(monkeypatch, tmp_path):
    selected = rr.find(provider="usgs_nwis", station=STATION, quantity="discharge", temporal_support="instantaneous")
    assert len(selected.series) == 1
    transport = _Spans(selected.series[0].identity.published_id)
    transport.second_series_id = "authored-new-series-in-second-span"
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    def fetch(cache):
        return rr.fetch(selected, start="2000-01-03", end="2003-02-01", cache=cache, on_issue="ignore")

    result = fetch("refresh")
    assert result.data.height == 2
    assert len(set(result.data["series_id"])) == 2
    assert len(transport.calls) == 2
    assert_frame_equal(fetch("reuse").data, result.data)
    assert len(transport.calls) == 2


@pytest.mark.parametrize("changed_fact", ["unit", "statistic"])
def test_public_continuous_fact_changes_across_spans_keep_all_source_facts(monkeypatch, tmp_path, changed_fact):
    selected = rr.find(provider="usgs_nwis", station=STATION, quantity="discharge")
    continuous = next(item for item in selected.series if item.product_id == "discharge_instantaneous")
    selected = rr.pick(selected, series_id=continuous.series_id)
    transport = _Spans(continuous.identity.published_id)
    if changed_fact == "unit":
        transport.second_unit = "m^3/s"
    else:
        transport.second_statistic = None
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    result = rr.fetch(selected, start="2000-01-03", end="2003-02-01", cache="refresh", on_issue="ignore")
    assert result.data.height == 2
    assert len(set(result.data["facts_id"])) == 2
    definition = next(item for item in result.source_series if item.series_id == continuous.series_id)
    assert set(result.data["facts_id"]).issubset({fact.facts_id for fact in definition.facts})
    assert all(item.completeness.value == "complete" for item in result.inventories if item.origin == "response")
    reused = rr.fetch(selected, start="2000-01-03", end="2003-02-01", cache="reuse", on_issue="ignore")
    assert_frame_equal(reused.data, result.data)
    assert len(transport.calls) == 2


def test_public_narrow_inventory_refresh_cannot_hide_new_series_in_broad_reuse(monkeypatch, tmp_path):
    selected = rr.find(provider="usgs_nwis", station=STATION, quantity="discharge", temporal_support="instantaneous")
    original = _Spans(selected.series[0].identity.published_id)

    class Publication:
        def __init__(self):
            self.updated = False
            self.calls = []

        def send(self, request):
            self.calls.append(request)
            if not self.updated:
                return original.send(request)
            begin, end = [
                datetime.fromisoformat(value.removesuffix("Z")) for value in request.params["datetime"].split("/")
            ]
            stamp = datetime(2003, 1, 15, 12)
            observations = []
            if begin <= stamp <= end:
                observation = feature("new-member-after-narrow-refresh")
                observation["properties"].update(statistic_id="00011", time=stamp.isoformat() + "Z")
                observations.append(observation)
            return TransportResponse(
                page(*observations),
                200,
                datetime(2026, 9, 28, tzinfo=UTC),
                "application/geo+json",
                request.url,
                request.params or {},
            )

    transport = Publication()
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    rr.fetch(selected, start="2000-01-03", end="2003-02-01", cache="refresh", on_issue="ignore")
    transport.updated = True
    narrow = rr.fetch(selected, start="2003-01-03", end="2003-02-01", cache="refresh", on_issue="ignore")
    assert narrow.data.height == 1
    reused = rr.fetch(selected, start="2000-01-03", end="2003-02-01", cache="reuse", on_issue="ignore")
    assert_frame_equal(reused.data, narrow.data)

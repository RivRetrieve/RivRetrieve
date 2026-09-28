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


def test_public_continuous_offset_boundaries_persist_refresh_and_reuse(monkeypatch, tmp_path):
    selected = rr.find(provider="usgs_nwis", station=STATION, quantity="discharge")
    continuous = next(item for item in selected.series if item.product_id == "discharge_instantaneous")
    selected = rr.pick(selected, series_id=continuous.series_id)

    class Spans:
        def __init__(self):
            self.calls = []
            self.failed_second = False
            self.value = 10

        def send(self, request):
            index = len(self.calls) % 2
            self.calls.append(request)
            if self.failed_second and index == 1:
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
            observation = feature(continuous.identity.published_id)
            observation["properties"].update(statistic_id="00011", time=stamp, value=str(self.value + index))
            return TransportResponse(
                page(observation),
                200,
                datetime(2026, 9, 28, tzinfo=UTC),
                "application/geo+json",
                request.url,
                request.params or {},
            )

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path))
    transport = Spans()
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

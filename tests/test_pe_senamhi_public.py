"""Public SENAMHI selection, source isolation and accumulated-store controls."""

import json
from datetime import UTC, datetime

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.transport import TransportResponse


class Replay:
    def __init__(self, documents):
        self.documents = iter(documents)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return TransportResponse(
            content=json.dumps(next(self.documents)).encode(),
            status_code=200,
            retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
            content_type="application/json",
            url=request.url,
            request_parameters=request.params,
        )


def phisis(rows, resolution="DAILY", variable="FLOW", unit="m3/s", station="47251282"):
    return {
        "status": True,
        "data": {
            "station": {"code": station},
            "type": resolution,
            "variable": variable,
            "unit": unit,
            "daily" if resolution == "DAILY" else "hourly": rows,
        },
    }


def select_product(station, product):
    selected = rr.find(provider="pe_senamhi", station=station)
    identities = rr.as_frame(selected).filter(pl.col("product_id") == product)["series_id"].to_list()
    return rr.pick(selected, series_id=identities)


def test_public_daily_selection_fetch_and_reuse(monkeypatch):
    document = phisis(
        [
            {"date": "2024-01-02", "current": -9, "minimum": None, "maximum": 7},
            {"date": "2024-01-03", "current": 10, "minimum": 8, "maximum": 12},
        ]
    )
    replay = Replay([document, document, document])
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selected = select_product("47251282", "phisis_daily_flow")
    result = rr.fetch(
        selected, start="2024-01-02", end="2024-01-02T23:59:59", cache="reuse", receipts=True, on_issue="ignore"
    )
    assert result.data.height == 3
    assert result.data["time"].to_list() == [datetime(2024, 1, 2)] * 3
    assert sorted(result.data["value"].drop_nulls()) == [-9.0, 7.0]
    assert result.data["value"].null_count() == 1
    assert result.data["series_id"].n_unique() == 3
    assert result.data["time_zone"].unique().to_list() == ["unknown"]
    repeated = rr.fetch(selected, start="2024-01-02", end="2024-01-02T23:59:59", cache="reuse", on_issue="ignore")
    assert_frame_equal(result.data, repeated.data)
    assert len(replay.requests) == 1
    source = result.provenance.acquisition_provenance.header.source_records[0]
    assert source.issuer == "Servicio Nacional de Meteorología e Hidrología del Perú (SENAMHI)"
    assert any(
        statement.kind == "terms" and "entera responsabilidad" in statement.exact_text
        for statement in source.statements
    )


def test_public_hourly_owned_overlap_and_cache_refresh_failure(monkeypatch):
    first = phisis([{"time": "2024-08-30T06:00:00", "value": 1}, {"time": "2024-08-31T06:00:00", "value": 2}], "HOURLY")
    second = phisis(
        [{"time": "2024-08-31T06:00:00", "value": 999}, {"time": "2024-09-01T06:00:00", "value": 3}], "HOURLY"
    )
    empty = phisis([], "HOURLY")
    replay = Replay([empty, first, second, empty] * 2 + [{"status": False, "message": "source refusal"}] * 4)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    selected = select_product("47251282", "phisis_hourly_flow")
    kwargs = {"start": "2024-08-30", "end": "2024-09-02T23:59:59", "on_issue": "ignore", "receipts": True}
    result = rr.fetch(selected, cache="reuse", **kwargs)
    assert_frame_equal(
        result.data.select("time", "value"),
        pl.DataFrame(
            {
                "time": [datetime(2024, 8, 30, 6), datetime(2024, 8, 31, 6), datetime(2024, 9, 1, 6)],
                "value": [1.0, 2.0, 3.0],
            }
        ),
    )
    assert len(result.receipts.entries) == 4
    assert b"999" in result.receipts.entries[2].content
    reused = rr.fetch(selected, cache="reuse", **kwargs)
    assert len(replay.requests) == 4
    assert_frame_equal(result.data, reused.data)
    bypassed = rr.fetch(selected, cache="bypass", **kwargs)
    assert len(replay.requests) == 8
    assert_frame_equal(result.data, bypassed.data)
    failed = rr.fetch(selected, cache="refresh", **kwargs)
    assert len(replay.requests) == 12
    assert_frame_equal(result.data, failed.data)
    assert any(issue.code == "source.response_failed" for issue in failed.issues)
    assert not any(issue.code == "unsupported_source_structure" for issue in failed.issues)


def test_public_success_survives_failed_adjacent_partition(monkeypatch):
    replay = Replay(
        [
            phisis([], "HOURLY"),
            phisis([{"time": "2024-08-30T06:00:00", "value": None}], "HOURLY"),
            {"status": False, "message": "source refusal"},
            phisis([], "HOURLY"),
        ]
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    result = rr.fetch(
        select_product("47251282", "phisis_hourly_flow"),
        start="2024-08-30",
        end="2024-09-02T23:59:59",
        cache="bypass",
        on_issue="ignore",
    )
    assert result.data.height == 1 and result.data["value"].null_count() == 1
    assert any(issue.code == "source.response_failed" for issue in result.issues)
    assert {outcome.status.value for outcome in result.outcomes} >= {"success", "failed"}


@pytest.mark.parametrize(
    "resolution,variable,unit",
    [(r, v, u) for r in ("DAILY", "HOURLY") for v, u in (("FLOW", "m3/s"), ("LEVEL", "m"), ("LEVEL", "m.s.n.m"))],
)
def test_public_phisis_routes_keep_units_and_fields(monkeypatch, resolution, variable, unit):
    product = f"phisis_{resolution.lower()}_{variable.lower()}" + ("_above_sea_level" if unit == "m.s.n.m" else "")
    candidates = rr.as_frame(rr.find(provider="pe_senamhi")).filter(pl.col("product_id") == product)
    station = candidates["station_id"][0]
    row = (
        {"date": "2024-01-10", "current": 1, "minimum": 2, "maximum": 3}
        if resolution == "DAILY"
        else {"time": "2024-01-10T06:00:00", "value": 4}
    )
    replay = Replay([phisis([row], resolution, variable, unit, station)] * 4)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    result = rr.fetch(
        select_product(station, product),
        start="2024-01-10",
        end="2024-01-10T23:59:59",
        cache="bypass",
        on_issue="ignore",
    )
    assert result.data.height == (3 if resolution == "DAILY" else 1)
    assert result.data["source_unit"].unique().to_list() == [unit]
    assert result.data["unit"].unique().to_list() == ["m3/s" if variable == "FLOW" else "m"]
    assert not any(issue.severity == "error" for issue in result.issues)


def test_public_monthly_fields_remain_separate_and_unknown(monkeypatch):
    from rivretrieve._internal.providers.pe_senamhi.series import MONTHLY_LEVEL_FIELDS

    for field in sorted(MONTHLY_LEVEL_FIELDS):
        product = "monthly_archive_" + field.lower()
        candidates = rr.as_frame(rr.find(provider="pe_senamhi")).filter(pl.col("product_id") == product)
        station = candidates["station_id"][0]
        replay = Replay(
            [
                {
                    "status": True,
                    "data": {
                        "columns": [{"column": field, "unit": "m"}],
                        "readings": [{"date": "2027-01-10", "time": "", "values": [{"column": field, "value": -5}]}],
                    },
                }
            ]
        )
        monkeypatch.setattr(discovery, "HttpClient", lambda replay=replay: replay)
        result = rr.fetch(
            select_product(station, product),
            start="2027-01-10",
            end="2027-01-10T23:59:59",
            cache="bypass",
            on_issue="ignore",
        )
        assert result.data["value"].to_list() == [-5.0]
        assert result.data["product_id"].to_list() == [product]
        assert result.data["time_zone"].to_list() == ["unknown"]
        assert not any(issue.severity == "error" for issue in result.issues)

"""Public official access controls using synthetic transport responses."""

import json
from datetime import UTC, datetime

import pytest

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.transport import TransportResponse


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_offline_selection_reaches_anonymous_official_retrieval(monkeypatch):
    requests = []

    class Transport:
        def send(self, request):
            requests.append(request)
            return TransportResponse(
                json.dumps(
                    {
                        "data": {
                            "water": {
                                "observations": {
                                    "data_10min_mean": [
                                        {
                                            "station": {"no": "2018"},
                                            "parameterName": "Q",
                                            "tsName": "Synthetic",
                                            "unitSymbol": "l/s",
                                            "timestamp": "2025-01-01T00:00:00Z",
                                            "value": 1200.0,
                                            "releaseState": "3",
                                        }
                                    ]
                                }
                            }
                        }
                    }
                ).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    monkeypatch.setattr(discovery, "HttpClient", Transport)
    selection = rr.find(provider="ch_foen", station="2018", quantity="discharge", frequency="10min", statistic="mean")
    result = rr.fetch(selection, start="2025-01-01", end="2025-01-01", receipts=True, on_issue="ignore")
    assert result.data.select("time", "source_unit", "unit", "value").rows() == [
        (datetime(2025, 1, 1), "l/s", "m3/s", 1.2)
    ]
    assert len(requests) == 1
    assert requests[0].url == "https://data.bafu.admin.ch/api"
    assert not any(key.lower() == "authorization" for key in requests[0].headers)
    assert result.receipts.entries[0].content
    assert result.provenance.endpoints == ("https://data.bafu.admin.ch/api",)


@pytest.mark.usefixtures("reuse_packaged_catalogues")
@pytest.mark.parametrize(
    "quantity,parameter,unit,value,expected",
    [
        ("discharge", "Q", "l/s", 1200.0, 1.2),
        ("stage", "W", "cm", 120.0, 1.2),
        ("temperature", "WT", "°C", 12.0, 12.0),
    ],
)
@pytest.mark.parametrize(
    "frequency,statistic,route,stamp",
    [
        ("10min", "mean", "data_10min_mean", "2025-07-01T00:00:00Z"),
        ("hourly", "mean", "data_1hour_mean", "2025-07-01T00:00:00Z"),
        *[
            (frequency, statistic, f"data_{period}_{statistic}", "2025-06-30T23:00:00Z")
            for frequency, period in [("daily", "1day"), ("monthly", "1month")]
            for statistic in ("mean", "min", "max")
        ],
        *[
            ("yearly", statistic, f"data_1year_{statistic}", "2024-12-31T23:00:00Z")
            for statistic in ("mean", "min", "max")
        ],
    ],
)
def test_public_archive_routes_preserve_variants_and_calendar_labels(
    monkeypatch, quantity, parameter, unit, value, expected, frequency, statistic, route, stamp
):
    class Transport:
        def send(self, request):
            query = json.loads(request.body)["query"]
            assert route + "(" in query
            assert f'parameterName: {{_eq: "{parameter}"}}' in query
            rows = [
                {
                    "station": {"no": "2018"},
                    "parameterName": parameter,
                    "tsName": variant,
                    "unitSymbol": unit,
                    "timestamp": stamp,
                    "value": amount,
                    "releaseState": status,
                }
                for variant, amount, status in [("Synthetic", value, "3"), ("Synthetic_01", None, None)]
            ]
            return TransportResponse(
                json.dumps({"data": {"water": {"observations": {route: rows}}}}).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    monkeypatch.setattr(discovery, "HttpClient", Transport)
    selection = rr.find(provider="ch_foen", station="2018", quantity=quantity, frequency=frequency, statistic=statistic)
    start, end = ("2025-01-01", "2025-12-31") if frequency == "yearly" else ("2025-07-01", "2025-07-31")
    result = rr.fetch(selection, start=start, end=end, on_issue="ignore")
    assert result.data.sort("value", nulls_last=True)["value"].to_list() == [expected, None]
    assert result.data["series_id"].n_unique() == 2
    assert result.data["time"].to_list() == [datetime.fromisoformat(stamp).replace(tzinfo=None)] * 2


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_public_cache_reuse_bypass_and_failed_refresh(monkeypatch):
    calls = []

    class Transport:
        value = 10.0
        failed = False

        def send(self, request):
            calls.append(request)
            document = (
                {"errors": [{"message": "source unavailable"}]}
                if self.failed
                else {
                    "data": {
                        "water": {
                            "observations": {
                                "data_10min_mean": [
                                    {
                                        "station": {"no": "2018"},
                                        "parameterName": "Q",
                                        "tsName": "10MinMittel",
                                        "unitSymbol": "m3/s",
                                        "timestamp": "2025-01-01T00:00:00Z",
                                        "value": self.value,
                                        "releaseState": "3",
                                    }
                                ]
                            }
                        }
                    }
                }
            )
            return TransportResponse(
                json.dumps(document).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    transport = Transport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    selection = rr.find(
        provider="ch_foen", station="2018", quantity="discharge", frequency="10min", variant="10MinMittel"
    )

    def fetch(cache):
        return rr.fetch(selection, start="2025-01-01", end="2025-01-01", cache=cache, on_issue="ignore")

    first = fetch("refresh")
    cached = fetch("reuse")
    assert len(calls) == 1
    assert cached.data["value"].to_list() == [10.0]
    assert cached.provenance.retrieved_at == first.provenance.retrieved_at
    transport.value = 20.0
    assert fetch("bypass").data["value"].to_list() == [20.0]
    assert fetch("reuse").data["value"].to_list() == [10.0]
    assert len(calls) == 2
    transport.failed = True
    refreshed = fetch("refresh")
    assert refreshed.data["value"].to_list() == [10.0]
    assert any(item.status.value == "failed" and "source unavailable" in item.reason for item in refreshed.outcomes)


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_public_recent_null_empty_and_archive_failure_remain_distinct(monkeypatch):
    calls = []

    class Transport:
        empty = False

        def send(self, request):
            query = json.loads(request.body)["query"]
            calls.append(query)
            if "data_live(" in query:
                document = {
                    "data": {
                        "water": {
                            "observations": {
                                "data_live": []
                                if self.empty
                                else [
                                    {
                                        "stationNo": "2018",
                                        "parameterName": "Q",
                                        "timestamp": "2025-01-01T00:00:00Z",
                                        "value": None,
                                        "releaseStatus": 0,
                                    }
                                ]
                            }
                        }
                    }
                }
            else:
                document = {"errors": [{"message": "archive unavailable", "errorType": "SourceError"}]}
            return TransportResponse(
                json.dumps(document).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    transport = Transport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    selection = rr.find(provider="ch_foen", station="2018", quantity="discharge")
    result = rr.fetch(selection, start="2025-01-01", end="2025-01-01", receipts=True, on_issue="ignore")
    assert result.data.select("product_id", "time", "value").rows() == [
        ("discharge_recent", datetime(2025, 1, 1), None)
    ]
    assert len(calls) == 12
    assert all('parameterName: {_eq: "Q"}' in query for query in calls)
    failures = [item for item in result.outcomes if item.status.value == "failed"]
    assert len(failures) == 11
    assert all("archive unavailable" in item.reason and item.product_id != "discharge_recent" for item in failures)
    recent_id = result.data["series_id"][0]
    transport.empty = True
    empty = rr.fetch(
        rr.find(provider="ch_foen", station="2018", series_id=recent_id),
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )
    assert empty.data.is_empty()
    assert any(item.status.value == "unresolved" and "retention" in item.reason for item in empty.outcomes)


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_retired_existenz_cache_cannot_satisfy_official_request(monkeypatch, tmp_path):
    import polars as pl

    from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval
    from rivretrieve._internal.engine import RowsSchema
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.source_series import (
        OutcomeStatus,
        PhysicalFacts,
        RetrievalOutcome,
        SeriesWindow,
        SourceIdentity,
        SourceSeries,
        known,
        stable_id,
    )
    from rivretrieve._internal.store import StoreRoot
    from rivretrieve._internal.store.accumulation import StoreUpdate, SuccessfulReplacement, accumulate
    from tests.test_partial_explicit_scope import _official_replay

    root = tmp_path / "cache"
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(root))
    # Historical identity and product contract, without retaining its fetcher/parser.
    identity = stable_id("ch_foen", "2018", "field", "flow")
    fact = PhysicalFacts(
        facts_id="legacy-facts",
        quantity=known("discharge", "synthetic"),
        source_unit=known("m3/s", "synthetic"),
        normalized_unit="m3/s",
        time_zone=known("+00:00", "synthetic"),
    )
    definition = SourceSeries(
        series_id=identity,
        provider_id="ch_foen",
        station_id="2018",
        product_id="discharge_reported",
        identity=SourceIdentity(
            namespace="existenz.parameter", published_id="flow", origin="mapping", evidence=("synthetic",)
        ),
        variant="flow",
        facts=(fact,),
    )
    start, end = datetime(2025, 1, 1), datetime(2025, 1, 1, 0, 30)
    retrieved = datetime(2026, 1, 1, tzinfo=UTC)
    outcome = RetrievalOutcome(
        outcome_id="legacy-success",
        series_id=identity,
        station_id="2018",
        product_id="discharge_reported",
        window=SeriesWindow(start=start, end=end),
        status=OutcomeStatus.SUCCESS,
        facts_ids=(fact.facts_id,),
        retrieved_at=retrieved,
    )
    rows = pl.DataFrame(
        [
            {
                "station_id": "2018",
                "product_id": "discharge_reported",
                "time": start,
                "value": 999.0,
                "time_zone": "+00:00",
                "series_id": identity,
                "facts_id": fact.facts_id,
                "source_unit": "m3/s",
            }
        ],
        schema=RowsSchema.polars_schema,
    )
    coverage = CoverageInterval(
        identity, RequestedInterval(start, end), retrieved, outcome.outcome_id, (fact.facts_id,)
    )
    accumulate(
        StoreRoot(root / "ch_foen" / "store"),
        ProviderId("ch_foen"),
        StoreUpdate((definition,), (), (outcome,), (SuccessfulReplacement(coverage, rows),)),
    )
    calls = _official_replay(monkeypatch)
    selection = rr.find(
        provider="ch_foen", station="2018", quantity="discharge", frequency="10min", variant="10MinMittel"
    )
    result = rr.fetch(selection, start=start, end=end, cache="reuse", on_issue="ignore")
    assert len(calls) == 1
    assert result.data["value"].to_list() == [0.0, 10.0, 20.0, 30.0]
    assert identity not in result.data["series_id"]
    assert result.provenance.endpoints == ("https://data.bafu.admin.ch/api",)


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_adjacent_summer_calendar_requests_clip_cached_neighbor(monkeypatch):
    calls = []

    class Transport:
        def send(self, request):
            calls.append(request)
            rows = [
                {
                    "station": {"no": "2018"},
                    "parameterName": "Q",
                    "tsName": "Synthetic",
                    "unitSymbol": "m3/s",
                    "timestamp": stamp,
                    "value": value,
                    "releaseState": "3",
                }
                for stamp, value in [("2025-06-30T23:00:00Z", 10.0), ("2025-07-31T23:00:00Z", 20.0)]
            ]
            return TransportResponse(
                json.dumps({"data": {"water": {"observations": {"data_1month_mean": rows}}}}).encode(),
                200,
                datetime(2026, 1, 1, tzinfo=UTC),
                "application/json",
                request.url,
                {},
            )

    monkeypatch.setattr(discovery, "HttpClient", Transport)
    selection = rr.find(
        provider="ch_foen",
        station="2018",
        quantity="discharge",
        frequency="monthly",
        statistic="mean",
        variant="Synthetic",
        on_issue="ignore",
    )
    whole = rr.fetch(selection, start="2025-07-01", end="2025-08-31", cache="refresh", on_issue="ignore")
    assert whole.data["value"].to_list() == [10.0, 20.0]
    july = rr.fetch(selection, start="2025-07-01", end="2025-07-31", cache="reuse", on_issue="ignore")
    august = rr.fetch(selection, start="2025-08-01", end="2025-08-31", cache="reuse", on_issue="ignore")
    assert len(calls) == 1
    import re

    # Acquisition padding must contain the fixed-UTC+1 calendar interval.
    bounds = re.findall(r'_(?:gte|lt): "([^"]+)"', json.loads(calls[0].body)["query"])
    assert datetime.fromisoformat(bounds[0]) <= datetime(2025, 6, 30, 23, tzinfo=UTC)
    assert datetime.fromisoformat(bounds[1]) >= datetime(2025, 8, 31, 23, tzinfo=UTC)
    assert july.data.select("time", "value").rows() == [(datetime(2025, 6, 30, 23), 10.0)]
    assert august.data.select("time", "value").rows() == [(datetime(2025, 7, 31, 23), 20.0)]
    assert july.provenance.retrieved_at == august.provenance.retrieved_at == whole.provenance.retrieved_at

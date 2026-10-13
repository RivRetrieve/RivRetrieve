"""Authored long-window controls, not evidence of a publisher request limit."""

import json
from datetime import UTC, datetime

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
from rivretrieve._internal import discovery
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


class ChunkTransport:
    def __init__(self, *, fail_second=False):
        self.calls = []
        self.fail_second = fail_second

    def send(self, request):
        params = dict(request.params)
        start = params["hydro_series[startAt]"]
        end = params["hydro_series[endAt]"]
        variant = params["hydro_series[statusData]"]
        self.calls.append((start, end, variant))
        if self.fail_second and start == "25/09/2022":
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=503)
        # Sparse source rows straddle the chunk boundary; padding must be clipped.
        samples = [
            ("2019-12-30T00:00:00Z", 9000),
            ("2020-01-01T00:00:00Z", 1000),
            ("2022-09-24T23:59:59Z", 2000),
            ("2022-09-25T00:00:00Z", 3000),
            ("2022-09-26T12:00:00Z", None),
            ("2023-01-03T00:00:00Z", 9000),
        ]
        first = datetime.strptime(start, "%d/%m/%Y").date()
        last = datetime.strptime(end, "%d/%m/%Y").date()
        metric = params["hydro_series[simpleAndInterpolatedAndHourlyVariable]"]
        body = {
            "series": {
                "code": "Y251002001",
                "metric": metric,
                "statuses": variant,
                "unit": "l" if metric == "Q" else "mm",
                "title": "Débit instantané" if metric == "Q" else "Hauteur instantanée",
                "data": [
                    {"t": time, "v": value, "s": 4, "q": 0, "m": 0, "c": 0}
                    for time, value in samples
                    if first <= datetime.fromisoformat(time).date() <= last
                ],
            },
            "timezone": "UTC",
        }
        return TransportResponse(
            json.dumps(body).encode(),
            200,
            datetime(2026, 10, 13, tzinfo=UTC),
            "application/json",
            request.url,
            params,
        )


def install(monkeypatch, tmp_path, transport, quantity):
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    return rr.pick(
        rr.find(provider="fr_hydroportail", station="Y251002001", quantity=quantity, statistic="instantaneous"),
        variant="validated",
    )


def retrieve(selection, **kwargs):
    return rr.fetch(selection, start="2020-01-01", end="2023-01-01", cache="reuse", on_issue="ignore", **kwargs)


@pytest.mark.parametrize("quantity", ["discharge", "stage"])
def test_public_long_window_assembles_chunk_edges_and_reuses_coverage(monkeypatch, tmp_path, quantity):
    transport = ChunkTransport()
    selection = install(monkeypatch, tmp_path, transport, quantity)
    result = retrieve(selection)
    assert transport.calls == [
        ("30/12/2019", "24/09/2022", "validated"),
        ("25/09/2022", "03/01/2023", "validated"),
    ]
    expected = pl.DataFrame(
        {
            "time": [
                datetime(2020, 1, 1),
                datetime(2022, 9, 24, 23, 59, 59),
                datetime(2022, 9, 25),
                datetime(2022, 9, 26, 12),
            ],
            "value": [1.0, 2.0, 3.0, None],
        }
    )
    assert_frame_equal(result.data.select("time", "value").sort("time"), expected)
    assert rr.series(result)["variant"].to_list() == ["validated"]
    assert result.data["time_zone"].unique().to_list() == ["+00:00"]
    cached = retrieve(selection)
    assert len(transport.calls) == 2
    assert_frame_equal(cached.data, result.data)


def test_failed_chunk_keeps_successful_rows_and_does_not_cover_failed_interval(monkeypatch, tmp_path):
    transport = ChunkTransport(fail_second=True)
    selection = install(monkeypatch, tmp_path, transport, "discharge")
    result = retrieve(selection)
    assert_frame_equal(
        result.data.select("time", "value").sort("time"),
        pl.DataFrame(
            {
                "time": [datetime(2020, 1, 1), datetime(2022, 9, 24, 23, 59, 59)],
                "value": [1.0, 2.0],
            }
        ),
    )
    failed = [outcome for outcome in result.outcomes if outcome.status == "failed"]
    assert len(failed) == 1
    assert failed[0].series_id == selection.series[0].series_id
    assert failed[0].window.start == datetime(2022, 9, 25)
    assert failed[0].window.end == datetime(2023, 1, 1, 23, 59, 59, 999999)
    assert failed[0].reason
    calls = len(transport.calls)
    rr.fetch(selection, start="2020-01-01", end="2022-09-22", cache="reuse", on_issue="ignore")
    assert len(transport.calls) == calls
    repeated = retrieve(selection)
    assert len(transport.calls) > calls
    assert_frame_equal(repeated.data, result.data)
    transport.fail_second = False
    recovered = retrieve(selection)
    assert recovered.data.height == 4
    calls = len(transport.calls)
    retrieve(selection)
    assert len(transport.calls) == calls

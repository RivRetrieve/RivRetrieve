"""Synthetic request and isolation controls, not source-completeness evidence."""

import json
from datetime import UTC, datetime

import pytest

from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
from rivretrieve._internal.providers.pe_senamhi.fetch import SenamhiSourceCoordinates, fetch, window_declaration
from rivretrieve._internal.transport import TransportResponse
from rivretrieve._internal.window_planning import plan_windows


def window(start, end):
    return _make_fetch_window(
        WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
        WindowEndpoint.from_datetime(datetime.fromisoformat(end)),
    )


class Transport:
    def __init__(self, bodies):
        self.bodies = iter(bodies)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        body = next(self.bodies)
        return TransportResponse(
            content=body,
            status_code=200,
            retrieved_at=datetime(2026, 11, 1, tzinfo=UTC),
            content_type="application/json",
            url=request.url,
            request_parameters=request.params,
        )


def body(resolution="HOURLY", rows=None):
    return json.dumps(
        {
            "status": True,
            "data": {
                "station": {"code": "A"},
                "type": resolution,
                "variable": "FLOW",
                "unit": "m3/s",
                "hourly": rows or [],
                "daily": [],
            },
        }
    ).encode()


def acquire(coordinates, start, end, bodies):
    windows = {
        product: plan_windows(window(start, end), window_declaration(route)) for product, route in coordinates.items()
    }
    transport = Transport(bodies)
    result = fetch(("A",), coordinates, windows, transport)
    return result, transport, windows


def test_hourly_requests_keep_original_overlapping_bytes_and_disjoint_ownership():
    route = SenamhiSourceCoordinates("phisis", "HOURLY", "FLOW", "m3/s")
    original = body(rows=[{"time": "2024-08-30T06:00:00", "value": None}])
    result, transport, windows = acquire(
        {"phisis_hourly_flow": route}, "2024-08-30", "2024-09-02T23:59:59", [original, original]
    )
    assert [dict(request.params) for request in transport.requests] == [
        {"type": "HOURLY", "variable": "FLOW", "date": "2024-08-31T23:59:59"},
        {"type": "HOURLY", "variable": "FLOW", "date": "2024-09-02T23:59:59"},
    ]
    assert all(request.url.endswith("/hydrology/stations/A/hydrogram") for request in transport.requests)
    assert [payload.fetch_window for payload in result.value] == [item.bounds for item in windows["phisis_hourly_flow"]]
    assert [payload.content for payload in result.value] == [original, original]
    assert result.value[0].fetch_window.end < result.value[1].fetch_window.start
    assert result.value[0].origin.request_parameters == transport.requests[0].params
    assert not result.failed_requests and not result.outcomes


def test_daily_requests_each_hydrological_year_despite_successful_empty_answer():
    route = SenamhiSourceCoordinates("phisis", "DAILY", "FLOW", "m3/s")
    result, transport, _ = acquire({"phisis_daily_flow": route}, "2023-08-31", "2024-09-01", [body("DAILY")] * 3)
    assert [request.params["date"] for request in transport.requests] == [
        "2023-08-31T23:59",
        "2024-08-31T23:59",
        "2025-08-31T23:59",
    ]
    assert len(result.value) == 3


def test_monthly_coproducts_share_each_request_without_period_list():
    products = {
        "monthly_archive_n_nivelagua": SenamhiSourceCoordinates("monthly_archive", None, "N_NIVELAGUA", "m"),
        "monthly_archive_n_nivelmedio": SenamhiSourceCoordinates("monthly_archive", None, "N_NIVELMEDIO", "m"),
    }
    original = b'{"status":true,"data":{"columns":[],"readings":[]}}'
    result, transport, _ = acquire(products, "2026-11-30", "2027-01-01", [original] * 3)
    assert [dict(request.params) for request in transport.requests] == [
        {"period": "202611"},
        {"period": "202612"},
        {"period": "202701"},
    ]
    assert all(request.url.endswith("/station/stations/A/readings") for request in transport.requests)
    assert all(set(payload.station_products) == {("A", product) for product in products} for payload in result.value)
    assert all(payload.content == original for payload in result.value)


@pytest.mark.parametrize("failure", ["http", "envelope", "malformed", "shape"])
def test_failed_middle_window_retains_identity_reason_and_siblings(failure):
    from rivretrieve._internal.source_acquisition import SourceResponseMeaning
    from rivretrieve._internal.transport import TransportFailure, TransportFailureReason

    route = SenamhiSourceCoordinates("phisis", "DAILY", "FLOW", "m3/s")
    failed_body = {
        "envelope": b'{"status":false,"message":"source refusal","data":null}',
        "malformed": b"not JSON",
        "shape": b'{"status":true,"data":null}',
    }
    original = body("DAILY")
    transport = Transport([original, failed_body.get(failure, original), original])
    send = transport.send

    def failing_send(request):
        response = send(request)
        if failure == "http" and len(transport.requests) == 2:
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=422, response=response)
        return response

    transport.send = failing_send
    bounds = plan_windows(window("2023-08-31", "2024-09-01"), window_declaration(route))
    result = fetch(("A",), {"phisis_daily_flow": route}, {"phisis_daily_flow": bounds}, transport)
    assert len(transport.requests) == 3
    if failure == "http":
        assert len(result.value) == 2
        assert len(result.failed_requests) == 3
        assert {item.meaning for item in result.failed_requests} == {SourceResponseMeaning.UNSPECIFIED}
        assert {item.series.identity.published_id for item in result.failed_requests} == {
            "current",
            "minimum",
            "maximum",
        }
        assert all(item.failure.status_code == 422 for item in result.failed_requests)
        intervals = [item.window for item in result.failed_requests]
    else:
        assert len(result.value) == 3  # Failed response bytes remain available as evidence.
        assert result.value[1].content == failed_body[failure]
        assert len(result.outcomes) == 3
        assert {item.series_id for item in result.outcomes} <= {item.series_id for item in result.series}
        assert all(item.status.value == "failed" and item.reason for item in result.outcomes)
        assert all(item.calls == (result.value[1].acquisition_id,) for item in result.outcomes)
        assert len(result.issues) == 3
        intervals = [item.window for item in result.outcomes]
    assert all(
        item.start == datetime(2023, 9, 1) and item.end == datetime(2024, 8, 31, 23, 59, 59, 999999)
        for item in intervals
    )


@pytest.mark.parametrize("damage", ["station", "product", "rows"])
def test_unrelated_or_malformed_response_is_not_a_successful_empty(damage):
    document = json.loads(body())
    if damage == "station":
        document["data"]["station"]["code"] = "B"
    elif damage == "product":
        document["data"]["variable"] = "LEVEL"
    else:
        document["data"]["hourly"] = [None]
    result, _, _ = acquire(
        {"phisis_hourly_flow": SenamhiSourceCoordinates("phisis", "HOURLY", "FLOW", "m3/s")},
        "2024-01-01",
        "2024-01-02",
        [json.dumps(document).encode()],
    )
    assert len(result.outcomes) == 1
    assert result.outcomes[0].status.value == "failed"


def test_invalid_internal_window_raises_before_network():
    from rivretrieve._internal.engine import RenderedWindow
    from rivretrieve._internal.issues import FatalContractError

    transport = Transport([])
    with pytest.raises(FatalContractError, match="bounds"):
        fetch(
            ("A",),
            {"p": SenamhiSourceCoordinates("phisis", "HOURLY", "FLOW", "m3/s")},
            {"p": (RenderedWindow("2024-01-01", "2024-01-02"),)},
            transport,
        )
    assert transport.requests == []


def test_published_null_rows_are_preserved_without_claiming_empty():
    original = body("DAILY", [{"date": "2024-02-29", "current": None, "minimum": None, "maximum": None}])
    document = json.loads(original)
    document["data"]["daily"] = document["data"].pop("hourly")
    original = json.dumps(document).encode()
    result, _, _ = acquire(
        {"phisis_daily_flow": SenamhiSourceCoordinates("phisis", "DAILY", "FLOW", "m3/s")},
        "2024-02-29",
        "2024-02-29",
        [original],
    )
    assert result.value[0].content == original
    assert not result.outcomes and not result.failed_requests

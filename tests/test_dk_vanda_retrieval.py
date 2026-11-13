"""Synthetic request shape and parser behavior, not source-completeness evidence."""

import json
from datetime import UTC, datetime

import pytest

from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
from rivretrieve._internal.providers.dk_vanda.config import config, window_declarations
from rivretrieve._internal.providers.dk_vanda.fetch import fetch
from rivretrieve._internal.providers.dk_vanda.parse import parse
from rivretrieve._internal.transport import TransportFailure, TransportFailureReason, TransportResponse
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
            retrieved_at=datetime(2026, 11, 10, tzinfo=UTC),
            content_type="application/json",
            url=request.url,
            request_parameters=request.params,
        )


class FailingTransport:
    def __init__(self, body, status):
        self.body = body
        self.status = status
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        response = TransportResponse(
            content=self.body,
            status_code=self.status,
            retrieved_at=datetime(2026, 11, 10, tzinfo=UTC),
            content_type="application/json",
            url=request.url,
            request_parameters=request.params,
        )
        raise TransportFailure(
            request, TransportFailureReason.HTTP_STATUS, 1, status_code=self.status, response=response
        )


def _acquire(station, product, body):
    cfg = config()
    decls = window_declarations()
    fw = window("2020-01-01", "2020-01-02")
    rendered = {product: plan_windows(fw, decls.products[product])}
    transport = Transport([body])
    result = fetch((station,), (product,), rendered, fw, cfg, transport)
    assert len(result.value) == 1
    return result.value[0], transport, cfg


def _result_row(sc, measurement_date_time, result, *, result_elevation_corrected=None, reason_sc=None, reason=None):
    return {
        "measurementPointNumber": 1,
        "parameterSc": 1233,
        "parameter": "x",
        "examinationTypeSc": sc,
        "examinationType": "x",
        "measurementDateTime": measurement_date_time,
        "depthM": None,
        "result": result,
        "resultElevationCorrected": result_elevation_corrected,
        "unitSc": 19,
        "unit": "x",
        "reasonSc": reason_sc,
        "reason": reason,
    }


def _envelope(station, rows):
    return json.dumps([{"stationId": station, "operatorStationId": "", "results": rows}]).encode()


def test_discharge_request_shape_and_success():
    body = _envelope("19000467", [_result_row(27, "2020-01-01T00:00:00.00Z", 123.4)])
    payload, transport, cfg = _acquire("19000467", "discharge", body)
    request = transport.requests[0]
    assert request.url == "https://vandah.miljoeportal.dk/api/water-flows"
    assert dict(request.params) == {
        "stationId": "19000467",
        "from": "2020-01-01T00:00:00Z",
        "to": "2020-01-02T00:00:00Z",
    }
    parsed = parse(payload, cfg)
    assert parsed.rows.to_dicts() == [
        {
            "station_id": "19000467",
            "product_id": "discharge",
            "time": datetime(2020, 1, 1),
            "value": 123.4,
            "time_zone": "+00:00",
            "series_id": parsed.series[0].series_id,
            "facts_id": parsed.series[0].facts[0].facts_id,
            "source_unit": "l/s",
        }
    ]
    assert [o.status.value for o in parsed.outcomes] == ["success"]
    assert not parsed.issues


def test_stage_request_shape_has_no_examination_type_sc_param():
    body = _envelope("19000468", [])
    _, transport, _ = _acquire("19000468", "stage", body)
    request = transport.requests[0]
    assert request.url == "https://vandah.miljoeportal.dk/api/water-levels"
    assert "examinationTypeSc" not in request.params


def test_temperature_request_adds_examination_type_sc():
    body = _envelope("70000277", [])
    _, transport, _ = _acquire("70000277", "temperature", body)
    request = transport.requests[0]
    assert request.url == "https://vandah.miljoeportal.dk/api/measurements/results/current"
    assert dict(request.params) == {
        "stationId": "70000277",
        "from": "2020-01-01T00:00:00Z",
        "to": "2020-01-02T00:00:00Z",
        "examinationTypeSc": 29,
    }


def test_stage_admits_both_fields_as_distinct_series_from_one_response():
    body = _envelope(
        "19000468",
        [_result_row(25, "2020-01-01T00:00:00.00Z", 24.3, result_elevation_corrected=82.0)],
    )
    payload, _, cfg = _acquire("19000468", "stage", body)
    parsed = parse(payload, cfg)
    assert {series.identity.published_id for series in parsed.series} == {"result", "resultElevationCorrected"}
    assert len(parsed.series) == 2
    by_field = {
        series.identity.published_id: [row for row in parsed.rows.to_dicts() if row["series_id"] == series.series_id]
        for series in parsed.series
    }
    assert by_field["result"][0]["value"] == 24.3
    assert by_field["resultElevationCorrected"][0]["value"] == 82.0
    assert [o.status.value for o in parsed.outcomes] == ["success", "success"]


def test_stage_null_result_elevation_corrected_is_preserved_as_none_not_coerced():
    body = _envelope(
        "19000468",
        [_result_row(25, "2020-01-01T00:00:00.00Z", 24.3, result_elevation_corrected=None)],
    )
    payload, _, cfg = _acquire("19000468", "stage", body)
    parsed = parse(payload, cfg)
    rows_by_field = {
        series.identity.published_id: parsed.rows.filter(parsed.rows["series_id"] == series.series_id).to_dicts()
        for series in parsed.series
    }
    assert rows_by_field["result"][0]["value"] == 24.3
    assert rows_by_field["resultElevationCorrected"][0]["value"] is None


def test_temperature_reason_flag_becomes_info_issue_but_stage_never_does():
    body = _envelope(
        "70000277",
        [_result_row(29, "2020-01-01T00:00:00.00Z", 5.2, reason_sc=3, reason="Is i vandløb")],
    )
    payload, _, cfg = _acquire("70000277", "temperature", body)
    parsed = parse(payload, cfg)
    assert len(parsed.issues) == 1
    assert parsed.issues[0].severity == "info"
    assert parsed.issues[0].code == "source.reason_flag"
    assert parsed.issues[0].details["source_reason_sc"] == 3
    assert parsed.issues[0].details["source_reason"] == "Is i vandløb"

    # /water-levels never carries reasonSc/reason at all (step 4 research finding);
    # even a row shaped with those keys set produces no Issue when parsed as stage,
    # since the real endpoint never actually serves them -- this just proves the
    # helper is correctly inert for the water-levels shape, not that the keys are read.
    stage_body = _envelope(
        "19000468", [_result_row(25, "2020-01-01T00:00:00.00Z", 24.3, reason_sc=3, reason="Is i vandløb")]
    )
    stage_payload, _, stage_cfg = _acquire("19000468", "stage", stage_body)
    stage_parsed = parse(stage_payload, stage_cfg)
    assert not stage_parsed.issues


def test_examination_type_mismatch_marks_unsupported_not_a_crash():
    body = _envelope("19000467", [_result_row(25, "2020-01-01T00:00:00.00Z", 1.0)])  # sc 25, not 27
    payload, _, cfg = _acquire("19000467", "discharge", body)
    parsed = parse(payload, cfg)
    assert parsed.rows.is_empty()
    assert [o.status.value for o in parsed.outcomes] == ["unsupported"]
    assert parsed.issues[0].code == "unsupported_source_structure"


def test_stage_multiple_measurement_point_entries_marks_failed_without_crashing():
    body = json.dumps(
        [
            {"stationId": "19000468", "operatorStationId": "", "results": []},
            {"stationId": "19000468", "operatorStationId": "", "results": []},
        ]
    ).encode()
    payload, _, cfg = _acquire("19000468", "stage", body)
    parsed = parse(payload, cfg)
    assert parsed.series == ()
    assert [o.status.value for o in parsed.outcomes] == ["failed"]
    assert parsed.outcomes[0].series_id is None
    assert parsed.issues[0].severity == "error"
    assert parsed.issues[0].code == "source.unsupported_structure"


def test_empty_response_is_empty_outcome_not_crash_for_discharge_and_stage():
    empty_body = b"[]"
    discharge_payload, _, cfg = _acquire("19000467", "discharge", empty_body)
    discharge_parsed = parse(discharge_payload, cfg)
    assert discharge_parsed.rows.is_empty()
    assert [o.status.value for o in discharge_parsed.outcomes] == ["empty"]

    stage_payload, _, stage_cfg = _acquire("19000468", "stage", empty_body)
    stage_parsed = parse(stage_payload, stage_cfg)
    assert stage_parsed.rows.is_empty()
    assert [o.status.value for o in stage_parsed.outcomes] == ["empty", "empty"]


def test_more_than_one_result_per_timestamp_is_preserved_not_deduped():
    """Defensive multi-version tolerance (research/dk-vanda-source-access.md): a
    future doubling must be preserved as two rows, never silently collapsed."""
    rows = [
        _result_row(27, "2020-01-01T00:00:00.00Z", 1.0),
        _result_row(27, "2020-01-01T00:00:00.00Z", 2.0),
    ]
    body = _envelope("19000467", rows)
    payload, _, cfg = _acquire("19000467", "discharge", body)
    parsed = parse(payload, cfg)
    assert sorted(row["value"] for row in parsed.rows.to_dicts()) == [1.0, 2.0]


def test_invalid_station_failure_is_not_mapped_to_no_observations_meaning():
    cfg = config()
    decls = window_declarations()
    fw = window("2020-01-01", "2020-01-02")
    rendered = {"discharge": plan_windows(fw, decls.products["discharge"])}
    body = b'{"statusCode":400,"message":"Cannot find station with either id \'00000000\' or operator station id \'\'"}'
    transport = FailingTransport(body, 400)
    result = fetch(("00000000",), ("discharge",), rendered, fw, cfg, transport)
    assert not result.value
    assert len(result.failed_requests) == 1
    failure = result.failed_requests[0]
    assert failure.failure.status_code == 400
    # A 400 means the station identity could not be resolved, never "this window has
    # no observations"; no SourceResponseMeaning mapping is supplied in fetch.py.
    assert failure.meaning.value == "unspecified"


def test_window_rendering_uses_inclusive_iso_instant_bounds_with_seconds():
    decls = window_declarations()
    for product in ("discharge", "stage", "temperature"):
        rendered = plan_windows(window("2020-01-01", "2020-01-02"), decls.products[product])
        assert len(rendered) == 1
        assert rendered[0].start == "2020-01-01T00:00:00Z"
        assert rendered[0].stop == "2020-01-02T00:00:00Z"


@pytest.mark.parametrize(
    "product,endpoint,expected_status",
    [("discharge", "water-flows", "unsupported"), ("stage", "water-levels", "failed")],
)
def test_response_station_id_mismatch_is_rejected_not_silently_accepted(product, endpoint, expected_status):
    body = json.dumps([{"stationId": "wrong-station", "operatorStationId": "", "results": []}]).encode()
    station = "19000467" if product == "discharge" else "19000468"
    payload, transport, cfg = _acquire(station, product, body)
    assert transport.requests[0].url.endswith(endpoint)
    parsed = parse(payload, cfg)
    assert parsed.rows.is_empty()
    assert [o.status.value for o in parsed.outcomes] == [expected_status]

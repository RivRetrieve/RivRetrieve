"""Public replay of retained Australia BoM KiWIS HTTP captures through find/pick/fetch."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse

_SCOPE = "maintenance/observations/au_bom/retrieval"
_GROUP = "verification"

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _load_capture(root: Path, name: str) -> tuple[bytes, dict[str, object]]:
    base = root / _SCOPE / _GROUP / name
    return base.with_suffix(".body").read_bytes(), json.loads(base.with_suffix(".receipt.json").read_bytes())


def _response_matching_request(root: Path, name: str, request: TransportRequest) -> TransportResponse:
    content, receipt = _load_capture(root, name)
    source = urlsplit(str(receipt["url"]))
    expected_params = {key: vals[0] for key, vals in parse_qs(source.query, keep_blank_values=True).items()}
    requested = urlsplit(request.url)
    assert (requested.scheme, requested.netloc, requested.path) == (source.scheme, source.netloc, source.path)
    assert dict(request.params or {}) == expected_params
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    retrieved_at = datetime.fromisoformat(str(receipt["acquired_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=content,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=retrieved_at,
        content_type=str(content_type) if content_type is not None else None,
        url=f"{source.scheme}://{source.netloc}{source.path}",
        request_parameters=expected_params,
    )


def _synthetic_empty_values(request: TransportRequest) -> TransportResponse:
    """A values response for a sibling product not under test in this call.

    Several of au_bom's stations carry both a `24HR` and a `09HR` daily-mean
    series for the same quantity (#647's documented selection ambiguity): a
    physical-predicate selection for one necessarily also matches the other,
    so a public `rr.fetch` call here genuinely requests both. This is not a
    retained capture -- it synthesizes an empty response for whichever `ts_id`
    isn't the one this test genuinely retained and is actually exercising.
    """
    params = request.params or {}
    ts_ids = str(params.get("ts_id", "")).split(",")
    body = json.dumps(
        [{"ts_id": ts_id, "rows": "0", "columns": "Timestamp,Value,Quality Code,Quality Code Name", "data": []} for ts_id in ts_ids]
    ).encode("utf-8")
    return TransportResponse(body, 200, datetime(2026, 11, 4, tzinfo=UTC), "application/json", request.url, dict(params))


def _select_stage_daily_mean(station: str) -> rr.Selection:
    return rr.find(provider="au_bom", station=station, quantity="stage", frequency="daily", statistic="mean")


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_station_410730_stage_success(retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Replay:
        def send(self, request: TransportRequest) -> TransportResponse:
            if (request.params or {}).get("request") == "getTimeseriesList":
                return _response_matching_request(retained_evidence_root, "timeserieslist-410730", request)
            return _response_matching_request(
                retained_evidence_root, "timeseriesvalues-410730-stage-24hr-success", request
            )

    monkeypatch.setattr(discovery, "HttpClient", _Replay)
    selection = _select_stage_daily_mean("410730")
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-10", cache="bypass")

    raw, _ = _load_capture(retained_evidence_root, "timeseriesvalues-410730-stage-24hr-success")
    clipped = [row for row in json.loads(raw)[0]["data"] if "2026-09-01" <= row[0][:10] <= "2026-09-10"]
    assert result.data.height == len(clipped) == 10
    assert result.data["unit"].unique().to_list() == ["m"]
    assert sorted(result.data["value"].to_list()) == pytest.approx(sorted(row[1] for row in clipped))
    assert not any(issue.code == "source.quality_code" for issue in result.issues)


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_station_410730_discharge_quality_e_issue(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Replay:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = request.params or {}
            if params.get("request") == "getTimeseriesList":
                return _response_matching_request(retained_evidence_root, "timeserieslist-410730", request)
            if str(params.get("ts_id")) == "1573010":
                return _response_matching_request(
                    retained_evidence_root, "timeseriesvalues-410730-discharge-24hr-quality-e", request
                )
            return _synthetic_empty_values(request)  # the 09HR sibling, not under test here

    monkeypatch.setattr(discovery, "HttpClient", _Replay)
    selection = rr.find(provider="au_bom", station="410730", quantity="discharge", frequency="daily", statistic="mean")
    result = rr.fetch(selection, start="2026-10-20", end="2026-10-27", cache="bypass", on_issue="ignore")

    discharge_rows = result.data.filter(result.data["product_id"] == "discharge_daily_mean_24hr")
    assert discharge_rows.height == 8
    assert discharge_rows["unit"].unique().to_list() == ["m3/s"]
    # Issues are emitted per source row from the engine's wider padded-window
    # response (11 rows), not the window the caller actually requested (8 rows).
    quality_issues = [issue for issue in result.issues if issue.code == "source.quality_code"]
    assert len(quality_issues) == 11
    assert all(issue.severity == "info" for issue in quality_issues)


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_station_138020a_duplicate_ts_id_split_with_published_nulls(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Replay:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = request.params or {}
            if params.get("request") == "getTimeseriesList":
                return _response_matching_request(retained_evidence_root, "timeserieslist-138020a", request)
            if str(params.get("ts_id")) == "470345010,381776010":
                return _response_matching_request(
                    retained_evidence_root, "timeseriesvalues-138020a-discharge-24hr-duplicate-nulls", request
                )
            return _synthetic_empty_values(request)  # the 09HR sibling pair, not under test here

    monkeypatch.setattr(discovery, "HttpClient", _Replay)
    selection = rr.find(
        provider="au_bom", station="138020A", quantity="discharge", frequency="daily", statistic="mean"
    )
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-10", cache="bypass", on_issue="ignore")

    statuses = {outcome.status for outcome in result.outcomes}
    assert OutcomeStatus.SUCCESS in statuses
    assert OutcomeStatus.EMPTY in statuses

    live = result.data.filter(result.data["product_id"] == "discharge_daily_mean_24hr").sort("time")
    assert live.height == 10
    null_rows = live.filter(live["value"].is_null())
    assert null_rows.height == 3


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_station_138020a_reports_no_match_for_water_temperature(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Replay:
        def send(self, request: TransportRequest) -> TransportResponse:
            return _response_matching_request(retained_evidence_root, "timeserieslist-138020a", request)

    monkeypatch.setattr(discovery, "HttpClient", _Replay)
    selection = rr.find(provider="au_bom", station="138020A", quantity="temperature")
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-10", cache="bypass", on_issue="ignore")

    assert result.data.is_empty()
    assert any(outcome.status is OutcomeStatus.NO_MATCH for outcome in result.outcomes)


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_future_window_is_empty_not_an_error(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Replay:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = request.params or {}
            if params.get("request") == "getTimeseriesList":
                return _response_matching_request(retained_evidence_root, "timeserieslist-410730", request)
            if str(params.get("ts_id")) == "1573010":
                return _response_matching_request(
                    retained_evidence_root, "timeseriesvalues-410730-discharge-24hr-future-empty", request
                )
            return _synthetic_empty_values(request)  # the 09HR sibling, not under test here

    monkeypatch.setattr(discovery, "HttpClient", _Replay)
    selection = rr.find(provider="au_bom", station="410730", quantity="discharge", frequency="daily", statistic="mean")
    result = rr.fetch(selection, start="2027-01-01", end="2027-01-05", cache="bypass", on_issue="ignore")

    outcomes_24hr = [o for o in result.outcomes if o.product_id == "discharge_daily_mean_24hr"]
    assert outcomes_24hr and all(o.status is OutcomeStatus.EMPTY for o in outcomes_24hr)
    assert not any(issue.severity == "error" for issue in result.issues)


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_values_call_transport_failure_reports_an_error_issue(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay the genuine HTTP 500 InvalidParameterValue body for a values call.

    No real BoM station resolves a product to ts_id "1"; the list response
    routing this product to that ts_id is a synthetic test fixture (clearly
    not a retained capture), used only to exercise the genuinely retained
    failure body end to end through the public surface.
    """
    from rivretrieve._internal.transport import TransportFailure, TransportFailureCategory, TransportFailureReason

    synthetic_list = json.dumps(
        [
            ["ts_id", "ts_name", "parametertype_name", "ts_unitsymbol", "station_no"],
            ["1", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec", "410730"],
        ]
    ).encode("utf-8")

    class _Replay:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = request.params or {}
            if params.get("request") == "getTimeseriesList":
                return TransportResponse(
                    synthetic_list, 200, datetime(2026, 11, 4, tzinfo=UTC), "application/json", request.url, dict(params)
                )
            _, receipt = _load_capture(retained_evidence_root, "timeseriesvalues-invalid-ts-id")
            if receipt.get("http_status") == 500:
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=500,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            raise AssertionError("expected the retained failure receipt to carry http_status 500")

    monkeypatch.setattr(discovery, "HttpClient", _Replay)
    selection = rr.find(provider="au_bom", station="410730", quantity="discharge", frequency="daily", statistic="mean")
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-10", cache="bypass", on_issue="ignore")

    assert result.data.is_empty()
    assert any(issue.severity == "error" for issue in result.issues)


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_camels_aus_v2_cross_check_09hr_matches_24hr_does_not(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay both admitted discharge daily-mean series at station 401203 and compare

    against the genuinely external CAMELS-AUS v2 streamflow archive (not
    retained in this repository; see research/au-bom-source-access.md on
    verification-evidence). Station 401203, 2018-06-15: CAMELS-AUS records
    1177.2 ML/day, i.e. 13.625 m3/s. BoM's 09HR series matches exactly;
    its 24HR sibling does not -- the two are different, source-meaningful
    conventions, not interchangeable approximations of the same day.
    """

    def _dispatch(request: TransportRequest) -> TransportResponse:
        params = request.params or {}
        if params.get("request") == "getTimeseriesList":
            return _response_matching_request(retained_evidence_root, "timeserieslist-401203", request)
        ts_id = str(params.get("ts_id", ""))
        name = {
            "281649010": "timeseriesvalues-401203-discharge-09hr-camels-crosscheck",
            "281650010": "timeseriesvalues-401203-discharge-24hr-camels-crosscheck",
        }[ts_id]
        return _response_matching_request(retained_evidence_root, name, request)

    class _Replay:
        def send(self, request: TransportRequest) -> TransportResponse:
            return _dispatch(request)

    monkeypatch.setattr(discovery, "HttpClient", _Replay)
    selection = rr.find(provider="au_bom", station="401203", quantity="discharge", frequency="daily", statistic="mean")
    result = rr.fetch(selection, start="2018-06-13", end="2018-06-17", cache="bypass", on_issue="ignore")

    camels_m3_per_s = 1177.2 * 1000 / 86400
    rows_09hr = result.data.filter(result.data["product_id"] == "discharge_daily_mean_09hr").sort("time")
    rows_24hr = result.data.filter(result.data["product_id"] == "discharge_daily_mean_24hr").sort("time")
    value_09hr = rows_09hr.filter(rows_09hr["time"] == datetime(2018, 6, 15, 9, 0))["value"].item()
    value_24hr = rows_24hr.filter(rows_24hr["time"] == datetime(2018, 6, 15, 0, 0))["value"].item()
    assert value_09hr == pytest.approx(camels_m3_per_s, abs=1e-6)
    assert value_24hr != pytest.approx(camels_m3_per_s, abs=1e-3)
    assert value_24hr == pytest.approx(17.955, abs=1e-6)

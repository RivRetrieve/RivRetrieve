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
        [
            {"ts_id": ts_id, "rows": "0", "columns": "Timestamp,Value,Quality Code,Quality Code Name", "data": []}
            for ts_id in ts_ids
        ]
    ).encode("utf-8")
    return TransportResponse(
        body, 200, datetime(2026, 11, 4, tzinfo=UTC), "application/json", request.url, dict(params)
    )


def _select_stage_daily_mean(station: str) -> rr.Selection:
    return rr.find(provider="au_bom", station=station, quantity="stage", frequency="P1D", statistic="mean")


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_station_410730_stage_success(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Replay:
        def send(self, request: TransportRequest) -> TransportResponse:
            if (request.params or {}).get("request") == "getTimeseriesList":
                return _response_matching_request(retained_evidence_root, "timeserieslist-410730", request)
            return _response_matching_request(
                retained_evidence_root, "timeseriesvalues-410730-stage-24hr-success", request
            )

    monkeypatch.setattr(discovery, "HttpClient", _Replay)
    selection = _select_stage_daily_mean("410730")
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-10", cache="bypass", on_issue="ignore")

    raw, _ = _load_capture(retained_evidence_root, "timeseriesvalues-410730-stage-24hr-success")
    clipped = [row for row in json.loads(raw)[0]["data"] if "2026-09-01" <= row[0][:10] <= "2026-09-10"]
    assert result.data.height == len(clipped) == 10
    assert result.data["unit"].unique().to_list() == ["m"]
    # Compare each value against the capture's value for that same date, not just the sorted
    # set of values: sorting alone would miss a value silently attached to the wrong time.
    expected_by_date = {row[0][:10]: row[1] for row in clipped}
    actual_by_date = dict(
        zip(
            (t.date().isoformat() for t in result.data["time"].to_list()),
            result.data["value"].to_list(),
            strict=True,
        )
    )
    assert actual_by_date.keys() == expected_by_date.keys()
    for date_key, expected_value in expected_by_date.items():
        assert actual_by_date[date_key] == pytest.approx(expected_value)
    table = rr.annotations(result, schema="au_bom.quality")
    assert table.height == result.data.height


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_station_410730_discharge_quality_e_annotations(
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
    selection = rr.find(provider="au_bom", station="410730", quantity="discharge", frequency="P1D", statistic="mean")
    result = rr.fetch(selection, start="2026-10-20", end="2026-10-27", cache="bypass", on_issue="ignore")

    discharge_rows = result.data.filter(result.data["product_id"] == "discharge_daily_mean_24hr")
    assert discharge_rows.height == 8
    assert discharge_rows["unit"].unique().to_list() == ["m3/s"]
    # The annotation table mirrors result.data's row scope exactly, the same
    # settled convention ch_foen's releaseState/releaseStatus annotations use:
    # the engine's wider padded-window response (11 source rows) is clipped to
    # the caller's requested window before the annotation table is built, so no
    # row describes an observation the caller cannot see in result.data.
    table = rr.annotations(result, schema="au_bom.quality")
    assert table.height == discharge_rows.height == 8
    assert table["Quality_Code_Name"].to_list() == ["quality-E"] * 8


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
    selection = rr.find(provider="au_bom", station="138020A", quantity="discharge", frequency="P1D", statistic="mean")
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
    selection = rr.find(provider="au_bom", station="410730", quantity="discharge", frequency="P1D", statistic="mean")
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

    invalid_body, invalid_receipt = _load_capture(retained_evidence_root, "timeseriesvalues-invalid-ts-id")
    # The retained body is the genuine evidence this test exists to exercise, not just its
    # receipt metadata: confirm it is really BoM's documented InvalidParameterValue failure
    # before treating this capture as a faithful stand-in for a real HTTP 500 transport error.
    assert json.loads(invalid_body)["code"] == "InvalidParameterValue"
    assert invalid_receipt.get("http_status") == 500

    class _Replay:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = request.params or {}
            if params.get("request") == "getTimeseriesList":
                return TransportResponse(
                    synthetic_list,
                    200,
                    datetime(2026, 11, 4, tzinfo=UTC),
                    "application/json",
                    request.url,
                    dict(params),
                )
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=500,
                category=TransportFailureCategory.HTTP_STATUS,
            )

    monkeypatch.setattr(discovery, "HttpClient", _Replay)
    selection = rr.find(provider="au_bom", station="410730", quantity="discharge", frequency="P1D", statistic="mean")
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
    selection = rr.find(provider="au_bom", station="401203", quantity="discharge", frequency="P1D", statistic="mean")
    result = rr.fetch(selection, start="2018-06-13", end="2018-06-17", cache="bypass", on_issue="ignore")

    camels_m3_per_s = 1177.2 * 1000 / 86400
    rows_09hr = result.data.filter(result.data["product_id"] == "discharge_daily_mean_09hr").sort("time")
    rows_24hr = result.data.filter(result.data["product_id"] == "discharge_daily_mean_24hr").sort("time")
    value_09hr = rows_09hr.filter(rows_09hr["time"] == datetime(2018, 6, 15, 9, 0))["value"].item()
    value_24hr = rows_24hr.filter(rows_24hr["time"] == datetime(2018, 6, 15, 0, 0))["value"].item()
    assert value_09hr == pytest.approx(camels_m3_per_s, abs=1e-6)
    assert value_24hr != pytest.approx(camels_m3_per_s, abs=1e-3)
    assert value_24hr == pytest.approx(17.955, abs=1e-6)


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_wa_station_601001_preserves_0200_and_1100_anchors(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay genuine WA station 601001 (+08:00 AWST -> 02:00 / 11:00 under +10:00; #1082)."""

    class _Replay:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = request.params or {}
            if params.get("request") == "getTimeseriesList":
                return _response_matching_request(retained_evidence_root, "timeserieslist-601001", request)
            name = {
                "73472010": "timeseriesvalues-601001-discharge-24hr",
                "73471010": "timeseriesvalues-601001-discharge-09hr",
            }[str(params.get("ts_id"))]
            return _response_matching_request(retained_evidence_root, name, request)

    monkeypatch.setattr(discovery, "HttpClient", _Replay)
    selection = rr.find(provider="au_bom", station="601001", quantity="discharge", frequency="P1D", statistic="mean")
    result = rr.fetch(selection, start="2026-08-01", end="2026-08-05", cache="bypass", on_issue="ignore")

    rows_24hr = result.data.filter(result.data["product_id"] == "discharge_daily_mean_24hr").sort("time")
    rows_09hr = result.data.filter(result.data["product_id"] == "discharge_daily_mean_09hr").sort("time")
    assert rows_24hr.height == 5
    assert rows_09hr.height == 5
    assert all((t.hour, t.minute) == (2, 0) for t in rows_24hr["time"].to_list())
    assert all((t.hour, t.minute) == (11, 0) for t in rows_09hr["time"].to_list())
    assert result.data["time_zone"].unique().to_list() == ["+10:00"]

    label_by_ts = {s.identity.published_id: s.facts[0].label_time for s in result.source_series}
    assert label_by_ts["73472010"] == "02:00"
    assert label_by_ts["73471010"] == "11:00"


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_sa_station_a5131021_supports_different_anchors_on_same_station(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay genuine SA station A5131021: discharge at 00:00+10:00 and temperature at 00:30+10:00 (#1082)."""

    class _Replay:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = request.params or {}
            if params.get("request") == "getTimeseriesList":
                return _response_matching_request(retained_evidence_root, "timeserieslist-a5131021", request)
            ts_id = str(params.get("ts_id", ""))
            if ts_id == "227552010":
                return _response_matching_request(
                    retained_evidence_root, "timeseriesvalues-a5131021-temperature-24hr", request
                )
            if ts_id == "485390010":
                return _response_matching_request(
                    retained_evidence_root, "timeseriesvalues-a5131021-discharge-24hr", request
                )
            return _synthetic_empty_values(request)

    monkeypatch.setattr(discovery, "HttpClient", _Replay)
    temp_sel = rr.find(provider="au_bom", station="A5131021", quantity="temperature", frequency="P1D", statistic="mean")
    temp_res = rr.fetch(temp_sel, start="2026-08-01", end="2026-08-05", cache="bypass", on_issue="ignore")
    assert temp_res.data.height == 5
    assert all((t.hour, t.minute) == (0, 30) for t in temp_res.data["time"].to_list())
    assert [s.facts[0].label_time for s in temp_res.source_series if s.identity.published_id == "227552010"] == [
        "00:30"
    ]

    disch_sel = rr.find(provider="au_bom", station="A5131021", quantity="discharge", frequency="P1D", statistic="mean")
    disch_res = rr.fetch(disch_sel, start="2026-08-01", end="2026-08-05", cache="bypass", on_issue="ignore")
    disch_rows = disch_res.data.filter(disch_res.data["product_id"] == "discharge_daily_mean_24hr")
    assert disch_rows.height == 5
    assert all((t.hour, t.minute) == (0, 0) for t in disch_rows["time"].to_list())
    assert [s.facts[0].label_time for s in disch_res.source_series if s.identity.published_id == "485390010"] == [
        "00:00"
    ]


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_nt_station_g8100106_and_wa_gmt_station_802009(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay genuine NT G8100106 (00:30/09:30) and WA 802009 (02:00 on right calendar date; #1082)."""

    class _ReplayNT:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = request.params or {}
            if params.get("request") == "getTimeseriesList":
                return _response_matching_request(retained_evidence_root, "timeserieslist-g8100106", request)
            name = {
                "52074010": "timeseriesvalues-g8100106-discharge-24hr",
                "52073010": "timeseriesvalues-g8100106-discharge-09hr",
            }[str(params.get("ts_id"))]
            return _response_matching_request(retained_evidence_root, name, request)

    monkeypatch.setattr(discovery, "HttpClient", _ReplayNT)
    nt_sel = rr.find(provider="au_bom", station="G8100106", quantity="discharge", frequency="P1D", statistic="mean")
    nt_res = rr.fetch(nt_sel, start="2026-08-01", end="2026-08-05", cache="bypass", on_issue="ignore")
    nt_24 = nt_res.data.filter(nt_res.data["product_id"] == "discharge_daily_mean_24hr")
    nt_09 = nt_res.data.filter(nt_res.data["product_id"] == "discharge_daily_mean_09hr")
    assert nt_24.height == 5 and all((t.hour, t.minute) == (0, 30) for t in nt_24["time"].to_list())
    assert nt_09.height == 5 and all((t.hour, t.minute) == (9, 30) for t in nt_09["time"].to_list())
    nt_labels = {s.identity.published_id: s.facts[0].label_time for s in nt_res.source_series}
    assert nt_labels["52074010"] == "00:30"
    assert nt_labels["52073010"] == "09:30"

    class _ReplayWA802009:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = request.params or {}
            if params.get("request") == "getTimeseriesList":
                return _response_matching_request(retained_evidence_root, "timeserieslist-802009", request)
            if str(params.get("ts_id")) == "763266010":
                return _response_matching_request(
                    retained_evidence_root, "timeseriesvalues-802009-discharge-24hr", request
                )
            return _synthetic_empty_values(request)

    monkeypatch.setattr(discovery, "HttpClient", _ReplayWA802009)
    wa_sel = rr.find(provider="au_bom", station="802009", quantity="discharge", frequency="P1D", statistic="mean")
    wa_res = rr.fetch(wa_sel, start="2024-03-01", end="2024-03-05", cache="bypass", on_issue="ignore")
    wa_24 = wa_res.data.filter(wa_res.data["product_id"] == "discharge_daily_mean_24hr").sort("time")
    assert wa_24.height == 5
    assert [t.date().isoformat() for t in wa_24["time"].to_list()] == [
        "2024-03-01",
        "2024-03-02",
        "2024-03-03",
        "2024-03-04",
        "2024-03-05",
    ]
    assert all((t.hour, t.minute) == (2, 0) for t in wa_24["time"].to_list())
    assert wa_24.filter(wa_24["time"] == datetime(2024, 3, 3, 2, 0))["value"].item() == pytest.approx(659.138)
    assert [s.facts[0].label_time for s in wa_res.source_series if s.identity.published_id == "763266010"] == ["02:00"]

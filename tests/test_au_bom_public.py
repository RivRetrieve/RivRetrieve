"""Public Australia BoM discovery and retrieval through rr.find/rr.pick/rr.fetch."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_RETRIEVED_AT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _list_json(station: str, rows: list[tuple[str, str, str, str]]) -> bytes:
    header = ["ts_id", "ts_name", "parametertype_name", "ts_unitsymbol", "station_no"]
    return json.dumps(
        [header, *[[ts_id, ts_name, param, unit, station] for ts_id, ts_name, param, unit in rows]]
    ).encode("utf-8")


def _values_json(blocks: list[tuple[str, list[tuple[str, float | None, int | None, str | None]]]]) -> bytes:
    columns = "Timestamp,Value,Quality Code,Quality Code Name"
    return json.dumps(
        [
            {
                "ts_id": ts_id,
                "rows": str(len(rows)),
                "columns": columns,
                "data": [[label, value, code, name] for label, value, code, name in rows],
            }
            for ts_id, rows in blocks
        ]
    ).encode("utf-8")


def _select_stage_daily_mean(station: str) -> rr.Selection:
    """au_bom's series identity is only known at response time (#645), so catalogue-level

    series_id cannot restrict a selection before fetching (unlike at_ehyd's
    Messstellen/info-resolved file numbers); physical predicates select instead.
    stage_daily_mean has no 09HR sibling, so quantity/frequency/statistic alone
    is unambiguous, unlike discharge's 24HR/09HR daily means.
    """
    return rr.find(provider="au_bom", station=station, quantity="stage", frequency="P1D", statistic="mean")


def test_public_discovery_is_network_free() -> None:
    selected = rr.find(provider="au_bom", station="410730")
    frame = rr.as_frame(selected)
    assert "discharge_daily_mean_24hr" in frame["product_id"].to_list()
    assert "stage_daily_mean" in frame["product_id"].to_list()


def test_public_fetch_combines_duplicate_ts_id_and_converts_units(monkeypatch: pytest.MonkeyPatch) -> None:
    station = "138020A"
    list_bytes = _list_json(
        station,
        [
            ("470345010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m"),
            ("381776010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m"),
        ],
    )
    values_bytes = _values_json(
        [
            ("470345010", [("2026-09-01T00:00:00.000+10:00", 1.887, 10, "quality-A")]),
            ("381776010", []),
        ]
    )

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if params.get("request") == "getTimeseriesList":
                return TransportResponse(list_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)
            return TransportResponse(values_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = _select_stage_daily_mean(station)
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass")

    assert result.data["unit"].to_list() == ["m"]
    assert result.data["value"].to_list() == [pytest.approx(1.887)]
    statuses = {outcome.status for outcome in result.outcomes}
    from rivretrieve._internal.source_series import OutcomeStatus

    assert OutcomeStatus.SUCCESS in statuses
    assert OutcomeStatus.EMPTY in statuses
    assert len({item.series_id for item in result.source_series}) == 2


def test_public_fetch_attaches_quality_code_annotation_without_dropping_the_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    station = "410730"
    list_bytes = _list_json(station, [("1598010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m")])
    values_bytes = _values_json([("1598010", [("2026-09-01T00:00:00.000+10:00", 0.745, -1, "quality-E")])])

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if params.get("request") == "getTimeseriesList":
                return TransportResponse(list_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)
            return TransportResponse(values_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = _select_stage_daily_mean(station)
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass")

    assert result.data["value"].to_list() == [pytest.approx(0.745)]
    annotated = result.to_polars(annotations=True)
    assert annotated["Quality_Code"].to_list() == [-1]
    assert annotated["Quality_Code_Name"].to_list() == ["quality-E"]


def test_public_fetch_cache_reuse_keeps_every_duplicate_ts_id_series(monkeypatch: pytest.MonkeyPatch) -> None:
    """A later cache='reuse' fetch must not silently drop one of two duplicate-ts_id series (#965).

    _parse_values used to emit one COMPLETE InventorySnapshot per block, each claiming
    the same scope with only that block's single series_id as its member. On reuse, the
    engine's reversed-iteration reuse scan stopped at whichever snapshot it saw first,
    discarding the other series_id's genuinely-fetched rows without raising an issue.
    """
    station = "138020A"
    list_bytes = _list_json(
        station,
        [
            ("470345010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m"),
            ("381776010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m"),
        ],
    )
    values_bytes = _values_json(
        [
            ("470345010", [("2026-09-01T00:00:00.000+10:00", 1.887, 10, "quality-A")]),
            ("381776010", [("2026-09-01T00:00:00.000+10:00", 2.5, 10, "quality-A")]),
        ]
    )
    calls = []

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            calls.append(request.url)
            params = dict(request.params or {})
            if params.get("request") == "getTimeseriesList":
                return TransportResponse(list_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)
            return TransportResponse(values_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = _select_stage_daily_mean(station)

    first = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="reuse")
    assert sorted(first.data["value"].to_list()) == [pytest.approx(1.887), pytest.approx(2.5)]

    calls_before = len(calls)
    reused = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="reuse")
    assert len(calls) == calls_before, "expected the second fetch to be served from cache, not re-fetched"
    assert sorted(reused.data["value"].to_list()) == [pytest.approx(1.887), pytest.approx(2.5)]


def test_public_fetch_reports_a_clear_unsupported_unit_outcome_not_a_generic_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A series BoM reports in an unexpected unit gets a named UNSUPPORTED outcome (#965 follow-up).

    fetch.py excludes a unit-mismatched ts_id before ever issuing a values call, so
    _parse_values's own admission()-based UNSUPPORTED branch can no longer see it; this
    checks _parse_list_prerequisite reports the same mismatch with its own clear reason,
    instead of the generic "cannot settle the requested source scope" fallback that fires
    when a product genuinely gets no outcome of its own.
    """
    station = "410730"
    list_bytes = _list_json(station, [("1598010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "cm")])

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            return TransportResponse(list_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = _select_stage_daily_mean(station)
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass", on_issue="ignore")

    from rivretrieve._internal.source_series import OutcomeStatus

    assert result.data.is_empty()
    assert any(o.status is OutcomeStatus.UNSUPPORTED and "cm" in (o.reason or "") for o in result.outcomes)
    assert any(i.code == "source.unsupported_unit" and "cm" in i.message for i in result.issues)


def test_public_fetch_reports_mixed_unit_duplicate_ts_id_without_dropping_valid_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When one duplicate ts_id matches the expected unit and another does not, keep the valid sibling and warn."""
    station = "138020A"
    list_bytes = _list_json(
        station,
        [
            ("470345010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m"),
            ("381776010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "cm"),
        ],
    )
    values_bytes = _values_json([("470345010", [("2026-09-01T00:00:00.000+10:00", 1.887, 10, "quality-A")])])
    requested_ts_ids: list[str] = []

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if params.get("request") == "getTimeseriesList":
                return TransportResponse(list_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)
            requested_ts_ids.append(str(params.get("ts_id", "")))
            return TransportResponse(values_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = _select_stage_daily_mean(station)
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass", on_issue="ignore")

    from rivretrieve._internal.source_series import OutcomeStatus

    assert requested_ts_ids == ["470345010"]
    assert result.data["value"].to_list() == [pytest.approx(1.887)]
    assert any(o.status is OutcomeStatus.SUCCESS for o in result.outcomes)
    assert any(
        o.status is OutcomeStatus.UNSUPPORTED
        and o.series_id is not None
        and "cm" in (o.reason or "")
        and "381776010" in (o.reason or "")
        for o in result.outcomes
    )
    assert any(i.code == "source.unsupported_unit" and "cm" in i.message for i in result.issues)
    assert {item.identity.published_id for item in result.source_series} == {"470345010", "381776010"}


def test_public_fetch_surfaces_no_match_for_an_unresolved_product(monkeypatch: pytest.MonkeyPatch) -> None:
    station = "410730"
    # The list response only carries discharge for this ts_name, leaving the requested
    # stage series unresolved.
    list_bytes = _list_json(station, [("1573010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec")])

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            return TransportResponse(list_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = _select_stage_daily_mean(station)
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass", on_issue="ignore")

    assert result.data.is_empty()
    from rivretrieve._internal.source_series import OutcomeStatus

    assert any(outcome.status is OutcomeStatus.NO_MATCH for outcome in result.outcomes)


def test_public_fetch_reports_a_failed_list_call_as_an_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    station = "410730"

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=503,
                category=TransportFailureCategory.HTTP_STATUS,
            )

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = _select_stage_daily_mean(station)
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass", on_issue="ignore")

    assert result.data.is_empty()
    assert any(issue.severity == "error" for issue in result.issues)


def test_public_fetch_reports_a_malformed_values_body_as_an_issue_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed getTimeseriesValues body is an isolated FAILED outcome, not a raised exception (#965)."""
    station = "410730"
    list_bytes = _list_json(station, [("1598010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m")])

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if params.get("request") == "getTimeseriesList":
                return TransportResponse(list_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)
            return TransportResponse(b"not valid json {{{", 200, _RETRIEVED_AT, "application/json", request.url, params)

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = _select_stage_daily_mean(station)
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass", on_issue="ignore")

    assert result.data.is_empty()
    assert any(issue.severity == "error" and issue.code == "source.unsupported_structure" for issue in result.issues)


@pytest.mark.parametrize(
    ("station", "ts_id", "ts_name", "param_name", "unit", "quantity", "frequency", "raw_time", "expected_time", "val"),
    [
        # WA (+08:00 local -> 02:00 / 11:00 in +10:00)
        (
            "601001",
            "73472010",
            "DMQaQc.Merged.DailyMean.24HR",
            "Water Course Discharge",
            "cumec",
            "discharge",
            "P1D",
            "2026-08-02T02:00:00.000+10:00",
            datetime(2026, 8, 2, 2, 0),
            0.172,
        ),
        (
            "601001",
            "73471010",
            "DMQaQc.Merged.DailyMean.09HR",
            "Water Course Discharge",
            "cumec",
            "discharge",
            "P1D",
            "2026-08-02T11:00:00.000+10:00",
            datetime(2026, 8, 2, 11, 0),
            0.172,
        ),
        # SA (+09:30 local -> 00:30 in +10:00; temperature daily and yearly)
        (
            "A5131021",
            "227552010",
            "DMQaQc.Merged.DailyMean.24HR",
            "Water Temperature",
            "°C",
            "temperature",
            "P1D",
            "2026-08-02T00:30:00.000+10:00",
            datetime(2026, 8, 2, 0, 30),
            12.5,
        ),
        (
            "A5131021",
            "227554010",
            "DMQaQc.Merged.YearlyMean.CalYear",
            "Water Temperature",
            "°C",
            "temperature",
            "P1Y",
            "2026-01-01T00:30:00.000+10:00",
            datetime(2026, 1, 1, 0, 30),
            15.0,
        ),
        # NT (+09:30 local -> 00:30 / 09:30 in +10:00)
        (
            "G8100106",
            "52074010",
            "DMQaQc.Merged.DailyMean.24HR",
            "Water Course Discharge",
            "cumec",
            "discharge",
            "P1D",
            "2026-08-02T00:30:00.000+10:00",
            datetime(2026, 8, 2, 0, 30),
            0.002,
        ),
        (
            "G8100106",
            "52073010",
            "DMQaQc.Merged.DailyMean.09HR",
            "Water Course Discharge",
            "cumec",
            "discharge",
            "P1D",
            "2026-08-02T09:30:00.000+10:00",
            datetime(2026, 8, 2, 9, 30),
            0.001,
        ),
    ],
)
def test_public_fetch_accepts_non_aest_local_standard_time_anchors(
    monkeypatch: pytest.MonkeyPatch,
    station: str,
    ts_id: str,
    ts_name: str,
    param_name: str,
    unit: str,
    quantity: str,
    frequency: str,
    raw_time: str,
    expected_time: datetime,
    val: float,
) -> None:
    """WA (+08:00 -> 02:00/11:00) and SA/NT (+09:30 -> 00:30/09:30) rows must not fail validation (#1082)."""
    list_bytes = _list_json(station, [(ts_id, ts_name, param_name, unit)])
    values_bytes = _values_json([(ts_id, [(raw_time, val, 110, "quality-C")])])

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if params.get("request") == "getTimeseriesList":
                return TransportResponse(list_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)
            return TransportResponse(values_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = rr.find(provider="au_bom", station=station, quantity=quantity, frequency=frequency, statistic="mean")
    result = rr.fetch(selection, start="2026-01-01", end="2026-08-05", cache="bypass", on_issue="ignore")

    assert result.data.height == 1
    assert result.data["time"].to_list() == [expected_time]
    assert result.data["time_zone"].to_list() == ["+10:00"]
    assert result.data["value"].to_list() == [pytest.approx(val)]
    expected_anchor = f"{expected_time.hour:02d}:{expected_time.minute:02d}"
    matching = [s for s in result.source_series if s.identity.published_id == ts_id]
    assert len(matching) == 1
    assert matching[0].facts[0].label_time == expected_anchor

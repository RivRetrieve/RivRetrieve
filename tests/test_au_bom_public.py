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
    return rr.find(provider="au_bom", station=station, quantity="stage", frequency="daily", statistic="mean")


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


def test_public_fetch_emits_quality_issue_without_dropping_the_value(monkeypatch: pytest.MonkeyPatch) -> None:
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
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass", on_issue="ignore")

    assert result.data["value"].to_list() == [pytest.approx(0.745)]
    quality_issues = [issue for issue in result.issues if issue.code == "source.quality_code"]
    assert len(quality_issues) == 1
    assert quality_issues[0].severity == "info"


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

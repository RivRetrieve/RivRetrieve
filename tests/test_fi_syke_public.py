"""Public SYKE discovery and retrieval through rr.find/rr.pick/rr.fetch."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_RETRIEVED_AT = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
_STAGE_STATION = "1721"

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _page(rows: list[dict[str, object]]) -> bytes:
    return json.dumps({"odata.metadata": "x", "value": rows}).encode("utf-8")


def _row(paikka_id: int, day: int, value: object, *, flag: int | None = None) -> dict[str, object]:
    return {
        "Paikka_Id": paikka_id,
        "Aika": f"2026-09-{day:02d}T00:00:00",
        "Arvo": value,
        "ArvoMin": None,
        "ArvoMax": None,
        "Lippu_id": flag,
        "huomautus": None,
    }


def _select_stage(station: str) -> rr.Selection:
    return rr.find(provider="fi_syke", station=station, quantity="stage")


def test_public_discovery_is_network_free() -> None:
    selected = rr.find(provider="fi_syke", station=_STAGE_STATION)
    frame = rr.as_frame(selected)
    assert "stage_reported" in frame["product_id"].to_list()


@pytest.mark.parametrize(
    ("quantity", "product_id", "unit"),
    [
        ("discharge", "discharge_reported", "m3/s"),
        ("stage", "stage_reported", "m"),
        ("temperature", "water_temperature_reported", "degC"),
    ],
)
def test_public_discovery_filters_all_three_quantities(quantity: str, product_id: str, unit: str) -> None:
    selected = rr.find(provider="fi_syke", station=_STAGE_STATION, quantity=quantity)
    assert selected.empty_reason is None
    frame = rr.series(selected)
    assert frame["product_id"].to_list() == [product_id]
    assert frame["quantity"].to_list() == [quantity]
    assert frame["unit"].to_list() == [unit]
    assert frame["admission"].to_list() == ["supported"]


def test_public_fetch_converts_native_cm_to_canonical_m(monkeypatch: pytest.MonkeyPatch) -> None:
    content = _page([_row(1721, 1, 11017)])

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(
                content, 200, _RETRIEVED_AT, "application/json", request.url, dict(request.params or {})
            )

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = _select_stage(_STAGE_STATION)
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass")

    assert result.data["unit"].to_list() == ["m"]
    assert result.data["value"].to_list() == [pytest.approx(110.17)]


def test_public_fetch_surfaces_lippu_flag_without_dropping_the_value(monkeypatch: pytest.MonkeyPatch) -> None:
    content = _page([_row(1721, 1, 11017, flag=1)])

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(
                content, 200, _RETRIEVED_AT, "application/json", request.url, dict(request.params or {})
            )

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = _select_stage(_STAGE_STATION)
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass", on_issue="ignore")

    assert result.data["value"].to_list() == [pytest.approx(110.17)]
    flag_issues = [issue for issue in result.issues if issue.code == "source.flag_code"]
    assert len(flag_issues) == 1
    assert flag_issues[0].severity == "info"
    assert flag_issues[0].details["source_flag_code"] == 1


def test_public_fetch_an_empty_range_is_an_empty_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    content = _page([])

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(
                content, 200, _RETRIEVED_AT, "application/json", request.url, dict(request.params or {})
            )

    monkeypatch.setattr(discovery, "HttpClient", _Transport)
    selection = _select_stage(_STAGE_STATION)
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass", on_issue="ignore")

    assert result.data.is_empty()
    assert any(outcome.status is OutcomeStatus.EMPTY for outcome in result.outcomes)


def test_public_fetch_reports_a_transport_failure_as_an_issue(monkeypatch: pytest.MonkeyPatch) -> None:
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
    selection = _select_stage(_STAGE_STATION)
    result = rr.fetch(selection, start="2026-09-01", end="2026-09-01", cache="bypass", on_issue="ignore")

    assert result.data.is_empty()
    assert any(issue.severity == "error" for issue in result.issues)

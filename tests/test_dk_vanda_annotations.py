"""Source-independent tests for dk_vanda water-temperature reason annotations (#809)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.engine import WindowEndpoint, _make_fetch_window
from rivretrieve._internal.providers.dk_vanda.annotations import DK_VANDA_TEMPERATURE_SCHEMA, VANDA_SWAGGER_URL
from rivretrieve._internal.providers.dk_vanda.config import config, window_declarations
from rivretrieve._internal.providers.dk_vanda.fetch import fetch
from rivretrieve._internal.providers.dk_vanda.parse import parse
from rivretrieve._internal.source_annotations import AnnotationScope
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportResponse
from rivretrieve._internal.window_planning import plan_windows

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _window(start: str, end: str):
    return _make_fetch_window(
        WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
        WindowEndpoint.from_datetime(datetime.fromisoformat(end)),
    )


class _Transport:
    def __init__(self, bodies: list[bytes]) -> None:
        self.bodies = iter(bodies)
        self.requests: list[object] = []

    def send(self, request: object):
        self.requests.append(request)
        return TransportResponse(
            content=next(self.bodies),
            status_code=200,
            retrieved_at=datetime(2026, 11, 15, tzinfo=UTC),
            content_type="application/json",
            url=request.url,  # type: ignore[attr-defined]
            request_parameters=request.params,  # type: ignore[attr-defined]
        )


def _result_row(
    sc: int, measurement_date_time: str, result: float | None, *, reason_sc: object = None, reason: object = None
) -> dict[str, object]:
    return {
        "measurementPointNumber": 1,
        "parameterSc": 1154,
        "parameter": "Temperatur",
        "examinationTypeSc": sc,
        "examinationType": "Temperaturmåling",
        "measurementDateTime": measurement_date_time,
        "depthM": None,
        "result": result,
        "resultElevationCorrected": None,
        "unitSc": 29,
        "unit": "grader C",
        "reasonSc": reason_sc,
        "reason": reason,
    }


def _envelope(station: str, rows: list[dict[str, object]]) -> bytes:
    return json.dumps([{"stationId": station, "operatorStationId": "", "results": rows}]).encode()


def _acquire(station: str, rows: list[dict[str, object]]):
    cfg = config()
    decls = window_declarations()
    fw = _window("2020-01-01", "2020-01-02")
    rendered = {"temperature": plan_windows(fw, decls.products["temperature"])}
    transport = _Transport([_envelope(station, rows)])
    result = fetch((station,), ("temperature",), rendered, fw, cfg, transport)
    assert len(result.value) == 1
    return result.value[0], cfg


def test_dk_vanda_temperature_annotation_schema_defines_verified_fields() -> None:
    assert DK_VANDA_TEMPERATURE_SCHEMA.schema_id == "dk_vanda.temperature"
    assert DK_VANDA_TEMPERATURE_SCHEMA.provider_id == "dk_vanda"
    assert DK_VANDA_TEMPERATURE_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [field.name for field in DK_VANDA_TEMPERATURE_SCHEMA.fields] == ["reasonSc", "reason"]
    assert [field.dtype for field in DK_VANDA_TEMPERATURE_SCHEMA.fields] == ["Int64", "String"]
    for field in DK_VANDA_TEMPERATURE_SCHEMA.fields:
        assert field.description
        assert field.reference_url == VANDA_SWAGGER_URL


def test_parse_preserves_native_codes_nulls_and_row_alignment() -> None:
    payload, cfg = _acquire(
        "70000277",
        [
            _result_row(29, "2020-01-01T00:00:00.00Z", 5.2, reason_sc=3, reason="Is i vandløb"),
            _result_row(29, "2020-01-01T00:10:00.00Z", 5.3),
            _result_row(29, "2020-01-01T00:20:00.00Z", 5.1, reason_sc=0, reason="Normal"),
        ],
    )
    parsed = parse(payload, cfg)
    assert not parsed.issues
    assert parsed.rows.height == 3
    assert set(parsed.annotations.observation_tables) == {"dk_vanda.temperature"}
    assert not parsed.annotations.series_tables
    table = parsed.annotations.observation_tables["dk_vanda.temperature"]
    assert table.measurement_indices == (0, 1, 2)
    assert table.rows["time"].to_list() == parsed.rows["time"].to_list()
    assert table.rows["measured"].to_list() == [True, True, True]
    assert table.rows["reasonSc"].dtype == pl.Int64()
    assert table.rows["reasonSc"].to_list() == [3, None, 0]
    assert table.rows["reason"].to_list() == ["Is i vandløb", None, "Normal"]


def test_parse_empty_series_emits_empty_annotations() -> None:
    payload, cfg = _acquire("70000277", [])
    parsed = parse(payload, cfg)
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty


@pytest.mark.parametrize("bad_reason_sc", ["3", 3.0, True, False, [3], 1 << 63, -(1 << 63) - 1])
def test_parse_rejects_non_integer_reason_sc(bad_reason_sc: object) -> None:
    payload, cfg = _acquire("70000277", [_result_row(29, "2020-01-01T00:00:00.00Z", 5.2, reason_sc=bad_reason_sc)])
    parsed = parse(payload, cfg)
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty
    assert parsed.outcomes[0].status is OutcomeStatus.UNSUPPORTED
    assert any(issue.code == "unsupported_source_structure" for issue in parsed.issues)


@pytest.mark.parametrize("bad_reason", [3, 3.0, True, ["Is i vandløb"]])
def test_parse_rejects_non_string_reason(bad_reason: object) -> None:
    payload, cfg = _acquire(
        "70000277", [_result_row(29, "2020-01-01T00:00:00.00Z", 5.2, reason_sc=3, reason=bad_reason)]
    )
    parsed = parse(payload, cfg)
    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty
    assert parsed.outcomes[0].status is OutcomeStatus.UNSUPPORTED
    assert any(issue.code == "unsupported_source_structure" for issue in parsed.issues)


def _install_transport(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bodies: list[bytes]) -> _Transport:
    transport = _Transport(bodies)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    return transport


def test_public_discovery_and_default_projection_schema_remain_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = [
        _result_row(29, "2020-01-01T00:00:00.00Z", 5.2, reason_sc=3, reason="Is i vandløb"),
        _result_row(29, "2020-01-01T00:10:00.00Z", 5.3),
    ]
    _install_transport(monkeypatch, tmp_path, [_envelope("70000277", rows)])
    selection = rr.find(provider="dk_vanda", station="70000277", quantity="temperature")
    assert rr.annotations(selection).is_empty()

    result = rr.fetch(selection, start="2020-01-01", end="2020-01-01T23:59:59", cache="bypass")
    assert result.data.height == 2
    assert result.to_polars().equals(result.data)

    catalog = rr.annotations(result)
    assert catalog["schema"].to_list() == ["dk_vanda.temperature"] * 2
    assert catalog["name"].to_list() == ["reasonSc", "reason"]
    assert catalog["row_count"].to_list() == [2, 2]

    schema_table = rr.annotations(result, schema="dk_vanda.temperature")
    assert schema_table.height == 2
    assert schema_table["measured"].to_list() == [True, True]

    projected = result.to_polars(annotations=True)
    assert projected.columns == [*result.data.columns, "reasonSc", "reason"]
    assert projected.sort("time")["reasonSc"].to_list() == [3, None]
    assert projected.sort("time")["reason"].to_list() == ["Is i vandløb", None]

    narrowed = result.to_polars(annotations="reasonSc")
    assert narrowed.columns == [*result.data.columns, "reasonSc"]


def test_public_discharge_and_stage_never_attach_temperature_annotations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transport = _install_transport(
        monkeypatch,
        tmp_path,
        [_envelope("25003918", [_result_row(27, "2020-01-01T00:00:00.00Z", 123.4)])],
    )
    selection = rr.find(provider="dk_vanda", station="25003918", quantity="discharge")
    result = rr.fetch(selection, start="2020-01-01", end="2020-01-01T23:59:59", cache="bypass")
    assert result.data.height == 1
    assert rr.annotations(result).is_empty()
    assert result.to_polars(annotations=True).equals(result.data)
    assert len(transport.requests) == 1

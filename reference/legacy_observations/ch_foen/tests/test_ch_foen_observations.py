from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.issues import InvalidObservationRequestError, IssuePolicyError
from rivretrieve._internal.observations import ObservationRequest, ObservationResult
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.providers.ch_foen import module as ch_foen_module
from rivretrieve._internal.providers.ch_foen.observation_client import (
    ChFoenObservationClient,
    ChFoenTransportRequest,
    ChFoenTransportResponse,
)
from rivretrieve._internal.providers.ch_foen.query import ChFoenProductPolicy, ChFoenTimeWindow, build_calls
from rivretrieve._internal.providers.ch_foen.transform import transform_series

TEST_DATA = Path(__file__).parent / "test_data"


def test_ch_foen_observations_2206_discharge_fallback_converts_to_m3s(monkeypatch) -> None:
    _install_transport(monkeypatch, _fixture_transport({"2206": "switzerland_2206_discharge_20250101.csv"}))

    result = rr.provider("ch_foen").observations(
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert result.data.height == 144
    assert result.data["value"].min() == 0.014
    assert result.data["value"].max() == 0.015
    mean_value = result.data["value"].mean()
    assert isinstance(mean_value, float)
    assert math.isclose(mean_value, 0.014944444444, rel_tol=0.0, abs_tol=1e-12)
    assert _series_value(result, "2206", "discharge_instantaneous", "fallback_source_used") == "true"
    assert _row_values(result, "native_unit") == {"L/s"}
    assert _row_values(result, "converted_unit") == {"m3/s"}


def test_ch_foen_observations_wrapper_2206_discharge_smoke(monkeypatch) -> None:
    _install_transport(monkeypatch, _fixture_transport({"2206": "switzerland_2206_discharge_20250101.csv"}))

    result = rr.observations(
        provider="ch_foen",
        stations=["2206"],
        products=["discharge_instantaneous"],
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert isinstance(result, ObservationResult)
    assert result.data.height == 144
    assert result.data["value"].min() == 0.014
    assert result.data["value"].max() == 0.015
    mean_value = result.data["value"].mean()
    assert isinstance(mean_value, float)
    assert math.isclose(mean_value, 0.014944444444, rel_tol=0.0, abs_tol=1e-12)
    assert _series_value(result, "2206", "discharge_instantaneous", "fallback_source_used") == "true"
    assert _row_values(result, "native_unit") == {"L/s"}
    assert _row_values(result, "converted_unit") == {"m3/s"}


def test_ch_foen_observations_2282_stage_instant_returns_all_samples(monkeypatch) -> None:
    _install_transport(monkeypatch, _fixture_transport({"2282": "switzerland_2282_stage_20250101.csv"}))

    result = rr.provider("ch_foen").observations(
        stations="2282",
        products="stage_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert result.data.height == 141
    assert result.data["time"].min() == _utc("2025-01-01T00:00:00Z")
    assert result.data["time"].max() == _utc("2025-01-01T23:50:00Z")


def test_ch_foen_observations_2016_temperature_daily_mean(monkeypatch) -> None:
    _install_transport(monkeypatch, _fixture_transport({"2016": "switzerland_2016_temperature_20200101.csv"}))

    result = rr.provider("ch_foen").observations(
        stations="2016",
        products="water_temperature_daily_mean",
        start="2020-01-01",
        end="2020-01-01",
        on_issue="ignore",
    )

    assert result.data.height == 1
    assert result.data.row(0, named=True)["time"] == _utc("2020-01-01T00:00:00Z")
    assert 6.5 <= result.data.row(0, named=True)["value"] <= 6.77


def test_ch_foen_observations_multi_station_single_product_bulk(monkeypatch) -> None:
    _install_transport(
        monkeypatch,
        _fixture_transport(
            {
                "2206": "switzerland_2206_discharge_20250101.csv",
                "2282": "switzerland_2282_stage_20250101.csv",
            }
        ),
    )

    result = rr.provider("ch_foen").observations(
        stations=["2206", "2282"],
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert set(result.data["station_id"].to_list()) == {"2206"}
    assert {issue.code for issue in result.issues} >= {"missing_data"}


def test_ch_foen_observations_single_station_multi_product_bulk(monkeypatch) -> None:
    _install_transport(monkeypatch, _fixture_transport({"2206": "switzerland_2206_discharge_20250101.csv"}))

    result = rr.provider("ch_foen").observations(
        stations="2206",
        products=["discharge_instantaneous", "stage_instantaneous"],
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert set(result.data["product_id"].to_list()) == {"discharge_instantaneous"}
    assert {issue.code for issue in result.issues} >= {"missing_data"}


def test_ch_foen_observations_cross_product_bulk(monkeypatch) -> None:
    _install_transport(monkeypatch, _fixture_transport({"2206": "switzerland_2206_discharge_20250101.csv"}))

    result = rr.provider("ch_foen").observations(
        stations=["2206", "2282"],
        products=["discharge_instantaneous", "stage_instantaneous"],
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert len(result.provenance.time_windows) == 4
    assert {issue.code for issue in result.issues} >= {"missing_data"}


def test_ch_foen_observations_decomposes_over_366_days_and_stitches() -> None:
    calls = build_calls(
        station_id="2206",
        product_id="discharge_instantaneous",
        start=_utc("2025-01-01T00:00:00Z"),
        end=_utc("2026-01-02T00:00:00Z"),
    )

    assert len(calls) == 2
    assert calls[0].window.start == _utc("2025-01-01T00:00:00Z")
    assert calls[0].window.end == _utc("2026-01-01T00:00:00Z")
    assert calls[1].window.start == _utc("2026-01-02T00:00:00Z")


def test_ch_foen_row_annotations_all_declared_ids_are_emitted(monkeypatch) -> None:
    result = _conflict_result(monkeypatch)

    assert set(result.row_annotations.data["annotation"].to_list()) == {
        schema.annotation_id for schema in ch_foen_module.row_annotation_schema()
    }


def test_ch_foen_series_annotations_all_declared_ids_are_emitted(monkeypatch) -> None:
    result = _conflict_result(monkeypatch)

    assert set(result.series_annotations.data["annotation"].to_list()) == {
        schema.annotation_id for schema in ch_foen_module.series_annotation_schema()
    }


def test_ch_foen_overlap_annotation_and_issue(monkeypatch) -> None:
    _install_transport(monkeypatch, _bytes_transport(_csv_with_fields(flow=1.0, flow_ls=1000.0)))

    result = rr.provider("ch_foen").observations(
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert "overlap" in {issue.code for issue in result.issues}
    assert _row_values(result, "alternative_native_field") == {"flow_ls"}


def test_ch_foen_conflict_annotation_and_issue(monkeypatch) -> None:
    result = _conflict_result(monkeypatch)

    assert "conflict" in {issue.code for issue in result.issues}
    assert _row_values(result, "alternative_raw_value") == {"900"}


def test_ch_foen_gap_issue(monkeypatch) -> None:
    _install_transport(monkeypatch, _bytes_transport(_csv_one("2025-01-01T00:00:00Z", "temperature", 6.0)))

    result = rr.provider("ch_foen").observations(
        stations="2206",
        products="water_temperature_daily_mean",
        start="2025-01-01",
        end="2025-01-02",
        on_issue="ignore",
    )

    assert "gap" in {issue.code for issue in result.issues}


def test_ch_foen_timezone_ambiguity_issue(monkeypatch) -> None:
    _install_transport(monkeypatch, _bytes_transport(_csv_one("2025-01-01T00:00:00", "temperature", 6.0)))

    result = rr.provider("ch_foen").observations(
        stations="2206",
        products="water_temperature_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert "timezone_ambiguity" in {issue.code for issue in result.issues}
    assert _series_value(result, "2206", "water_temperature_instantaneous", "timezone_mismatch_flag") == "true"


def test_ch_foen_unit_conversion_ambiguity_issue() -> None:
    policy = ChFoenProductPolicy("synthetic", ("mystery",), "mystery", None, "m", False, True)
    records = pl.DataFrame(
        [
            {
                "time": _utc("2025-01-01T00:00:00Z"),
                "station_id": "2206",
                "native_field": "mystery",
                "native_value": 1.0,
                "measurement": "hydro",
                "window_start": _utc("2025-01-01T00:00:00Z"),
                "window_stop": _utc("2025-01-02T00:00:00Z"),
                "table": 0,
            }
        ]
    )

    result = transform_series(
        records,
        station_id="2206",
        policy=policy,
        windows=(
            ChFoenTimeWindow(_utc("2025-01-01T00:00:00Z"), _utc("2025-01-01T00:00:00Z"), _utc("2025-01-02T00:00:00Z")),
        ),
        endpoint="https://influx.example.invalid",
        source_query="query",
    )

    assert "unit_conversion_ambiguity" in {issue.code for issue in result.issues}


def test_ch_foen_missing_data_issue(monkeypatch) -> None:
    _install_transport(monkeypatch, _bytes_transport(b""))

    result = rr.provider("ch_foen").observations(
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert "missing_data" in {issue.code for issue in result.issues}


def test_ch_foen_partial_failure_returns_well_formed_result(monkeypatch) -> None:
    calls = 0

    def transport(_request: ChFoenTransportRequest) -> ChFoenTransportResponse:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("offline failure")
        return _response((TEST_DATA / "switzerland_2206_discharge_20250101.csv").read_bytes())

    _install_transport(monkeypatch, transport)

    result = rr.provider("ch_foen").observations(
        stations=["2206", "2282"],
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert result.data.height == 144
    assert {issue.code for issue in result.issues} >= {"source_request_failed", "partial_response"}


def test_ch_foen_all_transport_calls_fail_returns_empty_with_issues(monkeypatch) -> None:
    def transport(_request: ChFoenTransportRequest) -> ChFoenTransportResponse:
        raise OSError("offline failure")

    _install_transport(monkeypatch, transport)

    result = rr.provider("ch_foen").observations(
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert result.data.is_empty()
    assert {issue.code for issue in result.issues} == {"source_request_failed", "missing_data"}


def test_ch_foen_provenance_contains_sanitized_calls(monkeypatch) -> None:
    _install_transport(monkeypatch, _fixture_transport({"2206": "switzerland_2206_discharge_20250101.csv"}))

    result = rr.provider("ch_foen").observations(
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    rendered = repr(result.provenance)
    assert result.provenance.calls_made
    assert "Authorization" not in rendered
    assert "Token " not in rendered


def test_ch_foen_raw_payload_metadata_is_sanitized(monkeypatch) -> None:
    _install_transport(monkeypatch, _fixture_transport({"2206": "switzerland_2206_discharge_20250101.csv"}))

    result = rr.provider("ch_foen").observations(
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert result.raw is not None
    assert result.raw.metadata is not None
    assert "Authorization" not in result.raw.metadata
    assert "Token " not in result.raw.metadata


def test_ch_foen_tests_tree_does_not_contain_public_token_literal() -> None:
    from rivretrieve._internal.providers.ch_foen import observation_client

    token = observation_client._EMBEDDED_PUBLIC_TOKEN
    for path in TEST_DATA.parent.glob("**/*"):
        if path.is_file():
            assert token not in path.read_text(errors="ignore")


def test_ch_foen_missing_start_raises_before_provider_execution(monkeypatch) -> None:
    touched = False

    def transport(_request: ChFoenTransportRequest) -> ChFoenTransportResponse:
        nonlocal touched
        touched = True
        return _response(b"")

    _install_transport(monkeypatch, transport)
    with pytest.raises(InvalidObservationRequestError):
        ObservationRequest.from_inputs(
            provider_id=ProviderId("ch_foen"),
            stations="2206",
            products="discharge_instantaneous",
            start=None,
            end="2025-01-01",
        )
    assert touched is False


def test_ch_foen_on_issue_raise_converts_recoverable_issue(monkeypatch) -> None:
    _install_transport(monkeypatch, _bytes_transport(b""))

    with pytest.raises(IssuePolicyError) as exc_info:
        rr.provider("ch_foen").observations(
            stations="2206",
            products="discharge_instantaneous",
            start="2025-01-01",
            end="2025-01-01",
            on_issue="raise",
        )

    assert {issue.code for issue in exc_info.value.issues} == {"missing_data"}


def test_ch_foen_provider_query_fields_generator_serializes_json(monkeypatch) -> None:
    result = _single_discharge_result(monkeypatch)

    encoded = _series_value(result, "2206", "discharge_instantaneous", "provider_query_fields")
    decoded = json.loads(encoded)
    assert encoded == json.dumps(decoded, sort_keys=True, separators=(",", ":"))
    assert decoded["windows"] == [{"range_start": "2025-01-01T00:00:00Z", "range_stop": "2025-01-02T00:00:00Z"}]


def test_ch_foen_boolean_annotations_generator_serializes_utf8(monkeypatch) -> None:
    result = _single_discharge_result(monkeypatch)

    assert _series_value(result, "2206", "discharge_instantaneous", "fallback_source_used") == "true"
    assert _series_value(result, "2206", "discharge_instantaneous", "timezone_mismatch_flag") == "false"


def test_ch_foen_datetime_annotations_generator_serializes_iso_z(monkeypatch) -> None:
    result = _single_discharge_result(monkeypatch)

    assert (
        _series_value(result, "2206", "discharge_instantaneous", "returned_time_range_start") == "2025-01-01T00:00:00Z"
    )
    assert _series_value(result, "2206", "discharge_instantaneous", "returned_time_range_end") == "2025-01-01T23:50:00Z"


def test_ch_foen_float_annotations_generator_serializes_decimal_utf8(monkeypatch) -> None:
    result = _conflict_result(monkeypatch)

    assert _row_values(result, "raw_value") == {"1"}
    assert _row_values(result, "alternative_raw_value") == {"900"}


def test_ch_foen_native_unit_returned_generator_serializes_json_array(monkeypatch) -> None:
    result = _conflict_result(monkeypatch)

    assert _series_value(result, "2206", "discharge_instantaneous", "native_unit_returned") == '["m3/s"]'


def test_ch_foen_flow_ls_generator_converts_value_before_result(monkeypatch) -> None:
    result = _single_discharge_result(monkeypatch)

    assert result.data["value"].max() == 0.015


def test_ch_foen_timestamp_generator_normalizes_utc(monkeypatch) -> None:
    result = _single_discharge_result(monkeypatch)

    assert result.data.schema["time"] == pl.Datetime(time_unit="us", time_zone="UTC")


def test_ch_foen_observation_client_default_transport_is_not_used_in_tests(monkeypatch) -> None:
    from rivretrieve._internal.providers.ch_foen import observation_client

    def forbidden(_request: ChFoenTransportRequest) -> ChFoenTransportResponse:
        raise AssertionError("default transport touched")

    monkeypatch.setattr(observation_client, "_default_transport", forbidden)
    _install_transport(monkeypatch, _fixture_transport({"2206": "switzerland_2206_discharge_20250101.csv"}))

    result = rr.provider("ch_foen").observations(
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )

    assert result.data.height == 144


def _single_discharge_result(monkeypatch) -> ObservationResult:
    _install_transport(monkeypatch, _fixture_transport({"2206": "switzerland_2206_discharge_20250101.csv"}))
    return rr.provider("ch_foen").observations(
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )


def _conflict_result(monkeypatch) -> ObservationResult:
    _install_transport(monkeypatch, _bytes_transport(_csv_with_fields(flow=1.0, flow_ls=900.0)))
    return rr.provider("ch_foen").observations(
        stations="2206",
        products="discharge_instantaneous",
        start="2025-01-01",
        end="2025-01-01",
        on_issue="ignore",
    )


def _install_transport(monkeypatch, transport) -> None:
    monkeypatch.setattr(
        ch_foen_module,
        "_observation_client_factory",
        lambda: ChFoenObservationClient(token="fake-token", transport=transport),
    )


def _fixture_transport(station_files: dict[str, str]):
    def transport(request: ChFoenTransportRequest) -> ChFoenTransportResponse:
        for station_id, filename in station_files.items():
            if f'r["loc"] == "{station_id}"' in request.query:
                return _response((TEST_DATA / filename).read_bytes())
        return _response(b"")

    return transport


def _bytes_transport(csv_bytes: bytes):
    def transport(_request: ChFoenTransportRequest) -> ChFoenTransportResponse:
        return _response(csv_bytes)

    return transport


def _response(csv_bytes: bytes) -> ChFoenTransportResponse:
    return ChFoenTransportResponse(
        content=csv_bytes,
        status_code=200,
        retrieved_at=datetime(2026, 5, 28, tzinfo=UTC),
    )


def _csv_one(timestamp: str, field: str, value: float, *, station_id: str = "2206") -> bytes:
    return (
        ",result,table,_start,_stop,_time,_value,_field,_measurement,loc\n"
        f",_result,0,2025-01-01T00:00:00Z,2025-01-02T00:00:00Z,{timestamp},{value},{field},hydro,{station_id}\n"
    ).encode()


def _csv_with_fields(*, flow: float, flow_ls: float) -> bytes:
    return (
        ",result,table,_start,_stop,_time,_value,_field,_measurement,loc\n"
        f",_result,0,2025-01-01T00:00:00Z,2025-01-02T00:00:00Z,2025-01-01T00:00:00Z,{flow},flow,hydro,2206\n"
        f",_result,0,2025-01-01T00:00:00Z,2025-01-02T00:00:00Z,2025-01-01T00:00:00Z,{flow_ls},flow_ls,hydro,2206\n"
    ).encode()


def _series_value(result, station_id: str, product_id: str, annotation: str) -> str:
    return (
        result.series_annotations.data.filter(
            (pl.col("station_id") == station_id)
            & (pl.col("product_id") == product_id)
            & (pl.col("annotation") == annotation)
        )
        .select("value")
        .item()
    )


def _row_values(result, annotation: str) -> set[str]:
    return set(
        result.row_annotations.data.filter(pl.col("annotation") == annotation)
        .filter(pl.col("value").is_not_null())
        .select("value")
        .to_series()
        .to_list()
    )


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

"""Public Belgium - Wallonia (`be_wal`) retrieval, series_id parity, annotations, and isolation tests."""

from __future__ import annotations

import json
import warnings
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.discovery import EmptySelectionError
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.observations import ObservationResult
from rivretrieve._internal.providers.be_wal.annotations import BE_WAL_QUALITY_SCHEMA
from rivretrieve._internal.providers.be_wal.series import PRODUCT_BY_ID, PRODUCT_SPECS
from rivretrieve._internal.selection import UnknownStationError, _Selection
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_RETRIEVED_AT = datetime(2026, 11, 23, 18, 0, tzinfo=UTC)

_FAMILY_STATION = {
    "discharge": "1046",
    "discharge_ultrasonic": "2708",
    "stage": "1046",
    "stage_absolute": "7102",
    "water_temperature": "7102",
}

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _select_products(station: str, *products: str) -> _Selection:
    selected = rr.find(provider="be_wal", station=station)
    series_ids = rr.as_frame(selected).filter(pl.col("product_id").is_in(products))["series_id"].to_list()
    assert len(series_ids) == len(products)
    picked = rr.pick(selected, series_id=series_ids)
    assert isinstance(picked, _Selection)
    return picked


def _raise_http_failure(request: TransportRequest, status_code: int = 503) -> NoReturn:
    raise TransportFailure(
        request,
        TransportFailureReason.HTTP_STATUS,
        1,
        status_code=status_code,
        category=TransportFailureCategory.HTTP_STATUS,
    )


def _kiwis_response(
    request: TransportRequest,
    *,
    ts_id: str,
    ts_name: str,
    station_no: str,
    param_name: str,
    unitsymbol: str,
    rows: Sequence[Sequence[object]],
    status_code: int = 200,
) -> TransportResponse:
    payload = [
        {
            "ts_id": ts_id,
            "ts_name": ts_name,
            "station_no": station_no,
            "stationparameter_name": param_name,
            "parametertype_name": param_name,
            "ts_unitsymbol": unitsymbol,
            "columns": "Timestamp,Value,Quality Code,Quality Code Name",
            "data": rows,
        }
    ]
    return TransportResponse(
        content=json.dumps(payload).encode("utf-8"),
        status_code=status_code,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/json",
        url=request.url,
        request_parameters=dict(request.params or {}),
    )


@pytest.mark.parametrize(
    ("station", "product_id", "raw_unit", "expected_unit", "raw_value", "expected_value"),
    [
        ("1046", "discharge_daily_mean", "m³/s", "m3/s", 12.4, 12.4),
        ("1046", "stage_daily_mean", "m", "m", 1.25, 1.25),
        ("7102", "stage_absolute_daily_mean", "m", "m", 60.4, 60.4),
        ("7102", "water_temperature_daily_mean", "°C", "degC", 14.2, 14.2),
    ],
)
def test_public_fetch_picked_by_catalogue_series_id_returns_matching_rows(
    monkeypatch: pytest.MonkeyPatch,
    station: str,
    product_id: str,
    raw_unit: str,
    expected_unit: str,
    raw_value: float,
    expected_value: float,
) -> None:
    selection = _select_products(station, product_id)
    cat_frame = rr.series(selection)
    assert cat_frame.height == 1
    cat_series_id = cat_frame["series_id"][0]
    cat_facts_id = cat_frame["facts_id"][0]
    ts_id = selection.series[0].identity.published_id
    assert ts_id is not None
    spec = PRODUCT_BY_ID[product_id]
    native_coord = spec.native_id
    param_name = spec.stationparameter_names[0]

    class _ParityTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            assert params["request"] == "getTimeseriesValues"
            assert params["timezone"] == "UTC"
            assert params["ts_id"] == ts_id
            return _kiwis_response(
                request,
                ts_id=ts_id,
                ts_name=native_coord,
                station_no=station,
                param_name=param_name,
                unitsymbol=raw_unit,
                rows=[["2025-12-31T23:00:00.000Z", raw_value, 10, "Validé"]],
            )

    monkeypatch.setattr(discovery, "HttpClient", _ParityTransport)

    unpicked = rr.fetch(selection, start="2026-01-01", end="2026-01-01", cache="bypass")
    assert [issue.code for issue in unpicked.issues] == ["provenance.license_not_established"]
    assert unpicked.data["series_id"].to_list() == [cat_series_id]
    assert unpicked.data["facts_id"].to_list() == [cat_facts_id]

    picked = rr.pick(selection, series_id=[cat_series_id])
    assert isinstance(picked, _Selection)
    result = rr.fetch(picked, start="2026-01-01", end="2026-01-01", cache="bypass")
    assert [issue.code for issue in result.issues] == ["provenance.license_not_established"]
    assert result.data.height == 1
    assert result.data["series_id"].to_list() == [cat_series_id]
    assert result.data["facts_id"].to_list() == [cat_facts_id]
    assert result.data["unit"].to_list() == [expected_unit]
    assert result.data["time_zone"].to_list() == ["+01:00"]
    assert result.data["time"].to_list() == [datetime(2026, 1, 1, 0, 0)]
    assert result.data["value"].to_list() == [pytest.approx(expected_value)]
    assert [o.status for o in result.outcomes] == [OutcomeStatus.SUCCESS]
    assert rr.series(result)["series_id"].to_list() == [cat_series_id]
    assert rr.series(result)["facts_id"].to_list() == [cat_facts_id]


def test_public_all_62_products_units_annotations_utc_provenance_and_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    # Select one representative station/series per product across all 62 products.
    all_sel = rr.find(provider="be_wal")
    selected_series_ids: list[str] = []
    ts_meta: dict[str, tuple[str, str, str, str, str]] = {}
    for spec in PRODUCT_SPECS:
        station = _FAMILY_STATION[spec.family]
        matches = [s for s in all_sel.series if s.station_id == station and s.product_id == spec.product_id]
        assert len(matches) == 1, (station, spec.product_id)
        item = matches[0]
        assert item.identity.published_id is not None
        selected_series_ids.append(item.series_id)
        ts_meta[item.identity.published_id] = (
            spec.product_id,
            station,
            spec.native_id,
            spec.stationparameter_names[0],
            spec.source_unit,
        )

    picked = rr.pick(all_sel, series_id=selected_series_ids)
    assert isinstance(picked, _Selection)
    assert len(picked.series) == 62

    class _All62Transport:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            params = dict(request.params or {})
            ts_id = str(params["ts_id"])
            product_id, station, native_id, param_name, source_unit = ts_meta[ts_id]
            if product_id == "water_temperature_hourly_min":
                row: list[object] = ["2023-12-31T23:00:00.000Z", None, -1, None]
            elif product_id == "discharge_daily_max":
                row = ["2023-12-31T23:00:00.000Z", 18.5, 200, "Unknown"]
            elif source_unit == "°C":
                row = ["2023-12-31T23:00:00.000Z", 9.5, 10, "Validé"]
            elif source_unit == "m":
                row = ["2023-12-31T23:00:00.000Z", 2.25, 10, "Validé"]
            else:
                row = ["2023-12-31T23:00:00.000Z", 11.5, 10, "Validé"]
            return _kiwis_response(
                request,
                ts_id=ts_id,
                ts_name=native_id,
                station_no=station,
                param_name=param_name,
                unitsymbol=source_unit,
                rows=[row],
            )

    transport = _All62Transport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    result = rr.fetch(picked, start="2024-01-01", end="2024-01-01T23:59:59", cache="bypass", receipts=True)
    assert transport.calls == len(PRODUCT_SPECS) == 62
    assert [issue.code for issue in result.issues] == ["provenance.license_not_established"]
    assert result.receipts is not None and len(result.receipts.entries) == 62
    assert result.data["product_id"].n_unique() == 62
    assert result.data.height == 62
    assert result.data["time_zone"].unique().to_list() == ["+01:00"]
    assert set(result.data["unit"]) == {"m3/s", "m", "degC"}

    wt_min = result.data.filter(pl.col("product_id") == "water_temperature_hourly_min")
    assert wt_min["value"].to_list() == [None]

    ann_catalog = rr.annotations(result)
    assert ann_catalog["schema"].unique().to_list() == [BE_WAL_QUALITY_SCHEMA.schema_id]
    assert ann_catalog["name"].to_list() == ["quality_code", "quality_code_name"]
    assert ann_catalog["unmeasured_count"].unique().to_list() == [0]
    ann_df = rr.annotations(result, schema=BE_WAL_QUALITY_SCHEMA.schema_id)
    assert ann_df.height == 62
    assert ann_df.filter(pl.col("measured")).height == 62
    assert ann_df.filter((pl.col("quality_code") == -1) & pl.col("quality_code_name").is_null()).height == 1
    assert ann_df.filter((pl.col("quality_code") == 200) & (pl.col("quality_code_name") == "Unknown")).height == 1
    assert ann_df.filter((pl.col("quality_code") == 10) & (pl.col("quality_code_name") == "Validé")).height == 60

    utc_result = rr.to_utc(result)
    assert utc_result.data.height == 62
    assert utc_result.data["time_zone"].unique().to_list() == ["+00:00"]
    assert utc_result.data["time"].unique().to_list() == [datetime(2023, 12, 31, 23, 0)]

    acq = result.provenance.acquisition_provenance
    assert acq is not None and acq.header is not None
    statements = [stmt for record in acq.header.source_records for stmt in record.statements]
    assert not any(stmt.kind == "license" for stmt in statements)
    assert any(
        stmt.kind == "citation" and stmt.exact_text is not None and "Service public de Wallonie" in stmt.exact_text
        for stmt in statements
    )
    assert any(
        stmt.kind == "terms"
        and stmt.exact_text is not None
        and "Le SPW est seul habilité à distribuer les données" in stmt.exact_text
        for stmt in statements
    )

    restored = rr.from_bundle(rr.to_bundle(result))
    assert isinstance(restored, ObservationResult)
    assert_frame_equal(restored.data, result.data)
    assert_frame_equal(
        rr.annotations(restored, schema=BE_WAL_QUALITY_SCHEMA.schema_id),
        ann_df,
    )


def test_public_multichunk_999999z_dedup_and_cache_reuse(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    calls = 0
    selection = _select_products("1046", "discharge_complete")
    ts_id = selection.series[0].identity.published_id
    assert ts_id is not None

    class _ChunkedTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            nonlocal calls
            calls += 1
            params = dict(request.params or {})
            if params["from"] == "2023-12-30T00:00:00Z":
                assert params["to"] == "2024-12-28T23:59:59.999999Z"
                # Simulate KiWIS treating .999999Z as +16m39s into Chunk 2's hour.
                rows = [
                    ["2024-12-28T23:55:00.000Z", 5.0, 10, "Validé"],
                    ["2024-12-29T00:00:00.000Z", 6.0, 10, "Validé"],
                    ["2024-12-29T00:05:00.000Z", 7.0, 10, "Validé"],
                ]
            else:
                assert params["from"] == "2024-12-29T00:00:00Z"
                rows = [
                    ["2024-12-29T00:00:00.000Z", 6.0, 10, "Validé"],
                    ["2024-12-29T00:05:00.000Z", 7.0, 10, "Validé"],
                ]
            return _kiwis_response(
                request,
                ts_id=ts_id,
                ts_name="05-Debit.Complet",
                station_no="1046",
                param_name="Débit",
                unitsymbol="m³/s",
                rows=rows,
            )

    monkeypatch.setattr(discovery, "HttpClient", _ChunkedTransport)
    sid = rr.series(selection)["series_id"][0]
    picked = rr.pick(selection, series_id=[sid])
    assert isinstance(picked, _Selection)

    first = rr.fetch(picked, start="2024-01-01", end="2024-12-31T23:59:59", cache="reuse")
    assert calls == 2
    assert [issue.code for issue in first.issues] == ["provenance.license_not_established"]
    assert first.data["time"].to_list() == [
        datetime(2024, 12, 29, 0, 55),
        datetime(2024, 12, 29, 1, 0),
        datetime(2024, 12, 29, 1, 5),
    ]
    assert first.data["value"].to_list() == pytest.approx([5.0, 6.0, 7.0])

    reused = rr.fetch(picked, start="2024-01-01", end="2024-12-31T23:59:59", cache="reuse")
    assert calls == 2
    assert_frame_equal(reused.data, first.data)


def test_public_failure_isolation_empty_and_closed_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    selected = _select_products("1046", "discharge_daily_mean", "stage_daily_mean")
    q_ts_id = next(s.identity.published_id for s in selected.series if s.product_id == "discharge_daily_mean")
    assert q_ts_id is not None

    class _FaultTransport:
        def __init__(self) -> None:
            self.fail_all_code: int | None = None
            self.return_empty: bool = False

        def send(self, request: TransportRequest) -> TransportResponse:
            if self.fail_all_code is not None:
                _raise_http_failure(request, self.fail_all_code)
            params = dict(request.params or {})
            if self.return_empty:
                return _kiwis_response(
                    request,
                    ts_id=q_ts_id,
                    ts_name="20-Debit.Jour.Moyen",
                    station_no="1046",
                    param_name="Débit",
                    unitsymbol="m³/s",
                    rows=[],
                )
            if params["ts_id"] == q_ts_id:
                return _kiwis_response(
                    request,
                    ts_id=q_ts_id,
                    ts_name="20-Debit.Jour.Moyen",
                    station_no="1046",
                    param_name="Débit",
                    unitsymbol="m³/s",
                    rows=[["2023-12-31T23:00:00.000Z", 9.4, 10, "Validé"]],
                )
            _raise_http_failure(request, 503)

    fault = _FaultTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: fault)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        partial = rr.fetch(selected, start="2024-01-01", end="2024-01-01", cache="reuse", on_issue="warn")
    assert caught
    assert partial.data["product_id"].to_list() == ["discharge_daily_mean"]
    assert partial.data["value"].to_list() == pytest.approx([9.4])
    assert {o.product_id: o.status for o in partial.outcomes} == {
        "discharge_daily_mean": OutcomeStatus.SUCCESS,
        "stage_daily_mean": OutcomeStatus.FAILED,
    }

    q_only = _select_products("1046", "discharge_daily_mean")
    fault.fail_all_code = 503
    with pytest.raises(IssuePolicyError):
        rr.fetch(q_only, start="2024-01-01", end="2024-01-01", cache="refresh", on_issue="raise")
    retained = rr.fetch(q_only, start="2024-01-01", end="2024-01-01", cache="refresh", on_issue="ignore")
    assert retained.data["value"].to_list() == pytest.approx([9.4])

    fault.fail_all_code = None
    fault.return_empty = True
    empty_res = rr.fetch(q_only, start="2030-01-01", end="2030-01-02", cache="bypass")
    assert {issue.code for issue in empty_res.issues} == {
        "provenance.license_not_established",
        "request.future_end",
    }
    assert empty_res.data.is_empty()
    assert [o.status for o in empty_res.outcomes] == [OutcomeStatus.EMPTY]

    # Unestablished time_zone and excluded stations fail closed before touching HttpClient.
    monkeypatch.setattr(discovery, "HttpClient", lambda: pytest.fail("closed failure must not touch network"))
    empty_tz = rr.find(provider="be_wal", station="1046", time_zone="Europe/Brussels")
    with pytest.raises(EmptySelectionError, match="be_wal"):
        rr.fetch(empty_tz, start="2024-01-01", end="2024-01-01")
    for excluded_station in ("640601", "7406", "9109"):
        with pytest.raises(UnknownStationError):
            rr.find(provider="be_wal", station=excluded_station)

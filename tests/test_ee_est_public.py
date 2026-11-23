"""Public Estonia Keskkonnaagentuur (`ee_est`) retrieval, series_id parity, annotations, and isolation tests."""

from __future__ import annotations

import json
import warnings
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
from rivretrieve._internal.providers.ee_est.annotations import EE_EST_ESTMODEL_SCHEMA
from rivretrieve._internal.providers.ee_est.series import PRODUCT_SPECS
from rivretrieve._internal.selection import UnknownStationError
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_RETRIEVED_AT = datetime(2026, 11, 23, 13, 30, tzinfo=UTC)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _select_products(station: str, *products: str) -> rr.Selection:
    selected = rr.find(provider="ee_est", station=station)
    series_ids = rr.as_frame(selected).filter(pl.col("product_id").is_in(products))["series_id"].to_list()
    assert len(series_ids) == len(products)
    return rr.pick(selected, series_id=series_ids)


def _raise_http_failure(request: TransportRequest, status_code: int = 503) -> NoReturn:
    raise TransportFailure(
        request,
        TransportFailureReason.HTTP_STATUS,
        1,
        status_code=status_code,
        category=TransportFailureCategory.HTTP_STATUS,
    )


def _json_response(request: TransportRequest, payload: object, status_code: int = 200) -> TransportResponse:
    return TransportResponse(
        content=json.dumps(payload).encode("utf-8"),
        status_code=status_code,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/json",
        url=request.url,
        request_parameters=dict(request.params or {}),
    )


@pytest.mark.parametrize(
    ("product_id", "raw_value", "expected_value", "expected_zone"),
    [
        ("stage_daily_mean", -0.23, -0.23, "unknown"),
        ("stage_hourly_mean", -24.5, -0.245, "+00:00"),
    ],
)
def test_public_fetch_picked_by_catalogue_series_id_returns_matching_rows(
    monkeypatch: pytest.MonkeyPatch,
    product_id: str,
    raw_value: float,
    expected_value: float,
    expected_zone: str,
) -> None:
    class _ParityTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            if "estmodel.envir.ee" in request.url:
                return _json_response(
                    request,
                    [
                        {
                            "parameter": "H",
                            "startDate": "2026-01-01",
                            "endDate": "2026-01-01",
                            "value": raw_value,
                            "unit": "m",
                            "qualityFlag": "UNCHECKED",
                        }
                    ],
                )
            return _json_response(
                request,
                [
                    {
                        "jaam_kood": 41061,
                        "aegrida_nimi": "WL avg",
                        "timeline_ts_utc": "2026-01-01T00:00:00",
                        "vaartus": raw_value,
                    }
                ],
            )

    monkeypatch.setattr(discovery, "HttpClient", _ParityTransport)
    selection = _select_products("SJA8821000", product_id)
    cat_frame = rr.series(selection)
    assert cat_frame.height == 1
    cat_series_id = cat_frame["series_id"][0]
    cat_facts_id = cat_frame["facts_id"][0]

    unpicked = rr.fetch(selection, start="2026-01-01", end="2026-01-01", cache="bypass")
    assert unpicked.issues == ()
    assert unpicked.data["series_id"].to_list() == [cat_series_id]
    assert unpicked.data["facts_id"].to_list() == [cat_facts_id]

    picked = rr.pick(selection, series_id=[cat_series_id])
    result = rr.fetch(picked, start="2026-01-01", end="2026-01-01", cache="bypass")

    assert result.issues == ()
    assert result.data.height == 1
    assert result.data["series_id"].to_list() == [cat_series_id]
    assert result.data["facts_id"].to_list() == [cat_facts_id]
    assert result.data["unit"].to_list() == ["m"]
    assert result.data["time_zone"].to_list() == [expected_zone]
    assert result.data["value"].to_list() == [pytest.approx(expected_value)]
    assert [o.status for o in result.outcomes] == [OutcomeStatus.SUCCESS]
    assert rr.series(result)["series_id"].to_list() == [cat_series_id]
    assert rr.series(result)["facts_id"].to_list() == [cat_facts_id]


def test_public_fetch_picked_by_catalogue_series_id_reuses_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = 0

    class _CacheTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            nonlocal calls
            calls += 1
            if "estmodel.envir.ee" in request.url:
                start_year = int((request.params or {})["start-year"])
                year_date = "2024-12-31" if start_year <= 2024 else "2026-01-01"
                rows = [{"parameter": "Q", "startDate": year_date, "endDate": year_date, "value": 3.5, "unit": "m³/s"}]
                return _json_response(request, rows)
            return _json_response(
                request,
                [
                    {
                        "jaam_kood": 41061,
                        "aegrida_nimi": "WL avg",
                        "timeline_ts_utc": "2026-01-01T00:00:00",
                        "vaartus": 120.0,
                    }
                ],
            )

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", _CacheTransport)

    # Multi-chunk EstModel daily (2000..2026) picked by catalogue series_id hits cache on replay.
    em_sel = _select_products("SJA8821000", "discharge_daily_mean")
    em_sid = rr.series(em_sel)["series_id"][0]
    em_picked = rr.pick(em_sel, series_id=[em_sid])
    em_first = rr.fetch(em_picked, start="2000-01-01", end="2026-01-01", cache="reuse")
    assert calls == 2
    em_reused = rr.fetch(em_picked, start="2000-01-01", end="2026-01-01", cache="reuse")
    assert calls == 2
    assert_frame_equal(em_reused.data, em_first.data)

    # Single-chunk f_hydroseire hourly picked by catalogue series_id hits cache on replay.
    fh_sel = _select_products("SJA8821000", "stage_hourly_mean")
    fh_sid = rr.series(fh_sel)["series_id"][0]
    fh_picked = rr.pick(fh_sel, series_id=[fh_sid])
    fh_first = rr.fetch(fh_picked, start="2026-01-01", end="2026-01-01", cache="reuse")
    assert calls == 3
    fh_reused = rr.fetch(fh_picked, start="2026-01-01", end="2026-01-01", cache="reuse")
    assert calls == 3
    assert_frame_equal(fh_reused.data, fh_first.data)


def test_public_all_18_products_units_annotations_utc_and_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    unit_map = {"Q": "m³/s", "H": "m", "T": "°C"}

    class _All18Transport:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            params = dict(request.params or {})
            if "estmodel.envir.ee" in request.url:
                param = params["parameter"]
                rows = [
                    {
                        "parameter": param,
                        "startDate": "2025-12-31",
                        "endDate": "2025-12-31",
                        "value": 5.0,
                        "unit": unit_map[param],
                    },
                    {
                        "parameter": param,
                        "startDate": "2026-01-01",
                        "endDate": "2026-01-01",
                        "value": 6.0,
                        "unit": unit_map[param],
                        **({} if param == "T" else {"qualityFlag": "UNCHECKED"}),
                    },
                ]
                return _json_response(request, rows)
            assert request.headers.get("Accept-Profile") == "apijahiala"
            aegrida = params["aegrida_nimi"].removeprefix("eq.")
            val = 123.0 if aegrida.startswith("WL ") else None if aegrida == "WT min" else 4.5
            return _json_response(
                request,
                [
                    {
                        "jaam_kood": 41061,
                        "aegrida_nimi": aegrida,
                        "timeline_ts_utc": "2026-01-01T00:00:00",
                        "vaartus": val,
                    }
                ],
            )

    transport = _All18Transport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    selection = rr.find(provider="ee_est", station="SJA8821000")
    assert len(selection.series) == 18
    result = rr.fetch(selection, start="2025-12-31", end="2026-01-01", cache="bypass", receipts=True)
    assert transport.calls == len(PRODUCT_SPECS) == 18
    assert result.issues == ()
    assert result.receipts is not None and len(result.receipts.entries) == 18
    assert result.data["product_id"].n_unique() == 18
    assert result.data.height == 27  # 9 * 2 EstModel rows + 9 * 1 f_hydroseire rows

    fh_stage = result.data.filter(pl.col("product_id").str.starts_with("stage_hourly_"))
    assert fh_stage.height == 3
    assert fh_stage["source_unit"].unique().to_list() == ["cm"]
    assert fh_stage["unit"].unique().to_list() == ["m"]
    assert fh_stage["value"].to_list() == pytest.approx([1.23, 1.23, 1.23])

    wt_min = result.data.filter(pl.col("product_id") == "water_temperature_hourly_min")
    assert wt_min["value"].to_list() == [None]

    ann_catalog = rr.annotations(result)
    assert ann_catalog["schema"].to_list() == [EE_EST_ESTMODEL_SCHEMA.schema_id]
    ann_df = rr.annotations(result, schema=EE_EST_ESTMODEL_SCHEMA.schema_id)
    assert ann_df.height == 18
    assert ann_df.filter(pl.col("qualityFlag") == "UNCHECKED").height == 6
    assert ann_df.filter(pl.col("qualityFlag").is_null()).height == 12

    hourly_only = rr.pick(result, frequency="hourly")
    utc_hourly = rr.to_utc(hourly_only)
    assert utc_hourly.data.height == 9

    statements = [
        stmt for record in result.provenance.acquisition_provenance.header.source_records for stmt in record.statements
    ]
    assert any(stmt.kind == "license" and stmt.exact_text == "CC BY 4.0" for stmt in statements)
    assert any(stmt.kind == "citation" and "Keskkonnaagentuur" in stmt.exact_text for stmt in statements)

    restored = rr.from_bundle(rr.to_bundle(result))
    assert_frame_equal(restored.data, result.data)
    assert_frame_equal(
        rr.annotations(restored, schema=EE_EST_ESTMODEL_SCHEMA.schema_id),
        ann_df,
    )


def test_public_failure_isolation_empty_rowcap_and_closed_timezone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    selected = _select_products("SJA8821000", "discharge_daily_mean", "stage_daily_mean")

    class _FaultTransport:
        def __init__(self) -> None:
            self.fail_all_code: int | None = None

        def send(self, request: TransportRequest) -> TransportResponse:
            if self.fail_all_code is not None:
                _raise_http_failure(request, self.fail_all_code)
            if (request.params or {}).get("parameter") == "Q":
                return _json_response(
                    request,
                    [
                        {
                            "parameter": "Q",
                            "startDate": "2024-01-01",
                            "endDate": "2024-01-01",
                            "value": 9.4,
                            "unit": "m³/s",
                        }
                    ],
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

    q_only = _select_products("SJA8821000", "discharge_daily_mean")
    fault.fail_all_code = 503
    with pytest.raises(IssuePolicyError):
        rr.fetch(q_only, start="2024-01-01", end="2024-01-01", cache="refresh", on_issue="raise")
    retained = rr.fetch(q_only, start="2024-01-01", end="2024-01-01", cache="refresh", on_issue="ignore")
    assert retained.data["value"].to_list() == pytest.approx([9.4])

    # Unestablished time_zone and excluded station fail closed before touching HttpClient.
    monkeypatch.setattr(discovery, "HttpClient", lambda: pytest.fail("closed failure must not touch network"))
    empty_tz = rr.find(provider="ee_est", station="SJA8821000", time_zone="Europe/Tallinn")
    with pytest.raises(EmptySelectionError, match="ee_est"):
        rr.fetch(empty_tz, start="2024-01-01", end="2024-01-01")
    with pytest.raises(UnknownStationError):
        rr.find(provider="ee_est", station="SJA4875000")

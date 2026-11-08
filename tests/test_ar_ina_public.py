"""Public Argentina INA Alerta5 discovery, retrieval, failure isolation, and cache controls."""

from __future__ import annotations

import json
import socket
import warnings
from datetime import UTC, datetime, timedelta
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
from rivretrieve._internal.providers.ar_ina.series import IN_SCOPE_SERIES_SPECS, SPECS_BY_PRODUCT_ID
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_RETRIEVED_AT = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
_SERIES_URL = "https://alerta.ina.gob.ar/a5/obs/puntual/series"

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _raise_http_failure(request: TransportRequest, status_code: int = 503) -> NoReturn:
    raise TransportFailure(
        request,
        TransportFailureReason.HTTP_STATUS,
        1,
        status_code=status_code,
        category=TransportFailureCategory.HTTP_STATUS,
    )


def _obs_bytes(rows: list[dict[str, object]]) -> bytes:
    return json.dumps(rows).encode("utf-8")


def _obs_row(
    *,
    obs_id: int | None,
    series_id: int,
    timestart: str,
    timeend: str,
    valor: float | None,
) -> dict[str, object]:
    return {
        "id": obs_id,
        "tipo": "puntual",
        "series_id": series_id,
        "timestart": timestart,
        "timeend": timeend,
        "valor": valor,
    }


def _interval_end_iso(start_utc: datetime, *, is_instantaneous: bool) -> str:
    end_utc = start_utc if is_instantaneous else start_utc + timedelta(hours=1)
    return end_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _series_lookup_bytes(
    *,
    station_id: int,
    product_id: str,
    series_ids: tuple[int, ...],
) -> bytes:
    spec = SPECS_BY_PRODUCT_ID[product_id]
    cutoff = (
        {
            "years": 0,
            "months": 0,
            "days": 0,
            "hours": 0,
            "minutes": 0,
            "seconds": 0,
            "milliseconds": 0,
        }
        if spec.requires_midnight_cutoff
        else None
    )
    return json.dumps(
        {
            "total": len(series_ids),
            "is_last_page": True,
            "rows": [
                {
                    "id": sid,
                    "tipo": "puntual",
                    "estacion": {"id": station_id, "nombre": f"Station {station_id}"},
                    "var": {
                        "id": spec.var_id,
                        "var": spec.var_code,
                        "datatype": spec.expected_datatype,
                        "timeSupport": spec.expected_time_support,
                        "def_hora_corte": cutoff,
                    },
                    "procedimiento": {"id": spec.proc_id, "abrev": "medicion" if spec.proc_id == 1 else "curva"},
                    "unidades": {"id": spec.expected_unit_id, "abrev": spec.expected_unit_abrev},
                }
                for sid in series_ids
            ],
        }
    ).encode("utf-8")


def test_public_discovery_is_network_free_after_live_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbid_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("ar_ina offline discovery must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(socket, "create_connection", forbid_network)

    selected = rr.find(provider="ar_ina", station="8")
    frame = rr.as_frame(selected)
    assert frame.height == 10
    assert {"discharge_daily_mean", "stage_daily_mean"} <= set(frame["product_id"].to_list())
    assert rr.describe("ar_ina")["license"] == "Creative Commons Atribución 4.0 Internacional"


def test_public_all_13_products_units_negative_stage_and_historical_dst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_products = {spec.product_id for spec in IN_SCOPE_SERIES_SPECS}
    assert len(expected_products) == 13
    assert set(rr.products("ar_ina")) == expected_products

    # Pick one real catalogued station-series per admitted product from the packaged catalogue.
    base_selection = rr.find(provider="ar_ina", station=["8", "52", "9", "2112"])
    all_ar = rr.as_frame(base_selection)
    chosen_series_ids: list[str] = []
    payload_by_pub_id: dict[str, bytes] = {}
    t1 = datetime(2009, 3, 14, 2, 0, tzinfo=UTC)  # Pre-2009 Argentina DST midnight (UTC-02:00)
    t2 = datetime(2009, 3, 15, 3, 0, tzinfo=UTC)  # Standard-time midnight (UTC-03:00)
    for index, spec in enumerate(IN_SCOPE_SERIES_SPECS):
        first_row = all_ar.filter(pl.col("product_id") == spec.product_id).sort("station_id").row(0, named=True)
        chosen_series_ids.append(str(first_row["series_id"]))
        pub_id = int(str(first_row["variant"]))
        sample_val = -0.27 if spec.product_id == "stage_monthly_min" else (0.0 if index == 0 else 10.5 + index)
        rows = [
            _obs_row(
                obs_id=100_000 + index * 10 + 1,
                series_id=pub_id,
                timestart=t1.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                timeend=_interval_end_iso(t1, is_instantaneous=spec.is_instantaneous),
                valor=sample_val,
            ),
            _obs_row(
                obs_id=100_000 + index * 10 + 2,
                series_id=pub_id,
                timestart=t2.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                timeend=_interval_end_iso(t2, is_instantaneous=spec.is_instantaneous),
                valor=sample_val + 1.0,
            ),
        ]
        payload_by_pub_id[str(pub_id)] = _obs_bytes(rows)

    class _AllProductsTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            params = dict(request.params or {})
            assert params.get("skip_nulls") == "true"
            parts = request.url.rstrip("/").split("/")
            assert parts[-1] == "observaciones"
            pub_id = parts[-2]
            return TransportResponse(
                payload_by_pub_id[pub_id],
                200,
                _RETRIEVED_AT,
                "application/json; charset=utf-8",
                request.url,
                params,
            )

    transport = _AllProductsTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    selection = rr.pick(base_selection, series_id=chosen_series_ids)
    result = rr.fetch(
        selection,
        start="2009-03-14",
        end="2009-03-15",
        cache="bypass",
        receipts=True,
        on_issue="raise",
    )

    assert len(transport.requests) == 13
    assert result.receipts is not None and len(result.receipts.entries) == 13
    assert set(result.data["product_id"].unique().to_list()) == expected_products
    assert result.data.height == 26
    assert result.data["time_zone"].unique().to_list() == ["+00:00"]
    assert {ts.hour for ts in result.data["time"].to_list()} == {2, 3}

    discharge_rows = result.data.filter(pl.col("quantity") == "discharge")
    assert discharge_rows["source_unit"].unique().to_list() == ["m^3/s"]
    assert discharge_rows["unit"].unique().to_list() == ["m3/s"]
    assert 0.0 in discharge_rows["value"].to_list()

    stage_rows = result.data.filter(pl.col("quantity") == "stage")
    assert stage_rows["source_unit"].unique().to_list() == ["m"]
    assert stage_rows["unit"].unique().to_list() == ["m"]
    min_stage = stage_rows.filter(pl.col("product_id") == "stage_monthly_min").sort("time")["value"].to_list()[0]
    assert min_stage == pytest.approx(-0.27)

    # Provenance carries verified CC BY 4.0 license and unestablished citation info issue.
    assert result.provenance.license == "Creative Commons Atribución 4.0 Internacional"
    assert result.provenance.citation is None
    assert any(
        issue.code == "provenance.citation_not_established" and issue.severity == "info" for issue in result.issues
    )

    # Result bundle round-trips losslessly without touching the network.
    restored = rr.from_bundle(rr.to_bundle(result))
    assert isinstance(restored, ObservationResult)
    assert_frame_equal(restored.data, result.data)


def test_public_stored_db_nulls_synthesized_boundary_nulls_and_empty_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Station 8 discharge_daily_mean -> published series_id 26605.
    selection = rr.find(provider="ar_ina", station="8", quantity="discharge", frequency="daily", statistic="mean")
    assert [item.identity.published_id for item in selection.series] == ["26605"]

    mixed_body = _obs_bytes(
        [
            # Counterfeit generateRegularSeries boundary null (id is None, valor is None).
            _obs_row(
                obs_id=None,
                series_id=26605,
                timestart="2024-01-01T03:00:00.000Z",
                timeend="2024-01-02T03:00:00.000Z",
                valor=None,
            ),
            # Genuine stored observation.
            _obs_row(
                obs_id=9001,
                series_id=26605,
                timestart="2024-01-02T03:00:00.000Z",
                timeend="2024-01-03T03:00:00.000Z",
                valor=845.25,
            ),
            # Genuine stored database null interval (id > 0, valor is None -> preserved as value=None).
            _obs_row(
                obs_id=9002,
                series_id=26605,
                timestart="2024-01-03T03:00:00.000Z",
                timeend="2024-01-04T03:00:00.000Z",
                valor=None,
            ),
            # Genuine zero discharge.
            _obs_row(
                obs_id=9003,
                series_id=26605,
                timestart="2024-01-04T03:00:00.000Z",
                timeend="2024-01-05T03:00:00.000Z",
                valor=0.0,
            ),
        ]
    )

    state = {"empty": False}

    class _GapTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            body = _obs_bytes([]) if state["empty"] else mixed_body
            return TransportResponse(
                body,
                200,
                _RETRIEVED_AT,
                "application/json; charset=utf-8",
                request.url,
                dict(request.params or {}),
            )

    monkeypatch.setattr(discovery, "HttpClient", _GapTransport)

    # Info issues never raise under on_issue="raise"; synthesized grid nulls are omitted while stored DB nulls survive.
    result = rr.fetch(selection, start="2024-01-01", end="2024-01-04", cache="bypass", on_issue="raise")
    ordered_vals = result.data.sort("time")["value"].to_list()
    assert len(ordered_vals) == 3
    assert ordered_vals[0] == pytest.approx(845.25)
    assert ordered_vals[1] is None
    assert ordered_vals[2] == pytest.approx(0.0)
    codes = {issue.code: issue for issue in result.issues}
    assert "source.synthesized_grid_null" in codes and codes["source.synthesized_grid_null"].severity == "info"
    assert [item.status for item in result.outcomes] == [OutcomeStatus.SUCCESS]

    # Empty observation window yields EMPTY outcome without raising on_issue="raise".
    state["empty"] = True
    empty_res = rr.fetch(selection, start="1900-01-01", end="1900-01-05", cache="bypass", on_issue="raise")
    assert empty_res.data.is_empty()
    assert [item.status for item in empty_res.outcomes] == [OutcomeStatus.EMPTY]


def test_public_predicate_honesty_and_runtime_explicit_variant_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # stage_hourly statistic is not_established, so statistic="mean" leaves an empty selection.
    unmatched = rr.find(provider="ar_ina", station="52", quantity="stage", frequency="hourly", statistic="mean")
    assert len(unmatched.series) == 0
    with pytest.raises(EmptySelectionError) as exc_info:
        rr.fetch(unmatched, start="2024-01-01", end="2024-01-02")
    assert exc_info.value.reason.code == "unresolved_inventory"

    # Explicit uncatalogued variant on station 8 discharge_daily_mean triggers /obs/puntual/series lookup.
    unresolved_sel = rr.find(
        provider="ar_ina",
        station="8",
        quantity="discharge",
        frequency="daily",
        statistic="mean",
        variant="999999",
        on_issue="ignore",
    )
    assert any(issue.code == "selection.unresolved_inventory" for issue in unresolved_sel.issues)

    mode = {"found": True}

    class _LookupTransport:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.urls.append(request.url)
            params = dict(request.params or {})
            if request.url == _SERIES_URL:
                if mode["found"]:
                    body = _series_lookup_bytes(
                        station_id=8, product_id="discharge_daily_mean", series_ids=(26605, 999999)
                    )
                else:
                    body = _series_lookup_bytes(station_id=8, product_id="discharge_daily_mean", series_ids=(26605,))
                return TransportResponse(body, 200, _RETRIEVED_AT, "application/json", request.url, params)
            assert request.url.endswith("/999999/observaciones")
            obs = _obs_bytes(
                [
                    _obs_row(
                        obs_id=77,
                        series_id=999999,
                        timestart="2024-02-01T03:00:00.000Z",
                        timeend="2024-02-02T03:00:00.000Z",
                        valor=512.0,
                    )
                ]
            )
            return TransportResponse(obs, 200, _RETRIEVED_AT, "application/json", request.url, params)

    transport = _LookupTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    resolved = rr.fetch(unresolved_sel, start="2024-02-01", end="2024-02-01", cache="bypass", on_issue="raise")
    assert transport.urls == [_SERIES_URL, f"{_SERIES_URL}/999999/observaciones"]
    assert resolved.data["value"].to_list() == [pytest.approx(512.0)]
    assert any(issue.code == "selection.inventory_resolved" and issue.severity == "info" for issue in resolved.issues)

    # When /obs/puntual/series proves variant 999999 is absent, fetch records NO_MATCH without hitting /observaciones.
    mode["found"] = False
    transport.urls.clear()
    absent = rr.fetch(unresolved_sel, start="2024-02-01", end="2024-02-01", cache="bypass", on_issue="ignore")
    assert transport.urls == [_SERIES_URL]
    assert absent.data.is_empty()
    assert any(outcome.status is OutcomeStatus.NO_MATCH for outcome in absent.outcomes)


def test_public_sibling_failure_isolation_and_local_cache_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    # Select discharge_daily_mean (26605) and stage_daily_mean (26250) on station 8.
    station_8 = rr.find(provider="ar_ina", station="8", frequency="daily", statistic="mean")
    assert {item.product_id for item in station_8.series} == {"discharge_daily_mean", "stage_daily_mean"}

    q_body = _obs_bytes(
        [
            _obs_row(
                obs_id=1,
                series_id=26605,
                timestart="2024-03-01T03:00:00.000Z",
                timeend="2024-03-02T03:00:00.000Z",
                valor=700.0,
            ),
            _obs_row(
                obs_id=2,
                series_id=26605,
                timestart="2024-03-02T03:00:00.000Z",
                timeend="2024-03-03T03:00:00.000Z",
                valor=710.0,
            ),
        ]
    )
    h_body = _obs_bytes(
        [
            _obs_row(
                obs_id=3,
                series_id=26250,
                timestart="2024-03-01T03:00:00.000Z",
                timeend="2024-03-02T03:00:00.000Z",
                valor=2.45,
            ),
            _obs_row(
                obs_id=4,
                series_id=26250,
                timestart="2024-03-02T03:00:00.000Z",
                timeend="2024-03-03T03:00:00.000Z",
                valor=2.50,
            ),
        ]
    )

    class _SiblingTransport:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.fail_stage = True
            self.fail_all = False

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls.append(request.url)
            params = dict(request.params or {})
            if self.fail_all:
                _raise_http_failure(request, 503)
            if request.url.endswith("/26250/observaciones") and self.fail_stage:
                _raise_http_failure(request, 503)
            body = q_body if request.url.endswith("/26605/observaciones") else h_body
            return TransportResponse(body, 200, _RETRIEVED_AT, "application/json", request.url, params)

    replay = _SiblingTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    # 1. Partial sibling failure: discharge succeeds while stage HTTP 503 becomes FAILED + error issue.
    partial = rr.fetch(station_8, start="2024-03-01", end="2024-03-02", cache="bypass", on_issue="ignore")
    assert partial.data["product_id"].unique().to_list() == ["discharge_daily_mean"]
    assert partial.data.sort("time")["value"].to_list() == [pytest.approx(700.0), pytest.approx(710.0)]
    assert {o.product_id: o.status for o in partial.outcomes} == {
        "discharge_daily_mean": OutcomeStatus.SUCCESS,
        "stage_daily_mean": OutcomeStatus.FAILED,
    }
    assert any(i.code == "source.request_failed" and i.severity == "error" for i in partial.issues)

    # 2. Both series succeed and populate the local observation store under cache="reuse".
    replay.fail_stage = False
    replay.calls.clear()
    cached = rr.fetch(station_8, start="2024-03-01", end="2024-03-02", cache="reuse", on_issue="raise")
    assert len(replay.calls) == 2
    assert cached.data.height == 4

    # Sub-window repeat query under cache="reuse" issues 0 HTTP calls.
    reused = rr.fetch(station_8, start="2024-03-01", end="2024-03-01", cache="reuse", on_issue="raise")
    assert len(replay.calls) == 2
    assert reused.data.height == 2

    # cache_status and audit_cache validate the committed live store without network I/O.
    status = rr.cache_status("ar_ina")
    assert status.presence.value == "present"
    audit = rr.audit_cache("ar_ina")
    assert audit.rows_checked == 4

    # 3. Failed refresh raises on "raise", warns on "warn", and preserves held rows on "warn"/"ignore".
    replay.fail_all = True
    with pytest.raises(IssuePolicyError):
        rr.fetch(station_8, start="2024-03-01", end="2024-03-02", cache="refresh", on_issue="raise")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warned = rr.fetch(station_8, start="2024-03-01", end="2024-03-02", cache="refresh", on_issue="warn")
    assert caught
    assert_frame_equal(cached.data, warned.data)

    ignored = rr.fetch(station_8, start="2024-03-01", end="2024-03-02", cache="refresh", on_issue="ignore")
    assert_frame_equal(cached.data, ignored.data)
    assert any(i.severity == "error" for i in ignored.issues)

    # 4. clear_cache removes the accumulated store cleanly.
    cleared = rr.clear_cache("ar_ina")
    assert cleared.existed is True
    assert rr.cache_status("ar_ina").presence.value == "absent"

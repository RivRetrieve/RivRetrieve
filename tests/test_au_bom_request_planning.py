"""Source-independent tests for au_bom request planning, batching, single decode, and isolation."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.engine import ObservationRequest, RequestedWindow, WindowEndpoint
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.au_bom import parse as au_bom_parse
from rivretrieve._internal.providers.au_bom.declaration import declaration
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_RETRIEVED_AT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_DISCHARGE_24 = ProductId("discharge_daily_mean_24hr")
_DISCHARGE_09 = ProductId("discharge_daily_mean_09hr")


def _list_json(rows: list[tuple[str, str, str, str, str]]) -> bytes:
    header = ["ts_id", "ts_name", "parametertype_name", "ts_unitsymbol", "station_no"]
    return json.dumps(
        [header, *[[ts_id, ts_name, param, unit, st] for ts_id, ts_name, param, unit, st in rows]]
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


def test_au_bom_declares_request_planner() -> None:
    assert isinstance(declaration.observations, LiveStages)
    assert hasattr(declaration.observations.stages, "request_planner")


def test_au_bom_batches_list_25_and_values_20_out_of_order_single_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    stations = tuple(f"410{idx:03d}" for idx in range(1, 31))
    ts_by_station = {st: f"900{idx:03d}" for idx, st in enumerate(stations, start=1)}
    val_by_ts = {ts_id: float(idx) for idx, ts_id in enumerate(ts_by_station.values(), start=1)}

    list_batches: list[list[str]] = []
    values_batches: list[list[str]] = []

    class _BatchTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            kind = params.get("request")
            if kind == "getTimeseriesList":
                sts = [s for s in str(params["station_no"]).split(",") if s]
                assert 1 <= len(sts) <= 25
                list_batches.append(sts)
                body = _list_json(
                    [
                        (
                            ts_by_station[st],
                            "DMQaQc.Merged.DailyMean.24HR",
                            "Water Course Discharge",
                            "cumec",
                            st,
                        )
                        for st in sts
                    ]
                )
                return TransportResponse(body, 200, _RETRIEVED_AT, "application/json", request.url, params)
            assert kind == "getTimeseriesValues"
            ts_ids = [t for t in str(params["ts_id"]).split(",") if t]
            assert 2 <= len(ts_ids) <= 20
            values_batches.append(ts_ids)
            # Emit blocks in REVERSED order to verify out-of-order routing by ts_id.
            body = _values_json(
                [
                    (ts_id, [("2026-09-01T00:00:00.000+10:00", val_by_ts[ts_id], 10, "quality-A")])
                    for ts_id in reversed(ts_ids)
                ]
            )
            return TransportResponse(body, 200, _RETRIEVED_AT, "application/json", request.url, params)

    loads_calls = 0
    real_loads = au_bom_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == au_bom_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(au_bom_parse.json, "loads", _counted_loads)
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("au_bom"),
            stations,
            (_DISCHARGE_24,),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2026, 9, 1)),
                WindowEndpoint.from_datetime(datetime(2026, 9, 1, 23, 59, 59)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(source="bom", provider_id=ProviderId("au_bom"), requested_at=_RETRIEVED_AT),
        receipts=ReceiptMode.INCLUDE,
        transport=_BatchTransport(),
        cache="bypass",
    )
    assert [len(b) for b in list_batches] == [25, 5]
    assert [len(b) for b in values_batches] == [20, 10]
    # 2 getTimeseriesList + 2 getTimeseriesValues = 4 JSON decodes total (not per station).
    assert loads_calls == 4
    assert res.canonical_rows.height == 30
    values_by_st = {r["station_id"]: r["value"] for r in res.canonical_rows.select("station_id", "value").to_dicts()}
    for idx, st in enumerate(stations, start=1):
        assert values_by_st[st] == pytest.approx(float(idx))
    assert res.annotations.observation_tables["au_bom.quality"].row_count == 30


def test_au_bom_isolates_missing_wrong_unit_corrupt_missing_block_and_http_batch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    stations = ("410001", "410002", "410003", "410004", "410005")

    class _MixedTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            params = dict(request.params or {})
            if params["request"] == "getTimeseriesList":
                # 410002 omitted cleanly; 410003 has wrong unit l/s; 410001/4/5 healthy.
                body = _list_json(
                    [
                        ("1001", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec", "410001"),
                        ("1003", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "l/s", "410003"),
                        ("1004", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec", "410004"),
                        ("1005", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec", "410005"),
                    ]
                )
                return TransportResponse(body, 200, _RETRIEVED_AT, "application/json", request.url, params)
            # Only 1001, 1004, 1005 requested (410002 absent, 410003 excluded by wrong unit).
            assert params["ts_id"] == "1001,1004,1005"
            # 1004 has invalid UTC+00:00 timestamp; 1005 omitted from values response.
            body = _values_json(
                [
                    ("1001", [("2026-09-01T00:00:00.000+10:00", 12.5, 10, "quality-A")]),
                    ("1004", [("2026-09-01T00:00:00.000+00:00", 9.0, 10, "quality-A")]),
                ]
            )
            return TransportResponse(body, 200, _RETRIEVED_AT, "application/json", request.url, params)

    t1 = _MixedTransport()
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("au_bom"),
            stations,
            (_DISCHARGE_24,),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2026, 9, 1)),
                WindowEndpoint.from_datetime(datetime(2026, 9, 1, 23, 59, 59)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(source="bom", provider_id=ProviderId("au_bom"), requested_at=_RETRIEVED_AT),
        transport=t1,
        cache="bypass",
    )
    assert len(t1.requests) == 2
    assert res.canonical_rows["station_id"].to_list() == ["410001"]
    assert res.canonical_rows["value"].to_list() == [12.5]
    by_st = {o.station_id: o.status for o in res.outcomes}
    assert by_st == {
        "410001": OutcomeStatus.SUCCESS,
        "410002": OutcomeStatus.NO_MATCH,
        "410003": OutcomeStatus.UNSUPPORTED,
        "410004": OutcomeStatus.FAILED,
        "410005": OutcomeStatus.FAILED,
    }

    # Verify HTTP failure on one values batch (22 stations -> 20 fail, 2 succeed) isolates failure cleanly.
    batch22 = tuple(f"420{idx:03d}" for idx in range(1, 23))

    class _HttpFailBatchTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if params["request"] == "getTimeseriesList":
                sts = [s for s in str(params["station_no"]).split(",") if s]
                return TransportResponse(
                    _list_json(
                        [(st, "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec", st) for st in sts]
                    ),
                    200,
                    _RETRIEVED_AT,
                    "application/json",
                    request.url,
                    params,
                )
            ts_ids = [t for t in str(params["ts_id"]).split(",") if t]
            if len(ts_ids) == 20:
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=500,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            return TransportResponse(
                _values_json([(t, [("2026-09-01T00:00:00.000+10:00", 5.0, 10, "quality-A")]) for t in ts_ids]),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                params,
            )

    res22 = driver_module.drive(
        ObservationRequest(
            ProviderId("au_bom"),
            batch22,
            (_DISCHARGE_24,),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2026, 9, 1)),
                WindowEndpoint.from_datetime(datetime(2026, 9, 1, 23, 59, 59)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(source="bom", provider_id=ProviderId("au_bom"), requested_at=_RETRIEVED_AT),
        transport=_HttpFailBatchTransport(),
        cache="bypass",
    )
    assert set(res22.canonical_rows["station_id"].to_list()) == set(batch22[20:])
    assert sum(1 for o in res22.outcomes if o.status is OutcomeStatus.FAILED) == 20


def test_au_bom_single_station_preserves_per_product_values_calls_and_multi_station_cache_reuse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages

    class _SingleTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            params = dict(request.params or {})
            if params["request"] == "getTimeseriesList":
                return TransportResponse(
                    _list_json(
                        [
                            ("1573010", "DMQaQc.Merged.DailyMean.24HR", "Water Course Discharge", "cumec", "410730"),
                            ("1572010", "DMQaQc.Merged.DailyMean.09HR", "Water Course Discharge", "cumec", "410730"),
                        ]
                    ),
                    200,
                    _RETRIEVED_AT,
                    "application/json",
                    request.url,
                    params,
                )
            ts_id = str(params["ts_id"])
            label = "2026-09-01T00:00:00.000+10:00" if ts_id == "1573010" else "2026-09-01T09:00:00.000+10:00"
            return TransportResponse(
                _values_json([(ts_id, [(label, 7.5, 10, "quality-A")])]),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                params,
            )

    t_single = _SingleTransport()
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("au_bom"),
            ("410730",),
            (_DISCHARGE_24, _DISCHARGE_09),
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2026, 9, 1)),
                WindowEndpoint.from_datetime(datetime(2026, 9, 1, 23, 59, 59)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(source="bom", provider_id=ProviderId("au_bom"), requested_at=_RETRIEVED_AT),
        transport=t_single,
        cache="bypass",
    )
    list_reqs = [r for r in t_single.requests if (r.params or {}).get("request") == "getTimeseriesList"]
    val_reqs = [r for r in t_single.requests if (r.params or {}).get("request") == "getTimeseriesValues"]
    assert len(list_reqs) == 1
    assert [(r.params or {})["ts_id"] for r in val_reqs] == ["1573010", "1572010"]
    assert res.canonical_rows.height == 2

    # Public multi-station reuse: 3 real stations x stage_daily_mean -> 1 list + 1 values batch, reread -> 0 GETs.
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    stage_all = rr.find(provider="au_bom", quantity="stage", frequency="P1D", statistic="mean")
    three_stations = tuple(rr.as_frame(stage_all)["station_id"].unique().sort().head(3).to_list())
    stage_sel = rr.find(provider="au_bom", station=three_stations, quantity="stage", frequency="P1D", statistic="mean")

    class _PubTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            params = dict(request.params or {})
            if params["request"] == "getTimeseriesList":
                return TransportResponse(
                    _list_json(
                        [
                            (f"55{i}", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m", st)
                            for i, st in enumerate(three_stations, start=1)
                        ]
                    ),
                    200,
                    _RETRIEVED_AT,
                    "application/json",
                    request.url,
                    params,
                )
            ts_ids = str(params["ts_id"]).split(",")
            return TransportResponse(
                _values_json([(t, [("2026-09-01T00:00:00.000+10:00", 3.5, 10, "quality-A")]) for t in ts_ids]),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                params,
            )

    t_pub = _PubTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_pub)
    first = rr.fetch(stage_sel, start="2026-09-01", end="2026-09-01", cache="reuse", receipts=True, on_issue="raise")
    assert len(t_pub.requests) == 2
    assert first.data.height == 3
    reread = rr.fetch(stage_sel, start="2026-09-01", end="2026-09-01", cache="reuse", receipts=True, on_issue="raise")
    assert len(t_pub.requests) == 2
    assert reread.data.height == 3


def test_au_bom_single_station_differing_rendered_windows_across_uncached_products(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    sel_daily = rr.find(provider="au_bom", station="001101A", quantity="stage", frequency="P1D", statistic="mean")
    sel_multi = rr.find(provider="au_bom", station="001101A", quantity="stage")

    class _WindowMismatchTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            params = dict(request.params or {})
            if params["request"] == "getTimeseriesList":
                return TransportResponse(
                    _list_json(
                        [
                            ("801001", "DMQaQc.Merged.DailyMean.24HR", "Water Course Level", "m", "001101A"),
                            ("801002", "DMQaQc.Merged.HourlyMean.HR", "Water Course Level", "m", "001101A"),
                            ("801003", "DMQaQc.Merged.DailyMax.24HR", "Water Course Level", "m", "001101A"),
                            ("801004", "DMQaQc.Merged.DailyMin.24HR", "Water Course Level", "m", "001101A"),
                            ("801005", "DMQaQc.Merged.MonthlyMean.CalMonth", "Water Course Level", "m", "001101A"),
                            ("801006", "DMQaQc.Merged.YearlyMean.CalYear", "Water Course Level", "m", "001101A"),
                        ]
                    ),
                    200,
                    _RETRIEVED_AT,
                    "application/json",
                    request.url,
                    params,
                )
            ts_id = str(params["ts_id"])
            if ts_id == "801001":
                rows = [
                    ("2024-01-01T00:00:00.000+10:00", 1.1, 10, "quality-A"),
                    ("2024-01-02T00:00:00.000+10:00", 1.2, 10, "quality-A"),
                    ("2024-01-05T00:00:00.000+10:00", 1.5, 10, "quality-A"),
                ]
            elif ts_id == "801002":
                rows = [("2024-01-03T10:00:00.000+10:00", 2.3, 10, "quality-A")]
            else:
                rows = []
            return TransportResponse(
                _values_json([(ts_id, rows)]),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                params,
            )

    transport = _WindowMismatchTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    seeded = rr.fetch(sel_daily, start="2024-01-01", end="2024-01-02", cache="reuse", on_issue="raise")
    assert seeded.data.height == 2
    transport.requests.clear()

    mixed = rr.fetch(sel_multi, start="2024-01-01", end="2024-01-06T12:00:00", cache="reuse", on_issue="raise")
    list_reqs = [r for r in transport.requests if (r.params or {}).get("request") == "getTimeseriesList"]
    val_reqs = [r for r in transport.requests if (r.params or {}).get("request") == "getTimeseriesValues"]
    assert len(list_reqs) == 1
    assert len(val_reqs) == 6
    params_by_ts = {str((r.params or {})["ts_id"]): dict(r.params or {}) for r in val_reqs}
    assert set(params_by_ts) == {"801001", "801002", "801003", "801004", "801005", "801006"}
    assert params_by_ts["801001"]["to"] != params_by_ts["801002"]["to"]
    assert mixed.data.height == 4

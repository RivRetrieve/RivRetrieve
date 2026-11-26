"""Source-independent tests for no_nve request planning and batch acquisition."""

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
from rivretrieve._internal.providers.no_nve import parse as no_nve_parse
from rivretrieve._internal.providers.no_nve.declaration import declaration
from rivretrieve._internal.providers.no_nve.fetch import fetch
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.source_series import InventoryCompleteness, OutcomeStatus, RestrictionKind, SeriesScope
from rivretrieve._internal.transport import (
    HttpMethod,
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=UTC)


def _window(start: str, end: str) -> RequestedWindow:
    return RequestedWindow(
        WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
        WindowEndpoint.from_datetime(datetime.fromisoformat(end)),
    )


def _series_meta_json(
    station: str, parameter: int, version: int, resolutions: list[int], unit: str
) -> dict[str, object]:
    return {
        "stationId": station,
        "parameter": parameter,
        "versionNo": version,
        "unit": unit,
        "resolutionList": [{"resTime": res, "method": "Instantaneous" if res == 0 else "Mean"} for res in resolutions],
    }


def _obs_block(
    *,
    station: str,
    parameter: int,
    version: int,
    unit: str,
    method: str = "Mean",
    observations: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "stationId": station,
        "stationName": f"Station {station}",
        "parameter": parameter,
        "parameterName": "Param",
        "parameterNameEng": "Param",
        "method": method,
        "unit": unit,
        "serieVersionNo": version,
        "observationCount": len(observations),
        "observations": observations,
    }


def test_no_nve_declares_request_planner() -> None:
    assert isinstance(declaration.observations, LiveStages)
    assert hasattr(declaration.observations.stages, "request_planner")


def test_no_nve_series_lookup_dedup_explicit_skip_and_single_target_get(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages

    class _Transport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            if request.url.endswith("/Series"):
                params = request.params or {}
                station = str(params["StationId"])
                param = int(params["Parameter"])
                unit = {1000: "m", 1001: "m³/s", 1003: "°C"}[param]
                data = [_series_meta_json(station, param, 1, [0, 60, 1440], unit)]
                return TransportResponse(
                    url=request.url,
                    request_parameters=dict(params),
                    status_code=200,
                    retrieved_at=_utc(2026, 1, 2, 12),
                    content_type="application/json",
                    content=json.dumps({"itemCount": len(data), "data": data}).encode(),
                )
            assert request.method is HttpMethod.GET
            assert request.url == "https://hydapi.nve.no/api/v1/Observations"
            params = request.params or {}
            param = int(params["Parameter"])
            res = int(params["ResolutionTime"])
            station = str(params["StationId"])
            version = int(params["VersionNumber"])
            data = [
                _obs_block(
                    station=station,
                    parameter=param,
                    version=version,
                    unit="m³/s",
                    method="Instantaneous" if res == 0 else "Mean",
                    observations=[
                        {"time": "2024-01-02T11:00:00Z", "value": float(res + version), "quality": 2, "correction": 0}
                    ],
                )
            ]
            return TransportResponse(
                url=request.url,
                request_parameters=dict(params),
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps({"data": data}).encode(),
            )

    t1 = _Transport()
    # 1 station x 3 discharge resolutions (all Parameter=1001) -> 1 GET /Series (not 3),
    # and resolutions stay separate because ObservationSeries responses carry no resolutionTime field.
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("no_nve"),
            ("1.200.0",),
            (
                ProductId("discharge_daily_mean"),
                ProductId("discharge_hourly_mean"),
                ProductId("discharge_instantaneous"),
            ),
            _window("2024-01-02", "2024-01-02T23:00:00"),
        ),
        stages,
        provenance=ObservationProvenance(
            source="nve", provider_id=ProviderId("no_nve"), requested_at=_utc(2026, 1, 2, 12)
        ),
        transport=t1,
        cache="bypass",
    )
    series_gets = [r for r in t1.requests if r.url.endswith("/Series")]
    assert len(series_gets) == 1
    assert res.canonical_rows.height == 3

    # Empty GET /Series shared across 3 stage resolutions yields 1 lookup, 3 scoped inventories, 3 NO_MATCH outcomes.
    class _EmptySeriesTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            assert request.url.endswith("/Series")
            params = request.params or {}
            return TransportResponse(
                url=request.url,
                request_parameters=dict(params),
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps({"itemCount": 0, "data": []}).encode(),
            )

    t_empty = _EmptySeriesTransport()
    empty_res = driver_module.drive(
        ObservationRequest(
            ProviderId("no_nve"),
            ("2.279.0",),
            (
                ProductId("stage_daily_mean"),
                ProductId("stage_hourly_mean"),
                ProductId("stage_instantaneous"),
            ),
            _window("2024-06-11", "2024-06-12"),
        ),
        stages,
        provenance=ObservationProvenance(
            source="nve", provider_id=ProviderId("no_nve"), requested_at=_utc(2026, 6, 13, 12)
        ),
        transport=t_empty,
        cache="bypass",
    )
    assert len(t_empty.requests) == 1
    assert empty_res.canonical_rows.is_empty()
    lookup_inventories = [
        inv for inv in empty_res.inventories if not any(e.startswith("retrieval-outcome:") for e in inv.evidence)
    ]
    assert len(lookup_inventories) == 3
    assert {p for inv in lookup_inventories for p in inv.scope.product_ids} == {
        "stage_daily_mean",
        "stage_hourly_mean",
        "stage_instantaneous",
    }
    no_match = [o for o in empty_res.outcomes if o.status is OutcomeStatus.NO_MATCH]
    assert len(no_match) == 3
    assert len({o.outcome_id for o in no_match}) == 3
    assert {o.product_id for o in no_match} == {
        "stage_daily_mean",
        "stage_hourly_mean",
        "stage_instantaneous",
    }

    # Public explicit variant skips GET /Series (0 lookups) and preserves GET /Observations for single pair.
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NVE_API_KEY", "test-key")
    t2 = _Transport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: t2)
    sel = rr.pick(
        rr.find(provider="no_nve", station="1.200.0", quantity="discharge", frequency="P1D", statistic="mean"),
        variant="1",
    )
    out = rr.fetch(sel, start="2024-01-02", end="2024-01-02", cache="bypass", on_issue="raise")
    assert out.data.height == 1
    assert [r.url for r in t2.requests] == ["https://hydapi.nve.no/api/v1/Observations"]
    assert t2.requests[0].method is HttpMethod.GET
    assert (t2.requests[0].params or {})["VersionNumber"] == 1


def test_no_nve_post_batch_25_cap_out_of_order_single_decode_and_partial_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages

    # 30 distinct daily stations -> 30 GET /Series + 2 POST /Observations (25 + 5), with mixed outcomes.
    # Also test 109.42.0 + 1.200.0 with closed variant across two parameters via POST + rr.fetch reuse.
    stations = tuple(f"100.{idx}.0" for idx in range(1, 31))
    empty_station = "100.28.0"
    missing_station = "100.29.0"
    corrupt_station = "100.30.0"

    class _BatchTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []
            self.post_batches: list[list[dict[str, object]]] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            if request.url.endswith("/Series"):
                params = request.params or {}
                station = str(params["StationId"])
                param = int(params["Parameter"])
                unit = {1000: "m", 1001: "m³/s", 1003: "°C"}[param]
                data = [_series_meta_json(station, param, 1, [1440], unit)]
                return TransportResponse(
                    url=request.url,
                    request_parameters=dict(params),
                    status_code=200,
                    retrieved_at=_utc(2026, 1, 2, 12),
                    content_type="application/json",
                    content=json.dumps({"itemCount": len(data), "data": data}).encode(),
                )
            assert request.url == "https://hydapi.nve.no/api/v1/Observations"
            assert request.method is HttpMethod.POST
            assert request.headers.get("Content-Type") == "application/json"
            assert request.body is not None
            items = json.loads(request.body)
            assert isinstance(items, list)
            assert 2 <= len(items) <= 25
            for item in items:
                assert set(item.keys()) == {
                    "stationId",
                    "parameter",
                    "resolutionTime",
                    "versionNumber",
                    "referenceTime",
                }
                assert type(item["stationId"]) is str
                assert type(item["parameter"]) is str
                assert type(item["resolutionTime"]) is str
                assert type(item["versionNumber"]) is int
                assert type(item["referenceTime"]) is str
            self.post_batches.append(items)

            # Emit blocks in REVERSED order to verify out-of-order routing by identity, not position.
            blocks = []
            for item in reversed(items):
                st = item["stationId"]
                param = int(item["parameter"])
                ver = int(item["versionNumber"])
                unit = {1000: "m", 1001: "m³/s", 1003: "°C"}[param]
                if st == missing_station:
                    continue
                if st == empty_station:
                    blocks.append(_obs_block(station=st, parameter=param, version=ver, unit=unit, observations=[]))
                    continue
                if st == corrupt_station:
                    block = _obs_block(
                        station=st,
                        parameter=param,
                        version=ver,
                        unit=unit,
                        observations=[{"time": "2024-01-02T11:00:00Z", "value": 1.0, "quality": 2, "correction": 0}],
                    )
                    block["observationCount"] = 99
                    blocks.append(block)
                    continue
                idx = int(st.split(".")[1]) if "." in st else 1
                blocks.append(
                    _obs_block(
                        station=st,
                        parameter=param,
                        version=ver,
                        unit=unit,
                        observations=[
                            {
                                "time": "2024-01-02T11:00:00Z",
                                "value": float(idx) + (0.5 if param == 1000 else 0.0),
                                "quality": 2,
                                "correction": 0,
                            }
                        ],
                    )
                )
            return TransportResponse(
                url=request.url,
                request_parameters={},
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps({"data": blocks}).encode(),
            )

    loads_calls = 0
    real_loads = no_nve_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == no_nve_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(no_nve_parse.json, "loads", _counted_loads)
    t_batch = _BatchTransport()
    store_dir = tmp_path / "nve_store"
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("no_nve"),
            stations,
            (ProductId("discharge_daily_mean"),),
            _window("2024-01-02", "2024-01-02"),
        ),
        stages,
        provenance=ObservationProvenance(
            source="nve", provider_id=ProviderId("no_nve"), requested_at=_utc(2026, 1, 2, 12)
        ),
        transport=t_batch,
        cache="reuse",
        store=store_dir,
        receipts=ReceiptMode.INCLUDE,
    )
    assert len(t_batch.post_batches) == 2
    assert [len(b) for b in t_batch.post_batches] == [25, 5]
    # Single JSON decode per POST payload (2 POSTs -> 2 parse json.loads calls)
    assert loads_calls == 2
    assert res.canonical_rows.height == 27
    vals_by_st = {r["station_id"]: r["value"] for r in res.canonical_rows.select("station_id", "value").to_dicts()}
    assert vals_by_st["100.1.0"] == pytest.approx(1.0)
    assert vals_by_st["100.27.0"] == pytest.approx(27.0)
    outcomes_by_st = {o.station_id: o.status for o in res.outcomes}
    assert outcomes_by_st[empty_station] is OutcomeStatus.EMPTY
    assert outcomes_by_st[missing_station] is OutcomeStatus.UNRESOLVED
    assert outcomes_by_st[corrupt_station] is OutcomeStatus.UNSUPPORTED

    # Explicit closed scope with 2 stations x 2 parameters through rr.fetch (0 GET /Series, 1 POST, reuse 0)
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "pub_cache"))
    monkeypatch.setenv("NVE_API_KEY", "test-api-key")
    t_pub = _BatchTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: t_pub)
    sel = rr.pick(
        rr.find(provider="no_nve", station=("1.200.0", "109.42.0"), frequency="P1D", statistic="mean"),
        variant="1",
    )
    # Remove water_temperature_daily_mean so we test stage + discharge = 4 items via rr.pick
    sel_2p = rr.pick(
        rr.find(
            provider="no_nve", station=("1.200.0", "109.42.0"), quantity="discharge", frequency="P1D", statistic="mean"
        ),
        variant="1",
    )
    assert len(sel.series) >= 4
    first_pub = rr.fetch(sel_2p, start="2024-01-02", end="2024-01-02", cache="reuse", receipts=True, on_issue="raise")
    assert len(t_pub.requests) == 1
    assert t_pub.requests[0].method is HttpMethod.POST
    assert t_pub.requests[0].headers.get("X-API-Key") == "test-api-key"
    assert first_pub.data.height == 2

    reused_pub = rr.fetch(sel_2p, start="2024-01-02", end="2024-01-02", cache="reuse", receipts=True, on_issue="raise")
    assert len(t_pub.requests) == 1
    assert reused_pub.data.height == 2


def test_no_nve_compatibility_fetch_with_scope_and_missing_resolution_safety() -> None:
    # Ensure mixed resolution products sharing (station, parameter, version) are never packed into one POST.
    class _CheckTransport:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            assert request.method is HttpMethod.GET
            params = request.params or {}
            res = int(params["ResolutionTime"])
            data = [
                _obs_block(
                    station="1.200.0",
                    parameter=1001,
                    version=1,
                    unit="m³/s",
                    method="Instantaneous" if res == 0 else "Mean",
                    observations=[{"time": "2024-01-02T11:00:00Z", "value": float(res), "quality": 2, "correction": 0}],
                )
            ]
            return TransportResponse(
                url=request.url,
                request_parameters=dict(params),
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps({"data": data}).encode(),
            )

    assert isinstance(declaration.observations, LiveStages)
    t = _CheckTransport()
    acq = fetch(
        ("1.200.0",),
        (ProductId("discharge_daily_mean"), ProductId("discharge_hourly_mean")),
        {
            ProductId("discharge_daily_mean"): (
                driver_module.RenderedWindow("2024-01-02T00:00:00Z", "2024-01-02T23:59:59Z"),
            ),
            ProductId("discharge_hourly_mean"): (
                driver_module.RenderedWindow("2024-01-02T00:00:00Z", "2024-01-02T23:59:59Z"),
            ),
        },
        driver_module._make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2024, 1, 2)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 2, 23, 59, 59)),
        ),
        declaration.observations.stages.config,
        t,
        scope=SeriesScope(provider_ids=("no_nve",), restriction=RestrictionKind.EXPLICIT, variants=("1",)),
    )
    assert len(t.requests) == 2
    assert len(acq.value) == 2


def test_no_nve_partial_lookup_failure_isolates_call_attribution_and_links_prerequisite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("NVE_API_KEY", "test-api-key")
    assert isinstance(declaration.observations, LiveStages)

    class _PartialSeriesTransport:
        def __init__(self) -> None:
            self.fail_110 = False

        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url.endswith("/Series"):
                params = dict(request.params or {})
                station = str(params["StationId"])
                if self.fail_110 and station == "1.10.0":
                    raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=500)
                return TransportResponse(
                    url=request.url,
                    request_parameters=params,
                    status_code=200,
                    retrieved_at=_utc(2026, 1, 2, 12),
                    content_type="application/json",
                    content=json.dumps(
                        {"itemCount": 1, "data": [_series_meta_json(station, 1000, 1, [1440], "m")]}
                    ).encode(),
                )
            assert request.method is HttpMethod.POST
            assert request.body is not None
            items = json.loads(request.body)
            data = [
                _obs_block(
                    station=str(item["stationId"]),
                    parameter=int(item["parameter"]),
                    version=int(item["versionNumber"]),
                    unit="m",
                    method="Mean",
                    observations=[{"time": "2024-01-02T11:00:00Z", "value": 2.5, "quality": 2, "correction": 0}],
                )
                for item in items
            ]
            return TransportResponse(
                url=request.url,
                request_parameters={},
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps({"data": data}).encode(),
            )

    transport = _PartialSeriesTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)
    sel = rr.find(provider="no_nve", station=("1.10.0", "1.14.0"), quantity="stage", frequency="P1D", statistic="mean")

    seeded = rr.fetch(sel, start="2024-01-02", end="2024-01-02", cache="reuse", receipts=True, on_issue="raise")
    assert seeded.data.height == 2

    transport.fail_110 = True
    refreshed = rr.fetch(sel, start="2024-01-02", end="2024-01-02", cache="refresh", receipts=True, on_issue="warn")
    assert refreshed.data.height == 2
    series_calls = [call for call in refreshed.provenance.calls_made if str(call["url"]).endswith("/Series")]
    post_calls = [call for call in refreshed.provenance.calls_made if str(call["url"]).endswith("/Observations")]
    assert len(series_calls) == 2
    assert len(post_calls) == 1
    by_station = {str(dict(call["request_parameters"])["StationId"]): call for call in series_calls}
    assert tuple(by_station["1.10.0"]["station_products"]) == (("1.10.0", "stage_daily_mean"),)
    assert tuple(by_station["1.14.0"]["station_products"]) == (("1.14.0", "stage_daily_mean"),)
    expected_prereqs = {str(by_station["1.10.0"]["call_id"]), str(by_station["1.14.0"]["call_id"])}
    assert set(post_calls[0]["prerequisite_acquisition_ids"]) == expected_prereqs


def test_no_nve_shared_batch_narrows_per_consumer_fetch_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages

    class _MixedAxisTransport:
        def __init__(self) -> None:
            self.post_count = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            if request.method is HttpMethod.GET:
                params = dict(request.params or {})
                station = str(params["StationId"])
                ts = "2024-01-01T11:00:00Z" if "2024-01-01" in str(params["ReferenceTime"]) else "2024-01-02T11:00:00Z"
                return TransportResponse(
                    url=request.url,
                    request_parameters=params,
                    status_code=200,
                    retrieved_at=_utc(2026, 1, 5, 13),
                    content_type="application/json",
                    content=json.dumps(
                        {
                            "data": [
                                _obs_block(
                                    station=station,
                                    parameter=1000,
                                    version=1,
                                    unit="m",
                                    method="Mean",
                                    observations=[{"time": ts, "value": 1.0, "quality": 2, "correction": 0}],
                                )
                            ]
                        }
                    ).encode(),
                )
            self.post_count += 1
            assert request.body is not None
            items = json.loads(request.body)
            data = [
                _obs_block(
                    station=str(item["stationId"]),
                    parameter=int(item["parameter"]),
                    version=int(item["versionNumber"]),
                    unit="m",
                    method="Mean",
                    observations=[
                        {"time": "2024-01-05T10:00:00Z", "value": 4.2, "quality": 2, "correction": 0},
                    ],
                )
                for item in items
            ]
            return TransportResponse(
                url=request.url,
                request_parameters={},
                status_code=200,
                retrieved_at=_utc(2026, 1, 5, 13),
                content_type="application/json",
                content=json.dumps({"data": data}).encode(),
            )

    transport = _MixedAxisTransport()
    store_dir = tmp_path / "nve_store"
    # Seed 1.10.0 stage_daily_mean so its cached Daily physical facts widen fetch_window.end to 23:59:59.999999.
    driver_module.drive(
        ObservationRequest(
            ProviderId("no_nve"),
            ("1.10.0",),
            (ProductId("stage_daily_mean"),),
            _window("2024-01-01", "2024-01-01"),
            scope=SeriesScope(provider_ids=("no_nve",), restriction=RestrictionKind.EXPLICIT, variants=("1",)),
        ),
        stages,
        provenance=ObservationProvenance(
            source="nve", provider_id=ProviderId("no_nve"), requested_at=_utc(2026, 1, 5, 13)
        ),
        transport=transport,
        cache="reuse",
        store=store_dir,
        receipts=ReceiptMode.OMIT,
    )

    real_loads = json.loads
    loads_calls = 0

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == no_nve_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(no_nve_parse.json, "loads", _counted_loads)
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("no_nve"),
            ("1.10.0", "1.15.0"),
            (ProductId("stage_daily_mean"), ProductId("stage_hourly_mean")),
            _window("2024-01-04", "2024-01-05T12:00:00"),
            scope=SeriesScope(provider_ids=("no_nve",), restriction=RestrictionKind.EXPLICIT, variants=("1",)),
            station_products=(
                ("1.10.0", ProductId("stage_daily_mean")),
                ("1.15.0", ProductId("stage_hourly_mean")),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="nve", provider_id=ProviderId("no_nve"), requested_at=_utc(2026, 1, 5, 13)
        ),
        transport=transport,
        cache="reuse",
        store=store_dir,
        receipts=ReceiptMode.OMIT,
    )
    assert transport.post_count == 1
    assert loads_calls == 1
    assert res.canonical_rows.height == 2
    manifest = json.loads((store_dir / "manifest.json").read_text())
    hourly_inventories = [
        inv
        for inv in manifest["inventories"]
        if inv["scope"]["station_ids"] == ["1.15.0"] and inv["scope"]["product_ids"] == ["stage_hourly_mean"]
    ]
    assert hourly_inventories
    assert {inv["window"]["end"] for inv in hourly_inventories} == {"2024-01-07T12:00:00"}


def test_no_nve_malformed_series_member_preserves_valid_sibling_versions() -> None:
    assert isinstance(declaration.observations, LiveStages)

    class _MalformedMemberTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url.endswith("/Series"):
                params = dict(request.params or {})
                data = [
                    _series_meta_json("109.42.0", 1001, 1, [1440], "m³/s"),
                    _series_meta_json("109.42.0", 1001, 2, [1440], "m³/s"),
                    {**_series_meta_json("109.42.0", 1001, 3, [1440], "m³/s"), "unit": False},
                ]
                return TransportResponse(
                    url=request.url,
                    request_parameters=params,
                    status_code=200,
                    retrieved_at=_utc(2026, 1, 2, 12),
                    content_type="application/json",
                    content=json.dumps({"itemCount": len(data), "data": data}).encode(),
                )
            assert request.method is HttpMethod.GET
            params = request.params or {}
            version = int(params["VersionNumber"])
            data = [
                _obs_block(
                    station=str(params["StationId"]),
                    parameter=int(params["Parameter"]),
                    version=version,
                    unit="m³/s",
                    method="Mean",
                    observations=[
                        {
                            "time": "2024-01-02T11:00:00Z",
                            "value": float(version),
                            "quality": 2,
                            "correction": 0,
                        }
                    ],
                )
            ]
            return TransportResponse(
                url=request.url,
                request_parameters=dict(params),
                status_code=200,
                retrieved_at=_utc(2026, 1, 2, 12),
                content_type="application/json",
                content=json.dumps({"data": data}).encode(),
            )

    transport = _MalformedMemberTransport()
    acquired = fetch(
        ("109.42.0",),
        (ProductId("discharge_daily_mean"),),
        {
            ProductId("discharge_daily_mean"): (
                driver_module.RenderedWindow("2024-01-02T00:00:00Z", "2024-01-02T23:59:59Z"),
            ),
        },
        driver_module._make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2024, 1, 2)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 2, 23, 59, 59)),
        ),
        declaration.observations.stages.config,
        transport,
        scope=SeriesScope(provider_ids=("no_nve",), station_ids=("109.42.0",), product_ids=("discharge_daily_mean",)),
    )
    assert {item.origin.request_parameters["VersionNumber"] for item in acquired.value} == {1, 2}
    assert acquired.inventories[0].completeness is InventoryCompleteness.INCOMPLETE
    assert any(issue.code == "source.inventory_unresolved" for issue in acquired.issues)

"""Source-independent tests for th_thaiwater request planning, single decode, and isolation."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.engine import (
    ObservationRequest,
    RenderedWindow,
    RequestedWindow,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.providers.th_thaiwater import parse as th_thaiwater_parse
from rivretrieve._internal.providers.th_thaiwater.config import config
from rivretrieve._internal.providers.th_thaiwater.declaration import declaration
from rivretrieve._internal.providers.th_thaiwater.fetch import fetch
from rivretrieve._internal.providers.th_thaiwater.issue_codes import ThThaiWaterObservationIssueCodes
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_PRODUCTS = (ProductId("discharge_reported"), ProductId("stage_reported"))


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=UTC)


class _ThaiWaterTransport:
    def __init__(self, payload_by_station: dict[str, dict[str, object]]) -> None:
        self.payload_by_station = payload_by_station
        self.requests: list[TransportRequest] = []
        self.bytes_by_station = {
            station: json.dumps(doc).encode("utf-8") for station, doc in payload_by_station.items()
        }

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        params = dict(request.params or {})
        station = str(params["station_id"])
        return TransportResponse(
            content=self.bytes_by_station[station],
            status_code=200,
            retrieved_at=_utc(2026, 8, 3, 12),
            content_type="application/json",
            url=request.url,
            request_parameters=params,
        )


def _ok_doc(
    *,
    discharge_val: object = 12.5,
    stage_val: object = 3.4,
    include_discharge: bool = True,
) -> dict[str, object]:
    row0: dict[str, object] = {"datetime": "2026-08-01 00:00", "value": stage_val}
    if include_discharge:
        row0["discharge"] = discharge_val
    row1: dict[str, object] = {"datetime": "2026-08-01 01:00", "value": 3.5}
    if include_discharge:
        row1["discharge"] = 13.0
    return {"result": "OK", "data": {"graph_data": [row0, row1]}}


def test_th_thaiwater_declares_request_planner() -> None:
    assert isinstance(declaration.observations, LiveStages)
    assert hasattr(declaration.observations.stages, "request_planner")


def test_th_thaiwater_two_products_one_station_take_one_get_one_decode_and_one_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    loads_calls = 0
    real_loads = th_thaiwater_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == th_thaiwater_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(th_thaiwater_parse.json, "loads", _counted_loads)
    transport = _ThaiWaterTransport({"1373273": _ok_doc()})
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("th_thaiwater"),
            ("1373273",),
            _PRODUCTS,
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2026, 8, 1)),
                WindowEndpoint.from_datetime(datetime(2026, 8, 2, 23, 50)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="thaiwater", provider_id=ProviderId("th_thaiwater"), requested_at=_utc(2026, 8, 3)
        ),
        receipts=ReceiptMode.INCLUDE,
        transport=transport,
        cache="bypass",
    )
    assert len(transport.requests) == 1
    assert loads_calls == 1
    assert len(res.receipts.entries) == 1
    assert res.receipts.entries[0].content == transport.bytes_by_station["1373273"]
    assert res.canonical_rows.height == 4
    assert res.canonical_rows["time_zone"].unique().to_list() == ["unknown"]
    assert set(res.canonical_rows["product_id"].unique().to_list()) == {"discharge_reported", "stage_reported"}


def test_th_thaiwater_two_stations_issue_distinct_gets(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    loads_calls = 0
    real_loads = th_thaiwater_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == th_thaiwater_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(th_thaiwater_parse.json, "loads", _counted_loads)
    transport = _ThaiWaterTransport({"1373273": _ok_doc(), "1373272": _ok_doc(stage_val=4.1)})
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("th_thaiwater"),
            ("1373273", "1373272"),
            _PRODUCTS,
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2026, 8, 1)),
                WindowEndpoint.from_datetime(datetime(2026, 8, 2, 23, 50)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="thaiwater", provider_id=ProviderId("th_thaiwater"), requested_at=_utc(2026, 8, 3)
        ),
        transport=transport,
        cache="bypass",
    )
    assert [dict(r.params or {})["station_id"] for r in transport.requests] == ["1373273", "1373272"]
    assert loads_calls == 2
    assert res.canonical_rows.height == 8
    assert set(res.canonical_rows["station_id"].unique().to_list()) == {"1373273", "1373272"}


def test_th_thaiwater_source_result_no_emits_failed_issue_from_single_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    loads_calls = 0
    real_loads = th_thaiwater_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == th_thaiwater_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(th_thaiwater_parse.json, "loads", _counted_loads)
    transport = _ThaiWaterTransport({"1373273": {"result": "NO", "data": "data not found"}})
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("th_thaiwater"),
            ("1373273",),
            _PRODUCTS,
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2026, 8, 1)),
                WindowEndpoint.from_datetime(datetime(2026, 8, 2, 23, 50)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="thaiwater", provider_id=ProviderId("th_thaiwater"), requested_at=_utc(2026, 8, 3)
        ),
        transport=transport,
        cache="bypass",
    )
    assert len(transport.requests) == 1
    assert loads_calls == 1
    assert res.canonical_rows.is_empty()
    failed_issues = [i for i in res.issues if i.code == ThThaiWaterObservationIssueCodes.SOURCE_REQUEST_FAILED]
    assert len(failed_issues) >= 1


@pytest.mark.parametrize(
    "doc_kwargs",
    [
        {"include_discharge": False},
        {"discharge_val": "bad"},
    ],
)
def test_th_thaiwater_isolates_corrupt_or_missing_field_per_product(
    monkeypatch: pytest.MonkeyPatch, doc_kwargs: dict[str, object]
) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    loads_calls = 0
    real_loads = th_thaiwater_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == th_thaiwater_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(th_thaiwater_parse.json, "loads", _counted_loads)
    transport = _ThaiWaterTransport({"1373273": _ok_doc(**doc_kwargs)})  # type: ignore[arg-type]
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("th_thaiwater"),
            ("1373273",),
            _PRODUCTS,
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2026, 8, 1)),
                WindowEndpoint.from_datetime(datetime(2026, 8, 2, 23, 50)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="thaiwater", provider_id=ProviderId("th_thaiwater"), requested_at=_utc(2026, 8, 3)
        ),
        transport=transport,
        cache="bypass",
    )
    assert len(transport.requests) == 1
    assert loads_calls == 1
    assert res.canonical_rows["product_id"].unique().to_list() == ["stage_reported"]
    assert res.canonical_rows.height == 2
    by_product = {o.product_id: o.status for o in res.outcomes}
    assert by_product["discharge_reported"] is OutcomeStatus.UNSUPPORTED
    assert by_product["stage_reported"] is OutcomeStatus.SUCCESS


def test_th_thaiwater_store_reuse_and_compatibility_fetch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    transport = _ThaiWaterTransport({"1373273": _ok_doc()})
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    found = rr.find(provider="th_thaiwater", station="1373273")
    picked = rr.pick(found, series_id=tuple(s.series_id for s in found.series))
    first = rr.fetch(
        picked, start="2026-08-01", end="2026-08-02T23:50:00", cache="reuse", receipts=True, on_issue="ignore"
    )
    assert len(transport.requests) == 1
    assert first.data.height == 4

    reused = rr.fetch(
        picked, start="2026-08-01", end="2026-08-02T23:50:00", cache="reuse", receipts=True, on_issue="ignore"
    )
    assert len(transport.requests) == 1
    assert reused.data.height == 4

    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 8, 1)),
        WindowEndpoint.from_datetime(datetime(2026, 8, 2, 23, 59, 59)),
    )
    rendered = {p: (RenderedWindow("2026-08-01", "2026-08-02", fetch_win),) for p in _PRODUCTS}
    compat = fetch(("1373273",), _PRODUCTS, rendered, fetch_win, config(), _ThaiWaterTransport({"1373273": _ok_doc()}))
    assert len(compat.value) == 1
    assert compat.value[0].station_products == (
        ("1373273", ProductId("discharge_reported")),
        ("1373273", ProductId("stage_reported")),
    )

"""Source-independent tests for cz_chmi request planning, single decode, and isolation."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.engine import (
    ObservationRequest,
    RenderedWindow,
    RequestedWindow,
    SourceCoordinates,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.cz_chmi import parse as cz_chmi_parse
from rivretrieve._internal.providers.cz_chmi.config import config
from rivretrieve._internal.providers.cz_chmi.declaration import declaration
from rivretrieve._internal.providers.cz_chmi.fetch import fetch
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")

_STATION = "0-203-1-000400"
_PRODUCTS = (
    ProductId("stage_daily_mean"),
    ProductId("discharge_daily_mean"),
    ProductId("water_temperature_daily_mean"),
    ProductId("stage_hourly_mean"),
    ProductId("discharge_hourly_mean"),
)


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=UTC)


def _dq_doc(
    *,
    hd_id: object = "HD",
    hd_unit: str = "CM",
    hd_time: str = "2023-06-01T00:00:00Z",
    include_hd: bool = True,
) -> dict[str, object]:
    ts_list: list[dict[str, object]] = []
    if include_hd:
        ts_list.append(
            {
                "tsConID": hd_id,
                "unit": hd_unit,
                "tsData": {
                    "type": "DataCollection",
                    "data": {
                        "header": "DT,VAL",
                        "values": [[hd_time, 12.0], ["2023-06-02T00:00:00Z", 14.0]],
                    },
                },
            }
        )
    ts_list.extend(
        [
            {
                "tsConID": "QD",
                "unit": "M3_S",
                "tsData": {
                    "type": "DataCollection",
                    "data": {
                        "header": "DT,VAL",
                        "values": [["2023-06-01T00:00:00Z", 1.5], ["2023-06-02T00:00:00Z", 1.7]],
                    },
                },
            },
            {
                "tsConID": "TD",
                "unit": "0C",
                "tsData": {
                    "type": "DataCollection",
                    "data": {
                        "header": "DT,VAL",
                        "values": [["2023-06-01T00:00:00Z", 15.2], ["2023-06-02T00:00:00Z", 15.6]],
                    },
                },
            },
        ]
    )
    return {"objID": _STATION, "tsList": ts_list}


def _hq_doc() -> dict[str, object]:
    return {
        "objID": _STATION,
        "tsList": [
            {
                "tsConID": "HH",
                "unit": "CM",
                "tsData": {
                    "type": "DataCollection",
                    "data": {
                        "header": "DT,VAL",
                        "values": [["2023-06-01T00:00:00Z", 11.0], ["2023-06-02T23:00:00Z", 13.0]],
                    },
                },
            },
            {
                "tsConID": "QH",
                "unit": "M3_S",
                "tsData": {
                    "type": "DataCollection",
                    "data": {
                        "header": "DT,VAL",
                        "values": [["2023-06-01T00:00:00Z", 1.2], ["2023-06-02T23:00:00Z", 1.8]],
                    },
                },
            },
        ],
    }


class _SyntheticChmiTransport:
    def __init__(self, dq_doc: dict[str, object] | None = None, hq_doc: dict[str, object] | None = None) -> None:
        self.requests: list[TransportRequest] = []
        self.dq_bytes = json.dumps(dq_doc if dq_doc is not None else _dq_doc()).encode("utf-8")
        self.hq_bytes = json.dumps(hq_doc if hq_doc is not None else _hq_doc()).encode("utf-8")

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        if request.url.endswith("_DQ_2023.json"):
            content = self.dq_bytes
        elif request.url.endswith("_HQ_2023.json"):
            content = self.hq_bytes
        else:
            raise AssertionError(f"Unexpected cz_chmi request: {request.url}")
        return TransportResponse(
            content=content,
            status_code=200,
            retrieved_at=_utc(2024, 1, 2, 12),
            content_type="application/json",
            url=request.url,
            request_parameters={},
        )


def test_cz_chmi_declares_request_planner() -> None:
    assert isinstance(declaration.observations, LiveStages)
    assert hasattr(declaration.observations.stages, "request_planner")


def test_cz_chmi_five_products_take_two_gets_two_decodes_and_two_receipts(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    loads_calls = 0
    real_loads = cz_chmi_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == cz_chmi_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cz_chmi_parse.json, "loads", _counted_loads)
    transport = _SyntheticChmiTransport()
    result = driver_module.drive(
        ObservationRequest(
            ProviderId("cz_chmi"),
            (_STATION,),
            _PRODUCTS,
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2023, 6, 1)),
                WindowEndpoint.from_datetime(datetime(2023, 6, 2, 23)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="chmi", provider_id=ProviderId("cz_chmi"), requested_at=_utc(2024, 1, 2)
        ),
        receipts=ReceiptMode.INCLUDE,
        transport=transport,
        cache="bypass",
    )
    assert len(transport.requests) == 2
    assert loads_calls == 2
    assert len(result.receipts.entries) == 2
    assert [entry.content for entry in result.receipts.entries] == [transport.dq_bytes, transport.hq_bytes]
    assert result.canonical_rows.height == 10
    assert set(result.canonical_rows["product_id"].unique().to_list()) == {str(p) for p in _PRODUCTS}


@pytest.mark.parametrize(
    "doc_kwargs",
    [
        {"hd_id": {"malformed": "HD"}},
        {"hd_unit": "MM"},
        {"include_hd": False},
        {"hd_time": "2023-06-01T00:00:00+01:00Z"},
    ],
)
def test_cz_chmi_isolates_per_series_errors_from_single_decode(
    monkeypatch: pytest.MonkeyPatch, doc_kwargs: dict[str, object]
) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    loads_calls = 0
    real_loads = cz_chmi_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == cz_chmi_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cz_chmi_parse.json, "loads", _counted_loads)
    transport = _SyntheticChmiTransport(dq_doc=_dq_doc(**doc_kwargs))  # type: ignore[arg-type]
    result = driver_module.drive(
        ObservationRequest(
            ProviderId("cz_chmi"),
            (_STATION,),
            _PRODUCTS[:3],
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2023, 6, 1)),
                WindowEndpoint.from_datetime(datetime(2023, 6, 2, 23)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="chmi", provider_id=ProviderId("cz_chmi"), requested_at=_utc(2024, 1, 2)
        ),
        transport=transport,
        cache="bypass",
    )
    assert len(transport.requests) == 1
    assert loads_calls == 1
    assert set(result.canonical_rows["product_id"].unique().to_list()) == {
        "discharge_daily_mean",
        "water_temperature_daily_mean",
    }
    assert result.canonical_rows.height == 4
    by_product = {outcome.product_id: outcome.status for outcome in result.outcomes}
    assert by_product["stage_daily_mean"] is OutcomeStatus.UNSUPPORTED
    assert by_product["discharge_daily_mean"] is OutcomeStatus.SUCCESS
    assert by_product["water_temperature_daily_mean"] is OutcomeStatus.SUCCESS


def test_cz_chmi_store_reuse_and_mixed_hit_miss_via_public_fetch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    transport = _SyntheticChmiTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    daily_sel = rr.find(provider="cz_chmi", station=_STATION, quantity="discharge", frequency="P1D", statistic="mean")
    first = rr.fetch(daily_sel, start="2023-06-01", end="2023-06-02", cache="reuse", receipts=True, on_issue="raise")
    assert first.data.height == 2
    assert len(transport.requests) == 1
    assert len(first.receipts.entries) == 1

    # Reusing discharge_daily_mean hits store while requesting uncovered stage_hourly_mean fetches only HQ.
    all_sel = rr.find(provider="cz_chmi", station=_STATION)
    mixed_ids = tuple(
        item.series_id for item in all_sel.series if item.product_id in ("discharge_daily_mean", "stage_hourly_mean")
    )
    mixed_sel = rr.pick(all_sel, series_id=mixed_ids)
    mixed = rr.fetch(
        mixed_sel, start="2023-06-01", end="2023-06-02T23:00:00", cache="reuse", receipts=True, on_issue="raise"
    )
    assert len(transport.requests) == 2
    assert transport.requests[1].url.endswith("_HQ_2023.json")
    assert set(mixed.data["product_id"].unique().to_list()) == {"discharge_daily_mean", "stage_hourly_mean"}

    reread = rr.fetch(
        mixed_sel, start="2023-06-01", end="2023-06-02T23:00:00", cache="reuse", receipts=True, on_issue="raise"
    )
    assert len(transport.requests) == 2
    assert reread.data.height == mixed.data.height


def test_cz_chmi_compatibility_fetch_and_parse_preserved() -> None:
    transport = _SyntheticChmiTransport()
    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2023, 12, 31, 23)),
    )
    rendered = MappingProxyType({p: (RenderedWindow("2023", None, fetch_win),) for p in _PRODUCTS[:3]})
    acq = fetch((_STATION,), _PRODUCTS[:3], rendered, fetch_win, config(), transport)
    assert len(acq.value) == 1
    parsed = cz_chmi_parse.parse(acq.value[0], config())
    assert parsed.rows.height == 6
    with pytest.raises(FatalContractError, match="invalid request coordinates"):
        cz_chmi_parse.parse(replace(acq.value[0], source_coordinates=SourceCoordinates(None)), config())

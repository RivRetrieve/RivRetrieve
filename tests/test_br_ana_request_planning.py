"""Source-independent tests for br_ana request planning, variant sharing, and isolation."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import pytest

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
from rivretrieve._internal.providers.br_ana import parse as br_ana_parse
from rivretrieve._internal.providers.br_ana.config import config
from rivretrieve._internal.providers.br_ana.declaration import declaration
from rivretrieve._internal.providers.br_ana.fetch import fetch
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_STATION = "15400000"
_ALL_PRODUCTS = (
    ProductId("discharge_instantaneous"),
    ProductId("stage_instantaneous"),
    ProductId("discharge_daily_mean_bruto"),
    ProductId("discharge_daily_mean_consistido"),
    ProductId("stage_daily_mean_bruto"),
    ProductId("stage_daily_mean_consistido"),
)


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=UTC)


def _envelope(items: list[dict[str, object]]) -> dict[str, object]:
    return {"status": "OK", "code": 200, "items": items}


def _telemetry_doc(
    *,
    cota_val: object = "150.0",
    vazao_val: object = "42.5",
) -> dict[str, object]:
    return _envelope(
        [
            {
                "codigoestacao": _STATION,
                "Data_Hora_Medicao": "2024-06-11 12:00:00.0",
                "Cota_Adotada": cota_val,
                "Cota_Adotada_Status": "0",
                "Vazao_Adotada": vazao_val,
                "Vazao_Adotada_Status": "1",
            }
        ]
    )


def _daily_item(
    *,
    prefix: str,
    consistency: str,
    day11_val: object = "10.0",
    day12_val: object = "11.0",
) -> dict[str, object]:
    consistency_field = "nivelconsistencia" if prefix == "Cota" else "Nivel_Consistencia"
    method_field = "Tipo_Medicao_Cotas" if prefix == "Cota" else "Metodo_Obtencao_Vazoes"
    item: dict[str, object] = {
        "codigoestacao": _STATION,
        "Mediadiaria": "1",
        consistency_field: consistency,
        "Data_Hora_Dado": "2024-06-01 00:00:00.0",
        method_field: "2",
    }
    for day in range(1, 32):
        if day > 30:
            item[f"{prefix}_{day:02d}"] = None
            item[f"{prefix}_{day:02d}_Status"] = "0"
        elif day == 11:
            item[f"{prefix}_{day:02d}"] = day11_val
            item[f"{prefix}_{day:02d}_Status"] = "1"
        elif day == 12:
            item[f"{prefix}_{day:02d}"] = day12_val
            item[f"{prefix}_{day:02d}_Status"] = "2"
        else:
            item[f"{prefix}_{day:02d}"] = None
            item[f"{prefix}_{day:02d}_Status"] = None
    return item


class _AnaTransport:
    def __init__(
        self,
        *,
        telemetry_doc: dict[str, object] | None = None,
        vazao_doc: dict[str, object] | None = None,
        cotas_doc: dict[str, object] | None = None,
        fail_endpoint: str | None = None,
    ) -> None:
        self.requests: list[TransportRequest] = []
        self.fail_endpoint = fail_endpoint
        self.telemetry_bytes = json.dumps(telemetry_doc if telemetry_doc is not None else _telemetry_doc()).encode()
        self.vazao_bytes = json.dumps(
            vazao_doc
            if vazao_doc is not None
            else _envelope(
                [
                    _daily_item(prefix="Vazao", consistency="1", day11_val="21.0", day12_val="22.0"),
                    _daily_item(prefix="Vazao", consistency="2", day11_val="23.0", day12_val="24.0"),
                ]
            )
        ).encode()
        self.cotas_bytes = json.dumps(
            cotas_doc
            if cotas_doc is not None
            else _envelope(
                [
                    _daily_item(prefix="Cota", consistency="1", day11_val="100.0", day12_val="102.0"),
                    _daily_item(prefix="Cota", consistency="2", day11_val="105.0", day12_val="106.0"),
                ]
            )
        ).encode()

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        if self.fail_endpoint is not None and self.fail_endpoint in request.url:
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=503,
                category=TransportFailureCategory.HTTP_STATUS,
            )
        if "HidroinfoanaSerieTelemetricaAdotada" in request.url:
            content = self.telemetry_bytes
        elif "HidroSerieVazao" in request.url:
            content = self.vazao_bytes
        elif "HidroSerieCotas" in request.url:
            content = self.cotas_bytes
        else:
            raise AssertionError(f"Unexpected ANA endpoint: {request.url}")
        return TransportResponse(
            content=content,
            status_code=200,
            retrieved_at=_utc(2024, 6, 13, 12),
            content_type="application/json",
            url=request.url,
            request_parameters=dict(request.params or {}),
        )


def test_br_ana_declares_request_planner() -> None:
    assert isinstance(declaration.observations, LiveStages)
    assert hasattr(declaration.observations.stages, "request_planner")


def test_br_ana_six_products_take_three_gets_three_decodes_and_preserve_annotations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    loads_calls = 0
    real_loads = br_ana_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == br_ana_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(br_ana_parse.json, "loads", _counted_loads)
    transport = _AnaTransport()
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("br_ana"),
            (_STATION,),
            _ALL_PRODUCTS,
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2024, 6, 11)),
                WindowEndpoint.from_datetime(datetime(2024, 6, 12)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="ana", provider_id=ProviderId("br_ana"), requested_at=_utc(2024, 6, 13)
        ),
        receipts=ReceiptMode.INCLUDE,
        transport=transport,
        cache="bypass",
    )
    assert len(transport.requests) == 3
    assert loads_calls == 3
    assert len(res.receipts.entries) == 3
    # 2 telemetry rows (1 each) + 4 daily products * 2 days = 10 rows; no duplication across variants.
    assert res.canonical_rows.height == 10
    assert set(res.canonical_rows["product_id"].unique().to_list()) == {str(p) for p in _ALL_PRODUCTS}
    # Verify all 4 annotation schemas survived intact and align with row counts.
    tables = res.annotations.observation_tables
    assert set(tables) == {
        "br_ana.telemetry_cota",
        "br_ana.telemetry_vazao",
        "br_ana.daily_cotas",
        "br_ana.daily_vazao",
    }
    assert tables["br_ana.telemetry_cota"].rows.height == 1
    assert tables["br_ana.telemetry_vazao"].rows.height == 1
    assert tables["br_ana.daily_cotas"].rows.height == 4
    assert tables["br_ana.daily_vazao"].rows.height == 4


def test_br_ana_isolates_malformed_telemetry_and_daily_variants_and_absent_consistency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    loads_calls = 0
    real_loads = br_ana_parse.json.loads

    def _counted_loads(*args: object, **kwargs: object) -> object:
        nonlocal loads_calls
        if sys._getframe(1).f_code.co_filename == br_ana_parse.__file__:
            loads_calls += 1
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(br_ana_parse.json, "loads", _counted_loads)
    transport = _AnaTransport(
        telemetry_doc=_telemetry_doc(cota_val="bad-decimal", vazao_val="42.5"),
        vazao_doc=_envelope(
            [
                _daily_item(prefix="Vazao", consistency="1", day11_val="not-a-number", day12_val="22.0"),
                _daily_item(prefix="Vazao", consistency="2", day11_val="23.0", day12_val="24.0"),
            ]
        ),
        cotas_doc=_envelope([_daily_item(prefix="Cota", consistency="1", day11_val="100.0", day12_val="102.0")]),
    )
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("br_ana"),
            (_STATION,),
            _ALL_PRODUCTS,
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2024, 6, 11)),
                WindowEndpoint.from_datetime(datetime(2024, 6, 12)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="ana", provider_id=ProviderId("br_ana"), requested_at=_utc(2024, 6, 13)
        ),
        transport=transport,
        cache="bypass",
    )
    assert len(transport.requests) == 3
    assert loads_calls == 3
    assert set(res.canonical_rows["product_id"].unique().to_list()) == {
        "discharge_instantaneous",
        "discharge_daily_mean_consistido",
        "stage_daily_mean_bruto",
    }
    by_product = {o.product_id: o.status for o in res.outcomes}
    assert by_product["stage_instantaneous"] is OutcomeStatus.UNSUPPORTED
    assert by_product["discharge_instantaneous"] is OutcomeStatus.SUCCESS
    assert by_product["discharge_daily_mean_bruto"] is OutcomeStatus.UNSUPPORTED
    assert by_product["discharge_daily_mean_consistido"] is OutcomeStatus.SUCCESS
    assert by_product["stage_daily_mean_bruto"] is OutcomeStatus.SUCCESS
    assert by_product["stage_daily_mean_consistido"] is OutcomeStatus.UNRESOLVED


def test_br_ana_isolates_endpoint_transport_failure_to_its_consumers() -> None:
    assert isinstance(declaration.observations, LiveStages)
    stages = declaration.observations.stages
    transport = _AnaTransport(fail_endpoint="HidroSerieCotas")
    res = driver_module.drive(
        ObservationRequest(
            ProviderId("br_ana"),
            (_STATION,),
            _ALL_PRODUCTS,
            RequestedWindow(
                WindowEndpoint.from_datetime(datetime(2024, 6, 11)),
                WindowEndpoint.from_datetime(datetime(2024, 6, 12)),
            ),
        ),
        stages,
        provenance=ObservationProvenance(
            source="ana", provider_id=ProviderId("br_ana"), requested_at=_utc(2024, 6, 13)
        ),
        transport=transport,
        cache="bypass",
    )
    assert len(transport.requests) == 3
    assert set(res.canonical_rows["product_id"].unique().to_list()) == {
        "discharge_instantaneous",
        "stage_instantaneous",
        "discharge_daily_mean_bruto",
        "discharge_daily_mean_consistido",
    }
    by_product = {o.product_id: o.status for o in res.outcomes}
    assert by_product["stage_daily_mean_bruto"] is OutcomeStatus.FAILED
    assert by_product["stage_daily_mean_consistido"] is OutcomeStatus.FAILED


def test_br_ana_single_product_compatibility_fetch_and_parse_preserved() -> None:
    transport = _AnaTransport()
    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 6, 1)),
        WindowEndpoint.from_datetime(datetime(2024, 6, 30)),
    )
    rendered = {
        ProductId("stage_daily_mean_bruto"): (RenderedWindow("2024-06-01", "2024-06-30", fetch_win),),
    }
    acq = fetch((_STATION,), (ProductId("stage_daily_mean_bruto"),), rendered, fetch_win, config(), transport)
    assert len(acq.value) == 1
    parsed = br_ana_parse.parse(acq.value[0], config())
    assert {s.product_id for s in parsed.series} == {"stage_daily_mean_bruto", "stage_daily_mean_consistido"}

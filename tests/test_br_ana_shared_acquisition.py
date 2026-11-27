"""Shared-endpoint acquisition and single-pass group parsing for ``br_ana``."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve._internal.providers.br_ana.parse as br_ana_parse
from rivretrieve._internal.driver import SharedAcquisitionProvider, SharedParseProvider, drive
from rivretrieve._internal.engine import (
    ObservationRequest,
    Payload,
    RequestedWindow,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ObservationProvenance, ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.br_ana.config import (
    SHARED_ACQUISITION_PRODUCTS,
    BrAnaSharedEndpointCoordinates,
    BrAnaSourceCoordinates,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.br_ana.declaration import declaration
from rivretrieve._internal.providers.br_ana.fetch import fetch
from rivretrieve._internal.providers.br_ana.parse import parse, parse_group
from rivretrieve._internal.providers.br_ana.series import describe_series
from rivretrieve._internal.source_series import OutcomeStatus, RestrictionKind, SeriesScope
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)
from rivretrieve._internal.window_planning import plan_windows

_PROVIDER = ProviderId("br_ana")
_STATION = "15400000"
_RETRIEVED_AT = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _daily_month_row(
    prefix: str,
    consistency: str,
    *,
    year: int = 2024,
    month: int = 1,
    base_value: float = 10.0,
) -> dict[str, object]:
    consistency_field = "nivelconsistencia" if prefix == "Cota" else "Nivel_Consistencia"
    method_field = "Tipo_Medicao_Cotas" if prefix == "Cota" else "Metodo_Obtencao_Vazoes"
    row: dict[str, object] = {
        "codigoestacao": _STATION,
        "Mediadiaria": "1",
        consistency_field: consistency,
        "Data_Hora_Dado": f"{year:04d}-{month:02d}-01 00:00:00.0",
        method_field: "1",
    }
    for day in range(1, 32):
        row[f"{prefix}_{day:02d}"] = f"{base_value + day:.2f}"
        row[f"{prefix}_{day:02d}_Status"] = "1"
    return row


def _daily_envelope(prefix: str, consistencies: tuple[str, ...] = ("1", "2"), *, year: int = 2024) -> bytes:
    items = [
        _daily_month_row(prefix, consistency, year=year, base_value=100.0 * int(consistency))
        for consistency in consistencies
    ]
    return json.dumps({"status": "OK", "code": 200, "items": items}).encode()


def _telemetry_envelope(*, corrupt_stage: bool = False) -> bytes:
    items: list[dict[str, object]] = [
        {
            "codigoestacao": _STATION,
            "Data_Hora_Medicao": "2024-01-01 23:45:00.0",
            "Vazao_Adotada": "123.45",
            "Vazao_Adotada_Status": "0",
            "Cota_Adotada": "456.00",
            "Cota_Adotada_Status": "0",
        },
        {
            "codigoestacao": _STATION,
            "Data_Hora_Medicao": "2024-01-02 00:00:00.0",
            "Vazao_Adotada": "125.00",
            "Vazao_Adotada_Status": "0",
            "Cota_Adotada": "460.00",
            "Cota_Adotada_Status": "0",
        },
    ]
    if corrupt_stage:
        del items[0]["Cota_Adotada"]
    return json.dumps({"status": "OK", "code": 200, "items": items}).encode()


class _RoutingTransport:
    def __init__(self, responses: dict[str, bytes | int]) -> None:
        self.responses = responses
        self.calls: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.calls.append(request)
        endpoint = request.url.split("/")[-2]
        entry = self.responses[endpoint]
        if isinstance(entry, int):
            raise TransportFailure(request, TransportFailureReason.HTTP_STATUS, 1, status_code=entry)
        return TransportResponse(
            content=entry,
            status_code=200,
            retrieved_at=_RETRIEVED_AT,
            content_type="application/json",
            url=request.url,
            request_parameters=request.params,
        )


class _SingletonStages:
    """Baseline stages without shared acquisition or parse_group for equivalence checks."""

    observation_source = "live"
    config = config()
    window_declarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _count_json_loads(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    counts = [0]
    real_loads = json.loads

    def counting_loads(*args, **kwargs):
        counts[0] += 1
        return real_loads(*args, **kwargs)

    monkeypatch.setattr(
        br_ana_parse,
        "json",
        SimpleNamespace(loads=counting_loads, JSONDecodeError=json.JSONDecodeError),
    )
    return counts


def test_declaration_exposes_shared_acquisition_and_parse_group() -> None:
    stages = declaration.observations.stages
    assert isinstance(stages, SharedAcquisitionProvider)
    assert isinstance(stages, SharedParseProvider)
    assert stages.shared_acquisition_products == SHARED_ACQUISITION_PRODUCTS
    assert stages.shared_acquisition_products == (
        frozenset((ProductId("discharge_instantaneous"), ProductId("stage_instantaneous"))),
        frozenset((ProductId("discharge_daily_mean_bruto"), ProductId("discharge_daily_mean_consistido"))),
        frozenset((ProductId("stage_daily_mean_bruto"), ProductId("stage_daily_mean_consistido"))),
    )


@pytest.mark.parametrize(
    ("products", "endpoint", "body", "start", "end"),
    [
        (
            (ProductId("discharge_daily_mean_bruto"), ProductId("discharge_daily_mean_consistido")),
            "HidroSerieVazao",
            _daily_envelope("Vazao"),
            datetime(2024, 1, 10),
            datetime(2024, 1, 12),
        ),
        (
            (ProductId("stage_daily_mean_bruto"), ProductId("stage_daily_mean_consistido")),
            "HidroSerieCotas",
            _daily_envelope("Cota"),
            datetime(2024, 1, 10),
            datetime(2024, 1, 12),
        ),
        (
            (ProductId("discharge_instantaneous"), ProductId("stage_instantaneous")),
            "HidroinfoanaSerieTelemetricaAdotada",
            _telemetry_envelope(),
            datetime(2024, 1, 1, 23, 45),
            datetime(2024, 1, 2, 0, 0),
        ),
    ],
)
def test_shared_pair_cuts_http_and_json_decodes_in_half_with_equivalent_output(
    monkeypatch: pytest.MonkeyPatch,
    products: tuple[ProductId, ProductId],
    endpoint: str,
    body: bytes,
    start: datetime,
    end: datetime,
) -> None:
    request = ObservationRequest(
        _PROVIDER,
        (_STATION,),
        products,
        RequestedWindow(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end)),
    )
    provenance = ObservationProvenance(source="test", provider_id=_PROVIDER)

    decode_counts = _count_json_loads(monkeypatch)
    shared_transport = _RoutingTransport({endpoint: body})
    shared = drive(
        request,
        declaration.observations.stages,
        provenance=provenance,
        transport=shared_transport,
        receipts=ReceiptMode.INCLUDE,
    )
    assert len(shared_transport.calls) == 1
    assert decode_counts[0] == 1
    assert len(shared.receipts.entries) == 1
    assert shared.receipts.entries[0].content == body
    data_calls = [call for call in shared.provenance.calls_made if call.get("response_disposition") is None]
    assert len(data_calls) == 1

    baseline_transport = _RoutingTransport({endpoint: body})
    baseline = drive(
        request,
        _SingletonStages(),
        provenance=provenance,
        transport=baseline_transport,
        receipts=ReceiptMode.INCLUDE,
    )
    assert len(baseline_transport.calls) == 2

    pl_testing.assert_frame_equal(
        shared.canonical_rows.sort(["product_id", "time"]),
        baseline.canonical_rows.sort(["product_id", "time"]),
    )
    assert {item.series_id for item in shared.source_series} == {item.series_id for item in baseline.source_series}
    assert [(o.product_id, o.series_id, o.status) for o in shared.outcomes] == [
        (o.product_id, o.series_id, o.status) for o in baseline.outcomes
    ]
    assert [(i.code, i.details) for i in shared.issues] == [(i.code, i.details) for i in baseline.issues]
    assert set(shared.annotations.observation_tables) == set(baseline.annotations.observation_tables)
    for schema_id, shared_table in shared.annotations.observation_tables.items():
        base_table = baseline.annotations.observation_tables[schema_id]
        pl_testing.assert_frame_equal(
            shared_table.rows.sort(["product_id", "time"]),
            base_table.rows.sort(["product_id", "time"]),
        )


def test_all_six_products_issue_three_http_calls_and_three_decodes(monkeypatch: pytest.MonkeyPatch) -> None:
    all_products = (
        ProductId("discharge_daily_mean_bruto"),
        ProductId("discharge_daily_mean_consistido"),
        ProductId("stage_daily_mean_bruto"),
        ProductId("stage_daily_mean_consistido"),
        ProductId("discharge_instantaneous"),
        ProductId("stage_instantaneous"),
    )
    request = ObservationRequest(
        _PROVIDER,
        (_STATION,),
        all_products,
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1, 23, 45)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 2, 0, 0)),
        ),
    )
    decode_counts = _count_json_loads(monkeypatch)
    transport = _RoutingTransport(
        {
            "HidroSerieVazao": _daily_envelope("Vazao"),
            "HidroSerieCotas": _daily_envelope("Cota"),
            "HidroinfoanaSerieTelemetricaAdotada": _telemetry_envelope(),
        }
    )
    result = drive(
        request,
        declaration.observations.stages,
        provenance=ObservationProvenance(source="test", provider_id=_PROVIDER),
        transport=transport,
        receipts=ReceiptMode.OMIT,
    )
    assert len(transport.calls) == 3
    assert decode_counts[0] == 3
    assert result.receipts.entries == ()
    assert set(result.canonical_rows["product_id"].unique().to_list()) == set(map(str, all_products))


def test_shared_daily_unobserved_sibling_remains_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    products = (ProductId("discharge_daily_mean_bruto"), ProductId("discharge_daily_mean_consistido"))
    request = ObservationRequest(
        _PROVIDER,
        (_STATION,),
        products,
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 10)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 12)),
        ),
    )
    decode_counts = _count_json_loads(monkeypatch)
    transport = _RoutingTransport({"HidroSerieVazao": _daily_envelope("Vazao", consistencies=("1",))})
    result = drive(
        request,
        declaration.observations.stages,
        provenance=ObservationProvenance(source="test", provider_id=_PROVIDER),
        transport=transport,
    )
    assert len(transport.calls) == 1
    assert decode_counts[0] == 1
    assert set(result.canonical_rows["product_id"].unique().to_list()) == {"discharge_daily_mean_bruto"}
    statuses = {outcome.product_id: outcome.status for outcome in result.outcomes}
    assert statuses == {
        "discharge_daily_mean_bruto": OutcomeStatus.SUCCESS,
        "discharge_daily_mean_consistido": OutcomeStatus.UNRESOLVED,
    }
    assert any(
        issue.code == "source.unresolved_inventory"
        and (issue.details or {}).get("product_id") == "discharge_daily_mean_consistido"
        for issue in result.issues
    )


def test_shared_telemetry_isolates_corrupt_sibling_field(monkeypatch: pytest.MonkeyPatch) -> None:
    products = (ProductId("discharge_instantaneous"), ProductId("stage_instantaneous"))
    request = ObservationRequest(
        _PROVIDER,
        (_STATION,),
        products,
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1, 23, 45)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 2, 0, 0)),
        ),
    )
    decode_counts = _count_json_loads(monkeypatch)
    transport = _RoutingTransport({"HidroinfoanaSerieTelemetricaAdotada": _telemetry_envelope(corrupt_stage=True)})
    result = drive(
        request,
        declaration.observations.stages,
        provenance=ObservationProvenance(source="test", provider_id=_PROVIDER),
        transport=transport,
    )
    assert len(transport.calls) == 1
    assert decode_counts[0] == 1
    assert set(result.canonical_rows["product_id"].unique().to_list()) == {"discharge_instantaneous"}
    assert result.canonical_rows.height == 2
    statuses = {outcome.product_id: outcome.status for outcome in result.outcomes}
    assert statuses == {
        "discharge_instantaneous": OutcomeStatus.SUCCESS,
        "stage_instantaneous": OutcomeStatus.UNSUPPORTED,
    }
    assert any(
        issue.code == "source.unsupported_series" and (issue.details or {}).get("product_id") == "stage_instantaneous"
        for issue in result.issues
    )


def test_shared_malformed_json_reports_unsupported_for_both_products(monkeypatch: pytest.MonkeyPatch) -> None:
    products = (ProductId("discharge_instantaneous"), ProductId("stage_instantaneous"))
    request = ObservationRequest(
        _PROVIDER,
        (_STATION,),
        products,
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1, 23, 45)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 2, 0, 0)),
        ),
    )
    decode_counts = _count_json_loads(monkeypatch)
    transport = _RoutingTransport({"HidroinfoanaSerieTelemetricaAdotada": b"not-json"})
    result = drive(
        request,
        declaration.observations.stages,
        provenance=ObservationProvenance(source="test", provider_id=_PROVIDER),
        transport=transport,
    )
    assert len(transport.calls) == 1
    assert decode_counts[0] == 1
    assert result.canonical_rows.is_empty()
    assert len(result.outcomes) == 2
    assert {outcome.product_id for outcome in result.outcomes} == set(map(str, products))
    assert all(outcome.status is OutcomeStatus.UNSUPPORTED for outcome in result.outcomes)
    assert len({outcome.outcome_id for outcome in result.outcomes}) == 2


def test_shared_transport_failure_shares_call_id_and_fails_both_products() -> None:
    products = (ProductId("discharge_daily_mean_bruto"), ProductId("discharge_daily_mean_consistido"))
    request = ObservationRequest(
        _PROVIDER,
        (_STATION,),
        products,
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 10)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 12)),
        ),
    )
    transport = _RoutingTransport({"HidroSerieVazao": 503})
    result = drive(
        request,
        declaration.observations.stages,
        provenance=ObservationProvenance(source="test", provider_id=_PROVIDER),
        transport=transport,
    )
    assert len(transport.calls) == 1
    assert result.canonical_rows.is_empty()
    assert {outcome.product_id for outcome in result.outcomes} == set(map(str, products))
    assert all(outcome.status is OutcomeStatus.FAILED for outcome in result.outcomes)
    data_calls = [call for call in result.provenance.calls_made if call.get("response_disposition") is None]
    assert len(data_calls) == 1


def test_shared_telemetry_cache_populates_and_reuses_both_products(tmp_path: Path) -> None:
    products = (ProductId("discharge_instantaneous"), ProductId("stage_instantaneous"))
    series = tuple(
        describe_series(_STATION, str(product), config().products[product].coordinates.value)  # type: ignore[arg-type]
        for product in products
    )
    scope = SeriesScope(
        provider_ids=("br_ana",),
        station_ids=(_STATION,),
        product_ids=tuple(map(str, products)),
        restriction=RestrictionKind.EXPLICIT,
        series_ids=tuple(item.series_id for item in series),
    )
    request = ObservationRequest(
        _PROVIDER,
        (_STATION,),
        products,
        RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1, 23, 45)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 2, 0, 0)),
        ),
        known_series=series,
        scope=scope,
    )
    store = StoreRoot(tmp_path / "store")
    transport = _RoutingTransport({"HidroinfoanaSerieTelemetricaAdotada": _telemetry_envelope()})
    live = drive(
        request,
        declaration.observations.stages,
        provenance=ObservationProvenance(source="test", provider_id=_PROVIDER),
        transport=transport,
        cache="reuse",
        store=store,
    )
    assert len(transport.calls) == 1
    assert live.canonical_rows.height == 4

    empty_transport = _RoutingTransport({})
    cached = drive(
        request,
        declaration.observations.stages,
        provenance=ObservationProvenance(source="test", provider_id=_PROVIDER),
        transport=empty_transport,
        cache="reuse",
        store=store,
    )
    assert len(empty_transport.calls) == 0
    pl_testing.assert_frame_equal(
        live.canonical_rows.sort(["product_id", "time"]),
        cached.canonical_rows.sort(["product_id", "time"]),
    )


def test_direct_parse_supports_multi_product_shared_payloads_without_row_duplication() -> None:
    daily_products = (ProductId("discharge_daily_mean_bruto"), ProductId("discharge_daily_mean_consistido"))
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 31)),
    )
    rendered = {product: plan_windows(window, window_declarations().products[product]) for product in daily_products}
    daily_acq = fetch(
        (_STATION,),
        daily_products,
        rendered,
        window,
        config(),
        _RoutingTransport({"HidroSerieVazao": _daily_envelope("Vazao")}),
    )
    assert len(daily_acq.value) == 1
    shared_payload = daily_acq.value[0]
    assert shared_payload.source_coordinates.value == BrAnaSharedEndpointCoordinates("HidroSerieVazao")
    parsed = parse(shared_payload, config())
    assert parsed.rows.height == 62
    assert parsed.rows.filter(pl.col("product_id") == "discharge_daily_mean_bruto").height == 31
    assert parsed.rows.filter(pl.col("product_id") == "discharge_daily_mean_consistido").height == 31
    assert parsed.annotations.observation_tables["br_ana.daily_vazao"].rows.height == 62


def test_coordinate_and_group_contract_violations_raise_fatal_contract_error() -> None:
    window = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 2)),
    )
    origin = SourceCallOrigin(
        url="https://www.ana.gov.br/test",
        request_parameters={},
        status_code=200,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )
    wrong_shared = Payload(
        source_coordinates=SourceCoordinates(BrAnaSharedEndpointCoordinates("HidroSerieCotas")),
        station_products=((_STATION, ProductId("discharge_daily_mean_bruto")),),
        fetch_window=window,
        content=_daily_envelope("Vazao"),
        origin=origin,
        prerequisite_calls=(),
    )
    with pytest.raises(FatalContractError, match="coordinates differ"):
        parse(wrong_shared, config())

    wrong_single = replace(
        wrong_shared,
        source_coordinates=SourceCoordinates(BrAnaSourceCoordinates("Cota_Adotada")),
        station_products=((_STATION, ProductId("discharge_instantaneous")),),
        content=_telemetry_envelope(),
    )
    with pytest.raises(FatalContractError, match="coordinates differ"):
        parse(wrong_single, config())

    with pytest.raises(FatalContractError, match="at least one pair"):
        parse_group(wrong_shared, {}, config())

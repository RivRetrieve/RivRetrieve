"""Synthetic unit and assembled driver/store controls for Argentina INA Alerta5 retrieval."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from rivretrieve._internal.assembly import _AssemblyResult
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
    Hourly,
    Instant,
    ObservationRequest,
    Payload,
    ProductWindowDeclarations,
    ProviderConfig,
    RequestedWindow,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownOriginFact,
    UnknownTemporalSupport,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import CacheMode, ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.ar_ina.config import (
    ArInaSeriesLookupCoordinates,
    ArInaSourceCoordinates,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.ar_ina.declaration import declaration
from rivretrieve._internal.providers.ar_ina.fetch import fetch, resolve_series_lookup
from rivretrieve._internal.providers.ar_ina.parse import parse
from rivretrieve._internal.providers.ar_ina.series import (
    IN_SCOPE_SERIES_SPECS,
    SPECS_BY_PRODUCT_ID,
    source_series,
)
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    OutcomeStatus,
    PhysicalPredicate,
    RestrictionKind,
    SeriesScope,
)
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import (
    Transport,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)
from tests.test_internal_driver import _provenance

_RETRIEVED_AT = datetime(2026, 11, 7, 0, 10, tzinfo=UTC)
_SERIES_URL = "https://alerta.ina.gob.ar/a5/obs/puntual/series"


@dataclass(frozen=True)
class _ArInaStages:
    """Explicit stage bundle matching the live declaration contract."""

    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _window(start: date, end: date) -> RequestedWindow:
    return RequestedWindow(
        WindowEndpoint(start.year, start.month, start.day, 0, 0, 0, 0),
        WindowEndpoint(end.year, end.month, end.day, 23, 59, 59, 999999),
    )


def _drive_ar_ina(
    request: ObservationRequest,
    *,
    transport: Transport,
    store: StoreRoot | None = None,
    cache: CacheMode = "reuse",
    receipts: ReceiptMode = ReceiptMode.OMIT,
) -> _AssemblyResult:
    effective_cache: CacheMode = "bypass" if store is None else cache
    return drive(
        request,
        _ArInaStages(),
        provenance=_provenance(request),
        receipts=receipts,
        transport=transport,
        cache=effective_cache,
        store=store,
    )


def _origin(
    url: str = _SERIES_URL,
    params: dict[str, str] | None = None,
) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=url,
        request_parameters=params or {},
        status_code=200,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/json; charset=utf-8",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


def _lookup_row(
    *,
    station_id: int,
    product_id: str,
    series_id: int,
    proc_id: int | None = None,
    unit_id: int | None = None,
    unit_abrev: str | None = None,
    data_availability: str = "C",
    timestart: str | None = "2020-01-01T03:00:00.000Z",
    timeend: str | None = "2025-01-01T03:00:00.000Z",
    count: int | None = 100,
    tipo: str = "puntual",
) -> dict[str, object]:
    spec = SPECS_BY_PRODUCT_ID[product_id]
    resolved_proc = spec.proc_id if proc_id is None else proc_id
    resolved_uid = spec.expected_unit_id if unit_id is None else unit_id
    resolved_uabrev = spec.expected_unit_abrev if unit_abrev is None else unit_abrev
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
    return {
        "tipo": tipo,
        "id": series_id,
        "estacion": {"id": station_id, "nombre": f"Station {station_id}"},
        "var": {
            "id": spec.var_id,
            "var": spec.var_code,
            "datatype": spec.expected_datatype,
            "timeSupport": spec.expected_time_support,
            "def_hora_corte": cutoff,
        },
        "procedimiento": {"id": resolved_proc, "abrev": "medicion" if resolved_proc == 1 else "curva"},
        "unidades": {"id": resolved_uid, "abrev": resolved_uabrev},
        "date_range": {
            "timestart": timestart,
            "timeend": timeend,
            "count": count,
            "data_availability": data_availability,
        },
    }


def _lookup_json(
    rows: list[dict[str, object]],
    *,
    total: int | str | None = None,
    is_last_page: bool = True,
) -> bytes:
    return json.dumps(
        {
            "rows": rows,
            "total": str(len(rows)) if total is None else total,
            "is_last_page": is_last_page,
        }
    ).encode("utf-8")


def _obs_row(
    *,
    obs_id: int | None,
    series_id: int,
    timestart: str,
    timeend: str,
    valor: float | None,
    unit_id: int | None = None,
    tipo: str = "puntual",
) -> dict[str, object]:
    return {
        "id": obs_id,
        "tipo": tipo,
        "series_id": series_id,
        "timestart": timestart,
        "timeend": timeend,
        "unit_id": unit_id,
        "valor": valor,
    }


class _QueuedTransport:
    def __init__(self, handler) -> None:
        self._handler = handler
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        return self._handler(request)


def _ok_response(request: TransportRequest, body: bytes) -> TransportResponse:
    params = {k: str(v) for k, v in (request.params or {}).items() if v is not None}
    return TransportResponse(
        content=body,
        status_code=200,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/json; charset=utf-8",
        url=request.url,
        request_parameters=params,
    )


def test_declaration_wires_live_stages_and_exposes_required_attributes() -> None:
    assert isinstance(declaration.observations, LiveStages)
    assert declaration.observations.stages.observation_source == "live"
    assert not hasattr(declaration.observations.stages, "shared_acquisition_products")
    stages = _ArInaStages()
    assert stages.config is config()
    assert stages.window_declarations is window_declarations()
    assert callable(stages.fetch)
    assert callable(stages.parse)


def test_config_and_window_declarations_cover_all_13_products_and_validate_coordinates() -> None:
    cfg = config()
    windows = window_declarations()
    assert cfg.zone.value == "+00:00"
    assert len(cfg.products) == 13
    assert set(cfg.products) == set(windows.products)

    for spec in IN_SCOPE_SERIES_SPECS:
        pid = ProductId(spec.product_id)
        product_cfg = cfg.products[pid]
        coords = product_cfg.coordinates.value
        assert isinstance(coords, ArInaSourceCoordinates)
        assert (coords.var_id, coords.proc_id, coords.published_series_id) == (spec.var_id, spec.proc_id, None)
        assert product_cfg.unit is (Unit.M3_S if spec.canonical_unit == "m3/s" else Unit.M)
        if spec.is_instantaneous:
            assert isinstance(product_cfg.semantics, Instant)
        elif spec.var_id == 85:
            assert isinstance(product_cfg.semantics, Hourly)
        else:
            assert isinstance(product_cfg.semantics, UnknownTemporalSupport)

        wdecl = windows.products[pid]
        assert wdecl.rendering is WindowRenderingVocabulary.ISO_INSTANT
        assert wdecl.stop_convention is StopConvention.INCLUSIVE
        if spec.is_instantaneous:
            assert (wdecl.granularity, wdecl.size, wdecl.stop_extension) == (
                WindowGranularity("capped-span"),
                365,
                None,
            )
        elif spec.var_id == 85:
            assert (wdecl.granularity, wdecl.size, wdecl.stop_extension) == (
                WindowGranularity("capped-span"),
                365,
                timedelta(hours=1),
            )
        elif spec.var_id == 101:
            assert (wdecl.granularity, wdecl.size, wdecl.stop_extension) == (
                WindowGranularity("capped-span"),
                365,
                timedelta(hours=4),
            )
        elif spec.frequency == "daily":
            assert (wdecl.granularity, wdecl.size, wdecl.stop_extension) == (
                WindowGranularity("capped-span"),
                3650,
                timedelta(hours=25),
            )
        elif spec.var_id == 67:
            assert (wdecl.granularity, wdecl.size, wdecl.stop_extension) == (
                WindowGranularity("iso-instant"),
                None,
                timedelta(days=7, hours=1),
            )
        else:
            assert (wdecl.granularity, wdecl.size, wdecl.stop_extension) == (
                WindowGranularity("iso-instant"),
                None,
                timedelta(days=31, hours=1),
            )

    with pytest.raises(ValueError, match="var_id"):
        ArInaSourceCoordinates(999, 1)
    with pytest.raises(ValueError, match="proc_id"):
        ArInaSourceCoordinates(40, 4)
    with pytest.raises(ValueError, match="published_series_id"):
        ArInaSourceCoordinates(40, 1, 0)
    with pytest.raises(ValueError, match="proc_id"):
        ArInaSeriesLookupCoordinates(4, 1)


def test_known_series_direct_fetch_skips_lookup_and_preserves_negative_stage_and_zero_discharge(
    tmp_path: Path,
) -> None:
    known_q = source_series("8", "discharge_daily_mean", published_series_id=26605)
    known_h = source_series("8", "stage_daily_mean", published_series_id=26100)

    def handler(request: TransportRequest) -> TransportResponse:
        assert request.url != _SERIES_URL, "known_series must bypass /obs/puntual/series lookup"
        assert request.params is not None
        assert request.params["skip_nulls"] == "true"
        if request.url.endswith("/26605/observaciones"):
            return _ok_response(
                request,
                json.dumps(
                    [
                        _obs_row(
                            obs_id=101,
                            series_id=26605,
                            timestart="2024-01-01T03:00:00.000Z",
                            timeend="2024-01-02T03:00:00.000Z",
                            valor=0.0,
                        ),
                        _obs_row(
                            obs_id=102,
                            series_id=26605,
                            timestart="2024-01-02T03:00:00.000Z",
                            timeend="2024-01-03T03:00:00.000Z",
                            valor=12.5,
                        ),
                        # Outside RequestedWindow(2024-01-01, 2024-01-02), inside 2-day fetch padding.
                        _obs_row(
                            obs_id=103,
                            series_id=26605,
                            timestart="2024-01-03T03:00:00.000Z",
                            timeend="2024-01-04T03:00:00.000Z",
                            valor=99.9,
                        ),
                    ]
                ).encode("utf-8"),
            )
        assert request.url.endswith("/26100/observaciones")
        return _ok_response(
            request,
            json.dumps(
                [
                    _obs_row(
                        obs_id=201,
                        series_id=26100,
                        timestart="2024-01-01T03:00:00.000Z",
                        timeend="2024-01-02T03:00:00.000Z",
                        valor=-0.35,
                    )
                ]
            ).encode("utf-8"),
        )

    transport = _QueuedTransport(handler)
    store = StoreRoot(tmp_path / "store")
    req = ObservationRequest(
        provider_id=ProviderId("ar_ina"),
        stations=("8",),
        products=(ProductId("discharge_daily_mean"), ProductId("stage_daily_mean")),
        window=_window(date(2024, 1, 1), date(2024, 1, 2)),
        known_series=(known_q, known_h),
    )
    result = _drive_ar_ina(req, transport=transport, store=store, cache="reuse", receipts=ReceiptMode.INCLUDE)

    assert len(transport.requests) == 2
    rows = result.canonical_rows.sort(["product_id", "time"]).to_dicts()
    assert [(r["product_id"], r["value"], r["unit"]) for r in rows] == [
        ("discharge_daily_mean", 0.0, "m3/s"),
        ("discharge_daily_mean", 12.5, "m3/s"),
        ("stage_daily_mean", -0.35, "m"),
    ]
    assert {o.status for o in result.outcomes} == {OutcomeStatus.SUCCESS}

    # Immediate cache="reuse" must issue zero network requests.
    reused = _drive_ar_ina(req, transport=transport, store=store, cache="reuse")
    assert len(transport.requests) == 2
    assert reused.canonical_rows.equals(result.canonical_rows)


def test_unknown_pairs_resolve_lookup_prerequisites_no_match_zero_count_empty_and_explicit_selector(
    tmp_path: Path,
) -> None:
    def handler(request: TransportRequest) -> TransportResponse:
        params = request.params or {}
        if request.url == _SERIES_URL:
            est = params["estacion_id"]
            var = params["var_id"]
            if (est, var) == ("8", "85"):
                return _ok_response(request, _lookup_json([], total=0))
            if (est, var) == ("1", "48"):
                return _ok_response(
                    request,
                    _lookup_json(
                        [
                            _lookup_row(
                                station_id=1,
                                product_id="discharge_monthly_mean",
                                series_id=24667,
                                data_availability="N",
                                timestart=None,
                                timeend=None,
                                count=None,
                            )
                        ]
                    ),
                )
            if (est, var) == ("8", "40"):
                return _ok_response(
                    request,
                    _lookup_json([_lookup_row(station_id=8, product_id="discharge_daily_mean", series_id=26605)]),
                )
        if request.url.endswith("/24667/observaciones"):
            return _ok_response(request, b"[]")
        if request.url.endswith("/26605/observaciones"):
            return _ok_response(
                request,
                json.dumps(
                    [
                        _obs_row(
                            obs_id=501,
                            series_id=26605,
                            timestart="2024-01-01T03:00:00.000Z",
                            timeend="2024-01-02T03:00:00.000Z",
                            valor=839.95,
                        )
                    ]
                ).encode("utf-8"),
            )
        raise AssertionError(f"Unexpected request: {request.url} {request.params}")

    transport = _QueuedTransport(handler)
    store = StoreRoot(tmp_path / "store")

    # 1. Absent series (rows: []) -> NO_MATCH, zero /observaciones calls, and cached on reuse.
    no_match_req = ObservationRequest(
        provider_id=ProviderId("ar_ina"),
        stations=("8",),
        products=(ProductId("stage_hourly"),),
        window=_window(date(2024, 1, 1), date(2024, 1, 2)),
    )
    no_match = _drive_ar_ina(no_match_req, transport=transport, store=store, cache="reuse")
    assert [o.status for o in no_match.outcomes] == [OutcomeStatus.NO_MATCH]
    assert any(i.code == "source.no_match" for i in no_match.issues)
    assert len(transport.requests) == 1

    no_match_reused = _drive_ar_ina(no_match_req, transport=transport, store=store, cache="reuse")
    assert len(transport.requests) == 1
    assert no_match_reused.canonical_rows.is_empty()

    # 2. Zero-count published series 24667 -> lookup + /24667/observaciones -> EMPTY (not NO_MATCH), with prerequisite link.
    zero_count_req = ObservationRequest(
        provider_id=ProviderId("ar_ina"),
        stations=("1",),
        products=(ProductId("discharge_monthly_mean"),),
        window=_window(date(2024, 1, 1), date(2024, 1, 2)),
    )
    zero_count = _drive_ar_ina(zero_count_req, transport=transport, store=store, cache="reuse")
    assert [o.status for o in zero_count.outcomes] == [OutcomeStatus.EMPTY]
    calls = zero_count.provenance.calls_made
    obs_calls = [c for c in calls if str(c.get("url", "")).endswith("/24667/observaciones")]
    assert len(obs_calls) == 1
    assert obs_calls[0]["prerequisite_acquisition_ids"]

    # 3. Unestablished explicit variant="999999999" must query /obs/puntual/series, never /999999999/observaciones,
    #    and emit NO_MATCH rather than misclassifying skip_nulls=true 200 [] as EMPTY.
    known_26605 = source_series("8", "discharge_daily_mean", published_series_id=26605)
    explicit_missing = _drive_ar_ina(
        ObservationRequest(
            provider_id=ProviderId("ar_ina"),
            stations=("8",),
            products=(ProductId("discharge_daily_mean"),),
            window=_window(date(2024, 1, 1), date(2024, 1, 2)),
            scope=SeriesScope(
                provider_ids=("ar_ina",),
                restriction=RestrictionKind.EXPLICIT,
                variants=("999999999",),
            ),
            known_series=(known_26605,),
        ),
        transport=transport,
        store=StoreRoot(tmp_path / "explicit_store"),
        cache="reuse",
    )
    assert not any("999999999" in req.url for req in transport.requests)
    assert [o.status for o in explicit_missing.outcomes] == [OutcomeStatus.NO_MATCH]
    assert explicit_missing.outcomes[0].requested_selector is not None
    assert explicit_missing.outcomes[0].requested_selector.value == "999999999"


def test_predicate_matching_distinguishes_known_mismatch_from_unestablished_day_definition(
    tmp_path: Path,
) -> None:
    known_26605 = source_series("8", "discharge_daily_mean", published_series_id=26605)
    transport = _QueuedTransport(lambda req: pytest.fail(f"Unexpected HTTP call: {req.url}"))

    known_false = _drive_ar_ina(
        ObservationRequest(
            provider_id=ProviderId("ar_ina"),
            stations=("8",),
            products=(ProductId("discharge_daily_mean"),),
            window=_window(date(2024, 1, 1), date(2024, 1, 2)),
            scope=SeriesScope(
                provider_ids=("ar_ina",),
                predicates=(PhysicalPredicate(field="statistic", value="max"),),
            ),
            known_series=(known_26605,),
        ),
        transport=transport,
        store=StoreRoot(tmp_path / "known_false"),
    )
    assert [o.status for o in known_false.outcomes] == [OutcomeStatus.NO_MATCH]

    unresolved = _drive_ar_ina(
        ObservationRequest(
            provider_id=ProviderId("ar_ina"),
            stations=("8",),
            products=(ProductId("discharge_daily_mean"),),
            window=_window(date(2024, 1, 1), date(2024, 1, 2)),
            scope=SeriesScope(
                provider_ids=("ar_ina",),
                predicates=(PhysicalPredicate(field="day_definition", value="00:00"),),
            ),
            known_series=(known_26605,),
        ),
        transport=transport,
        store=StoreRoot(tmp_path / "unresolved"),
    )
    assert [o.status for o in unresolved.outcomes] == [OutcomeStatus.UNRESOLVED]
    assert any(i.code == "source.inventory_unresolved" for i in unresolved.issues)
    assert all(inv.completeness is InventoryCompleteness.INCOMPLETE for inv in unresolved.inventories)


def test_parse_distinguishes_stored_db_nulls_synthesized_grid_nulls_duplicates_and_malformed_rows() -> None:
    cfg = config()
    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 3, 0, 0)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 3, 23, 59, 59, 999999)),
    )
    coords = SourceCoordinates(ArInaSourceCoordinates(85, 1, 31605))

    # 1. Genuine stored DB null (id > 0, valor: null) is preserved as value=None, while
    #    generateRegularSeries grid slot (id: null, valor: null) is omitted with info issue,
    #    and identical duplicate rows are deduplicated.
    mixed_payload = Payload(
        source_coordinates=coords,
        station_products=(("52", ProductId("stage_hourly")),),
        fetch_window=fw,
        content=json.dumps(
            [
                _obs_row(
                    obs_id=None,
                    series_id=31605,
                    timestart="2024-01-03T03:00:00.000Z",
                    timeend="2024-01-03T04:00:00.000Z",
                    valor=None,
                ),
                _obs_row(
                    obs_id=9001,
                    series_id=31605,
                    timestart="2024-01-03T06:00:00.000Z",
                    timeend="2024-01-03T07:00:00.000Z",
                    valor=None,
                ),
                _obs_row(
                    obs_id=9002,
                    series_id=31605,
                    timestart="2024-01-03T07:00:00.000Z",
                    timeend="2024-01-03T08:00:00.000Z",
                    valor=1.68,
                ),
                _obs_row(
                    obs_id=9002,
                    series_id=31605,
                    timestart="2024-01-03T07:00:00.000Z",
                    timeend="2024-01-03T08:00:00.000Z",
                    valor=1.68,
                ),
            ]
        ).encode("utf-8"),
        origin=_origin(),
        prerequisite_calls=(),
    )
    parsed = parse(mixed_payload, cfg)
    assert [o.status for o in parsed.outcomes] == [OutcomeStatus.SUCCESS]
    assert parsed.rows.select(["time", "value"]).to_dicts() == [
        {"time": datetime(2024, 1, 3, 6, 0), "value": None},
        {"time": datetime(2024, 1, 3, 7, 0), "value": 1.68},
    ]
    assert [i.code for i in parsed.issues] == ["source.synthesized_grid_null"]

    # 2. Numeric valor with id=None, conflicting duplicate timestamp, unit override, or series mismatch -> FAILED.
    bad_bodies = [
        [
            _obs_row(
                obs_id=None,
                series_id=31605,
                timestart="2024-01-03T06:00:00.000Z",
                timeend="2024-01-03T07:00:00.000Z",
                valor=1.5,
            )
        ],
        [
            _obs_row(
                obs_id=1,
                series_id=31605,
                timestart="2024-01-03T06:00:00.000Z",
                timeend="2024-01-03T07:00:00.000Z",
                valor=1.5,
            ),
            _obs_row(
                obs_id=2,
                series_id=31605,
                timestart="2024-01-03T06:00:00.000Z",
                timeend="2024-01-03T07:00:00.000Z",
                valor=1.9,
            ),
        ],
        [
            _obs_row(
                obs_id=1,
                series_id=31605,
                timestart="2024-01-03T06:00:00.000Z",
                timeend="2024-01-03T07:00:00.000Z",
                valor=1.5,
                unit_id=99,
            )
        ],
        [
            _obs_row(
                obs_id=1,
                series_id=99999,
                timestart="2024-01-03T06:00:00.000Z",
                timeend="2024-01-03T07:00:00.000Z",
                valor=1.5,
            )
        ],
    ]
    for bad_rows in bad_bodies:
        bad_parsed = parse(
            Payload(
                source_coordinates=coords,
                station_products=(("52", ProductId("stage_hourly")),),
                fetch_window=fw,
                content=json.dumps(bad_rows).encode("utf-8"),
                origin=_origin(),
                prerequisite_calls=(),
            ),
            cfg,
        )
        assert [o.status for o in bad_parsed.outcomes] == [OutcomeStatus.FAILED]
        assert bad_parsed.rows.is_empty()
        assert [i.code for i in bad_parsed.issues] == ["source.unsupported_structure"]


def test_resolve_series_lookup_rejects_paginated_station_mismatch_and_simulated_procedure() -> None:
    valid_row = _lookup_row(station_id=8, product_id="discharge_daily_mean", series_id=26605)
    with pytest.raises(UnsupportedSourceStructureError, match="is_last_page"):
        resolve_series_lookup(
            _lookup_json([valid_row], is_last_page=False),
            "8",
            ProductId("discharge_daily_mean"),
            evidence="test",
        )
    with pytest.raises(UnsupportedSourceStructureError, match="total"):
        resolve_series_lookup(
            _lookup_json([valid_row], total=2),
            "8",
            ProductId("discharge_daily_mean"),
            evidence="test",
        )
    with pytest.raises(UnsupportedSourceStructureError, match="estacion.id"):
        resolve_series_lookup(
            _lookup_json([valid_row]),
            "999",
            ProductId("discharge_daily_mean"),
            evidence="test",
        )
    sim_row = _lookup_row(station_id=8, product_id="discharge_daily_mean", series_id=90001, proc_id=4)
    with pytest.raises(UnsupportedSourceStructureError, match="procedure"):
        resolve_series_lookup(
            _lookup_json([sim_row]),
            "8",
            ProductId("discharge_daily_mean"),
            evidence="test",
        )
    with pytest.raises(FatalContractError, match="Unsupported INA Alerta5 product_id"):
        resolve_series_lookup(b"{}", "8", ProductId("unknown_product"), evidence="test")


def test_multichunk_stop_extension_deduplication_held_data_survival_and_sibling_isolation(
    tmp_path: Path,
) -> None:
    known_52 = source_series("52", "stage_hourly", published_series_id=31605)
    known_8 = source_series("8", "stage_hourly", published_series_id=39999)

    fail_refresh = False

    def handler(request: TransportRequest) -> TransportResponse:
        if request.url.endswith("/39999/observaciones"):
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=503,
                category=TransportFailureCategory.HTTP_STATUS,
            )
        assert request.url.endswith("/31605/observaciones")
        if fail_refresh:
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=503,
                category=TransportFailureCategory.HTTP_STATUS,
            )
        assert request.params is not None
        if request.params["timestart"].startswith("2023-11-30"):
            return _ok_response(
                request,
                json.dumps(
                    [
                        _obs_row(
                            obs_id=1,
                            series_id=31605,
                            timestart="2024-11-28T23:00:00.000Z",
                            timeend="2024-11-29T00:00:00.000Z",
                            valor=1.10,
                        ),
                        # Lookahead row pulled in by +1h stop_extension; belongs to chunk 2!
                        _obs_row(
                            obs_id=2,
                            series_id=31605,
                            timestart="2024-11-29T00:00:00.000Z",
                            timeend="2024-11-29T01:00:00.000Z",
                            valor=1.20,
                        ),
                    ]
                ).encode("utf-8"),
            )
        return _ok_response(
            request,
            json.dumps(
                [
                    _obs_row(
                        obs_id=2,
                        series_id=31605,
                        timestart="2024-11-29T00:00:00.000Z",
                        timeend="2024-11-29T01:00:00.000Z",
                        valor=1.20,
                    ),
                    _obs_row(
                        obs_id=3,
                        series_id=31605,
                        timestart="2024-12-01T12:00:00.000Z",
                        timeend="2024-12-01T13:00:00.000Z",
                        valor=1.30,
                    ),
                ]
            ).encode("utf-8"),
        )

    transport = _QueuedTransport(handler)
    store = StoreRoot(tmp_path / "store")
    req = ObservationRequest(
        provider_id=ProviderId("ar_ina"),
        stations=("52", "8"),
        products=(ProductId("stage_hourly"),),
        window=_window(date(2023, 12, 2), date(2024, 12, 5)),
        known_series=(known_52, known_8),
    )

    first = _drive_ar_ina(req, transport=transport, store=store, cache="reuse")
    assert first.canonical_rows.sort("time").select(["station_id", "value"]).to_dicts() == [
        {"station_id": "52", "value": 1.10},
        {"station_id": "52", "value": 1.20},
        {"station_id": "52", "value": 1.30},
    ]
    statuses_by_station = {(o.station_id, o.status) for o in first.outcomes}
    assert ("52", OutcomeStatus.SUCCESS) in statuses_by_station
    assert ("8", OutcomeStatus.FAILED) in statuses_by_station

    # Now fail refresh on station 52 and verify held rows survive intact!
    fail_refresh = True
    refreshed = _drive_ar_ina(
        ObservationRequest(
            provider_id=ProviderId("ar_ina"),
            stations=("52",),
            products=(ProductId("stage_hourly"),),
            window=_window(date(2023, 12, 2), date(2024, 12, 5)),
            known_series=(known_52,),
        ),
        transport=transport,
        store=store,
        cache="refresh",
    )
    assert refreshed.canonical_rows.sort("time").select("value").to_series().to_list() == [1.10, 1.20, 1.30]
    assert any(o.status is OutcomeStatus.FAILED for o in refreshed.outcomes)


def test_partial_second_chunk_failure_disappeared_catalogue_series_lookup_failure_and_fatal_contracts(
    tmp_path: Path,
) -> None:
    known_3346 = source_series("1741", "stage_instantaneous", published_series_id=3346)
    fail_chunk2 = True

    def chunk_handler(request: TransportRequest) -> TransportResponse:
        assert request.params is not None
        if request.params["timestart"].startswith("2023-11-30"):
            return _ok_response(
                request,
                json.dumps(
                    [
                        _obs_row(
                            obs_id=7001,
                            series_id=3346,
                            timestart="2023-12-10T12:00:00.000Z",
                            timeend="2023-12-10T12:00:00.000Z",
                            valor=2.45,
                        )
                    ]
                ).encode("utf-8"),
            )
        if fail_chunk2:
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=503,
                category=TransportFailureCategory.HTTP_STATUS,
            )
        return _ok_response(
            request,
            json.dumps(
                [
                    _obs_row(
                        obs_id=7002,
                        series_id=3346,
                        timestart="2024-12-01T12:00:00.000Z",
                        timeend="2024-12-01T12:00:00.000Z",
                        valor=2.55,
                    )
                ]
            ).encode("utf-8"),
        )

    transport = _QueuedTransport(chunk_handler)
    store = StoreRoot(tmp_path / "partial_store")
    req = ObservationRequest(
        provider_id=ProviderId("ar_ina"),
        stations=("1741",),
        products=(ProductId("stage_instantaneous"),),
        window=_window(date(2023, 12, 2), date(2024, 12, 5)),
        known_series=(known_3346,),
    )
    partial = _drive_ar_ina(req, transport=transport, store=store, cache="reuse")
    assert partial.canonical_rows.select("value").to_series().to_list() == [2.45]
    assert {o.status for o in partial.outcomes} == {OutcomeStatus.SUCCESS, OutcomeStatus.FAILED}
    assert partial.inventories[-1].completeness is InventoryCompleteness.INCOMPLETE
    assert "failed, unsupported or unresolved" in (partial.inventories[-1].reason or "")
    assert len(transport.requests) == 2

    # Because chunk 2 failed, cache="reuse" must NOT treat the full window as covered!
    fail_chunk2 = False
    completed = _drive_ar_ina(req, transport=transport, store=store, cache="reuse")
    assert len(transport.requests) > 2
    assert completed.canonical_rows.sort("time").select("value").to_series().to_list() == [2.45, 2.55]

    # Lookup HTTP 503 failure on unknown pair isolates cleanly from known sibling pair.
    def mixed_lookup_handler(request: TransportRequest) -> TransportResponse:
        if request.url == _SERIES_URL:
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=503,
                category=TransportFailureCategory.HTTP_STATUS,
            )
        return _ok_response(
            request,
            json.dumps(
                [
                    _obs_row(
                        obs_id=8001,
                        series_id=3346,
                        timestart="2024-01-01T12:00:00.000Z",
                        timeend="2024-01-01T12:00:00.000Z",
                        valor=3.01,
                    )
                ]
            ).encode("utf-8"),
        )

    mixed_res = _drive_ar_ina(
        ObservationRequest(
            provider_id=ProviderId("ar_ina"),
            stations=("1741",),
            products=(ProductId("stage_instantaneous"), ProductId("discharge_daily_mean")),
            window=_window(date(2024, 1, 1), date(2024, 1, 2)),
            known_series=(known_3346,),
        ),
        transport=_QueuedTransport(mixed_lookup_handler),
        store=StoreRoot(tmp_path / "mixed_lookup_store"),
    )
    assert mixed_res.canonical_rows.select("value").to_series().to_list() == [3.01]
    assert {(o.product_id, o.status) for o in mixed_res.outcomes} == {
        ("stage_instantaneous", OutcomeStatus.SUCCESS),
        ("discharge_daily_mean", OutcomeStatus.FAILED),
    }

    # Internal contract violations raise FatalContractError.
    cfg = config()
    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 2)),
    )
    with pytest.raises(FatalContractError):
        fetch((), (ProductId("stage_hourly"),), {}, fw, cfg, transport)
    with pytest.raises(FatalContractError):
        parse(
            Payload(
                source_coordinates=SourceCoordinates(ArInaSourceCoordinates(85, 1, None)),
                station_products=(("52", ProductId("stage_hourly")),),
                fetch_window=fw,
                content=b"[]",
                origin=_origin(),
                prerequisite_calls=(),
            ),
            cfg,
        )

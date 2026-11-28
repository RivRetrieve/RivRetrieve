"""Synthetic unit, driver/store, and catalogue-identity parity tests for Estonia (`ee_est`)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import pytest

from rivretrieve._internal.catalogues.source_series import catalogue_series
from rivretrieve._internal.driver import drive
from rivretrieve._internal.engine import (
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
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.ee_est.annotations import EE_EST_ESTMODEL_SCHEMA
from rivretrieve._internal.providers.ee_est.config import (
    EstModelCoordinates,
    FHydroseireCoordinates,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.ee_est.fetch import EeEstRequestPlanner, fetch
from rivretrieve._internal.providers.ee_est.parse import parse
from rivretrieve._internal.providers.ee_est.series import PRODUCT_SPECS, source_series
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.source_series import InventoryCompleteness, OutcomeStatus, SeriesScope, stable_id
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import (
    TRANSPORT_POLICY,
    HttpMethod,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)
from rivretrieve._internal.window_planning import plan_windows
from tests._catalogue import catalogue_reader
from tests.test_internal_driver import _provenance

_RETRIEVED_AT = datetime(2026, 11, 23, 13, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _EeEstStages:
    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


@dataclass(frozen=True)
class _PlannedEeEstStages:
    observation_source: str = "live"
    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    request_planner: EeEstRequestPlanner = EeEstRequestPlanner()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _envelope(
    url: str,
    params: dict[str, str],
    body: object,
    *,
    headers: dict[str, str] | None = None,
    status: int = 200,
) -> RecordingEnvelope:
    return RecordingEnvelope(
        request=RecordedRequest(
            HttpMethod.GET,
            url,
            params,
            ordinary_headers={
                "Accept": "application/json",
                **(headers or {}),
                "User-Agent": TRANSPORT_POLICY.user_agent,
            },
        ),
        content=body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"),
        status_code=status,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/json",
    )


def _origin(url: str) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=url,
        request_parameters={},
        status_code=200,
        retrieved_at=_RETRIEVED_AT,
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


def test_config_and_window_declarations_cover_all_18_products() -> None:
    cfg = config()
    win_decls = window_declarations()
    assert cfg.zone == ZoneValue("unknown")
    assert len(cfg.products) == 18
    assert set(cfg.products) == {ProductId(spec.product_id) for spec in PRODUCT_SPECS}

    for spec in PRODUCT_SPECS:
        pid = ProductId(spec.product_id)
        if spec.source_api == "estmodel":
            assert cfg.products[pid].coordinates.value == EstModelCoordinates(
                spec.em_parameter,
                spec.em_type,
                spec.product_id,  # type: ignore[arg-type]
            )
            decl = win_decls.products[pid]
            assert decl.granularity == WindowGranularity("n-year-chunk")
            assert decl.rendering == WindowRenderingVocabulary.YEAR
            assert decl.stop_convention == StopConvention.INCLUSIVE
            assert decl.size == 25
        else:
            assert cfg.products[pid].coordinates.value == FHydroseireCoordinates(
                spec.fh_aegrida_nimi,
                spec.product_id,  # type: ignore[arg-type]
            )
            assert cfg.products[pid].unit == (
                Unit.M3_S if spec.quantity == "discharge" else Unit.CM if spec.quantity == "stage" else Unit.DEG_C
            )
            decl = win_decls.products[pid]
            assert decl.granularity == WindowGranularity("capped-span")
            assert decl.rendering == WindowRenderingVocabulary.ISO_INSTANT
            assert decl.stop_convention == StopConvention.INCLUSIVE
            assert decl.size == 365

    with pytest.raises(FatalContractError, match="Invalid ee_est EstModel coordinates"):
        EstModelCoordinates("Q", "MEAN", "stage_daily_mean")
    with pytest.raises(FatalContractError, match="Invalid ee_est f_hydroseire coordinates"):
        FHydroseireCoordinates("WL avg", "discharge_hourly_mean")


def test_source_series_matches_every_packaged_catalogue_series_id_and_facts_id() -> None:
    artifact = catalogue_reader("ee_est").artifact
    materialized, _ = catalogue_series(artifact, scope=SeriesScope(provider_ids=("ee_est",)))
    assert len(materialized) == 1032

    cat_by_pair = {(item.station_id, item.product_id): item for item in materialized}
    for (station_id, product_id), cat_item in cat_by_pair.items():
        jaam_kood: int | None = None
        if cat_item.identity.namespace == "EE_EST.f_hydroseire.series":
            assert cat_item.identity.published_id is not None
            jaam_kood = int(cat_item.identity.published_id.split(":", 1)[0])
        runtime_item = source_series(station_id, product_id, jaam_kood=jaam_kood)
        assert runtime_item.series_id == cat_item.series_id
        assert runtime_item.series_id == stable_id(
            "ee_est", station_id, runtime_item.identity.namespace, runtime_item.identity.published_id
        )
        assert runtime_item.facts == cat_item.facts
        assert runtime_item.facts[0].facts_id == cat_item.facts[0].facts_id


def test_drive_estmodel_multi_chunk_annotations_and_cache_reuse(tmp_path: Path) -> None:
    series = source_series("SJA8821000", "stage_daily_mean")
    replay = ReplayTransport(
        (
            _envelope(
                "https://estmodel.envir.ee/stations/SJA8821000/measurements",
                {"parameter": "H", "type": "MEAN", "start-year": "2000", "end-year": "2024"},
                [{"parameter": "H", "startDate": "2024-12-31", "endDate": "2024-12-31", "value": 0.91, "unit": "m"}],
            ),
            _envelope(
                "https://estmodel.envir.ee/stations/SJA8821000/measurements",
                {"parameter": "H", "type": "MEAN", "start-year": "2025", "end-year": "2026"},
                [
                    {"parameter": "H", "startDate": "2025-12-31", "endDate": "2025-12-31", "value": 0.72, "unit": "m"},
                    {
                        "parameter": "H",
                        "startDate": "2026-01-01",
                        "endDate": "2026-01-01",
                        "value": 0.74,
                        "unit": "m",
                        "qualityFlag": "UNCHECKED",
                    },
                ],
            ),
        )
    )
    req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA8821000",),
        products=(ProductId("stage_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 1, 1)),
        ),
        known_series=(series,),
    )
    store = StoreRoot(tmp_path / "store")
    res = drive(
        req,
        _EeEstStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="reuse",
        store=store,
    )
    assert res.canonical_rows["time"].to_list() == [
        datetime(2024, 12, 31),
        datetime(2025, 12, 31),
        datetime(2026, 1, 1),
    ]
    assert res.canonical_rows["value"].to_list() == pytest.approx([0.91, 0.72, 0.74])
    assert res.canonical_rows["time_zone"].unique().to_list() == ["unknown"]
    ann_table = res.annotations.observation_tables[EE_EST_ESTMODEL_SCHEMA.schema_id]
    assert ann_table.rows["qualityFlag"].to_list() == [None, None, "UNCHECKED"]

    # Reuse hits local store with empty ReplayTransport (zero HTTP calls).
    empty_replay = ReplayTransport(())
    reused = drive(
        req,
        _EeEstStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=empty_replay,
        cache="reuse",
        store=store,
    )
    assert reused.canonical_rows.height == 3
    assert reused.annotations.observation_tables[EE_EST_ESTMODEL_SCHEMA.schema_id].rows["qualityFlag"].to_list() == [
        None,
        None,
        "UNCHECKED",
    ]


def test_drive_f_hydroseire_utc_cm_to_m_and_null_preservation(tmp_path: Path) -> None:
    series = source_series("SJA9204000", "stage_hourly_mean", jaam_kood=41116)
    replay = ReplayTransport(
        (
            _envelope(
                "https://keskkonnaandmed.envir.ee/f_hydroseire",
                {
                    "jaam_kood": "eq.41116",
                    "aegrida_nimi": "eq.WL avg",
                    "and": "(timeline_ts_utc.gte.2025-11-27T00:00:00Z,timeline_ts_utc.lte.2025-11-27T23:59:59.999999Z)",
                    "select": "jaam_kood,aegrida_nimi,timeline_ts_utc,vaartus",
                    "order": "timeline_ts_utc.asc",
                },
                [
                    {
                        "jaam_kood": 41116,
                        "aegrida_nimi": "WL avg",
                        "timeline_ts_utc": "2025-11-27T00:00:00",
                        "vaartus": -24.5,
                    },
                    {
                        "jaam_kood": 41116,
                        "aegrida_nimi": "WL avg",
                        "timeline_ts_utc": "2025-11-27T01:00:00",
                        "vaartus": None,
                    },
                ],
                headers={"Accept-Profile": "apijahiala"},
            ),
        )
    )
    req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA9204000",),
        products=(ProductId("stage_hourly_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2025, 11, 27, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2025, 11, 27, 23, 59, 59, 999999)),
        ),
        known_series=(series,),
    )
    res = drive(
        req,
        _EeEstStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=replay,
        cache="bypass",
        store=StoreRoot(tmp_path / "store"),
    )
    assert res.canonical_rows["source_unit"].to_list() == ["cm", "cm"]
    assert res.canonical_rows["unit"].to_list() == ["m", "m"]
    assert res.canonical_rows["time_zone"].to_list() == ["+00:00", "+00:00"]
    vals = res.canonical_rows["value"].to_list()
    assert vals[0] == pytest.approx(-0.245)
    assert vals[1] is None


def test_parse_confines_20000_cap_and_malformed_json_to_bounded_failed_outcomes() -> None:
    cfg = config()
    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 1, 23, 59, 59, 999999)),
    )
    fh_coords = FHydroseireCoordinates("WL avg", "stage_hourly_mean", jaam_kood=41061)
    capped_rows = [
        {"jaam_kood": 41061, "aegrida_nimi": "WL avg", "timeline_ts_utc": "2024-01-01T00:00:00", "vaartus": 100.0}
    ] * 20_000
    parsed_cap = parse(
        Payload(
            source_coordinates=SourceCoordinates(fh_coords),
            station_products=(("SJA8821000", ProductId("stage_hourly_mean")),),
            fetch_window=fw,
            content=json.dumps(capped_rows).encode("utf-8"),
            origin=_origin("https://keskkonnaandmed.envir.ee/f_hydroseire"),
            prerequisite_calls=(),
        ),
        cfg,
    )
    assert parsed_cap.rows.is_empty()
    assert parsed_cap.outcomes[0].status is OutcomeStatus.FAILED
    assert "20000" in (parsed_cap.outcomes[0].reason or "")
    assert parsed_cap.issues[0].code == "source.unsupported_structure"

    em_bad = parse(
        Payload(
            source_coordinates=cfg.products[ProductId("discharge_daily_mean")].coordinates,
            station_products=(("SJA8821000", ProductId("discharge_daily_mean")),),
            fetch_window=fw,
            content=json.dumps(
                [{"parameter": "H", "startDate": "2024-01-01", "endDate": "2024-01-01", "value": 1.0, "unit": "m"}]
            ).encode("utf-8"),
            origin=_origin("https://estmodel.envir.ee/stations/SJA8821000/measurements"),
            prerequisite_calls=(),
        ),
        cfg,
    )
    assert em_bad.rows.is_empty()
    assert em_bad.outcomes[0].status is OutcomeStatus.FAILED
    assert em_bad.issues[0].code == "source.unsupported_structure"


def test_fetch_isolates_404_failure_alongside_sibling_success(tmp_path: Path) -> None:
    class _MixedTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            if "MISSING" in request.url:
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=404,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            return TransportResponse(
                content=json.dumps(
                    [
                        {
                            "parameter": "Q",
                            "startDate": "2024-01-01",
                            "endDate": "2024-01-01",
                            "value": 4.2,
                            "unit": "m³/s",
                        }
                    ]
                ).encode("utf-8"),
                status_code=200,
                retrieved_at=_RETRIEVED_AT,
                content_type="application/json",
                url=request.url,
                request_parameters=MappingProxyType(dict(request.params or {})),
            )

    req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA8821000", "MISSING"),
        products=(ProductId("discharge_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
        ),
        known_series=(source_series("SJA8821000", "discharge_daily_mean"),),
    )
    res = drive(
        req,
        _EeEstStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=_MixedTransport(),
        cache="bypass",
        store=StoreRoot(tmp_path / "store"),
    )
    assert res.canonical_rows.height == 1
    assert res.canonical_rows["station_id"].to_list() == ["SJA8821000"]
    statuses = {o.station_id: o.status for o in res.outcomes}
    assert statuses == {"SJA8821000": OutcomeStatus.SUCCESS, "MISSING": OutcomeStatus.FAILED}
    assert any(issue.code == "source.http_not_found" for issue in res.issues)


@pytest.mark.parametrize("mode", ["empty", "malformed", "transport_503", "valid"])
def test_fetch_deduplicates_f_seirejaamad_lookup_across_three_hourly_products(mode: str) -> None:
    from rivretrieve._internal.engine import RenderedWindow

    hourly_products = (
        ProductId("stage_hourly_mean"),
        ProductId("discharge_hourly_mean"),
        ProductId("water_temperature_hourly_mean"),
    )
    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 3, 30, 0, 0)),
        WindowEndpoint.from_datetime(datetime(2024, 3, 30, 2, 59, 59, 999999)),
    )
    win = RenderedWindow("2024-03-30T00:00:00Z", "2024-03-30T02:59:59.999999Z", fw)
    rendered = dict.fromkeys(hourly_products, (win,))
    cfg = config()

    class _CountingTransport:
        def __init__(self) -> None:
            self.seirejaamad_requests: list[TransportRequest] = []
            self.hydroseire_requests: list[TransportRequest] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url.endswith("/f_seirejaamad"):
                self.seirejaamad_requests.append(request)
                if mode == "transport_503":
                    raise TransportFailure(
                        request,
                        TransportFailureReason.HTTP_STATUS,
                        1,
                        status_code=503,
                        category=TransportFailureCategory.HTTP_STATUS,
                    )
                if mode == "malformed":
                    raw = b"{not-json"
                elif mode == "empty":
                    raw = b"[]"
                else:
                    raw = json.dumps([{"kkr_kood": "SJA8821000", "kood": "41061"}]).encode("utf-8")
                return TransportResponse(
                    content=raw,
                    status_code=200,
                    retrieved_at=_RETRIEVED_AT,
                    content_type="application/json",
                    url=request.url,
                    request_parameters=MappingProxyType(dict(request.params or {})),
                )
            assert request.url.endswith("/f_hydroseire")
            self.hydroseire_requests.append(request)
            aegrida = dict(request.params or {})["aegrida_nimi"].removeprefix("eq.")
            return TransportResponse(
                content=json.dumps(
                    [
                        {
                            "jaam_kood": 41061,
                            "aegrida_nimi": aegrida,
                            "timeline_ts_utc": "2024-03-30T00:00:00",
                            "vaartus": 1.5,
                        }
                    ]
                ).encode("utf-8"),
                status_code=200,
                retrieved_at=_RETRIEVED_AT,
                content_type="application/json",
                url=request.url,
                request_parameters=MappingProxyType(dict(request.params or {})),
            )

    transport = _CountingTransport()
    acq = fetch(
        ("SJA8821000",),
        hourly_products,
        rendered,
        fw,
        cfg,
        transport,
        known_series=(),
    )

    assert len(transport.seirejaamad_requests) == 1
    if mode == "transport_503":
        assert transport.hydroseire_requests == []
        assert len(acq.failed_requests) == 3
        assert {item.series.product_id for item in acq.failed_requests} == {str(p) for p in hourly_products}
        assert acq.outcomes == ()
    elif mode in {"empty", "malformed"}:
        assert transport.hydroseire_requests == []
        assert len(acq.calls) == 1
        lookup_id = acq.calls[0].acquisition_id
        expected_status = OutcomeStatus.NO_MATCH if mode == "empty" else OutcomeStatus.FAILED
        expected_code = "source.no_match" if mode == "empty" else "source.unsupported_structure"
        assert len(acq.outcomes) == 3
        assert len(acq.inventories) == 3
        assert len(acq.issues) == 3
        assert {o.product_id for o in acq.outcomes} == {str(p) for p in hourly_products}
        assert all(o.status is expected_status and o.calls == (lookup_id,) for o in acq.outcomes)
        assert all(inv.evidence == (f"source-call:{lookup_id}",) for inv in acq.inventories)
        assert all(iss.code == expected_code for iss in acq.issues)
    else:
        assert len(transport.hydroseire_requests) == 3
        assert len(acq.value) == 3
        assert acq.issues == ()
        assert acq.failed_requests == ()


def test_parse_sorts_out_of_order_rows_and_rejects_invalid_calendar_dates() -> None:
    cfg = config()
    fw_em = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2024, 12, 31)),
    )
    unsorted_em = parse(
        Payload(
            source_coordinates=cfg.products[ProductId("discharge_daily_mean")].coordinates,
            station_products=(("SJA8821000", ProductId("discharge_daily_mean")),),
            fetch_window=fw_em,
            content=json.dumps(
                [
                    {
                        "parameter": "Q",
                        "startDate": "2024-01-03",
                        "endDate": "2024-01-03",
                        "value": 3.0,
                        "unit": "m³/s",
                        "qualityFlag": "UNCHECKED",
                    },
                    {
                        "parameter": "Q",
                        "startDate": "2024-01-01",
                        "endDate": "2024-01-01",
                        "value": 1.0,
                        "unit": "m³/s",
                        "qualityFlag": None,
                    },
                    {
                        "parameter": "Q",
                        "startDate": "2024-01-02",
                        "endDate": "2024-01-02",
                        "value": 2.0,
                        "unit": "m³/s",
                        "qualityFlag": "BELOW_LOQ",
                    },
                ]
            ).encode("utf-8"),
            origin=_origin("https://estmodel.envir.ee/stations/SJA8821000/measurements"),
            prerequisite_calls=(),
        ),
        cfg,
    )
    assert unsorted_em.rows["time"].to_list() == [
        datetime(2024, 1, 1),
        datetime(2024, 1, 2),
        datetime(2024, 1, 3),
    ]
    assert unsorted_em.rows["value"].to_list() == pytest.approx([1.0, 2.0, 3.0])
    assert unsorted_em.annotations.observation_tables[EE_EST_ESTMODEL_SCHEMA.schema_id].rows[
        "qualityFlag"
    ].to_list() == [
        None,
        "BELOW_LOQ",
        "UNCHECKED",
    ]

    bad_date = parse(
        Payload(
            source_coordinates=cfg.products[ProductId("discharge_daily_mean")].coordinates,
            station_products=(("SJA8821000", ProductId("discharge_daily_mean")),),
            fetch_window=fw_em,
            content=json.dumps(
                [{"parameter": "Q", "startDate": "2023-02-29", "endDate": "2023-02-29", "value": 1.0, "unit": "m³/s"}]
            ).encode("utf-8"),
            origin=_origin("https://estmodel.envir.ee/stations/SJA8821000/measurements"),
            prerequisite_calls=(),
        ),
        cfg,
    )
    assert bad_date.rows.is_empty()
    assert bad_date.outcomes[0].status is OutcomeStatus.FAILED
    assert bad_date.issues[0].code == "source.unsupported_structure"

    fw_fh = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1, 0, 0)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 1, 23, 59, 59, 999999)),
    )
    unsorted_fh = parse(
        Payload(
            source_coordinates=SourceCoordinates(
                FHydroseireCoordinates("WL avg", "stage_hourly_mean", jaam_kood=41061)
            ),
            station_products=(("SJA8821000", ProductId("stage_hourly_mean")),),
            fetch_window=fw_fh,
            content=json.dumps(
                [
                    {
                        "jaam_kood": 41061,
                        "aegrida_nimi": "WL avg",
                        "timeline_ts_utc": "2024-01-01T02:00:00",
                        "vaartus": 20.0,
                    },
                    {
                        "jaam_kood": 41061,
                        "aegrida_nimi": "WL avg",
                        "timeline_ts_utc": "2024-01-01T00:00:00",
                        "vaartus": 10.0,
                    },
                    {
                        "jaam_kood": 41061,
                        "aegrida_nimi": "WL avg",
                        "timeline_ts_utc": "2024-01-01T01:00:00",
                        "vaartus": 15.0,
                    },
                ]
            ).encode("utf-8"),
            origin=_origin("https://keskkonnaandmed.envir.ee/f_hydroseire"),
            prerequisite_calls=(),
        ),
        cfg,
    )
    assert unsorted_fh.rows["time"].to_list() == [
        datetime(2024, 1, 1, 0, 0),
        datetime(2024, 1, 1, 1, 0),
        datetime(2024, 1, 1, 2, 0),
    ]
    assert unsorted_fh.rows["value"].to_list() == pytest.approx([10.0, 15.0, 20.0])


def test_partial_chunk_failure_marks_estmodel_inventory_incomplete(tmp_path: Path) -> None:
    class _PartialEstModelTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if params["start-year"] == "2000":
                return TransportResponse(
                    content=json.dumps(
                        [
                            {
                                "parameter": "Q",
                                "startDate": "2024-12-31",
                                "endDate": "2024-12-31",
                                "value": 4.2,
                                "unit": "m³/s",
                            }
                        ]
                    ).encode("utf-8"),
                    status_code=200,
                    retrieved_at=_RETRIEVED_AT,
                    content_type="application/json",
                    url=request.url,
                    request_parameters=MappingProxyType(params),
                )
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=503,
                category=TransportFailureCategory.HTTP_STATUS,
            )

    fw_em = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2026, 1, 1)),
    )
    em_product = ProductId("discharge_daily_mean")
    em_acq = fetch(
        ("SJA8821000",),
        (em_product,),
        {em_product: plan_windows(fw_em, window_declarations().products[em_product])},
        fw_em,
        config(),
        _PartialEstModelTransport(),
        known_series=(source_series("SJA8821000", "discharge_daily_mean"),),
    )
    assert len(em_acq.value) == 1
    assert len(em_acq.failed_requests) == 1
    assert len(em_acq.inventories) == 1
    assert em_acq.inventories[0].completeness is InventoryCompleteness.INCOMPLETE
    assert em_acq.inventories[0].reason is not None

    req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA8821000",),
        products=(ProductId("discharge_daily_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2000, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 1, 1)),
        ),
        known_series=(source_series("SJA8821000", "discharge_daily_mean"),),
    )
    res = drive(
        req,
        _PlannedEeEstStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=_PartialEstModelTransport(),
        cache="bypass",
        store=StoreRoot(tmp_path / "store"),
    )
    assert res.canonical_rows["time"].to_list() == [datetime(2024, 12, 31)]
    assert res.canonical_rows["value"].to_list() == pytest.approx([4.2])
    assert {o.status for o in res.outcomes} == {OutcomeStatus.SUCCESS, OutcomeStatus.FAILED}
    assert res.inventories
    assert all(inv.completeness is InventoryCompleteness.INCOMPLETE for inv in res.inventories)


def test_partial_chunk_failure_marks_f_hydroseire_inventory_incomplete(tmp_path: Path) -> None:
    class _PartialFhTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if "2024-01-01T00:00:00Z" in params["and"]:
                return TransportResponse(
                    content=json.dumps(
                        [
                            {
                                "jaam_kood": 41061,
                                "aegrida_nimi": "WL avg",
                                "timeline_ts_utc": "2024-01-01T00:00:00",
                                "vaartus": 100.0,
                            }
                        ]
                    ).encode("utf-8"),
                    status_code=200,
                    retrieved_at=_RETRIEVED_AT,
                    content_type="application/json",
                    url=request.url,
                    request_parameters=MappingProxyType(params),
                )
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=503,
                category=TransportFailureCategory.HTTP_STATUS,
            )

    fw_fh = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1, 0, 0)),
        WindowEndpoint.from_datetime(datetime(2025, 1, 5, 23, 0)),
    )
    fh_product = ProductId("stage_hourly_mean")
    fh_acq = fetch(
        ("SJA8821000",),
        (fh_product,),
        {fh_product: plan_windows(fw_fh, window_declarations().products[fh_product])},
        fw_fh,
        config(),
        _PartialFhTransport(),
        known_series=(source_series("SJA8821000", "stage_hourly_mean", jaam_kood=41061),),
        station_codes={"SJA8821000": (41061,)},
    )
    assert len(fh_acq.value) == 1
    assert len(fh_acq.failed_requests) == 1
    assert len(fh_acq.inventories) == 1
    assert fh_acq.inventories[0].completeness is InventoryCompleteness.INCOMPLETE
    assert fh_acq.inventories[0].reason is not None

    planner = EeEstRequestPlanner(station_codes={"SJA8821000": (41061,)})
    req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA8821000",),
        products=(ProductId("stage_hourly_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2025, 1, 5, 23, 0)),
        ),
        known_series=(source_series("SJA8821000", "stage_hourly_mean", jaam_kood=41061),),
    )
    res = drive(
        req,
        _PlannedEeEstStages(request_planner=planner),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=_PartialFhTransport(),
        cache="bypass",
        store=StoreRoot(tmp_path / "store"),
    )
    assert res.canonical_rows["time"].to_list() == [datetime(2024, 1, 1, 0, 0)]
    assert res.canonical_rows["value"].to_list() == pytest.approx([1.0])
    assert {o.status for o in res.outcomes} == {OutcomeStatus.SUCCESS, OutcomeStatus.FAILED}
    assert res.inventories
    assert all(inv.completeness is InventoryCompleteness.INCOMPLETE for inv in res.inventories)


def test_dual_code_one_active_one_empty_complete_without_phantom_series(tmp_path: Path) -> None:
    s_41022 = source_series("SJA5524000", "stage_hourly_mean", jaam_kood=41022)
    s_41960 = source_series("SJA5524000", "stage_hourly_mean", jaam_kood=41960)
    seen_params: list[dict[str, str]] = []

    class _OneActiveTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            seen_params.append(params)
            assert "limit" not in params
            if params["jaam_kood"] == "eq.41022":
                rows = [
                    {
                        "jaam_kood": 41022,
                        "aegrida_nimi": "WL avg",
                        "timeline_ts_utc": "2026-10-01T00:00:00",
                        "vaartus": 34.5,
                    }
                ]
            else:
                assert params["jaam_kood"] == "eq.41960"
                rows = []
            return TransportResponse(
                content=json.dumps(rows).encode("utf-8"),
                status_code=200,
                retrieved_at=_RETRIEVED_AT,
                content_type="application/json",
                url=request.url,
                request_parameters=MappingProxyType(params),
            )

    req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA5524000",),
        products=(ProductId("stage_hourly_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 10, 1, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 1, 23, 0)),
        ),
        known_series=(s_41022,),
    )
    res = drive(
        req,
        _PlannedEeEstStages(request_planner=EeEstRequestPlanner(station_codes={"SJA5524000": (41022, 41960)})),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=_OneActiveTransport(),
        cache="bypass",
        store=StoreRoot(tmp_path / "store"),
    )
    assert [p["jaam_kood"] for p in seen_params] == ["eq.41022", "eq.41960"]
    assert res.canonical_rows["value"].to_list() == pytest.approx([0.345])
    assert res.canonical_rows["series_id"].to_list() == [s_41022.series_id]
    assert [s.series_id for s in res.source_series] == [s_41022.series_id]
    assert s_41960.series_id not in {o.series_id for o in res.outcomes}
    assert all(
        inv.completeness is InventoryCompleteness.COMPLETE
        and inv.members == (s_41022.series_id,)
        and sum(1 for ev in inv.evidence if ev.startswith("source-call:")) == 2
        for inv in res.inventories
    )


def test_dual_code_both_active_keeps_two_separate_series(tmp_path: Path) -> None:
    s_41022 = source_series("SJA5524000", "stage_hourly_mean", jaam_kood=41022)
    s_41960 = source_series("SJA5524000", "stage_hourly_mean", jaam_kood=41960)

    class _BothActiveTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            code = 41022 if params["jaam_kood"] == "eq.41022" else 41960
            vaartus = 100.0 if code == 41022 else 200.0
            return TransportResponse(
                content=json.dumps(
                    [
                        {
                            "jaam_kood": code,
                            "aegrida_nimi": "WL avg",
                            "timeline_ts_utc": "2026-10-01T00:00:00",
                            "vaartus": vaartus,
                        }
                    ]
                ).encode("utf-8"),
                status_code=200,
                retrieved_at=_RETRIEVED_AT,
                content_type="application/json",
                url=request.url,
                request_parameters=MappingProxyType(params),
            )

    req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA5524000",),
        products=(ProductId("stage_hourly_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 10, 1, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 1, 23, 0)),
        ),
        known_series=(s_41022,),
    )
    res = drive(
        req,
        _PlannedEeEstStages(request_planner=EeEstRequestPlanner(station_codes={"SJA5524000": (41022, 41960)})),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=_BothActiveTransport(),
        cache="bypass",
        store=StoreRoot(tmp_path / "store"),
    )
    by_sid = {row["series_id"]: row["value"] for row in res.canonical_rows.to_dicts()}
    assert by_sid == {s_41022.series_id: pytest.approx(1.0), s_41960.series_id: pytest.approx(2.0)}
    assert {s.identity.published_id for s in res.source_series} == {"41022:WL avg", "41960:WL avg"}
    assert res.inventories
    assert all(
        inv.completeness is InventoryCompleteness.COMPLETE
        and set(inv.members) == {s_41022.series_id, s_41960.series_id}
        for inv in res.inventories
    )


def test_dual_code_one_active_one_failed_marks_inventory_incomplete(tmp_path: Path) -> None:
    s_41022 = source_series("SJA5524000", "stage_hourly_mean", jaam_kood=41022)

    class _OneFailedTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if params["jaam_kood"] == "eq.41022":
                return TransportResponse(
                    content=json.dumps(
                        [
                            {
                                "jaam_kood": 41022,
                                "aegrida_nimi": "WL avg",
                                "timeline_ts_utc": "2026-10-01T00:00:00",
                                "vaartus": 50.0,
                            }
                        ]
                    ).encode("utf-8"),
                    status_code=200,
                    retrieved_at=_RETRIEVED_AT,
                    content_type="application/json",
                    url=request.url,
                    request_parameters=MappingProxyType(params),
                )
            raise TransportFailure(
                request,
                TransportFailureReason.HTTP_STATUS,
                1,
                status_code=503,
                category=TransportFailureCategory.HTTP_STATUS,
            )

    req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA5524000",),
        products=(ProductId("stage_hourly_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 10, 1, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 1, 23, 0)),
        ),
        known_series=(s_41022,),
    )
    res = drive(
        req,
        _PlannedEeEstStages(request_planner=EeEstRequestPlanner(station_codes={"SJA5524000": (41022, 41960)})),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=_OneFailedTransport(),
        cache="bypass",
        store=StoreRoot(tmp_path / "store"),
    )
    assert res.canonical_rows["value"].to_list() == pytest.approx([0.5])
    assert {o.status for o in res.outcomes} == {OutcomeStatus.SUCCESS, OutcomeStatus.FAILED}
    assert res.inventories
    assert all(inv.completeness is InventoryCompleteness.INCOMPLETE for inv in res.inventories)


def test_drive_request_planner_deduplicates_lookup_and_handles_empty_station_codes(tmp_path: Path) -> None:
    seirejaamad_calls = 0

    class _PlannerTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            nonlocal seirejaamad_calls
            params = dict(request.params or {})
            if request.url.endswith("/f_seirejaamad"):
                seirejaamad_calls += 1
                raw: object = [{"kkr_kood": "SJA8821000", "kood": "41061"}]
            elif request.url.endswith("/f_hydroseire"):
                raw = [
                    {
                        "jaam_kood": 41061,
                        "aegrida_nimi": params["aegrida_nimi"].removeprefix("eq."),
                        "timeline_ts_utc": "2024-03-30T00:00:00",
                        "vaartus": 2.0,
                    }
                ]
            else:
                raw = [
                    {"parameter": "Q", "startDate": "2024-03-30", "endDate": "2024-03-30", "value": 9.5, "unit": "m³/s"}
                ]
            return TransportResponse(
                content=json.dumps(raw).encode("utf-8"),
                status_code=200,
                retrieved_at=_RETRIEVED_AT,
                content_type="application/json",
                url=request.url,
                request_parameters=MappingProxyType(params),
            )

    req = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA8821000",),
        products=(
            ProductId("discharge_daily_mean"),
            ProductId("stage_hourly_mean"),
            ProductId("discharge_hourly_mean"),
            ProductId("water_temperature_hourly_mean"),
        ),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2024, 3, 30, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2024, 3, 30, 23, 0)),
        ),
    )
    res = drive(
        req,
        _PlannedEeEstStages(),
        provenance=_provenance(req),
        receipts=ReceiptMode.OMIT,
        transport=_PlannerTransport(),
        cache="bypass",
        store=StoreRoot(tmp_path / "store-dedup"),
    )
    assert seirejaamad_calls == 1
    assert res.canonical_rows.height == 4
    assert {o.status for o in res.outcomes} == {OutcomeStatus.SUCCESS}

    # All candidate codes empty settles as NO_MATCH with COMPLETE inventory; empty station_codes skips HTTP.
    class _AllEmptyTransport:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            return TransportResponse(
                content=b"[]",
                status_code=200,
                retrieved_at=_RETRIEVED_AT,
                content_type="application/json",
                url=request.url,
                request_parameters=MappingProxyType(dict(request.params or {})),
            )

    t_empty = _AllEmptyTransport()
    req_all_empty = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJA0000001",),
        products=(ProductId("stage_hourly_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 10, 1, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 1, 23, 0)),
        ),
    )
    res_all_empty = drive(
        req_all_empty,
        _PlannedEeEstStages(request_planner=EeEstRequestPlanner(station_codes={"SJA0000001": (41888, 41889)})),
        provenance=_provenance(req_all_empty),
        receipts=ReceiptMode.OMIT,
        transport=t_empty,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-all-empty"),
    )
    assert t_empty.calls == 2
    assert res_all_empty.canonical_rows.is_empty()
    assert res_all_empty.source_series == ()
    assert [o.status for o in res_all_empty.outcomes] == [OutcomeStatus.NO_MATCH]
    assert res_all_empty.inventories and res_all_empty.inventories[0].completeness is InventoryCompleteness.COMPLETE
    assert res_all_empty.inventories[0].members == ()

    t_none = _AllEmptyTransport()
    req_none = ObservationRequest(
        provider_id=ProviderId("ee_est"),
        stations=("SJB9999999",),
        products=(ProductId("stage_hourly_mean"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 10, 1, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 1, 23, 0)),
        ),
    )
    res_none = drive(
        req_none,
        _PlannedEeEstStages(request_planner=EeEstRequestPlanner(station_codes={"SJB9999999": ()})),
        provenance=_provenance(req_none),
        receipts=ReceiptMode.OMIT,
        transport=t_none,
        cache="bypass",
        store=StoreRoot(tmp_path / "store-none"),
    )
    assert t_none.calls == 0
    assert [o.status for o in res_none.outcomes] == [OutcomeStatus.NO_MATCH]
    assert res_none.inventories and res_none.inventories[0].completeness is InventoryCompleteness.COMPLETE

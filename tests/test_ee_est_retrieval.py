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
from rivretrieve._internal.providers.ee_est.fetch import fetch
from rivretrieve._internal.providers.ee_est.parse import parse
from rivretrieve._internal.providers.ee_est.series import PRODUCT_SPECS, source_series
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.source_series import OutcomeStatus, SeriesScope, stable_id
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
from tests._catalogue import catalogue_reader
from tests.test_internal_driver import _provenance

_RETRIEVED_AT = datetime(2026, 11, 23, 13, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _EeEstStages:
    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
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

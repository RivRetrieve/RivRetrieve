"""Synthetic unit and assembled driver/store controls for Colombia IDEAM S3 retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

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
    UnknownTemporalSupport,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    ZoneValue,
    _make_fetch_window,
)
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.co_ideam.config import (
    CoIdeamS3CsvCoordinates,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.co_ideam.declaration import declaration
from rivretrieve._internal.providers.co_ideam.fetch import fetch, s3_observation_csv_url
from rivretrieve._internal.providers.co_ideam.parse import parse
from rivretrieve._internal.providers.co_ideam.series import SERIES_SPECS, source_series
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.recordings import RecordedRequest, RecordingEnvelope, ReplayTransport
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    OutcomeStatus,
    SeriesScope,
)
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import (
    HttpMethod,
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)
from tests.test_internal_driver import _provenance

_RETRIEVED_AT = datetime(2026, 11, 8, 18, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _CoIdeamStages:
    """Explicit stage bundle matching the Step 4/5 provider contract."""

    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _origin(url: str, status: int = 200) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=url,
        request_parameters={},
        status_code=status,
        retrieved_at=_RETRIEVED_AT,
        content_type="text/csv",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


def _csv_bytes(*rows: tuple[str, str, str], bom: bool = False) -> bytes:
    lines = ["fechaObservacion,valorObservado,nivelAprobacion"]
    lines.extend(f"{ts},{val},{app}" for ts, val, app in rows)
    text = "\n".join(lines) + "\n"
    return ("\ufeff" + text if bom else text).encode("utf-8")


def test_declaration_exposes_live_stages_and_config_covers_all_20_products() -> None:
    assert isinstance(declaration.observations, LiveStages)
    cfg = config()
    win_decls = window_declarations()
    assert cfg.zone == ZoneValue("unknown")
    assert len(cfg.products) == 20
    assert set(cfg.products) == {ProductId(spec.product_id) for spec in SERIES_SPECS}

    for spec in SERIES_SPECS:
        pid = ProductId(spec.product_id)
        prod_cfg = cfg.products[pid]
        assert prod_cfg.coordinates.value == CoIdeamS3CsvCoordinates(spec.etiqueta, spec.product_id)
        assert prod_cfg.unit == (Unit.M3_S if spec.source_unit == "m3/s" else Unit.CM)
        assert prod_cfg.semantics == UnknownTemporalSupport()
        decl = win_decls.products[pid]
        assert decl.granularity == WindowGranularity("none")
        assert decl.rendering == WindowRenderingVocabulary.NONE
        assert decl.stop_convention == StopConvention.INCLUSIVE

    with pytest.raises(FatalContractError, match="Unsupported IDEAM S3 hydrological etiqueta"):
        CoIdeamS3CsvCoordinates("CM_D", "cm_d")
    with pytest.raises(FatalContractError, match="Invalid co_ideam S3 route coordinates"):
        CoIdeamS3CsvCoordinates("Q_MEDIA_D", "nv_media_d")


def test_fetch_and_url_builder_enforce_canonical_station_ids_and_window_contracts() -> None:
    assert s3_observation_csv_url("0011017010", "Q_MEDIA_D") == (
        "https://datos.ideam.gov.co/s3-estacionesideam/observaciones/historicos/csv/Q_MEDIA_D/0011017010-Q_MEDIA_D.csv"
    )
    for bad_station in ("", "11017010", "001101701A", "../0110170", "００１１０１７０１０"):
        with pytest.raises(FatalContractError, match="10-digit ASCII"):
            s3_observation_csv_url(bad_station, "Q_MEDIA_D")

    cfg = config()
    win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 2)),
    )
    replay = ReplayTransport(())

    with pytest.raises(FatalContractError, match="at least one station"):
        fetch((), (ProductId("q_media_d"),), {ProductId("q_media_d"): ()}, win, cfg, replay)
    with pytest.raises(FatalContractError, match="absent from provider config"):
        fetch(("0011017010",), (ProductId("unknown_prod"),), {}, win, cfg, replay)
    with pytest.raises(FatalContractError, match="10-digit ASCII"):
        fetch(("11017010",), (ProductId("q_media_d"),), {ProductId("q_media_d"): ()}, win, cfg, replay)


def test_all_20_products_parse_units_approvals_negative_values_and_hora_gaviria_fold(tmp_path: Path) -> None:
    station = "0011017010"
    sample_ts = {
        None: [("1993-02-06 23:00:00", "-12.5", "Preliminar"), ("1993-02-06 23:00:00", "0.0", "Definitivo")],
        "daily": [("1992-08-01 01:00:00", "0.0", "En revisión"), ("1992-08-02 01:00:00", "25.0", "")],
        "monthly": [("2020-01-01 00:00:00", "10.0", ""), ("2020-02-01 00:00:00", "-5.0", "Definitivo")],
        "yearly": [("2020-01-01 00:00:00", "100.0", "Preliminar")],
    }
    envelopes = []
    known_list = []
    products = []
    for spec in SERIES_SPECS:
        pid = ProductId(spec.product_id)
        products.append(pid)
        known_list.append(source_series(station, spec.etiqueta))
        url = s3_observation_csv_url(station, spec.etiqueta)
        envelopes.append(
            RecordingEnvelope(
                request=RecordedRequest(HttpMethod.GET, url, None, ordinary_headers={"User-Agent": "RivRetrieve"}),
                content=_csv_bytes(*sample_ts[spec.frequency], bom=(spec.etiqueta == "NIVEL_H")),
                status_code=200,
                retrieved_at=_RETRIEVED_AT,
                content_type="text/csv",
            )
        )

    req = ObservationRequest(
        provider_id=ProviderId("co_ideam"),
        stations=(station,),
        products=tuple(products),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1992, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2021, 1, 1)),
        ),
        known_series=tuple(known_list),
        scope=SeriesScope(provider_ids=("co_ideam",), station_ids=(station,)),
    )
    res = drive(
        req,
        _CoIdeamStages(),
        provenance=_provenance(req),
        transport=ReplayTransport(tuple(envelopes)),
        cache="bypass",
        store=StoreRoot(tmp_path / "store"),
        receipts=ReceiptMode.INCLUDE,
    )
    assert res.issues == ()
    assert len(res.source_series) == 20
    assert all(s.identity.origin == "catalogue" for s in res.source_series)

    # Verify duplicate 1993-02-06 23:00:00 fold rows and cm -> m vs m3/s -> m3/s scaling.
    nivel_h_rows = res.canonical_rows.filter(res.canonical_rows["product_id"] == "nivel_h")
    assert nivel_h_rows.height == 2
    assert nivel_h_rows["time"].to_list() == [datetime(1993, 2, 6, 23, 0), datetime(1993, 2, 6, 23, 0)]
    assert nivel_h_rows["value"].to_list() == pytest.approx([-0.125, 0.0])
    assert nivel_h_rows["unit"].to_list() == ["m", "m"]
    assert nivel_h_rows["time_zone"].to_list() == ["unknown", "unknown"]

    caudal_h_rows = res.canonical_rows.filter(res.canonical_rows["product_id"] == "caudal_h")
    assert caudal_h_rows.height == 2
    assert caudal_h_rows["value"].to_list() == pytest.approx([-12.5, 0.0])
    assert caudal_h_rows["unit"].to_list() == ["m3/s", "m3/s"]


def test_option_1a_interval_coverage_reuse_refresh_and_preliminar_spike_retirement(tmp_path: Path) -> None:
    station = "0024057080"
    product = ProductId("q_media_d")
    known = source_series(station, "Q_MEDIA_D")
    scope = SeriesScope(provider_ids=("co_ideam",), station_ids=(station,), product_ids=("q_media_d",))
    url = s3_observation_csv_url(station, "Q_MEDIA_D")

    # Snapshot 1 starts during 1992 Hora Gaviria (01:00:00) and includes a Preliminar spike on 1992-08-03.
    snap_1 = _csv_bytes(
        ("1992-08-01 01:00:00", "12.0", "Definitivo"),
        ("1992-08-02 01:00:00", "15.0", "Preliminar"),
        ("1992-08-03 01:00:00", "999.0", "Preliminar"),
        ("1992-08-04 01:00:00", "14.0", "Preliminar"),
    )
    # Snapshot 2 revises 1992-08-02, deletes the 1992-08-03 spike row, and appends 1992-08-05.
    snap_2 = _csv_bytes(
        ("1992-08-01 01:00:00", "12.0", "Definitivo"),
        ("1992-08-02 01:00:00", "16.5", "Definitivo"),
        ("1992-08-04 01:00:00", "14.0", "Definitivo"),
        ("1992-08-05 01:00:00", "18.0", "Preliminar"),
    )

    class _MutableTransport:
        def __init__(self, body: bytes) -> None:
            self.body = body
            self.calls = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            assert request.url == url
            return TransportResponse(self.body, 200, _RETRIEVED_AT, "text/csv", url, {})

    transport = _MutableTransport(snap_1)
    store = StoreRoot(tmp_path / "store_1a")

    # 1. Request 1992-07-25..1992-08-10: [1992-08-01 00:00:00, 1992-08-04 23:59:59.999999] is SUCCESS (interval),
    # while pre-record and post-record tails are UNRESOLVED (never EMPTY).
    req_wide = ObservationRequest(
        provider_id=ProviderId("co_ideam"),
        stations=(station,),
        products=(product,),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1992, 7, 25)),
            WindowEndpoint.from_datetime(datetime(1992, 8, 10)),
        ),
        known_series=(known,),
        scope=scope,
    )
    first = drive(
        req_wide, _CoIdeamStages(), provenance=_provenance(req_wide), transport=transport, cache="reuse", store=store
    )
    assert transport.calls == 1
    assert first.canonical_rows["value"].to_list() == pytest.approx([12.0, 15.0, 999.0, 14.0])
    assert all(o.status is not OutcomeStatus.EMPTY for o in first.outcomes)
    pos = next(o for o in first.outcomes if o.status is OutcomeStatus.SUCCESS)
    assert pos.coverage == "interval"
    assert pos.window.start == datetime(1992, 8, 1, 0, 0)
    assert pos.window.end == datetime(1992, 8, 4, 23, 59, 59, 999999)
    unresolved = [o for o in first.outcomes if o.status is OutcomeStatus.UNRESOLVED]
    assert len(unresolved) == 2

    # 2. Historical query inside [1992-08-01, 1992-08-04] hits cache offline (0 extra HTTP calls) even with 01:00:00 row!
    req_inside = ObservationRequest(
        provider_id=ProviderId("co_ideam"),
        stations=(station,),
        products=(product,),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1992, 8, 1)),
            WindowEndpoint.from_datetime(datetime(1992, 8, 4)),
        ),
        known_series=(known,),
        scope=scope,
    )
    reused = drive(
        req_inside,
        _CoIdeamStages(),
        provenance=_provenance(req_inside),
        transport=transport,
        cache="reuse",
        store=store,
    )
    assert transport.calls == 1
    assert reused.canonical_rows["value"].to_list() == pytest.approx([12.0, 15.0, 999.0, 14.0])
    assert [o.status for o in reused.outcomes] == [OutcomeStatus.SUCCESS]

    # 3. Query extending into 1992-08-05 hits UNRESOLVED tail -> re-fetches snap_2, revises 08-02, retires deleted 08-03 spike!
    transport.body = snap_2
    req_ext = ObservationRequest(
        provider_id=ProviderId("co_ideam"),
        stations=(station,),
        products=(product,),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1992, 8, 1)),
            WindowEndpoint.from_datetime(datetime(1992, 8, 5)),
        ),
        known_series=(known,),
        scope=scope,
    )
    updated = drive(
        req_ext, _CoIdeamStages(), provenance=_provenance(req_ext), transport=transport, cache="reuse", store=store
    )
    assert transport.calls == 2
    assert updated.canonical_rows["time"].to_list() == [
        datetime(1992, 8, 1, 1, 0),
        datetime(1992, 8, 2, 1, 0),
        datetime(1992, 8, 4, 1, 0),
        datetime(1992, 8, 5, 1, 0),
    ]
    assert updated.canonical_rows["value"].to_list() == pytest.approx([12.0, 16.5, 14.0, 18.0])


def test_header_only_csv_yields_unresolved_incomplete_inventory_without_empty_claim() -> None:
    cfg = config()
    win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2020, 12, 31)),
    )
    url = s3_observation_csv_url("0026157160", "NV_MN_A")
    parsed = parse(
        Payload(
            cfg.products[ProductId("nv_mn_a")].coordinates,
            (("0026157160", ProductId("nv_mn_a")),),
            win,
            b"fechaObservacion,valorObservado,nivelAprobacion\n",
            _origin(url),
            (),
        ),
        cfg,
    )
    assert parsed.rows.is_empty()
    assert len(parsed.series) == 1
    assert [o.status for o in parsed.outcomes] == [OutcomeStatus.UNRESOLVED]
    assert [inv.completeness for inv in parsed.inventories] == [InventoryCompleteness.INCOMPLETE]
    assert parsed.issues == ()


def test_option_2a_http_404_and_503_isolate_siblings_and_retain_held_rows(tmp_path: Path) -> None:
    station = "0026157160"
    stage_prod = ProductId("nv_mn_a")
    missing_q_prod = ProductId("caudal_h")
    stage_known = source_series(station, "NV_MN_A")
    stage_url = s3_observation_csv_url(station, "NV_MN_A")
    missing_url = s3_observation_csv_url(station, "CAUDAL_H")
    no_such_key_xml = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b"<Error><Code>NoSuchKey</Code><Message>The specified key does not exist.</Message></Error>"
    )

    class _SiblingAndTransient404Transport:
        def __init__(self) -> None:
            self.stage_status = 200

        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url == missing_url:
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=404,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            if self.stage_status != 200:
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=self.stage_status,
                    category=TransportFailureCategory.HTTP_STATUS,
                    response=TransportResponse(
                        no_such_key_xml, self.stage_status, _RETRIEVED_AT, "application/xml", stage_url, {}
                    ),
                )
            return TransportResponse(
                _csv_bytes(("2009-01-01 00:00:00", "1.0", "Preliminar")),
                200,
                _RETRIEVED_AT,
                "text/csv",
                stage_url,
                {},
            )

    transport = _SiblingAndTransient404Transport()
    store = StoreRoot(tmp_path / "store_2a")
    req = ObservationRequest(
        provider_id=ProviderId("co_ideam"),
        stations=(station,),
        products=(stage_prod, missing_q_prod),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2009, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2009, 1, 1)),
        ),
        known_series=(stage_known,),
    )
    res = drive(req, _CoIdeamStages(), provenance=_provenance(req), transport=transport, cache="reuse", store=store)
    assert res.canonical_rows["value"].to_list() == pytest.approx([0.01])
    assert any(i.code == "source.http_not_found" and i.severity == "warning" for i in res.issues)
    assert any(o.product_id == "caudal_h" and o.status is OutcomeStatus.FAILED for o in res.outcomes)

    # Now simulate a transient 404 (and then 503) on cache="refresh" for the already-cached stage series:
    # Option 2A retains the previously cached 0.01 m row instead of wiping it as NO_MATCH!
    req_stage_only = ObservationRequest(
        provider_id=ProviderId("co_ideam"),
        stations=(station,),
        products=(stage_prod,),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2009, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2009, 1, 1)),
        ),
        known_series=(stage_known,),
    )
    for transient_code in (404, 503):
        transport.stage_status = transient_code
        refreshed = drive(
            req_stage_only,
            _CoIdeamStages(),
            provenance=_provenance(req_stage_only),
            transport=transport,
            cache="refresh",
            store=store,
        )
        assert refreshed.canonical_rows["value"].to_list() == pytest.approx([0.01])
        assert any(o.status is OutcomeStatus.FAILED for o in refreshed.outcomes)


@pytest.mark.parametrize(
    ("product_id", "etiqueta", "bad_payload", "override_url"),
    [
        ("q_media_d", "Q_MEDIA_D", b"", None),
        ("q_media_d", "Q_MEDIA_D", b"\xff\xfe\x00", None),
        ("q_media_d", "Q_MEDIA_D", b"wrong,header,cols\n2020-01-01 00:00:00,1.0,Preliminar\n", None),
        ("q_media_d", "Q_MEDIA_D", b"fechaObservacion,valorObservado,nivelAprobacion\n2020-01-01 00:00:00,1.0\n", None),
        (
            "q_media_d",
            "Q_MEDIA_D",
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-01-01 00:00:00,1.0,Preliminar,extra\n",
            None,
        ),
        (
            "q_media_d",
            "Q_MEDIA_D",
            b"fechaObservacion,valorObservado,nivelAprobacion\n\n2020-01-01 00:00:00,1.0,Preliminar\n",
            None,
        ),
        (
            "q_media_d",
            "Q_MEDIA_D",
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-1-1 00:00:00,1.0,Preliminar\n",
            None,
        ),
        (
            "q_media_d",
            "Q_MEDIA_D",
            b"fechaObservacion,valorObservado,nivelAprobacion\n2023-02-29 00:00:00,1.0,Preliminar\n",
            None,
        ),
        (
            "q_media_d",
            "Q_MEDIA_D",
            (
                b"fechaObservacion,valorObservado,nivelAprobacion\n"
                b"2020-01-02 00:00:00,1.0,Preliminar\n"
                b"2020-01-01 00:00:00,1.0,Preliminar\n"
            ),
            None,
        ),
        (
            "q_media_m",
            "Q_MEDIA_M",
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-01-15 00:00:00,1.0,Preliminar\n",
            None,
        ),
        (
            "q_media_a",
            "Q_MEDIA_A",
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-06-01 00:00:00,1.0,Preliminar\n",
            None,
        ),
        (
            "q_media_d",
            "Q_MEDIA_D",
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-01-01 00:00:00,,Preliminar\n",
            None,
        ),
        (
            "q_media_d",
            "Q_MEDIA_D",
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-01-01 00:00:00,NaN,Preliminar\n",
            None,
        ),
        (
            "q_media_d",
            "Q_MEDIA_D",
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-01-01 00:00:00,inf,Preliminar\n",
            None,
        ),
        (
            "q_media_d",
            "Q_MEDIA_D",
            b"fechaObservacion,valorObservado,nivelAprobacion\n2020-01-01 00:00:00,1.0,Preliminar\n",
            "https://datos.ideam.gov.co/s3-estacionesideam/observaciones/historicos/csv/Q_MEDIA_D/0099999999-Q_MEDIA_D.csv",
        ),
    ],
)
def test_malformed_csv_payloads_produce_bounded_failed_outcome_and_preserve_siblings(
    product_id: str,
    etiqueta: str,
    bad_payload: bytes,
    override_url: str | None,
) -> None:
    cfg = config()
    win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2020, 12, 31)),
    )
    station = "0011017010"
    bad_url = override_url or s3_observation_csv_url(station, etiqueta)
    parsed_bad = parse(
        Payload(
            cfg.products[ProductId(product_id)].coordinates,
            ((station, ProductId(product_id)),),
            win,
            bad_payload,
            _origin(bad_url),
            (),
        ),
        cfg,
    )
    assert parsed_bad.rows.is_empty()
    assert parsed_bad.series == ()
    assert parsed_bad.inventories == ()
    assert len(parsed_bad.outcomes) == 1
    assert parsed_bad.outcomes[0].status is OutcomeStatus.FAILED
    assert len(parsed_bad.issues) == 1
    assert parsed_bad.issues[0].code == "source.unsupported_structure"
    assert parsed_bad.issues[0].severity == "error"

    # Multi-pair synthetic payload: malformed pair fails while valid sibling pair succeeds.
    if override_url is None and product_id != "nv_media_d":
        combined_ok = parse(
            Payload(
                SourceCoordinates(CoIdeamS3CsvCoordinates("NV_MEDIA_D", "nv_media_d")),
                ((station, ProductId("nv_media_d")),),
                win,
                _csv_bytes(("2020-01-01 00:00:00", "250.0", "Definitivo")),
                _origin(s3_observation_csv_url(station, "NV_MEDIA_D")),
                (),
            ),
            cfg,
        )
        assert combined_ok.rows.height == 1

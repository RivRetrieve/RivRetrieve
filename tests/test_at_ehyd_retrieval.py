"""Synthetic unit and assembled driver/store controls for Austria eHYD retrieval."""

from __future__ import annotations

import json
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
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.at_ehyd.config import (
    SHARED_ACQUISITION_PRODUCTS,
    AtEhydInfoCoordinates,
    AtEhydOwfCoordinates,
    AtEhydPegelCoordinates,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.at_ehyd.declaration import declaration
from rivretrieve._internal.providers.at_ehyd.fetch import fetch, resolve_messstellen_info_files
from rivretrieve._internal.providers.at_ehyd.parse import parse
from rivretrieve._internal.providers.at_ehyd.series import OWF_INTERVAL_RULE_TEXT, source_series
from rivretrieve._internal.providers.registration import LiveStages
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceState,
    InventoryCompleteness,
    OutcomeStatus,
    PhysicalPredicate,
    RestrictionKind,
    SeriesScope,
)
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)
from tests.test_internal_driver import _provenance

_RETRIEVED_AT = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _AtEhydStages:
    """Explicit stage bundle matching the live declaration contract."""

    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    shared_acquisition_products: tuple[frozenset[ProductId], ...] = SHARED_ACQUISITION_PRODUCTS
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _origin(url: str = "https://ehyd.gv.at/services/test", params: dict[str, str] | None = None) -> SourceCallOrigin:
    return SourceCallOrigin(
        url=url,
        request_parameters=params or {},
        status_code=200,
        retrieved_at=_RETRIEVED_AT,
        content_type="text/plain",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


def _info_json(station: str, files: list[tuple[int, str, str]]) -> bytes:
    return json.dumps(
        [
            {
                "caption": "Messstelle",
                "data": [
                    {
                        "info": {
                            "data": [
                                {"caption": "HZBNR", "text": int(station) if station.isdigit() else station},
                                {
                                    "tag": "dl_mstfiles",
                                    "data": {
                                        "fileData": [
                                            {
                                                "fileNr": file_nr,
                                                "fileName": file_name,
                                                "hzbnr": int(station) if station.isdigit() else station,
                                                "msttyp": msttyp,
                                            }
                                            for file_nr, file_name, msttyp in files
                                        ]
                                    },
                                },
                            ]
                        }
                    }
                ],
            }
        ]
    ).encode("utf-8")


def _owf_csv(
    *,
    station: str = "209486",
    unit: str = "[m³/s]",
    descriptor: str = "Abfluss,I,mit,T,1",
    exportzeitraum: str = "[01.01.2020 00:00,01.01.2024 00:00]",
    include_interval_rule: bool = True,
    lines: list[str],
) -> bytes:
    header = [
        "Stammdaten:",
        "Messstelle:                ;Testpegel",
        f"HZB-Nummer:                ;{station}",
        f"Einheit:                   ;{unit}",
        f"Exportzeitreihe:           ;{descriptor}",
    ]
    if include_interval_rule:
        header.append(f"Zeitreihenart:             ;{OWF_INTERVAL_RULE_TEXT}")
    header.extend(
        [
            f"Exportzeitraum:            ;{exportzeitraum}",
            "Werte:",
            *lines,
            "",
        ]
    )
    return "\r\n".join(header).encode("cp1252")


def test_declaration_wires_live_stages_and_config_declares_11_source_fixed_products() -> None:
    assert isinstance(declaration.observations, LiveStages)
    assert declaration.observations.stages.observation_source == "live"
    assert declaration.observations.stages.shared_acquisition_products == SHARED_ACQUISITION_PRODUCTS

    cfg = config()
    decls = window_declarations()
    assert len(cfg.products) == 11
    assert set(decls.products) == set(cfg.products)
    for product_id, decl in decls.products.items():
        assert decl.granularity == WindowGranularity("none"), product_id
        assert decl.rendering == WindowRenderingVocabulary.NONE
        assert decl.stop_convention == StopConvention.INCLUSIVE

    assert cfg.products[ProductId("owf_abfl_tagesmittel")].unit == Unit.M3_S
    assert cfg.products[ProductId("owf_wasserst_tagesmittel")].unit == Unit.CM
    assert cfg.products[ProductId("owf_wassertemp_monatsmittel")].unit == Unit.DEG_C
    assert cfg.products[ProductId("pegel_bgis_wasserstand")].unit == Unit.CM
    assert cfg.products[ProductId("pegel_longterm_abfluss")].unit == Unit.M3_S

    assert len(SHARED_ACQUISITION_PRODUCTS) == 3
    all_grouped = set().union(*SHARED_ACQUISITION_PRODUCTS)
    assert all_grouped == set(cfg.products)
    assert sum(len(group) for group in SHARED_ACQUISITION_PRODUCTS) == 11


def test_fetch_deduplicates_messstellen_info_resolves_shifted_filenr_and_isolates_sibling_failures() -> None:
    station = "204388"
    q_prod = ProductId("owf_abfl_tagesmittel")
    w_prod = ProductId("owf_wasserst_tagesmittel")
    wt_prod = ProductId("owf_wassertemp_monatsmittel")
    bgis_prod = ProductId("pegel_bgis_abfluss")

    info_bytes = _info_json(
        station,
        [
            (1, f"Stammdaten-{station}.pdf", "owf"),
            (2, f"W-Tagesmittel-{station}.csv", "owf"),
            (4, f"Q-Tagesmittel-{station}.csv", "owf"),
            (9, f"GW-Tagesmittel-{station}.csv", "gw"),
        ],
    )
    assert resolve_messstellen_info_files(info_bytes, station) == {
        w_prod: 2,
        q_prod: 4,
    }

    seen_requests: list[tuple[str, dict[str, str]]] = []

    class _Transport:
        def send(self, request: TransportRequest) -> TransportResponse | TransportFailure:
            params = dict(request.params or {})
            seen_requests.append((request.url, params))
            if request.url.endswith("/Messstellen/info"):
                return TransportResponse(info_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)
            if request.url.endswith("/MessstellenExtraData/owf") and params.get("file") == "4":
                csv = _owf_csv(station=station, lines=["01.01.2023 00:00:00; 12,5", "01.01.2024 00:00:00; Lücke"])
                return TransportResponse(csv, 200, _RETRIEVED_AT, "text/csv", request.url, params)
            if request.url.endswith("/MessstellenExtraData/owf") and params.get("file") == "2":
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=503,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            if request.url.endswith("/Diagram/pegelBgis"):
                bgis = json.dumps(
                    {
                        "hzbnr": int(station),
                        "parameter": "Abfluss",
                        "einheit": "m³/s",
                        "valCount": 1,
                        "categories": ["2026-10-31 10:00:00"],
                        "data": [14.2],
                    }
                ).encode("utf-8")
                return TransportResponse(bgis, 200, _RETRIEVED_AT, "application/json", request.url, params)
            raise AssertionError(f"Unexpected request: {request}")

    req = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=(station,),
        products=(q_prod, w_prod, wt_prod, bgis_prod),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2023, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 31, 23, 59, 59)),
        ),
    )
    result = drive(
        req, _AtEhydStages(), provenance=_provenance(req), transport=_Transport(), receipts=ReceiptMode.INCLUDE
    )

    info_calls = [item for item in seen_requests if item[0].endswith("/Messstellen/info")]
    assert info_calls == [("https://ehyd.gv.at/services/Messstellen/info", {"hzbnr": station})]
    owf_files = sorted(item[1]["file"] for item in seen_requests if item[0].endswith("/MessstellenExtraData/owf"))
    assert owf_files == ["2", "4"]

    q_rows = result.canonical_rows.filter(result.canonical_rows["product_id"] == str(q_prod))
    assert q_rows.select("time", "value").rows() == [(datetime(2023, 1, 1, 0, 0), 12.5)]
    bgis_rows = result.canonical_rows.filter(result.canonical_rows["product_id"] == str(bgis_prod))
    assert bgis_rows.select("value").rows() == [(14.2,)]

    by_product: dict[str, set[OutcomeStatus]] = {}
    for outcome in result.outcomes:
        by_product.setdefault(outcome.product_id, set()).add(outcome.status)
    assert OutcomeStatus.SUCCESS in by_product[str(q_prod)]
    assert OutcomeStatus.UNRESOLVED in by_product[str(q_prod)]
    assert by_product[str(w_prod)] == {OutcomeStatus.FAILED}
    assert by_product[str(wt_prod)] == {OutcomeStatus.NO_MATCH}
    assert OutcomeStatus.SUCCESS in by_product[str(bgis_prod)]


def test_owf_parser_handles_negative_stage_luecke_transitions_werfen_dec31_midnight_and_207340(tmp_path: Path) -> None:
    cfg = config()
    fetch_win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(1975, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 5)),
    )

    # 1. Negative stage in cm + multi-year sparse Lücke pair (modeled on 201806) + closing Lücke.
    w_csv = _owf_csv(
        station="201806",
        unit="[cm]",
        descriptor="Wasserstand,I,mit,T,1",
        exportzeitraum="[01.01.1976 00:00,01.01.2024 00:00]",
        lines=[
            "01.01.1976 01:00:00; -227",
            "02.01.1976 00:00:00; 0",
            "01.01.1977 00:00:00; Lücke",
            "01.01.2024 00:00:00; Lücke",
        ],
    )
    known = source_series("201806", "owf", "owf_wasserst_tagesmittel", units=("cm",))
    parsed_w = parse(
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_wasserst_tagesmittel", "W-Tagesmittel")),
            (("201806", ProductId("owf_wasserst_tagesmittel")),),
            fetch_win,
            w_csv,
            _origin(),
            (),
            known_series=(known,),
        ),
        cfg,
    )
    assert parsed_w.series[0].facts[0].facts_id == known.facts[0].facts_id
    assert parsed_w.rows.select("time", "value", "source_unit").rows() == [
        (datetime(1976, 1, 1, 1, 0), -227.0, "cm"),
        (datetime(1976, 1, 2, 0, 0), 0.0, "cm"),
    ]
    # Both Lücke markers are reported because 01.01.2024 follows an open 1977 gap rather than closing a numeric day.
    assert len(parsed_w.issues) == 1
    assert parsed_w.issues[0].code == "source.gap_marker"
    assert parsed_w.issues[0].severity == "info"
    assert parsed_w.issues[0].details is not None
    assert parsed_w.issues[0].details["count"] == 2
    assert parsed_w.issues[0].details["first_source_label"] == "01.01.1977 00:00:00"
    assert parsed_w.issues[0].details["last_source_label"] == "01.01.2024 00:00:00"

    # Assembled conversion converts -227 cm -> -2.27 m.
    class _StageTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if request.url.endswith("/Messstellen/info"):
                body = _info_json("201806", [(2, "W-Tagesmittel-201806.csv", "owf")])
                return TransportResponse(body, 200, _RETRIEVED_AT, "application/json", request.url, params)
            return TransportResponse(w_csv, 200, _RETRIEVED_AT, "text/csv", request.url, params)

    req_w = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=("201806",),
        products=(ProductId("owf_wasserst_tagesmittel"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(1976, 1, 1)),
            WindowEndpoint.from_datetime(datetime(1976, 1, 3)),
        ),
        known_series=(known,),
    )
    assembled_w = drive(req_w, _AtEhydStages(), provenance=_provenance(req_w), transport=_StageTransport())
    assert assembled_w.canonical_rows.select("value", "unit").rows() == [
        (pytest.approx(-2.27), "m"),
        (0.0, "m"),
    ]

    # 2. Trailing closing-boundary Lücke alone emits zero gap_marker issues; Werfen "; bis ;" + 00:15 header includes 00:00 row.
    werfen_csv = _owf_csv(
        station="204032",
        unit="m³/s",
        descriptor="(1,Abfluss,I,mit,T,1)",
        exportzeitraum="01.01.1995 00:15; bis ;01.01.2024 00:00",
        lines=[
            "01.01.1995 00:00:00; 8,40",
            "31.12.2023 00:00:00; 9,10",
            "01.01.2024 00:00:00; Lücke",
        ],
    )
    parsed_werfen = parse(
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_abfl_tagesmittel", "Q-Tagesmittel")),
            (("204032", ProductId("owf_abfl_tagesmittel")),),
            _make_fetch_window(
                WindowEndpoint.from_datetime(datetime(1995, 1, 1)),
                WindowEndpoint.from_datetime(datetime(2023, 12, 31, 23, 59, 59)),
            ),
            werfen_csv,
            _origin(),
            (),
        ),
        cfg,
    )
    assert parsed_werfen.issues == ()
    assert len(parsed_werfen.outcomes) == 1
    assert parsed_werfen.outcomes[0].status is OutcomeStatus.SUCCESS
    assert parsed_werfen.outcomes[0].window.start == datetime(1995, 1, 1, 0, 0)
    assert parsed_werfen.outcomes[0].window.end == datetime(2023, 12, 31, 23, 59, 59, 999999)

    # 3. Monthly extreme on Dec 31 24:00 stamped 01.01.2024 00:00:00 is retained inside covered_window.
    max_csv = _owf_csv(
        station="209486",
        unit="[m³/s]",
        descriptor="Abfluss,M,max,M,1",
        exportzeitraum="[01.01.2023 00:00,01.01.2024 00:00]",
        include_interval_rule=False,
        lines=["01.01.2024 00:00:00; 412,0"],
    )
    parsed_max = parse(
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_abfl_monatsmaxima", "Q-Monatsmaxima")),
            (("209486", ProductId("owf_abfl_monatsmaxima")),),
            _make_fetch_window(
                WindowEndpoint.from_datetime(datetime(2023, 1, 1)),
                WindowEndpoint.from_datetime(datetime(2024, 1, 1)),
            ),
            max_csv,
            _origin(),
            (),
        ),
        cfg,
    )
    assert parsed_max.outcomes[0].window.end == datetime(2024, 1, 1, 0, 0)
    assert parsed_max.rows.select("time", "value").rows() == [(datetime(2024, 1, 1, 0, 0), 412.0)]

    # 4. Station 207340 W-Monatsminima (T,1) keeps frequency and temporal_support not_established.
    daily_min_csv = _owf_csv(
        station="207340",
        unit="[cm]",
        descriptor="(Wasserstand,M,min,T,1)",
        exportzeitraum="[01.01.2023 00:00,01.01.2024 00:00]",
        include_interval_rule=False,
        lines=["01.01.2023 12:00:00; 45"],
    )
    parsed_207340 = parse(
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_wasserst_monatsminima", "W-Monatsminima")),
            (("207340", ProductId("owf_wasserst_monatsminima")),),
            _make_fetch_window(
                WindowEndpoint.from_datetime(datetime(2023, 1, 1)),
                WindowEndpoint.from_datetime(datetime(2023, 12, 31)),
            ),
            daily_min_csv,
            _origin(),
            (),
        ),
        cfg,
    )
    fact_207340 = parsed_207340.series[0].facts[0]
    assert fact_207340.statistic.value == "min"
    assert fact_207340.frequency.state is EvidenceState.NOT_ESTABLISHED
    assert fact_207340.temporal_support.state is EvidenceState.NOT_ESTABLISHED


@pytest.mark.parametrize("explicit_scope", [False, True])
def test_bounded_owf_cache_reuses_yearbook_span_keeps_2024_unresolved_and_preserves_held_rows_on_failed_refresh(
    tmp_path: Path, explicit_scope: bool
) -> None:
    station = "209486"
    product = ProductId("owf_abfl_tagesmittel")
    known = source_series(station, "owf", str(product), units=("m³/s",))
    scope = SeriesScope(restriction=RestrictionKind.EXPLICIT, series_ids=(known.series_id,)) if explicit_scope else None

    csv_bytes = _owf_csv(
        station=station,
        exportzeitraum="[01.01.2020 00:00,01.01.2024 00:00]",
        lines=[
            "01.01.2020 00:00:00; 10,0",
            "31.12.2023 00:00:00; 20,0",
            "01.01.2024 00:00:00; Lücke",
        ],
    )
    info_bytes = _info_json(station, [(5, f"Q-Tagesmittel-{station}.csv", "owf")])

    class _StatefulTransport:
        calls = 0
        fail_network = False

        def send(self, request: TransportRequest) -> TransportResponse | TransportFailure:
            self.calls += 1
            params = dict(request.params or {})
            if self.fail_network:
                raise TransportFailure(
                    request,
                    TransportFailureReason.HTTP_STATUS,
                    1,
                    status_code=502,
                    category=TransportFailureCategory.HTTP_STATUS,
                )
            if request.url.endswith("/Messstellen/info"):
                return TransportResponse(info_bytes, 200, _RETRIEVED_AT, "application/json", request.url, params)
            return TransportResponse(csv_bytes, 200, _RETRIEVED_AT, "text/csv", request.url, params)

    transport = _StatefulTransport()
    store = StoreRoot(tmp_path / f"store_{explicit_scope}")

    # 1. Request spanning 2020..2026: 2020..2023 is SUCCESS (interval), 2024..2026 is UNRESOLVED (never EMPTY).
    req_span = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=(station,),
        products=(product,),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 31)),
        ),
        known_series=(known,),
        scope=scope,
    )
    first = drive(
        req_span, _AtEhydStages(), provenance=_provenance(req_span), transport=transport, cache="reuse", store=store
    )
    assert transport.calls == 2
    assert first.canonical_rows["value"].to_list() == [10.0, 20.0]
    statuses = {item.status: item for item in first.outcomes}
    assert OutcomeStatus.EMPTY not in statuses
    assert statuses[OutcomeStatus.SUCCESS].coverage == "interval"
    assert statuses[OutcomeStatus.SUCCESS].window.end == datetime(2023, 12, 31, 23, 59, 59, 999999)
    assert statuses[OutcomeStatus.UNRESOLVED].window.start == datetime(2024, 1, 1, 0, 0)

    # 2. Follow-up historical query inside 2020..2023 reuses store offline with 0 HTTP calls and 0 UNRESOLVED outcomes.
    req_hist = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=(station,),
        products=(product,),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2023, 12, 31, 23, 59, 59)),
        ),
        known_series=(known,),
        scope=scope,
    )
    reused = drive(
        req_hist, _AtEhydStages(), provenance=_provenance(req_hist), transport=transport, cache="reuse", store=store
    )
    assert transport.calls == 2
    assert reused.canonical_rows["value"].to_list() == [10.0, 20.0]
    assert [item.status for item in reused.outcomes] == [OutcomeStatus.SUCCESS]

    # 3. Query extending into 2024 is not covered -> hits network; if network fails, held 2020..2023 rows survive.
    transport.fail_network = True
    req_2024 = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=(station,),
        products=(product,),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2024, 6, 30)),
        ),
        known_series=(known,),
        scope=scope,
    )
    degraded = drive(
        req_2024, _AtEhydStages(), provenance=_provenance(req_2024), transport=transport, cache="reuse", store=store
    )
    assert transport.calls == 3
    assert degraded.canonical_rows["value"].to_list() == [10.0, 20.0]
    assert any(item.status is OutcomeStatus.FAILED for item in degraded.outcomes)


def test_pegel_bgis_and_longterm_preserve_nulls_exclude_non_series_fields_and_accumulate_rolling_snapshots(
    tmp_path: Path,
) -> None:
    station = "209486"
    bgis_prod = ProductId("pegel_bgis_abfluss")
    longterm_prod = ProductId("pegel_longterm_abfluss")

    snap_1 = {
        "hzbnr": 209486,
        "parameter": "Abfluss",
        "einheit": "m³/s",
        "wert": 999.0,
        "zp": "31.10.2026 10:00",
        "niedrigwasser": 5.0,
        "mittelwasser": 25.0,
        "erhmittelwasser": 50.0,
        "hochwasser1": 120.0,
        "hochwasser2": 180.0,
        "hochwasser3": 240.0,
        "valCount": 3,
        "categories": [
            "2026-10-30 00:00:00",
            "2026-10-30 00:15:00",
            "2026-10-30 00:30:00",
        ],
        "data": [11.0, None, 12.0],
    }
    snap_2 = {
        **snap_1,
        "categories": [
            "2026-10-30 00:15:00",
            "2026-10-30 00:30:00",
            "2026-10-30 00:45:00",
        ],
        "data": [None, 12.5, 13.0],
    }
    longterm_doc = {
        "parameter": "Abfluss",
        "einheit": "m³/s",
        "points_in_time": ["2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"],
        "current_value": [10.5, None, 11.5, None],
        "last_year_value": [99.0, 99.0, 99.0, 99.0],
        "min_data": [1.0, 1.0, 1.0, 1.0],
        "max_data": [80.0, 80.0, 80.0, 80.0],
        "mit_data": [20.0, 20.0, 20.0, 20.0],
        "p5_data": [4.0, 4.0, 4.0, 4.0],
        "p95_data": [50.0, 50.0, 50.0, 50.0],
    }

    class _RollingTransport:
        second_snapshot = False

        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if request.url.endswith("/Diagram/pegelBgis"):
                doc = snap_2 if self.second_snapshot else snap_1
                return TransportResponse(
                    json.dumps(doc).encode("utf-8"),
                    200,
                    datetime(2026, 10, 31, 22 if self.second_snapshot else 10, 0, tzinfo=UTC),
                    "application/json",
                    request.url,
                    params,
                )
            return TransportResponse(
                json.dumps(longterm_doc).encode("utf-8"),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                params,
            )

    transport = _RollingTransport()
    store = StoreRoot(tmp_path / "rolling_store")

    # Historical 2020 request against rolling pegelBgis must report UNRESOLVED, never EMPTY.
    req_2020 = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=(station,),
        products=(bgis_prod,),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2020, 1, 2)),
        ),
    )
    res_2020 = drive(
        req_2020, _AtEhydStages(), provenance=_provenance(req_2020), transport=transport, cache="reuse", store=store
    )
    assert res_2020.canonical_rows.is_empty()
    assert [item.status for item in res_2020.outcomes] == [OutcomeStatus.UNRESOLVED]

    # Rolling accumulation across two snapshots retains aged-out 00:00 point, preserves interior null, and updates 00:30.
    req_live = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=(station,),
        products=(bgis_prod, longterm_prod),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 10, 29, 0, 0)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 31, 12, 0)),
        ),
    )
    first_live = drive(
        req_live, _AtEhydStages(), provenance=_provenance(req_live), transport=transport, cache="reuse", store=store
    )
    bgis_first = first_live.canonical_rows.filter(first_live.canonical_rows["product_id"] == str(bgis_prod)).sort(
        "time"
    )
    assert bgis_first["value"].to_list() == [11.0, None, 12.0]
    assert bgis_first["time_zone"].to_list() == ["+01:00", "+01:00", "+01:00"]

    lt_rows = first_live.canonical_rows.filter(first_live.canonical_rows["product_id"] == str(longterm_prod)).sort(
        "time"
    )
    # Preserves interior null on 2026-10-30, trims trailing future null on 2026-11-01, excludes last_year_value=99.0.
    assert lt_rows.select("time", "value", "time_zone").rows() == [
        (datetime(2026, 10, 29, 0, 0), 10.5, "unknown"),
        (datetime(2026, 10, 30, 0, 0), None, "unknown"),
        (datetime(2026, 10, 31, 0, 0), 11.5, "unknown"),
    ]
    lt_series = next(item for item in first_live.source_series if item.product_id == str(longterm_prod))
    assert lt_series.facts[0].clipping_axis is ClippingAxis.CALENDAR_DATE
    assert lt_series.facts[0].statistic.state is EvidenceState.NOT_ESTABLISHED

    # Predicate filter on statistic="mean" withholds pegelLongterm rows as UNRESOLVED because statistic is not_established.
    req_pred = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=(station,),
        products=(longterm_prod,),
        window=req_live.window,
        scope=SeriesScope(
            provider_ids=("at_ehyd",),
            station_ids=(station,),
            product_ids=(str(longterm_prod),),
            predicates=(PhysicalPredicate(field="statistic", value="mean"),),
        ),
    )
    pred_result = drive(req_pred, _AtEhydStages(), provenance=_provenance(req_pred), transport=transport)
    assert pred_result.canonical_rows.is_empty()
    assert [item.status for item in pred_result.outcomes] == [OutcomeStatus.UNRESOLVED]

    transport.second_snapshot = True
    second_live = drive(
        req_live, _AtEhydStages(), provenance=_provenance(req_live), transport=transport, cache="reuse", store=store
    )
    bgis_second = second_live.canonical_rows.filter(second_live.canonical_rows["product_id"] == str(bgis_prod)).sort(
        "time"
    )
    assert bgis_second["value"].to_list() == [11.0, None, 12.5, 13.0]


def test_outcome_boundaries_distinguish_no_match_unresolved_unsupported_and_failed() -> None:
    cfg = config()
    win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 10, 1)),
        WindowEndpoint.from_datetime(datetime(2026, 10, 31)),
    )

    # 1. NO_MATCH: Messstellen/info [[]] on telemetry-only station; Pegel Aktuell opposite parameter.
    no_match_info = parse(
        Payload(
            SourceCoordinates(AtEhydInfoCoordinates()),
            (("200675", ProductId("owf_abfl_tagesmittel")),),
            win,
            b"[[]]",
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in no_match_info.outcomes] == [OutcomeStatus.NO_MATCH]
    assert no_match_info.inventories[0].completeness is InventoryCompleteness.COMPLETE

    opposite_param = parse(
        Payload(
            SourceCoordinates(AtEhydPegelCoordinates("pegel_bgis", "Abfluss")),
            (("206557", ProductId("pegel_bgis_abfluss")),),
            win,
            json.dumps({"hzbnr": 206557, "parameter": "Wasserstand", "einheit": "cm", "valCount": 0}).encode("utf-8"),
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in opposite_param.outcomes] == [OutcomeStatus.NO_MATCH]

    # 2. UNRESOLVED: 0-byte pegelBgis, valCount=0 pegelBgis (209288), all-null pegelLongterm, open Invalid; Lücke owf (208058).
    empty_bgis_200 = parse(
        Payload(
            SourceCoordinates(AtEhydPegelCoordinates("pegel_bgis", "Abfluss")),
            (("215541", ProductId("pegel_bgis_abfluss")),),
            win,
            b"",
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in empty_bgis_200.outcomes] == [OutcomeStatus.UNRESOLVED]
    assert empty_bgis_200.outcomes[0].series_id is None

    valcount_zero = parse(
        Payload(
            SourceCoordinates(AtEhydPegelCoordinates("pegel_bgis", "Wasserstand")),
            (("209288", ProductId("pegel_bgis_wasserstand")),),
            win,
            json.dumps(
                {
                    "hzbnr": 209288,
                    "parameter": "Wasserstand",
                    "einheit": "cm",
                    "valCount": 0,
                    "categories": None,
                    "data": None,
                }
            ).encode("utf-8"),
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in valcount_zero.outcomes] == [OutcomeStatus.UNRESOLVED]
    assert valcount_zero.outcomes[0].series_id is not None

    all_null_lt = parse(
        Payload(
            SourceCoordinates(AtEhydPegelCoordinates("pegel_longterm", "Abfluss")),
            (("999999", ProductId("pegel_longterm_abfluss")),),
            win,
            json.dumps(
                {
                    "parameter": "Abfluss",
                    "einheit": "m³/s",
                    "points_in_time": ["2026-01-01", "2026-01-02"],
                    "current_value": [None, None],
                }
            ).encode("utf-8"),
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in all_null_lt.outcomes] == [OutcomeStatus.UNRESOLVED]

    empty_skeleton_lt = parse(
        Payload(
            SourceCoordinates(AtEhydPegelCoordinates("pegel_longterm", "Abfluss")),
            (("213801", ProductId("pegel_longterm_abfluss")),),
            win,
            json.dumps(
                {
                    "points_in_time": [],
                    "current_value": [],
                    "min_data": [],
                    "min_year": [],
                    "max_data": [],
                    "max_year": [],
                    "mit_data": [],
                    "p5_data": [],
                    "p95_data": [],
                    "last_year_value": [],
                }
            ).encode("utf-8"),
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in empty_skeleton_lt.outcomes] == [OutcomeStatus.UNRESOLVED]
    assert empty_skeleton_lt.outcomes[0].series_id is None

    open_invalid_owf = parse(
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_wassertemp_monatsmittel", "WT-Monatsmittel")),
            (("208058", ProductId("owf_wassertemp_monatsmittel")),),
            win,
            _owf_csv(
                station="208058",
                unit="[°C]",
                descriptor="WTemperatur,I,mit,M,1",
                exportzeitraum="[Invalid,+-Infty]",
                lines=["Invalid; Lücke"],
            ),
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in open_invalid_owf.outcomes] == [OutcomeStatus.UNRESOLVED]

    # Finite Exportzeitraum with Invalid; Lücke establishes bounded EMPTY over its published window.
    finite_empty_owf = parse(
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_wassertemp_monatsmittel", "WT-Monatsmittel")),
            (("208058", ProductId("owf_wassertemp_monatsmittel")),),
            _make_fetch_window(
                WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
                WindowEndpoint.from_datetime(datetime(2023, 12, 31)),
            ),
            _owf_csv(
                station="208058",
                unit="[°C]",
                descriptor="WTemperatur,I,mit,M,1",
                exportzeitraum="[01.01.2020 00:00,01.01.2024 00:00]",
                lines=["Invalid; Lücke"],
            ),
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in finite_empty_owf.outcomes] == [OutcomeStatus.EMPTY]

    # 3. UNSUPPORTED: cleared owf unit [] (station 203539 W-Monatsminima); cleared pegelLongterm ""; "m ü.A" stage.
    cleared_owf = parse(
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_wasserst_monatsminima", "W-Monatsminima")),
            (("203539", ProductId("owf_wasserst_monatsminima")),),
            win,
            _owf_csv(
                station="203539",
                unit="[]",
                descriptor="Wasserstand,M,min,M,1",
                exportzeitraum="[01.01.1997 00:00,+-Infty]",
                include_interval_rule=False,
                lines=["01.01.2020 00:00:00; 10"],
            ),
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in cleared_owf.outcomes] == [OutcomeStatus.UNSUPPORTED]

    cleared_lt = parse(
        Payload(
            SourceCoordinates(AtEhydPegelCoordinates("pegel_longterm", "Abfluss")),
            (("212167", ProductId("pegel_longterm_abfluss")),),
            win,
            json.dumps(
                {
                    "parameter": "Abfluss",
                    "einheit": "",
                    "points_in_time": ["2026-01-01"],
                    "current_value": [None],
                }
            ).encode("utf-8"),
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in cleared_lt.outcomes] == [OutcomeStatus.UNSUPPORTED]

    mua_bgis = parse(
        Payload(
            SourceCoordinates(AtEhydPegelCoordinates("pegel_bgis", "Wasserstand")),
            (("210120", ProductId("pegel_bgis_wasserstand")),),
            win,
            json.dumps(
                {
                    "hzbnr": 210120,
                    "parameter": "Wasserstand",
                    "einheit": "m ü.A",
                    "valCount": 1,
                    "categories": ["2026-10-31 10:00:00"],
                    "data": [402.15],
                }
            ).encode("utf-8"),
            _origin(),
            (),
        ),
        cfg,
    )
    assert [item.status for item in mua_bgis.outcomes] == [OutcomeStatus.UNSUPPORTED]

    # 4. FAILED: 0-byte owf, HZB-Nummer mismatch, pegelBgis hzbnr mismatch, Exportzeitreihe mismatch, malformed Lücke timestamp.
    failed_cases = [
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_abfl_tagesmittel", "Q-Tagesmittel")),
            (("209486", ProductId("owf_abfl_tagesmittel")),),
            win,
            b"",
            _origin(),
            (),
        ),
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_abfl_tagesmittel", "Q-Tagesmittel")),
            (("209486", ProductId("owf_abfl_tagesmittel")),),
            win,
            _owf_csv(station="999999", lines=["01.01.2023 00:00:00; 1,0"]),
            _origin(),
            (),
        ),
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_abfl_tagesmittel", "Q-Tagesmittel")),
            (("209486", ProductId("owf_abfl_tagesmittel")),),
            win,
            _owf_csv(station="209486", descriptor="Wasserstand,I,mit,T,1", lines=["01.01.2023 00:00:00; 1,0"]),
            _origin(),
            (),
        ),
        Payload(
            SourceCoordinates(AtEhydOwfCoordinates("owf_abfl_tagesmittel", "Q-Tagesmittel")),
            (("209486", ProductId("owf_abfl_tagesmittel")),),
            win,
            _owf_csv(station="209486", lines=["not-a-timestamp; Lücke"]),
            _origin(),
            (),
        ),
        Payload(
            SourceCoordinates(AtEhydPegelCoordinates("pegel_bgis", "Abfluss")),
            (("209486", ProductId("pegel_bgis_abfluss")),),
            win,
            json.dumps(
                {
                    "hzbnr": 111111,
                    "parameter": "Abfluss",
                    "einheit": "m³/s",
                    "valCount": 1,
                    "categories": ["2026-10-31 10:00:00"],
                    "data": [10.0],
                }
            ).encode("utf-8"),
            _origin(),
            (),
        ),
    ]
    for bad_payload in failed_cases:
        failed_parsed = parse(bad_payload, cfg)
        assert [item.status for item in failed_parsed.outcomes] == [OutcomeStatus.FAILED]
        assert failed_parsed.rows.is_empty()


def test_shared_pegel_endpoint_and_corrupt_messstellen_info_isolate_per_product_outcomes() -> None:
    station = "209486"
    q_owf = ProductId("owf_abfl_tagesmittel")
    bgis_q = ProductId("pegel_bgis_abfluss")
    bgis_w = ProductId("pegel_bgis_wasserstand")
    lt_q = ProductId("pegel_longterm_abfluss")
    lt_w = ProductId("pegel_longterm_wasserstand")

    seen_urls: list[str] = []

    class _MixedTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            seen_urls.append(request.url)
            params = dict(request.params or {})
            if request.url.endswith("/Messstellen/info"):
                return TransportResponse(b"{corrupt-info", 200, _RETRIEVED_AT, "application/json", request.url, params)
            if request.url.endswith("/Diagram/pegelBgis"):
                doc = {
                    "hzbnr": 209486,
                    "parameter": "Abfluss",
                    "einheit": "m³/s",
                    "valCount": 1,
                    "categories": ["2026-10-31 10:00:00"],
                    "data": [15.5],
                }
                return TransportResponse(
                    json.dumps(doc).encode("utf-8"), 200, _RETRIEVED_AT, "application/json", request.url, params
                )
            doc_lt = {
                "parameter": "Wasserstand",
                "einheit": "cm",
                "points_in_time": ["2026-10-31"],
                "current_value": [125],
            }
            return TransportResponse(
                json.dumps(doc_lt).encode("utf-8"), 200, _RETRIEVED_AT, "application/json", request.url, params
            )

    req = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=(station,),
        products=(q_owf, bgis_q, bgis_w, lt_q, lt_w),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 10, 30)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 31, 23, 59, 59)),
        ),
    )
    res = drive(req, _AtEhydStages(), provenance=_provenance(req), transport=_MixedTransport())
    # Exactly 1 Messstellen/info, 1 pegelBgis, and 1 pegelLongterm request despite 2 bgis + 2 longterm products.
    assert sorted(seen_urls) == [
        "https://ehyd.gv.at/services/Diagram/pegelBgis",
        "https://ehyd.gv.at/services/Diagram/pegelLongterm",
        "https://ehyd.gv.at/services/Messstellen/info",
    ]
    by_prod: dict[str, set[OutcomeStatus]] = {}
    for item in res.outcomes:
        by_prod.setdefault(item.product_id, set()).add(item.status)
    assert by_prod[str(q_owf)] == {OutcomeStatus.FAILED}
    assert OutcomeStatus.SUCCESS in by_prod[str(bgis_q)]
    assert by_prod[str(bgis_w)] == {OutcomeStatus.NO_MATCH}
    assert by_prod[str(lt_q)] == {OutcomeStatus.NO_MATCH}
    assert OutcomeStatus.SUCCESS in by_prod[str(lt_w)]
    lt_w_rows = res.canonical_rows.filter(res.canonical_rows["product_id"] == str(lt_w))
    assert lt_w_rows.select("value", "unit").rows() == [(pytest.approx(1.25), "m")]

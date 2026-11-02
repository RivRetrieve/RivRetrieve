"""Recorded replay of retained original Austria eHYD HTTP captures across all 11 products."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.at_ehyd.config import (
    SHARED_ACQUISITION_PRODUCTS,
    AtEhydInfoCoordinates,
    config,
    window_declarations,
)
from rivretrieve._internal.providers.at_ehyd.fetch import fetch, resolve_messstellen_info_files
from rivretrieve._internal.providers.at_ehyd.parse import parse
from rivretrieve._internal.source_series import InventoryCompleteness, OutcomeStatus
from rivretrieve._internal.store import StoreRoot
from rivretrieve._internal.transport import TransportRequest, TransportResponse
from tests.test_internal_driver import _provenance

_SCOPE = "maintenance/observations/at_ehyd/retrieval"


@dataclass(frozen=True)
class _AtEhydStages:
    config: ProviderConfig = config()
    window_declarations: ProductWindowDeclarations = window_declarations()
    shared_acquisition_products: tuple[frozenset[ProductId], ...] = SHARED_ACQUISITION_PRODUCTS
    fetch = staticmethod(fetch)
    parse = staticmethod(parse)


def _capture(root: Path, group: str, name: str) -> tuple[bytes, dict[str, object]]:
    base = root / _SCOPE / group / name
    return base.with_suffix(".body").read_bytes(), json.loads(base.with_suffix(".receipt.json").read_text())


def _response_from_capture(root: Path, group: str, name: str) -> TransportResponse:
    body, receipt = _capture(root, group, name)
    url = str(receipt["url"])
    parsed = urlsplit(url)
    params = {key: vals[0] for key, vals in parse_qs(parsed.query, keep_blank_values=True).items()}
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    acquired = datetime.fromisoformat(str(receipt["acquired_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=body,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=acquired,
        content_type=str(content_type) if content_type is not None else None,
        url=f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
        request_parameters=params,
    )


def _origin_from_receipt(receipt: dict[str, object]) -> SourceCallOrigin:
    url = str(receipt["url"])
    parsed = urlsplit(url)
    params = {key: vals[0] for key, vals in parse_qs(parsed.query, keep_blank_values=True).items()}
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    acquired = datetime.fromisoformat(str(receipt["acquired_at"]).replace("Z", "+00:00"))
    return SourceCallOrigin(
        url=f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
        request_parameters=params,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=acquired,
        content_type=str(content_type) if content_type is not None else UnknownOriginFact(),
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


@pytest.mark.recorded(_SCOPE)
def test_recorded_owf_routes_and_messstellen_info_replay_with_bounded_cache_reuse(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    cfg = config()

    # 1. Verify Messstellen/info resolution on 209486, 204388 (station-verified HZBNR), and 200675 ([[]] NO_MATCH).
    info_209486, _ = _capture(retained_evidence_root, "access", "messstellen-info-209486")
    expected_six_owf = {
        ProductId("owf_wasserst_tagesmittel"): 2,
        ProductId("owf_wasserst_monatsminima"): 3,
        ProductId("owf_wasserst_monatsmaxima"): 4,
        ProductId("owf_abfl_tagesmittel"): 5,
        ProductId("owf_abfl_monatsminima"): 6,
        ProductId("owf_abfl_monatsmaxima"): 7,
    }
    assert resolve_messstellen_info_files(info_209486, "209486") == expected_six_owf

    info_204388, _ = _capture(retained_evidence_root, "catalogue", "messstellen-info-204388")
    assert resolve_messstellen_info_files(info_204388, "204388") == expected_six_owf
    with pytest.raises(ValueError, match="204388"):
        resolve_messstellen_info_files(info_204388, "209486")

    info_200675, rcpt_200675 = _capture(retained_evidence_root, "catalogue", "messstellen-info-200675")
    assert resolve_messstellen_info_files(info_200675, "200675") == {}
    parsed_200675 = parse(
        Payload(
            SourceCoordinates(AtEhydInfoCoordinates()),
            (("200675", ProductId("owf_abfl_tagesmittel")),),
            _make_fetch_window(
                WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
                WindowEndpoint.from_datetime(datetime(2023, 12, 31)),
            ),
            info_200675,
            _origin_from_receipt(rcpt_200675),
            (),
        ),
        cfg,
    )
    assert [item.status for item in parsed_200675.outcomes] == [OutcomeStatus.NO_MATCH]
    assert parsed_200675.inventories[0].completeness is InventoryCompleteness.COMPLETE

    # 2. Replay all 6 owf series on 209486 (+ NO_MATCH on absent WT-Monatsmittel) through assembled drive + cache="reuse".
    file_to_capture = {
        "2": "owf-209486-file2-w-tagesmittel",
        "3": "owf-209486-file3-w-monatsminima",
        "4": "owf-209486-file4-w-monatsmaxima",
        "5": "owf-209486-file5-q-tagesmittel",
        "6": "owf-209486-file6-q-monatsminima",
        "7": "owf-209486-file7-q-monatsmaxima",
    }

    class _RecordedOwfTransport:
        calls = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            params = dict(request.params or {})
            if request.url.endswith("/Messstellen/info"):
                assert params == {"hzbnr": "209486"}
                return _response_from_capture(retained_evidence_root, "access", "messstellen-info-209486")
            assert request.url.endswith("/MessstellenExtraData/owf")
            assert params["id"] == "209486"
            return _response_from_capture(retained_evidence_root, "access", file_to_capture[str(params["file"])])

    owf_products = (
        ProductId("owf_wasserst_tagesmittel"),
        ProductId("owf_wasserst_monatsminima"),
        ProductId("owf_wasserst_monatsmaxima"),
        ProductId("owf_abfl_tagesmittel"),
        ProductId("owf_abfl_monatsminima"),
        ProductId("owf_abfl_monatsmaxima"),
        ProductId("owf_wassertemp_monatsmittel"),
    )
    transport = _RecordedOwfTransport()
    store = StoreRoot(tmp_path / "recorded_owf_store")

    req_span = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=("209486",),
        products=owf_products,
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2026, 10, 31)),
        ),
    )
    first = drive(
        req_span, _AtEhydStages(), provenance=_provenance(req_span), transport=transport, cache="reuse", store=store
    )
    # 1 deduplicated Messstellen/info call + 6 owf CSV calls.
    assert transport.calls == 7
    present_products = set(first.canonical_rows["product_id"].unique().to_list())
    assert present_products == {str(p) for p in owf_products if p != ProductId("owf_wassertemp_monatsmittel")}
    # Stage cm converted to m; discharge remains m3/s.
    stage_units = set(
        first.canonical_rows.filter(first.canonical_rows["product_id"] == "owf_wasserst_tagesmittel")["unit"].to_list()
    )
    assert stage_units == {"m"}
    # Every present owf series marks 2020..2023 SUCCESS (interval) and 2024..2026 UNRESOLVED (never EMPTY).
    for prod in owf_products:
        prod_outcomes = [item for item in first.outcomes if item.product_id == str(prod)]
        if prod == ProductId("owf_wassertemp_monatsmittel"):
            assert [item.status for item in prod_outcomes] == [OutcomeStatus.NO_MATCH]
        else:
            assert {item.status for item in prod_outcomes} == {OutcomeStatus.SUCCESS, OutcomeStatus.UNRESOLVED}

    # Historical query inside 2020..2023 hits local cache with 0 network calls!
    req_hist = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=("209486",),
        products=(ProductId("owf_abfl_tagesmittel"), ProductId("owf_wasserst_tagesmittel")),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
            WindowEndpoint.from_datetime(datetime(2023, 12, 31, 23, 59, 59)),
        ),
    )
    reused = drive(
        req_hist, _AtEhydStages(), provenance=_provenance(req_hist), transport=transport, cache="reuse", store=store
    )
    assert transport.calls == 7
    assert not reused.canonical_rows.is_empty()
    assert all(item.status is OutcomeStatus.SUCCESS for item in reused.outcomes)

    # 3. Replay 7th owf product (WT-Monatsmittel on 201350) and 0-byte invalid file=99 (FAILED).
    wt_body, wt_rcpt = _capture(retained_evidence_root, "access", "owf-201350-file8-wt-monatsmittel")
    wt_parsed = parse(
        Payload(
            cfg.products[ProductId("owf_wassertemp_monatsmittel")].coordinates,
            (("201350", ProductId("owf_wassertemp_monatsmittel")),),
            _make_fetch_window(
                WindowEndpoint.from_datetime(datetime(2015, 1, 1)),
                WindowEndpoint.from_datetime(datetime(2023, 12, 31)),
            ),
            wt_body,
            _origin_from_receipt(wt_rcpt),
            (),
        ),
        cfg,
    )
    assert not wt_parsed.rows.is_empty()
    assert set(wt_parsed.rows["source_unit"].to_list()) == {"°C"}
    assert wt_parsed.outcomes[0].status is OutcomeStatus.SUCCESS

    empty_owf_body, empty_owf_rcpt = _capture(retained_evidence_root, "access", "owf-209486-invalid-file99")
    assert empty_owf_body == b""
    failed_owf = parse(
        Payload(
            cfg.products[ProductId("owf_abfl_tagesmittel")].coordinates,
            (("209486", ProductId("owf_abfl_tagesmittel")),),
            _make_fetch_window(
                WindowEndpoint.from_datetime(datetime(2020, 1, 1)),
                WindowEndpoint.from_datetime(datetime(2023, 12, 31)),
            ),
            empty_owf_body,
            _origin_from_receipt(empty_owf_rcpt),
            (),
        ),
        cfg,
    )
    assert [item.status for item in failed_owf.outcomes] == [OutcomeStatus.FAILED]


@pytest.mark.recorded(_SCOPE)
def test_recorded_pegel_aktuell_rolling_accumulation_null_preservation_and_outcome_boundaries(
    retained_evidence_root: Path, tmp_path: Path
) -> None:
    cfg = config()
    win = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 9, 25)),
        WindowEndpoint.from_datetime(datetime(2026, 11, 1)),
    )

    # 1. Two-snapshot rolling accumulation on real 209486 captures (797 morning + 785 evening -> 801 unique rows).
    class _TwoSnapshotBgisTransport:
        evening = False

        def send(self, request: TransportRequest) -> TransportResponse:
            group = "catalogue" if self.evening else "access"
            return _response_from_capture(retained_evidence_root, group, "pegel-bgis-209486")

    rolling_transport = _TwoSnapshotBgisTransport()
    rolling_store = StoreRoot(tmp_path / "recorded_bgis_store")
    req_bgis = ObservationRequest(
        provider_id=ProviderId("at_ehyd"),
        stations=("209486",),
        products=(ProductId("pegel_bgis_abfluss"),),
        window=RequestedWindow(
            WindowEndpoint.from_datetime(datetime(2026, 9, 25)),
            WindowEndpoint.from_datetime(datetime(2026, 11, 2)),
        ),
    )
    morning_res = drive(
        req_bgis,
        _AtEhydStages(),
        provenance=_provenance(req_bgis),
        transport=rolling_transport,
        cache="reuse",
        store=rolling_store,
    )
    assert morning_res.canonical_rows.height == 797

    rolling_transport.evening = True
    evening_res = drive(
        req_bgis,
        _AtEhydStages(),
        provenance=_provenance(req_bgis),
        transport=rolling_transport,
        cache="reuse",
        store=rolling_store,
    )
    assert evening_res.canonical_rows.height == 801

    # 2. Stage conversion (cm -> m) on pegel-bgis-206557-stage and pegel-longterm-206557, plus Abfluss on pegel-longterm-209486.
    for group, name, station, prod, exp_unit in (
        ("access", "pegel-bgis-206557-stage", "206557", ProductId("pegel_bgis_wasserstand"), "cm"),
        ("access", "pegel-longterm-209486", "209486", ProductId("pegel_longterm_abfluss"), "m³/s"),
        ("catalogue", "pegel-longterm-206557", "206557", ProductId("pegel_longterm_wasserstand"), "cm"),
    ):
        body, rcpt = _capture(retained_evidence_root, group, name)
        parsed = parse(
            Payload(
                cfg.products[prod].coordinates,
                ((station, prod),),
                _make_fetch_window(
                    WindowEndpoint.from_datetime(datetime(2026, 1, 1)),
                    WindowEndpoint.from_datetime(datetime(2026, 12, 31)),
                ),
                body,
                _origin_from_receipt(rcpt),
                (),
            ),
            cfg,
        )
        assert not parsed.rows.is_empty()
        assert set(parsed.rows["source_unit"].to_list()) == {exp_unit}
        assert any(o.status is OutcomeStatus.SUCCESS and o.coverage == "observations" for o in parsed.outcomes)

    # 3. Interior null preservation and future-tail trimming on 200592 (pegelBgis) and 200345 (pegelLongterm).
    bgis_200592_body, bgis_200592_rcpt = _capture(retained_evidence_root, "catalogue", "pegel-bgis-200592")
    parsed_200592 = parse(
        Payload(
            cfg.products[ProductId("pegel_bgis_abfluss")].coordinates,
            (("200592", ProductId("pegel_bgis_abfluss")),),
            win,
            bgis_200592_body,
            _origin_from_receipt(bgis_200592_rcpt),
            (),
        ),
        cfg,
    )
    assert parsed_200592.rows["value"].null_count() > 0

    lt_200345_body, lt_200345_rcpt = _capture(retained_evidence_root, "catalogue", "pegel-longterm-200345")
    parsed_200345 = parse(
        Payload(
            cfg.products[ProductId("pegel_longterm_abfluss")].coordinates,
            (("200345", ProductId("pegel_longterm_abfluss")),),
            _make_fetch_window(
                WindowEndpoint.from_datetime(datetime(2026, 1, 1)),
                WindowEndpoint.from_datetime(datetime(2026, 12, 31)),
            ),
            lt_200345_body,
            _origin_from_receipt(lt_200345_rcpt),
            (),
        ),
        cfg,
    )
    assert parsed_200345.rows.height < 365
    assert parsed_200345.rows["value"].null_count() == 68
    assert parsed_200345.rows["value"][-1] is not None

    # 4. Real-capture UNRESOLVED and UNSUPPORTED boundaries.
    unresolved_captures = [
        ("access", "pegel-bgis-215541-empty", "215541", ProductId("pegel_bgis_abfluss")),
        ("catalogue", "pegel-bgis-212167", "212167", ProductId("pegel_bgis_abfluss")),
        ("catalogue", "pegel-bgis-209288", "209288", ProductId("pegel_bgis_abfluss")),
        ("catalogue", "pegel-longterm-212167", "212167", ProductId("pegel_longterm_abfluss")),
        ("catalogue", "pegel-longterm-213801", "213801", ProductId("pegel_longterm_abfluss")),
    ]
    for group, name, station, prod in unresolved_captures:
        body, rcpt = _capture(retained_evidence_root, group, name)
        parsed = parse(
            Payload(cfg.products[prod].coordinates, ((station, prod),), win, body, _origin_from_receipt(rcpt), ()),
            cfg,
        )
        assert [item.status for item in parsed.outcomes] == [OutcomeStatus.UNRESOLVED], name
        assert parsed.rows.is_empty()

    for group, name, prod in (
        ("catalogue", "pegel-bgis-210120", ProductId("pegel_bgis_wasserstand")),
        ("catalogue", "pegel-longterm-210120", ProductId("pegel_longterm_wasserstand")),
    ):
        body, rcpt = _capture(retained_evidence_root, group, name)
        parsed = parse(
            Payload(cfg.products[prod].coordinates, (("210120", prod),), win, body, _origin_from_receipt(rcpt), ()),
            cfg,
        )
        assert [item.status for item in parsed.outcomes] == [OutcomeStatus.UNSUPPORTED], name
        assert parsed.rows.is_empty()

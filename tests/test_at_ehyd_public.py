"""Public Austria eHYD discovery, retrieval, route isolation, and cache controls."""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from typing import NoReturn

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.discovery import EmptySelectionError
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.providers.at_ehyd.series import OWF_INTERVAL_RULE_TEXT
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_RETRIEVED_AT = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _raise_http_failure(request: TransportRequest, status_code: int = 503) -> NoReturn:
    raise TransportFailure(
        request,
        TransportFailureReason.HTTP_STATUS,
        1,
        status_code=status_code,
        category=TransportFailureCategory.HTTP_STATUS,
    )


def _info_bytes(station: str, files: list[tuple[int, str]]) -> bytes:
    return json.dumps(
        [
            {
                "caption": "Messstelle",
                "data": [
                    {
                        "info": {
                            "data": [
                                {"caption": "HZBNR", "text": int(station)},
                                {
                                    "tag": "dl_mstfiles",
                                    "data": {
                                        "fileData": [
                                            {
                                                "fileNr": nr,
                                                "fileName": f"{prefix}-{station}.csv",
                                                "hzbnr": int(station),
                                                "msttyp": "owf",
                                            }
                                            for nr, prefix in files
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


def _owf_csv_bytes(
    *,
    station: str,
    descriptor: str,
    unit: str,
    export_span: str,
    body_lines: list[str],
    include_interval_rule: bool = True,
) -> bytes:
    lines = [
        "Stammdaten:",
        "Messstelle:                ;Teststation",
        f"HZB-Nummer:                ;{station}",
        f"Einheit:                   ;{unit}",
        f"Exportzeitreihe:           ;{descriptor}",
    ]
    if include_interval_rule:
        lines.append(f"Zeitreihenart:             ;{OWF_INTERVAL_RULE_TEXT}")
    lines.extend(
        [
            f"Exportzeitraum:            ;{export_span}",
            "Werte:",
            *body_lines,
            "",
        ]
    )
    return "\r\n".join(lines).encode("cp1252")


def _select_products(station: str, *products: str) -> rr.Selection:
    selected = rr.find(provider="at_ehyd", station=station)
    series_ids = rr.as_frame(selected).filter(pl.col("product_id").is_in(products))["series_id"].to_list()
    assert len(series_ids) == len(products)
    return rr.pick(selected, series_id=series_ids)


def test_public_owf_shared_acquisition_units_provenance_and_bounded_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    station = "209486"
    info_doc = _info_bytes(station, [(2, "W-Tagesmittel"), (5, "Q-Tagesmittel")])
    w_csv = _owf_csv_bytes(
        station=station,
        descriptor="Wasserstand,I,mit,T,1",
        unit="[cm]",
        export_span="[01.01.2020 00:00,01.01.2024 00:00]",
        body_lines=[
            "01.01.2020 00:00:00; -227,0",
            "02.01.2020 00:00:00; 15,5",
            "03.01.2020 00:00:00; Lücke",
            "04.01.2020 00:00:00; 0,0",
            "01.01.2024 00:00:00; Lücke",
        ],
    )
    q_csv = _owf_csv_bytes(
        station=station,
        descriptor="Abfluss,I,mit,T,1",
        unit="[m³/s]",
        export_span="[01.01.2020 00:00,01.01.2024 00:00]",
        body_lines=[
            "01.01.2020 00:00:00; 0,00",
            "02.01.2020 00:00:00; 12,34",
            "03.01.2020 00:00:00; 8,50",
            "04.01.2020 00:00:00; 6,25",
            "01.01.2024 00:00:00; Lücke",
        ],
    )

    class _OwfReplay:
        def __init__(self) -> None:
            self.requests: list[TransportRequest] = []
            self.fail_all = False

        def send(self, request: TransportRequest) -> TransportResponse:
            self.requests.append(request)
            params = dict(request.params or {})
            if self.fail_all:
                _raise_http_failure(request, 503)
            if request.url.endswith("/Messstellen/info"):
                assert params == {"hzbnr": station}
                return TransportResponse(info_doc, 200, _RETRIEVED_AT, "application/json", request.url, params)
            assert request.url.endswith("/MessstellenExtraData/owf")
            assert params["id"] == station
            body = w_csv if params["file"] == "2" else q_csv
            return TransportResponse(body, 200, _RETRIEVED_AT, "text/csv; charset=windows-1252", request.url, params)

    replay = _OwfReplay()
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    selected = _select_products(station, "owf_wasserst_tagesmittel", "owf_abfl_tagesmittel")
    first = rr.fetch(
        selected,
        start="2020-01-01",
        end="2020-01-04T23:59:59",
        cache="reuse",
        receipts=True,
    )
    # Shared acquisition: 1 Messstellen/info prerequisite + 2 CSV fetches = 3 HTTP calls.
    assert len(replay.requests) == 3
    assert [req.url.rsplit("/", 1)[-1] for req in replay.requests] == ["info", "owf", "owf"]
    assert first.receipts is not None and len(first.receipts.entries) == 3

    stage_rows = first.data.filter(pl.col("product_id") == "owf_wasserst_tagesmittel").sort("time")
    assert stage_rows["value"].to_list() == [pytest.approx(-2.27), pytest.approx(0.155), pytest.approx(0.0)]
    assert stage_rows["source_unit"].unique().to_list() == ["cm"]
    assert stage_rows["unit"].unique().to_list() == ["m"]
    assert stage_rows["time_zone"].unique().to_list() == ["unknown"]
    assert any(issue.code == "source.gap_marker" and issue.severity == "info" for issue in first.issues)

    flow_rows = first.data.filter(pl.col("product_id") == "owf_abfl_tagesmittel").sort("time")
    assert flow_rows["value"].to_list() == [
        pytest.approx(0.0),
        pytest.approx(12.34),
        pytest.approx(8.5),
        pytest.approx(6.25),
    ]
    assert flow_rows["source_unit"].unique().to_list() == ["m³/s"]
    assert flow_rows["unit"].unique().to_list() == ["m3/s"]

    # Provenance carries CC BY 4.0 and Datenquelle: ehyd.gv.at attribution.
    records = first.provenance.acquisition_provenance.header.source_records
    statements = [stmt for record in records for stmt in record.statements]
    assert any(stmt.kind == "license" and "CC BY 4.0" in stmt.exact_text for stmt in statements)
    assert any(stmt.kind == "citation" and "Datenquelle: ehyd.gv.at" in stmt.exact_text for stmt in statements)

    # Repeat historical query inside 2020..2023 reuses local store with 0 additional HTTP requests.
    reused = rr.fetch(selected, start="2020-01-01", end="2020-01-04T23:59:59", cache="reuse")
    assert len(replay.requests) == 3
    assert_frame_equal(first.data, reused.data)

    # Bypass re-fetches over HTTP without losing identical observation rows.
    bypassed = rr.fetch(selected, start="2020-01-01", end="2020-01-04T23:59:59", cache="bypass")
    assert len(replay.requests) == 6
    assert_frame_equal(first.data, bypassed.data)

    # Query extending into unpublished 2024 via predicate-based rr.find reuses accumulated store
    # without ObservationStoreRefusedError and records post-yearbook UNRESOLVED without raising on_issue="raise".
    q_only = rr.find(provider="at_ehyd", station=station, quantity="discharge", frequency="daily", statistic="mean")
    post_gap = rr.fetch(q_only, start="2020-01-04", end="2024-01-02T23:59:59", cache="reuse", on_issue="raise")
    assert len(replay.requests) == 8
    assert post_gap.data["value"].to_list() == [pytest.approx(6.25)]
    assert {item.status for item in post_gap.outcomes} == {OutcomeStatus.SUCCESS, OutcomeStatus.UNRESOLVED}

    # Failed refresh raises on "raise", warns on "warn", and preserves held cached observations on "warn"/"ignore".
    replay.fail_all = True
    with pytest.raises(IssuePolicyError):
        rr.fetch(selected, start="2020-01-01", end="2020-01-04T23:59:59", cache="refresh", on_issue="raise")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warned_refresh = rr.fetch(
            selected, start="2020-01-01", end="2020-01-04T23:59:59", cache="refresh", on_issue="warn"
        )
    assert caught
    assert_frame_equal(first.data, warned_refresh.data)
    failed_refresh = rr.fetch(
        selected, start="2020-01-01", end="2020-01-04T23:59:59", cache="refresh", on_issue="ignore"
    )
    assert_frame_equal(first.data, failed_refresh.data)
    assert any(issue.severity in ("warning", "error") for issue in failed_refresh.issues)


def test_public_all_11_products_route_isolation_and_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    expected_products = {
        "owf_abfl_tagesmittel",
        "owf_abfl_monatsminima",
        "owf_abfl_monatsmaxima",
        "owf_wasserst_tagesmittel",
        "owf_wasserst_monatsminima",
        "owf_wasserst_monatsmaxima",
        "owf_wassertemp_monatsmittel",
        "pegel_bgis_abfluss",
        "pegel_bgis_wasserstand",
        "pegel_longterm_abfluss",
        "pegel_longterm_wasserstand",
    }
    assert set(rr.products("at_ehyd")) == expected_products

    # 1. Monthly water temperature on 201350 preserves negative °C -> degC without touching Pegel Aktuell.
    wt_csv = _owf_csv_bytes(
        station="201350",
        descriptor="WTemperatur,I,mit,M,1",
        unit="[°C]",
        export_span="[01.01.2023 00:00,01.01.2024 00:00]",
        body_lines=[
            "01.01.2023 00:00:00; -0,4",
            "01.02.2023 00:00:00; 1,8",
            "01.01.2024 00:00:00; Lücke",
        ],
    )
    seen_urls: list[str] = []

    class _TempReplay:
        def send(self, request: TransportRequest) -> TransportResponse:
            seen_urls.append(request.url)
            params = dict(request.params or {})
            if request.url.endswith("/Messstellen/info"):
                return TransportResponse(
                    _info_bytes("201350", [(8, "WT-Monatsmittel")]),
                    200,
                    _RETRIEVED_AT,
                    "application/json",
                    request.url,
                    params,
                )
            return TransportResponse(wt_csv, 200, _RETRIEVED_AT, "text/csv", request.url, params)

    monkeypatch.setattr(discovery, "HttpClient", _TempReplay)
    temp_sel = rr.find(provider="at_ehyd", station="201350", quantity="temperature")
    temp_res = rr.fetch(temp_sel, start="2023-01-01", end="2023-02-28T23:59:59", cache="bypass")
    assert temp_res.data["value"].to_list() == [pytest.approx(-0.4), pytest.approx(1.8)]
    assert temp_res.data["source_unit"].unique().to_list() == ["°C"]
    assert temp_res.data["unit"].unique().to_list() == ["degC"]
    assert all("pegel" not in url for url in seen_urls)

    # 2. All 4 monthly extrema owf products on 209486 share 1 Messstellen/info call, select via standard M,1
    #    frequency="monthly" predicates, and convert stage cm -> m while keeping discharge in m3/s.
    extrema_files = [
        (3, "W-Monatsminima"),
        (4, "W-Monatsmaxima"),
        (6, "Q-Monatsminima"),
        (7, "Q-Monatsmaxima"),
    ]
    extrema_payloads = {
        "3": _owf_csv_bytes(
            station="209486",
            descriptor="Wasserstand,M,min,M,1",
            unit="[cm]",
            export_span="[01.01.2020 00:00,01.01.2024 00:00]",
            body_lines=["05.01.2020 12:15:00; -50,0", "01.01.2024 00:00:00; Lücke"],
            include_interval_rule=False,
        ),
        "4": _owf_csv_bytes(
            station="209486",
            descriptor="Wasserstand,M,max,M,1",
            unit="[cm]",
            export_span="[01.01.2020 00:00,01.01.2024 00:00]",
            body_lines=["18.01.2020 06:00:00; 210,0", "01.01.2024 00:00:00; Lücke"],
            include_interval_rule=False,
        ),
        "6": _owf_csv_bytes(
            station="209486",
            descriptor="Abfluss,M,min,M,1",
            unit="[m³/s]",
            export_span="[01.01.2020 00:00,01.01.2024 00:00]",
            body_lines=["05.01.2020 12:15:00; 1,25", "01.01.2024 00:00:00; Lücke"],
            include_interval_rule=False,
        ),
        "7": _owf_csv_bytes(
            station="209486",
            descriptor="Abfluss,M,max,M,1",
            unit="[m³/s]",
            export_span="[01.01.2020 00:00,01.01.2024 00:00]",
            body_lines=["18.01.2020 06:00:00; 48,60", "01.01.2024 00:00:00; Lücke"],
            include_interval_rule=False,
        ),
    }
    extrema_urls: list[str] = []

    class _ExtremaReplay:
        def send(self, request: TransportRequest) -> TransportResponse:
            extrema_urls.append(request.url)
            params = dict(request.params or {})
            if request.url.endswith("/Messstellen/info"):
                return TransportResponse(
                    _info_bytes("209486", extrema_files),
                    200,
                    _RETRIEVED_AT,
                    "application/json",
                    request.url,
                    params,
                )
            return TransportResponse(
                extrema_payloads[str(params["file"])], 200, _RETRIEVED_AT, "text/csv", request.url, params
            )

    monkeypatch.setattr(discovery, "HttpClient", _ExtremaReplay)
    monthly_stage_min = rr.find(
        provider="at_ehyd", station="209486", quantity="stage", frequency="monthly", statistic="min"
    )
    assert [item.product_id for item in monthly_stage_min.series] == ["owf_wasserst_monatsminima"]
    extrema_sel = _select_products(
        "209486",
        "owf_wasserst_monatsminima",
        "owf_wasserst_monatsmaxima",
        "owf_abfl_monatsminima",
        "owf_abfl_monatsmaxima",
    )
    extrema_res = rr.fetch(extrema_sel, start="2020-01-01", end="2020-01-31T23:59:59", cache="bypass")
    assert len(extrema_urls) == 5
    assert all("pegel" not in url for url in extrema_urls)
    by_product = {
        pid: extrema_res.data.filter(pl.col("product_id") == pid)["value"].to_list()
        for pid in (
            "owf_wasserst_monatsminima",
            "owf_wasserst_monatsmaxima",
            "owf_abfl_monatsminima",
            "owf_abfl_monatsmaxima",
        )
    }
    assert by_product["owf_wasserst_monatsminima"] == [pytest.approx(-0.50)]
    assert by_product["owf_wasserst_monatsmaxima"] == [pytest.approx(2.10)]
    assert by_product["owf_abfl_monatsminima"] == [pytest.approx(1.25)]
    assert by_product["owf_abfl_monatsmaxima"] == [pytest.approx(48.60)]

    # 3. Selecting pegel_bgis_wasserstand on 206557 hits only pegelBgis (never owf/pegelLongterm);
    #    selecting pegel_bgis_abfluss on 209486 when live response publishes Wasserstand yields NO_MATCH.
    bgis_urls: list[str] = []

    class _BgisReplay:
        def send(self, request: TransportRequest) -> TransportResponse:
            bgis_urls.append(request.url)
            params = dict(request.params or {})
            doc = {
                "hzbnr": int(params["hzbnr"]),
                "parameter": "Wasserstand",
                "einheit": "cm",
                "valCount": 2,
                "categories": ["2026-10-31 00:00:00", "2026-10-31 00:15:00"],
                "data": [-15.0, None],
                "wert": -15.0,
                "hochwasser1": 350.0,
            }
            return TransportResponse(
                json.dumps(doc).encode("utf-8"), 200, _RETRIEVED_AT, "application/json", request.url, request.params
            )

    monkeypatch.setattr(discovery, "HttpClient", _BgisReplay)
    bgis_sel = _select_products("206557", "pegel_bgis_wasserstand")
    bgis_res = rr.fetch(
        bgis_sel,
        start="2026-10-31T00:00:00",
        end="2026-10-31T00:30:00",
        cache="bypass",
    )
    assert bgis_urls == ["https://ehyd.gv.at/services/Diagram/pegelBgis"]
    assert bgis_res.data["product_id"].to_list() == ["pegel_bgis_wasserstand", "pegel_bgis_wasserstand"]
    assert bgis_res.data["value"].to_list() == [pytest.approx(-0.15), None]
    assert bgis_res.data["unit"].unique().to_list() == ["m"]
    assert bgis_res.data["time_zone"].unique().to_list() == ["+01:00"]

    bgis_mismatch_sel = _select_products("209486", "pegel_bgis_abfluss")
    bgis_mismatch = rr.fetch(
        bgis_mismatch_sel,
        start="2026-10-31T00:00:00",
        end="2026-10-31T00:30:00",
        cache="bypass",
        on_issue="ignore",
    )
    assert bgis_mismatch.data.is_empty()
    assert OutcomeStatus.NO_MATCH in {item.status for item in bgis_mismatch.outcomes}

    # 4. pegelLongterm routes hit only pegelLongterm, clip date-only rows via ClippingAxis.CALENDAR_DATE
    #    under intra-day bounds, trim trailing future nulls, exclude climatologies, and convert cm -> m.
    lt_urls: list[str] = []

    class _LongtermReplay:
        def send(self, request: TransportRequest) -> TransportResponse:
            lt_urls.append(request.url)
            params = dict(request.params or {})
            is_stage = params.get("hzbnr") == "206557"
            doc = {
                "parameter": "Wasserstand" if is_stage else "Abfluss",
                "einheit": "cm" if is_stage else "m³/s",
                "points_in_time": ["2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"],
                "current_value": [125.0, None, -5.0, None] if is_stage else [14.2, None, 16.8, None],
                "last_year_value": [99.0, 99.0, 99.0, 99.0],
                "mit_data": [50.0, 50.0, 50.0, 50.0],
            }
            return TransportResponse(
                json.dumps(doc).encode("utf-8"), 200, _RETRIEVED_AT, "application/json", request.url, request.params
            )

    monkeypatch.setattr(discovery, "HttpClient", _LongtermReplay)
    lt_sel = _select_products("209486", "pegel_longterm_abfluss")
    lt_res = rr.fetch(
        lt_sel,
        start="2026-10-29T18:00:00",
        end="2026-10-31T06:00:00",
        cache="bypass",
    )
    assert lt_urls == ["https://ehyd.gv.at/services/Diagram/pegelLongterm"]
    assert lt_res.data["product_id"].unique().to_list() == ["pegel_longterm_abfluss"]
    assert lt_res.data["time"].to_list() == [
        datetime(2026, 10, 29),
        datetime(2026, 10, 30),
        datetime(2026, 10, 31),
    ]
    assert lt_res.data["value"].to_list() == [pytest.approx(14.2), None, pytest.approx(16.8)]
    assert lt_res.data["time_zone"].unique().to_list() == ["unknown"]

    lt_stage_sel = _select_products("206557", "pegel_longterm_wasserstand")
    lt_stage_res = rr.fetch(lt_stage_sel, start="2026-10-29", end="2026-11-01T23:59:59", cache="bypass")
    assert lt_stage_res.data["value"].to_list() == [pytest.approx(1.25), None, pytest.approx(-0.05)]
    assert lt_stage_res.data["unit"].unique().to_list() == ["m"]


def test_public_physical_predicates_207340_exception_and_sibling_failure_survival(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Querying daily mean discharge selects owf_abfl_tagesmittel and withholds pegel_longterm_abfluss (statistic unknown).
    daily_mean_sel = rr.find(
        provider="at_ehyd",
        station="209486",
        quantity="discharge",
        frequency="daily",
        statistic="mean",
    )
    assert [item.product_id for item in daily_mean_sel.series] == ["owf_abfl_tagesmittel"]

    # Broad discharge query retains all 5 distinct discharge routes without ranking or merging.
    broad_sel = rr.find(provider="at_ehyd", station="209486", quantity="discharge")
    assert len(broad_sel.series) == 5

    # 2. Station 207340 W-Monatsminima (T,1) is refused under frequency="monthly" without starting network calls,
    #    and retrieved cleanly under statistic="min".
    def _forbid_http():
        pytest.fail("Empty selection must not construct HttpClient")

    monkeypatch.setattr(discovery, "HttpClient", _forbid_http)
    monthly_207340 = rr.find(
        provider="at_ehyd",
        station="207340",
        quantity="stage",
        frequency="monthly",
        statistic="min",
    )
    with pytest.raises(EmptySelectionError, match="at_ehyd"):
        rr.fetch(monthly_207340, start="2020-01-01", end="2020-01-05")

    min_207340_csv = _owf_csv_bytes(
        station="207340",
        descriptor="Wasserstand,M,min,T,1",
        unit="[cm]",
        export_span="[01.01.2020 00:00,01.01.2024 00:00]",
        body_lines=[
            "01.01.2020 08:30:00; 140,0",
            "02.01.2020 09:00:00; 138,0",
        ],
        include_interval_rule=False,
    )

    class _Min207340AndSiblingReplay:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = dict(request.params or {})
            if request.url.endswith("/Messstellen/info"):
                if params["hzbnr"] == "207340":
                    return TransportResponse(
                        _info_bytes("207340", [(3, "W-Monatsminima")]),
                        200,
                        _RETRIEVED_AT,
                        "application/json",
                        request.url,
                        params,
                    )
                return TransportResponse(
                    _info_bytes("209486", [(5, "Q-Tagesmittel"), (6, "Q-Monatsminima")]),
                    200,
                    _RETRIEVED_AT,
                    "application/json",
                    request.url,
                    params,
                )
            if params["id"] == "207340":
                return TransportResponse(min_207340_csv, 200, _RETRIEVED_AT, "text/csv", request.url, params)
            if params["file"] == "6":
                _raise_http_failure(request, 500)
            q_ok = _owf_csv_bytes(
                station="209486",
                descriptor="Abfluss,I,mit,T,1",
                unit="[m³/s]",
                export_span="[01.01.2020 00:00,01.01.2024 00:00]",
                body_lines=[
                    "01.01.2020 00:00:00; 4,50",
                    "01.01.2024 00:00:00; Lücke",
                ],
            )
            return TransportResponse(q_ok, 200, _RETRIEVED_AT, "text/csv", request.url, params)

    monkeypatch.setattr(discovery, "HttpClient", _Min207340AndSiblingReplay)
    min_207340_sel = rr.find(provider="at_ehyd", station="207340", quantity="stage", statistic="min")
    min_207340_res = rr.fetch(min_207340_sel, start="2020-01-01", end="2020-01-03T23:59:59", cache="bypass")
    assert min_207340_res.data["value"].to_list() == [pytest.approx(1.40), pytest.approx(1.38)]
    assert min_207340_res.data["unit"].unique().to_list() == ["m"]

    # 3. Sibling survival: Q-Monatsminima HTTP 500 fails with OutcomeStatus.FAILED while Q-Tagesmittel succeeds.
    pair_sel = _select_products("209486", "owf_abfl_tagesmittel", "owf_abfl_monatsminima")
    pair_res = rr.fetch(
        pair_sel,
        start="2020-01-01",
        end="2020-01-01T23:59:59",
        cache="bypass",
        on_issue="ignore",
    )
    assert pair_res.data["product_id"].to_list() == ["owf_abfl_tagesmittel"]
    assert pair_res.data["value"].to_list() == [pytest.approx(4.5)]
    assert {item.status for item in pair_res.outcomes} >= {OutcomeStatus.SUCCESS, OutcomeStatus.FAILED}


def test_public_rolling_telemetry_accumulation_and_failed_refresh_retention(monkeypatch: pytest.MonkeyPatch) -> None:
    snap_1 = {
        "hzbnr": 209486,
        "parameter": "Abfluss",
        "einheit": "m³/s",
        "valCount": 2,
        "categories": ["2026-10-31 10:00:00", "2026-10-31 10:15:00"],
        "data": [2.1, 2.2],
    }
    snap_2 = {
        "hzbnr": 209486,
        "parameter": "Abfluss",
        "einheit": "m³/s",
        "valCount": 2,
        "categories": ["2026-10-31 10:15:00", "2026-10-31 10:30:00"],
        "data": [2.2, 2.5],
    }

    class _RollingReplay:
        def __init__(self) -> None:
            self.step = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.step += 1
            if self.step == 1:
                return TransportResponse(
                    json.dumps(snap_1).encode("utf-8"),
                    200,
                    _RETRIEVED_AT,
                    "application/json",
                    request.url,
                    request.params,
                )
            if self.step == 2:
                return TransportResponse(
                    json.dumps(snap_2).encode("utf-8"),
                    200,
                    _RETRIEVED_AT,
                    "application/json",
                    request.url,
                    request.params,
                )
            _raise_http_failure(request, 504)

    replay = _RollingReplay()
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
    sel = _select_products("209486", "pegel_bgis_abfluss")
    kwargs = {
        "start": "2026-10-31T09:00:00",
        "end": "2026-10-31T11:00:00",
        "on_issue": "ignore",
    }

    first = rr.fetch(sel, cache="reuse", **kwargs)
    assert first.data["value"].to_list() == [pytest.approx(2.1), pytest.approx(2.2)]

    second = rr.fetch(sel, cache="reuse", **kwargs)
    assert second.data["value"].to_list() == [pytest.approx(2.1), pytest.approx(2.2), pytest.approx(2.5)]

    failed = rr.fetch(sel, cache="refresh", **kwargs)
    assert_frame_equal(second.data, failed.data)
    assert any(issue.severity in ("warning", "error") for issue in failed.issues)

    # pegelLongterm rolling daily snapshots also accumulate in the local store across snapshots.
    lt_snap_1 = {
        "parameter": "Abfluss",
        "einheit": "m³/s",
        "points_in_time": ["2026-10-29", "2026-10-30"],
        "current_value": [10.0, 11.0],
    }
    lt_snap_2 = {
        "parameter": "Abfluss",
        "einheit": "m³/s",
        "points_in_time": ["2026-10-30", "2026-10-31"],
        "current_value": [11.0, 12.5],
    }

    class _LongtermRollingReplay:
        def __init__(self) -> None:
            self.step = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.step += 1
            doc = lt_snap_1 if self.step == 1 else lt_snap_2
            return TransportResponse(
                json.dumps(doc).encode("utf-8"),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                request.params,
            )

    lt_replay = _LongtermRollingReplay()
    monkeypatch.setattr(discovery, "HttpClient", lambda: lt_replay)
    lt_sel = _select_products("209486", "pegel_longterm_abfluss")
    lt_first = rr.fetch(lt_sel, start="2026-10-29", end="2026-10-31", cache="reuse")
    assert lt_first.data["value"].to_list() == [pytest.approx(10.0), pytest.approx(11.0)]
    lt_second = rr.fetch(lt_sel, start="2026-10-29", end="2026-10-31", cache="reuse")
    assert lt_second.data["value"].to_list() == [
        pytest.approx(10.0),
        pytest.approx(11.0),
        pytest.approx(12.5),
    ]


def test_public_unsupported_response_unit_and_empty_pegel_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    datum_doc = {
        "hzbnr": 206557,
        "parameter": "Wasserstand",
        "einheit": "m ü.A",
        "valCount": 1,
        "categories": ["2026-10-31 10:00:00"],
        "data": [412.35],
    }

    class _DatumReplay:
        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(
                json.dumps(datum_doc).encode("utf-8"),
                200,
                _RETRIEVED_AT,
                "application/json",
                request.url,
                request.params,
            )

    monkeypatch.setattr(discovery, "HttpClient", _DatumReplay)
    stage_sel = _select_products("206557", "pegel_bgis_wasserstand")
    with pytest.raises(IssuePolicyError):
        rr.fetch(stage_sel, start="2026-10-31T09:00:00", end="2026-10-31T11:00:00", cache="bypass", on_issue="raise")

    unsupported = rr.fetch(
        stage_sel,
        start="2026-10-31T09:00:00",
        end="2026-10-31T11:00:00",
        cache="bypass",
        on_issue="ignore",
    )
    assert unsupported.data.is_empty()
    assert OutcomeStatus.UNSUPPORTED in {item.status for item in unsupported.outcomes}
    datum_facts = [
        fact for series in unsupported.source_series for fact in series.facts if fact.source_unit.value == "m ü.A"
    ]
    assert len(datum_facts) == 1
    assert datum_facts[0].source_unit.evidence == ("https://ehyd.gv.at/services/Diagram/pegelBgis",)

    class _EmptyBodyReplay:
        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(b"", 200, _RETRIEVED_AT, "application/json", request.url, request.params)

    monkeypatch.setattr(discovery, "HttpClient", _EmptyBodyReplay)
    with pytest.raises(IssuePolicyError):
        rr.fetch(
            stage_sel,
            start="2026-10-31T09:00:00",
            end="2026-10-31T11:00:00",
            cache="bypass",
            on_issue="raise",
        )
    empty_res = rr.fetch(
        stage_sel,
        start="2026-10-31T09:00:00",
        end="2026-10-31T11:00:00",
        cache="bypass",
        on_issue="ignore",
    )
    assert empty_res.data.is_empty()
    assert {item.status for item in empty_res.outcomes} == {OutcomeStatus.UNRESOLVED}

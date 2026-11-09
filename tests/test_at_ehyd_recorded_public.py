"""Public replay of retained Austria eHYD HTTP captures through find/pick/fetch."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.selection import UnknownStationError
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse

_SCOPE = "maintenance/observations/at_ehyd/retrieval"

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _load_capture(root: Path, group: str, name: str) -> tuple[bytes, dict[str, object]]:
    base = root / _SCOPE / group / name
    return base.with_suffix(".body").read_bytes(), json.loads(base.with_suffix(".receipt.json").read_bytes())


def _response_matching_request(
    root: Path,
    group: str,
    name: str,
    request: TransportRequest,
) -> TransportResponse:
    content, receipt = _load_capture(root, group, name)
    source = urlsplit(str(receipt["url"]))
    expected_params = {key: vals[0] for key, vals in parse_qs(source.query, keep_blank_values=True).items()}
    requested = urlsplit(request.url)
    assert (requested.scheme, requested.netloc, requested.path) == (
        source.scheme,
        source.netloc,
        source.path,
    )
    assert dict(request.params or {}) == expected_params
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    retrieved_at = datetime.fromisoformat(str(receipt["acquired_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=content,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=retrieved_at,
        content_type=str(content_type) if content_type is not None else None,
        url=f"{source.scheme}://{source.netloc}{source.path}",
        request_parameters=expected_params,
    )


def _decode_owf_slice(
    content: bytes,
    start: datetime,
    end: datetime,
    *,
    scale: float = 1.0,
) -> list[tuple[datetime, float]]:
    text = content.decode("cp1252")
    in_values = False
    rows: list[tuple[datetime, float]] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not in_values:
            if stripped.startswith("Werte:"):
                in_values = True
            continue
        if not stripped:
            continue
        left, right = (part.strip() for part in raw_line.split(";", 1))
        if right == "Lücke":
            continue
        ts = datetime.strptime(left, "%d.%m.%Y %H:%M:%S")
        if start <= ts <= end:
            rows.append((ts, float(right.replace(",", ".")) * scale))
    return rows


def _select_products(station: str, *products: str) -> rr.Selection:
    selected = rr.find(provider="at_ehyd", station=station)
    series_ids = rr.as_frame(selected).filter(pl.col("product_id").is_in(products))["series_id"].to_list()
    assert len(series_ids) == len(products)
    return rr.pick(selected, series_id=series_ids)


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_owf_209486_all_six_series_clipping_units_and_cache(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_to_capture = {
        "2": ("owf_wasserst_tagesmittel", "owf-209486-file2-w-tagesmittel", 0.01),
        "3": ("owf_wasserst_monatsminima", "owf-209486-file3-w-monatsminima", 0.01),
        "4": ("owf_wasserst_monatsmaxima", "owf-209486-file4-w-monatsmaxima", 0.01),
        "5": ("owf_abfl_tagesmittel", "owf-209486-file5-q-tagesmittel", 1.0),
        "6": ("owf_abfl_monatsminima", "owf-209486-file6-q-monatsminima", 1.0),
        "7": ("owf_abfl_monatsmaxima", "owf-209486-file7-q-monatsmaxima", 1.0),
    }

    class _Replay209486:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            if request.url.endswith("/Messstellen/info"):
                return _response_matching_request(retained_evidence_root, "access", "messstellen-info-209486", request)
            file_nr = str((request.params or {})["file"])
            _, capture_name, _ = file_to_capture[file_nr]
            return _response_matching_request(retained_evidence_root, "access", capture_name, request)

    replay = _Replay209486()
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    owf_products = tuple(item[0] for item in file_to_capture.values())
    selection = _select_products("209486", *owf_products)
    start_str, end_str = "2020-01-01", "2023-12-31T23:59:59"
    start_dt, end_dt = datetime.fromisoformat(start_str), datetime.fromisoformat(end_str)

    result = rr.fetch(selection, start=start_str, end=end_str, cache="reuse", receipts=True)
    # 1 shared Messstellen/info prerequisite + 6 CSV downloads.
    assert replay.calls == 7
    assert result.receipts is not None and len(result.receipts.entries) == 7
    assert result.data["time_zone"].unique().to_list() == ["unknown"]

    for _, (product_id, capture_name, scale) in file_to_capture.items():
        raw_bytes, _ = _load_capture(retained_evidence_root, "access", capture_name)
        expected = _decode_owf_slice(raw_bytes, start_dt, end_dt, scale=scale)
        actual_df = result.data.filter(pl.col("product_id") == product_id).sort("time")
        assert actual_df.height == len(expected) > 0
        assert actual_df["time"].to_list() == [ts for ts, _ in expected]
        assert actual_df["value"].to_list() == pytest.approx([val for _, val in expected])
        if scale == 0.01:
            assert actual_df["source_unit"].unique().to_list() == ["cm"]
            assert actual_df["unit"].unique().to_list() == ["m"]
        else:
            assert actual_df["source_unit"].unique().to_list() == ["m³/s"]
            assert actual_df["unit"].unique().to_list() == ["m3/s"]

    # Provenance carries verified CC BY 4.0 license and Datenquelle: ehyd.gv.at citation.
    statements = [
        stmt for record in result.provenance.acquisition_provenance.header.source_records for stmt in record.statements
    ]
    assert any(stmt.kind == "license" and "CC BY 4.0" in stmt.exact_text for stmt in statements)
    assert any(stmt.kind == "citation" and "Datenquelle: ehyd.gv.at" in stmt.exact_text for stmt in statements)

    # Repeat historical sub-window query is served entirely from local store (0 HTTP calls).
    sub_start, sub_end = "2021-06-01", "2022-06-30T23:59:59"
    reused = rr.fetch(selection, start=sub_start, end=sub_end, cache="reuse")
    assert replay.calls == 7
    q_bytes, _ = _load_capture(retained_evidence_root, "access", "owf-209486-file5-q-tagesmittel")
    expected_q = _decode_owf_slice(q_bytes, datetime.fromisoformat(sub_start), datetime.fromisoformat(sub_end))
    reused_q = reused.data.filter(pl.col("product_id") == "owf_abfl_tagesmittel").sort("time")
    assert reused_q["time"].to_list() == [ts for ts, _ in expected_q]
    assert reused_q["value"].to_list() == pytest.approx([val for _, val in expected_q])

    # Extending into unpublished 2024 reuses the accumulated store cleanly and marks post-2023 UNRESOLVED.
    q_only = rr.find(
        provider="at_ehyd",
        station="209486",
        quantity="discharge",
        frequency="daily",
        statistic="mean",
    )
    assert [item.product_id for item in q_only.series] == ["owf_abfl_tagesmittel"]
    post_gap = rr.fetch(q_only, start="2023-12-25", end="2024-01-05T23:59:59", cache="reuse", on_issue="raise")
    assert replay.calls == 9
    assert {item.status for item in post_gap.outcomes} == {OutcomeStatus.SUCCESS, OutcomeStatus.UNRESOLVED}
    expected_tail = _decode_owf_slice(q_bytes, datetime(2023, 12, 25), datetime(2023, 12, 31, 23, 59, 59))
    assert post_gap.data["value"].to_list() == pytest.approx([val for _, val in expected_tail])


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_pegel_aktuell_rolling_accumulation_units_and_nulls(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. Two-snapshot rolling store accumulation on 209486 merges overlapping morning and evening captures.
    class _Rolling209486:
        def __init__(self) -> None:
            self.evening = False
            self.calls = 0

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            group = "catalogue" if self.evening else "access"
            return _response_matching_request(retained_evidence_root, group, "pegel-bgis-209486", request)

    rolling = _Rolling209486()
    monkeypatch.setattr(discovery, "HttpClient", lambda: rolling)
    bgis_209486 = _select_products("209486", "pegel_bgis_abfluss")

    morning_bytes, _ = _load_capture(retained_evidence_root, "access", "pegel-bgis-209486")
    evening_bytes, _ = _load_capture(retained_evidence_root, "catalogue", "pegel-bgis-209486")
    morning_doc = json.loads(morning_bytes)
    evening_doc = json.loads(evening_bytes)
    combined_expected = dict(zip(morning_doc["categories"], morning_doc["data"], strict=True))
    combined_expected.update(zip(evening_doc["categories"], evening_doc["data"], strict=True))

    res_morning = rr.fetch(bgis_209486, start="2026-09-25", end="2026-11-02", cache="reuse", on_issue="ignore")
    assert res_morning.data.height == len(morning_doc["categories"]) > 0
    assert res_morning.data["time_zone"].unique().to_list() == ["+01:00"]

    rolling.evening = True
    res_evening = rr.fetch(bgis_209486, start="2026-09-25", end="2026-11-02", cache="reuse", on_issue="ignore")
    assert rolling.calls == 2
    assert (
        len(morning_doc["categories"])
        < len(combined_expected)
        < len(morning_doc["categories"]) + len(evening_doc["categories"])
    )
    assert res_evening.data.height == len(combined_expected)
    sorted_expected = [
        (datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"), val) for ts, val in sorted(combined_expected.items())
    ]
    assert res_evening.data.sort("time")["time"].to_list() == [ts for ts, _ in sorted_expected]
    assert res_evening.data.sort("time")["value"].to_list() == pytest.approx([val for _, val in sorted_expected])

    # 2. Stage cm -> m conversion and discharge m3/s across pegelBgis and pegelLongterm, plus interior nulls.
    cases = [
        ("access", "pegel-bgis-206557-stage", "206557", "pegel_bgis_wasserstand", 0.01, "cm", "m", "+01:00"),
        ("access", "pegel-longterm-209486", "209486", "pegel_longterm_abfluss", 1.0, "m³/s", "m3/s", "unknown"),
        ("catalogue", "pegel-longterm-206557", "206557", "pegel_longterm_wasserstand", 0.01, "cm", "m", "unknown"),
        ("catalogue", "pegel-bgis-200592", "200592", "pegel_bgis_abfluss", 1.0, "m³/s", "m3/s", "+01:00"),
        ("catalogue", "pegel-longterm-200345", "200345", "pegel_longterm_abfluss", 1.0, "m³/s", "m3/s", "unknown"),
    ]
    for group, capture_name, station, product_id, scale, src_unit, unit, tz in cases:
        monkeypatch.setattr(
            discovery,
            "HttpClient",
            lambda g=group, n=capture_name: type(
                "_Single",
                (),
                {"send": lambda self, req: _response_matching_request(retained_evidence_root, g, n, req)},
            )(),
        )
        sel = _select_products(station, product_id)
        out = rr.fetch(sel, start="2026-01-01", end="2026-12-31T23:59:59", cache="bypass", on_issue="ignore")
        assert not out.data.is_empty(), capture_name
        assert out.data["source_unit"].unique().to_list() == [src_unit]
        assert out.data["unit"].unique().to_list() == [unit]
        assert out.data["time_zone"].unique().to_list() == [tz]

        raw_doc = json.loads(_load_capture(retained_evidence_root, group, capture_name)[0])
        out_sorted = out.data.sort("time")
        if product_id.startswith("pegel_bgis_"):
            expected_times = [datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") for ts in raw_doc["categories"]]
            expected_vals = [None if v is None else pytest.approx(float(v) * scale) for v in raw_doc["data"]]
            assert out_sorted["time"].to_list() == expected_times
            assert out_sorted["value"].to_list() == expected_vals
        else:
            vals = list(raw_doc["current_value"])
            last_idx = max(i for i, v in enumerate(vals) if v is not None)
            trimmed_times = [datetime.strptime(d, "%Y-%m-%d") for d in raw_doc["points_in_time"][: last_idx + 1]]
            trimmed_vals = [None if v is None else pytest.approx(float(v) * scale) for v in vals[: last_idx + 1]]
            assert out_sorted["time"].to_list() == trimmed_times
            assert out_sorted["value"].to_list() == trimmed_vals
            assert out_sorted["value"][-1] is not None


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_unresolved_boundaries_and_telemetry_only_discovery(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Telemetry-only river gauge 200675 exposes only Pegel Aktuell series in offline discovery.
    sel_200675 = rr.find(provider="at_ehyd", station="200675")
    assert all(not item.product_id.startswith("owf_") for item in sel_200675.series)

    # Standing-water lake gauges 210120 and 213801 are excluded from the river station catalogue.
    for lake_station in ("210120", "213801"):
        with pytest.raises(UnknownStationError):
            rr.find(provider="at_ehyd", station=lake_station)

    # River gauges whose retained pegelBgis probes were 0 bytes do not claim pegel_bgis_* in offline discovery.
    for group, capture_name, station in (
        ("access", "pegel-bgis-215541-empty", "215541"),
        ("catalogue", "pegel-bgis-212167", "212167"),
    ):
        raw_body, _ = _load_capture(retained_evidence_root, group, capture_name)
        assert raw_body == b""
        sel_station = rr.find(provider="at_ehyd", station=station)
        assert all(not item.product_id.startswith("pegel_bgis_") for item in sel_station.series)

    # Witnessed Pegel Aktuell series with valCount=0 (209288) or all-null current_value (212167) report UNRESOLVED.
    unresolved_cases = [
        ("catalogue", "pegel-bgis-209288", "209288", "pegel_bgis_abfluss"),
        ("catalogue", "pegel-longterm-212167", "212167", "pegel_longterm_abfluss"),
    ]
    for group, capture_name, station, product_id in unresolved_cases:
        monkeypatch.setattr(
            discovery,
            "HttpClient",
            lambda g=group, n=capture_name: type(
                "_Unresolved",
                (),
                {"send": lambda self, req: _response_matching_request(retained_evidence_root, g, n, req)},
            )(),
        )
        sel = _select_products(station, product_id)
        res = rr.fetch(sel, start="2026-10-01", end="2026-10-31T23:59:59", cache="bypass", on_issue="raise")
        assert res.data.is_empty(), capture_name
        assert [item.status for item in res.outcomes] == [OutcomeStatus.UNRESOLVED]


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_verification_supplement_routes_and_owf_source_boundaries(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    # 1. 11th public route (owf_wassertemp_monatsmittel) on 201350 + cache reuse, plus negative °C on 200352.
    class _WaterTemp201350:
        calls = 0

        def send(self, req: TransportRequest) -> TransportResponse:
            self.calls += 1
            if req.url.endswith("/Messstellen/info"):
                return _response_matching_request(
                    retained_evidence_root, "verification", "messstellen-info-201350", req
                )
            return _response_matching_request(retained_evidence_root, "access", "owf-201350-file8-wt-monatsmittel", req)

    wt_201350 = _WaterTemp201350()
    monkeypatch.setattr(discovery, "HttpClient", lambda: wt_201350)
    sel_wt_201350 = rr.find(
        provider="at_ehyd", station="201350", quantity="temperature", frequency="monthly", statistic="mean"
    )
    assert [item.product_id for item in sel_wt_201350.series] == ["owf_wassertemp_monatsmittel"]
    wt_start, wt_end = "2018-01-01", "2023-12-31T23:59:59"
    res_wt_201350 = rr.fetch(sel_wt_201350, start=wt_start, end=wt_end, cache="reuse", receipts=True)
    assert wt_201350.calls == 2
    assert res_wt_201350.receipts is not None and len(res_wt_201350.receipts.entries) == 2
    wt_bytes_201350, _ = _load_capture(retained_evidence_root, "access", "owf-201350-file8-wt-monatsmittel")
    exp_wt_201350 = _decode_owf_slice(
        wt_bytes_201350, datetime.fromisoformat(wt_start), datetime.fromisoformat(wt_end), scale=1.0
    )
    assert res_wt_201350.data["source_unit"].unique().to_list() == ["°C"]
    assert res_wt_201350.data["unit"].unique().to_list() == ["degC"]
    assert res_wt_201350.data.sort("time")["time"].to_list() == [ts for ts, _ in exp_wt_201350]
    assert res_wt_201350.data.sort("time")["value"].to_list() == pytest.approx([val for _, val in exp_wt_201350])

    def _assert_owf_slice_equal(
        frame: pl.DataFrame,
        group: str,
        capture_name: str,
        start: datetime,
        end: datetime,
        *,
        scale: float = 1.0,
    ) -> list[tuple[datetime, float]]:
        raw_bytes, _ = _load_capture(retained_evidence_root, group, capture_name)
        expected = _decode_owf_slice(raw_bytes, start, end, scale=scale)
        ordered = frame.sort("time")
        assert ordered.height == len(expected) > 0
        assert ordered["time"].to_list() == [ts for ts, _ in expected]
        assert ordered["value"].to_list() == pytest.approx([val for _, val in expected])
        return expected

    # Cached sub-window query on 201350 water temperature issues 0 network requests.
    reused_wt = rr.fetch(sel_wt_201350, start="2020-01-01", end="2021-12-31T23:59:59", cache="reuse")
    assert wt_201350.calls == 2
    _assert_owf_slice_equal(
        reused_wt.data,
        "access",
        "owf-201350-file8-wt-monatsmittel",
        datetime(2020, 1, 1),
        datetime(2021, 12, 31, 23, 59, 59),
        scale=1.0,
    )

    # Genuine negative water temperature (-2.8 °C -> -2.8 degC) on river gauge 200352.
    monkeypatch.setattr(
        discovery,
        "HttpClient",
        lambda: type(
            "_WT200352",
            (),
            {
                "send": lambda self, req: _response_matching_request(
                    retained_evidence_root,
                    "verification",
                    "messstellen-info-200352"
                    if req.url.endswith("/Messstellen/info")
                    else "owf-200352-file8-wt-monatsmittel",
                    req,
                )
            },
        )(),
    )
    sel_wt_200352 = rr.find(
        provider="at_ehyd", station="200352", quantity="temperature", frequency="monthly", statistic="mean"
    )
    res_wt_200352 = rr.fetch(sel_wt_200352, start="1970-01-01", end="2023-12-31T23:59:59", cache="bypass")
    assert res_wt_200352.data["unit"].unique().to_list() == ["degC"]
    _assert_owf_slice_equal(
        res_wt_200352.data,
        "verification",
        "owf-200352-file8-wt-monatsmittel",
        datetime(1970, 1, 1),
        datetime(2023, 12, 31, 23, 59, 59),
        scale=1.0,
    )
    min_wt_row = res_wt_200352.data.sort("value", "time").row(0, named=True)
    assert min_wt_row["time"] == datetime(2023, 12, 1, 0, 0)
    assert min_wt_row["value"] == pytest.approx(-2.8)

    # 2. Negative gauge-zero stage scaling (-227.0 cm -> -2.27 m) on 207068 (Linz / Donau).
    monkeypatch.setattr(
        discovery,
        "HttpClient",
        lambda: type(
            "_Stage207068",
            (),
            {
                "send": lambda self, req: _response_matching_request(
                    retained_evidence_root,
                    "verification",
                    "messstellen-info-207068"
                    if req.url.endswith("/Messstellen/info")
                    else "owf-207068-file3-w-monatsminima",
                    req,
                )
            },
        )(),
    )
    sel_207068 = rr.find(provider="at_ehyd", station="207068", quantity="stage", frequency="monthly", statistic="min")
    res_207068 = rr.fetch(sel_207068, start="1901-01-01", end="2023-12-31T23:59:59", cache="bypass")
    assert res_207068.data["source_unit"].unique().to_list() == ["cm"]
    assert res_207068.data["unit"].unique().to_list() == ["m"]
    _assert_owf_slice_equal(
        res_207068.data,
        "verification",
        "owf-207068-file3-w-monatsminima",
        datetime(1901, 1, 1),
        datetime(2023, 12, 31, 23, 59, 59),
        scale=0.01,
    )
    min_stage_row = res_207068.data.sort("value", "time").row(0, named=True)
    assert min_stage_row["time"] == datetime(1933, 1, 28, 0, 0)
    assert min_stage_row["value"] == pytest.approx(-2.27)

    # 3. Sparse multi-year 'Lücke' gap markers on 201806 omit gap lines and emit info source.gap_marker.
    monkeypatch.setattr(
        discovery,
        "HttpClient",
        lambda: type(
            "_Gap201806",
            (),
            {
                "send": lambda self, req: _response_matching_request(
                    retained_evidence_root,
                    "verification",
                    "messstellen-info-201806"
                    if req.url.endswith("/Messstellen/info")
                    else "owf-201806-file2-w-tagesmittel",
                    req,
                )
            },
        )(),
    )
    sel_201806 = rr.find(provider="at_ehyd", station="201806", quantity="stage", frequency="daily", statistic="mean")
    res_201806 = rr.fetch(sel_201806, start="1975-01-01", end="2023-12-31T23:59:59", cache="bypass", on_issue="raise")
    assert res_201806.data["value"].null_count() == 0
    _assert_owf_slice_equal(
        res_201806.data,
        "verification",
        "owf-201806-file2-w-tagesmittel",
        datetime(1975, 1, 1),
        datetime(2023, 12, 31, 23, 59, 59),
        scale=0.01,
    )
    gap_issues = [item for item in res_201806.issues if item.code == "source.gap_marker"]
    assert len(gap_issues) == 1
    assert gap_issues[0].severity == "info"
    # 1,098 total 'Lücke' lines: 1,097 interior transitions + 1 closing-boundary t_end sentinel.
    assert gap_issues[0].details["count"] == 1097

    # 4. Werfen 204032: unbracketed Einheit, '; bis ;' Exportzeitraum, and 00:00:00 pre-header row cached offline.
    class _Werfen204032:
        calls = 0

        def send(self, req: TransportRequest) -> TransportResponse:
            self.calls += 1
            name = (
                "messstellen-info-204032" if req.url.endswith("/Messstellen/info") else "owf-204032-file5-q-tagesmittel"
            )
            return _response_matching_request(retained_evidence_root, "verification", name, req)

    werfen = _Werfen204032()
    monkeypatch.setattr(discovery, "HttpClient", lambda: werfen)
    sel_204032 = rr.find(
        provider="at_ehyd", station="204032", quantity="discharge", frequency="daily", statistic="mean"
    )
    res_204032 = rr.fetch(sel_204032, start="1995-01-01", end="1995-01-10T23:59:59", cache="reuse")
    assert werfen.calls == 2
    assert res_204032.data.sort("time")["time"][0] == datetime(1995, 1, 1, 0, 0)
    _assert_owf_slice_equal(
        res_204032.data,
        "verification",
        "owf-204032-file5-q-tagesmittel",
        datetime(1995, 1, 1),
        datetime(1995, 1, 10, 23, 59, 59),
        scale=1.0,
    )
    reused_204032 = rr.fetch(sel_204032, start="1995-01-01", end="1995-01-05T23:59:59", cache="reuse")
    assert werfen.calls == 2
    assert reused_204032.data.sort("time")["time"][0] == datetime(1995, 1, 1, 0, 0)
    _assert_owf_slice_equal(
        reused_204032.data,
        "verification",
        "owf-204032-file5-q-tagesmittel",
        datetime(1995, 1, 1),
        datetime(1995, 1, 5, 23, 59, 59),
        scale=1.0,
    )

    # 5. Station 207340 W-Monatsminima (T,1 daily step): withheld from frequency="monthly", selectable by statistic="min".
    monthly_207340 = rr.find(provider="at_ehyd", station="207340", frequency="monthly")
    assert [item.product_id for item in monthly_207340.series] == ["owf_wasserst_monatsmaxima"]
    min_207340 = rr.find(provider="at_ehyd", station="207340", statistic="min")
    assert [item.product_id for item in min_207340.series] == ["owf_wasserst_monatsminima"]
    monkeypatch.setattr(
        discovery,
        "HttpClient",
        lambda: type(
            "_Min207340",
            (),
            {
                "send": lambda self, req: _response_matching_request(
                    retained_evidence_root,
                    "verification",
                    "messstellen-info-207340"
                    if req.url.endswith("/Messstellen/info")
                    else "owf-207340-file3-w-monatsminima",
                    req,
                )
            },
        )(),
    )
    res_207340 = rr.fetch(min_207340, start="2023-01-01", end="2023-01-10T23:59:59", cache="bypass")
    assert res_207340.data["unit"].unique().to_list() == ["m"]
    _assert_owf_slice_equal(
        res_207340.data,
        "verification",
        "owf-207340-file3-w-monatsminima",
        datetime(2023, 1, 1),
        datetime(2023, 1, 10, 23, 59, 59),
        scale=0.01,
    )
    series_207340 = rr.series(res_207340).row(0, named=True)
    assert series_207340["frequency"] is None
    assert series_207340["frequency_state"] == "not_established"
    assert series_207340["temporal_support"] is None
    assert series_207340["temporal_support_state"] == "not_established"
    assert series_207340["statistic"] == "min"

    # 6. Cleared-unit W-Tagesmittel on 211078 is withheld from offline rr.find discovery while valid siblings remain selectable.
    sel_211078 = rr.find(provider="at_ehyd", station="211078")
    assert sorted(item.product_id for item in sel_211078.series) == [
        "owf_abfl_monatsmaxima",
        "owf_abfl_monatsminima",
        "owf_abfl_tagesmittel",
        "owf_wasserst_monatsmaxima",
        "owf_wasserst_monatsminima",
    ]

    # 7. Multi-series sibling survival across UNRESOLVED (208058 Invalid; Lücke) and FAILED (209486 0-byte owf).
    monkeypatch.setattr(
        discovery,
        "HttpClient",
        lambda: type(
            "_Sibling208058",
            (),
            {
                "send": lambda self, req: _response_matching_request(
                    retained_evidence_root,
                    "verification",
                    "messstellen-info-208058"
                    if req.url.endswith("/Messstellen/info")
                    else (
                        "owf-208058-file8-wt-monatsmittel"
                        if str((req.params or {})["file"]) == "8"
                        else "owf-208058-file5-q-tagesmittel"
                    ),
                    req,
                )
            },
        )(),
    )
    sel_208058 = _select_products("208058", "owf_wassertemp_monatsmittel", "owf_abfl_tagesmittel")
    res_208058 = rr.fetch(sel_208058, start="2023-01-01", end="2023-01-10T23:59:59", cache="bypass", on_issue="ignore")
    assert res_208058.data["product_id"].unique().to_list() == ["owf_abfl_tagesmittel"]
    _assert_owf_slice_equal(
        res_208058.data,
        "verification",
        "owf-208058-file5-q-tagesmittel",
        datetime(2023, 1, 1),
        datetime(2023, 1, 10, 23, 59, 59),
        scale=1.0,
    )
    assert [item.status for item in res_208058.outcomes if item.product_id == "owf_wassertemp_monatsmittel"] == [
        OutcomeStatus.UNRESOLVED
    ]

    class _PartialFail209486:
        def send(self, req: TransportRequest) -> TransportResponse:
            if req.url.endswith("/Messstellen/info"):
                return _response_matching_request(retained_evidence_root, "access", "messstellen-info-209486", req)
            file_nr = str((req.params or {})["file"])
            if file_nr == "5":
                return _response_matching_request(
                    retained_evidence_root, "access", "owf-209486-file5-q-tagesmittel", req
                )
            # Parameter-remapped fault-isolation check: serve retained 0-byte file=99 body on sibling file=2.
            empty_body, empty_rcpt = _load_capture(retained_evidence_root, "access", "owf-209486-invalid-file99")
            assert empty_body == b""
            return TransportResponse(
                content=empty_body,
                status_code=int(str(empty_rcpt["http_status"])),
                retrieved_at=datetime.fromisoformat(str(empty_rcpt["acquired_at"]).replace("Z", "+00:00")),
                content_type="text/plain",
                url="https://ehyd.gv.at/services/MessstellenExtraData/owf",
                request_parameters={"id": "209486", "file": file_nr},
            )

    monkeypatch.setattr(discovery, "HttpClient", _PartialFail209486)
    sel_partial = _select_products("209486", "owf_abfl_tagesmittel", "owf_wasserst_tagesmittel")
    res_partial = rr.fetch(
        sel_partial, start="2023-01-01", end="2023-01-10T23:59:59", cache="bypass", on_issue="ignore"
    )
    assert res_partial.data["product_id"].unique().to_list() == ["owf_abfl_tagesmittel"]
    _assert_owf_slice_equal(
        res_partial.data,
        "access",
        "owf-209486-file5-q-tagesmittel",
        datetime(2023, 1, 1),
        datetime(2023, 1, 10, 23, 59, 59),
        scale=1.0,
    )
    assert [item.status for item in res_partial.outcomes if item.product_id == "owf_abfl_tagesmittel"] == [
        OutcomeStatus.SUCCESS
    ]
    assert [item.status for item in res_partial.outcomes if item.product_id == "owf_wasserst_tagesmittel"] == [
        OutcomeStatus.FAILED,
        OutcomeStatus.UNRESOLVED,
    ]
    assert [item.details["product_id"] for item in res_partial.issues if item.severity == "error"] == [
        "owf_wasserst_tagesmittel"
    ]

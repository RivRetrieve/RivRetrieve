"""Public replay of retained Argentina INA Alerta5 HTTP captures through find/pick/fetch."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit  # noqa: TID251 - URL parsing for retained receipt replay only

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.discovery import EmptySelectionError
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse

_SCOPE = "maintenance/observations/ar_ina/retrieval"

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _load_capture(root: Path, group: str, name: str) -> tuple[bytes, dict[str, object]]:
    base = root / _SCOPE / group / name
    return base.with_suffix(".body").read_bytes(), json.loads(base.with_suffix(".receipt.json").read_bytes())


def _response_matching_request(
    root: Path,
    group: str,
    name: str,
    request: TransportRequest,
    *,
    strict_params: bool = True,
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
    actual_params = dict(request.params or {})
    if strict_params:
        assert actual_params == expected_params
    else:
        assert actual_params.get("skip_nulls") == "true"
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    status_code = int(str(receipt.get("status", receipt.get("http_status", 200))))
    retrieved_at = datetime.fromisoformat(str(receipt["acquired_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=content,
        status_code=status_code,
        retrieved_at=retrieved_at,
        content_type=str(content_type) if content_type is not None else None,
        url=f"{source.scheme}://{source.netloc}{source.path}",
        request_parameters=actual_params,
    )


def _decode_json_slice(
    content: bytes,
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, float | None]]:
    raw_rows = json.loads(content)
    assert isinstance(raw_rows, list)
    deduped: dict[datetime, float | None] = {}
    for entry in raw_rows:
        assert isinstance(entry, dict)
        if entry.get("id") is None:
            continue
        ts = datetime.fromisoformat(str(entry["timestart"]).replace("Z", "+00:00")).replace(tzinfo=None)
        if start <= ts <= end:
            val = entry.get("valor")
            deduped[ts] = None if val is None else float(val)
    return sorted(deduped.items(), key=lambda item: item[0])


def _select_product(station: str, product_id: str) -> rr.Selection:
    selected = rr.find(provider="ar_ina", station=station)
    series_ids = rr.as_frame(selected).filter(pl.col("product_id") == product_id)["series_id"].to_list()
    assert len(series_ids) == 1
    return rr.pick(selected, series_id=series_ids)


class _ExactPublicReplay:
    """Replay genuine retained captures matched strictly by URL path and exact query parameters."""

    def __init__(self, root: Path, captures: tuple[tuple[str, str], ...]) -> None:
        self._root = root
        self._by_key: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[str, str]] = {}
        for group, cap_name in captures:
            _, rcpt = _load_capture(root, group, cap_name)
            parsed = urlsplit(str(rcpt["url"]))
            params = {k: vals[0] for k, vals in parse_qs(parsed.query, keep_blank_values=True).items()}
            key = (f"{parsed.scheme}://{parsed.netloc}{parsed.path}", tuple(sorted(params.items())))
            assert key not in self._by_key, f"Duplicate replay key: {key!r}"
            self._by_key[key] = (group, cap_name)
        self.calls: list[str] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        params = {str(k): str(v) for k, v in (request.params or {}).items() if v is not None}
        key = (request.url, tuple(sorted(params.items())))
        assert key in self._by_key, f"Unmatched public request: {key!r}"
        group, cap_name = self._by_key[key]
        self.calls.append(cap_name)
        return _response_matching_request(self._root, group, cap_name, request, strict_params=True)


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_planned_windows_stop_extensions_cache_reuse_and_runtime_lookups(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    planned_captures = (
        ("retrieval", "a5-obs-3307-var2-dense15m-2d-202401"),
        ("retrieval", "a5-obs-26605-var40-planned-20240101-20240105"),
        ("retrieval", "a5-obs-26605-var40-prerecord-1900-empty"),
        ("retrieval", "a5-obs-24674-var48-planned-20240101-20240102"),
        ("retrieval", "a5-obs-36030-var67-planned-20251006-20251007"),
        ("retrieval", "a5-series-lookup-st8-var40-proc1"),
        ("verification", "a5-obs-857-var4-span1-20230530-20240528"),
        ("verification", "a5-obs-857-var4-span2-20240529-20240607"),
    )
    replay = _ExactPublicReplay(retained_evidence_root, planned_captures)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    # 1. Dense 15-minute (:10-second) stage on station 1701 (series 3307) + offline cache="reuse" + audit_cache.
    sel_1701 = rr.find(provider="ar_ina", station="1701", quantity="stage", statistic="instantaneous")
    assert [item.identity.published_id for item in sel_1701.series] == ["3307"]
    dense_start, dense_end = "2024-01-03T00:00:00", "2024-01-04T00:00:00"
    dense_res = rr.fetch(sel_1701, start=dense_start, end=dense_end, cache="reuse", receipts=True, on_issue="raise")
    assert replay.calls == ["a5-obs-3307-var2-dense15m-2d-202401"]
    assert dense_res.receipts is not None and len(dense_res.receipts.entries) == 1
    raw_3307, _ = _load_capture(retained_evidence_root, "retrieval", "a5-obs-3307-var2-dense15m-2d-202401")
    expected_3307 = _decode_json_slice(raw_3307, datetime.fromisoformat(dense_start), datetime.fromisoformat(dense_end))
    assert dense_res.data.height == len(expected_3307) == 96
    assert dense_res.data.sort("time")["time"].to_list() == [ts for ts, _ in expected_3307]
    assert dense_res.data.sort("time")["value"].to_list() == pytest.approx([val for _, val in expected_3307])
    assert any(ts.second == 10 for ts in dense_res.data["time"].to_list())
    assert dense_res.provenance.license == "Creative Commons Atribución 4.0 Internacional"

    # Repeat sub-window query is served entirely from local store (0 additional HTTP calls).
    sub_start, sub_end = "2024-01-03T06:00:00", "2024-01-03T18:00:00"
    reused_dense = rr.fetch(sel_1701, start=sub_start, end=sub_end, cache="reuse", on_issue="raise")
    assert replay.calls == ["a5-obs-3307-var2-dense15m-2d-202401"]
    expected_sub = _decode_json_slice(raw_3307, datetime.fromisoformat(sub_start), datetime.fromisoformat(sub_end))
    assert reused_dense.data.sort("time")["time"].to_list() == [ts for ts, _ in expected_sub]
    assert reused_dense.data.sort("time")["value"].to_list() == pytest.approx([val for _, val in expected_sub])
    assert rr.cache_status("ar_ina").presence.value == "present"
    assert rr.audit_cache("ar_ina").rows_checked >= len(expected_3307)

    # 2. Daily mean discharge on station 8 (series 26605) + pre-record 1900 EMPTY window.
    sel_8_q = rr.find(provider="ar_ina", station="8", quantity="discharge", frequency="daily", statistic="mean")
    assert [item.identity.published_id for item in sel_8_q.series] == ["26605"]
    q_res = rr.fetch(sel_8_q, start="2024-01-01T00:00:00", end="2024-01-05T00:00:00", cache="reuse", on_issue="raise")
    raw_26605, _ = _load_capture(retained_evidence_root, "retrieval", "a5-obs-26605-var40-planned-20240101-20240105")
    expected_26605 = _decode_json_slice(raw_26605, datetime(2024, 1, 1), datetime(2024, 1, 5))
    assert q_res.data.sort("time")["time"].to_list() == [ts for ts, _ in expected_26605]
    assert q_res.data.sort("time")["value"].to_list() == pytest.approx([val for _, val in expected_26605])

    empty_1900 = rr.fetch(
        sel_8_q, start="1900-01-03T00:00:00", end="1900-01-08T00:00:00", cache="bypass", on_issue="raise"
    )
    assert empty_1900.data.is_empty()
    assert [item.status for item in empty_1900.outcomes] == [OutcomeStatus.EMPTY]

    # 3. Monthly 31d1h stop_extension (series 24674) and weekly 7d1h stop_extension (series 36030).
    sel_8_qmm = rr.find(provider="ar_ina", station="8", quantity="discharge", frequency="monthly", statistic="mean")
    monthly_res = rr.fetch(
        sel_8_qmm, start="2024-01-01T00:00:00", end="2024-01-02T00:00:00", cache="bypass", on_issue="raise"
    )
    raw_24674, _ = _load_capture(retained_evidence_root, "retrieval", "a5-obs-24674-var48-planned-20240101-20240102")
    expected_24674 = _decode_json_slice(raw_24674, datetime(2024, 1, 1), datetime(2024, 1, 2))
    assert len(expected_24674) == 1
    assert monthly_res.data["value"].to_list() == pytest.approx([val for _, val in expected_24674])

    sel_151_hms = _select_product("151", "stage_weekly_mean")
    weekly_res = rr.fetch(
        sel_151_hms, start="2025-10-06T00:00:00", end="2025-10-07T00:00:00", cache="bypass", on_issue="raise"
    )
    raw_36030, _ = _load_capture(retained_evidence_root, "retrieval", "a5-obs-36030-var67-planned-20251006-20251007")
    expected_36030 = _decode_json_slice(raw_36030, datetime(2025, 10, 6), datetime(2025, 10, 7))
    assert len(expected_36030) == 1
    assert weekly_res.data["value"].to_list() == pytest.approx([val for _, val in expected_36030])

    # 4. Multi-span 365-day capped_span (.999999Z microsecond boundary) through public rr.fetch on station 8 (series 857).
    sel_8_qi = rr.find(provider="ar_ina", station="8", quantity="discharge", statistic="instantaneous")
    assert [item.identity.published_id for item in sel_8_qi.series] == ["857"]
    calls_before_span = len(replay.calls)
    span_res = rr.fetch(
        sel_8_qi,
        start="2023-06-01T00:00:00",
        end="2024-06-05T00:00:00",
        cache="bypass",
        receipts=True,
        on_issue="raise",
    )
    assert replay.calls[calls_before_span:] == [
        "a5-obs-857-var4-span1-20230530-20240528",
        "a5-obs-857-var4-span2-20240529-20240607",
    ]
    assert span_res.receipts is not None and len(span_res.receipts.entries) == 2
    span1_bytes, _ = _load_capture(retained_evidence_root, "verification", "a5-obs-857-var4-span1-20230530-20240528")
    span2_bytes, _ = _load_capture(retained_evidence_root, "verification", "a5-obs-857-var4-span2-20240529-20240607")
    combined_raw = json.dumps([*json.loads(span1_bytes), *json.loads(span2_bytes)]).encode("utf-8")
    expected_span = _decode_json_slice(combined_raw, datetime(2023, 6, 1), datetime(2024, 6, 5))
    assert span_res.data.height == len(expected_span) == 375
    assert span_res.data.sort("time")["time"].to_list() == [ts for ts, _ in expected_span]
    assert span_res.data.sort("time")["value"].to_list() == pytest.approx([val for _, val in expected_span])

    # 5. Unwitnessed ("unknown") station-product pairs withhold public routing with EmptySelectionError,
    #    while an explicit uncatalogued variant on a witnessed pair resolves through /obs/puntual/series,
    #    never hits /999999999/observaciones, and records NO_MATCH.
    for unknown_sel in (
        rr.find(provider="ar_ina", station="8", quantity="stage", frequency="hourly", on_issue="ignore"),
        rr.find(
            provider="ar_ina",
            station="1",
            quantity="discharge",
            frequency="monthly",
            statistic="mean",
            variant="24667",
            on_issue="ignore",
        ),
    ):
        assert len(unknown_sel.series) == 0
        with pytest.raises(EmptySelectionError) as exc_info:
            rr.fetch(unknown_sel, start="2024-01-01T00:00:00", end="2024-01-02T00:00:00")
        assert exc_info.value.reason.code == "unresolved_inventory"

    sel_missing_variant = rr.find(
        provider="ar_ina",
        station="8",
        quantity="discharge",
        frequency="daily",
        statistic="mean",
        variant="999999999",
        on_issue="ignore",
    )
    calls_before_lookup = len(replay.calls)
    missing_variant_res = rr.fetch(
        sel_missing_variant,
        start="2024-01-01T00:00:00",
        end="2024-01-05T00:00:00",
        cache="reuse",
        on_issue="ignore",
    )
    assert replay.calls[calls_before_lookup:] == ["a5-series-lookup-st8-var40-proc1"]
    assert not any("999999999" in name for name in replay.calls)
    assert any(item.status is OutcomeStatus.NO_MATCH for item in missing_variant_res.outcomes)


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_all_13_products_strict_params_negative_stage_historical_dst_and_boundary_nulls(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Replay all 13 admitted products with strict_params=True against genuine engine-planned captures.
    thirteen_cases = (
        (
            "retrieval",
            "a5-obs-26605-var40-planned-20240101-20240105",
            "8",
            "discharge_daily_mean",
            "2024-01-01T00:00:00",
            "2024-01-05T00:00:00",
            "m^3/s",
            "m3/s",
        ),
        (
            "verification",
            "a5-obs-857-var4-planned-20240101-20240106",
            "8",
            "discharge_instantaneous",
            "2024-01-01T00:00:00",
            "2024-01-06T00:00:00",
            "m^3/s",
            "m3/s",
        ),
        (
            "retrieval",
            "a5-obs-24674-var48-planned-20240101-20240102",
            "8",
            "discharge_monthly_mean",
            "2024-01-01T00:00:00",
            "2024-01-02T00:00:00",
            "m^3/s",
            "m3/s",
        ),
        (
            "verification",
            "a5-obs-25775-var51-planned-20220101-20220602",
            "8",
            "discharge_monthly_min",
            "2022-01-01T00:00:00",
            "2022-06-02T00:00:00",
            "m^3/s",
            "m3/s",
        ),
        (
            "verification",
            "a5-obs-25869-var52-planned-20220101-20220602",
            "8",
            "discharge_monthly_max",
            "2022-01-01T00:00:00",
            "2022-06-02T00:00:00",
            "m^3/s",
            "m3/s",
        ),
        (
            "verification",
            "a5-obs-26250-var39-planned-20240101-20240105",
            "8",
            "stage_daily_mean",
            "2024-01-01T00:00:00",
            "2024-01-05T00:00:00",
            "m",
            "m",
        ),
        (
            "retrieval",
            "a5-obs-3307-var2-dense15m-2d-202401",
            "1701",
            "stage_instantaneous",
            "2024-01-03T00:00:00",
            "2024-01-04T00:00:00",
            "m",
            "m",
        ),
        (
            "verification",
            "a5-obs-31605-var85-planned-20240101-20240103",
            "52",
            "stage_hourly",
            "2024-01-01T00:00:00",
            "2024-01-03T00:00:00",
            "m",
            "m",
        ),
        (
            "verification",
            "a5-obs-38398-var101-planned-20250101-20250104",
            "2112",
            "stage_4hourly",
            "2025-01-01T00:00:00",
            "2025-01-04T00:00:00",
            "m",
            "m",
        ),
        (
            "retrieval",
            "a5-obs-36030-var67-planned-20251006-20251007",
            "151",
            "stage_weekly_mean",
            "2025-10-06T00:00:00",
            "2025-10-07T00:00:00",
            "m",
            "m",
        ),
        (
            "verification",
            "a5-obs-25486-var33-planned-20240101-20240602",
            "8",
            "stage_monthly_mean",
            "2024-01-01T00:00:00",
            "2024-06-02T00:00:00",
            "m",
            "m",
        ),
        (
            "verification",
            "a5-obs-25587-var49-planned-20220101-20220602",
            "8",
            "stage_monthly_min",
            "2022-01-01T00:00:00",
            "2022-06-02T00:00:00",
            "m",
            "m",
        ),
        (
            "verification",
            "a5-obs-25681-var50-planned-20220101-20220602",
            "8",
            "stage_monthly_max",
            "2022-01-01T00:00:00",
            "2022-06-02T00:00:00",
            "m",
            "m",
        ),
    )

    dst_cases = (
        (
            "verification",
            "a5-obs-26616-var40-planned-dst-2008-spring",
            "19",
            "discharge_daily_mean",
            "2008-10-15T00:00:00",
            "2008-10-25T23:59:59",
        ),
        (
            "verification",
            "a5-obs-26616-var40-planned-dst-2009-fall",
            "19",
            "discharge_daily_mean",
            "2009-03-10T00:00:00",
            "2009-03-20T23:59:59",
        ),
        (
            "verification",
            "a5-obs-24665-var48-planned-dst-2008-2009",
            "19",
            "discharge_monthly_mean",
            "2008-09-01T00:00:00",
            "2009-05-01T23:59:59",
        ),
    )

    grdc_cases = (
        ("a5-obs-st14-var40-grdc3264500-2000", "14", "1999-11-01T00:00:00", "2000-10-29T23:59:59", 363),
        ("a5-obs-st19-var40-grdc3265300-2019-2020", "19", "2019-09-01T00:00:00", "2020-08-31T23:59:59", 366),
        ("a5-obs-st1967-var40-grdc3265070-2019-2020", "1967", "2019-09-01T00:00:00", "2020-08-31T23:59:59", 366),
        ("a5-obs-st1964-var40-grdc3268270-2019-2020", "1964", "2019-09-01T00:00:00", "2020-08-31T23:59:59", 366),
        ("a5-obs-st1978-var40-grdc3268500-2019-2020", "1978", "2019-09-01T00:00:00", "2020-08-31T23:59:59", 366),
        ("a5-obs-st2046-var40-grdc3268900-2019-2020", "2046", "2019-09-01T00:00:00", "2020-08-31T23:59:59", 366),
        ("a5-obs-st2832-var40-grdc3265910-2019-2020", "2832", "2019-09-01T00:00:00", "2020-08-31T23:59:59", 0),
    )

    strict_replay = _ExactPublicReplay(
        retained_evidence_root,
        (
            *((group, cap_name) for group, cap_name, *_ in thirteen_cases),
            *((group, cap_name) for group, cap_name, *_ in dst_cases),
            *(("verification", cap_name) for cap_name, *_ in grdc_cases),
        ),
    )
    monkeypatch.setattr(discovery, "HttpClient", lambda: strict_replay)

    seen_products: set[str] = set()
    for group, cap_name, station, product_id, start_str, end_str, src_unit, unit in thirteen_cases:
        sel = _select_product(station, product_id)
        out = rr.fetch(
            sel,
            start=start_str,
            end=end_str,
            cache="bypass",
            on_issue="raise",
        )
        raw_bytes, _ = _load_capture(retained_evidence_root, group, cap_name)
        expected = _decode_json_slice(
            raw_bytes,
            datetime.fromisoformat(start_str),
            datetime.fromisoformat(end_str),
        )
        ordered = out.data.sort("time")
        assert ordered.height == len(expected) > 0, cap_name
        assert ordered["time"].to_list() == [ts for ts, _ in expected]
        assert ordered["value"].to_list() == pytest.approx([val for _, val in expected])
        assert ordered["source_unit"].unique().to_list() == [src_unit]
        assert ordered["unit"].unique().to_list() == [unit]
        assert ordered["time_zone"].unique().to_list() == ["+00:00"]
        if cap_name == "a5-obs-25587-var49-planned-20220101-20220602":
            # Negative gauge-zero stage (-0.27 m) survives public normalization intact.
            assert min(v for v in ordered["value"].to_list() if v is not None) == pytest.approx(-0.27)
        seen_products.add(product_id)
    assert len(seen_products) == 13

    # 2. Replay pre-2009 Argentina DST 23h/25h captures (02:00Z and 03:00Z civil midnights) with strict_params=True.
    for group, cap_name, station, product_id, start_str, end_str in dst_cases:
        sel = _select_product(station, product_id)
        dst_res = rr.fetch(
            sel,
            start=start_str,
            end=end_str,
            cache="bypass",
            on_issue="raise",
        )
        raw_bytes, _ = _load_capture(retained_evidence_root, group, cap_name)
        expected = _decode_json_slice(
            raw_bytes,
            datetime.fromisoformat(start_str),
            datetime.fromisoformat(end_str),
        )
        assert dst_res.data.sort("time")["time"].to_list() == [ts for ts, _ in expected]
        assert dst_res.data.sort("time")["value"].to_list() == pytest.approx([val for _, val in expected])
        assert {2, 3}.issubset({ts.hour for ts in dst_res.data["time"].to_list()})

    # 3. Replay all 7 GRDC-Caravan benchmark gauges (6 active + 1 pre-commissioning EMPTY) with strict_params=True.
    for cap_name, station, start_str, end_str, expected_count in grdc_cases:
        sel = _select_product(station, "discharge_daily_mean")
        grdc_res = rr.fetch(sel, start=start_str, end=end_str, cache="bypass", on_issue="raise")
        assert grdc_res.data.height == expected_count, cap_name
        if expected_count == 0:
            assert [item.status for item in grdc_res.outcomes] == [OutcomeStatus.EMPTY]
        else:
            raw_bytes, _ = _load_capture(retained_evidence_root, "verification", cap_name)
            expected = _decode_json_slice(
                raw_bytes,
                datetime.fromisoformat(start_str),
                datetime.fromisoformat(end_str),
            )
            assert grdc_res.data.sort("time")["time"].to_list() == [ts for ts, _ in expected]
            assert grdc_res.data.sort("time")["value"].to_list() == pytest.approx([val for _, val in expected])

    # 4. Counterfeit generateRegularSeries boundary nulls (id: null) in skip_nulls=false capture are omitted
    #    with source.synthesized_grid_null info issue, matching skip_nulls=true row-for-row through public rr.fetch.
    sel_52_h1h = _select_product("52", "stage_hourly")
    for cap_name, expect_grid_issue in (
        ("a5-obs-31605-var85-boundary-skipnulls-false", True),
        ("a5-obs-31605-var85-boundary-skipnulls-true", False),
    ):
        monkeypatch.setattr(
            discovery,
            "HttpClient",
            lambda n=cap_name: type(
                "_Boundary",
                (),
                {
                    "send": lambda self, req: _response_matching_request(
                        retained_evidence_root, "retrieval", n, req, strict_params=False
                    )
                },
            )(),
        )
        bound_res = rr.fetch(
            sel_52_h1h,
            start="2024-01-03T06:00:00",
            end="2024-01-03T12:00:00",
            cache="bypass",
            on_issue="raise",
        )
        true_bytes, _ = _load_capture(retained_evidence_root, "retrieval", "a5-obs-31605-var85-boundary-skipnulls-true")
        expected_true = _decode_json_slice(
            true_bytes,
            datetime(2024, 1, 3, 6, 0),
            datetime(2024, 1, 3, 12, 0),
        )
        assert bound_res.data.height == len(expected_true) == 6
        assert bound_res.data.sort("time")["time"].to_list() == [ts for ts, _ in expected_true]
        assert bound_res.data.sort("time")["value"].to_list() == pytest.approx([val for _, val in expected_true])
        grid_issues = [item for item in bound_res.issues if item.code == "source.synthesized_grid_null"]
        if expect_grid_issue:
            assert len(grid_issues) == 1 and grid_issues[0].details == {
                "station_id": "52",
                "product_id": "stage_hourly",
                "series_id": sel_52_h1h.series[0].series_id,
                "count": 6,
            }
        else:
            assert grid_issues == []

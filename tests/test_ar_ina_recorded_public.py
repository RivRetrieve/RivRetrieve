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


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_planned_windows_stop_extensions_cache_reuse_and_runtime_lookups(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    planned_captures = (
        "a5-obs-3307-var2-dense15m-2d-202401",
        "a5-obs-26605-var40-planned-20240101-20240105",
        "a5-obs-26605-var40-prerecord-1900-empty",
        "a5-obs-24674-var48-planned-20240101-20240102",
        "a5-obs-36030-var67-planned-20251006-20251007",
        "a5-series-lookup-st8-var40-proc1",
    )

    class _ExactPublicReplay:
        def __init__(self) -> None:
            self._by_key: dict[tuple[str, tuple[tuple[str, str], ...]], str] = {}
            for cap_name in planned_captures:
                _, rcpt = _load_capture(retained_evidence_root, "retrieval", cap_name)
                parsed = urlsplit(str(rcpt["url"]))
                params = {k: vals[0] for k, vals in parse_qs(parsed.query, keep_blank_values=True).items()}
                key = (f"{parsed.scheme}://{parsed.netloc}{parsed.path}", tuple(sorted(params.items())))
                self._by_key[key] = cap_name
            self.calls: list[str] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            params = {str(k): str(v) for k, v in (request.params or {}).items() if v is not None}
            key = (request.url, tuple(sorted(params.items())))
            assert key in self._by_key, f"Unmatched public request: {key!r}"
            cap_name = self._by_key[key]
            self.calls.append(cap_name)
            return _response_matching_request(retained_evidence_root, "retrieval", cap_name, request)

    replay = _ExactPublicReplay()
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
    assert dense_res.data.height == len(expected_3307) >= 90
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

    # 4. Unwitnessed ("unknown") station-product pairs withhold public routing with EmptySelectionError,
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
def test_public_recorded_all_13_products_negative_stage_historical_dst_and_boundary_nulls(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 1. Replay all 13 admitted products from retained access/ captures through public rr.find/rr.pick/rr.fetch.
    thirteen_cases = (
        ("a5-obs-26605-var40-qmd", "8", "discharge_daily_mean", "2024-01-01", "2024-01-10", "m^3/s", "m3/s"),
        ("a5-obs-857-var4-q", "8", "discharge_instantaneous", "2024-01-01", "2024-01-06", "m^3/s", "m3/s"),
        ("a5-obs-24674-var48-qmm", "8", "discharge_monthly_mean", "2024-01-01", "2024-07-01", "m^3/s", "m3/s"),
        ("a5-obs-25775-var51-qmmin", "8", "discharge_monthly_min", "2022-01-01", "2022-07-01", "m^3/s", "m3/s"),
        ("a5-obs-25869-var52-qmmax", "8", "discharge_monthly_max", "2022-01-01", "2022-07-01", "m^3/s", "m3/s"),
        ("a5-obs-26250-var39-hmd", "8", "stage_daily_mean", "2024-01-01", "2024-01-10", "m", "m"),
        ("a5-obs-8-var2-h", "8", "stage_instantaneous", "2024-01-01", "2024-01-06", "m", "m"),
        ("a5-obs-31605-var85-h1h", "52", "stage_hourly", "2024-01-01", "2024-01-03", "m", "m"),
        ("a5-obs-38398-var101-hm4h", "2112", "stage_4hourly", "2025-01-01", "2025-01-04", "m", "m"),
        ("a5-obs-35313-var67-hms", "9", "stage_weekly_mean", "2024-01-01", "2024-03-01", "m", "m"),
        ("a5-obs-25486-var33-hmm", "8", "stage_monthly_mean", "2024-01-01", "2024-07-01", "m", "m"),
        ("a5-obs-25587-var49-hmmin", "8", "stage_monthly_min", "2022-01-01", "2022-07-01", "m", "m"),
        ("a5-obs-25681-var50-hmmax", "8", "stage_monthly_max", "2022-01-01", "2022-07-01", "m", "m"),
    )
    seen_products: set[str] = set()
    for cap_name, station, product_id, start_str, end_str, src_unit, unit in thirteen_cases:
        monkeypatch.setattr(
            discovery,
            "HttpClient",
            lambda n=cap_name: type(
                "_SingleAccess",
                (),
                {
                    "send": lambda self, req: _response_matching_request(
                        retained_evidence_root, "access", n, req, strict_params=False
                    )
                },
            )(),
        )
        sel = _select_product(station, product_id)
        out = rr.fetch(
            sel,
            start=f"{start_str}T00:00:00",
            end=f"{end_str}T23:59:59",
            cache="bypass",
            on_issue="raise",
        )
        raw_bytes, _ = _load_capture(retained_evidence_root, "access", cap_name)
        expected = _decode_json_slice(
            raw_bytes,
            datetime.fromisoformat(f"{start_str}T00:00:00"),
            datetime.fromisoformat(f"{end_str}T23:59:59"),
        )
        ordered = out.data.sort("time")
        assert ordered.height == len(expected) > 0, cap_name
        assert ordered["time"].to_list() == [ts for ts, _ in expected]
        assert ordered["value"].to_list() == pytest.approx([val for _, val in expected])
        assert ordered["source_unit"].unique().to_list() == [src_unit]
        assert ordered["unit"].unique().to_list() == [unit]
        assert ordered["time_zone"].unique().to_list() == ["+00:00"]
        if cap_name == "a5-obs-25587-var49-hmmin":
            # Negative gauge-zero stage (-0.27 m) survives public normalization intact.
            assert min(v for v in ordered["value"].to_list() if v is not None) == pytest.approx(-0.27)
        seen_products.add(product_id)
    assert len(seen_products) == 13

    # 2. Replay pre-2009 Argentina DST 23h/25h captures (02:00Z and 03:00Z civil midnights) through rr.fetch.
    dst_cases = (
        ("a5-obs-26616-var40-qmd-dst-2008-spring", "19", "discharge_daily_mean", "2008-10-15", "2008-10-25"),
        ("a5-obs-26616-var40-qmd-dst-2009-fall", "19", "discharge_daily_mean", "2009-03-10", "2009-03-20"),
        ("a5-obs-35888-var40-qmd-bdhi-dst-2008", "2047", "discharge_daily_mean", "2008-10-15", "2008-10-25"),
        ("a5-obs-24665-var48-qmm-dst-2008-2009", "19", "discharge_monthly_mean", "2008-09-01", "2009-05-01"),
    )
    for cap_name, station, product_id, start_str, end_str in dst_cases:
        monkeypatch.setattr(
            discovery,
            "HttpClient",
            lambda n=cap_name: type(
                "_SingleDst",
                (),
                {
                    "send": lambda self, req: _response_matching_request(
                        retained_evidence_root, "series", n, req, strict_params=False
                    )
                },
            )(),
        )
        sel = _select_product(station, product_id)
        dst_res = rr.fetch(
            sel,
            start=f"{start_str}T00:00:00",
            end=f"{end_str}T23:59:59",
            cache="bypass",
            on_issue="raise",
        )
        raw_bytes, _ = _load_capture(retained_evidence_root, "series", cap_name)
        expected = _decode_json_slice(
            raw_bytes,
            datetime.fromisoformat(f"{start_str}T00:00:00"),
            datetime.fromisoformat(f"{end_str}T23:59:59"),
        )
        assert dst_res.data.sort("time")["time"].to_list() == [ts for ts, _ in expected]
        assert dst_res.data.sort("time")["value"].to_list() == pytest.approx([val for _, val in expected])
        assert {2, 3}.issubset({ts.hour for ts in dst_res.data["time"].to_list()})

    # 3. Counterfeit generateRegularSeries boundary nulls (id: null) in skip_nulls=false capture are omitted
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

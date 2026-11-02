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

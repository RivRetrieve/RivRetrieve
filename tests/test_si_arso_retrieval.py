"""Verify Slovenia ARSO request planning and CSV/HTML response parsing across all 3 streams."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal import primitives, window_planning
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.providers.si_arso import config, fetch, parse, series
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse
from tests.test_boundary_probe_harness import _make_fetch_window

WE = window_planning.WindowEndpoint
RW = window_planning.RenderedWindow


class _MemoryTransport:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.requests: list[TransportRequest] = []

    def send(self, request: TransportRequest) -> TransportResponse:
        self.requests.append(request)
        return TransportResponse(
            content=self._body,
            status_code=200,
            retrieved_at=datetime(2026, 11, 23, 22, 0, tzinfo=UTC),
            content_type="text/plain",
            url=request.url,
            request_parameters={},
        )


def test_si_arso_archive_daily_parse_ragged_empty_and_cm_to_m_stage() -> None:
    body = (
        "Datum;vodostaj (cm);pretok (m3/s);temp. vode (°C)\n01.01.2024\n02.01.2024;-5;12.5;4.2\n03.01.2024;125;;\n"
    ).encode()
    tr = _MemoryTransport(body)
    fw = _make_fetch_window(WE(2024, 1, 1, 0, 0, 0, 0), WE(2024, 1, 3, 0, 0, 0, 0))
    rw = RW("2024-01-01", "2024-01-03")
    acq = fetch.fetch(
        ("1060",),
        (
            primitives.ProductId("archive_stage_daily"),
            primitives.ProductId("archive_discharge_daily"),
            primitives.ProductId("archive_temperature_daily"),
        ),
        {
            primitives.ProductId("archive_stage_daily"): (rw,),
            primitives.ProductId("archive_discharge_daily"): (rw,),
            primitives.ProductId("archive_temperature_daily"): (rw,),
        },
        fw,
        config._CONFIG,
        tr,
        known_series=(
            series.source_series("1060", "archive_stage_daily"),
            series.source_series("1060", "archive_discharge_daily"),
            series.source_series("1060", "archive_temperature_daily"),
        ),
    )
    assert len(tr.requests) == 1
    assert "p_vodotok" not in tr.requests[0].params
    parsed = parse.parse(acq.value[0], config._CONFIG)
    stage_rows = parsed.rows.filter(parsed.rows["product_id"] == "archive_stage_daily").sort("time")
    assert stage_rows["value"].to_list() == pytest.approx([-5.0, 125.0])
    assert stage_rows["source_unit"].to_list() == ["cm", "cm"]
    assert (
        parsed.annotations.series_tables["si_arso.series"].rows["data_status"].to_list() == ["Verificirani podatki"] * 3
    )


def test_si_arso_archive_monthly_extremes_and_blank_discharge() -> None:
    body = (
        b"Leto;Mesec;Q_MIN_datum;Q_MIN_vrednost;Q_MAX_datum;Q_MAX_vrednost\n"
        b"2024;1\n"
        b"2024;2;15.02.2024 06:30;42.1;28.02.2024 18:00;310.4\n"
    )
    tr = _MemoryTransport(body)
    fw = _make_fetch_window(WE(2024, 1, 1, 0, 0, 0, 0), WE(2024, 2, 29, 0, 0, 0, 0))
    rw = RW("2024-01-01", "2024-02-29")
    acq = fetch.fetch(
        ("1060",),
        (primitives.ProductId("archive_discharge_monthly_max"),),
        {primitives.ProductId("archive_discharge_monthly_max"): (rw,)},
        fw,
        config._CONFIG,
        tr,
        known_series=(series.source_series("1060", "archive_discharge_monthly_max"),),
    )
    parsed = parse.parse(acq.value[0], config._CONFIG)
    assert parsed.rows.height == 1
    assert parsed.rows["value"].to_list() == pytest.approx([310.4])
    assert parsed.rows["time"].to_list() == [datetime(2024, 2, 28, 18, 0)]


def test_si_arso_amp_dash_outage_and_float_underscore_rejection() -> None:
    html = (
        '<table class="podatki"><thead><tr>'
        "<th>Datum</th><th>Vodostaj [cm]</th><th>Pretok [m³/s]</th>"
        "</tr></thead><tbody>"
        "<tr><td>23.11.2026 10:00</td><td> - </td><td> - </td></tr>"
        "<tr><td>23.11.2026 09:00</td><td>110.0</td><td>54.2</td></tr>"
        "</tbody></table>"
    ).encode()
    tr = _MemoryTransport(html)
    fw = _make_fetch_window(WE(2026, 11, 22, 0, 0, 0, 0), WE(2026, 11, 23, 23, 59, 59, 0))
    rw = RW("2026-11-22", "2026-11-23")
    acq = fetch.fetch(
        ("1060",),
        (primitives.ProductId("operational_discharge_hourly"),),
        {primitives.ProductId("operational_discharge_hourly"): (rw,)},
        fw,
        config._CONFIG,
        tr,
        known_series=(series.source_series("1060", "operational_discharge_hourly"),),
    )
    parsed = parse.parse(acq.value[0], config._CONFIG)
    assert parsed.rows.height == 1
    assert parsed.rows["value"].to_list() == pytest.approx([54.2])
    assert parsed.annotations.series_tables["si_arso.series"].rows["data_status"].to_list() == ["Začasni podatki"]

    bad_csv = b"Datum;pretok (m3/s)\n01.01.2024;1_000.0\n"
    tr_bad = _MemoryTransport(bad_csv)
    fw_bad = _make_fetch_window(WE(2024, 1, 1, 0, 0, 0, 0), WE(2024, 1, 1, 0, 0, 0, 0))
    rw_bad = RW("2024-01-01", "2024-01-01")
    acq_bad = fetch.fetch(
        ("1060",),
        (primitives.ProductId("archive_discharge_daily"),),
        {primitives.ProductId("archive_discharge_daily"): (rw_bad,)},
        fw_bad,
        config._CONFIG,
        tr_bad,
        known_series=(series.source_series("1060", "archive_discharge_daily"),),
    )
    bad_parsed = parse.parse(cast("parse.Payload", acq_bad.value[0]), config._CONFIG)
    assert bad_parsed.rows.height == 0
    assert len(bad_parsed.outcomes) == 1
    assert bad_parsed.outcomes[0].status.value == "failed"
    assert "1_000.0" in bad_parsed.outcomes[0].reason
    assert bad_parsed.issues[0].code == "source.unsupported_structure"
    with pytest.raises(UnsupportedSourceStructureError):
        parse._parse_finite_float("1_000.0", 2, "test")


@pytest.mark.usefixtures("reuse_packaged_catalogues")
def test_si_arso_unclipped_cache_reuse_and_unresolved_without_warnings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    # Full-year 2024 oddo CSV + multi-decade 1950..2024 eks CSV + amp t_1 HTML (plus all-dash outage on temp).
    oddo_2024 = (
        "Datum;vodostaj (cm);pretok (m3/s);temp. vode (°C)\n"
        "01.01.2024;10;12.0;3.1\n"
        "05.05.2024;-9;25.4;8.5\n"
        "05.08.2024;0;0.0;19.2\n"
        "31.12.2024;5;10.0;2.0\n"
    ).encode()
    oddo_empty_2025 = b"Datum\n01.01.2025\n02.01.2025\n"
    eks_multi = (
        b"Leto;Mesec;Q_MAX_datum;Q_MAX_vrednost\n"
        b"1950;5;14.05.1950 12:00;111.1\n"
        b"1950;8;20.08.1950 09:00;95.0\n"
        b"2024;8;12.08.2024 06:15;222.2\n"
    )
    amp_html = (
        '<table class="podatki"><thead><tr>'
        "<th>Datum</th><th>Vodostaj [cm]</th><th>Pretok [m³/s]</th><th>Temperatura vode [°C]</th>"
        "</tr></thead><tbody>"
        "<tr><td>23.11.2026 12:00</td><td> - </td><td>18.5</td><td> - </td></tr>"
        "<tr><td>23.11.2026 06:00</td><td>95</td><td>16.2</td><td> - </td></tr>"
        "<tr><td>23.11.2026 00:00</td><td>90</td><td>14.0</td><td> - </td></tr>"
        "</tbody></table>"
    ).encode()

    amp_html_snap2 = (
        b'<table class="podatki"><thead><tr>'
        b"<th>Datum</th><th>Vodostaj [cm]</th><th>Pretok [m\xc2\xb3/s]</th><th>Temperatura vode [\xc2\xb0C]</th>"
        b"</tr></thead><tbody>"
        b"<tr><td>23.11.2026 18:00</td><td>105</td><td>20.0</td><td> - </td></tr>"
        b"<tr><td>23.11.2026 06:00</td><td>96</td><td>16.8</td><td> - </td></tr>"
        b"</tbody></table>"
    )

    class _CountingTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str]]] = []
            self.amp_body = amp_html

        def send(self, request: TransportRequest) -> TransportResponse:
            params = {str(k): str(v) for k, v in (request.params or {}).items()}
            self.calls.append((request.url, params))
            if params.get("b_oddo_CSV") == "1":
                body = oddo_empty_2025 if params.get("p_od_leto") == "2025" else oddo_2024
                return TransportResponse(
                    body, 200, datetime(2026, 11, 24, 0, 0, tzinfo=UTC), "text/csv", request.url, params
                )
            if params.get("b_eks_CSV") == "1":
                return TransportResponse(
                    eks_multi, 200, datetime(2026, 11, 24, 0, 0, tzinfo=UTC), "text/csv", request.url, params
                )
            if request.url.endswith("/H1060_t_1.html"):
                return TransportResponse(
                    self.amp_body, 200, datetime(2026, 11, 24, 0, 0, tzinfo=UTC), "text/html", request.url, params
                )
            raise AssertionError(f"Unexpected request: {request.url} {params}")

    tr = _CountingTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: tr)

    # 0. Verify parse.parse() itself never clips parsed.rows or covered_window for sub-windows (even empty tick gaps).
    rw_may = RW("2024-05-01", "2024-05-07")
    fw_may = _make_fetch_window(WE(2024, 5, 1, 0, 0, 0, 0), WE(2024, 5, 7, 23, 59, 59, 999999))
    acq_may = fetch.fetch(
        ("1060",),
        (primitives.ProductId("archive_discharge_daily"),),
        {primitives.ProductId("archive_discharge_daily"): (rw_may,)},
        fw_may,
        config._CONFIG,
        tr,
        known_series=(series.source_series("1060", "archive_discharge_daily"),),
    )
    parsed_may = parse.parse(acq_may.value[0], config._CONFIG)
    assert parsed_may.issues == ()
    assert parsed_may.rows.height == 4
    assert parsed_may.outcomes[0].status is OutcomeStatus.SUCCESS
    assert parsed_may.outcomes[0].window.start == datetime(2024, 1, 1, 0, 0)
    assert parsed_may.outcomes[0].window.end == datetime(2024, 12, 31, 23, 59, 59, 999999)

    fw_amp_gap = _make_fetch_window(WE(2026, 11, 23, 1, 0, 0, 0), WE(2026, 11, 23, 5, 0, 0, 0))
    acq_amp_gap = fetch.fetch(
        ("1060",),
        (primitives.ProductId("operational_discharge_10min"),),
        {primitives.ProductId("operational_discharge_10min"): ()},
        fw_amp_gap,
        config._CONFIG,
        tr,
        known_series=(series.source_series("1060", "operational_discharge_10min"),),
    )
    parsed_amp_gap = parse.parse(acq_amp_gap.value[0], config._CONFIG)
    assert parsed_amp_gap.issues == ()
    assert parsed_amp_gap.rows.height == 3
    assert parsed_amp_gap.outcomes[0].status is OutcomeStatus.SUCCESS
    assert parsed_amp_gap.outcomes[0].coverage == "observations"
    assert len(parsed_amp_gap.outcomes[0].observation_keys) == 3
    assert parsed_amp_gap.outcomes[0].window.start == datetime(2026, 11, 23, 0, 0)
    assert parsed_amp_gap.outcomes[0].window.end == datetime(2026, 11, 23, 12, 0)
    tr.calls.clear()

    # 1. Archive daily: 2024-01-01..2026-11-24 caches all of 2024 + reports UNRESOLVED (no warning) for 2025..2026;
    #    subsequent sub-window fetches in May & August make 0 HTTP calls!
    q_daily = rr.find(provider="si_arso", station="1060", quantity="discharge", frequency="P1D")
    span_res = rr.fetch(q_daily, start="2024-01-01", end="2026-11-24", cache="reuse", on_issue="raise")
    assert len(tr.calls) == 1
    assert span_res.issues == ()
    assert span_res.data.height == 4
    assert {o.status for o in span_res.outcomes} == {OutcomeStatus.SUCCESS, OutcomeStatus.UNRESOLVED}

    may_res = rr.fetch(q_daily, start="2024-05-01", end="2024-05-07", cache="reuse", on_issue="raise")
    aug_res = rr.fetch(q_daily, start="2024-08-01", end="2024-08-07", cache="reuse", on_issue="raise")
    assert len(tr.calls) == 1
    assert may_res.issues == ()
    assert aug_res.issues == ()
    assert may_res.data["value"].to_list() == pytest.approx([25.4])
    assert aug_res.data["value"].to_list() == pytest.approx([0.0])

    # Empty post-2024 Datum-only response resolves to UNRESOLVED with issues=().
    post_only = rr.fetch(q_daily, start="2025-01-01", end="2026-01-01", cache="bypass", on_issue="raise")
    assert post_only.issues == ()
    assert post_only.data.is_empty()
    assert [o.status for o in post_only.outcomes] == [OutcomeStatus.UNRESOLVED]

    # 2. Archive monthly extremes: multi-decade fetch caches 1950..2024 -> follow-up 1950-05 & 2024-08 issue 0 HTTP calls.
    calls_before_eks = len(tr.calls)
    q_max = rr.find(provider="si_arso", station="1060", quantity="discharge", frequency="P1M", statistic="max")
    eks_first = rr.fetch(q_max, start="1950-01-01", end="2024-12-31", cache="reuse", on_issue="raise")
    assert len(tr.calls) == calls_before_eks + 1
    assert eks_first.data.height == 3
    eks_may = rr.fetch(q_max, start="1950-05-01", end="1950-05-31", cache="reuse", on_issue="raise")
    eks_aug = rr.fetch(q_max, start="2024-08-01", end="2024-08-31", cache="reuse", on_issue="raise")
    assert len(tr.calls) == calls_before_eks + 1
    assert eks_may.data["value"].to_list() == pytest.approx([111.1])
    assert eks_aug.data["value"].to_list() == pytest.approx([222.2])

    # 3. Operational amp/: rolling buffer accumulates aged-out 00:00, updates overlapping 06:00, and adds new 18:00!
    q_10m = rr.pick(rr.find(provider="si_arso", station="1060", quantity="discharge"), variant="operational_10min")
    amp_full = rr.fetch(q_10m, start="2026-11-23T00:00:00", end="2026-11-23T18:00:00", cache="reuse", on_issue="raise")
    assert amp_full.issues == ()
    assert amp_full.data.sort("time")["value"].to_list() == pytest.approx([14.0, 16.2, 18.5])

    tr.amp_body = amp_html_snap2
    amp_accum = rr.fetch(q_10m, start="2026-11-23T00:00:00", end="2026-11-23T18:00:00", cache="reuse", on_issue="raise")
    assert amp_accum.issues == ()
    assert amp_accum.data.sort("time")["value"].to_list() == pytest.approx([14.0, 16.8, 18.5, 20.0])

    # Extending before/after amp table span returns UNRESOLVED outside table span with issues=().
    amp_ext = rr.fetch(q_10m, start="2026-11-20T00:00:00", end="2026-11-24T12:00:00", cache="bypass", on_issue="raise")
    assert amp_ext.issues == ()
    assert {o.status for o in amp_ext.outcomes} == {OutcomeStatus.SUCCESS, OutcomeStatus.UNRESOLVED}

    # All-dash rolling amp column (temperature here) produces UNRESOLVED with issues=().
    t_10m = rr.pick(rr.find(provider="si_arso", station="1060", quantity="temperature"), variant="operational_10min")
    t_dash = rr.fetch(t_10m, start="2026-11-23T00:00:00", end="2026-11-23T12:00:00", cache="bypass", on_issue="raise")
    assert t_dash.issues == ()
    assert t_dash.data.is_empty()
    assert [o.status for o in t_dash.outcomes] == [OutcomeStatus.UNRESOLVED]

    audit = rr.audit_cache("si_arso")
    assert audit.rows_checked >= 4 + 3 + 3


def _make_si_arso_amp_html(
    title: str,
    columns: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    *,
    footer: str = "Vir: ARSO - Začasni podatki",
) -> bytes:
    header_cells = "".join(f"<th>{col}</th>" for col in ("Datum", *columns))
    body_rows = "".join(f"<tr>{''.join(f'<td>{cell}</td>' for cell in row)}</tr>" for row in rows)
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
        f"<h1>{title}</h1>"
        f'<table class="podatki"><thead><tr>{header_cells}</tr></thead>'
        f"<tbody>{body_rows}</tbody></table>"
        f"<p>{footer}</p></body></html>"
    ).encode()


def test_si_arso_shared_parse_provider_single_pass_and_receipt_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import polars.testing as pl_testing

    from rivretrieve._internal import driver as driver_module
    from rivretrieve._internal.coverage import RequestedInterval
    from rivretrieve._internal.driver import SharedParseProvider
    from rivretrieve._internal.engine import (
        InterpretedPayload,
        SourceAcquisition,
        WindowEndpoint,
        narrow_payload_for_pair,
    )
    from rivretrieve._internal.observations import ReceiptAuthorship
    from rivretrieve._internal.providers.si_arso.declaration import declaration
    from rivretrieve._internal.source_series import SeriesScope, SeriesWindow
    from rivretrieve._internal.window_planning import plan_windows

    assert isinstance(declaration.observations.stages, SharedParseProvider)

    oddo_body = (
        "Datum;vodostaj (cm);pretok (m3/s);temp. vode (°C)\r\n"
        "01.01.2024;142;223.499;4.4\r\n"
        "02.01.2024;138;213.818;4.6\r\n"
    ).encode()
    eks_body = (
        b"Leto;Mesec;H_MIN_datum;H_MIN_vrednost;H_MAX_datum;H_MAX_vrednost;"
        b"Q_MIN_datum;Q_MIN_vrednost;Q_MAX_datum;Q_MAX_vrednost;"
        b"Tv_MIN_datum;Tv_MIN_vrednost;Tv_MAX_datum;Tv_MAX_vrednost\r\n"
        b"2024;1;21.01.2024 16:49;86;07.01.2024 15:13;172;"
        b"21.01.2024 16:49;95.947;07.01.2024 15:13;292.108;"
        b"21.01.2024 08:30;1.9;07.01.2024 14:50;5.5\r\n"
        b"2024;2;02.02.2024 15:36;83;12.02.2024 06:37;127;"
        b"02.02.2024 15:36;89.984;12.02.2024 06:37;188.552;"
        b"01.02.2024 04:10;2.9;29.02.2024 16:30;8.2\r\n"
    )
    amp_body = _make_si_arso_amp_html(
        "Postaja Gornja Radgona I - Mura",
        ("Vodostaj [cm]", "Pretok [m³/s]", "Temperatura vode [°C]"),
        (
            ("23.11.2026 10:10", "125", "180.5", "6.2"),
            ("23.11.2026 10:00", "124", "179.0", "6.1"),
        ),
    )

    requests: list[TransportRequest] = []

    class _SharedTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            requests.append(request)
            params = request.params or {}
            if "b_oddo_CSV" in params:
                body, ctype = oddo_body, "text/csv; charset=utf-8"
            elif "b_eks_CSV" in params:
                body, ctype = eks_body, "text/csv; charset=utf-8"
            else:
                body, ctype = amp_body, "text/html; charset=utf-8"
            return TransportResponse(
                content=body,
                status_code=200,
                retrieved_at=datetime(2026, 11, 23, 10, 20, tzinfo=UTC),
                content_type=ctype,
                url=request.url,
                request_parameters=params,
            )

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "_credentialed_transport", lambda provider_id, values: _SharedTransport())

    daily_counts = {"n": 0}
    eks_counts = {"n": 0}
    amp_counts = {"n": 0}
    orig_daily = parse._parse_archive_daily
    orig_eks = parse._parse_archive_monthly_extremes
    orig_amp = parse._parse_amp

    def _spy_daily(*args: object, **kwargs: object) -> object:
        daily_counts["n"] += 1
        return orig_daily(*args, **kwargs)  # type: ignore[arg-type]

    def _spy_eks(*args: object, **kwargs: object) -> object:
        eks_counts["n"] += 1
        return orig_eks(*args, **kwargs)  # type: ignore[arg-type]

    def _spy_amp(*args: object, **kwargs: object) -> object:
        amp_counts["n"] += 1
        return orig_amp(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(parse, "_parse_archive_daily", _spy_daily)
    monkeypatch.setattr(parse, "_parse_archive_monthly_extremes", _spy_eks)
    monkeypatch.setattr(parse, "_parse_amp", _spy_amp)

    # 1. 3-product archive_daily (oddo) decoded once; ReceiptMode.OMIT vs INCLUDE parity.
    sel_oddo = rr.find(provider="si_arso", station="1060", frequency="P1D")
    assert len(rr.as_frame(sel_oddo)) == 3
    res_omit = rr.fetch(
        sel_oddo, start="2024-01-01", end="2024-01-02", receipts=False, cache="bypass", on_issue="raise"
    )
    assert daily_counts["n"] == 1
    assert res_omit.data.height == 6
    assert [o.status for o in res_omit.outcomes] == [OutcomeStatus.SUCCESS] * 3
    assert res_omit.receipts.entries == ()

    res_include = rr.fetch(
        sel_oddo, start="2024-01-01", end="2024-01-02", receipts=True, cache="bypass", on_issue="raise"
    )
    assert daily_counts["n"] == 2
    pl_testing.assert_frame_equal(res_omit.data, res_include.data)
    assert [o.status for o in res_include.outcomes] == [OutcomeStatus.SUCCESS] * 3
    assert len(res_include.receipts.entries) == 1
    assert res_include.receipts.entries[0].authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    assert res_include.receipts.entries[0].content == oddo_body

    # 2. 6-product archive_monthly_extremes (eks) decoded once (never 6x).
    sel_eks = rr.find(provider="si_arso", station="1060", frequency="P1M")
    assert len(rr.as_frame(sel_eks)) == 6
    res_eks = rr.fetch(sel_eks, start="2024-01-01", end="2024-02-29", cache="bypass", on_issue="raise")
    assert eks_counts["n"] == 1
    assert res_eks.data.height == 12
    assert [o.status for o in res_eks.outcomes] == [OutcomeStatus.SUCCESS] * 6

    # 3. 3-product operational amp (t_1) decoded once (never 3x).
    sel_amp = rr.pick(rr.find(provider="si_arso", station="1060"), variant="operational_10min")
    assert len(rr.as_frame(sel_amp)) == 3
    res_amp = rr.fetch(
        sel_amp,
        start="2026-11-23T10:00:00",
        end="2026-11-23T10:10:00",
        cache="bypass",
        on_issue="raise",
    )
    assert amp_counts["n"] == 1
    assert res_amp.data.height == 6
    assert [o.status for o in res_amp.outcomes] == [OutcomeStatus.SUCCESS] * 3

    # 4. Driver _acquire_group strips shared payload bytes when retain_bytes=False and keeps them when True.
    oddo_prods = tuple(
        primitives.ProductId(p) for p in ("archive_discharge_daily", "archive_stage_daily", "archive_temperature_daily")
    )
    fw = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1, 0, 0)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 2, 23, 59, 59)),
    )
    rendered = {prod: window_planning.plan_windows(fw, config._WINDOWS.products[prod]) for prod in oddo_prods}
    acq_scope = SeriesScope(
        provider_ids=("si_arso",),
        station_ids=("1060",),
        product_ids=tuple(str(prod) for prod in oddo_prods),
    )
    acq = fetch.fetch(
        ("1060",),
        oddo_prods,
        rendered,
        fw,
        config._CONFIG,
        _SharedTransport(),
        scope=acq_scope,
    )
    shared_payload = acq.value[0]
    pair_payloads = {("1060", prod): narrow_payload_for_pair(shared_payload, "1060", prod) for prod in oddo_prods}
    grouped = parse.parse_group(shared_payload, pair_payloads, config._CONFIG)
    interps = tuple(InterpretedPayload.from_payload(pair_payloads[k], grouped[k]) for k in pair_payloads)
    plans = tuple(
        driver_module._PairRetrieval(
            station="1060",
            product=prod,
            scope=SeriesScope(provider_ids=("si_arso",), station_ids=("1060",), product_ids=(str(prod),)),
            series=(),
            interval=RequestedInterval(datetime(2024, 1, 1), datetime(2024, 1, 2, 23, 59, 59)),
            window=SeriesWindow(start=datetime(2024, 1, 1), end=datetime(2024, 1, 2, 23, 59, 59)),
            reuse=None,
            fetch_window=fw,
            rendered=plan_windows(fw, config._WINDOWS.products[prod]),
        )
        for prod in oddo_prods
    )
    acq_with_interps = SourceAcquisition(value=(shared_payload,), interpretations=interps)
    slot_omit = driver_module._acquire_group(acq_with_interps, plans, retain_bytes=False)
    slot_include = driver_module._acquire_group(acq_with_interps, plans, retain_bytes=True)
    assert slot_omit.payload_slots[0] is not None and slot_omit.payload_slots[0].content == b""
    assert slot_include.payload_slots[0] is not None and slot_include.payload_slots[0].content == oddo_body


def test_si_arso_shared_per_column_failure_isolation_and_shared_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bodies: dict[str, bytes] = {}

    class _DispatchTransport:
        def send(self, request: TransportRequest) -> TransportResponse:
            params = request.params or {}
            if "b_oddo_CSV" in params:
                body, ctype = bodies["oddo"], "text/csv; charset=utf-8"
            elif "b_eks_CSV" in params:
                body, ctype = bodies["eks"], "text/csv; charset=utf-8"
            else:
                body, ctype = bodies["amp"], "text/html; charset=utf-8"
            return TransportResponse(
                content=body,
                status_code=200,
                retrieved_at=datetime(2026, 11, 23, 10, 20, tzinfo=UTC),
                content_type=ctype,
                url=request.url,
                request_parameters=params,
            )

    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "_credentialed_transport", lambda provider_id, values: _DispatchTransport())

    # 1. oddo: bad float in temp. vode (°C) isolates failure to archive_temperature_daily only.
    bodies["oddo"] = (
        "Datum;vodostaj (cm);pretok (m3/s);temp. vode (°C)\r\n"
        "01.01.2024;142;223.499;bad-temp\r\n"
        "02.01.2024;138;213.818;4.6\r\n"
    ).encode()
    sel_oddo = rr.find(provider="si_arso", station="1060", frequency="P1D")
    with pytest.warns(RuntimeWarning, match="non-numeric value"):
        res_oddo = rr.fetch(sel_oddo, start="2024-01-01", end="2024-01-02", cache="bypass", on_issue="warn")
    oddo_status = {o.product_id: o.status for o in res_oddo.outcomes}
    assert oddo_status == {
        "archive_discharge_daily": OutcomeStatus.SUCCESS,
        "archive_stage_daily": OutcomeStatus.SUCCESS,
        "archive_temperature_daily": OutcomeStatus.FAILED,
    }
    assert sorted(res_oddo.data["product_id"].unique().to_list()) == [
        "archive_discharge_daily",
        "archive_stage_daily",
    ]
    assert res_oddo.data.height == 4
    assert [i.code for i in res_oddo.issues] == ["source.unsupported_structure"]

    # 2. eks: unpaired datum/value in Tv_MIN isolates failure to archive_temperature_monthly_min only.
    bodies["eks"] = (
        b"Leto;Mesec;H_MIN_datum;H_MIN_vrednost;H_MAX_datum;H_MAX_vrednost;"
        b"Q_MIN_datum;Q_MIN_vrednost;Q_MAX_datum;Q_MAX_vrednost;"
        b"Tv_MIN_datum;Tv_MIN_vrednost;Tv_MAX_datum;Tv_MAX_vrednost\r\n"
        b"2024;1;21.01.2024 16:49;86;07.01.2024 15:13;172;"
        b"21.01.2024 16:49;95.947;07.01.2024 15:13;292.108;"
        b"21.01.2024 08:30;;07.01.2024 14:50;5.5\r\n"
        b"2024;2;02.02.2024 15:36;83;12.02.2024 06:37;127;"
        b"02.02.2024 15:36;89.984;12.02.2024 06:37;188.552;"
        b"01.02.2024 04:10;2.9;29.02.2024 16:30;8.2\r\n"
    )
    sel_eks = rr.find(provider="si_arso", station="1060", frequency="P1M")
    with pytest.warns(RuntimeWarning, match="unpaired datum/value"):
        res_eks = rr.fetch(sel_eks, start="2024-01-01", end="2024-02-29", cache="bypass", on_issue="warn")
    eks_status = {o.product_id: o.status for o in res_eks.outcomes}
    assert eks_status == {
        "archive_discharge_monthly_min": OutcomeStatus.SUCCESS,
        "archive_discharge_monthly_max": OutcomeStatus.SUCCESS,
        "archive_stage_monthly_min": OutcomeStatus.SUCCESS,
        "archive_stage_monthly_max": OutcomeStatus.SUCCESS,
        "archive_temperature_monthly_min": OutcomeStatus.FAILED,
        "archive_temperature_monthly_max": OutcomeStatus.SUCCESS,
    }
    assert res_eks.data.height == 10
    assert [i.code for i in res_eks.issues] == ["source.unsupported_structure"]

    # 3. amp: conflicting values at duplicate timestamp in Temperatura vode [°C] isolates failure to temperature.
    bodies["amp"] = _make_si_arso_amp_html(
        "Postaja Gornja Radgona I - Mura",
        ("Vodostaj [cm]", "Pretok [m³/s]", "Temperatura vode [°C]"),
        (
            ("23.11.2026 10:10", "125", "180.5", "6.2"),
            ("23.11.2026 10:10", "125", "180.5", "6.9"),
            ("23.11.2026 10:00", "124", "179.0", "6.1"),
        ),
    )
    sel_amp = rr.pick(rr.find(provider="si_arso", station="1060"), variant="operational_10min")
    with pytest.warns(RuntimeWarning, match="conflicting values"):
        res_amp = rr.fetch(
            sel_amp, start="2026-11-23T10:00:00", end="2026-11-23T10:10:00", cache="bypass", on_issue="warn"
        )
    amp_status = {o.product_id: o.status for o in res_amp.outcomes}
    assert amp_status == {
        "operational_discharge_10min": OutcomeStatus.SUCCESS,
        "operational_stage_10min": OutcomeStatus.SUCCESS,
        "operational_temperature_10min": OutcomeStatus.FAILED,
    }
    assert res_amp.data.height == 4
    assert [i.code for i in res_amp.issues] == ["source.unsupported_structure"]

    # 4. Shared structural / row-date failure fails ALL requested pairs.
    bodies["oddo"] = ("Datum;vodostaj (cm);pretok (m3/s);temp. vode (°C)\r\nnot-a-date;142;223.499;4.4\r\n").encode()
    with pytest.warns(RuntimeWarning, match="invalid Datum"):
        shared_bad_oddo = rr.fetch(sel_oddo, start="2024-01-01", end="2024-01-02", cache="bypass", on_issue="warn")
    assert shared_bad_oddo.data.is_empty()
    assert [o.status for o in shared_bad_oddo.outcomes] == [OutcomeStatus.FAILED] * 3

    bodies["eks"] = (
        b"Leto;Mesec;Q_MIN_datum;Q_MIN_vrednost;H_MIN_datum;H_MIN_vrednost\r\n"
        b"bad-year;1;21.01.2024 16:49;95.9;21.01.2024 16:49;86\r\n"
    )
    with pytest.warns(RuntimeWarning):
        shared_bad_eks = rr.fetch(sel_eks, start="2024-01-01", end="2024-02-29", cache="bypass", on_issue="warn")
    assert shared_bad_eks.data.is_empty()
    assert [o.status for o in shared_bad_eks.outcomes] == [OutcomeStatus.FAILED] * 6

    bodies["amp"] = b"<html><body><p>no podatki table here</p></body></html>"
    with pytest.warns(RuntimeWarning, match="table.podatki"):
        shared_bad_amp = rr.fetch(
            sel_amp, start="2026-11-23T10:00:00", end="2026-11-23T10:10:00", cache="bypass", on_issue="warn"
        )
    assert shared_bad_amp.data.is_empty()
    assert [o.status for o in shared_bad_amp.outcomes] == [OutcomeStatus.FAILED] * 3


def test_si_arso_parse_group_pair_context_isolation_and_parse_parity() -> None:
    from dataclasses import replace

    import polars.testing as pl_testing

    from rivretrieve._internal.engine import WindowEndpoint, narrow_payload_for_pair
    from rivretrieve._internal.source_series import (
        InventoryCompleteness,
        RestrictionKind,
        SeriesScope,
        SourceIdentity,
    )

    amp_body = _make_si_arso_amp_html(
        "Postaja Gornja Radgona I - Mura",
        ("Vodostaj [cm]", "Pretok [m³/s]"),
        (("23.11.2026 10:10", "125", "180.5"),),
    )

    class _SingleBodyTransport:
        def __init__(self, body: bytes, content_type: str) -> None:
            self._body = body
            self._content_type = content_type

        def send(self, request: TransportRequest) -> TransportResponse:
            return TransportResponse(
                content=self._body,
                status_code=200,
                retrieved_at=datetime(2026, 11, 23, 10, 20, tzinfo=UTC),
                content_type=self._content_type,
                url=request.url,
                request_parameters=request.params or {},
            )

    p_q = primitives.ProductId("operational_discharge_10min")
    p_h = primitives.ProductId("operational_stage_10min")
    p_t = primitives.ProductId("operational_temperature_10min")
    fw_amp = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2026, 11, 23, 10, 0)),
        WindowEndpoint.from_datetime(datetime(2026, 11, 23, 10, 10)),
    )
    rendered_amp = {p: window_planning.plan_windows(fw_amp, config._WINDOWS.products[p]) for p in (p_q, p_h, p_t)}
    acq_amp = fetch.fetch(
        ("1060",),
        (p_q, p_h, p_t),
        rendered_amp,
        fw_amp,
        config._CONFIG,
        _SingleBodyTransport(amp_body, "text/html; charset=utf-8"),
    )
    shared_amp = acq_amp.value[0]

    custom_q_series = series.source_series("1060", str(p_q)).model_copy(
        update={
            "identity": SourceIdentity(
                namespace="si_arso-custom",
                published_id="custom-q-1060",
                origin="catalogue",
                evidence=("per-pair test",),
            )
        }
    )
    cat_t_series = series.source_series("1060", str(p_t))

    def _pair_map(temp_restriction: RestrictionKind) -> dict[tuple[str, primitives.ProductId], object]:
        base_q = narrow_payload_for_pair(shared_amp, "1060", p_q)
        base_h = narrow_payload_for_pair(shared_amp, "1060", p_h)
        base_t = narrow_payload_for_pair(shared_amp, "1060", p_t)
        return {
            ("1060", p_q): replace(base_q, known_series=(custom_q_series,)),
            ("1060", p_h): replace(base_h, known_series=()),
            ("1060", p_t): replace(
                base_t,
                known_series=(cat_t_series,) if temp_restriction is RestrictionKind.EXPLICIT else (),
                scope=SeriesScope(
                    provider_ids=("si_arso",),
                    station_ids=("1060",),
                    product_ids=(str(p_t),),
                    restriction=temp_restriction,
                    series_ids=(cat_t_series.series_id,) if temp_restriction is RestrictionKind.EXPLICIT else (),
                ),
            ),
        }

    grouped_all = parse.parse_group(shared_amp, _pair_map(RestrictionKind.ALL), config._CONFIG)  # type: ignore[arg-type]
    assert grouped_all[("1060", p_q)].series[0].identity == custom_q_series.identity
    expected_h_identity = series.source_series(
        "1060",
        str(p_h),
        origin="response",
        identity_evidence=(f"source-call:{shared_amp.acquisition_id}",),
    ).identity
    assert grouped_all[("1060", p_h)].series[0].identity == expected_h_identity
    assert [o.status for o in grouped_all[("1060", p_t)].outcomes] == [OutcomeStatus.NO_MATCH]
    assert [i.code for i in grouped_all[("1060", p_t)].issues] == ["source.no_match"]

    grouped_explicit = parse.parse_group(
        shared_amp,
        _pair_map(RestrictionKind.EXPLICIT),
        config._CONFIG,  # type: ignore[arg-type]
    )
    assert grouped_explicit[("1060", p_t)].outcomes == ()
    assert grouped_explicit[("1060", p_t)].issues == ()
    assert grouped_explicit[("1060", p_t)].inventories[0].completeness is InventoryCompleteness.COMPLETE
    assert grouped_explicit[("1060", p_t)].inventories[0].members == ()

    # Direct parse() over multi-product payload matches parse_group() merged outputs.
    oddo_body = ("Datum;vodostaj (cm);pretok (m3/s);temp. vode (°C)\r\n01.01.2024;142;223.499;4.4\r\n").encode()
    oddo_prods = tuple(
        primitives.ProductId(p) for p in ("archive_discharge_daily", "archive_stage_daily", "archive_temperature_daily")
    )
    fw_oddo = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime(2024, 1, 1, 0, 0)),
        WindowEndpoint.from_datetime(datetime(2024, 1, 1, 23, 59, 59)),
    )
    rendered_oddo = {p: window_planning.plan_windows(fw_oddo, config._WINDOWS.products[p]) for p in oddo_prods}
    acq_oddo = fetch.fetch(
        ("1060",),
        oddo_prods,
        rendered_oddo,
        fw_oddo,
        config._CONFIG,
        _SingleBodyTransport(oddo_body, "text/csv; charset=utf-8"),
    )
    shared_oddo = acq_oddo.value[0]
    direct = parse.parse(shared_oddo, config._CONFIG)
    pair_oddo = {k: narrow_payload_for_pair(shared_oddo, *k) for k in shared_oddo.station_products}
    by_group = parse.parse_group(shared_oddo, pair_oddo, config._CONFIG)
    assert len(direct.series) == len(by_group)
    assert direct.rows.height == sum(by_group[k].rows.height for k in pair_oddo)
    assert direct.outcomes == tuple(o for k in pair_oddo for o in by_group[k].outcomes)
    for k in pair_oddo:
        pl_testing.assert_frame_equal(
            direct.rows.filter(direct.rows["product_id"] == str(k[1])),
            by_group[k].rows,
        )
        pl_testing.assert_frame_equal(
            direct.annotations.series_tables["si_arso.series"].rows.filter(
                direct.annotations.series_tables["si_arso.series"].rows["series_id"] == by_group[k].series[0].series_id
            ),
            by_group[k].annotations.series_tables["si_arso.series"].rows,
        )

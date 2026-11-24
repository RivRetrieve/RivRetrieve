"""Public replay of retained Slovenia ARSO HTTP captures through find/pick/fetch/to_utc/cache."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit  # noqa: TID251 - URL parsing for retained receipt replay only

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse

_SCOPE = "maintenance/observations/si_arso/retrieval"

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _load_capture(root: Path, group: str, name: str) -> tuple[bytes, dict[str, object]]:
    base = root / _SCOPE / group / name
    return base.with_suffix(".body").read_bytes(), json.loads(base.with_suffix(".receipt.json").read_bytes())


def _response_matching_request(root: Path, group: str, name: str, request: TransportRequest) -> TransportResponse:
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
    assert actual_params == expected_params
    headers = receipt.get("response_headers")
    content_type = headers.get("content-type") if isinstance(headers, dict) else None
    status_code = int(str(receipt.get("http_status", 200)))
    retrieved_at = datetime.fromisoformat(str(receipt["retrieved_at"]).replace("Z", "+00:00"))
    return TransportResponse(
        content=content,
        status_code=status_code,
        retrieved_at=retrieved_at,
        content_type=str(content_type) if content_type is not None else None,
        url=f"{source.scheme}://{source.netloc}{source.path}",
        request_parameters=actual_params,
    )


class _ExactPublicReplay:
    """Replay genuine retained ARSO captures matched strictly by URL path and exact parameters."""

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
        return _response_matching_request(self._root, group, cap_name, request)


def _decode_oddo_col(raw: bytes, column: str, *, scale: float = 1.0) -> list[tuple[datetime, float]]:
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";")
    header = next(reader)
    idx = header.index(column)
    out: list[tuple[datetime, float]] = []
    for row in reader:
        if idx < len(row) and row[idx].strip():
            d = datetime.strptime(row[0].strip(), "%d.%m.%Y")
            out.append((d, float(row[idx].strip()) * scale))
    return out


def _decode_amp_col(raw: bytes, column: str) -> list[tuple[datetime, float]]:
    text = raw.decode("utf-8")
    table = text[text.index('<table class="podatki">') :]
    ths = re.findall(r"<th>(.*?)</th>", table[: table.index("</thead>")], re.DOTALL)
    idx = ths.index(column)
    rows_out: list[tuple[datetime, float]] = []
    for tr_html in re.findall(r"<tr>(.*?)</tr>", table[table.index("<tbody>") :], re.DOTALL):
        cells = [c.strip() for c in re.findall(r"<td>(.*?)</td>", tr_html, re.DOTALL)]
        if len(cells) > idx and cells[idx] not in {"", "-"}:
            rows_out.append((datetime.strptime(cells[0], "%d.%m.%Y %H:%M"), float(cells[idx])))
    return sorted(rows_out, key=lambda item: item[0])


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_archive_conversions_sediment_extremes_and_cache_reuse(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    captures = (
        ("access", "archive-1060-2024-oddo"),
        ("access", "archive-1060-2024-eks"),
        ("access", "archive-1060-1950-1955-oddo"),
        ("access", "archive-1060-2025-2026-oddo"),
        ("access", "archive-1060-2025-2026-eks"),
        ("access", "archive-2070-2024-oddo"),
        ("access", "archive-3660-1895-oddo"),
        ("access", "archive-3660-1895-eks"),
        ("access", "archive-4450-2024-oddo"),
        ("catalogue", "oddo/1058"),
        ("catalogue", "oddo/1030"),
        ("catalogue", "oddo/1020"),
        ("catalogue", "oddo/6310"),
    )
    replay = _ExactPublicReplay(retained_evidence_root, captures)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    # 1. Station 1060 (2024 leap year): dual-sediment + turbidity CSV ignored cleanly,
    #    cm -> m conversion, Verificirani podatki annotation, cache="reuse" + audit_cache, and to_utc refusal.
    sel_1060 = rr.find(provider="si_arso", station="1060", frequency="P1D")
    res_1060 = rr.fetch(sel_1060, start="2024-01-01", end="2024-12-31", cache="reuse", receipts=True, on_issue="raise")
    assert replay.calls == ["archive-1060-2024-oddo"]
    assert res_1060.issues == ()
    assert res_1060.receipts is not None and len(res_1060.receipts.entries) == 1
    assert "CC BY 4.0" in str(res_1060.provenance.license)
    assert "Agencije Republike Slovenije za okolje" in str(res_1060.provenance.citation)

    raw_1060, _ = _load_capture(retained_evidence_root, "access", "archive-1060-2024-oddo")
    q_expected = _decode_oddo_col(raw_1060, "pretok (m3/s)")
    h_expected = _decode_oddo_col(raw_1060, "vodostaj (cm)", scale=0.01)
    q_actual = res_1060.data.filter(pl.col("product_id") == "archive_discharge_daily").sort("time")
    h_actual = res_1060.data.filter(pl.col("product_id") == "archive_stage_daily").sort("time")
    assert q_actual.height == 366
    assert q_actual["time"].to_list() == [ts for ts, _ in q_expected]
    assert q_actual["value"].to_list() == pytest.approx([v for _, v in q_expected])
    assert h_actual["time"].to_list() == [ts for ts, _ in h_expected]
    assert h_actual["value"].to_list() == pytest.approx([v for _, v in h_expected])
    assert set(h_actual["source_unit"].to_list()) == {"cm"}
    assert set(h_actual["unit"].to_list()) == {"m"}
    assert rr.series(res_1060, annotations=True)["data_status"].to_list() == ["Verificirani podatki"] * 3

    # Repeat sub-window query issues 0 network calls.
    reused = rr.fetch(sel_1060, start="2024-06-01", end="2024-06-15", cache="reuse", on_issue="raise")
    assert replay.calls == ["archive-1060-2024-oddo"]
    assert reused.data.filter(pl.col("product_id") == "archive_discharge_daily").height == 15
    assert rr.audit_cache("si_arso").rows_checked >= 366 * 3

    with pytest.raises(FatalContractError, match="time_zone is 'unknown'"):
        rr.to_utc(res_1060)

    # 2. Monthly extremes (min & max share 1 call) and deep 1895 historical witness (3660).
    sel_eks = rr.find(provider="si_arso", station="1060", frequency="P1M", quantity="discharge")
    res_eks = rr.fetch(sel_eks, start="2024-01-01", end="2024-12-31", cache="bypass", on_issue="raise")
    assert res_eks.data.filter(pl.col("product_id") == "archive_discharge_monthly_min").height == 12
    assert res_eks.data.filter(pl.col("product_id") == "archive_discharge_monthly_max").height == 12

    sel_3660 = rr.find(provider="si_arso", station="3660", quantity="discharge", frequency="P1D")
    res_3660 = rr.fetch(sel_3660, start="1895-01-01", end="1895-12-31", cache="bypass", on_issue="raise")
    assert res_3660.data.height == 365
    assert res_3660.issues == ()

    # 3. Unpublished 2025-2026 Datum-only & Leto;Mesec-only resolve cleanly with issues=().
    q_1060 = rr.pick(sel_1060, quantity="discharge")
    empty_2025 = rr.fetch(q_1060, start="2025-01-01", end="2026-11-24", cache="bypass", on_issue="raise")
    assert empty_2025.data.is_empty()
    assert empty_2025.issues == ()
    assert [o.status for o in empty_2025.outcomes] == [OutcomeStatus.UNRESOLVED]

    empty_eks_2025 = rr.fetch(
        rr.pick(sel_eks, statistic="max"), start="2025-01-01", end="2026-11-24", cache="bypass", on_issue="raise"
    )
    assert empty_eks_2025.data.is_empty()
    assert empty_eks_2025.issues == ()
    assert [o.status for o in empty_eks_2025.outcomes] == [OutcomeStatus.UNRESOLVED]

    # 4. Partial-column 1950-1955 oddo (stage starts later than 1950 -> pre-gap UNRESOLVED without warnings).
    res_50 = rr.fetch(sel_1060, start="1950-01-01", end="1955-12-31", cache="bypass", on_issue="raise")
    assert res_50.issues == ()
    assert res_50.data.filter(pl.col("product_id") == "archive_discharge_daily").height == 2191
    assert any(o.product_id == "archive_stage_daily" and o.status is OutcomeStatus.UNRESOLVED for o in res_50.outcomes)

    # 5. Negative stage (1058 -> -0.21 m), zero discharge (1030 -> 0.0), ragged 1895 rows (1020), and blank Q (6310).
    res_1058 = rr.fetch(
        rr.find(provider="si_arso", station="1058", quantity="stage", frequency="P1D"),
        start="1895-01-01",
        end="2025-12-31",
        cache="bypass",
        on_issue="raise",
    )
    assert float(res_1058.data["value"].min()) < 0.0  # type: ignore[arg-type]

    res_1030 = rr.fetch(
        rr.find(provider="si_arso", station="1030", quantity="discharge", frequency="P1D"),
        start="1895-01-01",
        end="2025-12-31",
        cache="bypass",
        on_issue="raise",
    )
    assert 0.0 in res_1030.data["value"].to_list()

    res_1020 = rr.fetch(
        rr.find(provider="si_arso", station="1020", quantity="discharge", frequency="P1D"),
        start="1895-01-01",
        end="2025-12-31",
        cache="bypass",
        on_issue="raise",
    )
    assert res_1020.issues == ()
    assert res_1020.data.height > 0

    res_6310 = rr.fetch(
        rr.find(provider="si_arso", station="6310", quantity="stage", frequency="P1D"),
        start="1895-01-01",
        end="2025-12-31",
        cache="bypass",
        on_issue="raise",
    )
    assert res_6310.data.height > 0


@pytest.mark.recorded(_SCOPE)
def test_public_recorded_operational_amp_cadences_conductivity_outage_and_to_utc(
    retained_evidence_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    captures = (
        ("catalogue", "amp_t1/1060"),
        ("catalogue", "amp_t7/1060"),
        ("catalogue", "amp_t30/1060"),
        ("catalogue", "amp_t1/1312"),
        ("catalogue", "amp_t1/7409"),
    )
    replay = _ExactPublicReplay(retained_evidence_root, captures)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    # 1. Fixed +01:00 -> rr.to_utc (+00:00) on 1060 across t_1, t_7, and t_30 (all three products share one GET each!).
    for variant, cap_name, span in (
        ("operational_10min", "amp_t1/1060", ("2026-11-22T00:00:00", "2026-11-23T23:00:00")),
        ("operational_30min", "amp_t7/1060", ("2026-11-16T00:00:00", "2026-11-23T23:00:00")),
        ("operational_hourly", "amp_t30/1060", ("2026-10-21T00:00:00", "2026-11-23T23:00:00")),
    ):
        sel = rr.pick(rr.find(provider="si_arso", station="1060"), variant=variant)
        res = rr.fetch(sel, start=span[0], end=span[1], cache="bypass", on_issue="raise")
        raw, _ = _load_capture(retained_evidence_root, "catalogue", cap_name)
        s_dt = datetime.fromisoformat(span[0])
        e_dt = datetime.fromisoformat(span[1])
        expected_q = [(ts, v) for ts, v in _decode_amp_col(raw, "Pretok [m³/s]") if s_dt <= ts <= e_dt]
        q_rows = res.data.filter(pl.col("quantity") == "discharge").sort("time")
        assert q_rows.height > 0
        assert q_rows["time"].to_list() == [ts for ts, _ in expected_q]
        assert q_rows["value"].to_list() == pytest.approx([v for _, v in expected_q])
        assert set(res.data["time_zone"].to_list()) == {"+01:00"}
        assert rr.series(res, annotations=True)["data_status"].unique().to_list() == ["Začasni podatki"]

        utc = rr.to_utc(res)
        assert set(utc.data["time_zone"].to_list()) == {"+00:00"}

    # 2. Station 1312 outage ('-' across Vodostaj & Temperatura, valid Pretok).
    sel_1312 = rr.pick(rr.find(provider="si_arso", station="1312"), variant="operational_10min")
    span_1312 = ("2026-11-22T00:00:00", "2026-11-23T23:00:00")
    res_1312 = rr.fetch(sel_1312, start=span_1312[0], end=span_1312[1], cache="bypass", on_issue="raise")
    assert res_1312.issues == ()
    raw_1312, _ = _load_capture(retained_evidence_root, "catalogue", "amp_t1/1312")
    expected_1312 = _decode_amp_col(raw_1312, "Pretok [m³/s]")
    assert res_1312.data.filter(pl.col("quantity") == "discharge").height == len(expected_1312)
    assert res_1312.data.filter(pl.col("quantity") == "stage").is_empty()

    # 3. Station 7409 includes deferred Elektroprevodnost vode [uS] column cleanly.
    sel_7409 = rr.pick(rr.find(provider="si_arso", station="7409"), variant="operational_10min")
    res_7409 = rr.fetch(
        sel_7409, start="2026-11-22T00:00:00", end="2026-11-24T00:00:00", cache="bypass", on_issue="raise"
    )
    assert res_7409.issues == ()
    assert not res_7409.data.is_empty()

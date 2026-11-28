"""Public replay of retained Slovenia ARSO HTTP captures through find/pick/fetch/to_utc/cache."""

from __future__ import annotations

import json
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


def _assert_time_values(frame: pl.DataFrame, expected: tuple[tuple[datetime, float], ...]) -> None:
    by_time = dict(frame.select("time", "value").iter_rows())
    for ts, value in expected:
        assert ts in by_time, f"Expected timestamp {ts!r} missing from frame"
        assert by_time[ts] == pytest.approx(value)


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

    q_actual = res_1060.data.filter(pl.col("product_id") == "archive_discharge_daily").sort("time")
    h_actual = res_1060.data.filter(pl.col("product_id") == "archive_stage_daily").sort("time")
    t_actual = res_1060.data.filter(pl.col("product_id") == "archive_temperature_daily").sort("time")
    assert q_actual.height == 366
    assert h_actual.height == 366
    assert t_actual.height == 366
    _assert_time_values(
        q_actual,
        (
            (datetime(2024, 1, 1), 223.499),
            (datetime(2024, 1, 2), 213.818),
            (datetime(2024, 1, 3), 195.036),
            (datetime(2024, 12, 31), 69.675),
        ),
    )
    _assert_time_values(
        h_actual,
        (
            (datetime(2024, 1, 1), 1.42),
            (datetime(2024, 1, 2), 1.38),
            (datetime(2024, 1, 3), 1.30),
            (datetime(2024, 12, 31), 0.72),
        ),
    )
    _assert_time_values(
        t_actual,
        (
            (datetime(2024, 1, 1), 4.4),
            (datetime(2024, 1, 3), 4.8),
            (datetime(2024, 12, 31), 2.3),
        ),
    )
    assert set(h_actual["source_unit"].to_list()) == {"cm"}
    assert set(h_actual["unit"].to_list()) == {"m"}

    series_1060 = rr.series(res_1060, annotations=True)
    assert series_1060["data_status"].to_list() == ["Verificirani podatki"] * 3
    by_prod = {
        row["product_id"]: (row["published_id"], row["series_id"], row["facts_id"])
        for row in series_1060.iter_rows(named=True)
    }
    assert by_prod["archive_discharge_daily"] == (
        "pretok (m3/s)",
        "67360c767ccae4fffd3b7a2fe6c3bbef8355a837bac0edb718705c2088620890",
        "f01aa7199eb3488fb3ae8d1cf71ad6d80f54f1704785ec11fae88cc75d43f950",
    )
    assert by_prod["archive_stage_daily"] == (
        "vodostaj (cm)",
        "081c8eefe1270f69eaa6a771981d9d84fda3f181fbecc8b9639f21f7ad139ca3",
        "41e59be358d9e5b049c1f2bf2bad139d765f11bc45a9e261b0b08cb50dc878fa",
    )
    assert by_prod["archive_temperature_daily"] == (
        "temp. vode (°C)",
        "e4fab09271a46e2f4e65567ae64aa9f6b553620d39f7e20010ce78d75176bf9b",
        "93e064975e4311c648b4d7a23ccd7680931f7f37f1d55a9320c45067a4b9b91c",
    )

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
    eks_min = res_eks.data.filter(pl.col("product_id") == "archive_discharge_monthly_min").sort("time")
    eks_max = res_eks.data.filter(pl.col("product_id") == "archive_discharge_monthly_max").sort("time")
    assert eks_min.height == 12
    assert eks_max.height == 12
    _assert_time_values(
        eks_min,
        (
            (datetime(2024, 1, 21, 16, 49), 95.947),
            (datetime(2024, 2, 2, 15, 36), 89.984),
            (datetime(2024, 12, 28, 3, 43), 52.634),
        ),
    )
    _assert_time_values(
        eks_max,
        (
            (datetime(2024, 1, 7, 15, 13), 292.108),
            (datetime(2024, 2, 12, 6, 37), 188.552),
            (datetime(2024, 12, 1, 7, 7), 95.947),
        ),
    )
    eks_ids = {
        row["product_id"]: (row["published_id"], row["series_id"], row["facts_id"])
        for row in rr.series(res_eks).iter_rows(named=True)
    }
    assert eks_ids["archive_discharge_monthly_min"] == (
        "Q_MIN",
        "dc24db386bf401fdfc56a79dd36c9dadd179871965e834652ad4b7a0013dbaf6",
        "e73ac99822d6e2e2e5b009dc57085f73bf860b65ae6405bcdf8e608c71ed5658",
    )
    assert eks_ids["archive_discharge_monthly_max"] == (
        "Q_MAX",
        "dee28efd8be7a49cc32e8e6bdb5731a91d4e3ad0a1f9d81de32db2f35c20a176",
        "1d966a9d3539f6f7c7b00db8ba24448bb038c927933a33f27f6389d103b00729",
    )

    sel_3660 = rr.find(provider="si_arso", station="3660", quantity="discharge", frequency="P1D")
    res_3660 = rr.fetch(sel_3660, start="1895-01-01", end="1895-12-31", cache="bypass", on_issue="raise")
    assert res_3660.data.height == 365
    assert res_3660.issues == ()
    _assert_time_values(
        res_3660.data,
        (
            (datetime(1895, 1, 1), 80.8),
            (datetime(1895, 1, 2), 83.3),
            (datetime(1895, 1, 3), 81.0),
            (datetime(1895, 12, 31), 209.2),
        ),
    )
    assert rr.series(res_3660).select("published_id", "series_id", "facts_id").rows() == [
        (
            "pretok (m3/s)",
            "7750e275e63f4460eb0bf58d2290beb42cdb1f5a41bb2afb139155375e8567b5",
            "f01aa7199eb3488fb3ae8d1cf71ad6d80f54f1704785ec11fae88cc75d43f950",
        )
    ]

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
    q_50 = res_50.data.filter(pl.col("product_id") == "archive_discharge_daily")
    assert q_50.height == 2191
    _assert_time_values(
        q_50,
        (
            (datetime(1950, 1, 1), 96.6),
            (datetime(1950, 1, 2), 93.4),
            (datetime(1955, 12, 31), 88.6),
        ),
    )
    assert any(o.product_id == "archive_stage_daily" and o.status is OutcomeStatus.UNRESOLVED for o in res_50.outcomes)

    # 5. Negative stage (1058 -> -0.21 m), zero discharge (1030 -> 0.0), ragged 1895 rows (1020), and blank Q (6310).
    res_1058 = rr.fetch(
        rr.find(provider="si_arso", station="1058", quantity="stage", frequency="P1D"),
        start="1895-01-01",
        end="2025-12-31",
        cache="bypass",
        on_issue="raise",
    )
    _assert_time_values(
        res_1058.data,
        (
            (datetime(1930, 1, 1), -0.21),
            (datetime(1930, 1, 2), -0.19),
            (datetime(1930, 1, 3), -0.20),
        ),
    )
    assert rr.series(res_1058)["series_id"].to_list() == [
        "60994855c80ab7fdfac5bba66ee27512787c56be64be86f69b4d48e8175644cf"
    ]

    res_1030 = rr.fetch(
        rr.find(provider="si_arso", station="1030", quantity="discharge", frequency="P1D"),
        start="1895-01-01",
        end="2025-12-31",
        cache="bypass",
        on_issue="raise",
    )
    _assert_time_values(
        res_1030.data,
        (
            (datetime(1957, 1, 1), 0.0),
            (datetime(1957, 1, 2), 0.0),
            (datetime(1957, 1, 3), 0.0),
        ),
    )
    assert rr.series(res_1030)["series_id"].to_list() == [
        "1244f16dd222e8c16227fc4e54a4c25d2d68d0f13b4fc54852a57e2c8186ee56"
    ]

    res_1020 = rr.fetch(
        rr.find(provider="si_arso", station="1020", quantity="discharge", frequency="P1D"),
        start="1895-01-01",
        end="2025-12-31",
        cache="bypass",
        on_issue="raise",
    )
    assert res_1020.issues == ()
    _assert_time_values(
        res_1020.data,
        (
            (datetime(1956, 4, 8), 162.0),
            (datetime(1956, 4, 9), 142.0),
        ),
    )
    assert rr.series(res_1020)["series_id"].to_list() == [
        "3c3cc7a27334b3d5a6cc68f31c0ddff92b2018ba3bc9a6ccddb01fed33efbca6"
    ]

    res_6310 = rr.fetch(
        rr.find(provider="si_arso", station="6310", quantity="stage", frequency="P1D"),
        start="1895-01-01",
        end="2025-12-31",
        cache="bypass",
        on_issue="raise",
    )
    _assert_time_values(
        res_6310.data,
        (
            (datetime(1954, 1, 1), 1.10),
            (datetime(1954, 1, 2), 1.14),
            (datetime(1969, 12, 31), 1.10),
        ),
    )
    assert rr.series(res_6310)["series_id"].to_list() == [
        "77089a44a71767a4a0e5498f16c88a4c5060599e82ae3891d3c3ff9b3b0754dd"
    ]


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

    # 1. Fixed +01:00 -> rr.to_utc (+00:00) on 1060 across t_1, t_7, and t_30 (all three products share one GET each).
    cases = (
        (
            "operational_10min",
            ("2026-11-22T00:00:00", "2026-11-23T23:00:00"),
            "81a2484d03f453b3f8825cc231c1f0a26881fa4d5973bb721bfde36be9bebe4a",
            "93d99c4358bf65bef269acd7293fda33ae7ad1ada517bbc92a7013a07ef37efa",
            ((datetime(2026, 11, 22, 22, 30), 43.4), (datetime(2026, 11, 23, 22, 20), 49.1)),
            ((datetime(2026, 11, 22, 21, 30), 43.4), (datetime(2026, 11, 23, 21, 20), 49.1)),
        ),
        (
            "operational_30min",
            ("2026-11-16T00:00:00", "2026-11-23T23:00:00"),
            "9cb9b62671cfe4b69efc9b7d1b8b809ce1668f707f4de5e63467ba22cc40ceda",
            "51ecf694c9d256c7cc7824ffeedef6f4428bf15c9782b0ec2faf15415c8186bb",
            (
                (datetime(2026, 11, 16, 1, 30), 47.6),
                (datetime(2026, 11, 16, 2, 0), 44.8),
                (datetime(2026, 11, 23, 0, 30), 49.1),
            ),
            (
                (datetime(2026, 11, 16, 0, 30), 47.6),
                (datetime(2026, 11, 22, 23, 30), 49.1),
            ),
        ),
        (
            "operational_hourly",
            ("2026-10-21T00:00:00", "2026-11-23T23:00:00"),
            "6f6e40888677b266a1ebb8dc073cb7b3ff8ebb0d9b9a61376af44d4a0874dc61",
            "f18f7cc8eab66a4019ad197e80b319728ba263c0cac5bd3fc1ca85dea6a988be",
            (
                (datetime(2026, 10, 21, 0, 0), 44.8),
                (datetime(2026, 10, 21, 1, 0), 43.4),
                (datetime(2026, 11, 20, 0, 0), 65.7),
            ),
            (
                (datetime(2026, 10, 20, 23, 0), 44.8),
                (datetime(2026, 11, 19, 23, 0), 65.7),
            ),
        ),
    )
    for variant, span, expected_sid, expected_fid, expected_cet, expected_utc in cases:
        sel = rr.pick(rr.find(provider="si_arso", station="1060"), variant=variant)
        res = rr.fetch(sel, start=span[0], end=span[1], cache="bypass", on_issue="raise")
        q_rows = res.data.filter(pl.col("quantity") == "discharge").sort("time")
        _assert_time_values(q_rows, expected_cet)
        assert set(res.data["time_zone"].to_list()) == {"+01:00"}

        ser_tbl = rr.series(res, annotations=True)
        assert ser_tbl["data_status"].unique().to_list() == ["Začasni podatki"]
        q_meta = (
            ser_tbl.filter(pl.col("quantity") == "discharge").select("published_id", "series_id", "facts_id").rows()
        )
        assert q_meta == [("Pretok [m³/s]", expected_sid, expected_fid)]

        utc = rr.to_utc(res)
        assert set(utc.data["time_zone"].to_list()) == {"+00:00"}
        _assert_time_values(utc.data.filter(pl.col("quantity") == "discharge"), expected_utc)

    # 2. Station 1312 outage ('-' across Vodostaj & Temperatura, valid Pretok).
    sel_1312 = rr.pick(rr.find(provider="si_arso", station="1312"), variant="operational_10min")
    span_1312 = ("2026-11-22T00:00:00", "2026-11-23T23:00:00")
    res_1312 = rr.fetch(sel_1312, start=span_1312[0], end=span_1312[1], cache="bypass", on_issue="raise")
    assert res_1312.issues == ()
    q_1312 = res_1312.data.filter(pl.col("quantity") == "discharge")
    assert q_1312.height == 144
    _assert_time_values(
        q_1312,
        (
            (datetime(2026, 11, 22, 22, 30), 0.009),
            (datetime(2026, 11, 23, 22, 20), 0.012),
        ),
    )
    assert res_1312.data.filter(pl.col("quantity") == "stage").is_empty()
    assert rr.series(res_1312).filter(pl.col("quantity") == "discharge").select(
        "published_id", "series_id", "facts_id"
    ).rows() == [
        (
            "Pretok [m³/s]",
            "23c5859e50baa5bfb86470e6e43fb1e75cea3fab39f5ab38e74f59bb993357ef",
            "93d99c4358bf65bef269acd7293fda33ae7ad1ada517bbc92a7013a07ef37efa",
        )
    ]

    # 3. Station 7409 includes deferred Elektroprevodnost vode [uS] column cleanly.
    sel_7409 = rr.pick(rr.find(provider="si_arso", station="7409"), variant="operational_10min")
    res_7409 = rr.fetch(
        sel_7409, start="2026-11-22T00:00:00", end="2026-11-24T00:00:00", cache="bypass", on_issue="raise"
    )
    assert res_7409.issues == ()
    _assert_time_values(
        res_7409.data.filter(pl.col("quantity") == "discharge"),
        (
            (datetime(2026, 11, 22, 22, 40), 0.433),
            (datetime(2026, 11, 22, 22, 50), 0.433),
        ),
    )
    _assert_time_values(
        res_7409.data.filter(pl.col("quantity") == "stage"),
        (
            (datetime(2026, 11, 22, 22, 40), 0.67),
            (datetime(2026, 11, 22, 22, 50), 0.67),
        ),
    )
    assert rr.series(res_7409).filter(pl.col("quantity") == "discharge").select(
        "published_id", "series_id", "facts_id"
    ).rows() == [
        (
            "Pretok [m³/s]",
            "04c93a5cf24b71671864ab073b8d9eedbe78f40af977c8707ebe41a1ec7130be",
            "93d99c4358bf65bef269acd7293fda33ae7ad1ada517bbc92a7013a07ef37efa",
        )
    ]

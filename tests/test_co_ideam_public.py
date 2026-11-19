"""Public Colombia IDEAM discovery, retrieval, per-series isolation, and cache controls."""

from __future__ import annotations

import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.discovery import EmptySelectionError
from rivretrieve._internal.issues import IssuePolicyError
from rivretrieve._internal.providers.co_ideam.fetch import s3_observation_csv_url
from rivretrieve._internal.providers.co_ideam.series import SERIES_SPECS
from rivretrieve._internal.selection import UnknownStationError
from rivretrieve._internal.source_series import InventoryCompleteness, OutcomeStatus
from rivretrieve._internal.transport import (
    TransportFailure,
    TransportFailureCategory,
    TransportFailureReason,
    TransportRequest,
    TransportResponse,
)

_RETRIEVED_AT = datetime(2026, 11, 8, 22, 0, tzinfo=UTC)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _csv_bytes(*rows: tuple[str, str, str], bom: bool = False) -> bytes:
    lines = ["fechaObservacion,valorObservado,nivelAprobacion"]
    lines.extend(f"{ts},{val},{app}" for ts, val, app in rows)
    text = "\n".join(lines) + "\n"
    return ("\ufeff" + text if bom else text).encode("utf-8")


def _raise_http_failure(request: TransportRequest, status_code: int = 503, body: bytes = b"") -> NoReturn:
    response = TransportResponse(body, status_code, _RETRIEVED_AT, "application/xml", request.url, {}) if body else None
    raise TransportFailure(
        request,
        TransportFailureReason.HTTP_STATUS,
        1,
        status_code=status_code,
        category=TransportFailureCategory.HTTP_STATUS,
        response=response,
    )


def _select_products(station: str, *products: str) -> rr.Selection:
    selected = rr.find(provider="co_ideam", station=station)
    series_ids = rr.as_frame(selected).filter(pl.col("product_id").is_in(products))["series_id"].to_list()
    assert len(series_ids) == len(products)
    return rr.pick(selected, series_id=series_ids)


def test_public_all_20_products_units_provenance_and_predicate_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    station = "0011017010"

    providers_df = rr.providers()
    ideam_row = providers_df.filter(pl.col("provider_id") == "co_ideam").row(0, named=True)
    assert ideam_row == {"provider_id": "co_ideam", "credentials": [], "access": "open"}
    assert len(rr.products("co_ideam")) == 20

    url_to_body: dict[str, bytes] = {}
    for idx, spec in enumerate(SERIES_SPECS, start=1):
        ts = "2023-01-01 06:00:00" if spec.product_id in ("caudal_h", "nivel_h") else "2023-01-01 00:00:00"
        raw_val = f"{-15.0 if spec.product_id == 'nivel_h' else float(idx):.2f}"
        approval = ("Preliminar", "En revisión", "Definitivo", "")[idx % 4]
        url_to_body[s3_observation_csv_url(station, spec.etiqueta)] = _csv_bytes(
            (ts, raw_val, approval),
            bom=(idx % 2 == 0),
        )

    class _AllProductsTransport:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            self.urls.append(request.url)
            assert request.params in (None, {})
            return TransportResponse(url_to_body[request.url], 200, _RETRIEVED_AT, "text/csv", request.url, {})

    replay = _AllProductsTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    selection = rr.find(provider="co_ideam", station=station)
    assert len(selection.series) == 20
    result = rr.fetch(selection, start="2023-01-01", end="2023-12-31T23:59:59", cache="bypass", receipts=True)
    assert len(replay.urls) == 20
    assert result.issues == ()
    assert result.receipts is not None and len(result.receipts.entries) == 20
    assert result.data.height == 20
    assert result.data["product_id"].n_unique() == 20
    assert result.data["time_zone"].unique().to_list() == ["unknown"]

    # Stage cm -> m conversion (factor=0.01, vertical_reference="gauge_zero"), preserving negative stage (-15 cm -> -0.15 m).
    stage_df = result.data.filter(pl.col("product_id").str.starts_with("nv_") | (pl.col("product_id") == "nivel_h"))
    assert stage_df.height == 10
    assert stage_df["source_unit"].unique().to_list() == ["cm"]
    assert stage_df["unit"].unique().to_list() == ["m"]
    nivel_h_val = stage_df.filter(pl.col("product_id") == "nivel_h")["value"].item()
    assert nivel_h_val == pytest.approx(-0.15)

    flow_df = result.data.filter(pl.col("product_id").str.starts_with("q_") | (pl.col("product_id") == "caudal_h"))
    assert flow_df.height == 10
    assert flow_df["source_unit"].unique().to_list() == ["m3/s"]
    assert flow_df["unit"].unique().to_list() == ["m3/s"]

    series_frame = rr.series(result)
    assert set(series_frame.filter(pl.col("quantity") == "stage")["vertical_reference"].to_list()) == {"gauge_zero"}

    # Provenance carries verified CC BY-SA 4.0 license and IDEAM citation.
    statements = [
        stmt for record in result.provenance.acquisition_provenance.header.source_records for stmt in record.statements
    ]
    assert any(stmt.kind == "license" and "Share Alike 4.0" in stmt.exact_text for stmt in statements)
    assert any(stmt.kind == "citation" and "IDEAM" in stmt.exact_text for stmt in statements)

    # Bundle roundtrip preserves selection and observation result.
    restored = rr.from_bundle(rr.to_bundle(result))
    assert_frame_equal(restored.data, result.data)
    assert restored.outcomes == result.outcomes

    # Physical-predicate filtering withholds CAUDAL_H when frequency="daily", statistic="mean" is requested,
    # while selecting by series_id from rr.series(...) targets CAUDAL_H explicitly.
    daily_mean_q = rr.find(
        provider="co_ideam", station=station, quantity="discharge", frequency="daily", statistic="mean"
    )
    assert [s.product_id for s in daily_mean_q.series] == ["q_media_d"]
    all_q = rr.find(provider="co_ideam", station=station, quantity="discharge")
    caudal_h_sid = rr.series(all_q).filter(pl.col("product_id") == "caudal_h")["series_id"].to_list()
    subdaily_q = rr.pick(all_q, series_id=caudal_h_sid)
    assert [s.product_id for s in subdaily_q.series] == ["caudal_h"]

    # Unestablished time_zone selection fails closed before touching network transport.
    monkeypatch.setattr(discovery, "HttpClient", lambda: pytest.fail("EmptySelectionError must not touch network"))
    empty_tz = rr.find(provider="co_ideam", station=station, time_zone="America/Bogota")
    with pytest.raises(EmptySelectionError, match="co_ideam"):
        rr.fetch(empty_tz, start="2023-05-01", end="2023-05-02")

    # Dead registry station without S3 hydrological CSVs raises UnknownStationError.
    with pytest.raises(UnknownStationError):
        rr.find(provider="co_ideam", station="0026077050")


def test_public_option_1a_bounded_cache_reuse_extension_revision_and_zero_row_unresolved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    station = "0026177030"
    selected = _select_products(station, "nv_media_d")

    snap_v1 = _csv_bytes(
        ("1992-08-01 01:00:00", "0.0", "Definitivo"),
        ("1992-08-02 01:00:00", "155.5", "Preliminar"),
    )
    snap_v2 = _csv_bytes(
        ("1992-08-01 01:00:00", "0.0", "Definitivo"),
        ("1992-08-02 01:00:00", "157.625", "Definitivo"),
        ("1992-08-03 01:00:00", "160.0", "Preliminar"),
    )

    class _RegenTransport:
        def __init__(self) -> None:
            self.calls = 0
            self.current = snap_v1

        def send(self, request: TransportRequest) -> TransportResponse:
            self.calls += 1
            return TransportResponse(self.current, 200, _RETRIEVED_AT, "text/csv", request.url, {})

    transport = _RegenTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    # First query spans pre-record (1992-07-31) through 1992-08-02: Option 1A expands CALENDAR_DATE
    # covered_start to 1992-08-01 00:00:00 despite 01:00:00 Hora Gaviria wall clock, and leaves 1992-07-31 UNRESOLVED.
    first = rr.fetch(selected, start="1992-07-31", end="1992-08-02", cache="reuse", on_issue="raise")
    assert transport.calls == 1
    assert first.data["value"].to_list() == pytest.approx([0.0, 1.555])
    assert [o.status for o in first.outcomes] == [OutcomeStatus.SUCCESS, OutcomeStatus.UNRESOLVED]

    # Repeat query inside [1992-08-01, 1992-08-02] hits local cache offline (0 network calls), even starting at 00:00:00!
    reused = rr.fetch(selected, start="1992-08-01", end="1992-08-02", cache="reuse", on_issue="raise")
    assert transport.calls == 1
    assert_frame_equal(reused.data, first.data)

    # Extending to 1992-08-04 misses the post-record span, re-fetches snap_v2, updates revised 1992-08-02 in place
    # (1.555 -> 1.57625 m), appends 1992-08-03 (1.60 m), and leaves unpublished 1992-08-04 UNRESOLVED!
    transport.current = snap_v2
    extended = rr.fetch(selected, start="1992-08-01", end="1992-08-04", cache="reuse", on_issue="raise")
    assert transport.calls == 2
    assert extended.data.sort("time")["value"].to_list() == pytest.approx([0.0, 1.57625, 1.60])
    assert {o.status for o in extended.outcomes} == {OutcomeStatus.SUCCESS, OutcomeStatus.UNRESOLVED}

    # Folded 1993-02-06 23:00:00 duplicate timestamps survive public rr.fetch and local store reuse.
    fold_sel = _select_products("0011107010", "nivel_h")
    transport.current = _csv_bytes(
        ("1993-02-06 23:00:00", "415.0", "Definitivo"),
        ("1993-02-06 23:00:00", "414.0", "Definitivo"),
    )
    fold_live = rr.fetch(
        fold_sel, start="1993-02-06T22:00:00", end="1993-02-06T23:30:00", cache="reuse", on_issue="raise"
    )
    assert transport.calls == 3
    assert fold_live.data["time"].to_list() == [datetime(1993, 2, 6, 23, 0), datetime(1993, 2, 6, 23, 0)]
    assert sorted(fold_live.data["value"].to_list()) == pytest.approx([4.14, 4.15])
    fold_cached = rr.fetch(
        fold_sel, start="1993-02-06T23:00:00", end="1993-02-06T23:00:00", cache="reuse", on_issue="raise"
    )
    assert transport.calls == 3
    assert_frame_equal(fold_cached.data, fold_live.data)

    # Zero-row header-only CSV returns OutcomeStatus.UNRESOLVED and InventoryCompleteness.INCOMPLETE (never EMPTY).
    empty_sel = _select_products("0012047010", "q_media_a")
    transport.current = _csv_bytes()
    zero_row = rr.fetch(empty_sel, start="2020-01-01", end="2020-12-31", cache="reuse", on_issue="raise")
    assert zero_row.data.is_empty()
    assert [o.status for o in zero_row.outcomes] == [OutcomeStatus.UNRESOLVED]
    assert all(inv.completeness is InventoryCompleteness.INCOMPLETE for inv in zero_row.inventories)


def test_public_option_2a_404_nosuchkey_sibling_isolation_and_held_row_survival(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    station = "0011017010"
    selected = _select_products(station, "q_media_d", "nv_media_d")
    q_url = s3_observation_csv_url(station, "Q_MEDIA_D")
    no_such_key_xml = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b"<Error><Code>NoSuchKey</Code><Message>The specified key does not exist.</Message></Error>"
    )

    class _FaultTransport:
        def __init__(self) -> None:
            self.fail_all_code: int | None = None

        def send(self, request: TransportRequest) -> TransportResponse:
            if self.fail_all_code is not None:
                _raise_http_failure(request, self.fail_all_code, no_such_key_xml)
            if request.url == q_url:
                return TransportResponse(
                    _csv_bytes(("2023-06-01 00:00:00", "42.5", "Preliminar")),
                    200,
                    _RETRIEVED_AT,
                    "text/csv",
                    request.url,
                    {},
                )
            _raise_http_failure(request, 404, no_such_key_xml)

    fault = _FaultTransport()
    monkeypatch.setattr(discovery, "HttpClient", lambda: fault)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        partial = rr.fetch(selected, start="2023-06-01", end="2023-06-01", cache="reuse", on_issue="warn")
    assert caught
    assert partial.data["product_id"].to_list() == ["q_media_d"]
    assert partial.data["value"].to_list() == pytest.approx([42.5])
    assert any(i.code == "source.http_not_found" and i.severity == "warning" for i in partial.issues)
    assert {o.product_id: o.status for o in partial.outcomes} == {
        "q_media_d": OutcomeStatus.SUCCESS,
        "nv_media_d": OutcomeStatus.FAILED,
    }

    # Transient 404 or 503 on cache="refresh" raises under on_issue="raise" and retains held q_media_d rows under "ignore".
    q_only = _select_products(station, "q_media_d")
    for status_code in (404, 503):
        fault.fail_all_code = status_code
        with pytest.raises(IssuePolicyError):
            rr.fetch(q_only, start="2023-06-01", end="2023-06-01", cache="refresh", on_issue="raise")
        retained = rr.fetch(q_only, start="2023-06-01", end="2023-06-01", cache="refresh", on_issue="ignore")
        assert retained.data["value"].to_list() == pytest.approx([42.5])

"""Source-independent tests for jp_mlit observation annotations (#815)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.observations import ObservationDataSchema, ReceiptAuthorship
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.jp_mlit.config import config
from rivretrieve._internal.providers.jp_mlit.fetch import JpMlitPayloadCoordinates
from rivretrieve._internal.providers.jp_mlit.parse import parse
from rivretrieve._internal.source_annotations import CATALOG_SCHEMA, AnnotationScope
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues", "registered_jp_mlit")

_STATION = "301011281104010"
_RETRIEVED_AT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
_ORIGIN = SourceCallOrigin(
    "http://www1.river.go.jp/dat/dload/download/test.dat",
    {},
    200,
    _RETRIEVED_AT,
    "text/plain",
    UnknownOriginFact(),
    UnknownOriginFact(),
)


def _hourly_dat(day_cells: list[tuple[str, list[tuple[str, str]]]], *, kind: int = 6) -> bytes:
    title = "時刻水位月表検索結果" if kind == 2 else "時刻流量月表検索結果"
    legend = "#  フラグの意味： *:暫定値, $:欠測, #:閉局, -:未登録"
    header = "," + ",".join(f"{h}時," for h in range(1, 25))
    lines = [
        title,
        "水系名,テスト水系",
        "河川名,テスト川",
        "観測所名,テスト観測所",
        f"観測所記号,{_STATION}",
        "# 水文水質データベース",
        "# 出力データ",
        legend,
        header,
    ]
    for date_str, pairs in day_cells:
        flat = ",".join(f"{val},{flg}" for val, flg in pairs)
        lines.append(f"{date_str},{flat}")
    return ("\n".join(lines) + "\n").encode("shift_jis")


def _daily_dat(
    year: int, month_rows: list[tuple[int, list[tuple[str, str]], tuple[str, str] | None]], *, kind: int = 3
) -> bytes:
    title = "日水位年表検索結果" if kind == 3 else "日流量年表検索結果"
    legend = "#  フラグの意味： $:欠測, -:未登録"
    header = "," + ",".join(f"{d}日," for d in range(1, 32))
    lines = [
        title,
        "水系名,テスト水系",
        "河川名,テスト川",
        "観測所名,テスト観測所",
        f"観測所記号,{_STATION}",
        "# 水文水質データベース",
        "# 出力データ",
        legend,
        header,
        f"{year}年",
    ]
    for month, pairs, trailing_summary in month_rows:
        cells = [f"{month}月"] + [item for val, flg in pairs for item in (val, flg)]
        if trailing_summary is not None:
            cells.extend(trailing_summary)
        lines.append(",".join(cells))
    return ("\n".join(lines) + "\n").encode("shift_jis")


def _dat_payload(product: str, kind: int, content: bytes, start: datetime, end: datetime) -> Payload:
    return Payload(
        SourceCoordinates(JpMlitPayloadCoordinates(kind=kind, role="dat")),
        ((_STATION, ProductId(product)),),
        _make_fetch_window(WindowEndpoint.from_datetime(start), WindowEndpoint.from_datetime(end)),
        content,
        _ORIGIN,
        (),
    )


def _html_page(kind: int, station: str, dat_path: str = "/dat/dload/download/test2023.dat") -> bytes:
    title = {2: "時刻水位月表検索結果", 3: "日水位年表検索結果", 6: "時刻流量月表検索結果", 7: "日流量年表検索結果"}[
        kind
    ]
    unit = "単位：m" if kind in (2, 3) else "単位：m<SUP>3</SUP>/s"
    html = (
        f"<html><head><meta http-equiv='Content-Type' content='text/html; charset=EUC-JP'>"
        f"<title>{title}</title></head>"
        f"<body><p>{station}</p><table><tr><td>{unit}</td></tr></table>"
        f"<a href='{dat_path}'>DAT</a></body></html>"
    )
    return html.encode("euc-jp")


def test_jp_mlit_annotation_schema_and_official_reference() -> None:
    from rivretrieve._internal.providers.jp_mlit.annotations import JP_MLIT_OBSERVATIONS_SCHEMA, JP_MLIT_URL

    assert JP_MLIT_OBSERVATIONS_SCHEMA.schema_id == "jp_mlit.observations"
    assert JP_MLIT_OBSERVATIONS_SCHEMA.provider_id == "jp_mlit"
    assert JP_MLIT_OBSERVATIONS_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert [field.name for field in JP_MLIT_OBSERVATIONS_SCHEMA.fields] == ["flag"]
    assert [field.dtype for field in JP_MLIT_OBSERVATIONS_SCHEMA.fields] == ["String"]
    flag_field = JP_MLIT_OBSERVATIONS_SCHEMA.fields[0]
    assert flag_field.reference_url == JP_MLIT_URL
    for marker in ("*", "$", "#", "-"):
        assert marker in flag_field.description


def test_jp_mlit_hourly_annotations_preserve_flags_unmeasured_slots_and_hour_24() -> None:
    pairs = [("1.25", " "), ("2.50", "*"), ("", "$"), ("", "#"), ("", "-")] + [("3.00", " ")] * 18 + [("", "$")]
    content = _hourly_dat([("2023/01/03", pairs)], kind=6)
    parsed = parse(
        _dat_payload("discharge_hourly", 6, content, datetime(2023, 1, 1), datetime(2023, 1, 31)),
        config(),
    )

    assert parsed.outcomes[0].status is OutcomeStatus.SUCCESS
    assert parsed.issues == ()
    assert parsed.rows.height == 20
    assert set(parsed.annotations.observation_tables) == {"jp_mlit.observations"}
    assert not parsed.annotations.series_tables

    table = parsed.annotations.observation_tables["jp_mlit.observations"]
    assert table.row_count == 24
    assert table.unmeasured_count == 4
    assert table.rows["flag"].dtype == pl.String()
    assert table.rows["measured"].to_list()[:5] == [True, True, False, False, False]
    assert table.rows["measured"][-1] is False
    assert table.rows["flag"].to_list()[:5] == [None, "*", "$", "#", "-"]
    assert table.rows["flag"][-1] == "$"
    # 24時 rolls onto 2023-01-04 00:00 and preserves its unmeasured slot timestamp.
    assert table.rows["time"][-1] == datetime(2023, 1, 4, 0, 0)
    assert table.measurement_indices[:5] == (0, 1, None, None, None)
    assert table.measurement_indices[-1] is None


def test_jp_mlit_daily_emits_exact_calendar_day_slots_and_rejects_extra_cells() -> None:
    # February 2023 has 28 days; valid daily rows emit 28 calendar slots and reject padded or summary columns.
    feb_pairs = [("1.10", " "), ("", "$"), ("", "-")] + [("1.20", " ")] * 25
    content = _daily_dat(2023, [(2, feb_pairs, None)], kind=3)
    parsed = parse(
        _dat_payload("stage_daily", 3, content, datetime(2023, 1, 1), datetime(2023, 12, 31)),
        config(),
    )

    assert parsed.outcomes[0].status is OutcomeStatus.SUCCESS
    assert parsed.issues == ()
    assert parsed.rows.height == 26
    table = parsed.annotations.observation_tables["jp_mlit.observations"]
    assert table.row_count == 28
    assert table.unmeasured_count == 2
    assert table.rows["time"].to_list()[:3] == [datetime(2023, 2, 1), datetime(2023, 2, 2), datetime(2023, 2, 3)]
    assert table.rows["time"][-1] == datetime(2023, 2, 28)
    assert table.rows["flag"].to_list()[:4] == [None, "$", "-", None]

    padded_short_month = _daily_dat(2023, [(2, feb_pairs + [("", "")] * 3, None)], kind=3)
    padded_parsed = parse(
        _dat_payload("stage_daily", 3, padded_short_month, datetime(2023, 1, 1), datetime(2023, 12, 31)),
        config(),
    )
    assert padded_parsed.outcomes[0].status is OutcomeStatus.UNSUPPORTED
    assert padded_parsed.rows.is_empty()
    assert padded_parsed.annotations.is_empty

    with_summary = _daily_dat(2023, [(2, feb_pairs, ("1.15", " "))], kind=3)
    summary_parsed = parse(
        _dat_payload("stage_daily", 3, with_summary, datetime(2023, 1, 1), datetime(2023, 12, 31)),
        config(),
    )
    assert summary_parsed.outcomes[0].status is OutcomeStatus.UNSUPPORTED
    assert summary_parsed.rows.is_empty()
    assert summary_parsed.annotations.is_empty


def test_jp_mlit_all_unmeasured_series_retains_slots_at_empty_outcome() -> None:
    pairs = [("", "$")] * 10 + [("", "#")] * 10 + [("", "-")] * 4
    content = _hourly_dat([("2023/01/03", pairs)], kind=6)
    parsed = parse(
        _dat_payload("discharge_hourly", 6, content, datetime(2023, 1, 1), datetime(2023, 1, 31)),
        config(),
    )

    assert parsed.rows.is_empty()
    assert parsed.outcomes[0].status is OutcomeStatus.EMPTY
    assert parsed.issues == ()
    table = parsed.annotations.observation_tables["jp_mlit.observations"]
    assert table.row_count == 24
    assert table.unmeasured_count == 24
    assert table.measurement_indices == (None,) * 24
    assert table.rows["flag"].to_list() == ["$"] * 10 + ["#"] * 10 + ["-"] * 4


def test_jp_mlit_unknown_flag_fails_structural_validation_without_partial_annotations() -> None:
    pairs = [("1.25", " "), ("2.50", "?")] + [("3.00", " ")] * 22
    content = _hourly_dat([("2023/01/03", pairs)], kind=6)
    parsed = parse(
        _dat_payload("discharge_hourly", 6, content, datetime(2023, 1, 1), datetime(2023, 1, 31)),
        config(),
    )

    assert parsed.rows.is_empty()
    assert parsed.annotations.is_empty
    assert parsed.outcomes[0].status is OutcomeStatus.UNSUPPORTED
    assert any(issue.code == "unsupported_source_structure" for issue in parsed.issues)


def test_jp_mlit_public_projection_clipping_cache_reuse_and_bundle_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Day 1: 24 hours ending at 2023-01-04 00:00 (24時); Day 2: 2023-01-04 01時..24時.
    day3 = [("1.0", " "), ("2.0", "*"), ("", "$"), ("", "#")] + [("1.5", " ")] * 19 + [("", "-")]
    day4 = [("4.0", "*"), ("", "$")] + [("5.0", " ")] * 22
    dat_bytes = _hourly_dat([("2023/01/03", day3), ("2023/01/04", day4)], kind=6)
    html_bytes = _html_page(6, _STATION)

    class _Transport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url.endswith(".dat"):
                self.calls.append("dat")
                return TransportResponse(dat_bytes, 200, _RETRIEVED_AT, "text/plain", request.url, {})
            self.calls.append("html")
            return TransportResponse(html_bytes, 200, _RETRIEVED_AT, "text/html", request.url, dict(request.params))

    transport = _Transport()
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    selection = rr.find(provider="jp_mlit", station=_STATION, quantity="discharge", frequency="hourly")
    assert rr.annotations(selection).is_empty()
    base_series = rr.series(selection)

    # Clip to 2023-01-03T01:00..2023-01-03T23:59 so 24時 (2023-01-04 00:00) and all day-4 slots are excluded.
    result = rr.fetch(
        selection,
        start="2023-01-03T01:00:00",
        end="2023-01-03T23:59:59",
        cache="reuse",
        receipts=True,
        on_issue="ignore",
    )
    assert transport.calls == ["html", "dat"]
    assert list(result.data.columns) == list(ObservationDataSchema.polars_schema)
    assert rr.series(result).columns == base_series.columns
    assert result.data.height == 21
    pl_testing.assert_frame_equal(result.to_polars(), result.data)

    catalog = rr.annotations(result)
    assert list(catalog.columns) == list(CATALOG_SCHEMA)
    assert catalog["schema"].to_list() == ["jp_mlit.observations"]
    assert catalog["name"].to_list() == ["flag"]
    assert catalog["dtype"].to_list() == ["String"]
    assert catalog["row_count"].to_list() == [23]
    assert catalog["unmeasured_count"].to_list() == [2]

    direct = rr.annotations(result, schema="jp_mlit.observations").sort("time")
    assert direct["measured"].to_list()[:4] == [True, True, False, False]
    assert direct["flag"].to_list()[:4] == [None, "*", "$", "#"]
    assert direct["time"][-1] == datetime(2023, 1, 3, 23, 0)

    projected = result.to_polars(annotations=True).sort("time")
    assert projected.columns == [*result.data.columns, "flag"]
    assert projected.height == 21
    assert projected["flag"].to_list()[:3] == [None, "*", None]
    pandas_df = result.to_pandas(annotations=True)
    assert isinstance(pandas_df, pd.DataFrame)
    assert list(pandas_df.columns) == [*result.data.columns, "flag"]

    chosen = rr.pick(selection, series_id=rr.series(result)["series_id"].item())
    reused = rr.fetch(
        chosen,
        start="2023-01-03T01:00:00",
        end="2023-01-03T23:59:59",
        cache="reuse",
        receipts=True,
        on_issue="ignore",
    )
    assert transport.calls == ["html", "dat"]
    assert all(entry.authorship is ReceiptAuthorship.STORE_EXCERPT for entry in reused.receipts.entries)
    pl_testing.assert_frame_equal(reused.to_polars(annotations=True).sort("time"), projected)
    pl_testing.assert_frame_equal(rr.annotations(reused, schema="jp_mlit.observations").sort("time"), direct)

    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(rr.annotations(restored), rr.annotations(result))
    pl_testing.assert_frame_equal(rr.annotations(restored, schema="jp_mlit.observations").sort("time"), direct)
    pl_testing.assert_frame_equal(restored.to_polars(annotations=True).sort("time"), projected)


def test_jp_mlit_daily_public_fetch_cache_reuse_and_bundle_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    feb_pairs = [("1.10", " "), ("", "$"), ("", "-")] + [("1.20", " ")] * 25
    dat_bytes = _daily_dat(2023, [(2, feb_pairs, None)], kind=3)
    html_bytes = _html_page(3, _STATION, dat_path="/dat/dload/download/test2023_daily.dat")

    class _Transport:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def send(self, request: TransportRequest) -> TransportResponse:
            if request.url.endswith(".dat"):
                self.calls.append("dat")
                return TransportResponse(dat_bytes, 200, _RETRIEVED_AT, "text/plain", request.url, {})
            self.calls.append("html")
            return TransportResponse(html_bytes, 200, _RETRIEVED_AT, "text/html", request.url, dict(request.params))

    transport = _Transport()
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    selection = rr.find(provider="jp_mlit", station=_STATION, quantity="stage", frequency="daily")
    result = rr.fetch(selection, start="2023-02-01", end="2023-02-05", cache="reuse", on_issue="ignore")
    assert transport.calls == ["html", "dat"]
    assert result.data.height == 3
    direct = rr.annotations(result, schema="jp_mlit.observations").sort("time")
    assert direct["measured"].to_list() == [True, False, False, True, True]
    assert direct["flag"].to_list() == [None, "$", "-", None, None]

    chosen = rr.pick(selection, series_id=rr.series(result)["series_id"].item())
    before = len(transport.calls)
    reused = rr.fetch(chosen, start="2023-02-01", end="2023-02-05", cache="reuse", on_issue="ignore")
    assert len(transport.calls) == before
    pl_testing.assert_frame_equal(rr.annotations(reused, schema="jp_mlit.observations").sort("time"), direct)

    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(rr.annotations(restored, schema="jp_mlit.observations").sort("time"), direct)

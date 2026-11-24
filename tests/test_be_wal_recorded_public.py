"""Public replay of retained Belgium - Wallonia (`be_wal`) captures via find/pick/fetch and boundary probes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit  # noqa: TID251 - URL parsing for retained receipt replay only

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.boundary_probes import (
    FIRST_WALL_CLOCK_TIME,
    LAST_WALL_CLOCK_TIME,
    READING_COUNT,
    LiveBoundaryProbe,
    WallClockExpectation,
    run_manifest_boundary_probes,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.providers.be_wal.annotations import BE_WAL_QUALITY_SCHEMA
from rivretrieve._internal.providers.be_wal.series import PRODUCT_SPECS
from rivretrieve._internal.providers.registration import load_manifest
from rivretrieve._internal.recordings import ReplayTransport
from rivretrieve._internal.selection import _Selection
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse
from tests.test_be_wal_retrieval_recorded import _RECORDING_SLUGS, _envelope_from_capture

_SCOPE = "maintenance/observations/be_wal/retrieval"
_PROVIDER = ProviderId("be_wal")
_DECLARED = load_manifest((_PROVIDER,))

_PROBE_EXPECTATIONS: tuple[tuple[str, str, str, str, int, str, str], ...] = (
    (
        "discharge_complete",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        288,
        "2024-07-01T00:00:00",
        "2024-07-01T23:55:00",
    ),
    (
        "discharge_daily_max",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "discharge_daily_mean",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "discharge_daily_min",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "discharge_hourly_max",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "discharge_hourly_mean",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "discharge_hourly_min",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "discharge_monthly_max",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "discharge_monthly_mean",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "discharge_monthly_min",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "discharge_ultrasonic_complete",
        "2708",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "discharge_ultrasonic_daily_max",
        "2708",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "discharge_ultrasonic_daily_mean",
        "2708",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "discharge_ultrasonic_daily_min",
        "2708",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "discharge_ultrasonic_hourly_max",
        "2708",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "discharge_ultrasonic_hourly_mean",
        "2708",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "discharge_ultrasonic_hourly_min",
        "2708",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "discharge_ultrasonic_monthly_max",
        "2708",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "discharge_ultrasonic_monthly_mean",
        "2708",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "discharge_ultrasonic_monthly_min",
        "2708",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "discharge_ultrasonic_yearly_max",
        "2708",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00",
    ),
    (
        "discharge_ultrasonic_yearly_mean",
        "2708",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00",
    ),
    (
        "discharge_ultrasonic_yearly_min",
        "2708",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00",
    ),
    (
        "discharge_yearly_max",
        "1046",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00",
    ),
    (
        "discharge_yearly_mean",
        "1046",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00",
    ),
    (
        "discharge_yearly_min",
        "1046",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00",
    ),
    (
        "stage_absolute_complete",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        288,
        "2024-07-01T00:00:00",
        "2024-07-01T23:55:00",
    ),
    (
        "stage_absolute_daily_max",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "stage_absolute_daily_mean",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "stage_absolute_daily_min",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "stage_absolute_hourly_max",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "stage_absolute_hourly_mean",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "stage_absolute_hourly_min",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "stage_absolute_monthly_max",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "stage_absolute_monthly_mean",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "stage_absolute_monthly_min",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "stage_absolute_yearly_max",
        "7102",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00",
    ),
    (
        "stage_absolute_yearly_mean",
        "7102",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00",
    ),
    (
        "stage_absolute_yearly_min",
        "7102",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00",
    ),
    (
        "stage_complete",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        288,
        "2024-07-01T00:00:00",
        "2024-07-01T23:55:00",
    ),
    (
        "stage_daily_max",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "stage_daily_mean",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "stage_daily_min",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "stage_hourly_max",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "stage_hourly_mean",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "stage_hourly_min",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "stage_monthly_max",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "stage_monthly_mean",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "stage_monthly_min",
        "1046",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "stage_yearly_max",
        "1046",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00",
    ),
    (
        "stage_yearly_mean",
        "1046",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00",
    ),
    (
        "stage_yearly_min",
        "1046",
        "2024-01-01T00:00:00",
        "2024-01-02T00:00:00",
        1,
        "2024-01-01T00:00:00",
        "2024-01-01T00:00:00",
    ),
    (
        "water_temperature_complete",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        288,
        "2024-07-01T00:00:00",
        "2024-07-01T23:55:00",
    ),
    (
        "water_temperature_daily_max",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "water_temperature_daily_mean",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "water_temperature_daily_min",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-02T23:59:59",
        2,
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
    ),
    (
        "water_temperature_hourly_max",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "water_temperature_hourly_mean",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "water_temperature_hourly_min",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-01T23:59:59",
        24,
        "2024-07-01T00:00:00",
        "2024-07-01T23:00:00",
    ),
    (
        "water_temperature_monthly_max",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "water_temperature_monthly_mean",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
    (
        "water_temperature_monthly_min",
        "7102",
        "2024-07-01T00:00:00",
        "2024-07-02T00:00:00",
        1,
        "2024-07-01T00:00:00",
        "2024-07-01T00:00:00",
    ),
)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _response_matching_request(
    root: Path,
    slug: str,
    request: TransportRequest,
    *,
    group: str = "web",
) -> TransportResponse:
    base = root / _SCOPE / group / slug
    content = base.with_suffix(".body").read_bytes()
    receipt = json.loads(base.with_suffix(".receipt.json").read_text())
    source = urlsplit(str(receipt["url"]))
    expected_params = {k: vals[0] for k, vals in parse_qs(source.query, keep_blank_values=True).items()}
    requested = urlsplit(request.url)
    assert (requested.scheme, requested.netloc, requested.path) == (source.scheme, source.netloc, source.path)
    actual_params = dict(request.params or {})
    assert actual_params == expected_params
    retrieved_raw = str(receipt.get("retrieved_at") or receipt.get("acquired_at")).replace("Z", "+00:00")
    media_type = receipt.get("media_type")
    return TransportResponse(
        content=content,
        status_code=int(str(receipt["http_status"])),
        retrieved_at=datetime.fromisoformat(retrieved_raw),
        content_type=str(media_type) if isinstance(media_type, str) and media_type else None,
        url=f"{source.scheme}://{source.netloc}{source.path}",
        request_parameters=actual_params,
    )


def _select_products(station: str, *products: str) -> _Selection:
    selected = rr.find(provider="be_wal", station=station)
    series_ids = rr.as_frame(selected).filter(pl.col("product_id").is_in(products))["series_id"].to_list()
    assert len(series_ids) == len(products)
    picked = rr.pick(selected, series_id=series_ids)
    assert isinstance(picked, _Selection)
    return picked


@pytest.mark.recorded(_SCOPE)
def test_each_be_wal_product_has_an_exact_live_replay_boundary_probe(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))

    def _make_probe(
        product_id: str,
        station: str,
        start: str,
        end: str,
        count: int,
        first_ts: str,
        last_ts: str,
    ) -> LiveBoundaryProbe:
        slug = f"prod-{station}-{product_id.replace('_', '-')}"

        def _run(replay: ReplayTransport) -> pl.DataFrame:
            monkeypatch.setattr(discovery, "HttpClient", lambda: replay)
            return rr.fetch(_select_products(station, product_id), start=start, end=end, cache="bypass").data

        return LiveBoundaryProbe(
            provider_id=_PROVIDER,
            product_id=ProductId(product_id),
            recordings=(_envelope_from_capture(retained_evidence_root, slug),),
            assertions={
                READING_COUNT: count,
                FIRST_WALL_CLOCK_TIME: WallClockExpectation(first_ts, "+01:00"),
                LAST_WALL_CLOCK_TIME: WallClockExpectation(last_ts, "+01:00"),
            },
            run=_run,
        )

    probes = tuple(_make_probe(*row) for row in _PROBE_EXPECTATIONS)
    results = run_manifest_boundary_probes(_DECLARED, probes)
    assert len(results) == len(PRODUCT_SPECS) == 62


@pytest.mark.recorded(_SCOPE)
def test_recorded_public_all_62_products_replay_via_find_pick_fetch(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = ReplayTransport(tuple(_envelope_from_capture(retained_evidence_root, slug) for slug in _RECORDING_SLUGS))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    for product_id, station, start, end, expected_rows, _, _ in _PROBE_EXPECTATIONS:
        sel = _select_products(station, product_id)
        cat_df = rr.series(sel)
        res = rr.fetch(sel, start=start, end=end, cache="bypass", receipts=True)
        assert [issue.code for issue in res.issues] == ["provenance.license_not_established"]
        assert res.data.height == expected_rows
        assert res.data["series_id"].unique().to_list() == cat_df["series_id"].to_list()
        assert res.data["facts_id"].unique().to_list() == cat_df["facts_id"].to_list()
        assert res.data["time_zone"].unique().to_list() == ["+01:00"]
        assert res.data["unit"].unique().to_list() == cat_df["unit"].to_list()
        assert [o.status for o in res.outcomes] == [OutcomeStatus.SUCCESS]
        assert res.receipts is not None and len(res.receipts.entries) == 1


@pytest.mark.recorded(_SCOPE)
def test_recorded_public_edge_cases_dst_nulls_flood_negative_hsonde_1929_multichunk_and_empty(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = ReplayTransport(tuple(_envelope_from_capture(retained_evidence_root, slug) for slug in _RECORDING_SLUGS))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    dst_spring = rr.fetch(
        _select_products("3643", "discharge_hourly_mean"),
        start="2024-03-30",
        end="2024-04-01T23:00:00",
        cache="bypass",
    )
    assert dst_spring.data.height == 72
    assert rr.to_utc(dst_spring).data["time"].n_unique() == 72

    dst_autumn = rr.fetch(
        _select_products("3643", "stage_hourly_mean"),
        start="2024-10-26",
        end="2024-10-28T23:00:00",
        cache="bypass",
    )
    assert dst_autumn.data.height == 72
    assert rr.to_utc(dst_autumn).data["time"].n_unique() == 72

    null_res = rr.fetch(
        _select_products("3561", "discharge_daily_mean"),
        start="2011-08-01",
        end="2011-08-10",
        cache="bypass",
    )
    assert null_res.data.height == 10
    assert null_res.data["value"].null_count() == 5
    q_ann = rr.annotations(null_res, schema=BE_WAL_QUALITY_SCHEMA.schema_id)
    assert q_ann["measured"].to_list() == [True] * 10
    assert q_ann.filter((pl.col("quality_code") == -1) & pl.col("quality_code_name").is_null()).height == 5

    flood_res = rr.fetch(
        _select_products("6228", "discharge_daily_mean"),
        start="2021-07-12",
        end="2021-07-18",
        cache="bypass",
    )
    assert flood_res.data["value"].max() == pytest.approx(402.9)
    flood_ann = rr.annotations(flood_res, schema=BE_WAL_QUALITY_SCHEMA.schema_id)
    assert flood_ann.filter((pl.col("quality_code") == 200) & (pl.col("quality_code_name") == "Unknown")).height >= 1

    neg_res = rr.fetch(
        _select_products("L8910", "stage_daily_mean"),
        start="2024-08-18",
        end="2024-08-25",
        cache="bypass",
    )
    assert neg_res.data.height == 8
    assert neg_res.data.filter(pl.col("value") < 0).height == 1

    hsonde_res = rr.fetch(
        _select_products("5922", "stage_daily_mean"),
        start="2024-07-01",
        end="2024-07-03",
        cache="bypass",
    )
    assert hsonde_res.data.height == 3

    ascii_temp = rr.fetch(
        _select_products("L8220", "water_temperature_daily_mean"),
        start="2024-07-01",
        end="2024-07-05",
        cache="bypass",
    )
    assert ascii_temp.data.height == 5
    assert ascii_temp.data["unit"].unique().to_list() == ["degC"]

    hist_res = rr.fetch(
        _select_products("9434", "discharge_daily_mean"),
        start="1929-01-01",
        end="1929-01-10",
        cache="bypass",
    )
    assert hist_res.data.height == 10
    assert hist_res.data["time"][0] == datetime(1929, 1, 1)

    res_365 = rr.fetch(
        _select_products("2708", "discharge_ultrasonic_complete"),
        start="2024-01-01",
        end="2024-12-31T23:59:59",
        cache="bypass",
    )
    assert res_365.data.height == 8_486

    res_3650 = rr.fetch(
        _select_products("9434", "discharge_hourly_mean"),
        start="2016-01-01",
        end="2026-01-05T23:00:00",
        cache="bypass",
    )
    assert res_3650.data.height == 87_792

    empty_res = rr.fetch(
        _select_products("1046", "discharge_daily_mean"),
        start="2030-01-01",
        end="2030-01-02",
        cache="bypass",
    )
    assert empty_res.data.is_empty()
    assert [o.status for o in empty_res.outcomes] == [OutcomeStatus.EMPTY]

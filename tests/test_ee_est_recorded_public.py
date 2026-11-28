"""Public replay of retained Estonia Keskkonnaagentuur (`ee_est`) captures via find/pick/fetch."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit  # noqa: TID251 - URL parsing for retained receipt replay only

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.providers.ee_est.annotations import EE_EST_ESTMODEL_SCHEMA
from rivretrieve._internal.providers.ee_est.series import PRODUCT_SPECS
from rivretrieve._internal.recordings import ReplayTransport
from rivretrieve._internal.source_series import InventoryCompleteness, OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse
from tests.test_ee_est_retrieval_recorded import _AHJA_EXPECTED, _RECORDING_SLUGS, _envelope_from_capture

_SCOPE = "maintenance/observations/ee_est/retrieval"

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _response_matching_request(
    root: Path,
    slug: str,
    request: TransportRequest,
    *,
    group: str = "web",
) -> TransportResponse:
    """Replay a recorded capture when the request URL and parameters match."""
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


@pytest.mark.recorded(_SCOPE)
def test_recorded_public_all_18_products_replay_via_find_pick_fetch(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = ReplayTransport(tuple(_envelope_from_capture(retained_evidence_root, slug) for slug in _RECORDING_SLUGS))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    for spec in PRODUCT_SPECS:
        found = rr.find(provider="ee_est", station="SJA8821000")
        sel = rr.pick(found, quantity=spec.quantity, frequency=spec.frequency, statistic=spec.statistic)
        if spec.source_api == "estmodel":
            start = (
                "2026-01-01"
                if spec.product_id in {"discharge_daily_mean", "water_temperature_daily_mean"}
                else "2025-01-01"
            )
            end = "2026-11-22"
            expected_rows = 326 if start == "2026-01-01" else 691
        else:
            start = "2024-03-30"
            end = "2024-04-01T23:59:59.999999"
            expected_rows = 72

        expected_pub, expected_sid, expected_fid, first_pair, last_pair = _AHJA_EXPECTED[spec.product_id]
        res = rr.fetch(sel, start=start, end=end, cache="bypass", receipts=True)
        assert res.issues == ()
        assert res.data.height == expected_rows
        assert res.data["series_id"].unique().to_list() == [expected_sid]
        assert res.data["facts_id"].unique().to_list() == [expected_fid]
        assert rr.series(res)["published_id"].to_list() == [expected_pub]
        rows_sorted = res.data.sort("time")
        assert rows_sorted["time"][0] == first_pair[0]
        assert rows_sorted["value"][0] == pytest.approx(first_pair[1])
        assert rows_sorted["time"][-1] == last_pair[0]
        assert rows_sorted["value"][-1] == pytest.approx(last_pair[1])
        assert [o.status for o in res.outcomes] == [OutcomeStatus.SUCCESS]
        assert res.receipts is not None and len(res.receipts.entries) == 1
        if spec.source_api == "estmodel":
            ann = rr.annotations(res, schema=EE_EST_ESTMODEL_SCHEMA.schema_id)["qualityFlag"].to_list()
            if spec.quantity == "temperature":
                assert all(flag is None for flag in ann)
            elif start == "2026-01-01":
                assert ann == ["UNCHECKED"] * 326
            else:
                assert ann[:365] == [None] * 365
                assert ann[365:] == ["UNCHECKED"] * 326
            if spec.product_id == "stage_daily_mean":
                annotated = res.to_polars(annotations=True).sort("time")
                by_time = {row["time"]: (row["value"], row["qualityFlag"]) for row in annotated.to_dicts()}
                assert by_time[datetime(2025, 12, 31)][0] == pytest.approx(1.04)
                assert by_time[datetime(2025, 12, 31)][1] is None
                assert by_time[datetime(2026, 1, 1)][0] == pytest.approx(1.01)
                assert by_time[datetime(2026, 1, 1)][1] == "UNCHECKED"
        else:
            assert res.data["time_zone"].unique().to_list() == ["+00:00"]
            if spec.product_id == "stage_hourly_mean":
                vals_by_time = dict(zip(rows_sorted["time"].to_list(), rows_sorted["value"].to_list(), strict=True))
                assert vals_by_time[datetime(2024, 3, 31, 0, 0)] == pytest.approx(1.1414)
                assert vals_by_time[datetime(2024, 3, 31, 1, 0)] == pytest.approx(1.1383)
                assert vals_by_time[datetime(2024, 3, 31, 2, 0)] == pytest.approx(1.1353)

    # Autumn DST transition on UTC hourly timeline (41061:WL avg)
    autumn_sel = rr.find(provider="ee_est", station="SJA8821000", quantity="stage", frequency="PT1H", statistic="mean")
    autumn = rr.fetch(autumn_sel, start="2024-10-26", end="2024-10-28T23:59:59.999999", cache="bypass")
    assert autumn.data.height == 72
    assert autumn.data["series_id"].unique().to_list() == [
        "d8882a9d825e990daeddb93d1989506c4ef4fa48845c97f4bb719bbbc1ed5383"
    ]
    autumn_map = dict(zip(autumn.data["time"].to_list(), autumn.data["value"].to_list(), strict=True))
    assert autumn_map[datetime(2024, 10, 27, 0, 0)] == pytest.approx(0.516)
    assert autumn_map[datetime(2024, 10, 27, 1, 0)] == pytest.approx(0.516)
    assert autumn_map[datetime(2024, 10, 27, 2, 0)] == pytest.approx(0.515)


@pytest.mark.recorded(_SCOPE)
def test_recorded_public_edge_cases_deep_history_negative_stage_nulls_and_dual_code(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = ReplayTransport(tuple(_envelope_from_capture(retained_evidence_root, slug) for slug in _RECORDING_SLUGS))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    tartu_sel = rr.find(provider="ee_est", station="SJA7331000", quantity="stage", frequency="P1D", statistic="mean")
    tartu = rr.fetch(tartu_sel, start="1867-01-01", end="1891-12-31", cache="bypass")
    assert tartu.data.height == 5432
    assert tartu.data["series_id"].unique().to_list() == [
        "a9318e9dccbca0930d28b622ba159e2ac66d0084c746c379278225cb2d8f71cc"
    ]
    tartu_sorted = tartu.data.sort("time")
    assert tartu_sorted["time"][0] == datetime(1867, 4, 1)
    assert tartu_sorted["value"][0] == pytest.approx(1.73)
    assert tartu_sorted["time"][-1] == datetime(1891, 11, 13)
    assert tartu_sorted["value"][-1] == pytest.approx(0.35)

    rapina_sel = rr.find(provider="ee_est", station="SJA4456000", quantity="stage", frequency="P1D", statistic="mean")
    rapina = rr.fetch(rapina_sel, start="2025-01-01", end="2026-11-22", cache="bypass")
    assert rapina.data.height == 691
    assert rapina.data["series_id"].unique().to_list() == [
        "a6fb603be5e66b1067fce1b50e720ac2dc91e445a59ad5a536ac471f47431949"
    ]
    assert rapina.data.filter(pl.col("value") < 0).height == 101
    rapina_map = dict(zip(rapina.data["time"].to_list(), rapina.data["value"].to_list(), strict=True))
    assert rapina_map[datetime(2025, 4, 18)] == pytest.approx(-0.04)
    assert rapina_map[datetime(2025, 10, 5)] == pytest.approx(-0.23)
    assert rapina_map[datetime(2026, 11, 22)] == pytest.approx(-0.05)

    konuvere_sel = rr.find(
        provider="ee_est", station="SJA9204000", quantity="stage", frequency="PT1H", statistic="mean"
    )
    konuvere = rr.fetch(
        konuvere_sel,
        start="2025-11-27",
        end="2025-11-27T23:59:59.999999",
        cache="bypass",
    )
    assert konuvere.data.height == 9
    assert konuvere.data["series_id"].unique().to_list() == [
        "2bc275081c14cb367b39c6ac3d43b56051cb06f5e5267b904c421a274ce10992"
    ]
    konuvere_sorted = konuvere.data.sort("time")
    assert konuvere_sorted["time"][0] == datetime(2025, 11, 27, 0, 0)
    assert konuvere_sorted["time"][-1] == datetime(2025, 11, 27, 8, 0)
    assert konuvere.data["value"].null_count() == 9

    # Unrestricted pair selection on dual-code SJA5524000 queries BOTH 41022 and 41960 and emits COMPLETE.
    dual_sel = rr.find(provider="ee_est", station="SJA5524000", quantity="stage", frequency="PT1H", statistic="mean")
    dual = rr.fetch(
        dual_sel,
        start="2026-10-01",
        end="2026-10-01T23:59:59.999999",
        cache="bypass",
        receipts=True,
    )
    expected_41022_sid = "1091ce4c857da51bb29fc8c74c87b04065d61aafb129a7cadf3c5fb2aaa20249"
    assert dual.data.height == 24
    assert dual.data["series_id"].unique().to_list() == [expected_41022_sid]
    assert rr.series(dual)["published_id"].to_list() == ["41022:WL avg"]
    dual_sorted = dual.data.sort("time")
    assert dual_sorted["time"][0] == datetime(2026, 10, 1, 0, 0)
    assert dual_sorted["value"][0] == pytest.approx(0.3447)
    assert dual_sorted["time"][-1] == datetime(2026, 10, 1, 23, 0)
    assert dual_sorted["value"][-1] == pytest.approx(0.3637)
    assert dual.receipts is not None and len(dual.receipts.entries) == 2
    assert all(
        inv.completeness is InventoryCompleteness.COMPLETE
        and inv.members == (expected_41022_sid,)
        and sum(1 for ev in inv.evidence if ev.startswith("source-call:")) == 2
        for inv in dual.inventories
    )

    empty_sel = rr.find(
        provider="ee_est", station="SJA8821000", quantity="discharge", frequency="P1D", statistic="mean"
    )
    empty_2030 = rr.fetch(
        empty_sel,
        start="2030-01-01",
        end="2030-12-31",
        cache="bypass",
    )
    assert empty_2030.data.is_empty()
    assert [o.status for o in empty_2030.outcomes] == [OutcomeStatus.EMPTY]

"""Public replay of retained Estonia Keskkonnaagentuur (`ee_est`) captures via find/pick/fetch."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.providers.ee_est.annotations import EE_EST_ESTMODEL_SCHEMA
from rivretrieve._internal.providers.ee_est.series import PRODUCT_SPECS
from rivretrieve._internal.recordings import ReplayTransport
from rivretrieve._internal.source_series import OutcomeStatus
from tests.test_ee_est_retrieval_recorded import _RECORDING_SLUGS, _envelope_from_capture

_SCOPE = "maintenance/observations/ee_est/retrieval"

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _select_products(station: str, *products: str) -> rr.Selection:
    selected = rr.find(provider="ee_est", station=station)
    series_ids = rr.as_frame(selected).filter(pl.col("product_id").is_in(products))["series_id"].to_list()
    assert len(series_ids) == len(products)
    return rr.pick(selected, series_id=series_ids)


@pytest.mark.recorded(_SCOPE)
def test_recorded_public_all_18_products_replay_via_find_pick_fetch(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = ReplayTransport(tuple(_envelope_from_capture(retained_evidence_root, slug) for slug in _RECORDING_SLUGS))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    for spec in PRODUCT_SPECS:
        sel = _select_products("SJA8821000", spec.product_id)
        cat_df = rr.series(sel)
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

        res = rr.fetch(sel, start=start, end=end, cache="bypass", receipts=True)
        assert res.issues == ()
        assert res.data.height == expected_rows
        assert res.data["series_id"].unique().to_list() == cat_df["series_id"].to_list()
        assert res.data["facts_id"].unique().to_list() == cat_df["facts_id"].to_list()
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
        else:
            assert res.data["time_zone"].unique().to_list() == ["+00:00"]


@pytest.mark.recorded(_SCOPE)
def test_recorded_public_edge_cases_deep_history_negative_stage_nulls_and_dual_code(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = ReplayTransport(tuple(_envelope_from_capture(retained_evidence_root, slug) for slug in _RECORDING_SLUGS))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    tartu = rr.fetch(
        _select_products("SJA7331000", "stage_daily_mean"), start="1867-01-01", end="1891-12-31", cache="bypass"
    )
    assert tartu.data.height == 5432
    assert tartu.data["time"][0] == datetime(1867, 4, 1)

    rapina = rr.fetch(
        _select_products("SJA4456000", "stage_daily_mean"), start="2025-01-01", end="2026-11-22", cache="bypass"
    )
    assert rapina.data.height == 691
    assert rapina.data.filter(pl.col("value") < 0).height == 101

    konuvere = rr.fetch(
        _select_products("SJA9204000", "stage_hourly_mean"),
        start="2025-11-27",
        end="2025-11-27T23:59:59.999999",
        cache="bypass",
    )
    assert konuvere.data.height == 9
    assert konuvere.data["value"].null_count() == 9

    dual = rr.fetch(
        _select_products("SJA5524000", "stage_hourly_mean"),
        start="2026-10-01",
        end="2026-10-01T23:59:59.999999",
        cache="bypass",
    )
    assert dual.data.height == 24
    assert (
        dual.data["series_id"].unique().to_list()
        == rr.series(_select_products("SJA5524000", "stage_hourly_mean"))["series_id"].to_list()
    )

    empty_2030 = rr.fetch(
        _select_products("SJA8821000", "discharge_daily_mean"),
        start="2030-01-01",
        end="2030-12-31",
        cache="bypass",
    )
    assert empty_2030.data.is_empty()
    assert [o.status for o in empty_2030.outcomes] == [OutcomeStatus.EMPTY]

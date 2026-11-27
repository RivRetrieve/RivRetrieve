"""Public replay of retained Ireland OPW (`ie_opw`) captures via find/pick/fetch."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.discovery import EmptySelectionError, _Selection
from rivretrieve._internal.providers.ie_opw.annotations import (
    IE_OPW_DAILY_STAGE_SCHEMA,
    IE_OPW_SERIES_SCHEMA,
)
from rivretrieve._internal.recordings import ReplayTransport
from rivretrieve._internal.source_series import OutcomeStatus
from rivretrieve._internal.transport import TransportRequest, TransportResponse
from tests.test_ie_opw_retrieval_recorded import _RECORDING_SLUGS, _envelope_from_capture

_SCOPE = "maintenance/observations/ie_opw/retrieval"

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _select_products(station: str, *products: str) -> _Selection:
    selected = rr.find(provider="ie_opw", station=station)
    series_ids = rr.as_frame(selected).filter(pl.col("product_id").is_in(products))["series_id"].to_list()
    assert len(series_ids) == len(products)
    picked = rr.pick(selected, series_id=series_ids)
    assert isinstance(picked, _Selection)
    return picked


class _ForbidSendTransport:
    def send(self, request: TransportRequest) -> TransportResponse:
        raise AssertionError(f"cache reuse must not send HTTP requests: {request.url}")


@pytest.mark.recorded(_SCOPE)
def test_recorded_public_all_12_products_replay_and_cache_reuse_via_find_pick_fetch(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = ReplayTransport(tuple(_envelope_from_capture(retained_evidence_root, slug) for slug in _RECORDING_SLUGS))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    sel = rr.find(provider="ie_opw", station="01041")
    cat_df = rr.series(sel)
    assert cat_df.height == 12

    res = rr.fetch(sel, start="2025-07-15", end="2025-07-15T23:59:59.999999", cache="reuse", receipts=True)
    assert res.issues == ()
    assert res.data.height == 225  # 9 daily + 96 Q + 96 S + 24 TWater
    assert res.data["product_id"].n_unique() == 12
    assert res.receipts is not None and len(res.receipts.entries) == 6
    assert all(o.status is OutcomeStatus.SUCCESS for o in res.outcomes)

    res_series = res.data.select("product_id", "series_id", "facts_id").unique().sort("product_id")
    expected_series = cat_df.select("product_id", "series_id", "facts_id").sort("product_id")
    assert_frame_equal(res_series, expected_series)

    stage_ann = rr.annotations(res, schema=IE_OPW_DAILY_STAGE_SCHEMA.schema_id)
    assert stage_ann.height == 3
    assert stage_ann["aggregation_accuracy_pct"].to_list() == [100.0, 100.0, 100.0]

    # Offline subset replay from cache must not perform HTTP sends.
    monkeypatch.setattr(discovery, "HttpClient", _ForbidSendTransport)
    subset_sel = _select_products("01041", "stage_daily_min")
    reused = rr.fetch(subset_sel, start="2025-07-15", end="2025-07-15", cache="reuse")
    assert_frame_equal(reused.data, res.data.filter(pl.col("product_id") == "stage_daily_min"))


@pytest.mark.recorded(_SCOPE)
def test_recorded_public_edge_cases_1940s_negative_od_unmeasured_and_empty_blocks(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = ReplayTransport(tuple(_envelope_from_capture(retained_evidence_root, slug) for slug in _RECORDING_SLUGS))
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    boyne_daily = rr.fetch(
        _select_products("07012", "discharge_daily_mean", "stage_daily_mean"),
        start="1940-06-27",
        end="1940-06-28",
        cache="bypass",
    )
    assert boyne_daily.data.height == 4
    assert boyne_daily.data["time"].min() == datetime(1940, 6, 27)

    boyne_zip = rr.fetch(
        _select_products("07012", "discharge_instantaneous", "stage_instantaneous"),
        start="1940-06-27T13:00:00",
        end="1940-06-27T15:00:00",
        cache="bypass",
    )
    assert boyne_zip.data.filter(pl.col("product_id") == "discharge_instantaneous")["time"].min() == datetime(
        1940, 6, 27, 13, 0
    )

    galway_neg = rr.fetch(
        _select_products("30061", "stage_daily_min", "stage_instantaneous"),
        start="2024-01-01",
        end="2026-11-23",
        cache="bypass",
    )
    assert galway_neg.data.filter((pl.col("product_id") == "stage_daily_min") & (pl.col("value") < 0)).height > 0
    assert galway_neg.data.filter((pl.col("product_id") == "stage_instantaneous") & (pl.col("value") < 0)).height > 0

    # Level-only 06015 excludes discharge_daily_mean in catalogue discovery.
    assert (
        "discharge_daily_mean" not in rr.as_frame(rr.find(provider="ie_opw", station="06015"))["product_id"].to_list()
    )
    assert (
        "discharge_instantaneous"
        not in rr.as_frame(rr.find(provider="ie_opw", station="06025"))["product_id"].to_list()
    )

    historic_06025 = rr.fetch(
        _select_products("06025", "discharge_daily_mean"),
        start="1972-01-01",
        end="2026-11-22",
        cache="bypass",
    )
    assert historic_06025.data.height == 2094
    assert [o.status for o in historic_06025.outcomes] == [OutcomeStatus.SUCCESS]
    assert (
        rr.annotations(historic_06025, schema=IE_OPW_SERIES_SCHEMA.schema_id).filter(pl.col("measured").not_()).height
        == 17956
    )

    inst_14124 = rr.fetch(
        _select_products("14124", "water_temperature_instantaneous"),
        start="2022-08-14",
        end="2025-10-07T12:00:00",
        cache="bypass",
    )
    assert (
        rr.annotations(inst_14124, schema=IE_OPW_SERIES_SCHEMA.schema_id).filter(pl.col("measured").not_()).height == 94
    )

    temp_03055 = rr.fetch(
        _select_products("03055", "water_temperature_daily_mean"),
        start="2016-02-07",
        end="2026-11-23",
        cache="bypass",
    )
    assert temp_03055.data.height == 3942
    assert (
        rr.annotations(temp_03055, schema=IE_OPW_SERIES_SCHEMA.schema_id).filter(pl.col("measured").not_()).height == 1
    )

    # Confirmed unavailable water temperature on 18121 is excluded from discovery.
    empty_18121 = rr.find(provider="ie_opw", station="18121", quantity="temperature")
    assert empty_18121.series == ()
    with pytest.raises(EmptySelectionError, match="ie_opw"):
        rr.fetch(empty_18121, start="2025-01-01", end="2025-12-31", cache="bypass")

    # Querying historic 06025 outside its measured 1972..2004 period returns UNRESOLVED.
    out_of_range_06025 = rr.fetch(
        _select_products("06025", "discharge_daily_mean"),
        start="2025-01-01",
        end="2025-12-31",
        cache="bypass",
    )
    assert out_of_range_06025.data.is_empty()
    assert [o.status for o in out_of_range_06025.outcomes] == [OutcomeStatus.UNRESOLVED]

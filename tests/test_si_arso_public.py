"""Live sanity integration tests against Slovenia ARSO public hydrological endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.source_series import OutcomeStatus


@pytest.mark.live
def test_live_si_arso_archive_historical_reach_extremes_amp_and_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "live_cache"))

    # 1. Modern daily archive on 1060 Gornja Radgona I (2024) + sub-window cache="reuse" + audit_cache.
    sel_1060 = rr.find(provider="si_arso", station="1060", quantity="discharge", frequency="P1D")
    res_2024 = rr.fetch(sel_1060, start="2024-01-01", end="2024-12-31", cache="reuse", on_issue="raise")
    assert res_2024.issues == ()
    assert res_2024.data.height == 366
    assert rr.series(res_2024, annotations=True)["data_status"].to_list() == ["Verificirani podatki"]

    reused = rr.fetch(sel_1060, start="2024-06-01", end="2024-06-07", cache="reuse", on_issue="raise")
    assert reused.data.height == 7
    assert rr.audit_cache("si_arso").rows_checked >= 366

    # 2. Deep 1895 historical reach on 3660 Sava - Litija I (per provider-ports.md historical verification).
    sel_3660 = rr.find(provider="si_arso", station="3660", quantity="discharge", frequency="P1D")
    res_1895 = rr.fetch(sel_3660, start="1895-01-01", end="1895-12-31", cache="bypass", on_issue="raise")
    assert res_1895.issues == ()
    assert res_1895.data.height == 365

    # 3. Unpublished post-2024 years omit warning issues under on_issue="raise".
    res_2025 = rr.fetch(sel_1060, start="2025-01-01", end="2026-01-01", cache="bypass", on_issue="raise")
    assert res_2025.issues == ()
    assert res_2025.data.is_empty()
    assert [o.status for o in res_2025.outcomes] == [OutcomeStatus.UNRESOLVED]

    # 4. Monthly extremes on 1060.
    sel_eks = rr.find(provider="si_arso", station="1060", quantity="discharge", frequency="P1M", statistic="max")
    res_eks = rr.fetch(sel_eks, start="2024-01-01", end="2024-12-31", cache="bypass", on_issue="raise")
    assert res_eks.issues == ()
    assert res_eks.data.height == 12

    # 5. Live operational rolling 10-min amp/ on 1060 + rr.to_utc.
    now = datetime.now(UTC).date()
    start_s = (now - timedelta(days=2)).isoformat()
    sel_amp = rr.pick(rr.find(provider="si_arso", station="1060"), variant="operational_10min")
    res_amp = rr.fetch(sel_amp, start=start_s, cache="bypass", on_issue="raise")
    assert res_amp.issues == ()
    assert not res_amp.data.filter(pl.col("quantity") == "discharge").is_empty()
    assert set(res_amp.data["time_zone"].to_list()) == {"+01:00"}
    assert set(rr.to_utc(res_amp).data["time_zone"].to_list()) == {"+00:00"}

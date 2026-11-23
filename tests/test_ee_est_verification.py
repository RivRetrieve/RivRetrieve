"""Step 6 verification replay of Estonia (`ee_est`) GRDC-Caravan benchmark sample, historical reach, and cache audit."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.recordings import ReplayTransport
from rivretrieve._internal.source_series import OutcomeStatus
from tests.test_ee_est_recorded_public import _select_products
from tests.test_ee_est_retrieval_recorded import _envelope_from_capture

_SCOPE = "maintenance/observations/ee_est/retrieval"

_VERIFICATION_SLUGS: tuple[str, ...] = (
    "grdc-01-sja2259000-01",
    "grdc-02-sja1098000-01",
    "grdc-03-sja4385000-01",
    "grdc-04-sja3959000-01",
    "grdc-05-sja3814000-01",
    "grdc-06-sja2558000-01",
    "grdc-07-sja2129000-01",
    "grdc-08-sja2072000-01",
    "grdc-09-sja7331000-01",
    "grdc-10-sja9946000-01",
    "deep-01-sja7331000-h-1867-01",
    "deep-02-sja7331000-q-1902-01",
    "deep-03-sja2718000-q-1902-01",
    "deep-04-sja8821000-h-hourly-2012-01",
    "deep-05-sja8821000-q-hourly-2012-01",
    "deep-06-sja7331000-q-1922-01",
)

pytestmark = pytest.mark.usefixtures("reuse_packaged_catalogues")


def _verification_replay(root: Path) -> ReplayTransport:
    envelopes = [_envelope_from_capture(root, slug, subdir="verification/web") for slug in _VERIFICATION_SLUGS]
    return ReplayTransport(tuple(envelopes))


@pytest.mark.recorded(_SCOPE)
def test_recorded_verification_10_grdc_gauges_deep_history_and_cache_audit(
    retained_evidence_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    replay = _verification_replay(retained_evidence_root)
    monkeypatch.setattr(discovery, "HttpClient", lambda: replay)

    sampled_stations = (
        "SJA2259000",
        "SJA1098000",
        "SJA4385000",
        "SJA3959000",
        "SJA3814000",
        "SJA2558000",
        "SJA2129000",
        "SJA2072000",
        "SJA7331000",
        "SJA9946000",
    )
    for station_id in sampled_stations:
        sel = _select_products(station_id, "discharge_daily_mean")
        res = rr.fetch(sel, start="2013-01-01", end="2022-12-31", cache="reuse", receipts=True)
        assert res.issues == ()
        assert res.data.height == 3652
        assert [o.status for o in res.outcomes] == [OutcomeStatus.SUCCESS]

    # Deep historical reach witnesses: 1867-04-01 Tartu H, 1902-09-22 Vasknarva Q, 1922-01-01 Tartu Q, 2012 hourly.
    h_1867 = rr.fetch(
        _select_products("SJA7331000", "stage_daily_mean"), start="1867-01-01", end="1867-12-31", cache="reuse"
    )
    assert h_1867.data.height == 240
    assert h_1867.data.sort("time")["time"][0] == datetime(1867, 4, 1)

    q_1902_empty = rr.fetch(
        _select_products("SJA7331000", "discharge_daily_mean"), start="1902-01-01", end="1921-12-31", cache="bypass"
    )
    assert q_1902_empty.data.is_empty()
    assert [o.status for o in q_1902_empty.outcomes] == [OutcomeStatus.EMPTY]

    q_vask_1902 = rr.fetch(
        _select_products("SJA2718000", "discharge_daily_mean"), start="1902-01-01", end="1903-12-31", cache="reuse"
    )
    assert q_vask_1902.data.height == 466
    assert q_vask_1902.data.sort("time")["time"][0] == datetime(1902, 9, 22)

    q_tartu_1922 = rr.fetch(
        _select_products("SJA7331000", "discharge_daily_mean"), start="1922-01-01", end="1922-12-31", cache="reuse"
    )
    assert q_tartu_1922.data.height == 365
    assert q_tartu_1922.data.sort("time")["time"][0] == datetime(1922, 1, 1)

    for product_id in ("stage_hourly_mean", "discharge_hourly_mean"):
        hr_2012 = rr.fetch(
            _select_products("SJA8821000", product_id),
            start="2012-01-01",
            end="2012-01-07T23:59:59.999999",
            cache="reuse",
        )
        assert hr_2012.data.height == 168
        assert hr_2012.data.sort("time")["time"][0] == datetime(2012, 1, 1, 0, 0)
        assert hr_2012.data["time_zone"].unique().to_list() == ["+00:00"]

    # Cache inspection, offline audit, and bundle round-trip checks.
    status = rr.cache_status("ee_est")
    assert len(status.coverage) == 15
    assert len({item.series_id for item in status.coverage}) == 14
    audit = rr.audit_cache("ee_est")
    assert str(audit.provider_id) == "ee_est"
    assert audit.partitions_checked >= 14
    assert audit.rows_checked > 36000

    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    offline = rr.fetch(
        _select_products("SJA7331000", "discharge_daily_mean"), start="2013-01-01", end="2022-12-31", cache="reuse"
    )
    assert offline.data.height == 3652
    restored = rr.from_bundle(rr.to_bundle(offline))
    assert_frame_equal(restored.data, offline.data)

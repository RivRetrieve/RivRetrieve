"""Step 6 verification replay of Belgium - Wallonia (`be_wal`) GRDC-Caravan benchmark sample, historical reach, and cache audit."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from polars.testing import assert_frame_equal

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.observations import ObservationResult
from rivretrieve._internal.providers.be_wal.annotations import BE_WAL_QUALITY_SCHEMA
from rivretrieve._internal.recordings import ReplayTransport
from rivretrieve._internal.source_series import OutcomeStatus
from tests.test_be_wal_recorded_public import _select_products
from tests.test_be_wal_retrieval_recorded import _envelope_from_capture

_SCOPE = "maintenance/observations/be_wal/retrieval"

_GRDC_BENCHMARK_SAMPLES: tuple[tuple[str, str, str, int, int], ...] = (
    ("grdc-01-8622-q-2000-2012", "8622", "discharge_daily_mean", 4749, 0),
    ("grdc-02-2971-q-2000-2012", "2971", "discharge_daily_mean", 4749, 0),
    ("grdc-03-1046-q-2000-2012", "1046", "discharge_daily_mean", 4749, 0),
    ("grdc-04-9071-q-2000-2012", "9071", "discharge_daily_mean", 4749, 0),
    ("grdc-05-6228-q-2000-2012", "6228", "discharge_daily_mean", 4749, 0),
    ("grdc-06-5921-q-2000-2012", "5921", "discharge_daily_mean", 4749, 0),
    ("grdc-07-8702-q-2000-2012", "8702", "discharge_daily_mean", 4749, 0),
    ("grdc-08-3282-q-2000-2012", "3282", "discharge_ultrasonic_daily_mean", 4749, 22),
    ("grdc-09-9651-q-2000-2012", "9651", "discharge_daily_mean", 4749, 0),
    ("grdc-10-8221-q-2000-2012", "8221", "discharge_daily_mean", 4749, 0),
)

_DEEP_PROBES: tuple[tuple[str, str, str, str, str, int, int, datetime], ...] = (
    (
        "deep-01-9434-q20-1928-1929",
        "9434",
        "discharge_daily_mean",
        "1928-01-01",
        "1929-12-31",
        365,
        0,
        datetime(1929, 1, 1),
    ),
    (
        "deep-02-9434-h20-1928-1929",
        "9434",
        "stage_daily_mean",
        "1928-01-01",
        "1929-12-31",
        365,
        0,
        datetime(1929, 1, 1),
    ),
    (
        "deep-03-9434-q1h-1929-01",
        "9434",
        "discharge_hourly_mean",
        "1929-01-01",
        "1929-01-07T23:00:00",
        168,
        0,
        datetime(1929, 1, 1),
    ),
    (
        "deep-04-8221-q20-1967-1968",
        "8221",
        "discharge_daily_mean",
        "1967-01-01",
        "1968-12-31",
        366,
        0,
        datetime(1968, 1, 1),
    ),
    (
        "deep-05-8221-h1h-1968-01",
        "8221",
        "stage_hourly_mean",
        "1968-01-01",
        "1968-01-07T23:00:00",
        168,
        0,
        datetime(1968, 1, 1),
    ),
    (
        "deep-06-8078-qu20-1982-1983",
        "8078",
        "discharge_ultrasonic_daily_mean",
        "1982-01-01",
        "1983-12-31",
        365,
        195,
        datetime(1983, 1, 1),
    ),
    (
        "deep-07-9541-t20-1994",
        "9541",
        "water_temperature_daily_mean",
        "1994-06-01",
        "1994-07-31",
        40,
        1,
        datetime(1994, 6, 22),
    ),
)

_VERIFICATION_SLUGS: tuple[str, ...] = (
    *(item[0] for item in _GRDC_BENCHMARK_SAMPLES),
    *(item[0] for item in _DEEP_PROBES),
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

    for _, station_id, product_id, expected_rows, expected_nulls in _GRDC_BENCHMARK_SAMPLES:
        sel = _select_products(station_id, product_id)
        res = rr.fetch(sel, start="2000-01-01", end="2012-12-31", cache="reuse", receipts=True)
        assert [issue.code for issue in res.issues] == ["provenance.license_not_established"]
        assert res.data.height == expected_rows
        assert res.data["value"].null_count() == expected_nulls
        assert res.data["time_zone"].unique().to_list() == ["+01:00"]
        assert [o.status for o in res.outcomes] == [OutcomeStatus.SUCCESS]

    # Deep historical reach witnesses across daily Q/H (1929), hourly Q/H (1929/1968), ultrasonic (1983), and water T (1994).
    for _, station_id, product_id, start, end, expected_rows, expected_nulls, first_ts in _DEEP_PROBES:
        sel = _select_products(station_id, product_id)
        res = rr.fetch(sel, start=start, end=end, cache="reuse")
        assert [issue.code for issue in res.issues] == ["provenance.license_not_established"]
        assert res.data.height == expected_rows
        assert res.data["value"].null_count() == expected_nulls
        assert res.data.sort("time")["time"][0] == first_ts
        assert res.data["time_zone"].unique().to_list() == ["+01:00"]

    # Cache inspection, offline audit, and bundle round-trip checks.
    status = rr.cache_status("be_wal")
    assert len(status.coverage) >= 16
    assert len({item.series_id for item in status.coverage}) == 16
    audit = rr.audit_cache("be_wal")
    assert str(audit.provider_id) == "be_wal"
    assert audit.partitions_checked >= 16
    assert audit.rows_checked > 48_000

    monkeypatch.setattr(discovery, "HttpClient", lambda: ReplayTransport(()))
    offline = rr.fetch(
        _select_products("8622", "discharge_daily_mean"),
        start="2000-01-01",
        end="2012-12-31",
        cache="reuse",
    )
    assert offline.data.height == 4_749
    restored = rr.from_bundle(rr.to_bundle(offline))
    assert isinstance(restored, ObservationResult)
    assert_frame_equal(restored.data, offline.data)
    assert_frame_equal(
        rr.annotations(restored, schema=BE_WAL_QUALITY_SCHEMA.schema_id),
        rr.annotations(offline, schema=BE_WAL_QUALITY_SCHEMA.schema_id),
    )

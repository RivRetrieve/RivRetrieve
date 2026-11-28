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

# Independently read literal (published_id, series_id, val_2013_01_01, val_2022_12_31) per GRDC gauge.
_GRDC_EXPECTED: dict[str, tuple[str, str, float, float]] = {
    "SJA2259000": ("SJA2259000:Q:MEAN", "4458ab51accdb31b1fc623b742978438396c5ee4a5c8da23c20f3bf2b75b7e94", 2.58, 1.48),
    "SJA1098000": ("SJA1098000:Q:MEAN", "372d0ada61621c595809961e61f72f6d4f43d9258ae2c0cbfe64c284e85d87f0", 3.51, 2.63),
    "SJA4385000": ("SJA4385000:Q:MEAN", "b4fe1869976ede46a2fe436b9c4c156ef79eb826678107c622a19ccde5faba46", 27.5, 21.9),
    "SJA3959000": ("SJA3959000:Q:MEAN", "d3995add7cb92116d72512bc654a174608234ae15d1b15f0185a95f9e583c862", 9.5, 3.81),
    "SJA3814000": ("SJA3814000:Q:MEAN", "09ba6302ddac4219821b6fd53c17bbe08e5fac01b875a38a7852be63dffa6c4d", 9.65, 3.23),
    "SJA2558000": ("SJA2558000:Q:MEAN", "9e3bbc311075b3433683a6068c63921d644617e7f55af465db613a9ed2f6ac37", 2.24, 2.35),
    "SJA2129000": ("SJA2129000:Q:MEAN", "d254a6c2684e1bd0f8ab611f8c9d05bd14bd867870aa8064036cec740111451a", 2.17, 6.68),
    "SJA2072000": ("SJA2072000:Q:MEAN", "9ea9321b3d956d9f1afa75ca947e6e067b7123aedfbf6c7827cf1f786ff22715", 3.26, 2.58),
    "SJA7331000": ("SJA7331000:Q:MEAN", "3724234b5dbc9064d618ec0a5fa75f6c47e3514e4132d34efc6457dd6afd9933", 69.1, 41.1),
    "SJA9946000": ("SJA9946000:Q:MEAN", "e5def30432ec090b1177a6fd39061a39898bec8e68a7ada18626b89e71d72f66", 1.42, 1.06),
}

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

    for station_id, (expected_pub, expected_sid, first_val, last_val) in _GRDC_EXPECTED.items():
        sel = rr.find(provider="ee_est", station=station_id, quantity="discharge", frequency="P1D", statistic="mean")
        res = rr.fetch(sel, start="2013-01-01", end="2022-12-31", cache="reuse", receipts=True)
        assert res.issues == ()
        assert res.data.height == 3652
        assert res.data["series_id"].unique().to_list() == [expected_sid]
        assert rr.series(res)["published_id"].to_list() == [expected_pub]
        rows_sorted = res.data.sort("time")
        assert rows_sorted["time"][0] == datetime(2013, 1, 1)
        assert rows_sorted["value"][0] == pytest.approx(first_val)
        assert rows_sorted["time"][-1] == datetime(2022, 12, 31)
        assert rows_sorted["value"][-1] == pytest.approx(last_val)
        assert [o.status for o in res.outcomes] == [OutcomeStatus.SUCCESS]

    # Deep historical reach witnesses: 1867-04-01 Tartu H, 1902-09-22 Vasknarva Q, 1922-01-01 Tartu Q, 2012 hourly.
    h_1867 = rr.fetch(
        rr.find(provider="ee_est", station="SJA7331000", quantity="stage", frequency="P1D", statistic="mean"),
        start="1867-01-01",
        end="1867-12-31",
        cache="reuse",
    )
    assert h_1867.data.height == 240
    assert h_1867.data["series_id"].unique().to_list() == [
        "a9318e9dccbca0930d28b622ba159e2ac66d0084c746c379278225cb2d8f71cc"
    ]
    h_1867_sorted = h_1867.data.sort("time")
    assert h_1867_sorted["time"][0] == datetime(1867, 4, 1)
    assert h_1867_sorted["value"][0] == pytest.approx(1.73)
    assert h_1867_sorted["time"][-1] == datetime(1867, 11, 26)
    assert h_1867_sorted["value"][-1] == pytest.approx(1.68)

    q_1902_empty = rr.fetch(
        rr.find(provider="ee_est", station="SJA7331000", quantity="discharge", frequency="P1D", statistic="mean"),
        start="1902-01-01",
        end="1921-12-31",
        cache="bypass",
    )
    assert q_1902_empty.data.is_empty()
    assert [o.status for o in q_1902_empty.outcomes] == [OutcomeStatus.EMPTY]

    q_vask_1902 = rr.fetch(
        rr.find(provider="ee_est", station="SJA2718000", quantity="discharge", frequency="P1D", statistic="mean"),
        start="1902-01-01",
        end="1903-12-31",
        cache="reuse",
    )
    assert q_vask_1902.data.height == 466
    assert q_vask_1902.data["series_id"].unique().to_list() == [
        "17abaad1e391a64c7fbce2c2657f97f878a9ace555d42186220476096f2a8753"
    ]
    q_vask_sorted = q_vask_1902.data.sort("time")
    assert q_vask_sorted["time"][0] == datetime(1902, 9, 22)
    assert q_vask_sorted["value"][0] == pytest.approx(532.0)
    assert q_vask_sorted["time"][-1] == datetime(1903, 12, 31)
    assert q_vask_sorted["value"][-1] == pytest.approx(416.0)

    q_tartu_1922 = rr.fetch(
        rr.find(provider="ee_est", station="SJA7331000", quantity="discharge", frequency="P1D", statistic="mean"),
        start="1922-01-01",
        end="1922-12-31",
        cache="reuse",
    )
    assert q_tartu_1922.data.height == 365
    assert q_tartu_1922.data["series_id"].unique().to_list() == [
        "3724234b5dbc9064d618ec0a5fa75f6c47e3514e4132d34efc6457dd6afd9933"
    ]
    q_tartu_sorted = q_tartu_1922.data.sort("time")
    assert q_tartu_sorted["time"][0] == datetime(1922, 1, 1)
    assert q_tartu_sorted["value"][0] == pytest.approx(26.9)
    assert q_tartu_sorted["time"][-1] == datetime(1922, 12, 31)
    assert q_tartu_sorted["value"][-1] == pytest.approx(24.5)

    hourly_checks = (
        (
            "stage",
            "41061:WL avg",
            "d8882a9d825e990daeddb93d1989506c4ef4fa48845c97f4bb719bbbc1ed5383",
            0.631,
            0.784,
        ),
        (
            "discharge",
            "41061:Äravool avg",
            "721af9089dd31b30b8ea086ec55a27a5fc8e2125ec4ca2659604e7e98551826e",
            5.153,
            6.418,
        ),
    )
    for quantity, expected_pub, expected_sid, first_val, last_val in hourly_checks:
        hr_2012 = rr.fetch(
            rr.find(provider="ee_est", station="SJA8821000", quantity=quantity, frequency="PT1H", statistic="mean"),
            start="2012-01-01",
            end="2012-01-07T23:59:59.999999",
            cache="reuse",
        )
        assert hr_2012.data.height == 168
        assert hr_2012.data["series_id"].unique().to_list() == [expected_sid]
        assert rr.series(hr_2012)["published_id"].to_list() == [expected_pub]
        hr_sorted = hr_2012.data.sort("time")
        assert hr_sorted["time"][0] == datetime(2012, 1, 1, 0, 0)
        assert hr_sorted["value"][0] == pytest.approx(first_val)
        assert hr_sorted["time"][-1] == datetime(2012, 1, 7, 23, 0)
        assert hr_sorted["value"][-1] == pytest.approx(last_val)
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
        rr.find(provider="ee_est", station="SJA7331000", quantity="discharge", frequency="P1D", statistic="mean"),
        start="2013-01-01",
        end="2022-12-31",
        cache="reuse",
    )
    assert offline.data.height == 3652
    assert offline.data.sort("time")["value"][0] == pytest.approx(69.1)
    restored = rr.from_bundle(rr.to_bundle(offline))
    assert_frame_equal(restored.data, offline.data)

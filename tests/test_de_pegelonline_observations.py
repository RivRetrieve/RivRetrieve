"""de_pegelonline recorded observations exercise the real fetch/parse path against genuine responses.

Recordings come from `de_pegelonline-verification-2026-11-26-v1`
(`verification-evidence`), captured via `rivretrieve._internal.record_observations`
driving the real public-fetch path (engine padding, window planning and stop
convention included) against the live PEGELONLINE API. Step 6, #1021.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import rivretrieve as rr
import rivretrieve._internal.discovery as discovery
from rivretrieve._internal.engine import RenderedWindow, WindowEndpoint, _make_fetch_window
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.de_pegelonline.config import config
from rivretrieve._internal.providers.de_pegelonline.fetch import fetch
from rivretrieve._internal.providers.de_pegelonline.series import source_series
from rivretrieve._internal.recordings import ReplayTransport
from rivretrieve._internal.source_series import OutcomeStatus, admission

_DATA = Path("tests/test_data")

# The exact, already-padded window every "recent" capture's own request used,
# as naive UTC wall-clock instants (`RenderedWindow.bounds`'s own form --
# the request's rendered "+01:00" local offset is one hour ahead of this).
# `record_observations.py` applies the real engine padding at capture time;
# calling `fetch()` directly here must match those exact bounds, not
# re-derive padding from the original public start/end.
_RECENT_START, _RECENT_END = "2026-11-22T00:00:00", "2026-11-28T23:59:59.999999"


def _window(start: str, end: str) -> RenderedWindow:
    bounds = _make_fetch_window(
        WindowEndpoint.from_datetime(datetime.fromisoformat(start)), WindowEndpoint.from_datetime(datetime.fromisoformat(end))
    )
    return RenderedWindow("ignored-start", "ignored-stop", bounds)


def _fetch_one(
    retained_evidence_root: Path,
    station: str,
    product: str,
    recording_name: str,
    *,
    unit: str,
    equidistance: int | None = None,
    gauge_zero_unit: str | None = None,
):
    product_id = ProductId(product)
    window = _window(_RECENT_START, _RECENT_END)
    series = source_series(station, product, unit=unit, equidistance=equidistance, gauge_zero_unit=gauge_zero_unit)
    transport = ReplayTransport([retained_evidence_root / _DATA / recording_name])
    return (
        fetch(
            (station,),
            (product_id,),
            {product_id: (window,)},
            window.bounds,
            config(),
            transport,
            known_series=(series,),
        ),
        series,
    )


@pytest.mark.recorded("tests/test_data/de_pegelonline_hofkirchen_w_recent.recording.json")
def test_hofkirchen_stage_w_recording_admits_cm_to_m(retained_evidence_root) -> None:
    acquired, series = _fetch_one(
        retained_evidence_root,
        "616dd98e-816d-4e17-b8cd-57b163dbc8a2",
        "W",
        "de_pegelonline_hofkirchen_w_recent.recording.json",
        unit="cm",
        equidistance=15,
        gauge_zero_unit="m. ü. NHN",
    )
    assert acquired.failed_requests == ()
    rows = acquired.interpretations[0].parsed.rows.sort("time")
    assert rows.height == 410
    assert rows["source_unit"].unique().to_list() == ["cm"]
    assert rows["value"][0] == 261.0
    assert rows["value"][-1] == 231.0
    outcome = acquired.interpretations[0].parsed.outcomes[0]
    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.series_id == series.series_id
    fact = series.facts[0]
    assert admission(fact).status == "supported"
    assert admission(fact).target_unit == "m"
    assert admission(fact).factor == 0.01


@pytest.mark.recorded("tests/test_data/de_pegelonline_hofkirchen_q_recent.recording.json")
def test_hofkirchen_discharge_q_recording(retained_evidence_root) -> None:
    acquired, series = _fetch_one(
        retained_evidence_root,
        "616dd98e-816d-4e17-b8cd-57b163dbc8a2",
        "Q",
        "de_pegelonline_hofkirchen_q_recent.recording.json",
        unit="m³/s",
        equidistance=15,
    )
    rows = acquired.interpretations[0].parsed.rows.sort("time")
    assert rows.height == 409
    assert rows["source_unit"].unique().to_list() == ["m³/s"]
    assert rows["value"][0] == 488.0
    assert rows["value"][-1] == 398.0
    outcome = acquired.interpretations[0].parsed.outcomes[0]
    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.series_id == series.series_id


@pytest.mark.recorded("tests/test_data/de_pegelonline_hofkirchen_wt_recent.recording.json")
def test_hofkirchen_water_temperature_wt_recording_has_exactly_one_row(retained_evidence_root) -> None:
    """PEGELONLINE's raw WT telemetry is sparse at some stations -- genuinely 1 row here, not a capture mistake."""
    acquired, series = _fetch_one(
        retained_evidence_root,
        "616dd98e-816d-4e17-b8cd-57b163dbc8a2",
        "WT",
        "de_pegelonline_hofkirchen_wt_recent.recording.json",
        unit="°C",
        equidistance=60,
    )
    rows = acquired.interpretations[0].parsed.rows
    assert rows.height == 1
    assert rows["source_unit"].to_list() == ["°C"]
    assert rows["value"].to_list() == [0.0]
    outcome = acquired.interpretations[0].parsed.outcomes[0]
    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.series_id == series.series_id


@pytest.mark.recorded("tests/test_data/de_pegelonline_hofkirchen_trm_recent.recording.json")
def test_hofkirchen_scheduled_stage_trm_recording_captures_the_difference_annotation(
    retained_evidence_root,
) -> None:
    acquired, series = _fetch_one(
        retained_evidence_root,
        "616dd98e-816d-4e17-b8cd-57b163dbc8a2",
        "TRM",
        "de_pegelonline_hofkirchen_trm_recent.recording.json",
        unit="cm",
        gauge_zero_unit="m. ü. NHN",
    )
    parsed = acquired.interpretations[0].parsed
    rows = parsed.rows.sort("time")
    assert rows.height == 18
    assert rows["value"][0] == 262.0
    assert rows["value"][-1] == 231.0
    table = parsed.annotations.observation_tables["de_pegelonline.trm"]
    sorted_table = table.rows.sort("time")
    assert sorted_table["difference"][0] == -6.0
    assert sorted_table["difference"][-1] == -22.0
    outcome = parsed.outcomes[0]
    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.series_id == series.series_id
    # TRM is scheduled (Terminwerte), not a regular elapsed interval: frequency stays not_established.
    assert series.facts[0].frequency.value is None


@pytest.mark.recorded("tests/test_data/de_pegelonline_versen-trennspitze_w_recent.recording.json")
def test_versen_trennspitze_stage_w_recording_second_station(retained_evidence_root) -> None:
    acquired, series = _fetch_one(
        retained_evidence_root,
        "0024cc40-d690-468d-84f9-4e9bf45d9108",
        "W",
        "de_pegelonline_versen-trennspitze_w_recent.recording.json",
        unit="cm",
        equidistance=15,
        gauge_zero_unit="m. ü. NHN",
    )
    rows = acquired.interpretations[0].parsed.rows.sort("time")
    assert rows.height == 410
    assert rows["value"][0] == 241.0
    assert rows["value"][-1] == 244.0
    outcome = acquired.interpretations[0].parsed.outcomes[0]
    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.series_id == series.series_id


@pytest.mark.recorded("tests/test_data/de_pegelonline_tyniste_q_recent.recording.json")
def test_tyniste_discharge_q_recording_second_station(retained_evidence_root) -> None:
    acquired, series = _fetch_one(
        retained_evidence_root,
        "04cbc946-8ee9-4521-ac52-557642cad52c",
        "Q",
        "de_pegelonline_tyniste_q_recent.recording.json",
        unit="m³/s",
        equidistance=10,
    )
    rows = acquired.interpretations[0].parsed.rows.sort("time")
    assert rows.height == 611
    assert rows["value"][0] == 22.0
    assert rows["value"][-1] == 8.81
    outcome = acquired.interpretations[0].parsed.outcomes[0]
    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.series_id == series.series_id


@pytest.mark.recorded("tests/test_data/de_pegelonline_tonning_wt_recent.recording.json")
def test_tonning_water_temperature_wt_recording_second_station(retained_evidence_root) -> None:
    acquired, series = _fetch_one(
        retained_evidence_root,
        "00e386ac-e35c-4a6e-80dd-f8cd8a9e7a62",
        "WT",
        "de_pegelonline_tonning_wt_recent.recording.json",
        unit="°C",
        equidistance=1,
    )
    rows = acquired.interpretations[0].parsed.rows.sort("time")
    assert rows.height == 6141
    assert rows["value"][0] == 5.0
    assert rows["value"][-1] == 2.9
    outcome = acquired.interpretations[0].parsed.outcomes[0]
    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.series_id == series.series_id


@pytest.mark.recorded("tests/test_data/de_pegelonline_rinteln_trm_recent.recording.json")
def test_rinteln_scheduled_stage_trm_recording_second_station_has_a_published_null(
    retained_evidence_root,
) -> None:
    acquired, series = _fetch_one(
        retained_evidence_root,
        "005dfdae-efcc-410a-bf1c-24096e0c2866",
        "TRM",
        "de_pegelonline_rinteln_trm_recent.recording.json",
        unit="cm",
        gauge_zero_unit="m. ü. NN",
    )
    rows = acquired.interpretations[0].parsed.rows.sort("time")
    assert rows.height == 16
    assert rows["value"][0] == 184.0
    # Genuinely published null (a scheduled reading PEGELONLINE did not supply), preserved not dropped.
    assert rows["value"][-1] is None
    outcome = acquired.interpretations[0].parsed.outcomes[0]
    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.series_id == series.series_id


@pytest.mark.recorded("tests/test_data/de_pegelonline_schwabelweis_trm-wt_recent.recording.json")
def test_schwabelweis_scheduled_water_temperature_trm_wt_recording_is_genuinely_empty(
    retained_evidence_root,
) -> None:
    """Both TRM_WT-publishing stations were empty across this capture window -- a real finding, not a mistake.

    Re-probed separately against a ~26-day window before committing this
    test; still empty at both stations. See the PR description.
    """
    acquired, series = _fetch_one(
        retained_evidence_root,
        "7644f1d7-3198-4313-9340-abefd459a4f3",
        "TRM_WT",
        "de_pegelonline_schwabelweis_trm-wt_recent.recording.json",
        unit="°C",
    )
    assert acquired.failed_requests == ()
    outcome = acquired.interpretations[0].parsed.outcomes[0]
    assert outcome.status is OutcomeStatus.EMPTY
    assert outcome.series_id == series.series_id


@pytest.mark.recorded("tests/test_data/de_pegelonline_passau-donau_trm-wt_recent.recording.json")
def test_passau_donau_scheduled_water_temperature_trm_wt_recording_is_genuinely_empty(
    retained_evidence_root,
) -> None:
    acquired, series = _fetch_one(
        retained_evidence_root,
        "9f12c405-35ac-4d90-9b7b-023be355867e",
        "TRM_WT",
        "de_pegelonline_passau-donau_trm-wt_recent.recording.json",
        unit="°C",
    )
    assert acquired.failed_requests == ()
    outcome = acquired.interpretations[0].parsed.outcomes[0]
    assert outcome.status is OutcomeStatus.EMPTY
    assert outcome.series_id == series.series_id


@pytest.mark.recorded("tests/test_data/de_pegelonline_hofkirchen_q_future-empty.recording.json")
def test_future_window_is_genuinely_empty_not_an_error(retained_evidence_root) -> None:
    station = "616dd98e-816d-4e17-b8cd-57b163dbc8a2"
    product_id = ProductId("Q")
    window = _window("2027-05-30T00:00:00", "2027-06-04T23:59:59.999999")
    series = source_series(station, "Q", unit="m³/s", equidistance=15)
    transport = ReplayTransport(
        [retained_evidence_root / _DATA / "de_pegelonline_hofkirchen_q_future-empty.recording.json"]
    )

    acquired = fetch(
        (station,),
        (product_id,),
        {product_id: (window,)},
        window.bounds,
        config(),
        transport,
        known_series=(series,),
    )

    assert acquired.failed_requests == ()
    outcome = acquired.interpretations[0].parsed.outcomes[0]
    assert outcome.status is OutcomeStatus.EMPTY
    assert outcome.series_id == series.series_id


class _CountingTransport:
    """Wraps a transport to count real `send` calls, proving a second fetch was served from cache."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.send_count = 0

    def send(self, request):
        self.send_count += 1
        return self._inner.send(request)

    def can_authenticate(self, url: str) -> bool:
        return self._inner.can_authenticate(url)


@pytest.mark.recorded("tests/test_data/de_pegelonline_hofkirchen_q_recent.recording.json")
def test_no_declared_cache_means_reuse_still_genuinely_refetches(
    retained_evidence_root, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verifies de_pegelonline's store behavior through the real public API, backed by a genuine recording.

    `config().cache is None` (`tests/test_de_pegelonline_fetch.py`): this
    provider declares no observation cache at all, presumably because its
    data is a rolling, frequently-changing live window. The relevant
    cache/store check here is that this is honored consistently: `cache="reuse"`
    behaves like `bypass` and genuinely refetches rather than silently
    fabricating a cache hit, exactly like `cache="refresh"` did -- the same
    one recording genuinely answers both independent requests.
    """
    monkeypatch.setenv("RIVRETRIEVE_CACHE_DIR", str(tmp_path / "cache"))
    recording = retained_evidence_root / _DATA / "de_pegelonline_hofkirchen_q_recent.recording.json"
    transport = _CountingTransport(ReplayTransport([recording]))
    monkeypatch.setattr(discovery, "HttpClient", lambda: transport)

    selection = rr.find(provider="de_pegelonline", station="616dd98e-816d-4e17-b8cd-57b163dbc8a2", quantity="discharge")

    # The original public window used at capture time (via record_observations.py):
    # the engine pads the underlying source request to the exact bounds the
    # recording's own request used (_RECENT_START/_RECENT_END), the same way
    # it did at capture time, then clips the returned rows back down to this
    # narrower requested window -- 221 of the recording's 409 rows fall inside it.
    first = rr.fetch(selection, start="2026-11-24", end="2026-11-26", cache="refresh")
    assert transport.send_count == 1
    assert first.data.height == 221

    second = rr.fetch(selection, start="2026-11-24", end="2026-11-26", cache="reuse")
    assert transport.send_count == 2
    assert second.data.height == first.data.height

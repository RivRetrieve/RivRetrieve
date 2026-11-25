"""Synthetic controls for Germany PEGELONLINE series identity and physical facts.

Unit, `equidistance` and `gaugeZero` values used below are copied from genuine
station entries in the committed fixture `tests/test_data/de_pegelonline_stations.json`
(step 1/2's settled source), not invented, per
`planning/visions/2026-11-25-de-pegelonline-series-identity-and-physical-meaning.md`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rivretrieve._internal.frequency import canonicalize_frequency
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.de_pegelonline.series import QUANTITIES, source_series
from rivretrieve._internal.source_series import EvidenceState, admission

FIXTURE_PATH = Path(__file__).parent / "test_data" / "de_pegelonline_stations.json"


def _load_stations_by_longname() -> dict[str, dict[str, object]]:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return {station["longname"]: station for station in data}


_STATIONS = _load_stations_by_longname()


def _timeseries(longname: str, shortname: str) -> dict[str, object]:
    station = _STATIONS[longname]
    for entry in station["timeseries"]:
        if entry["shortname"] == shortname:
            return entry
    raise AssertionError(f"{longname} has no {shortname} timeseries in the fixture")


def _uuid(longname: str) -> str:
    return str(_STATIONS[longname]["uuid"])


# Real per-unit-regime examples confirmed present in the committed fixture.
CELLE_W = _timeseries("CELLE", "W")  # cm, gaugeZero present ("m. ü. NN")
WALTROP_W = _timeseries("WALTROP", "W")  # m+NN, gaugeZero absent
DIEMELTALSPERRE_W = _timeseries("DIEMELTALSPERRE", "W")  # m+PNP, gaugeZero present
AHLDEN_W = _timeseries("AHLDEN", "W")  # cm, gaugeZero absent
HOFKIRCHEN_Q = _timeseries("HOFKIRCHEN", "Q")  # m³/s, equidistance=15
HOFKIRCHEN_W = _timeseries("HOFKIRCHEN", "W")  # cm, equidistance=15, same station as WT below
HOFKIRCHEN_WT = _timeseries("HOFKIRCHEN", "WT")  # °C, equidistance=60, carries an 'Ausfall' comment
HOFKIRCHEN_TRM = _timeseries("HOFKIRCHEN", "TRM")  # cm, no equidistance at all
SCHWABELWEIS_TRM_WT = _timeseries("SCHWABELWEIS", "TRM_WT")  # °C, no equidistance at all


def test_quantity_mapping_uses_the_dimensional_admission_vocabulary():
    # WT and TRM_WT must map to "temperature", never "water_temperature" (the
    # catalogue's separate observed_property label): a prior "water_temperature"
    # value caused the exact dk_vanda admission-rejection bug documented in
    # providers/dk_vanda/series.py; this guards against reintroducing it here.
    assert QUANTITIES == {
        "W": "stage",
        "Q": "discharge",
        "WT": "temperature",
        "TRM": "stage",
        "TRM_WT": "temperature",
    }
    for product_id, unit in (("Q", "m³/s"), ("WT", "°C"), ("TRM_WT", "°C")):
        equidistance = None if product_id == "TRM_WT" else 15
        series = source_series(_uuid("HOFKIRCHEN"), product_id, unit=unit, equidistance=equidistance)
        facts = series.facts[0]
        assert facts.quantity.value == QUANTITIES[product_id]
        assert admission(facts).status == "supported"


@pytest.mark.parametrize(
    ("entry", "expected_normalized_unit", "expected_factor", "expected_vertical_reference"),
    [
        (CELLE_W, "cm", 0.01, "gauge_zero"),
        (DIEMELTALSPERRE_W, "m", 1.0, "gauge_zero"),
        (WALTROP_W, "m", 1.0, "above_sea_level"),
    ],
)
def test_vertical_reference_branches_on_unit_not_on_scaling(
    entry, expected_normalized_unit, expected_factor, expected_vertical_reference
):
    # cm and m+PNP land on the SAME vertical_reference ("gauge_zero") despite
    # cm needing a ÷100 admission factor and m+PNP needing none (it is already
    # denominated in metres); a naive branch keyed off the (post-scaling)
    # value rather than the native unit string could get this backwards.
    series = source_series("station", "W", unit=entry["unit"], equidistance=entry.get("equidistance"))
    facts = series.facts[0]
    assert facts.source_unit.value == entry["unit"]
    assert facts.normalized_unit == expected_normalized_unit
    assert facts.vertical_reference.value == expected_vertical_reference
    decision = admission(facts)
    assert decision.status == "supported"
    assert decision.target_unit == "m"
    assert decision.factor == pytest.approx(expected_factor)


def test_cm_and_m_plus_pnp_both_pick_up_gauge_zero_unit_as_the_vertical_datum():
    cm_facts = source_series(
        "station", "W", unit=CELLE_W["unit"], equidistance=15, gauge_zero_unit=CELLE_W["gaugeZero"]["unit"]
    ).facts[0]
    assert cm_facts.vertical_datum.value == "m. ü. NN"
    assert cm_facts.vertical_datum.state is EvidenceState.KNOWN

    pnp_facts = source_series(
        "station",
        "W",
        unit=DIEMELTALSPERRE_W["unit"],
        equidistance=15,
        gauge_zero_unit=DIEMELTALSPERRE_W["gaugeZero"]["unit"],
    ).facts[0]
    assert pnp_facts.vertical_datum.value == "m. ü. NN"
    assert pnp_facts.vertical_datum.state is EvidenceState.KNOWN


def test_cm_without_a_published_gauge_zero_is_source_silent_not_unknown_guessed():
    assert AHLDEN_W.get("gaugeZero") is None
    facts = source_series("station", "W", unit=AHLDEN_W["unit"], equidistance=15, gauge_zero_unit=None).facts[0]
    assert facts.vertical_datum.state is EvidenceState.SOURCE_SILENT
    assert facts.vertical_datum.value is None


def test_m_plus_nn_vertical_datum_is_literal_nn_even_without_a_published_gauge_zero():
    # WALTROP publishes no gaugeZero at all for its m+NN timeseries; m+NN's
    # datum is still established as literal "NN" (per the vision), unlike the
    # cm/m+PNP branches above, which fall back to source_silent in that case.
    assert WALTROP_W.get("gaugeZero") is None
    facts = source_series("station", "W", unit=WALTROP_W["unit"], equidistance=1, gauge_zero_unit=None).facts[0]
    assert facts.vertical_datum.value == "NN"
    assert facts.vertical_datum.state is EvidenceState.KNOWN


def test_trm_shares_ws_vertical_regime_as_its_own_identity_not_folded_into_w():
    w_series = source_series(_uuid("HOFKIRCHEN"), "W", unit=HOFKIRCHEN_W["unit"], equidistance=15)
    trm_series = source_series(_uuid("HOFKIRCHEN"), "TRM", unit=HOFKIRCHEN_TRM["unit"])
    assert w_series.product_id == "W"
    assert trm_series.product_id == "TRM"
    assert w_series.series_id != trm_series.series_id
    assert trm_series.facts[0].quantity.value == "stage"
    assert trm_series.facts[0].vertical_reference.value == "gauge_zero"


def test_discharge_and_temperature_products_never_claim_a_vertical_reference():
    for product_id, unit in (("Q", "m³/s"), ("WT", "°C"), ("TRM_WT", "°C")):
        equidistance = None if product_id == "TRM_WT" else 15
        facts = source_series("station", product_id, unit=unit, equidistance=equidistance).facts[0]
        assert facts.vertical_reference.state is EvidenceState.NOT_ESTABLISHED
        assert facts.vertical_datum.state is EvidenceState.NOT_ESTABLISHED


def test_frequency_varies_per_station_for_the_same_product_and_canonicalizes():
    # HOFKIRCHEN is #874's own cited mixed-interval example: W/Q every 15 min
    # but WT every 60 min, at the same station.
    w_facts = source_series(
        _uuid("HOFKIRCHEN"), "W", unit=HOFKIRCHEN_W["unit"], equidistance=HOFKIRCHEN_W["equidistance"]
    ).facts[0]
    q_facts = source_series(
        _uuid("HOFKIRCHEN"), "Q", unit=HOFKIRCHEN_Q["unit"], equidistance=HOFKIRCHEN_Q["equidistance"]
    ).facts[0]
    wt_facts = source_series(
        _uuid("HOFKIRCHEN"), "WT", unit=HOFKIRCHEN_WT["unit"], equidistance=HOFKIRCHEN_WT["equidistance"]
    ).facts[0]

    assert HOFKIRCHEN_W["equidistance"] == HOFKIRCHEN_Q["equidistance"] == 15
    assert HOFKIRCHEN_WT["equidistance"] == 60
    assert w_facts.frequency.value == "PT15M"
    assert q_facts.frequency.value == "PT15M"
    # A station reporting equidistance=60 must collapse to the canonical PT1H
    # spelling, not stay as the non-canonical PT60M.
    assert wt_facts.frequency.value == "PT1H"
    assert wt_facts.frequency.value == canonicalize_frequency("PT60M")
    assert w_facts.frequency.state is EvidenceState.KNOWN


@pytest.mark.parametrize(
    "equidistance,expected", [(1, "PT1M"), (5, "PT5M"), (10, "PT10M"), (15, "PT15M"), (60, "PT1H")]
)
def test_frequency_builder_covers_every_witnessed_equidistance_value(equidistance, expected):
    facts = source_series("station", "WT", unit="°C", equidistance=equidistance).facts[0]
    assert facts.frequency.value == expected


def test_trm_and_trm_wt_frequency_stays_not_established():
    assert "equidistance" not in HOFKIRCHEN_TRM
    assert "equidistance" not in SCHWABELWEIS_TRM_WT
    trm_facts = source_series(_uuid("HOFKIRCHEN"), "TRM", unit=HOFKIRCHEN_TRM["unit"]).facts[0]
    trm_wt_facts = source_series(_uuid("SCHWABELWEIS"), "TRM_WT", unit=SCHWABELWEIS_TRM_WT["unit"]).facts[0]
    for facts in (trm_facts, trm_wt_facts):
        assert facts.frequency.state is EvidenceState.NOT_ESTABLISHED
        assert facts.frequency.value is None
    # Passing an equidistance for a scheduled product must not silently be
    # honored into a forced regular-interval claim.
    ignored = source_series(_uuid("HOFKIRCHEN"), "TRM", unit=HOFKIRCHEN_TRM["unit"], equidistance=15).facts[0]
    assert ignored.frequency.state is EvidenceState.NOT_ESTABLISHED


def test_regular_products_require_an_explicit_equidistance():
    with pytest.raises(FatalContractError):
        source_series("station", "W", unit="cm")
    with pytest.raises(FatalContractError):
        source_series("station", "Q", unit="m³/s")
    with pytest.raises(FatalContractError):
        source_series("station", "WT", unit="°C")


@pytest.mark.parametrize("product_id", ["W", "Q", "WT", "TRM", "TRM_WT"])
def test_statistic_day_definition_and_timestamp_anchor_stay_not_established(product_id):
    unit = {"W": "cm", "Q": "m³/s", "WT": "°C", "TRM": "cm", "TRM_WT": "°C"}[product_id]
    equidistance = None if product_id in ("TRM", "TRM_WT") else 15
    facts = source_series("station", product_id, unit=unit, equidistance=equidistance).facts[0]
    assert facts.statistic.state is EvidenceState.NOT_ESTABLISHED
    assert facts.day_definition.state is EvidenceState.NOT_ESTABLISHED
    assert facts.timestamp_anchor.state is EvidenceState.NOT_ESTABLISHED
    assert facts.time_zone.state is EvidenceState.NOT_ESTABLISHED


def test_unsupported_product_id_is_rejected():
    with pytest.raises(FatalContractError):
        source_series("station", "LF", unit="µS/cm")


def test_unsupported_unit_is_rejected_rather_than_silently_admitted():
    with pytest.raises(FatalContractError):
        source_series("station", "W", unit="ft", equidistance=15)
    with pytest.raises(FatalContractError):
        source_series("station", "Q", unit="l/s", equidistance=15)


def test_blank_station_id_is_rejected():
    with pytest.raises(FatalContractError):
        source_series("   ", "W", unit="cm", equidistance=15)


def test_no_fact_or_identity_anywhere_concerns_the_excluded_live_status_codes():
    # stateMnwMhw/stateNswHsw are explicitly out of scope for this vision;
    # nothing built here should reference them under any spelling.
    for product_id, unit, equidistance in (
        ("W", "cm", 15),
        ("Q", "m³/s", 15),
        ("WT", "°C", 15),
        ("TRM", "cm", None),
        ("TRM_WT", "°C", None),
    ):
        series = source_series("station", product_id, unit=unit, equidistance=equidistance)
        dumped = series.model_dump_json().casefold()
        assert "mnwmhw" not in dumped
        assert "nswhsw" not in dumped

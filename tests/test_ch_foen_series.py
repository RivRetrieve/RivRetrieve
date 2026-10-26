"""Synthetic controls for official Swiss series definitions, not source certification."""

import polars as pl
import pytest

from rivretrieve._internal.providers.ch_foen.generate_catalogue import ASSOCIATION_SCHEMA, describe_associations
from rivretrieve._internal.providers.ch_foen.official_series import source_series
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceState,
    PhysicalPredicate,
    SeriesScope,
    admission,
    stable_id,
)


def define(route="data_1day_mean", *, station="2602", name="Q", parameter="Q", units=("m³/s",)):
    return source_series(
        station,
        route,
        parameter,
        name,
        units=units,
        evidence="synthetic:units",
        temporal_evidence="catalogue:ch_foen:source.product.temporal_meaning",
        origin="response",
    )


def test_response_and_catalogue_preserve_coordinates_and_unit_segments():
    rows = [
        {"station_no": "2602", "route": route, "parameterName": "Q", "tsName": name, "unitSymbol": unit}
        for route, name, unit in [
            ("data_1day_mean", "Q", "m³/s"),
            ("data_1day_mean", "Q", "l/s"),
            ("data_1day_mean", "Q_01", "m³/s"),
            ("data_live", None, "l/s"),
        ]
    ]
    descriptions = describe_associations(pl.DataFrame(rows, schema=ASSOCIATION_SCHEMA), evidence="synthetic:units")
    identities = []
    for description in descriptions.descriptions:
        route, parameter, name = description.identity_key
        response = define(route, name=name, units=tuple(f.source_unit.value for f in description.facts))
        assert response.series_id == stable_id("ch_foen", description.station_id, *description.identity_key)
        assert response.facts == description.facts
        assert response.identity.published_id == description.identity.published_id
        identities.append(response.series_id)
    assert len(set(identities)) == 3
    assert define(station="02602").series_id != define(station="2602").series_id
    assert define(units=("l/s",)).series_id == define().series_id


@pytest.mark.parametrize(
    "route,frequency,support,statistic",
    [
        ("data_10min_mean", "10min", "10_minutes", "mean"),
        ("data_1hour_mean", "hourly", "1_hour", "mean"),
        ("data_1day_min", "daily", "calendar_day", "min"),
        ("data_1month_max", "monthly", "calendar_month", "max"),
        ("data_1year_mean", "yearly", "calendar_year", "mean"),
    ],
)
def test_archive_support_keeps_utc_labels_separate_from_aggregation_calendar(route, frequency, support, statistic):
    facts = define(route).facts[0]
    assert facts.frequency.value == frequency
    assert facts.statistic.value == statistic
    assert facts.temporal_support.value == support
    assert facts.timestamp_anchor.value == "start"
    assert facts.time_zone.value == "UTC"
    assert facts.day_definition.value == ("UTC+01:00" if support.startswith("calendar_") else None)
    assert facts.clipping_axis is ClippingAxis.SOURCE_TIMESTAMP
    assert facts.label_time is None


@pytest.mark.parametrize(
    "route,station,name,anchor",
    [
        ("data_live", "2602", None, "end"),
        ("data_1day_mean", "7008", "MonatsMittel_Orbe_flex", None),
    ],
)
def test_unknown_support_is_admissible_but_cannot_match_known_support(route, station, name, anchor):
    series = define(route, station=station, name=name)
    facts = series.facts[0]
    assert admission(facts).status == "supported"
    assert facts.temporal_support.state is EvidenceState.NOT_ESTABLISHED
    assert facts.frequency.value is None and facts.statistic.value is None
    assert facts.timestamp_anchor.value == anchor
    assert facts.time_zone.value == "UTC"
    assert not SeriesScope(predicates=(PhysicalPredicate(field="temporal_support", value="calendar_day"),)).matches(
        series
    )
    assert SeriesScope().matches(series)


@pytest.mark.parametrize(
    "parameter,archive_unit,recent_unit,factor", [("Q", "m³/s", "l/s", 0.001), ("W", "m ü.M.", "cm", 0.01)]
)
def test_2282_units_keep_scale_and_reference_without_offset(parameter, archive_unit, recent_unit, factor):
    archive = define(station="2282", parameter=parameter, units=(archive_unit,)).facts[0]
    recent = define("data_live", station="2282", name=None, parameter=parameter, units=(recent_unit,)).facts[0]
    assert admission(archive).factor == 1
    assert admission(recent).factor == factor
    assert recent.source_unit.value == recent_unit
    assert archive.vertical_reference.value == ("above_sea_level" if parameter == "W" else None)
    assert recent.vertical_reference.value is None
    assert archive.vertical_datum.value is None
    assert recent.vertical_datum.value is None
    missing = define("data_live", station="2282", name=None, parameter=parameter, units=(None,)).facts[0]
    assert admission(missing).status == "unsupported"
    incompatible = define(parameter=parameter, units=("°C",)).facts[0]
    assert admission(incompatible).status == "unsupported"


def test_release_vocabulary_does_not_rewrite_raw_encoding():
    from rivretrieve._internal.providers.ch_foen.official_series import RELEASE_STATUS_FIELDS, RELEASE_STATUS_MEANINGS

    assert RELEASE_STATUS_FIELDS == {"archive": "releaseState", "recent": "releaseStatus"}
    assert RELEASE_STATUS_MEANINGS[None] == RELEASE_STATUS_MEANINGS[0] == "raw"
    assert RELEASE_STATUS_MEANINGS[1] == "unreleased/prechecked"
    assert RELEASE_STATUS_MEANINGS[2] == "released/checked"
    assert RELEASE_STATUS_MEANINGS[3] == "released/definitive"
    assert None in RELEASE_STATUS_MEANINGS and 0 in RELEASE_STATUS_MEANINGS

"""Authored modern USGS parser controls, not untouched publisher recordings."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.engine import (
    Payload,
    SourceCallOrigin,
    SourceCoordinates,
    UnknownOriginFact,
    WindowEndpoint,
    _make_fetch_window,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.usgs_nwis.config import config
from rivretrieve._internal.providers.usgs_nwis.metadata import NAMESPACE, source_series
from rivretrieve._internal.providers.usgs_nwis.parse import parse
from rivretrieve._internal.source_series import PhysicalPredicate, SeriesScope, admission
from rivretrieve._internal.time_axis import TimeAxis


def feature(product="discharge_daily_mean", **changes):
    coordinates = config().products[ProductId(product)].coordinates.value
    properties = {
        "time_series_id": "opaque-series-a",
        "monitoring_location_id": "USGS-07374000",
        "parameter_code": coordinates.parameter_code,
        "statistic_id": coordinates.statistic_code if coordinates.endpoint == "daily" else "00011",
        "unit_of_measure": "ft^3/s" if coordinates.parameter_code == "00060" else "ft",
        "time": "2024-01-01" if coordinates.endpoint == "daily" else "2024-01-01T01:02:03Z",
        "value": "1.25",
        "qualifier": ["ESTIMATED"],
        "approval_status": "Approved",
    }
    properties.update(changes)
    return {"type": "Feature", "id": "unstable-record-id", "properties": properties}


def payload(document, product="discharge_daily_mean", known=()):
    coordinates = replace(
        config().products[ProductId(product)].coordinates.value, monitoring_location_id="USGS-07374000"
    )
    return Payload(
        SourceCoordinates(coordinates),
        (("07374000", ProductId(product)),),
        _make_fetch_window(
            WindowEndpoint.from_datetime(datetime(2024, 1, 1)), WindowEndpoint.from_datetime(datetime(2024, 1, 7))
        ),
        json.dumps(document).encode(),
        SourceCallOrigin(
            "https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items",
            {},
            200,
            datetime(2026, 9, 22, tzinfo=UTC),
            "application/geo+json",
            UnknownOriginFact(),
            UnknownOriginFact(),
        ),
        prerequisite_calls=(),
        known_series=known,
        acquisition_axis=TimeAxis.UTC if coordinates.endpoint == "continuous" else TimeAxis.NATIVE,
    )


def decode(features, product="discharge_daily_mean", known=()):
    return parse(payload({"type": "FeatureCollection", "features": features}, product, known), config())


def unsupported(result):
    assert result.rows.is_empty()
    assert result.issues
    assert all(outcome.status == "unsupported" and outcome.reason for outcome in result.outcomes)


@pytest.mark.parametrize("product", tuple(config().products))
def test_all_six_routes_preserve_source_facts(product):
    result = decode([feature(product)], product)
    assert result.rows.height == 1
    facts = result.series[0].facts[0]
    assert admission(facts).status == "supported"
    assert result.series[0].identity.namespace == NAMESPACE
    assert result.series[0].identity.published_id == "opaque-series-a"
    assert result.series[0].series_id != "unstable-record-id"
    assert facts.source_unit.value == ("ft" if product.startswith("stage") else "ft^3/s")
    assert facts.quantity.value == ("stage" if product.startswith("stage") else "discharge")
    assert facts.day_definition.value is None
    assert facts.time_zone.value is None


@pytest.mark.parametrize(
    "field",
    ["time_series_id", "monitoring_location_id", "parameter_code", "statistic_id", "unit_of_measure", "time", "value"],
)
def test_required_observation_fields_are_not_defaulted(field):
    item = feature()
    del item["properties"][field]
    unsupported(decode([item]))


@pytest.mark.parametrize(
    "field,value",
    [
        ("monitoring_location_id", "USGS-02196000"),
        ("parameter_code", "00065"),
        ("statistic_id", "00001"),
        ("statistic_id", None),
        ("unit_of_measure", "ft"),
        ("time_series_id", ""),
        ("time_series_id", 123),
        ("parameter_code", 60),
    ],
)
def test_source_coordinate_contradictions(field, value):
    unsupported(decode([feature(**{field: value})]))


@pytest.mark.parametrize(
    "value", [True, False, 1.2, 123, "NaN", "Infinity", "-Infinity", "1e400", "", " 1", "1,25", {}, []]
)
def test_non_decimal_and_nonfinite_values_are_unsupported(value):
    unsupported(decode([feature(value=value)]))


@pytest.mark.parametrize("value,expected", [("1.25", 1.25), ("-2.5e1", -25.0), ("0", 0.0), (None, None)])
def test_decimal_and_present_null_remain_rows(value, expected):
    result = decode([feature(value=value)])
    assert result.rows["value"].to_list() == [expected]
    assert result.outcomes[0].status == "success"
    assert decode([]).rows.is_empty()
    assert not decode([]).issues


@pytest.mark.parametrize(
    "document",
    [
        None,
        [],
        {},
        {"type": "FeatureCollection"},
        {"type": "FeatureCollection", "features": None},
        {"type": "Other", "features": []},
    ],
)
def test_malformed_collection(document):
    unsupported(parse(payload(document), config()))


@pytest.mark.parametrize(
    "item", [None, [], {}, {"type": "Feature", "properties": []}, {"type": "Wrong", "properties": {}}]
)
def test_malformed_feature(item):
    unsupported(decode([item]))


def test_unreadable_json_is_an_identified_source_failure():
    unsupported(parse(replace(payload({}), content=b"not-json"), config()))


@pytest.mark.parametrize("stamp", ["2024-01-01T00:00:00Z", "2024-02-30", "2024-1-1", None])
def test_daily_requires_valid_date_only(stamp):
    unsupported(decode([feature(time=stamp)]))


@pytest.mark.parametrize("stamp", ["2024-01-01", "2024-01-01T01:02:03", "2024-01-01T01:02:03+25:00", None])
def test_continuous_requires_valid_offset_timestamp(stamp):
    product = "discharge_instantaneous"
    unsupported(decode([feature(product, time=stamp)], product))


@pytest.mark.parametrize("offset,zone", [("Z", "+00:00"), ("-05:00", "-05:00"), ("+05:30", "+05:30")])
def test_continuous_keeps_wall_time_and_published_offset(offset, zone):
    product = "discharge_instantaneous"
    result = decode([feature(product, time="2024-01-01T01:02:03.123456" + offset)], product)
    assert result.rows["time"].to_list() == [datetime(2024, 1, 1, 1, 2, 3, 123456)]
    assert result.rows["time_zone"].to_list() == [zone]


@pytest.mark.parametrize("qualifier", [None, "ESTIMATED", ["ESTIMATED", "DISCONTINUED"], []])
def test_source_qualifier_representations_are_accepted(qualifier):
    assert decode([feature(qualifier=qualifier)]).rows.height == 1


@pytest.mark.parametrize("qualifier", [True, 1, {}, ["ESTIMATED", None]])
def test_malformed_qualifier_is_not_silently_accepted(qualifier):
    unsupported(decode([feature(qualifier=qualifier)]))


def test_equal_valued_siblings_are_not_collapsed():
    result = decode([feature(), feature(time_series_id="opaque-series-b")])
    assert result.rows.height == 2
    assert len(result.series) == 2
    assert result.rows["series_id"].n_unique() == 2


def test_record_revision_does_not_change_series_identity():
    first = feature()
    second = {**first, "id": "different-record-revision"}
    assert_frame_equal(decode([first]).rows, decode([second]).rows)
    assert decode([first]).series == decode([second]).series


def test_invalid_series_rows_do_not_discard_independent_siblings():
    good = feature(time_series_id="opaque-series-b")
    baseline = decode([good])
    result = decode([feature(value="NaN"), good])
    assert_frame_equal(result.rows, baseline.rows)
    assert {outcome.status for outcome in result.outcomes} == {"success", "unsupported"}
    assert len(result.series) == 2


def test_known_identity_preserved_on_coordinate_failure():
    known = decode([feature()]).series
    result = decode([feature(parameter_code="00065"), feature(time_series_id="opaque-series-b")], known=known)
    failed = next(outcome for outcome in result.outcomes if outcome.status == "unsupported")
    assert failed.series_id == known[0].series_id
    assert result.rows.height == 1


def test_conflicting_same_series_time_removes_only_that_series():
    good = feature(time_series_id="opaque-series-b")
    result = decode([feature(), feature(value="2"), good])
    assert_frame_equal(result.rows, decode([good]).rows)
    assert any("Conflicting observations" in (outcome.reason or "") for outcome in result.outcomes)


def test_unknown_continuous_statistic_broad_admission_not_precise_instantaneous():
    product = "discharge_instantaneous"
    result = decode([feature(product, statistic_id=None)], product)
    facts = result.series[0].facts[0]
    assert admission(facts).status == "supported"
    assert facts.statistic.value is None
    assert facts.temporal_support.value is None
    assert SeriesScope().matches_facts(facts)
    for field in ("statistic", "temporal_support"):
        assert not SeriesScope(predicates=(PhysicalPredicate(field=field, value="instantaneous"),)).matches_facts(facts)


@pytest.mark.parametrize("description", [None, "", "[(2)]"])
def test_exact_metadata_description_survives_observation_parse(description):
    product = "discharge_daily_mean"
    properties = feature()["properties"] | {
        "id": "opaque-series-a",
        "computation_period_identifier": "Daily",
        "computation_identifier": "Mean",
        "web_description": description,
        "sublocation_identifier": None,
    }
    coordinates = config().products[ProductId(product)].coordinates.value
    known = source_series(
        properties, "07374000", product, coordinates, metadata=True, monitoring_location_id="USGS-07374000"
    )
    result = decode([feature()], known=(known,))
    assert result.series[0].identity.description == description


def test_daily_label_has_no_inferred_timezone_or_support_bounds():
    result = decode([feature()])
    assert result.rows["time"].to_list() == [datetime(2024, 1, 1)]
    assert result.rows["time_zone"].to_list() == ["unknown"]
    facts = result.series[0].facts[0]
    assert facts.clipping_axis == "calendar_date"
    assert facts.day_definition.value is None


def test_invalid_coordinate_and_valid_row_share_failure_identity_without_catalogue():
    result = decode([feature(parameter_code="00065"), feature(), feature(time_series_id="opaque-series-b")])
    expected = decode([feature(time_series_id="opaque-series-b")])
    assert_frame_equal(result.rows, expected.rows)
    failed = next(outcome for outcome in result.outcomes if outcome.status == "unsupported")
    target = decode([feature()]).series[0]
    assert failed.series_id == target.series_id


@pytest.mark.parametrize("catalogued", [False, True])
@pytest.mark.parametrize("field,value", [("monitoring_location_id", "USGS-02196000"), ("parameter_code", "00065")])
def test_coordinate_failures_retain_identity_and_request_scope(catalogued, field, value):
    target = decode([feature()]).series[0]
    result = decode([feature(**{field: value})], known=(target,) if catalogued else ())
    unsupported(result)
    outcome = result.outcomes[0]
    assert outcome.series_id == target.series_id
    assert outcome.station_id == "07374000"
    assert outcome.product_id == "discharge_daily_mean"
    assert bool(outcome.facts_ids) == catalogued
    assert result.issues[0].details["series_id"] == target.series_id
    assert result.issues[0].details["station_id"] == "07374000"


@pytest.mark.parametrize("identifier", [None, "", " ", 123])
def test_unattributable_source_failure_retains_requested_scope(identifier):
    result = decode([feature(time_series_id=identifier)])
    unsupported(result)
    assert result.outcomes[0].series_id is None
    assert result.outcomes[0].station_id == "07374000"
    assert result.outcomes[0].product_id == "discharge_daily_mean"
    assert result.issues[0].details["series_id"] is None


def test_unknown_internal_product_is_fatal_not_a_source_issue():
    from rivretrieve._internal.issues import FatalContractError

    original = payload({"type": "FeatureCollection", "features": []})
    invalid = replace(original, station_products=(("07374000", ProductId("undeclared")),))
    with pytest.raises(FatalContractError, match="absent from provider configuration"):
        parse(invalid, config())


def test_retrieval_instant_is_part_of_outcome_identity_not_source_series_identity():
    from datetime import timedelta

    original = payload({"type": "FeatureCollection", "features": [feature()]})
    later = replace(
        original, origin=replace(original.origin, retrieved_at=original.origin.retrieved_at + timedelta(days=1))
    )
    first, second = parse(original, config()), parse(later, config())
    assert first.series == second.series
    assert first.outcomes[0].outcome_id != second.outcomes[0].outcome_id
    assert second.outcomes[0].retrieved_at == later.origin.retrieved_at


@pytest.mark.parametrize("alias", ["2024-01-01T01:00:00.000000+00:00", "2024-01-01T02:00:00+01:00"])
def test_equivalent_timestamp_spellings_cannot_hide_conflicting_observations(alias):
    first = feature("discharge_instantaneous", time="2024-01-01T01:00:00Z")
    conflict = feature("discharge_instantaneous", time=alias, value="99.5")
    unsupported(decode([first, conflict], "discharge_instantaneous"))


def test_equal_wall_labels_with_different_published_offsets_are_distinct_instants():
    first = feature("discharge_instantaneous", time="2024-01-01T01:00:00Z")
    other = feature("discharge_instantaneous", time="2024-01-01T01:00:00+01:00", value="99.5")
    result = decode([first, other], "discharge_instantaneous")
    assert result.rows.height == 2
    assert set(result.rows["time_zone"]) == {"+00:00", "+01:00"}


def test_internal_model_validation_cannot_be_reported_as_a_source_limitation(monkeypatch):
    import rivretrieve._internal.providers.usgs_nwis.metadata as metadata
    from rivretrieve._internal.issues import FatalContractError

    original = metadata.PhysicalFacts

    def invalid_internal_facts(**kwargs):
        return original(facts_id="")

    monkeypatch.setattr(metadata, "PhysicalFacts", invalid_internal_facts)
    with pytest.raises(FatalContractError, match="Invalid internal USGS"):
        decode([feature()])

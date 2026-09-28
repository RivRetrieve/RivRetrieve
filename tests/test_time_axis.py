"""Axis conversion requires explicit source offsets; coverage never mixes axes."""

from datetime import datetime, timedelta

import polars as pl
import polars.testing as pt
import pytest

from rivretrieve._internal.coverage import (
    CoverageInterval,
    RequestedInterval,
    interval_envelope,
    remainder,
    served_coverage,
)
from rivretrieve._internal.time_axis import TimeAxis, axis_time_expression, timestamp_on_axis


def test_axis_expression_converts_only_valid_published_fixed_offsets():
    label = datetime(2024, 1, 2)
    zones = ["+00:00", "+05:30", "-03:45", "+23:59", "-23:59", "unknown", "Europe/Paris", "+24:00", "+01:60", None]
    frame = pl.DataFrame({"time": [label] * len(zones), "time_zone": zones})
    pt.assert_frame_equal(frame.select(axis_time_expression(TimeAxis.NATIVE)), frame.select("time"))
    expected = pl.DataFrame(
        {
            "time": [
                label,
                label - timedelta(hours=5, minutes=30),
                label + timedelta(hours=3, minutes=45),
                label - timedelta(hours=23, minutes=59),
                label + timedelta(hours=23, minutes=59),
                None,
                None,
                None,
                None,
                None,
            ]
        }
    )
    pt.assert_frame_equal(frame.select(axis_time_expression(TimeAxis.UTC)), expected)


def test_remainder_preserves_axis_and_rejects_mixed_axis():
    start, middle, end = (datetime(2024, 1, day) for day in (1, 2, 3))
    requested = RequestedInterval(start, end, axis=TimeAxis.UTC)
    held = RequestedInterval(middle, middle, axis=TimeAxis.UTC)
    assert remainder(requested, (held,)) == (
        RequestedInterval(start, middle - timedelta(microseconds=1), axis=TimeAxis.UTC),
        RequestedInterval(middle + timedelta(microseconds=1), end, axis=TimeAxis.UTC),
    )
    with pytest.raises(ValueError, match="different time axis"):
        remainder(requested, (RequestedInterval(start, end),))


def test_served_coverage_filters_unlike_axes_and_preserves_axis():
    start, middle, end = (datetime(2024, 1, day) for day in (1, 2, 3))
    native = CoverageInterval("series", RequestedInterval(start, end), None, "native")
    utc = CoverageInterval("series", RequestedInterval(start, end, axis=TimeAxis.UTC), None, "utc")
    requested = RequestedInterval(middle, end, axis=TimeAxis.UTC)
    assert served_coverage((native, utc), "series", requested) == (CoverageInterval("series", requested, None, "utc"),)


def test_native_request_envelope_is_conservative_not_a_zone_assignment():
    interval = RequestedInterval(datetime(2024, 1, 1), datetime(2024, 1, 2))
    assert interval_envelope(interval, TimeAxis.NATIVE) is interval
    expanded = interval_envelope(interval, TimeAxis.UTC)
    assert expanded == RequestedInterval(datetime(2023, 12, 31, 0, 1), datetime(2024, 1, 2, 23, 59), axis=TimeAxis.UTC)
    assert interval_envelope(expanded, TimeAxis.UTC) is expanded
    assert interval_envelope(expanded, TimeAxis.NATIVE).axis == TimeAxis.NATIVE
    extremes = interval_envelope(RequestedInterval(datetime.min, datetime.max), TimeAxis.UTC)
    assert extremes == RequestedInterval(datetime.min, datetime.max, axis=TimeAxis.UTC)


@pytest.mark.parametrize("zone", ["+00:00", "+05:30", "-03:45", "unknown", "Europe/Paris", "+24:00", None])
def test_scalar_timestamp_conversion_matches_frame_expression(zone):
    label = datetime(2024, 1, 2)
    frame = pl.DataFrame({"time": [label], "time_zone": [zone]}, schema={"time": pl.Datetime, "time_zone": pl.String})
    assert timestamp_on_axis(label, zone, TimeAxis.NATIVE) == label
    assert timestamp_on_axis(label, zone, TimeAxis.UTC) == frame.select(axis_time_expression(TimeAxis.UTC)).item()


@pytest.mark.parametrize("zone,hours", [("-05:00", -5), ("+03:00", 3), ("unknown", 0)])
def test_isolated_utc_store_coverage_uses_published_offset_across_native_year_boundary(tmp_path, zone, hours):
    from rivretrieve._internal.engine import RowsSchema
    from rivretrieve._internal.issues import FatalContractError
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.provider_series import SeriesMapping
    from rivretrieve._internal.source_series import RetrievalOutcome, SeriesWindow
    from rivretrieve._internal.store import StoreReader, StoreRoot
    from rivretrieve._internal.store.accumulation import StoreUpdate, SuccessfulReplacement, accumulate

    definition = SeriesMapping(
        namespace="authored",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        evidence=("authored axis control",),
    ).source_series("axis_control", "station", "discharge")
    fact = definition.facts[0]
    instant = datetime(2024, 1, 1)
    label = instant + timedelta(hours=hours)
    rows = pl.DataFrame(
        [
            {
                "station_id": "station",
                "product_id": "discharge",
                "time": label,
                "value": 2.0,
                "time_zone": zone,
                "series_id": definition.series_id,
                "facts_id": fact.facts_id,
                "source_unit": "m3/s",
            }
        ],
        schema=RowsSchema.polars_schema,
    )
    outcome = RetrievalOutcome(
        outcome_id="utc-source",
        series_id=definition.series_id,
        station_id="station",
        product_id="discharge",
        window=SeriesWindow(start=instant, end=instant, axis=TimeAxis.UTC),
        status="success",
        facts_ids=(fact.facts_id,),
    )
    coverage = CoverageInterval(
        definition.series_id,
        RequestedInterval(instant, instant, axis=TimeAxis.UTC),
        None,
        outcome.outcome_id,
        (fact.facts_id,),
    )
    update = StoreUpdate((definition,), (), (outcome,), (SuccessfulReplacement(coverage, rows),))
    store = StoreRoot(tmp_path / "store")
    if zone == "unknown":
        with pytest.raises(FatalContractError, match="Replacement rows exceed"):
            accumulate(store, ProviderId("axis_control"), update)
        return
    manifest = accumulate(store, ProviderId("axis_control"), update)
    assert manifest.coverage == (coverage,)
    assert StoreReader().status(store, ProviderId("axis_control")).manifest.coverage == (coverage,)
    persisted = pl.concat([pl.read_parquet(path) for path in store.rglob("*.parquet")])
    pt.assert_frame_equal(persisted.select("time", "time_zone", "value"), rows.select("time", "time_zone", "value"))


def test_all_scope_member_proof_uses_only_complete_contributor_absence():
    from types import SimpleNamespace

    from rivretrieve._internal.driver import _covered_facts
    from rivretrieve._internal.provider_series import SeriesMapping
    from rivretrieve._internal.source_series import InventorySnapshot, SeriesScope, SeriesWindow

    definition = SeriesMapping(
        namespace="authored",
        quantity="discharge",
        source_unit="m3/s",
        normalized_unit="m3/s",
        evidence=("authored finite identity control",),
    ).source_series("axis_control", "station", "discharge")
    start, middle, end = datetime(2024, 1, 1), datetime(2024, 1, 2), datetime(2024, 1, 3)
    scope = SeriesScope(provider_ids=("axis_control",), station_ids=("station",), product_ids=("discharge",))
    coverage = CoverageInterval(
        definition.series_id,
        RequestedInterval(start, middle - timedelta(microseconds=1)),
        None,
        "first-span",
        (definition.facts[0].facts_id,),
    )
    missing = InventorySnapshot(
        snapshot_id="second-span",
        scope=scope,
        members=(),
        completeness="complete",
        origin="response",
        access="exhaustive finite authored query",
        window=SeriesWindow(start=middle, end=end),
        evidence=("control",),
    )
    manifest = SimpleNamespace(coverage=(coverage,))
    window = SeriesWindow(start=start, end=end)
    assert not _covered_facts(manifest, definition, scope, window)
    assert _covered_facts(manifest, definition, scope, window, (missing,))
    different_facts = missing.model_copy(
        update={"members": (definition.series_id,), "member_facts": ((definition.series_id, ("other-source-facts",)),)}
    )
    assert _covered_facts(manifest, definition, scope, window, (different_facts,))
    unspecified_facts = missing.model_copy(update={"members": (definition.series_id,), "member_facts": ()})
    assert not _covered_facts(manifest, definition, scope, window, (unspecified_facts,))
    assert not _covered_facts(
        manifest, definition, scope, window, (missing.model_copy(update={"completeness": "incomplete"}),)
    )

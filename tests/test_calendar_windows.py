"""Established aggregate calendars select unchanged source timestamp labels."""

from datetime import datetime

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rivretrieve._internal.conversion import convert
from rivretrieve._internal.driver import _clip_native, _require_canonical_rows_within_requested
from rivretrieve._internal.engine import (
    ProductConfig,
    ProviderConfig,
    RequestedWindow,
    RowsSchema,
    SourceCoordinates,
    Unit,
    UnknownTemporalSupport,
    WindowEndpoint,
    ZoneValue,
)
from rivretrieve._internal.primitives import ProductId
from rivretrieve._internal.providers.ch_foen.official_series import source_series


def _definition(period="1month", station="synthetic", name="synthetic"):
    return source_series(
        station,
        f"data_{period}_mean",
        "Q",
        name,
        units=("m3/s",),
        evidence="synthetic units",
        temporal_evidence="synthetic calendar",
        origin="response",
    )


def _rows(definition, labels):
    return pl.DataFrame(
        [
            {
                "station_id": definition.station_id,
                "product_id": definition.product_id,
                "series_id": definition.series_id,
                "facts_id": definition.facts[0].facts_id,
                "source_unit": "m3/s",
                "time": datetime.fromisoformat(label),
                "time_zone": "+00:00",
                "value": 1.0,
            }
            for label in labels
        ],
        schema=RowsSchema.polars_schema,
    )


def _window(start, end):
    return RequestedWindow(
        WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
        WindowEndpoint.from_datetime(datetime.fromisoformat(end)),
    )


def _config(definition):
    return ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId(definition.product_id): ProductConfig(
                SourceCoordinates("synthetic"), Unit.M3_S, UnknownTemporalSupport()
            )
        },
    )


@pytest.mark.parametrize(
    "period,start,end,labels",
    [
        ("1day", "2025-02-01", "2025-02-28T23:59:59.999999", ["2025-01-31T23:00", "2025-02-28T23:00"]),
        ("1month", "2025-02-01", "2025-02-28T23:59:59.999999", ["2025-01-31T23:00", "2025-02-28T23:00"]),
        ("1month", "2025-07-01", "2025-07-31T23:59:59.999999", ["2025-06-30T23:00", "2025-07-31T23:00"]),
        ("1year", "2025-01-01", "2025-12-31T23:59:59.999999", ["2024-12-31T23:00", "2025-12-31T23:00"]),
    ],
)
def test_calendar_clipping_preserves_native_start_labels(period, start, end, labels):
    definition = _definition(period)
    rows = _rows(definition, labels)
    window = _window(start, end)
    result = convert(rows, _config(definition), window, series=(definition,)).value
    assert result["time"].to_list() == [datetime.fromisoformat(labels[0])]
    assert_frame_equal(_clip_native(rows, (definition,), window), rows.head(1))
    _require_canonical_rows_within_requested(result, (definition,), window)


def test_adjacent_month_and_unknown_support_use_distinct_coordinates():
    definition = _definition()
    rows = _rows(definition, ["2025-02-28T23:00"])
    march = _window("2025-03-01", "2025-03-01T23:59:59.999999")
    assert convert(rows, _config(definition), march, series=(definition,)).value.height == 1
    unknown = _definition("1day", "7008", "MonatsMittel_Orbe_flex")
    unknown_rows = _rows(unknown, ["2025-02-28T23:00"])
    assert convert(unknown_rows, _config(unknown), march, series=(unknown,)).value.is_empty()
    feb = _window("2025-02-01", "2025-02-28T23:59:59.999999")
    assert convert(unknown_rows, _config(unknown), feb, series=(unknown,)).value.height == 1


@pytest.mark.parametrize("mixed_support", [False, True])
@pytest.mark.parametrize("known_before_fetch", [False, True])
def test_calendar_cache_reuse_reads_previous_year_and_failed_refresh_retains_it(
    tmp_path, known_before_fetch, mixed_support
):
    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.engine import ObservationRequest
    from rivretrieve._internal.observations import ObservationProvenance
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.source_series import OutcomeStatus, known
    from rivretrieve._internal.store import StoreRoot
    from tests.test_independent_fact_cache import _FactStages

    stages = _FactStages()
    stages.members = ("mean",)
    original = stages.definition
    fact = original.facts[0].model_copy(
        update={
            "frequency": known("daily", "synthetic calendar"),
            "temporal_support": known("calendar_day", "synthetic calendar"),
            "day_definition": known("UTC+01:00", "synthetic calendar"),
            "timestamp_anchor": known("start", "synthetic calendar"),
            "time_zone": known("UTC", "synthetic labels"),
        }
    )
    stages.definition = original.model_copy(update={"facts": (fact, original.facts[1]) if mixed_support else (fact,)})
    if mixed_support:
        stages.members = ("mean", "max")
    stages.row_times = (datetime(2024, 12, 31, 23), datetime(2025, 1, 1, 23))
    request = ObservationRequest(
        ProviderId("independent_facts"),
        ("station-1",),
        (ProductId("level"),),
        _window("2025-01-01", "2025-01-01T23:59:59.999999"),
        known_series=(stages.definition,) if known_before_fetch else (),
    )

    def fetch(cache):
        return drive(
            request,
            stages,
            provenance=ObservationProvenance(source="synthetic", provider_id=request.provider_id),
            transport=object(),
            cache=cache,
            store=StoreRoot(tmp_path / "store"),
        )

    fresh = fetch("reuse")
    assert fresh.canonical_rows.filter(pl.col("facts_id") == "mean")["time"].to_list() == [datetime(2024, 12, 31, 23)]
    if mixed_support:
        assert fresh.canonical_rows.filter(pl.col("facts_id") == "max")["time"].to_list() == [datetime(2025, 1, 1, 23)]
    stages.forbid_fetch = True
    reused = fetch("reuse")
    assert_frame_equal(fresh.canonical_rows, reused.canonical_rows)
    stages.forbid_fetch = False
    stages.status["mean"] = OutcomeStatus.FAILED
    failed = fetch("refresh")
    assert_frame_equal(fresh.canonical_rows, failed.canonical_rows)
    assert any(outcome.status is OutcomeStatus.FAILED for outcome in failed.outcomes)


def test_source_failure_intervals_do_not_use_calendar_date_clipping():
    from rivretrieve._internal.coverage import RequestedInterval
    from rivretrieve._internal.driver import _exclude_native_intervals

    definition = _definition("1day")
    rows = _rows(definition, ["2025-01-31T23:00", "2025-02-01T23:00"])
    interval = RequestedInterval(datetime(2025, 2, 1), datetime(2025, 2, 1, 12))
    remaining = _exclude_native_intervals(
        rows, (definition,), ((definition.series_id, (definition.facts[0].facts_id,), interval),)
    )
    assert_frame_equal(remaining, rows)


def test_request_planning_uses_native_calendar_bounds():
    from rivretrieve._internal.coverage import RequestedInterval
    from rivretrieve._internal.driver import _requested_interval

    calendar = _definition()
    february = _window("2025-02-01", "2025-02-28T23:59:59.999999")
    assert _requested_interval(february, UnknownTemporalSupport(), facts=calendar.facts) == RequestedInterval(
        datetime(2025, 1, 31, 23), datetime(2025, 2, 28, 22, 59, 59, 999999)
    )


@pytest.mark.parametrize("period", ["1month", "1year"])
def test_calendar_month_and_year_preserve_explicit_clock_bounds(period):
    definition = _definition(period)
    rows = _rows(definition, ["2024-12-31T23:00"])
    # Midnight in the established calendar is outside a noon-only request.
    window = _window("2025-01-01T12:00", "2025-01-01T13:00")
    assert convert(rows, _config(definition), window, series=(definition,)).value.is_empty()
    midnight = _window("2025-01-01T00:00", "2025-01-01T00:00")
    assert convert(rows, _config(definition), midnight, series=(definition,)).value.height == 1


def test_established_daily_calendar_retains_whole_date_clipping():
    definition = _definition("1day")
    rows = _rows(definition, ["2024-12-31T23:00"])
    window = _window("2025-01-01T12:00", "2025-01-01T13:00")
    assert convert(rows, _config(definition), window, series=(definition,)).value.height == 1

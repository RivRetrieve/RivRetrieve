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


def test_calendar_month_clipping_axis_validation():
    from rivretrieve._internal.source_series import ClippingAxis, EvidenceState, PhysicalFacts, known

    monthly = PhysicalFacts(
        facts_id="monthly-labels",
        quantity=known("discharge", "synthetic"),
        source_unit=known("m3/s", "synthetic"),
        normalized_unit="m3/s",
        frequency=known("monthly", "synthetic"),
        clipping_axis=ClippingAxis.CALENDAR_MONTH,
    )
    assert monthly.clipping_axis is ClippingAxis.CALENDAR_MONTH
    assert monthly.temporal_support.state is EvidenceState.NOT_ESTABLISHED
    assert monthly.time_zone.state is EvidenceState.NOT_ESTABLISHED
    assert monthly.timestamp_anchor.state is EvidenceState.NOT_ESTABLISHED
    assert monthly.day_definition.state is EvidenceState.NOT_ESTABLISHED

    with pytest.raises(ValueError, match="monthly"):
        PhysicalFacts(
            facts_id="unknown-freq",
            clipping_axis=ClippingAxis.CALENDAR_MONTH,
        )

    with pytest.raises(ValueError, match="monthly"):
        PhysicalFacts(
            facts_id="daily-freq",
            frequency=known("daily", "synthetic"),
            clipping_axis=ClippingAxis.CALENDAR_MONTH,
        )


@pytest.mark.parametrize(
    "start,end,expected_start,expected_end",
    [
        ("2025-01-15T12:00", "2025-03-10T06:30", "2025-01-01T00:00:00", "2025-03-31T23:59:59.999999"),
        ("2024-12-15", "2025-01-10", "2024-12-01T00:00:00", "2025-01-31T23:59:59.999999"),
        ("2024-02-10", "2024-02-20", "2024-02-01T00:00:00", "2024-02-29T23:59:59.999999"),
        ("2025-02-10", "2025-02-20", "2025-02-01T00:00:00", "2025-02-28T23:59:59.999999"),
    ],
)
def test_native_window_expands_calendar_month_bounds(start, end, expected_start, expected_end):
    from rivretrieve._internal.coverage import RequestedInterval
    from rivretrieve._internal.physical_window import native_window
    from rivretrieve._internal.source_series import ClippingAxis, PhysicalFacts, known

    facts = PhysicalFacts(
        facts_id="monthly-labels",
        frequency=known("monthly", "synthetic"),
        clipping_axis=ClippingAxis.CALENDAR_MONTH,
    )
    assert native_window(datetime.fromisoformat(start), datetime.fromisoformat(end), facts) == RequestedInterval(
        datetime.fromisoformat(expected_start), datetime.fromisoformat(expected_end)
    )


def test_native_window_calendar_month_applies_established_offset_after_expansion():
    from rivretrieve._internal.coverage import RequestedInterval
    from rivretrieve._internal.physical_window import native_window
    from rivretrieve._internal.source_series import ClippingAxis, PhysicalFacts, known

    facts = PhysicalFacts(
        facts_id="monthly-offset",
        frequency=known("monthly", "synthetic"),
        temporal_support=known("calendar_month", "synthetic"),
        day_definition=known("UTC+01:00", "synthetic"),
        timestamp_anchor=known("start", "synthetic"),
        time_zone=known("UTC", "synthetic"),
        clipping_axis=ClippingAxis.CALENDAR_MONTH,
    )
    assert native_window(
        datetime.fromisoformat("2025-01-15T12:00"), datetime.fromisoformat("2025-03-10T06:30"), facts
    ) == RequestedInterval(
        datetime.fromisoformat("2024-12-31T23:00:00"), datetime.fromisoformat("2025-03-31T22:59:59.999999")
    )


def test_drive_store_calendar_month_selection_annotations_and_outcomes(tmp_path):
    from dataclasses import replace

    from rivretrieve._internal.driver import drive_store
    from rivretrieve._internal.engine import ObservationRequest
    from rivretrieve._internal.observations import ObservationProvenance
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.source_annotations import (
        AnnotationBundle,
        AnnotationField,
        AnnotationSchema,
        AnnotationScope,
        ObservationAnnotationTable,
    )
    from rivretrieve._internal.source_series import (
        ClippingAxis,
        OutcomeStatus,
        PhysicalFacts,
        SeriesWindow,
        SourceIdentity,
        SourceSeries,
        known,
        stable_id,
    )
    from rivretrieve._internal.store import certify_store
    from tests.store.certification_support import artifact_and_request, complete

    month_facts = PhysicalFacts(
        facts_id="month-labels",
        quantity=known("discharge", "synthetic"),
        source_unit=known("m3/s", "synthetic"),
        normalized_unit="m3/s",
        frequency=known("monthly", "synthetic"),
        clipping_axis=ClippingAxis.CALENDAR_MONTH,
    )
    ts_facts = PhysicalFacts(
        facts_id="timestamp-monthly",
        quantity=known("discharge", "synthetic"),
        source_unit=known("m3/s", "synthetic"),
        normalized_unit="m3/s",
        frequency=known("monthly", "synthetic"),
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    )
    month_series = SourceSeries(
        series_id=stable_id("fixture_bulk", "station-1", "discharge", "month-labels"),
        provider_id="fixture_bulk",
        station_id="station-1",
        product_id="discharge",
        identity=SourceIdentity(namespace="synthetic", published_id="month-labels", origin="mapping", evidence=("s",)),
        variant="month-labels",
        facts=(month_facts,),
    )
    ts_series = SourceSeries(
        series_id=stable_id("fixture_bulk", "station-1", "discharge", "ts-monthly"),
        provider_id="fixture_bulk",
        station_id="station-1",
        product_id="discharge",
        identity=SourceIdentity(namespace="synthetic", published_id="ts-monthly", origin="mapping", evidence=("s",)),
        variant="ts-monthly",
        facts=(ts_facts,),
    )

    month_times = [
        datetime(2024, 2, 1),
        datetime(2024, 12, 1),
        datetime(2025, 1, 1),
        datetime(2025, 2, 1),
        datetime(2025, 3, 1),
        datetime(2025, 4, 1),
    ]
    ts_times = [
        datetime(2024, 12, 1),
        datetime(2025, 1, 1),
        datetime(2025, 2, 1),
        datetime(2025, 3, 1),
        datetime(2025, 4, 1),
    ]
    all_records = [
        {
            "product": "discharge",
            "station_id": "station-1",
            "time": ts,
            "time_zone": "unknown",
            "value": float(idx + 1),
            "value_state": "published_value",
            "series_id": month_series.series_id,
            "facts_id": month_facts.facts_id,
            "source_unit": "m3/s",
            "raw_value": str(idx + 1),
        }
        for idx, ts in enumerate(month_times)
    ] + [
        {
            "product": "discharge",
            "station_id": "station-1",
            "time": ts,
            "time_zone": "+00:00",
            "value": float(idx + 10),
            "value_state": "published_value",
            "series_id": ts_series.series_id,
            "facts_id": ts_facts.facts_id,
            "source_unit": "m3/s",
            "raw_value": str(idx + 10),
        }
        for idx, ts in enumerate(ts_times)
    ]
    decoded = pl.DataFrame(
        all_records,
        schema={
            "product": pl.String,
            "station_id": pl.String,
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "value": pl.Float64,
            "value_state": pl.String,
            "series_id": pl.String,
            "facts_id": pl.String,
            "source_unit": pl.String,
            "raw_value": pl.String,
        },
    )
    ann_schema = AnnotationSchema(
        schema_id="fixture_bulk.obs",
        provider_id="fixture_bulk",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="note", dtype="String", description="Monthly note."),),
    )
    ann_rows = pl.DataFrame(
        {
            "series_id": [month_series.series_id] * 6,
            "facts_id": [month_facts.facts_id] * 6,
            "station_id": ["station-1"] * 6,
            "product_id": ["discharge"] * 6,
            "time": [
                datetime(2024, 12, 1),
                datetime(2025, 1, 1),
                datetime(2025, 4, 1),
                datetime(2024, 12, 1),
                datetime(2025, 2, 1),
                datetime(2025, 4, 1),
            ],
            "time_zone": ["unknown"] * 6,
            "measured": [True, True, True, False, False, False],
            "note": ["m-dec", "m-jan", "m-apr", "u-dec", "u-feb", "u-apr"],
        },
        schema={
            "series_id": pl.String,
            "facts_id": pl.String,
            "station_id": pl.String,
            "product_id": pl.String,
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "measured": pl.Boolean,
            **ann_schema.polars_schema(),
        },
    )
    bundle = AnnotationBundle(
        observation_tables={
            "fixture_bulk.obs": ObservationAnnotationTable.from_rows(
                schema=ann_schema, rows=ann_rows, measurement_indices=[1, 2, 5, None, None, None]
            )
        }
    )

    artifact, compile_req = artifact_and_request(tmp_path)
    compile_req = replace(compile_req, series=(month_series, ts_series))
    certify_store(compile_req, artifact, lambda _p: replace(complete(decoded), annotations=bundle))

    config = ProviderConfig(
        zone=ZoneValue("+00:00"),
        products={
            ProductId("discharge"): ProductConfig(SourceCoordinates("synthetic"), Unit.M3_S, UnknownTemporalSupport())
        },
    )

    def query_store(start: str, end: str):
        return drive_store(
            ObservationRequest(
                ProviderId("fixture_bulk"),
                ("station-1",),
                (ProductId("discharge"),),
                _window(start, end),
            ),
            config,
            compile_req.destination,
            provenance=ObservationProvenance(source="Bulk", provider_id=ProviderId("fixture_bulk")),
        )

    mid_month = query_store("2025-01-15", "2025-03-10")
    month_out = mid_month.canonical_rows.filter(pl.col("series_id") == month_series.series_id)
    ts_out = mid_month.canonical_rows.filter(pl.col("series_id") == ts_series.series_id)
    assert month_out["time"].to_list() == [datetime(2025, 1, 1), datetime(2025, 2, 1), datetime(2025, 3, 1)]
    assert ts_out["time"].to_list() == [datetime(2025, 2, 1), datetime(2025, 3, 1)]

    obs_ann = mid_month.annotations.observation_tables["fixture_bulk.obs"].rows
    assert obs_ann.filter(pl.col("measured"))["note"].to_list() == ["m-jan"]
    assert obs_ann.filter(~pl.col("measured"))["note"].to_list() == ["u-feb"]

    outcomes_by_series = {item.series_id: item for item in mid_month.outcomes}
    assert outcomes_by_series[month_series.series_id].status is OutcomeStatus.SUCCESS
    assert outcomes_by_series[month_series.series_id].window == SeriesWindow(
        start=datetime(2025, 1, 1), end=datetime(2025, 3, 31, 23, 59, 59, 999999)
    )
    assert outcomes_by_series[ts_series.series_id].status is OutcomeStatus.SUCCESS
    assert outcomes_by_series[ts_series.series_id].window == SeriesWindow(
        start=datetime(2025, 1, 15), end=datetime(2025, 3, 10)
    )

    year_boundary = query_store("2024-12-15", "2025-01-10")
    yb_rows = year_boundary.canonical_rows.filter(pl.col("series_id") == month_series.series_id)
    assert yb_rows["time"].to_list() == [datetime(2024, 12, 1), datetime(2025, 1, 1)]
    yb_outcome = next(item for item in year_boundary.outcomes if item.series_id == month_series.series_id)
    assert yb_outcome.window == SeriesWindow(start=datetime(2024, 12, 1), end=datetime(2025, 1, 31, 23, 59, 59, 999999))

    leap_feb = query_store("2024-02-10", "2024-02-20")
    lf_rows = leap_feb.canonical_rows.filter(pl.col("series_id") == month_series.series_id)
    assert lf_rows["time"].to_list() == [datetime(2024, 2, 1)]
    lf_outcome = next(item for item in leap_feb.outcomes if item.series_id == month_series.series_id)
    assert lf_outcome.window == SeriesWindow(start=datetime(2024, 2, 1), end=datetime(2024, 2, 29, 23, 59, 59, 999999))


def test_exclude_native_intervals_matches_calendar_month_range():
    from rivretrieve._internal.coverage import RequestedInterval
    from rivretrieve._internal.driver import _exclude_native_intervals
    from rivretrieve._internal.source_series import (
        ClippingAxis,
        PhysicalFacts,
        SourceIdentity,
        SourceSeries,
        known,
        stable_id,
    )

    month_fact = PhysicalFacts(
        facts_id="month-labels",
        quantity=known("discharge", "synthetic"),
        source_unit=known("m3/s", "synthetic"),
        normalized_unit="m3/s",
        frequency=known("monthly", "synthetic"),
        clipping_axis=ClippingAxis.CALENDAR_MONTH,
    )
    ts_fact = PhysicalFacts(
        facts_id="ts-monthly",
        quantity=known("discharge", "synthetic"),
        source_unit=known("m3/s", "synthetic"),
        normalized_unit="m3/s",
        frequency=known("monthly", "synthetic"),
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    )
    series = SourceSeries(
        series_id=stable_id("synthetic", "station-1", "discharge"),
        provider_id="synthetic",
        station_id="station-1",
        product_id="discharge",
        identity=SourceIdentity(namespace="synthetic", origin="mapping", evidence=("s",)),
        facts=(month_fact, ts_fact),
    )
    stamps = [datetime(2024, 12, 1), datetime(2025, 1, 1), datetime(2025, 2, 1), datetime(2025, 3, 1)]
    rows = pl.DataFrame(
        [
            {
                "station_id": "station-1",
                "product_id": "discharge",
                "series_id": series.series_id,
                "facts_id": fact_id,
                "source_unit": "m3/s",
                "time": stamp,
                "time_zone": "+00:00",
                "value": 1.0,
            }
            for fact_id in ("month-labels", "ts-monthly")
            for stamp in stamps
        ],
        schema=RowsSchema.polars_schema,
    )
    interval = RequestedInterval(datetime(2025, 1, 15), datetime(2025, 2, 10))
    remaining = _exclude_native_intervals(
        rows, (series,), ((series.series_id, ("month-labels", "ts-monthly"), interval),)
    )
    assert remaining.filter(pl.col("facts_id") == "month-labels")["time"].to_list() == [
        datetime(2024, 12, 1),
        datetime(2025, 3, 1),
    ]
    assert remaining.filter(pl.col("facts_id") == "ts-monthly")["time"].to_list() == [
        datetime(2024, 12, 1),
        datetime(2025, 1, 1),
        datetime(2025, 3, 1),
    ]


def test_rolling_snapshot_held_read_preserves_calendar_month_carrier(tmp_path):
    from rivretrieve._internal.driver import drive
    from rivretrieve._internal.engine import ObservationRequest
    from rivretrieve._internal.observations import ObservationProvenance
    from rivretrieve._internal.primitives import ProviderId
    from rivretrieve._internal.source_series import ClippingAxis, known
    from rivretrieve._internal.store import StoreRoot
    from tests.test_independent_fact_cache import _FactStages

    stages = _FactStages()
    stages.members = ("mean",)
    stages.snapshot = True
    original = stages.definition
    fact = original.facts[0].model_copy(
        update={
            "frequency": known("monthly", "synthetic"),
            "clipping_axis": ClippingAxis.CALENDAR_MONTH,
        }
    )
    stages.definition = original.model_copy(update={"facts": (fact,)})
    stages.row_times = (datetime(2025, 1, 1), datetime(2025, 2, 1))
    request = ObservationRequest(
        ProviderId("independent_facts"),
        ("station-1",),
        (ProductId("level"),),
        _window("2025-01-15", "2025-03-10"),
        known_series=(stages.definition,),
    )
    store = StoreRoot(tmp_path / "store")

    first = drive(
        request,
        stages,
        provenance=ObservationProvenance(source="synthetic", provider_id=request.provider_id),
        transport=object(),
        cache="reuse",
        store=store,
    )
    assert first.canonical_rows["time"].to_list() == [datetime(2025, 1, 1), datetime(2025, 2, 1)]

    stages.row_times = (datetime(2025, 2, 1),)
    refreshed = drive(
        request,
        stages,
        provenance=ObservationProvenance(source="synthetic", provider_id=request.provider_id),
        transport=object(),
        cache="refresh",
        store=store,
    )
    assert sorted(refreshed.canonical_rows["time"].to_list()) == [datetime(2025, 1, 1), datetime(2025, 2, 1)]

"""Source-independent tests for NRFA series identities, physical facts, and annotations (#595)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import polars as pl
import pytest

import rivretrieve as rr
from rivretrieve._internal.conversion import convert, filter_annotations_for_window
from rivretrieve._internal.coverage import CoverageInterval, RequestedInterval
from rivretrieve._internal.engine import (
    ProductConfig,
    ProviderConfig,
    RequestedWindow,
    SourceCoordinates,
    Unit,
    UnknownTemporalSupport,
    WindowEndpoint,
    ZoneValue,
)
from rivretrieve._internal.observations import (
    ObservationDataSchema,
    ObservationProvenance,
    ObservationResult,
    Receipts,
)
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.provider_series import UnsupportedSourceStructureError
from rivretrieve._internal.source_annotations import AnnotationBundle, AnnotationScope, with_annotations
from rivretrieve._internal.source_series import (
    ClippingAxis,
    EvidenceState,
    OutcomeStatus,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceSeries,
    admission,
    stable_id,
)
from rivretrieve._internal.store import StoreReader, StoreRoot
from rivretrieve._internal.store.accumulation import StoreUpdate, SuccessfulReplacement, accumulate
from rivretrieve._internal.store.reader import StoreQuery
from rivretrieve._internal.time_axis import TimeAxis, timestamp_on_axis

EXPECTED_HEADERS: dict[str, dict[str, str]] = {
    "gdf": {
        "id": "gdf",
        "name": "Gauged Daily Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Mean",
        "period": "P1D",
    },
    "ndf": {
        "id": "ndf",
        "name": "Naturalised Daily Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Mean",
        "period": "P1D",
    },
    "gmf": {
        "id": "gmf",
        "name": "Gauged Monthly Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Mean",
        "period": "P1M",
    },
    "nmf": {
        "id": "nmf",
        "name": "Naturalised Monthly Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Mean",
        "period": "P1M",
    },
    "gauging-flow": {
        "id": "gauging-flow",
        "name": "Gauging - Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Measured",
        "period": "PT1S",
    },
    "gauging-stage": {
        "id": "gauging-stage",
        "name": "Gauging - Stage",
        "parameter": "Stage",
        "units": "m",
        "measurement-type": "Measured",
        "period": "PT1S",
    },
    "amax-flow": {
        "id": "amax-flow",
        "name": "Annual Maxima - Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Maximum",
        "period": "PT15M",
    },
    "amax-stage": {
        "id": "amax-stage",
        "name": "Annual Maxima - Stage",
        "parameter": "Stage",
        "units": "m",
        "measurement-type": "Maximum",
        "period": "PT15M",
    },
    "pot-flow": {
        "id": "pot-flow",
        "name": "Peaks Over Threshold - Flow",
        "parameter": "Flow",
        "units": "m3/s",
        "measurement-type": "Measured",
        "period": "PT15M",
    },
    "pot-stage": {
        "id": "pot-stage",
        "name": "Peaks Over Threshold - Stage",
        "parameter": "Stage",
        "units": "m",
        "measurement-type": "Measured",
        "period": "PT15M",
    },
}


def _payload(product_id: str, stream: list[object], *, station_id: int = 39001) -> dict[str, object]:
    return {
        "timestamp": "2026-11-16T10:00:00Z",
        "station": {"id": station_id, "name": "Synthetic Gauge"},
        "data-type": dict(EXPECTED_HEADERS[product_id]),
        "data-stream": stream,
    }


def _provider_config() -> ProviderConfig:
    products = {
        ProductId(pid): ProductConfig(
            coordinates=SourceCoordinates(pid),
            unit=Unit("m" if pid.endswith("stage") else "m3/s"),
            semantics=UnknownTemporalSupport(),
        )
        for pid in EXPECTED_HEADERS
    }
    return ProviderConfig(zone=ZoneValue("unknown"), products=MappingProxyType(products))


def _requested_window(start: str, end: str) -> RequestedWindow:
    return RequestedWindow(
        start=WindowEndpoint.from_datetime(datetime.fromisoformat(start)),
        end=WindowEndpoint.from_datetime(datetime.fromisoformat(end)),
    )


def _result_for_decoded(
    defined_list: tuple[SourceSeries, ...],
    canonical_rows: pl.DataFrame,
    bundle: AnnotationBundle,
    *,
    outcomes: tuple[RetrievalOutcome, ...] = (),
) -> ObservationResult:
    base = ObservationResult(
        data=canonical_rows.sort(["station_id", "product_id", "time", "series_id"])
        if not canonical_rows.is_empty()
        else canonical_rows,
        provenance=ObservationProvenance(
            source="live",
            provider_id=ProviderId("uk_nrfa"),
            request={"station": "39001"},
        ),
        receipts=Receipts(provider_id=ProviderId("uk_nrfa")),
        source_series=defined_list,
        outcomes=outcomes,
        scope=SeriesScope(provider_ids=("uk_nrfa",)),
    )
    return with_annotations(base, bundle)


def test_ten_product_identities_physical_facts_and_explicit_unknowns() -> None:
    from rivretrieve._internal.providers.uk_nrfa.series import PRODUCT_IDS, product_facts, source_series

    assert PRODUCT_IDS == (
        "gdf",
        "ndf",
        "gmf",
        "nmf",
        "gauging-flow",
        "gauging-stage",
        "amax-flow",
        "amax-stage",
        "pot-flow",
        "pot-stage",
    )
    facts_by_product = product_facts()
    assert tuple(facts_by_product) == PRODUCT_IDS

    defined = {pid: source_series("39001", pid, origin="response") for pid in PRODUCT_IDS}
    assert len({item.series_id for item in defined.values()}) == 10
    assert defined["gdf"].series_id != defined["ndf"].series_id
    assert defined["gmf"].series_id != defined["nmf"].series_id

    for pid, item in defined.items():
        assert item.series_id == stable_id("uk_nrfa", "39001", "uk_nrfa/data-type", pid)
        assert item.identity.namespace == "uk_nrfa/data-type"
        assert item.identity.published_id == pid
        assert item.identity.origin == "response"
        assert len(item.facts) == 1
        facts = item.facts[0]
        assert facts == facts_by_product[pid]
        assert isinstance(facts, PhysicalFacts)
        assert facts.facts_id == stable_id(facts.model_dump_json(exclude={"facts_id"}))

        expected_stage = pid.endswith("stage")
        assert facts.quantity.value == ("stage" if expected_stage else "discharge")
        assert facts.quantity.state == EvidenceState.KNOWN
        assert facts.source_unit.value == ("m" if expected_stage else "m3/s")
        assert facts.normalized_unit == ("m" if expected_stage else "m3/s")

        decision = admission(facts)
        assert decision.status == "supported"
        assert decision.factor == 1.0
        assert decision.target_unit == facts.normalized_unit

        # Optional temporal / datum facts remain explicitly unestablished unless verified.
        assert facts.temporal_support.state == EvidenceState.NOT_ESTABLISHED
        assert facts.day_definition.state == EvidenceState.NOT_ESTABLISHED
        assert facts.timestamp_anchor.state == EvidenceState.NOT_ESTABLISHED
        assert facts.time_zone.state == EvidenceState.NOT_ESTABLISHED
        assert facts.vertical_datum.state == EvidenceState.NOT_ESTABLISHED
        assert facts.label_time is None

        if pid in {"gdf", "ndf"}:
            assert facts.frequency.value == "daily"
            assert facts.statistic.value == "mean"
            assert facts.clipping_axis == ClippingAxis.CALENDAR_DATE
        elif pid in {"gmf", "nmf"}:
            assert facts.frequency.value == "monthly"
            assert facts.statistic.value == "mean"
            assert facts.clipping_axis == ClippingAxis.SOURCE_TIMESTAMP
        elif pid == "amax-flow":
            assert facts.frequency.state == EvidenceState.NOT_ESTABLISHED
            assert facts.statistic.value == "max"
            assert facts.clipping_axis == ClippingAxis.SOURCE_TIMESTAMP
        else:
            assert facts.frequency.state == EvidenceState.NOT_ESTABLISHED
            assert facts.statistic.state == EvidenceState.NOT_ESTABLISHED
            assert facts.clipping_axis == ClippingAxis.SOURCE_TIMESTAMP

        if expected_stage:
            assert facts.vertical_reference.value == "gauge_zero"
            assert facts.vertical_reference.state == EvidenceState.KNOWN
        else:
            assert facts.vertical_reference.state == EvidenceState.NOT_ESTABLISHED


def test_annotation_schemas_have_verified_fields_and_official_references() -> None:
    from rivretrieve._internal.providers.uk_nrfa.annotations import (
        UK_NRFA_AMAX_REJECTION_SCHEMA,
        UK_NRFA_OBSERVATIONS_SCHEMA,
        UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA,
        UK_NRFA_SERIES_METADATA_SCHEMA,
    )

    assert UK_NRFA_OBSERVATIONS_SCHEMA.schema_id == "uk_nrfa.observations"
    assert UK_NRFA_OBSERVATIONS_SCHEMA.scope is AnnotationScope.OBSERVATION
    assert UK_NRFA_OBSERVATIONS_SCHEMA.polars_schema() == {"source_label": pl.String, "flag": pl.String}

    assert UK_NRFA_SERIES_METADATA_SCHEMA.schema_id == "uk_nrfa.series_metadata"
    assert UK_NRFA_SERIES_METADATA_SCHEMA.scope is AnnotationScope.SERIES
    assert UK_NRFA_SERIES_METADATA_SCHEMA.polars_schema() == {
        "data_type_name": pl.String,
        "measurement_type": pl.String,
        "source_period": pl.String,
    }

    assert UK_NRFA_AMAX_REJECTION_SCHEMA.schema_id == "uk_nrfa.amax_rejection"
    assert UK_NRFA_AMAX_REJECTION_SCHEMA.scope is AnnotationScope.SERIES
    assert UK_NRFA_AMAX_REJECTION_SCHEMA.polars_schema() == {"rejected_amax_years": pl.List(pl.Int64)}

    assert UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.schema_id == "uk_nrfa.peak_rejected_periods"
    assert UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.scope is AnnotationScope.SERIES
    assert UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.polars_schema() == {"rejected_periods": pl.List(pl.String)}

    for schema in (
        UK_NRFA_OBSERVATIONS_SCHEMA,
        UK_NRFA_SERIES_METADATA_SCHEMA,
        UK_NRFA_AMAX_REJECTION_SCHEMA,
        UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA,
    ):
        assert schema.provider_id == "uk_nrfa"
        for field in schema.fields:
            assert field.description
            assert "—" not in field.description
            assert field.reference_url is not None
            assert field.reference_url.startswith("https://")


def test_monthly_nominal_carrier_clipping_output_and_bundles() -> None:
    from rivretrieve._internal.providers.uk_nrfa.series import decode_time_series_response

    defined, rows, bundle = decode_time_series_response(
        _payload("gmf", ["2020-01", 12.5, "2020-02", [14.0, "E"]]),
        expected_station_id="39001",
        expected_product_id="gmf",
    )
    assert rows["time"].to_list() == [datetime(2020, 1, 1, 0, 0, 0), datetime(2020, 2, 1, 0, 0, 0)]
    assert rows["time_zone"].to_list() == ["unknown", "unknown"]
    assert timestamp_on_axis(rows["time"][0], rows["time_zone"][0], TimeAxis.UTC) is None

    cfg = _provider_config()

    # January 1-31 includes January's nominal month-start label and preserves source_label & series metadata.
    win_jan = _requested_window("2020-01-01", "2020-01-31")
    conv_jan = convert(rows, cfg, win_jan, series=(defined,))
    assert not conv_jan.issues
    ann_jan = filter_annotations_for_window(rows, bundle, win_jan, series=(defined,))
    res_jan = _result_for_decoded((defined,), conv_jan.value, ann_jan)
    assert res_jan.data["value"].to_list() == [12.5]
    with_ann = res_jan.to_polars(annotations=True)
    assert with_ann["source_label"].to_list() == ["2020-01"]
    assert with_ann["flag"].to_list() == [None]
    restored_jan = rr.from_bundle(rr.to_bundle(res_jan))
    assert isinstance(restored_jan, ObservationResult)
    assert restored_jan.to_polars(annotations=True)["source_label"].to_list() == ["2020-01"]
    assert rr.annotations(restored_jan, schema="uk_nrfa.series_metadata")["source_period"].to_list() == ["P1M"]

    # February 1-28 excludes January's label and retains February's.
    win_feb = _requested_window("2020-02-01", "2020-02-28")
    conv_feb = convert(rows, cfg, win_feb, series=(defined,))
    ann_feb = filter_annotations_for_window(rows, bundle, win_feb, series=(defined,))
    res_feb = _result_for_decoded((defined,), conv_feb.value, ann_feb)
    assert res_feb.to_polars(annotations=True)["source_label"].to_list() == ["2020-02"]
    assert res_feb.to_polars(annotations=True)["flag"].to_list() == ["E"]

    # January 15-31 excludes January's nominal month-start carrier under source-timestamp clipping.
    win_mid = _requested_window("2020-01-15", "2020-01-31")
    conv_mid = convert(rows, cfg, win_mid, series=(defined,))
    ann_mid = filter_annotations_for_window(rows, bundle, win_mid, series=(defined,))
    res_mid = _result_for_decoded((defined,), conv_mid.value, ann_mid)
    empty_projected = res_mid.to_polars(annotations=True)
    assert empty_projected.is_empty()
    assert empty_projected.columns == list(ObservationDataSchema.polars_schema)
    with pytest.raises(ValueError, match="Unknown observation annotation"):
        res_mid.to_polars(annotations="source_label")
    assert rr.annotations(res_mid, schema="uk_nrfa.series_metadata")["data_type_name"].to_list() == [
        "Gauged Monthly Flow"
    ]


def test_daily_calendar_clipping_flags_nulls_peaks_and_empty_stream() -> None:
    from rivretrieve._internal.providers.uk_nrfa.annotations import (
        UK_NRFA_OBSERVATIONS_SCHEMA,
        UK_NRFA_SERIES_METADATA_SCHEMA,
    )
    from rivretrieve._internal.providers.uk_nrfa.series import decode_time_series_response

    cfg = _provider_config()

    # Daily series preserve flags, explicit null values, and whole-calendar-date clipping.
    daily_def, daily_rows, daily_bundle = decode_time_series_response(
        _payload("ndf", ["2020-01-01", [1.5, "E"], "2020-01-02", [None, "S"], "2020-01-03", None]),
        expected_station_id="39001",
        expected_product_id="ndf",
    )
    assert daily_rows["value"].to_list() == [1.5, None, None]
    obs_tbl = daily_bundle.schema_table(UK_NRFA_OBSERVATIONS_SCHEMA.schema_id)
    assert obs_tbl["flag"].to_list() == ["E", "S", None]
    win_daily = _requested_window("2020-01-01T12:00:00", "2020-01-02T06:00:00")
    conv_daily = convert(daily_rows, cfg, win_daily, series=(daily_def,))
    assert conv_daily.value["time"].to_list() == [datetime(2020, 1, 1), datetime(2020, 1, 2)]

    # Peak series keep midnight T00:00:00 timestamps and gauge-relative values untouched.
    peak_def, peak_rows, peak_bundle = decode_time_series_response(
        _payload("amax-stage", ["1999-12-25T00:00:00", 2.345, "2000-11-03T14:15:00", 3.21], station_id=6007),
        expected_station_id="6007",
        expected_product_id="amax-stage",
    )
    assert peak_rows["time"].to_list() == [datetime(1999, 12, 25, 0, 0, 0), datetime(2000, 11, 3, 14, 15, 0)]
    assert peak_rows["value"].to_list() == [2.345, 3.21]
    assert peak_def.facts[0].statistic.state == EvidenceState.NOT_ESTABLISHED
    assert peak_bundle.schema_table(UK_NRFA_OBSERVATIONS_SCHEMA.schema_id)["source_label"].to_list() == [
        "1999-12-25T00:00:00",
        "2000-11-03T14:15:00",
    ]

    # Empty stream emits 0 rows, omits observation annotation table, and retains series metadata.
    empty_def, empty_rows, empty_bundle = decode_time_series_response(
        _payload("nmf", []),
        expected_station_id="39001",
        expected_product_id="nmf",
    )
    assert empty_def.product_id == "nmf"
    assert empty_rows.is_empty()
    assert not empty_bundle.observation_tables
    assert set(empty_bundle.series_tables) == {UK_NRFA_SERIES_METADATA_SCHEMA.schema_id}


@pytest.mark.parametrize(
    ("product_id", "override", "expected_station", "expected_product"),
    [
        ("gdf", {"data-stream": ["2020-01-01"]}, "39001", "gdf"),  # dates=false / odd stream
        ("gdf", {"data-stream": ["2020-01-01", True]}, "39001", "gdf"),  # bool scalar
        ("gdf", {"data-stream": ["2020-01-01", [False, "E"]]}, "39001", "gdf"),  # bool flagged
        ("gdf", {"data-stream": ["2020-01-01", float("nan")]}, "39001", "gdf"),
        ("gmf", {"data-stream": ["2020-13", 1.0]}, "39001", "gmf"),
        ("gdf", {"data-stream": ["2020-02-30", 1.0]}, "39001", "gdf"),
        ("amax-stage", {"data-stream": ["2020-01-01", 1.0]}, "39001", "amax-stage"),  # missing T00:00:00
        ("gdf", {"data-stream": ["2020-01-01", [1.0, ""]]}, "39001", "gdf"),
        ("gdf", {"data-stream": ["2020-01-01", [1.0, "E", "extra"]]}, "39001", "gdf"),
        ("gdf", {"data-type": {**EXPECTED_HEADERS["gdf"], "units": "l/s"}}, "39001", "gdf"),
        ("gdf", {}, "6007", "gdf"),  # station mismatch
        ("gdf", {}, "39001", "ndf"),  # product mismatch
    ],
)
def test_decode_time_series_response_rejects_malformed_or_mismatched_payloads(
    product_id: str,
    override: dict[str, object],
    expected_station: str,
    expected_product: str,
) -> None:
    from rivretrieve._internal.providers.uk_nrfa.series import decode_time_series_response

    payload = _payload(product_id, ["2020-01-01", 1.0])
    payload.update(override)
    with pytest.raises(UnsupportedSourceStructureError):
        decode_time_series_response(
            payload,
            expected_station_id=expected_station,
            expected_product_id=expected_product,
        )


def test_peak_rejection_annotations_preserve_null_empty_populated_narrowing_and_store_reuse(
    tmp_path: Path,
) -> None:
    from rivretrieve._internal.providers.uk_nrfa.annotations import (
        UK_NRFA_AMAX_REJECTION_SCHEMA,
        UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA,
    )
    from rivretrieve._internal.providers.uk_nrfa.series import (
        PRODUCT_IDS,
        build_peak_rejection_annotations,
        decode_time_series_response,
        source_series,
    )

    all_82001 = tuple(source_series("82001", pid, origin="response") for pid in PRODUCT_IDS)
    non_peak = tuple(
        s for s in all_82001 if s.product_id in {"gdf", "ndf", "gmf", "nmf", "gauging-flow", "gauging-stage"}
    )
    assert (
        build_peak_rejection_annotations(
            {"id": 82001, "peak-flow-rejected-amax-years": None, "peak-flow-rejected-periods": None},
            series=non_peak,
        )
        == {}
    )

    for bad_row in (
        {"id": 82001, "peak-flow-rejected-amax-years": None},
        {"id": 82001, "peak-flow-rejected-amax-years": {"excluded-years": [True]}, "peak-flow-rejected-periods": None},
        {"id": 82001, "peak-flow-rejected-amax-years": None, "peak-flow-rejected-periods": {"rejected-periods": [""]}},
    ):
        with pytest.raises(UnsupportedSourceStructureError):
            build_peak_rejection_annotations(bad_row, series=all_82001)

    # Populated vs empty vs null distinction across result, rr.series, rr.annotations, rr.pick, and bundles.
    row_populated = {
        "id": 82001,
        "peak-flow-rejected-amax-years": {"excluded-years": [1962, 1963]},
        "peak-flow-rejected-periods": {"rejected-periods": ["1963-09-05/1982-05-31"]},
    }
    row_empty = {
        "id": 82001,
        "peak-flow-rejected-amax-years": {"excluded-years": []},
        "peak-flow-rejected-periods": {"rejected-periods": []},
    }
    row_null = {
        "id": 82001,
        "peak-flow-rejected-amax-years": None,
        "peak-flow-rejected-periods": None,
    }

    tables_empty = build_peak_rejection_annotations(row_empty, series=all_82001)
    assert tables_empty[UK_NRFA_AMAX_REJECTION_SCHEMA.schema_id].rows["rejected_amax_years"].to_list() == [[], []]
    assert tables_empty[UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.schema_id].rows["rejected_periods"].to_list() == [[]] * 4

    tables_null = build_peak_rejection_annotations(row_null, series=all_82001)
    assert tables_null[UK_NRFA_AMAX_REJECTION_SCHEMA.schema_id].rows["rejected_amax_years"].to_list() == [None, None]
    assert tables_null[UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.schema_id].rows["rejected_periods"].to_list() == [None] * 4

    # Build a combined ObservationResult for amax-stage + pot-flow + gdf on station 82001.
    cfg = _provider_config()
    win = _requested_window("1963-01-01", "2001-12-31")
    amax_def, amax_rows, amax_bundle = decode_time_series_response(
        _payload("amax-stage", ["1963-11-10T00:00:00", 2.1], station_id=82001),
        expected_station_id="82001",
        expected_product_id="amax-stage",
    )
    pot_def, pot_rows, pot_bundle = decode_time_series_response(
        _payload("pot-flow", ["1964-02-01T12:00:00", 58.5], station_id=82001),
        expected_station_id="82001",
        expected_product_id="pot-flow",
    )
    gdf_def, gdf_rows, gdf_bundle = decode_time_series_response(
        _payload("gdf", ["1964-02-01", 20.0], station_id=82001),
        expected_station_id="82001",
        expected_product_id="gdf",
    )
    combined_defs = (amax_def, pot_def, gdf_def)
    combined_canonical = pl.concat(
        [
            convert(amax_rows, cfg, win, series=(amax_def,)).value,
            convert(pot_rows, cfg, win, series=(pot_def,)).value,
            convert(gdf_rows, cfg, win, series=(gdf_def,)).value,
        ]
    )
    rejection_tables = build_peak_rejection_annotations(row_populated, series=combined_defs)
    combined_bundle = AnnotationBundle(series_tables=rejection_tables)
    # Merge decoded series_metadata table across all 3 series.
    meta_rows = pl.concat(
        [
            amax_bundle.schema_table("uk_nrfa.series_metadata"),
            pot_bundle.schema_table("uk_nrfa.series_metadata"),
            gdf_bundle.schema_table("uk_nrfa.series_metadata"),
        ]
    )
    from rivretrieve._internal.providers.uk_nrfa.annotations import UK_NRFA_SERIES_METADATA_SCHEMA
    from rivretrieve._internal.source_annotations import SeriesAnnotationTable

    full_bundle = AnnotationBundle(
        series_tables={
            **combined_bundle.series_tables,
            UK_NRFA_SERIES_METADATA_SCHEMA.schema_id: SeriesAnnotationTable.from_rows(
                schema=UK_NRFA_SERIES_METADATA_SCHEMA,
                rows=meta_rows,
            ),
        }
    )
    result = _result_for_decoded(combined_defs, combined_canonical, full_bundle)
    series_df = rr.series(result, annotations=True)
    by_prod = {row["product_id"]: row for row in series_df.iter_rows(named=True)}
    assert by_prod["amax-stage"]["rejected_amax_years"] == [1962, 1963]
    assert by_prod["amax-stage"]["rejected_periods"] == ["1963-09-05/1982-05-31"]
    assert by_prod["pot-flow"]["rejected_amax_years"] is None
    assert by_prod["pot-flow"]["rejected_periods"] == ["1963-09-05/1982-05-31"]
    assert by_prod["gdf"]["rejected_amax_years"] is None
    assert by_prod["gdf"]["rejected_periods"] is None

    # Measurements remain unchanged alongside rejection annotations, bundles, and rr.pick narrowing.
    assert sorted(result.data["value"].to_list()) == [2.1, 20.0, 58.5]
    restored = rr.from_bundle(rr.to_bundle(result))
    assert isinstance(restored, ObservationResult)
    narrowed_pot = rr.pick(restored, series_id=pot_def.series_id)
    assert rr.series(narrowed_pot, annotations=True)["rejected_periods"].to_list() == [["1963-09-05/1982-05-31"]]
    narrowed_stage = rr.pick(restored, vertical_reference="gauge_zero")
    assert rr.series(narrowed_stage, annotations=True)["rejected_amax_years"].to_list() == [[1962, 1963]]
    assert narrowed_stage.data["value"].to_list() == [2.1]

    # Offline StoreRoot reuse preserves series rejection lists.
    store = StoreRoot(tmp_path / "nrfa-store")
    out = RetrievalOutcome(
        outcome_id="o-amax-1",
        series_id=amax_def.series_id,
        station_id="82001",
        product_id="amax-stage",
        window=SeriesWindow(start=datetime(1963, 1, 1), end=datetime(1963, 12, 31, 23, 59, 59)),
        status=OutcomeStatus.SUCCESS,
        facts_ids=(amax_def.facts[0].facts_id,),
        retrieved_at=datetime(2026, 11, 16, tzinfo=UTC),
    )
    accumulate(
        store,
        ProviderId("uk_nrfa"),
        StoreUpdate(
            (amax_def,),
            (),
            (out,),
            (
                SuccessfulReplacement(
                    CoverageInterval(
                        amax_def.series_id,
                        RequestedInterval(out.window.start, out.window.end),
                        out.retrieved_at,
                        out.outcome_id,
                    ),
                    amax_rows,
                    annotations=amax_bundle,
                ),
            ),
            series_annotations=(
                rejection_tables[UK_NRFA_AMAX_REJECTION_SCHEMA.schema_id],
                rejection_tables[UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.schema_id],
            ),
        ),
    )
    loaded = StoreReader().query(
        StoreQuery(
            store,
            ProviderId("uk_nrfa"),
            ("82001",),
            (ProductId("amax-stage"),),
            datetime(1963, 1, 1),
            datetime(1963, 12, 31, 23, 59, 59),
        )
    )
    assert loaded.annotations.series_tables[UK_NRFA_AMAX_REJECTION_SCHEMA.schema_id].rows[
        "rejected_amax_years"
    ].to_list() == [[1962, 1963]]
    assert loaded.annotations.series_tables[UK_NRFA_PEAK_REJECTED_PERIODS_SCHEMA.schema_id].rows[
        "rejected_periods"
    ].to_list() == [["1963-09-05/1982-05-31"]]

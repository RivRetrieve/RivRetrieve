from datetime import datetime

import polars as pl
import pytest

from rivretrieve._internal.conversion import convert
from rivretrieve._internal.engine import RequestedWindow, RowsSchema, WindowEndpoint
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.providers.usgs_nwis.config import config
from rivretrieve._internal.source_series import PhysicalFacts, SourceIdentity, SourceSeries, known


@pytest.mark.parametrize("normalized_unit", ["m", "m3/s"])
def test_conversion_refuses_dimensionally_incompatible_series_facts(normalized_unit):
    facts = PhysicalFacts(
        facts_id="contradiction",
        quantity=known("discharge", "test source definition"),
        source_unit=known("m", "test response unit"),
        normalized_unit="m",
    )
    series = SourceSeries(
        series_id="series",
        provider_id="usgs_nwis",
        station_id="07374000",
        product_id="discharge_daily_mean",
        identity=SourceIdentity(namespace="methodID", published_id="1", origin="response", evidence=("test response",)),
        facts=(facts,),
    ).model_copy(update={"facts": (facts.model_copy(update={"normalized_unit": normalized_unit}),)})
    rows = pl.DataFrame(
        [
            {
                "station_id": "07374000",
                "product_id": "discharge_daily_mean",
                "time": datetime(2023, 1, 1),
                "value": 1.0,
                "time_zone": "unknown",
                "series_id": "series",
                "facts_id": "contradiction",
                "source_unit": "m",
            }
        ],
        schema=RowsSchema.polars_schema,
    )
    window = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1)), WindowEndpoint.from_datetime(datetime(2023, 1, 2))
    )
    with pytest.raises(FatalContractError, match="admitted"):
        convert(rows, config(), window, series=(series,))


def test_conversion_refuses_conflicting_fact_identity_across_series():
    def definition(sid, unit):
        return SourceSeries(
            series_id=sid,
            provider_id="usgs_nwis",
            station_id="07374000",
            product_id="discharge_daily_mean",
            identity=SourceIdentity(namespace="methodID", published_id=sid, origin="response", evidence=("source",)),
            facts=(
                PhysicalFacts(
                    facts_id="shared",
                    quantity=known("discharge", "source"),
                    source_unit=known(unit, "source"),
                    normalized_unit=unit,
                ),
            ),
        )

    definitions = (definition("a", "m3/s"), definition("b", "ft3/s"))
    rows = pl.DataFrame(
        [
            {
                "station_id": "07374000",
                "product_id": "discharge_daily_mean",
                "time": datetime(2023, 1, 1),
                "value": 1.0,
                "time_zone": "unknown",
                "series_id": "a",
                "facts_id": "shared",
                "source_unit": "m3/s",
            }
        ],
        schema=RowsSchema.polars_schema,
    )
    window = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1)), WindowEndpoint.from_datetime(datetime(2023, 1, 2))
    )
    with pytest.raises(FatalContractError, match="fact.*identity|facts.*identity"):
        convert(rows, config(), window, series=definitions)


def test_active_explicit_scope_cannot_omit_its_identity_restriction():
    from rivretrieve._internal.source_series import RestrictionKind, SeriesScope

    with pytest.raises(ValueError, match="explicit.*restriction"):
        SeriesScope(restriction=RestrictionKind.EXPLICIT)


def test_inventory_fact_membership_cannot_reference_an_absent_series():
    from rivretrieve._internal.source_series import InventoryCompleteness, InventorySnapshot, SeriesScope

    with pytest.raises(ValueError, match="fact.*member"):
        InventorySnapshot(
            snapshot_id="snapshot",
            scope=SeriesScope(),
            members=("known",),
            member_facts=(("absent", ("fact",)),),
            completeness=InventoryCompleteness.COMPLETE,
            access="recorded scope",
            origin="response",
            evidence=("source",),
        )


def test_validate_series_rows_checks_zero_row_invalid_definition_and_cross_series_facts():
    from rivretrieve._internal.source_series import validate_series_rows

    facts_a = PhysicalFacts(
        facts_id="facts-a",
        quantity=known("discharge", "source"),
        source_unit=known("m3/s", "source"),
        normalized_unit="m3/s",
    )
    facts_b = PhysicalFacts(
        facts_id="facts-b",
        quantity=known("discharge", "source"),
        source_unit=known("ft3/s", "source"),
        normalized_unit="ft3/s",
    )
    series_a = SourceSeries(
        series_id="series-a",
        provider_id="usgs_nwis",
        station_id="07374000",
        product_id="discharge_daily_mean",
        identity=SourceIdentity(namespace="methodID", published_id="a", origin="response", evidence=("source",)),
        facts=(facts_a,),
    )
    series_b = SourceSeries(
        series_id="series-b",
        provider_id="usgs_nwis",
        station_id="07374000",
        product_id="discharge_daily_mean",
        identity=SourceIdentity(namespace="methodID", published_id="b", origin="response", evidence=("source",)),
        facts=(facts_b,),
    )
    # Invalid model_copy definition with 0 rows must still raise FatalContractError
    invalid_zero_row = series_a.model_copy(update={"facts": ()})
    empty_rows = pl.DataFrame(schema=RowsSchema.polars_schema)
    with pytest.raises(FatalContractError, match="Native series requires valid admitted physical facts"):
        validate_series_rows(empty_rows, (invalid_zero_row,))

    # Cross-series facts_id mismatch must raise even though facts-b exists on series-b
    cross_rows = pl.DataFrame(
        [
            {
                "station_id": "07374000",
                "product_id": "discharge_daily_mean",
                "time": datetime(2023, 1, 1),
                "value": 1.0,
                "time_zone": "+00:00",
                "series_id": "series-a",
                "facts_id": "facts-b",
                "source_unit": "ft3/s",
            }
        ],
        schema=RowsSchema.polars_schema,
    )
    with pytest.raises(FatalContractError, match="unknown physical facts"):
        validate_series_rows(cross_rows, (series_a, series_b))

    # Missing column raises FatalContractError rather than Polars ColumnNotFoundError
    with pytest.raises(FatalContractError, match="unknown physical facts"):
        validate_series_rows(cross_rows.drop("facts_id"), (series_a, series_b))


def test_convert_mid_series_fact_unit_change_duplicate_timestamps_and_work_counts(monkeypatch):
    import rivretrieve._internal.conversion as conv_mod
    import rivretrieve._internal.source_series as ss_mod
    from rivretrieve._internal.conversion import convert_with_annotations
    from rivretrieve._internal.source_annotations import (
        AnnotationBundle,
        AnnotationField,
        AnnotationSchema,
        AnnotationScope,
        ObservationAnnotationTable,
    )
    from rivretrieve._internal.source_series import ClippingAxis

    facts_cfs = PhysicalFacts(
        facts_id="seg-cfs",
        quantity=known("discharge", "source"),
        source_unit=known("ft3/s", "source"),
        normalized_unit="ft3/s",
        frequency=known("instantaneous", "source"),
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
    )
    facts_cms = PhysicalFacts(
        facts_id="seg-cms",
        quantity=known("discharge", "source"),
        source_unit=known("m3/s", "source"),
        normalized_unit="m3/s",
        frequency=known("daily", "source"),
        clipping_axis=ClippingAxis.CALENDAR_DATE,
        label_time="00:00",
    )
    series = SourceSeries(
        series_id="s-mixed",
        provider_id="usgs_nwis",
        station_id="07374000",
        product_id="discharge_daily_mean",
        identity=SourceIdentity(namespace="methodID", published_id="1", origin="response", evidence=("source",)),
        facts=(facts_cfs, facts_cms),
    )

    n_each = 40
    times = [
        *[datetime(2023, 1, 1, 12, 0) for _ in range(2)],
        *[datetime(2023, 1, 1, 12, 0) for _ in range(n_each - 2)],
        datetime(2023, 1, 1, 0, 0),  # out of instant window [10:00..14:00], inside daily calendar window!
        *[datetime(2023, 1, 2, 0, 0) for _ in range(n_each)],  # outside 2023-01-01
    ]
    facts_ids = [*["seg-cfs"] * n_each, *["seg-cms"] * (n_each + 1)]
    src_units = [*["ft3/s"] * n_each, *["m3/s"] * (n_each + 1)]
    values: list[float | None] = [100.0, None, *[50.0] * (n_each - 2), 7.5, *[9.0] * n_each]
    rows = pl.DataFrame(
        {
            "station_id": ["07374000"] * len(times),
            "product_id": ["discharge_daily_mean"] * len(times),
            "time": times,
            "value": values,
            "time_zone": ["+00:00"] * len(times),
            "series_id": ["s-mixed"] * len(times),
            "facts_id": facts_ids,
            "source_unit": src_units,
        },
        schema=RowsSchema.polars_schema,
    )
    ann_schema = AnnotationSchema(
        schema_id="usgs_nwis.qc",
        provider_id="usgs_nwis",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="flag", dtype="String", description="Quality flag."),),
    )
    # Attach flag only on 2nd duplicate timestamp (index 1, null value), plus the kept daily row (index 40)
    # and two unmeasured rows (one inside seg-cms calendar window on Jan 1, one outside on Jan 2).
    ann_rows = pl.DataFrame(
        {
            "series_id": ["s-mixed"] * 4,
            "facts_id": ["seg-cfs", "seg-cms", "seg-cms", "seg-cms"],
            "station_id": ["07374000"] * 4,
            "product_id": ["discharge_daily_mean"] * 4,
            "time": [
                datetime(2023, 1, 1, 12, 0),
                datetime(2023, 1, 1, 0, 0),
                datetime(2023, 1, 1, 0, 0),
                datetime(2023, 1, 2, 0, 0),
            ],
            "time_zone": ["+00:00"] * 4,
            "measured": [True, True, False, False],
            "flag": ["second-dup-null", "kept-daily", "unm-jan1", "unm-jan2-drop"],
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
            "usgs_nwis.qc": ObservationAnnotationTable.from_rows(
                schema=ann_schema, rows=ann_rows, measurement_indices=(1, n_each, None, None)
            )
        }
    )

    counts = {"native_window": 0, "zone": 0, "admission": 0}
    orig_nw = conv_mod.native_window
    orig_zv = conv_mod.ZoneValue
    orig_adm_ss = ss_mod.admission
    orig_adm_conv = conv_mod.admission

    def spy_nw(s, e, fact):
        counts["native_window"] += 1
        return orig_nw(s, e, fact)

    def spy_zv(z):
        counts["zone"] += 1
        return orig_zv(z)

    def spy_adm_ss(fact):
        counts["admission"] += 1
        return orig_adm_ss(fact)

    def spy_adm_conv(fact):
        counts["admission"] += 1
        return orig_adm_conv(fact)

    monkeypatch.setattr(conv_mod, "native_window", spy_nw)
    monkeypatch.setattr(conv_mod, "ZoneValue", spy_zv)
    monkeypatch.setattr(ss_mod, "admission", spy_adm_ss)
    monkeypatch.setattr(conv_mod, "admission", spy_adm_conv)

    window = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1, 10, 0)),
        WindowEndpoint.from_datetime(datetime(2023, 1, 1, 14, 0)),
    )
    converted, filtered_ann = convert_with_annotations(rows, bundle, config(), window, series=(series,))

    # Kept: n_each instant rows (first 100.0, second None, rest 50.0) + 1 daily row (7.5 m3/s)
    assert converted.value.height == n_each + 1
    assert converted.value["value"][0] == pytest.approx(100.0 * 0.028316846592)
    assert converted.value["value"][1] is None
    assert converted.value["source_unit"][:n_each].to_list() == ["ft3/s"] * n_each
    assert converted.value["unit"].to_list() == ["m3/s"] * (n_each + 1)
    assert converted.value["value"][n_each] == pytest.approx(7.5)
    assert converted.value["source_unit"][n_each] == "m3/s"

    out_table = filtered_ann.observation_tables["usgs_nwis.qc"]
    assert out_table.rows["flag"].to_list() == ["second-dup-null", "kept-daily", "unm-jan1"]
    assert out_table.measurement_indices == (1, n_each, None)

    assert counts["native_window"] <= 2
    assert counts["zone"] <= 1
    assert counts["admission"] <= 4


def test_shared_preparation_scopes_allowed_facts_per_call():
    from rivretrieve._internal.conversion import (
        WindowFactPreparation,
        convert_with_annotations,
        filter_annotations_for_window,
    )
    from rivretrieve._internal.source_annotations import (
        AnnotationBundle,
        AnnotationField,
        AnnotationSchema,
        AnnotationScope,
        ObservationAnnotationTable,
    )

    series_a = SourceSeries(
        series_id="series-a",
        provider_id="usgs_nwis",
        station_id="07374000",
        product_id="discharge_daily_mean",
        identity=SourceIdentity(namespace="methodID", published_id="1", origin="response", evidence=("source",)),
        facts=(
            PhysicalFacts(
                facts_id="facts-a",
                quantity=known("discharge", "source"),
                source_unit=known("m3/s", "source"),
                normalized_unit="m3/s",
            ),
        ),
    )
    series_b = SourceSeries(
        series_id="series-b",
        provider_id="usgs_nwis",
        station_id="07374000",
        product_id="discharge_daily_mean",
        identity=SourceIdentity(namespace="methodID", published_id="2", origin="response", evidence=("source",)),
        facts=(
            PhysicalFacts(
                facts_id="facts-b",
                quantity=known("discharge", "source"),
                source_unit=known("m3/s", "source"),
                normalized_unit="m3/s",
            ),
        ),
    )
    window = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2023, 1, 1)),
        WindowEndpoint.from_datetime(datetime(2023, 1, 2)),
    )
    prep = WindowFactPreparation.for_request(window, ())
    # Prime prep with series_a via an initial call
    rows_a = pl.DataFrame(
        {
            "station_id": ["07374000"],
            "product_id": ["discharge_daily_mean"],
            "time": [datetime(2023, 1, 1)],
            "value": [1.0],
            "time_zone": ["+00:00"],
            "series_id": ["series-a"],
            "facts_id": ["facts-a"],
            "source_unit": ["m3/s"],
        },
        schema=RowsSchema.polars_schema,
    )
    convert_with_annotations(rows_a, AnnotationBundle.empty(), config(), window, series=(series_a,), preparation=prep)
    assert "facts-a" in prep.intervals

    ann_schema = AnnotationSchema(
        schema_id="usgs_nwis.qc",
        provider_id="usgs_nwis",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="flag", dtype="String", description="Quality flag."),),
    )
    rows_b = pl.DataFrame(
        {
            "station_id": ["07374000"],
            "product_id": ["discharge_daily_mean"],
            "time": [datetime(2023, 1, 1)],
            "value": [2.0],
            "time_zone": ["+00:00"],
            "series_id": ["series-b"],
            "facts_id": ["facts-b"],
            "source_unit": ["m3/s"],
        },
        schema=RowsSchema.polars_schema,
    )
    ann_df = pl.DataFrame(
        {
            "series_id": ["series-a", "series-b"],
            "facts_id": ["facts-a", "facts-b"],
            "station_id": ["07374000", "07374000"],
            "product_id": ["discharge_daily_mean", "discharge_daily_mean"],
            "time": [datetime(2023, 1, 1), datetime(2023, 1, 1)],
            "time_zone": ["+00:00", "+00:00"],
            "measured": [False, False],
            "flag": ["from-a", "from-b"],
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
            "usgs_nwis.qc": ObservationAnnotationTable.from_rows(
                schema=ann_schema, rows=ann_df, measurement_indices=(None, None)
            )
        }
    )
    _, conv_ann = convert_with_annotations(rows_b, bundle, config(), window, series=(series_b,), preparation=prep)
    assert conv_ann.observation_tables["usgs_nwis.qc"].rows["flag"].to_list() == ["from-b"]

    meas_plus_a = pl.concat([rows_a, rows_b])
    ann_meas = pl.DataFrame(
        {
            "series_id": ["series-a", "series-b", "series-a", "series-b"],
            "facts_id": ["facts-a", "facts-b", "facts-a", "facts-b"],
            "station_id": ["07374000"] * 4,
            "product_id": ["discharge_daily_mean"] * 4,
            "time": [datetime(2023, 1, 1)] * 4,
            "time_zone": ["+00:00"] * 4,
            "measured": [True, True, False, False],
            "flag": ["m-a", "m-b", "u-a", "u-b"],
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
    filtered = filter_annotations_for_window(
        meas_plus_a,
        AnnotationBundle(
            observation_tables={
                "usgs_nwis.qc": ObservationAnnotationTable.from_rows(
                    schema=ann_schema, rows=ann_meas, measurement_indices=(0, 1, None, None)
                )
            }
        ),
        window,
        series=(series_b,),
        preparation=prep,
    )
    assert filtered.observation_tables["usgs_nwis.qc"].rows["flag"].to_list() == ["m-b", "u-b"]
    assert not hasattr(prep, "series")

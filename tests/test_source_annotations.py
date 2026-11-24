"""Core domain contracts and public API behavior for source annotations."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import polars.testing as pl_testing
import pytest

import rivretrieve as rr
from rivretrieve._internal.discovery import _merge_provider_results
from rivretrieve._internal.engine import SourceCallOrigin, UnknownOriginFact
from rivretrieve._internal.issues import FatalContractError
from rivretrieve._internal.observations import (
    ObservationDataSchema,
    ObservationProvenance,
    ObservationResult,
    ReceiptAuthorship,
    ReceiptEntry,
    Receipts,
)
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_annotations import (
    AnnotationBundle,
    AnnotationField,
    AnnotationSchema,
    AnnotationScope,
    ObservationAnnotationTable,
    SeriesAnnotationTable,
    with_annotations,
)
from rivretrieve._internal.source_series import (
    PhysicalFacts,
    SeriesScope,
    SourceIdentity,
    SourceSeries,
    known,
)


def _series_def(
    provider_id: str,
    station_id: str,
    product_id: str,
    *,
    published_id: str | None = None,
) -> SourceSeries:
    pid = published_id or f"{station_id}-{product_id}"
    quantity, unit = ("discharge", "m3/s") if "discharge" in product_id else ("stage", "m")
    frequency = "P1D" if "daily" in product_id else "PT15M"
    return SourceSeries(
        series_id=f"{provider_id}/{station_id}/{product_id}",
        provider_id=provider_id,
        station_id=station_id,
        product_id=product_id,
        identity=SourceIdentity(
            namespace=f"{provider_id}.series",
            published_id=pid,
            origin="mapping",
            evidence=("test-fixture",),
        ),
        facts=(
            PhysicalFacts(
                facts_id=f"{provider_id}/facts/{product_id}",
                quantity=known(quantity, "test-fixture"),
                source_unit=known(unit, "test-fixture"),
                normalized_unit=unit,
                frequency=known(frequency, "test-fixture"),
            ),
        ),
    )


def _obs_frame(
    rows: list[dict[str, object]],
    series_defs: tuple[SourceSeries, ...],
) -> pl.DataFrame:
    by_pair = {(s.station_id, s.product_id): s for s in series_defs}
    enriched = []
    for row in rows:
        defn = by_pair[(str(row["station_id"]), str(row["product_id"]))]
        fact = defn.facts[0]
        enriched.append(
            {
                "series_id": defn.series_id,
                "facts_id": fact.facts_id,
                "station_id": row["station_id"],
                "product_id": row["product_id"],
                "time": row["time"],
                "time_zone": row["time_zone"],
                "value": row["value"],
                "quantity": fact.quantity.value,
                "source_unit": fact.source_unit.value,
                "unit": fact.normalized_unit,
            }
        )
    return pl.DataFrame(enriched, schema=ObservationDataSchema.polars_schema)


def _empty_result(provider_id: str = "provider_a") -> ObservationResult:
    pid = ProviderId(provider_id)
    origin = SourceCallOrigin(
        url="https://example.invalid/observations",
        request_parameters={"station": "s1"},
        status_code=200,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )
    receipts = Receipts(
        provider_id=pid,
        entries=(ReceiptEntry(content=b"{}", origin=origin, authorship=ReceiptAuthorship.PUBLISHER_PAYLOAD),),
    )
    return ObservationResult(
        data=pl.DataFrame(schema=ObservationDataSchema.polars_schema),
        provenance=ObservationProvenance(
            source="live",
            provider_id=pid,
            request={"start": "2026-01-01T00:00:00", "end": "2026-01-02T23:59:59"},
        ),
        receipts=receipts,
        source_series=(),
        scope=SeriesScope(provider_ids=(provider_id,)),
    )


def _make_result(
    rows: list[dict[str, object]],
    series_defs: tuple[SourceSeries, ...],
    *,
    provider_id: str = "provider_a",
    bundle: AnnotationBundle | None = None,
) -> ObservationResult:
    base = _empty_result(provider_id=provider_id).model_copy(
        update={
            "data": _obs_frame(rows, series_defs),
            "source_series": series_defs,
        }
    )
    if bundle is not None:
        return with_annotations(base, bundle)
    return base


def test_annotation_field_and_schema_validation_enforces_plain_types_and_clean_metadata() -> None:
    valid = AnnotationField(
        name="qualifier",
        dtype=pl.List(pl.String),
        description="Observation qualifier codes reported by the source.",
        reference_url="https://example.org/docs/qualifiers",
    )
    assert valid.dtype == "List(String)"
    assert valid.polars_dtype == pl.List(pl.String)

    utf8_alias = AnnotationField(
        name="approval_status",
        dtype="Utf8",
        description="Review status of the observation.",
    )
    assert utf8_alias.dtype == "String"

    dt_field = AnnotationField(
        name="published_at",
        dtype=pl.Datetime("us"),
        description="Native publication timestamp reported by source.",
    )
    assert dt_field.dtype == "Datetime"

    for bad_dtype in (
        pl.Struct({"a": pl.Int64}),
        pl.List(pl.Struct({"a": pl.Int64})),
        pl.Object,
        pl.Categorical,
        pl.Null,
        "Struct({a: Int64})",
        "CustomWrapperClass",
    ):
        with pytest.raises(ValueError):
            AnnotationField(name="flag", dtype=bad_dtype, description="Valid description.")

    for bad_desc in ("", "   ", "unknown", "Unknown", "N/A", "tbd"):
        with pytest.raises(ValueError):
            AnnotationField(name="flag", dtype="String", description=bad_desc)

    for bad_url in ("", "   ", "not-a-url", "ftp://example.org/doc", "https://example.org/with space"):
        with pytest.raises(ValueError):
            AnnotationField(
                name="flag",
                dtype="String",
                description="Valid description.",
                reference_url=bad_url,
            )

    for reserved in ("series_id", "value", "measured", "_link_time"):
        with pytest.raises(ValueError):
            AnnotationSchema(
                schema_id="provider_a.obs",
                provider_id="provider_a",
                scope=AnnotationScope.OBSERVATION,
                fields=(AnnotationField(name=reserved, dtype="String", description="Reserved collision."),),
            )

    with pytest.raises(ValueError):
        AnnotationSchema(
            schema_id="provider_a/bad",
            provider_id="provider_a",
            scope=AnnotationScope.OBSERVATION,
            fields=(valid,),
        )

    with pytest.raises(ValueError):
        AnnotationSchema(
            schema_id="provider_a.series",
            provider_id="provider_a",
            scope=AnnotationScope.SERIES,
            fields=(AnnotationField(name="variant", dtype="String", description="Must not duplicate identity."),),
        )

    with pytest.raises(ValueError):
        AnnotationSchema(
            schema_id="provider_a.dup",
            provider_id="provider_a",
            scope=AnnotationScope.OBSERVATION,
            fields=(valid, valid),
        )


def test_observation_and_series_annotations_catalog_direct_tables_and_projections() -> None:
    daily = _series_def("usgs_nwis", "01646500", "discharge_daily_mean")
    cont = _series_def("usgs_nwis", "01646500", "discharge_instantaneous")

    daily_schema = AnnotationSchema(
        schema_id="usgs_nwis.daily",
        provider_id="usgs_nwis",
        scope=AnnotationScope.OBSERVATION,
        fields=(
            AnnotationField(
                name="approval_status",
                dtype="String",
                description="Approval status.",
                reference_url="https://example.org/approval",
            ),
            AnnotationField(
                name="qualifier",
                dtype="List(String)",
                description="Qualifier codes.",
                reference_url="https://example.org/qualifier",
            ),
        ),
    )
    cont_schema = AnnotationSchema(
        schema_id="usgs_nwis.continuous",
        provider_id="usgs_nwis",
        scope=AnnotationScope.OBSERVATION,
        fields=(
            AnnotationField(
                name="approval_status",
                dtype="String",
                description="Approval status.",
                reference_url="https://example.org/approval",
            ),
            AnnotationField(
                name="method_category",
                dtype="String",
                description="Measurement method category.",
                reference_url="https://example.org/method",
            ),
        ),
    )
    series_schema = AnnotationSchema(
        schema_id="usgs_nwis.series_notes",
        provider_id="usgs_nwis",
        scope=AnnotationScope.SERIES,
        fields=(
            AnnotationField(
                name="datum_note",
                dtype="String",
                description="Source datum note.",
                reference_url="https://example.org/datum",
            ),
        ),
    )

    obs_rows = [
        {
            "station_id": "01646500",
            "product_id": "discharge_daily_mean",
            "time": datetime(2026, 1, 1, 0, 0),
            "time_zone": "America/New_York",
            "value": 10.0,
        },
        {
            "station_id": "01646500",
            "product_id": "discharge_instantaneous",
            "time": datetime(2026, 1, 1, 12, 0),
            "time_zone": "-05:00",
            "value": 12.5,
        },
    ]

    daily_table = ObservationAnnotationTable.from_rows(
        schema=daily_schema,
        rows=pl.DataFrame(
            {
                "series_id": [daily.series_id, daily.series_id],
                "facts_id": [daily.facts[0].facts_id, daily.facts[0].facts_id],
                "station_id": ["01646500", "01646500"],
                "product_id": ["discharge_daily_mean", "discharge_daily_mean"],
                "time": [datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 2, 0, 0)],
                "time_zone": ["America/New_York", "America/New_York"],
                "measured": [True, False],
                "approval_status": ["Approved", "Provisional"],
                "qualifier": [["A"], ["Ice"]],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **daily_schema.polars_schema(),
            },
        ),
        measurement_indices=(0, None),
    )
    cont_table = ObservationAnnotationTable.from_rows(
        schema=cont_schema,
        rows=pl.DataFrame(
            {
                "series_id": [cont.series_id],
                "facts_id": [cont.facts[0].facts_id],
                "station_id": ["01646500"],
                "product_id": ["discharge_instantaneous"],
                "time": [datetime(2026, 1, 1, 12, 0)],
                "time_zone": ["-05:00"],
                "measured": [True],
                "approval_status": ["Provisional"],
                "method_category": ["gage"],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **cont_schema.polars_schema(),
            },
        ),
        measurement_indices=(1,),
    )
    series_table = SeriesAnnotationTable.from_rows(
        schema=series_schema,
        rows=pl.DataFrame(
            {
                "series_id": [daily.series_id],
                "datum_note": ["NGVD29 note"],
            },
            schema={"series_id": pl.String, **series_schema.polars_schema()},
        ),
    )

    bundle = AnnotationBundle(
        observation_tables={"usgs_nwis.daily": daily_table, "usgs_nwis.continuous": cont_table},
        series_tables={"usgs_nwis.series_notes": series_table},
    )
    result = _make_result(obs_rows, (daily, cont), provider_id="usgs_nwis", bundle=bundle)

    # ObservationResult model schema stays unchanged
    assert "_annotations" not in ObservationResult.model_fields

    # Default projection stays canonical 10 columns
    pl_testing.assert_frame_equal(result.to_polars(), result.data)
    assert result.to_polars().columns == ObservationDataSchema.polars_schema.names()
    assert result.to_pandas().columns.tolist() == ObservationDataSchema.polars_schema.names()

    # Catalog frame shows both observation and series schemas
    catalog = rr.annotations(result)
    assert catalog.columns == [
        "scope",
        "schema",
        "name",
        "dtype",
        "row_count",
        "unmeasured_count",
        "description",
        "reference_url",
    ]
    assert catalog.filter(pl.col("schema") == "usgs_nwis.daily").select("row_count", "unmeasured_count").rows() == [
        (2, 1),
        (2, 1),
    ]
    assert catalog.filter(pl.col("schema") == "usgs_nwis.continuous").select(
        "row_count", "unmeasured_count"
    ).rows() == [
        (1, 0),
        (1, 0),
    ]
    assert catalog.filter(pl.col("schema") == "usgs_nwis.series_notes").select("scope", "row_count").rows() == [
        ("series", 1)
    ]

    # Direct schema table has no cross-route null padding and retains measured=False slot
    direct_daily = rr.annotations(result, schema="usgs_nwis.daily")
    assert direct_daily.columns == [
        "series_id",
        "facts_id",
        "station_id",
        "product_id",
        "time",
        "time_zone",
        "measured",
        "approval_status",
        "qualifier",
    ]
    assert "method_category" not in direct_daily.columns
    assert direct_daily["measured"].to_list() == [True, False]
    assert direct_daily["qualifier"].to_list() == [["A"], ["Ice"]]

    direct_series = rr.annotations(result, schema="usgs_nwis.series_notes")
    assert direct_series.columns == ["series_id", "datum_note"]
    assert direct_series["datum_note"].to_list() == ["NGVD29 note"]

    with pytest.raises(ValueError, match="Unknown annotation schema"):
        rr.annotations(result, schema="usgs_nwis.missing")

    # Project all observation annotations via compatible merge
    annotated_all = result.to_polars(annotations=True)
    assert annotated_all.columns == [
        *ObservationDataSchema.polars_schema.names(),
        "approval_status",
        "qualifier",
        "method_category",
    ]
    assert annotated_all["approval_status"].to_list() == ["Approved", "Provisional"]
    assert annotated_all["qualifier"].to_list() == [["A"], None]
    assert annotated_all["method_category"].to_list() == [None, "gage"]
    assert annotated_all.height == 2
    assert "datum_note" not in annotated_all.columns

    # Project subset (str or Sequence[str]) via to_polars and to_pandas; as_frame rejects results
    subset = result.to_polars(annotations="approval_status")
    assert subset.columns == [*ObservationDataSchema.polars_schema.names(), "approval_status"]
    pl_testing.assert_frame_equal(result.to_polars(annotations=["approval_status"]), subset)
    with pytest.raises(TypeError):
        rr.as_frame(result)  # type: ignore[arg-type]
    pandas_df = result.to_pandas(annotations="approval_status")
    assert pandas_df.columns.tolist() == subset.columns
    assert pandas_df["approval_status"].tolist() == ["Approved", "Provisional"]

    # Unknown or wrong-scope field names raise ValueError
    with pytest.raises(ValueError):
        result.to_polars(annotations="missing")
    with pytest.raises(ValueError):
        result.to_polars(annotations="datum_note")

    # Series grain annotations
    series_plain = rr.series(result)
    assert "datum_note" not in series_plain.columns
    series_with_all = rr.series(result, annotations=True)
    assert "datum_note" in series_with_all.columns
    assert "approval_status" not in series_with_all.columns
    notes_by_series = dict(series_with_all.select("series_id", "datum_note").iter_rows())
    assert notes_by_series == {daily.series_id: "NGVD29 note", cont.series_id: None}
    assert (
        rr.series(result, annotations=["datum_note"])["datum_note"].to_list() == series_with_all["datum_note"].to_list()
    )

    with pytest.raises(ValueError):
        rr.series(result, annotations="approval_status")

    # Empty result returns empty 8-column catalog
    empty = _empty_result()
    empty_cat = rr.annotations(empty)
    assert empty_cat.is_empty()
    assert empty_cat.columns == catalog.columns


def test_incompatible_field_dtype_collision_is_refused_on_projection_and_series() -> None:
    s1 = _series_def("provider_a", "s1", "discharge_daily_mean")
    s2 = _series_def("provider_a", "s2", "stage_daily_mean")

    schema1 = AnnotationSchema(
        schema_id="provider_a.one",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(
            AnnotationField(name="shared", dtype="String", description="Compatible string field."),
            AnnotationField(name="code", dtype="String", description="String code."),
        ),
    )
    schema2 = AnnotationSchema(
        schema_id="provider_a.two",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(
            AnnotationField(name="shared", dtype="String", description="Compatible string field."),
            AnnotationField(name="code", dtype="Int64", description="Integer code."),
        ),
    )
    series_s1 = AnnotationSchema(
        schema_id="provider_a.s_one",
        provider_id="provider_a",
        scope=AnnotationScope.SERIES,
        fields=(AnnotationField(name="attr", dtype="String", description="String series attr."),),
    )
    series_s2 = AnnotationSchema(
        schema_id="provider_a.s_two",
        provider_id="provider_a",
        scope=AnnotationScope.SERIES,
        fields=(AnnotationField(name="attr", dtype="Int64", description="Int series attr."),),
    )

    t1 = ObservationAnnotationTable.from_rows(
        schema=schema1,
        rows=pl.DataFrame(
            {
                "series_id": [s1.series_id],
                "facts_id": [s1.facts[0].facts_id],
                "station_id": ["s1"],
                "product_id": ["discharge_daily_mean"],
                "time": [datetime(2026, 1, 1)],
                "time_zone": ["+00:00"],
                "measured": [True],
                "shared": ["ok"],
                "code": ["A"],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **schema1.polars_schema(),
            },
        ),
        measurement_indices=(0,),
    )
    t2 = ObservationAnnotationTable.from_rows(
        schema=schema2,
        rows=pl.DataFrame(
            {
                "series_id": [s2.series_id],
                "facts_id": [s2.facts[0].facts_id],
                "station_id": ["s2"],
                "product_id": ["stage_daily_mean"],
                "time": [datetime(2026, 1, 1)],
                "time_zone": ["+00:00"],
                "measured": [True],
                "shared": ["also_ok"],
                "code": [7],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **schema2.polars_schema(),
            },
        ),
        measurement_indices=(1,),
    )
    st1 = SeriesAnnotationTable.from_rows(
        schema=series_s1,
        rows=pl.DataFrame(
            {"series_id": [s1.series_id], "attr": ["x"]}, schema={"series_id": pl.String, **series_s1.polars_schema()}
        ),
    )
    st2 = SeriesAnnotationTable.from_rows(
        schema=series_s2,
        rows=pl.DataFrame(
            {"series_id": [s2.series_id], "attr": [9]}, schema={"series_id": pl.String, **series_s2.polars_schema()}
        ),
    )

    result = _make_result(
        [
            {
                "station_id": "s1",
                "product_id": "discharge_daily_mean",
                "time": datetime(2026, 1, 1),
                "time_zone": "+00:00",
                "value": 1.0,
            },
            {
                "station_id": "s2",
                "product_id": "stage_daily_mean",
                "time": datetime(2026, 1, 1),
                "time_zone": "+00:00",
                "value": 2.0,
            },
        ],
        (s1, s2),
        bundle=AnnotationBundle(
            observation_tables={"provider_a.one": t1, "provider_a.two": t2},
            series_tables={"provider_a.s_one": st1, "provider_a.s_two": st2},
        ),
    )

    # Catalog keeps distinct schemas inspectable
    assert rr.annotations(result).height == 6

    # Compatible subset works while colliding projection refuses
    assert result.to_polars(annotations="shared")["shared"].to_list() == ["ok", "also_ok"]
    with pytest.raises(ValueError, match="Incompatible annotation field 'code'"):
        result.to_polars(annotations=True)
    with pytest.raises(ValueError, match="Incompatible annotation field 'code'"):
        result.to_polars(annotations="code")
    with pytest.raises(ValueError, match="Incompatible annotation field 'attr'"):
        rr.series(result, annotations=True)

    # Same dtype but different description or reference_url also raises ValueError
    meaning_s1 = AnnotationSchema(
        schema_id="provider_a.m_one",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(
            AnnotationField(
                name="flag",
                dtype="String",
                description="Primary publisher quality flag.",
                reference_url="https://example.org/flag-a",
            ),
        ),
    )
    meaning_s2 = AnnotationSchema(
        schema_id="provider_a.m_two",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(
            AnnotationField(
                name="flag",
                dtype="String",
                description="Sensor telemetry diagnostic code.",
                reference_url="https://example.org/flag-b",
            ),
        ),
    )
    mt1 = ObservationAnnotationTable.from_rows(
        schema=meaning_s1,
        rows=pl.DataFrame(
            {
                "series_id": [s1.series_id],
                "facts_id": [s1.facts[0].facts_id],
                "station_id": ["s1"],
                "product_id": ["discharge_daily_mean"],
                "time": [datetime(2026, 1, 1)],
                "time_zone": ["+00:00"],
                "measured": [True],
                "flag": ["A"],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **meaning_s1.polars_schema(),
            },
        ),
        measurement_indices=(0,),
    )
    mt2 = ObservationAnnotationTable.from_rows(
        schema=meaning_s2,
        rows=pl.DataFrame(
            {
                "series_id": [s2.series_id],
                "facts_id": [s2.facts[0].facts_id],
                "station_id": ["s2"],
                "product_id": ["stage_daily_mean"],
                "time": [datetime(2026, 1, 1)],
                "time_zone": ["+00:00"],
                "measured": [True],
                "flag": ["OK"],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **meaning_s2.polars_schema(),
            },
        ),
        measurement_indices=(1,),
    )
    meaning_result = _make_result(
        [
            {
                "station_id": "s1",
                "product_id": "discharge_daily_mean",
                "time": datetime(2026, 1, 1),
                "time_zone": "+00:00",
                "value": 1.0,
            },
            {
                "station_id": "s2",
                "product_id": "stage_daily_mean",
                "time": datetime(2026, 1, 1),
                "time_zone": "+00:00",
                "value": 2.0,
            },
        ],
        (s1, s2),
        bundle=AnnotationBundle(observation_tables={"provider_a.m_one": mt1, "provider_a.m_two": mt2}),
    )
    with pytest.raises(ValueError, match="Incompatible annotation field 'flag'"):
        meaning_result.to_polars(annotations=True)
    with pytest.raises(ValueError, match="Incompatible annotation field 'flag'"):
        meaning_result.to_polars(annotations="flag")


def test_pick_to_utc_and_merge_preserve_exact_row_association() -> None:
    s_dst = _series_def("provider_a", "s_dst", "discharge_instantaneous")
    s_other = _series_def("provider_a", "s_other", "stage_daily_mean")

    schema_a = AnnotationSchema(
        schema_id="provider_a.obs",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="tag", dtype="String", description="Row provenance tag."),),
    )
    series_a = AnnotationSchema(
        schema_id="provider_a.meta",
        provider_id="provider_a",
        scope=AnnotationScope.SERIES,
        fields=(AnnotationField(name="gauge_note", dtype="String", description="Gauge note."),),
    )
    schema_b = AnnotationSchema(
        schema_id="provider_a.daily",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="tag", dtype="String", description="Row provenance tag."),),
    )

    # Include two different native offsets collapsing to same UTC instant AND an IANA DST fold duplicate
    rows_a = [
        {
            "station_id": "s_dst",
            "product_id": "discharge_instantaneous",
            "time": datetime(2026, 1, 1, 5, 0),
            "time_zone": "+00:00",
            "value": 1.0,
        },
        {
            "station_id": "s_dst",
            "product_id": "discharge_instantaneous",
            "time": datetime(2026, 1, 1, 6, 0),
            "time_zone": "+01:00",
            "value": 2.0,
        },
        {
            "station_id": "s_dst",
            "product_id": "discharge_instantaneous",
            "time": datetime(2023, 11, 5, 1, 30),
            "time_zone": "America/New_York",
            "value": 3.0,
        },
        {
            "station_id": "s_dst",
            "product_id": "discharge_instantaneous",
            "time": datetime(2023, 11, 5, 1, 30),
            "time_zone": "America/New_York",
            "value": 4.0,
        },
    ]
    table_a = ObservationAnnotationTable.from_rows(
        schema=schema_a,
        rows=pl.DataFrame(
            {
                "series_id": [s_dst.series_id] * 5,
                "facts_id": [s_dst.facts[0].facts_id] * 5,
                "station_id": ["s_dst"] * 5,
                "product_id": ["discharge_instantaneous"] * 5,
                "time": [
                    datetime(2026, 1, 1, 5, 0),
                    datetime(2026, 1, 1, 6, 0),
                    datetime(2023, 11, 5, 1, 30),
                    datetime(2023, 11, 5, 1, 30),
                    datetime(2026, 1, 2, 0, 0),
                ],
                "time_zone": ["+00:00", "+01:00", "America/New_York", "America/New_York", "+00:00"],
                "measured": [True, True, True, True, False],
                "tag": ["utc-match-0", "utc-match-1", "dst-first", "dst-second", "unmeasured-slot"],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **schema_a.polars_schema(),
            },
        ),
        measurement_indices=(0, 1, 2, 3, None),
    )
    series_table_a = SeriesAnnotationTable.from_rows(
        schema=series_a,
        rows=pl.DataFrame(
            {"series_id": [s_dst.series_id], "gauge_note": ["kept-note"]},
            schema={"series_id": pl.String, **series_a.polars_schema()},
        ),
    )
    res_a = _make_result(
        rows_a,
        (s_dst,),
        provider_id="provider_a",
        bundle=AnnotationBundle(
            observation_tables={"provider_a.obs": table_a},
            series_tables={"provider_a.meta": series_table_a},
        ),
    )

    # to_utc converts measured & unmeasured rows and retains 1:1 row tags despite identical UTC timestamps
    utc_a = rr.to_utc(res_a)
    assert utc_a.to_polars(annotations="tag").select("value", "time_zone", "tag").rows() == [
        (1.0, "+00:00", "utc-match-0"),
        (2.0, "+00:00", "utc-match-1"),
        (3.0, "+00:00", "dst-first"),
        (4.0, "+00:00", "dst-second"),
    ]
    utc_direct = rr.annotations(utc_a, schema="provider_a.obs")
    assert utc_direct["time_zone"].to_list() == ["+00:00"] * 5
    assert utc_direct.filter(~pl.col("measured"))["tag"].to_list() == ["unmeasured-slot"]

    # to_utc fails loudly if an unmeasured annotation slot has unknown time_zone
    bad_unmeasured = ObservationAnnotationTable.from_rows(
        schema=schema_a,
        rows=pl.DataFrame(
            {
                "series_id": [s_dst.series_id],
                "facts_id": [s_dst.facts[0].facts_id],
                "station_id": ["s_dst"],
                "product_id": ["discharge_instantaneous"],
                "time": [datetime(2026, 1, 2, 0, 0)],
                "time_zone": ["unknown"],
                "measured": [False],
                "tag": ["unknown-slot"],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **schema_a.polars_schema(),
            },
        ),
        measurement_indices=(None,),
    )
    res_bad_utc = _make_result(
        [],
        (s_dst,),
        provider_id="provider_a",
        bundle=AnnotationBundle(observation_tables={"provider_a.obs": bad_unmeasured}),
    )
    with pytest.raises(FatalContractError):
        rr.to_utc(res_bad_utc)

    # _merge_provider_results sorts canonically while keeping tags aligned 1:1
    table_b = ObservationAnnotationTable.from_rows(
        schema=schema_b,
        rows=pl.DataFrame(
            {
                "series_id": [s_other.series_id],
                "facts_id": [s_other.facts[0].facts_id],
                "station_id": ["s_other"],
                "product_id": ["stage_daily_mean"],
                "time": [datetime(2026, 1, 1, 0, 0)],
                "time_zone": ["+00:00"],
                "measured": [True],
                "tag": ["from-b"],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **schema_b.polars_schema(),
            },
        ),
        measurement_indices=(0,),
    )
    res_b = _make_result(
        [
            {
                "station_id": "s_other",
                "product_id": "stage_daily_mean",
                "time": datetime(2026, 1, 1, 0, 0),
                "time_zone": "+00:00",
                "value": 9.0,
            }
        ],
        (s_other,),
        provider_id="provider_a",
        bundle=AnnotationBundle(observation_tables={"provider_a.daily": table_b}),
    )
    # Reverse input order so canonical sort permutes everything
    merged = _merge_provider_results((res_b, res_a), (s_other, s_dst))
    assert merged.to_polars(annotations="tag").select("station_id", "value", "tag").rows() == [
        ("s_dst", 3.0, "dst-first"),
        ("s_dst", 4.0, "dst-second"),
        ("s_dst", 1.0, "utc-match-0"),
        ("s_dst", 2.0, "utc-match-1"),
        ("s_other", 9.0, "from-b"),
    ]

    # pick narrows annotations and omits dropped route schemas
    picked_b = rr.pick(merged, station="s_other", on_issue="ignore")
    assert picked_b.to_polars(annotations="tag").select("station_id", "tag").rows() == [("s_other", "from-b")]
    assert rr.annotations(picked_b)["schema"].to_list() == ["provider_a.daily"]
    with pytest.raises(ValueError, match="Unknown annotation schema"):
        rr.annotations(picked_b, schema="provider_a.obs")

    picked_a = rr.pick(merged, station="s_dst", on_issue="ignore")
    assert set(rr.annotations(picked_a)["schema"].to_list()) == {"provider_a.obs", "provider_a.meta"}
    assert rr.series(picked_a, annotations="gauge_note")["gauge_note"].to_list() == ["kept-note"]


def test_selection_supports_series_annotations_in_series_as_frame_and_annotations() -> None:
    from rivretrieve._internal.selection import _Selection

    s1 = _series_def("provider_a", "s1", "discharge_daily_mean")
    s2 = _series_def("provider_a", "s2", "stage_daily_mean")
    series_schema = AnnotationSchema(
        schema_id="provider_a.sel_meta",
        provider_id="provider_a",
        scope=AnnotationScope.SERIES,
        fields=(AnnotationField(name="site_note", dtype="String", description="Station series note."),),
    )
    table = SeriesAnnotationTable.from_rows(
        schema=series_schema,
        rows=pl.DataFrame(
            {"series_id": [s1.series_id, s2.series_id], "site_note": ["note-1", "note-2"]},
            schema={"series_id": pl.String, **series_schema.polars_schema()},
        ),
    )
    selection = _Selection(
        scope=SeriesScope(provider_ids=("provider_a",)),
        known_series=(s1, s2),
        series_annotations=AnnotationBundle(series_tables={"provider_a.sel_meta": table}),
    )

    cat = rr.annotations(selection)
    assert cat.select("scope", "schema", "name", "row_count").rows() == [
        ("series", "provider_a.sel_meta", "site_note", 2),
    ]
    pl_testing.assert_frame_equal(
        rr.series(selection, annotations=True),
        rr.as_frame(selection, annotations=True),
    )
    assert dict(rr.as_frame(selection, annotations="site_note").select("series_id", "site_note").iter_rows()) == {
        s1.series_id: "note-1",
        s2.series_id: "note-2",
    }
    narrowed = rr.pick(selection, station="s1", on_issue="ignore")
    assert rr.annotations(narrowed)["row_count"].to_list() == [1]
    assert rr.series(narrowed, annotations="site_note")["site_note"].to_list() == ["note-1"]


def test_narrow_and_pick_preserve_order_null_measured_unmeasured_and_omit_native_links() -> None:
    import inspect
    from dataclasses import fields

    from rivretrieve._internal.source_series import PhysicalFacts

    assert "native_links" not in {item.name for item in fields(ObservationAnnotationTable)}
    assert "native_links" not in inspect.signature(ObservationAnnotationTable.from_rows).parameters

    s_keep = SourceSeries(
        series_id="provider_a/s1/discharge_instantaneous",
        provider_id="provider_a",
        station_id="s1",
        product_id="discharge_instantaneous",
        identity=SourceIdentity(
            namespace="provider_a.series",
            published_id="s1-q",
            origin="mapping",
            evidence=("test-fixture",),
        ),
        facts=(
            PhysicalFacts(
                facts_id="provider_a/facts/q-m3s",
                quantity=known("discharge", "test-fixture"),
                source_unit=known("m3/s", "test-fixture"),
                normalized_unit="m3/s",
                frequency=known("PT1H", "test-fixture"),
            ),
            PhysicalFacts(
                facts_id="provider_a/facts/q-ft3s",
                quantity=known("discharge", "test-fixture"),
                source_unit=known("ft^3/s", "test-fixture"),
                normalized_unit="ft3/s",
                frequency=known("P1D", "test-fixture"),
            ),
        ),
    )
    s_drop = _series_def("provider_a", "s1", "stage_daily_mean")

    obs_schema = AnnotationSchema(
        schema_id="provider_a.obs",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="tag", dtype="String", description="Observation tag."),),
    )
    drop_schema = AnnotationSchema(
        schema_id="provider_a.stage_obs",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="stage_tag", dtype="String", description="Stage tag."),),
    )

    f_15m = s_keep.facts[0]
    f_daily = s_keep.facts[1]
    f_stage = s_drop.facts[0]
    obs_df = pl.DataFrame(
        {
            "series_id": [s_keep.series_id, s_keep.series_id, s_drop.series_id, s_keep.series_id, s_keep.series_id],
            "facts_id": [f_15m.facts_id, f_15m.facts_id, f_stage.facts_id, f_15m.facts_id, f_daily.facts_id],
            "station_id": ["s1"] * 5,
            "product_id": [
                "discharge_instantaneous",
                "discharge_instantaneous",
                "stage_daily_mean",
                "discharge_instantaneous",
                "discharge_instantaneous",
            ],
            "time": [
                datetime(2026, 1, 1, 0, 0),
                datetime(2026, 1, 1, 0, 0),
                datetime(2026, 1, 1, 0, 0),
                datetime(2026, 1, 1, 0, 15),
                datetime(2026, 1, 2, 0, 0),
            ],
            "time_zone": ["+00:00"] * 5,
            "value": [2.0, 1.0, 5.0, None, 3.0],
            "quantity": ["discharge", "discharge", "stage", "discharge", "discharge"],
            "source_unit": ["m3/s", "m3/s", "m", "m3/s", "ft^3/s"],
            "unit": ["m3/s", "m3/s", "m", "m3/s", "m3/s"],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    # Intentionally place annotations in reverse/mixed order across measured & unmeasured rows
    ann_df = pl.DataFrame(
        {
            "series_id": [
                s_keep.series_id,  # unmeasured dropped daily fact
                s_keep.series_id,  # measured idx=3 (null value!)
                s_keep.series_id,  # unmeasured kept 15min fact
                s_keep.series_id,  # measured idx=0 (dup 1)
                s_keep.series_id,  # measured idx=1 (dup 2)
                s_keep.series_id,  # measured idx=4 (dropped daily fact)
            ],
            "facts_id": [
                f_daily.facts_id,
                f_15m.facts_id,
                f_15m.facts_id,
                f_15m.facts_id,
                f_15m.facts_id,
                f_daily.facts_id,
            ],
            "station_id": ["s1"] * 6,
            "product_id": ["discharge_instantaneous"] * 6,
            "time": [
                datetime(2026, 1, 3, 0, 0),
                datetime(2026, 1, 1, 0, 15),
                datetime(2026, 1, 1, 0, 30),
                datetime(2026, 1, 1, 0, 0),
                datetime(2026, 1, 1, 0, 0),
                datetime(2026, 1, 2, 0, 0),
            ],
            "time_zone": ["+00:00"] * 6,
            "measured": [False, True, False, True, True, False],
            "tag": ["drop-unm-daily", "kept-null", "kept-unm-15m", "dup-1", "dup-2", "drop-meas-daily"],
        },
        schema={
            "series_id": pl.String,
            "facts_id": pl.String,
            "station_id": pl.String,
            "product_id": pl.String,
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "measured": pl.Boolean,
            **obs_schema.polars_schema(),
        },
    )
    # Fix measured flag for idx=4
    ann_df = ann_df.with_columns(pl.Series("measured", [False, True, False, True, True, True], dtype=pl.Boolean))
    obs_table = ObservationAnnotationTable.from_rows(
        schema=obs_schema,
        rows=ann_df,
        measurement_indices=(None, 3, None, 0, 1, 4),
    )
    drop_table = ObservationAnnotationTable.from_rows(
        schema=drop_schema,
        rows=pl.DataFrame(
            {
                "series_id": [s_drop.series_id, s_drop.series_id],
                "facts_id": [f_stage.facts_id, f_stage.facts_id],
                "station_id": ["s1", "s1"],
                "product_id": ["stage_daily_mean", "stage_daily_mean"],
                "time": [datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 2, 0, 0)],
                "time_zone": ["+00:00", "+00:00"],
                "measured": [True, False],
                "stage_tag": ["drop-stage-m", "drop-stage-u"],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **drop_schema.polars_schema(),
            },
        ),
        measurement_indices=(2, None),
    )
    base = _empty_result(provider_id="provider_a").model_copy(
        update={"data": obs_df, "source_series": (s_keep, s_drop)}
    )
    result = with_annotations(
        base,
        AnnotationBundle(observation_tables={"provider_a.obs": obs_table, "provider_a.stage_obs": drop_table}),
    )

    picked = rr.pick(result, quantity="discharge", frequency="PT1H", on_issue="ignore")
    assert picked.to_polars(annotations="tag").select("time", "value", "tag").rows() == [
        (datetime(2026, 1, 1, 0, 0), 2.0, "dup-1"),
        (datetime(2026, 1, 1, 0, 0), 1.0, "dup-2"),
        (datetime(2026, 1, 1, 0, 15), None, "kept-null"),
    ]
    direct = rr.annotations(picked, schema="provider_a.obs")
    assert direct["tag"].to_list() == ["kept-null", "kept-unm-15m", "dup-1", "dup-2"]
    assert picked._annotations.observation_tables["provider_a.obs"].measurement_indices == (2, None, 0, 1)
    assert rr.annotations(picked)["schema"].to_list() == ["provider_a.obs"]
    with pytest.raises(ValueError, match="Unknown annotation schema"):
        rr.annotations(picked, schema="provider_a.stage_obs")


def test_pick_narrows_growing_annotated_result_preserving_exact_mapping() -> None:
    from datetime import timedelta

    s1 = _series_def("provider_a", "s1", "discharge_daily_mean")
    s2 = _series_def("provider_a", "s2", "stage_daily_mean")
    schema = AnnotationSchema(
        schema_id="provider_a.obs",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="tag", dtype="String", description="Observation tag."),),
    )
    n_pairs = 1_000
    base_time = datetime(2020, 1, 1)
    times = [base_time + timedelta(days=i // 2) for i in range(n_pairs * 2)]
    is_s1 = [i % 2 == 0 for i in range(n_pairs * 2)]
    obs_df = pl.DataFrame(
        {
            "series_id": [s1.series_id if k else s2.series_id for k in is_s1],
            "facts_id": [s1.facts[0].facts_id if k else s2.facts[0].facts_id for k in is_s1],
            "station_id": ["s1" if k else "s2" for k in is_s1],
            "product_id": ["discharge_daily_mean" if k else "stage_daily_mean" for k in is_s1],
            "time": times,
            "time_zone": ["+00:00"] * (n_pairs * 2),
            "value": [float(i) for i in range(n_pairs * 2)],
            "quantity": ["discharge" if k else "stage" for k in is_s1],
            "source_unit": ["m3/s" if k else "m" for k in is_s1],
            "unit": ["m3/s" if k else "m" for k in is_s1],
        },
        schema=ObservationDataSchema.polars_schema,
    )
    ann_df = pl.DataFrame(
        {
            "series_id": obs_df["series_id"],
            "facts_id": obs_df["facts_id"],
            "station_id": obs_df["station_id"],
            "product_id": obs_df["product_id"],
            "time": times,
            "time_zone": ["+00:00"] * (n_pairs * 2),
            "measured": [True] * (n_pairs * 2),
            "tag": [f"tag-{i}" for i in range(n_pairs * 2)],
        },
        schema={
            "series_id": pl.String,
            "facts_id": pl.String,
            "station_id": pl.String,
            "product_id": pl.String,
            "time": pl.Datetime("us"),
            "time_zone": pl.String,
            "measured": pl.Boolean,
            **schema.polars_schema(),
        },
    )
    table = ObservationAnnotationTable.from_rows(
        schema=schema, rows=ann_df, measurement_indices=tuple(range(n_pairs * 2))
    )
    result = with_annotations(
        _empty_result(provider_id="provider_a").model_copy(update={"data": obs_df, "source_series": (s1, s2)}),
        AnnotationBundle(observation_tables={"provider_a.obs": table}),
    )
    picked = rr.pick(result, quantity="discharge", on_issue="ignore")
    projected = picked.to_polars(annotations="tag")
    assert projected.height == n_pairs
    assert projected["value"].to_list() == [float(2 * i) for i in range(n_pairs)]
    assert projected["tag"].to_list() == [f"tag-{2 * i}" for i in range(n_pairs)]


def test_filter_native_with_annotations_builds_dicts_only_for_needed_unmeasured_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rivretrieve._internal.engine import RowsSchema
    from rivretrieve._internal.source_annotations import filter_native_with_annotations

    s1 = _series_def("provider_a", "s1", "discharge_daily_mean")
    s2 = _series_def("provider_a", "s2", "stage_daily_mean")
    schema = AnnotationSchema(
        schema_id="provider_a.obs",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="tag", dtype="String", description="Observation tag."),),
    )
    rows = pl.DataFrame(
        {
            "station_id": ["s1", "s1", "s1"],
            "product_id": ["discharge_daily_mean"] * 3,
            "time": [datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2026, 1, 3)],
            "value": [1.0, None, 3.0],
            "time_zone": ["+00:00"] * 3,
            "series_id": [s1.series_id] * 3,
            "facts_id": [s1.facts[0].facts_id] * 3,
            "source_unit": ["m3/s"] * 3,
        },
        schema=RowsSchema.polars_schema,
    )
    ann_schema = {
        "series_id": pl.String,
        "facts_id": pl.String,
        "station_id": pl.String,
        "product_id": pl.String,
        "time": pl.Datetime("us"),
        "time_zone": pl.String,
        "measured": pl.Boolean,
        **schema.polars_schema(),
    }

    to_dicts_counts: list[int] = []
    orig_to_dicts = pl.DataFrame.to_dicts

    def spy_to_dicts(self: pl.DataFrame, *args: object, **kwargs: object) -> list[dict[str, object]]:
        out = orig_to_dicts(self, *args, **kwargs)
        to_dicts_counts.append(len(out))
        return out

    monkeypatch.setattr(pl.DataFrame, "to_dicts", spy_to_dicts)

    # 1. Fully measured table including a null-valued measured row -> zero predicate dicts
    measured_only = ObservationAnnotationTable.from_rows(
        schema=schema,
        rows=pl.DataFrame(
            {
                "series_id": [s1.series_id] * 3,
                "facts_id": [s1.facts[0].facts_id] * 3,
                "station_id": ["s1"] * 3,
                "product_id": ["discharge_daily_mean"] * 3,
                "time": [datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2026, 1, 3)],
                "time_zone": ["+00:00"] * 3,
                "measured": [True, True, True],
                "tag": ["m0", "m-null", "m2"],
            },
            schema=ann_schema,
        ),
        measurement_indices=(0, 1, 2),
    )
    pred_calls: list[dict[str, object]] = []
    filtered_rows, filtered_bundle = filter_native_with_annotations(
        rows,
        AnnotationBundle(observation_tables={"provider_a.obs": measured_only}),
        kept_indices=[0, 1],
        unmeasured_predicate=lambda rec: (pred_calls.append(rec), True)[1],
    )
    assert to_dicts_counts == []
    assert pred_calls == []
    assert filtered_rows["value"].to_list() == [1.0, None]
    kept_table = filtered_bundle.observation_tables["provider_a.obs"]
    assert kept_table.rows["tag"].to_list() == ["m0", "m-null"]
    assert kept_table.measurement_indices == (0, 1)

    # 2. Mixed table: series/expr filter before to_dicts, so dicts created ONLY for surviving candidates
    mixed_table = ObservationAnnotationTable.from_rows(
        schema=schema,
        rows=pl.DataFrame(
            {
                "series_id": [
                    s1.series_id,
                    s2.series_id,
                    s1.series_id,
                    s1.series_id,
                    s1.series_id,
                    s1.series_id,
                    s1.series_id,
                ],
                "facts_id": [
                    s1.facts[0].facts_id,
                    s2.facts[0].facts_id,
                    s1.facts[0].facts_id,
                    s1.facts[0].facts_id,
                    s1.facts[0].facts_id,
                    s1.facts[0].facts_id,
                    s1.facts[0].facts_id,
                ],
                "station_id": ["s1", "s2", "s1", "s1", "s1", "s1", "s1"],
                "product_id": [
                    "discharge_daily_mean",
                    "stage_daily_mean",
                    "discharge_daily_mean",
                    "discharge_daily_mean",
                    "discharge_daily_mean",
                    "discharge_daily_mean",
                    "discharge_daily_mean",
                ],
                "time": [
                    datetime(2026, 1, 1),
                    datetime(2026, 1, 5),
                    datetime(2026, 1, 2),
                    datetime(2026, 1, 1),
                    datetime(2026, 1, 3),
                    datetime(2026, 1, 4),
                    datetime(2026, 1, 3),
                ],
                "time_zone": ["+00:00"] * 7,
                "measured": [True, False, True, False, False, False, True],
                "tag": ["m0", "u-drop-series", "m-null", "u-drop-expr", "u-keep-pred", "u-drop-pred", "m2"],
            },
            schema=ann_schema,
        ),
        measurement_indices=(0, None, 1, None, None, None, 2),
    )
    mixed_bundle = AnnotationBundle(observation_tables={"provider_a.obs": mixed_table})
    to_dicts_counts.clear()
    pred_calls.clear()
    _, mixed_out = filter_native_with_annotations(
        rows,
        mixed_bundle,
        kept_indices=[0, 1],
        unmeasured_expr=pl.col("time") >= datetime(2026, 1, 2),
        unmeasured_predicate=lambda rec: (pred_calls.append(rec), rec["tag"] == "u-keep-pred")[1],
        allowed_series_ids={s1.series_id},
    )
    assert sum(to_dicts_counts) == 2
    assert [rec["tag"] for rec in pred_calls] == ["u-keep-pred", "u-drop-pred"]
    out_table = mixed_out.observation_tables["provider_a.obs"]
    assert out_table.rows["tag"].to_list() == ["m0", "m-null", "u-keep-pred"]
    assert out_table.measurement_indices == (0, 1, None)

    # 3. Excluded unmeasured rows never reach unmeasured_predicate; kept candidate exceptions still raise
    def fail_on_excluded(rec: dict[str, object]) -> bool:
        if rec["tag"] in {"u-drop-series", "u-drop-expr"}:
            raise FatalContractError("excluded row should not reach predicate")
        return True

    filter_native_with_annotations(
        rows,
        mixed_bundle,
        kept_indices=[0, 1],
        unmeasured_expr=pl.col("time") >= datetime(2026, 1, 2),
        unmeasured_predicate=fail_on_excluded,
        allowed_series_ids={s1.series_id},
    )

    def fail_on_candidate(rec: dict[str, object]) -> bool:
        if rec["tag"] == "u-keep-pred":
            raise FatalContractError("candidate failure must surface")
        return True

    with pytest.raises(FatalContractError, match="candidate failure must surface"):
        filter_native_with_annotations(
            rows,
            mixed_bundle,
            kept_indices=[0, 1],
            unmeasured_expr=pl.col("time") >= datetime(2026, 1, 2),
            unmeasured_predicate=fail_on_candidate,
            allowed_series_ids={s1.series_id},
        )


def test_merge_single_station_multi_series_ordered_reuses_without_revalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rivretrieve._internal import discovery, observations, source_annotations
    from rivretrieve._internal.issues import Issue
    from rivretrieve._internal.source_series import OutcomeStatus, RetrievalOutcome, SeriesWindow

    s_q = _series_def("provider_a", "s1", "discharge_daily_mean")
    s_h = _series_def("provider_a", "s1", "stage_daily_mean")
    # Ensure s_q < s_h in canonical order ("discharge_daily_mean" < "stage_daily_mean")
    obs_schema = AnnotationSchema(
        schema_id="provider_a.obs",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="tag", dtype="String", description="Observation tag."),),
    )
    ser_schema = AnnotationSchema(
        schema_id="provider_a.meta",
        provider_id="provider_a",
        scope=AnnotationScope.SERIES,
        fields=(AnnotationField(name="gauge_note", dtype="String", description="Series note."),),
    )
    rows = [
        {
            "station_id": "s1",
            "product_id": "discharge_daily_mean",
            "time": datetime(2026, 1, 1),
            "time_zone": "+00:00",
            "value": None,
        },
        {
            "station_id": "s1",
            "product_id": "discharge_daily_mean",
            "time": datetime(2026, 1, 1),
            "time_zone": "+00:00",
            "value": 1.0,
        },
        {
            "station_id": "s1",
            "product_id": "stage_daily_mean",
            "time": datetime(2026, 1, 1),
            "time_zone": "+00:00",
            "value": 5.0,
        },
    ]
    obs_table = ObservationAnnotationTable.from_rows(
        schema=obs_schema,
        rows=pl.DataFrame(
            {
                "series_id": [s_q.series_id, s_q.series_id, s_q.series_id, s_h.series_id],
                "facts_id": [
                    s_q.facts[0].facts_id,
                    s_q.facts[0].facts_id,
                    s_q.facts[0].facts_id,
                    s_h.facts[0].facts_id,
                ],
                "station_id": ["s1"] * 4,
                "product_id": [
                    "discharge_daily_mean",
                    "discharge_daily_mean",
                    "discharge_daily_mean",
                    "stage_daily_mean",
                ],
                "time": [
                    datetime(2026, 1, 1),
                    datetime(2026, 1, 1),
                    datetime(2026, 1, 1),
                    datetime(2026, 1, 1),
                ],
                "time_zone": ["+00:00"] * 4,
                "measured": [True, True, False, True],
                "tag": ["q-null", "q-one", "q-unm", "h-five"],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **obs_schema.polars_schema(),
            },
        ),
        measurement_indices=(0, 1, None, 2),
    )
    ordered_series_ids = sorted([s_q.series_id, s_h.series_id])
    ser_table = SeriesAnnotationTable.from_rows(
        schema=ser_schema,
        rows=pl.DataFrame(
            {"series_id": ordered_series_ids, "gauge_note": ["note-0", "note-1"]},
            schema={"series_id": pl.String, **ser_schema.polars_schema()},
        ),
    )
    prov_issue = Issue(
        severity="info",
        code="provenance.note",
        message="Duplicate provenance note",
        provider_id=ProviderId("provider_a"),
    )
    src_issue = Issue(
        severity="warning",
        code="source.partial",
        message="Stage product unavailable",
        provider_id=ProviderId("provider_a"),
        details={"station_id": "s1", "product_id": "stage_daily_mean"},
    )
    out_q = RetrievalOutcome(
        outcome_id="out-q",
        series_id=s_q.series_id,
        station_id="s1",
        product_id="discharge_daily_mean",
        window=SeriesWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2)),
        status=OutcomeStatus.SUCCESS,
        facts_ids=(s_q.facts[0].facts_id,),
    )
    out_h = RetrievalOutcome(
        outcome_id="out-h",
        series_id=s_h.series_id,
        station_id="s1",
        product_id="stage_daily_mean",
        window=SeriesWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2)),
        status=OutcomeStatus.FAILED,
        reason="partial stage failure",
    )
    single = _make_result(
        rows,
        (s_q, s_h),
        bundle=AnnotationBundle(
            observation_tables={"provider_a.obs": obs_table},
            series_tables={"provider_a.meta": ser_table},
        ),
    )
    single = with_annotations(
        single.model_copy(
            update={
                "outcomes": (out_q, out_h),
                "issues": (prov_issue, src_issue, prov_issue),
                "provenance": single.provenance.model_copy(
                    update={
                        "endpoints": ("https://example.invalid/a", "https://example.invalid/a"),
                        "decomposition": ("d1", "d1"),
                    }
                ),
            }
        ),
        single._annotations,
    )

    validate_calls: list[str] = []
    orig_validate_data = observations.validate_observation_data
    orig_zone_value = observations.ZoneValue
    orig_validate_bundle = source_annotations.validate_bundle_for_result
    orig_merge_sorted = AnnotationBundle.merge_sorted

    def spy_validate_data(data: object) -> None:
        validate_calls.append("validate_observation_data")
        return orig_validate_data(data)

    def spy_zone_value(value: str) -> object:
        validate_calls.append("ZoneValue")
        return orig_zone_value(value)

    def spy_bundle(bundle: AnnotationBundle, data: pl.DataFrame, source_series: tuple[SourceSeries, ...]) -> None:
        validate_calls.append("validate_bundle")
        return orig_validate_bundle(bundle, data, source_series)

    @classmethod
    def spy_merge_sorted(cls, *args: object, **kwargs: object) -> AnnotationBundle:
        validate_calls.append("merge_sorted")
        return orig_merge_sorted.__func__(cls, *args, **kwargs)

    orig_with_annotations = discovery.with_annotations

    monkeypatch.setattr(observations, "validate_observation_data", spy_validate_data)
    monkeypatch.setattr(observations, "ZoneValue", spy_zone_value)
    monkeypatch.setattr(source_annotations, "validate_bundle_for_result", spy_bundle)
    monkeypatch.setattr(
        discovery,
        "with_annotations",
        lambda res, bundle: (validate_calls.append("with_annotations"), orig_with_annotations(res, bundle))[1],
    )
    monkeypatch.setattr(AnnotationBundle, "merge_sorted", spy_merge_sorted)

    merged = _merge_provider_results((single,), (s_q, s_h))
    assert validate_calls == []
    assert merged.data is single.data
    assert merged._annotations is single._annotations
    assert merged.issues == (prov_issue, src_issue)
    assert merged.provenance.endpoints == ("https://example.invalid/a",)
    assert merged.provenance.decomposition == ("d1",)
    assert merged.provenance.request == {
        "scope": single.scope.model_dump(mode="json"),
        "series": [
            {"station_id": "s1", "product_id": "discharge_daily_mean", "series_id": s_q.series_id},
            {"station_id": "s1", "product_id": "stage_daily_mean", "series_id": s_h.series_id},
        ],
        "start": "2026-01-01T00:00:00",
        "end": "2026-01-02T23:59:59",
    }
    assert merged.outcomes == (out_q, out_h)
    assert merged.to_polars(annotations="tag").select("value", "tag").rows() == [
        (None, "q-null"),
        (1.0, "q-one"),
        (5.0, "h-five"),
    ]
    assert rr.annotations(merged, schema="provider_a.obs")["tag"].to_list() == ["q-null", "q-one", "q-unm", "h-five"]


def test_merge_single_station_multi_series_unsorted_rows_and_annotations_preserves_exact_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rivretrieve._internal import discovery, observations, source_annotations

    s_q = _series_def("provider_a", "s1", "discharge_daily_mean")
    s_h = _series_def("provider_a", "s1", "stage_daily_mean")
    obs_schema = AnnotationSchema(
        schema_id="provider_a.obs",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="tag", dtype="String", description="Observation tag."),),
    )
    empty_schema = AnnotationSchema(
        schema_id="provider_a.empty_obs",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="unused", dtype="String", description="Unused empty schema."),),
    )
    ser_schema = AnnotationSchema(
        schema_id="provider_a.meta",
        provider_id="provider_a",
        scope=AnnotationScope.SERIES,
        fields=(AnnotationField(name="gauge_note", dtype="String", description="Series note."),),
    )
    # Intentionally unsorted: stage first, then discharge duplicate timestamps (2.0, 1.0, None)
    rows = [
        {
            "station_id": "s1",
            "product_id": "stage_daily_mean",
            "time": datetime(2026, 1, 1),
            "time_zone": "+00:00",
            "value": 9.0,
        },
        {
            "station_id": "s1",
            "product_id": "discharge_daily_mean",
            "time": datetime(2026, 1, 1),
            "time_zone": "+00:00",
            "value": 2.0,
        },
        {
            "station_id": "s1",
            "product_id": "discharge_daily_mean",
            "time": datetime(2026, 1, 1),
            "time_zone": "+00:00",
            "value": 1.0,
        },
        {
            "station_id": "s1",
            "product_id": "discharge_daily_mean",
            "time": datetime(2026, 1, 1),
            "time_zone": "+00:00",
            "value": None,
        },
    ]
    obs_table = ObservationAnnotationTable.from_rows(
        schema=obs_schema,
        rows=pl.DataFrame(
            {
                "series_id": [
                    s_h.series_id,
                    s_q.series_id,
                    s_q.series_id,
                    s_q.series_id,
                    s_q.series_id,
                ],
                "facts_id": [
                    s_h.facts[0].facts_id,
                    s_q.facts[0].facts_id,
                    s_q.facts[0].facts_id,
                    s_q.facts[0].facts_id,
                    s_q.facts[0].facts_id,
                ],
                "station_id": ["s1"] * 5,
                "product_id": [
                    "stage_daily_mean",
                    "discharge_daily_mean",
                    "discharge_daily_mean",
                    "discharge_daily_mean",
                    "discharge_daily_mean",
                ],
                "time": [datetime(2026, 1, 1)] * 5,
                "time_zone": ["+00:00"] * 5,
                "measured": [True, False, True, True, True],
                "tag": ["h-nine", "q-unm", "q-two", "q-one", "q-null"],
            },
            schema={
                "series_id": pl.String,
                "facts_id": pl.String,
                "station_id": pl.String,
                "product_id": pl.String,
                "time": pl.Datetime("us"),
                "time_zone": pl.String,
                "measured": pl.Boolean,
                **obs_schema.polars_schema(),
            },
        ),
        measurement_indices=(0, None, 1, 2, 3),
    )
    # Reverse series_id order for SeriesAnnotationTable
    reverse_series_ids = sorted([s_q.series_id, s_h.series_id], reverse=True)
    ser_table = SeriesAnnotationTable.from_rows(
        schema=ser_schema,
        rows=pl.DataFrame(
            {"series_id": reverse_series_ids, "gauge_note": ["note-rev-0", "note-rev-1"]},
            schema={"series_id": pl.String, **ser_schema.polars_schema()},
        ),
    )
    single = _make_result(
        rows,
        (s_q, s_h),
        bundle=AnnotationBundle(
            observation_tables={
                "provider_a.obs": obs_table,
                "provider_a.empty_obs": ObservationAnnotationTable.empty(empty_schema),
            },
            series_tables={"provider_a.meta": ser_table},
        ),
    )

    revalidation_calls: list[str] = []
    orig_validate_data = observations.validate_observation_data
    orig_zone_value = observations.ZoneValue
    orig_validate_bundle = source_annotations.validate_bundle_for_result
    monkeypatch.setattr(
        observations,
        "validate_observation_data",
        lambda data: (revalidation_calls.append("validate_observation_data"), orig_validate_data(data))[1],
    )
    monkeypatch.setattr(
        observations,
        "ZoneValue",
        lambda value: (revalidation_calls.append("ZoneValue"), orig_zone_value(value))[1],
    )
    monkeypatch.setattr(
        source_annotations,
        "validate_bundle_for_result",
        lambda *a, **k: (revalidation_calls.append("validate_bundle"), orig_validate_bundle(*a, **k))[1],
    )
    orig_with_annotations = discovery.with_annotations
    monkeypatch.setattr(
        discovery,
        "with_annotations",
        lambda res, bundle: (revalidation_calls.append("with_annotations"), orig_with_annotations(res, bundle))[1],
    )

    merged = _merge_provider_results((single,), (s_q, s_h))
    assert revalidation_calls == []
    assert merged.to_polars(annotations="tag").select("product_id", "value", "tag").rows() == [
        ("discharge_daily_mean", None, "q-null"),
        ("discharge_daily_mean", 1.0, "q-one"),
        ("discharge_daily_mean", 2.0, "q-two"),
        ("stage_daily_mean", 9.0, "h-nine"),
    ]
    assert rr.annotations(merged, schema="provider_a.obs")["tag"].to_list() == [
        "q-null",
        "q-one",
        "q-two",
        "q-unm",
        "h-nine",
    ]
    with pytest.raises(ValueError, match="Unknown annotation schema"):
        rr.annotations(merged, schema="provider_a.empty_obs")
    assert rr.series(merged, annotations="gauge_note")["series_id"].to_list() == [s_q.series_id, s_h.series_id]
    assert rr.series(merged, annotations="gauge_note")["gauge_note"].to_list() == ["note-rev-1", "note-rev-0"]


def test_merge_single_station_ordered_data_unsorted_annotations_and_contract_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rivretrieve._internal.issues import ObservationDataSchemaError
    from rivretrieve._internal.source_series import OutcomeStatus, RetrievalOutcome, SeriesWindow

    s_q = _series_def("provider_a", "s1", "discharge_daily_mean")
    obs_schema = AnnotationSchema(
        schema_id="provider_a.obs",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="tag", dtype="String", description="Observation tag."),),
    )
    # Ordered data (2.0, 2.0 at same timestamp) with unsorted annotations (unmeasured before measured + reversed indices)
    single_ordered = _make_result(
        [
            {
                "station_id": "s1",
                "product_id": "discharge_daily_mean",
                "time": datetime(2026, 1, 1),
                "time_zone": "+00:00",
                "value": 2.0,
            },
            {
                "station_id": "s1",
                "product_id": "discharge_daily_mean",
                "time": datetime(2026, 1, 1),
                "time_zone": "+00:00",
                "value": 2.0,
            },
        ],
        (s_q,),
        bundle=AnnotationBundle(
            observation_tables={
                "provider_a.obs": ObservationAnnotationTable.from_rows(
                    schema=obs_schema,
                    rows=pl.DataFrame(
                        {
                            "series_id": [s_q.series_id] * 3,
                            "facts_id": [s_q.facts[0].facts_id] * 3,
                            "station_id": ["s1"] * 3,
                            "product_id": ["discharge_daily_mean"] * 3,
                            "time": [datetime(2026, 1, 1)] * 3,
                            "time_zone": ["+00:00"] * 3,
                            "measured": [False, True, True],
                            "tag": ["unm", "second", "first"],
                        },
                        schema={
                            "series_id": pl.String,
                            "facts_id": pl.String,
                            "station_id": pl.String,
                            "product_id": pl.String,
                            "time": pl.Datetime("us"),
                            "time_zone": pl.String,
                            "measured": pl.Boolean,
                            **obs_schema.polars_schema(),
                        },
                    ),
                    measurement_indices=(None, 1, 0),
                )
            }
        ),
    )
    from rivretrieve._internal import observations, source_annotations

    validate_calls: list[str] = []
    orig_validate_data = observations.validate_observation_data
    orig_zone_value = observations.ZoneValue
    orig_merge_sorted = AnnotationBundle.merge_sorted
    orig_validate_bundle = source_annotations.validate_bundle_for_result
    monkeypatch.setattr(
        observations,
        "validate_observation_data",
        lambda data: (validate_calls.append("validate_observation_data"), orig_validate_data(data))[1],
    )
    monkeypatch.setattr(
        observations,
        "ZoneValue",
        lambda value: (validate_calls.append("ZoneValue"), orig_zone_value(value))[1],
    )
    monkeypatch.setattr(
        source_annotations,
        "validate_bundle_for_result",
        lambda *a, **k: (validate_calls.append("validate_bundle"), orig_validate_bundle(*a, **k))[1],
    )

    @classmethod
    def spy_merge_sorted(cls, *args: object, **kwargs: object) -> AnnotationBundle:
        validate_calls.append("merge_sorted")
        return orig_merge_sorted.__func__(cls, *args, **kwargs)

    monkeypatch.setattr(AnnotationBundle, "merge_sorted", spy_merge_sorted)
    merged = _merge_provider_results((single_ordered,), (s_q,))
    assert validate_calls == []
    assert merged.data is single_ordered.data
    assert merged.to_polars(annotations="tag")["tag"].to_list() == ["first", "second"]
    assert rr.annotations(merged, schema="provider_a.obs")["tag"].to_list() == ["first", "second", "unm"]

    # view_scope present -> falls back to full ObservationResult validation
    viewed = rr.pick(single_ordered, station="s1", on_issue="ignore")
    validate_calls.clear()
    _merge_provider_results((viewed,), (s_q,))
    assert "validate_observation_data" in validate_calls
    assert "ZoneValue" in validate_calls

    # Missing provenance.request start/end still raises FatalContractError
    bad_req = single_ordered.model_copy(
        update={"provenance": single_ordered.provenance.model_copy(update={"request": {}})}
    )
    with pytest.raises(FatalContractError, match="normalized requested window"):
        _merge_provider_results((bad_req,), (s_q,))

    # Zero-observation result with invalid outcome contract still raises ObservationDataSchemaError
    zero_obs = _empty_result(provider_id="provider_a").model_copy(
        update={
            "outcomes": (
                RetrievalOutcome(
                    outcome_id="bad-empty",
                    series_id="missing-series",
                    station_id="s1",
                    product_id="discharge_daily_mean",
                    window=SeriesWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2)),
                    status=OutcomeStatus.EMPTY,
                    facts_ids=(s_q.facts[0].facts_id,),
                ),
            )
        }
    )
    with pytest.raises(ObservationDataSchemaError, match="unknown source series"):
        _merge_provider_results((zero_obs,), ())


def test_filter_mask_anti_join_sort_validation_and_projection_preserve_duplicate_occurrences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rivretrieve._internal.engine import RowsSchema
    from rivretrieve._internal.source_annotations import (
        anti_join_native_with_annotations,
        filter_native_with_annotations_by_mask,
        sort_native_by_station_with_annotations,
        validate_bundle_for_result,
    )

    s1 = _series_def("provider_a", "s1", "discharge_daily_mean")
    s2 = _series_def("provider_a", "s2", "stage_daily_mean")
    schema = AnnotationSchema(
        schema_id="provider_a.obs",
        provider_id="provider_a",
        scope=AnnotationScope.OBSERVATION,
        fields=(AnnotationField(name="tag", dtype="String", description="Observation tag."),),
    )
    ann_schema = {
        "series_id": pl.String,
        "facts_id": pl.String,
        "station_id": pl.String,
        "product_id": pl.String,
        "time": pl.Datetime("us"),
        "time_zone": pl.String,
        "measured": pl.Boolean,
        **schema.polars_schema(),
    }

    ts = datetime(2026, 1, 1)
    ts2 = datetime(2026, 1, 2)
    rows = pl.DataFrame(
        {
            "station_id": ["s2", "s1", "s1", "s1"],
            "product_id": ["stage_daily_mean", "discharge_daily_mean", "discharge_daily_mean", "discharge_daily_mean"],
            "time": [ts, ts, ts, ts2],
            "value": [9.0, 1.0, 2.0, 3.0],
            "time_zone": ["+00:00"] * 4,
            "series_id": [s2.series_id, s1.series_id, s1.series_id, s1.series_id],
            "facts_id": [s2.facts[0].facts_id, s1.facts[0].facts_id, s1.facts[0].facts_id, s1.facts[0].facts_id],
            "source_unit": ["m", "m3/s", "m3/s", "m3/s"],
        },
        schema=RowsSchema.polars_schema,
    )
    # Only the 2nd occurrence at `ts` for s1 (idx=2) carries a flag, plus unmeasured slot at ts2
    table = ObservationAnnotationTable.from_rows(
        schema=schema,
        rows=pl.DataFrame(
            {
                "series_id": [s1.series_id, s2.series_id, s1.series_id],
                "facts_id": [s1.facts[0].facts_id, s2.facts[0].facts_id, s1.facts[0].facts_id],
                "station_id": ["s1", "s2", "s1"],
                "product_id": ["discharge_daily_mean", "stage_daily_mean", "discharge_daily_mean"],
                "time": [ts, ts, ts2],
                "time_zone": ["+00:00", "+00:00", "+00:00"],
                "measured": [True, True, False],
                "tag": ["second-dup", "s2-flag", "unmeasured-ts2"],
            },
            schema=ann_schema,
        ),
        measurement_indices=(2, 0, None),
    )
    bundle = AnnotationBundle(observation_tables={"provider_a.obs": table})

    # Validate error contracts
    with pytest.raises(FatalContractError, match="disagrees between measured and measurement index"):
        ObservationAnnotationTable.from_rows(schema=schema, rows=table.rows, measurement_indices=(None, 0, None))
    with pytest.raises(FatalContractError, match="cannot be negative"):
        ObservationAnnotationTable.from_rows(schema=schema, rows=table.rows, measurement_indices=(-1, 0, None))
    with pytest.raises(FatalContractError, match="Duplicate annotation row"):
        ObservationAnnotationTable.from_rows(
            schema=schema,
            rows=table.rows.with_columns(pl.lit(True).alias("measured")),
            measurement_indices=(0, 0, 1),
        )
    with pytest.raises(FatalContractError, match="missing observation row 99"):
        validate_bundle_for_result(
            AnnotationBundle(
                observation_tables={
                    "provider_a.obs": ObservationAnnotationTable.from_rows(
                        schema=schema, rows=table.rows.head(1), measurement_indices=(99,)
                    )
                }
            ),
            rows,
            (s1, s2),
        )
    with pytest.raises(FatalContractError, match="disagrees with observation row coordinates"):
        validate_bundle_for_result(bundle, rows.with_columns(pl.col("time").dt.replace_time_zone("UTC")), (s1, s2))

    # Spy on to_dicts to ensure anti_join & mask filter avoid Python dicts
    monkeypatch.setattr(
        pl.DataFrame, "to_dicts", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("to_dicts called"))
    )

    # Sort stably by station_id: s1 rows move to indices 0,1,2 and s2 moves to 3; second-dup must link to index 1!
    sorted_rows, sorted_bundle = sort_native_by_station_with_annotations(rows, bundle)
    assert sorted_rows["value"].to_list() == [1.0, 2.0, 3.0, 9.0]
    sorted_tbl = sorted_bundle.observation_tables["provider_a.obs"]
    assert sorted_tbl.rows["tag"].to_list() == ["second-dup", "unmeasured-ts2", "s2-flag"]
    assert sorted_tbl.measurement_indices == (1, None, 3)
    validate_bundle_for_result(sorted_bundle, sorted_rows, (s1, s2))

    # Mask filter dropping first row of s1 (index 0): second-dup shifts from 1 -> 0
    keep_mask = pl.Series([False, True, True, True], dtype=pl.Boolean)
    masked_rows, masked_bundle = filter_native_with_annotations_by_mask(sorted_rows, sorted_bundle, keep_mask)
    assert masked_rows["value"].to_list() == [2.0, 3.0, 9.0]
    masked_tbl = masked_bundle.observation_tables["provider_a.obs"]
    assert masked_tbl.measurement_indices == (0, None, 2)
    validate_bundle_for_result(masked_bundle, masked_rows, (s1, s2))

    # Anti-join excluding ts2 drops unmeasured-ts2 and row at ts2, preserving second-dup and s2-flag
    excl = sorted_rows.filter(pl.col("time") == ts2)
    aj_rows, aj_bundle = anti_join_native_with_annotations(sorted_rows, sorted_bundle, excl)
    assert aj_rows["value"].to_list() == [1.0, 2.0, 9.0]
    aj_tbl = aj_bundle.observation_tables["provider_a.obs"]
    assert aj_tbl.rows["tag"].to_list() == ["second-dup", "s2-flag"]
    assert aj_tbl.measurement_indices == (1, 2)
    validate_bundle_for_result(aj_bundle, aj_rows, (s1, s2))

    # 1:1 aligned projection fast path preserves exact series dtype & values
    aligned_rows = pl.DataFrame(
        {
            "series_id": [s1.series_id, s1.series_id],
            "facts_id": [s1.facts[0].facts_id, s1.facts[0].facts_id],
            "station_id": ["s1", "s1"],
            "product_id": ["discharge_daily_mean", "discharge_daily_mean"],
            "time": [ts, ts2],
            "time_zone": ["+00:00", "+00:00"],
            "measured": [True, True],
            "tag": ["t0", "t1"],
        },
        schema=ann_schema,
    )
    aligned_bundle = AnnotationBundle(
        observation_tables={
            "provider_a.obs": ObservationAnnotationTable.from_rows(
                schema=schema, rows=aligned_rows, measurement_indices=(0, 1)
            )
        }
    )
    projected = aligned_bundle.project_observation_columns(2, True)
    assert len(projected) == 1
    assert projected[0].to_list() == ["t0", "t1"]

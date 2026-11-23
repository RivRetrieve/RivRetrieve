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
    frequency = "daily" if "daily" in product_id else "15min"
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

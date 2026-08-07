from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo

import pandas.testing as pd_testing
import polars as pl
import polars.testing as pl_testing
import pytest

from rivretrieve._internal.catalogues.schemas import validate_catalogue
from rivretrieve._internal.engine import SourceCallOrigin, UnknownOriginFact
from rivretrieve._internal.issues import (
    AnnotationSchemaViolationError,
    InvalidObservationRequestError,
    IssuePolicyError,
    ObservationDataSchemaError,
)
from rivretrieve._internal.observations import (
    AnnotationSchema,
    AnnotationSchemaDeclaration,
    AnnotationTable,
    ObservationDataSchema,
    ObservationProvenance,
    ObservationRequest,
    ObservationResult,
    RawMode,
    RawPayload,
    RawSourceCall,
    RowAnnotationTableSchema,
    SeriesAnnotationTableSchema,
    validate_annotation_names,
    validate_observation_data,
)
from rivretrieve._internal.primitives import ProviderId


def _issue_policy_error_chain(exc: BaseException) -> list[IssuePolicyError]:
    found = []
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, IssuePolicyError):
            found.append(current)
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None:
            stack.append(current.__context__)
    return found


def _observation_df(**overrides: object) -> pl.DataFrame:
    data: dict[str, object] = {
        "time": [datetime(2026, 1, 1), datetime(2026, 1, 2)],
        "station_id": ["station-1", "station-1"],
        "product_id": ["flow", "flow"],
        "value": [1.2, None],
    }
    data.update(overrides)
    return pl.DataFrame(data, schema=ObservationDataSchema.polars_schema)


def _row_annotation_df(**overrides: object) -> pl.DataFrame:
    data: dict[str, object] = {
        "time": [datetime(2026, 1, 1)],
        "station_id": ["station-1"],
        "product_id": ["flow"],
        "annotation": ["quality"],
        "value": ["estimated"],
    }
    data.update(overrides)
    return pl.DataFrame(data, schema=RowAnnotationTableSchema.polars_schema)


def _series_annotation_df(**overrides: object) -> pl.DataFrame:
    data: dict[str, object] = {
        "station_id": ["station-1"],
        "product_id": ["flow"],
        "annotation": ["timezone"],
        "value": ["Europe/Zurich"],
    }
    data.update(overrides)
    return pl.DataFrame(data, schema=SeriesAnnotationTableSchema.polars_schema)


def _row_annotations() -> AnnotationTable:
    return AnnotationTable(_row_annotation_df(), RowAnnotationTableSchema)


def _series_annotations() -> AnnotationTable:
    return AnnotationTable(_series_annotation_df(), SeriesAnnotationTableSchema)


def _provenance() -> ObservationProvenance:
    return ObservationProvenance(source="live", provider_id=ProviderId("provider-a"))


def _result(data: pl.DataFrame | None = None) -> ObservationResult:
    return ObservationResult(
        data=_observation_df() if data is None else data,
        row_annotations=_row_annotations(),
        series_annotations=_series_annotations(),
        provenance=_provenance(),
        raw=RawPayload(provider_id=ProviderId("provider-a")),
    )


def test_observation_request_from_single_station_product_normalizes_to_tuples() -> None:
    request = ObservationRequest.from_inputs(
        provider_id="provider-a",
        stations="station-1",
        products="flow",
        start="2026-01-01",
        end="2026-01-02",
    )

    assert request.provider_id == ProviderId("provider-a")
    assert request.stations == ("station-1",)
    assert request.products == ("flow",)


def test_observation_request_from_sequences_preserves_order() -> None:
    request = ObservationRequest.from_inputs(
        provider_id="provider-a",
        stations=["station-2", "station-1", "station-1"],
        products=("level", "flow"),
        start="2026-01-01",
        end="2026-01-02",
    )

    assert request.stations == ("station-2", "station-1", "station-1")
    assert request.products == ("level", "flow")


def test_observation_request_normalizes_typed_temporal_inputs() -> None:
    request = ObservationRequest.from_inputs(
        provider_id="provider-a",
        stations="station-1",
        products="flow",
        start=datetime(2026, 1, 1),
        end=datetime(2026, 1, 2, 3, 4, 5),
    )
    string_request = ObservationRequest.from_inputs(
        provider_id="provider-a",
        stations="station-1",
        products="flow",
        start="2026-01-01T12:30:00",
        end="2026-01-02",
    )

    assert request.start.isoformat() == "2026-01-01T00:00:00"
    assert request.end.isoformat() == "2026-01-02T03:04:05"
    assert string_request.start.isoformat() == "2026-01-01T12:30:00"
    assert string_request.end.isoformat() == "2026-01-02T23:59:59.999999"


def test_bare_date_end_expands_but_explicit_midnight_is_preserved() -> None:
    kwargs = {"provider_id": "provider-a", "stations": "station-1", "products": "flow"}
    bare = ObservationRequest.from_inputs(**kwargs, start="2020-07-31", end="2020-07-31")
    explicit = ObservationRequest.from_inputs(**kwargs, start="2020-07-31", end="2020-07-31 00:00")

    assert bare.start.isoformat() == explicit.start.isoformat() == "2020-07-31T00:00:00"
    assert bare.end.isoformat() == "2020-07-31T23:59:59.999999"
    assert explicit.end.isoformat() == "2020-07-31T00:00:00"


def test_datetime_midnight_is_explicit_not_a_bare_date() -> None:
    request = ObservationRequest.from_inputs(
        provider_id="provider-a",
        stations="station-1",
        products="flow",
        start=datetime(2020, 7, 31),
        end=datetime(2020, 7, 31),
    )
    assert request.end.isoformat() == "2020-07-31T00:00:00"


def test_observation_request_rejects_reversed_normalized_window() -> None:
    with pytest.raises(
        InvalidObservationRequestError,
        match="^requested window start must not be after end$",
    ):
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations="station-1",
            products="flow",
            start="2020-08-01",
            end="2020-07-31",
        )


@pytest.mark.parametrize("name", ["start", "end"])
@pytest.mark.parametrize(
    "value",
    [
        datetime(2020, 7, 31, tzinfo=UTC),
        datetime(2020, 7, 31, tzinfo=timezone(timedelta(hours=2))),
        datetime(2020, 7, 31, tzinfo=ZoneInfo("Europe/Zurich")),
    ],
)
def test_observation_request_rejects_zone_carrying_datetime_with_fix(name: str, value: datetime) -> None:
    inputs: dict[str, object] = {"start": "2020-07-31", "end": "2020-07-31"}
    inputs[name] = value
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(provider_id="provider-a", stations="station-1", products="flow", **inputs)
    assert str(exc_info.value) == (
        f"{name} must be wall-clock time without a time zone; remove it with `{name} = {name}.replace(tzinfo=None)`."
    )


@pytest.mark.parametrize("name", ["start", "end"])
@pytest.mark.parametrize("value", ["2020-07-31T00:00:00Z", "2020-07-31T00:00:00+02:00", "2020-07-31T00:00:00-06:00"])
def test_observation_request_rejects_offset_bearing_iso_string_with_fix(name: str, value: str) -> None:
    inputs: dict[str, object] = {"start": "2020-07-31", "end": "2020-07-31"}
    inputs[name] = value
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(provider_id="provider-a", stations="station-1", products="flow", **inputs)
    assert str(exc_info.value) == (
        f"{name} must be wall-clock time without a time zone; remove it with "
        f"`{name} = datetime.fromisoformat({name}).replace(tzinfo=None)`."
    )


@pytest.mark.parametrize("name", ["start", "end"])
def test_observation_request_rejects_date_object(name: str) -> None:
    inputs: dict[str, object] = {"start": "2020-07-31", "end": "2020-07-31"}
    inputs[name] = date(2020, 7, 31)
    with pytest.raises(
        InvalidObservationRequestError,
        match=rf"^{name} must be a datetime or ISO-like string$",
    ):
        ObservationRequest.from_inputs(provider_id="provider-a", stations="station-1", products="flow", **inputs)


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_request_rejects_missing_provider_id_for_every_on_issue(on_issue: str) -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id=cast(Any, None),
            stations="station-1",
            products="flow",
            start="2026-01-01",
            end="2026-01-02",
        )

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_request_rejects_missing_start_for_every_on_issue(on_issue: str) -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations="station-1",
            products="flow",
            start=cast(Any, None),
            end="2026-01-02",
        )

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_request_rejects_missing_end_for_every_on_issue(on_issue: str) -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations="station-1",
            products="flow",
            start="2026-01-01",
            end=cast(Any, None),
        )

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("field", ["start", "end"])
def test_observation_request_rejects_unparseable_temporal_values(field: str) -> None:
    inputs = {
        "provider_id": "provider-a",
        "stations": "station-1",
        "products": "flow",
        "start": "2026-01-01",
        "end": "2026-01-02",
    }
    inputs[field] = "not-a-date"

    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(**inputs)  # type: ignore[arg-type]

    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_request_rejects_missing_stations_for_every_on_issue(on_issue: str) -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations=cast(Any, None),
            products="flow",
            start="2026-01-01",
            end="2026-01-02",
        )

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_request_rejects_missing_products_for_every_on_issue(on_issue: str) -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations="station-1",
            products=cast(Any, None),
            start="2026-01-01",
            end="2026-01-02",
        )

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_request_rejects_empty_station_sequence_for_every_on_issue(on_issue: str) -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations=[],
            products="flow",
            start="2026-01-01",
            end="2026-01-02",
        )

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_request_rejects_empty_product_sequence_for_every_on_issue(on_issue: str) -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations="station-1",
            products=[],
            start="2026-01-01",
            end="2026-01-02",
        )

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize(
    ("stations", "products"),
    [
        (["station-1", 12], "flow"),
        (["station-1", ""], "flow"),
        ("station-1", ["flow", object()]),
        ("station-1", ["flow", "  "]),
        (123, "flow"),
        ("station-1", 123),
    ],
)
@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_request_rejects_non_string_and_empty_ids(
    stations: object,
    products: object,
    on_issue: str,
) -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations=cast(Any, stations),
            products=cast(Any, products),
            start="2026-01-01",
            end="2026-01-02",
        )

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


def test_observation_provenance_constructs_without_scientific_metadata() -> None:
    provenance = ObservationProvenance(
        source="live",
        provider_id=ProviderId("provider-a"),
        request={"stations": ["station-1"]},
        calls_made=({"url": "https://example.invalid/observations"},),
        time_windows=({"start": "2026-01-01", "end": "2026-01-02"},),
        decomposition=("by-station",),
        endpoints=("https://example.invalid/observations",),
    )

    assert provenance.provider_id == ProviderId("provider-a")
    assert not hasattr(provenance, "unit")
    assert not hasattr(provenance, "timezone")
    assert not hasattr(provenance, "quality_flag")


def test_observation_provenance_metadata_may_be_json_string() -> None:
    provenance = ObservationProvenance(
        source="live",
        provider_id=ProviderId("provider-a"),
        metadata='{"trace": "kept"}',
    )

    assert provenance.metadata == '{"trace": "kept"}'


def test_annotation_schema_constructs_per_annotation_declaration() -> None:
    schema = AnnotationSchema(
        annotation_id="quality",
        description="Provider quality code",
        value_type="string",
        allowed_values=("estimated", "observed"),
        source_field="qc",
    )

    assert schema.annotation_id == "quality"
    assert schema.allowed_values == ("estimated", "observed")
    assert schema.to_row()["allowed_values"] == '["estimated", "observed"]'


def test_annotation_schema_declaration_reuses_catalogue_schema_pattern() -> None:
    schema = AnnotationSchema("quality", "Provider quality code", "string", ("estimated",), "qc")
    frame = pl.DataFrame([schema.to_row()], schema=AnnotationSchemaDeclaration.polars_schema)

    issues = validate_catalogue(frame, AnnotationSchemaDeclaration, on_issue="raise")

    assert issues == []
    assert AnnotationSchema.from_row(frame.row(0, named=True)) == schema


@pytest.mark.parametrize("annotation_id", ["", "  ", 123])
def test_annotation_schema_rejects_invalid_annotation_id(annotation_id: object) -> None:
    with pytest.raises(AnnotationSchemaViolationError):
        AnnotationSchema(cast(Any, annotation_id), "Description", "string")


@pytest.mark.parametrize("value_type", ["", "  ", "opaque", 123])
def test_annotation_schema_rejects_invalid_value_type(value_type: object) -> None:
    with pytest.raises(AnnotationSchemaViolationError):
        AnnotationSchema("quality", "Description", cast(Any, value_type))


def test_annotation_table_validates_row_annotation_shape() -> None:
    table = AnnotationTable(_row_annotation_df(), RowAnnotationTableSchema)

    pl_testing.assert_frame_equal(table.data, _row_annotation_df())
    assert table.schema == RowAnnotationTableSchema


def test_annotation_table_validates_series_annotation_shape() -> None:
    table = AnnotationTable(_series_annotation_df(), SeriesAnnotationTableSchema)

    pl_testing.assert_frame_equal(table.data, _series_annotation_df())
    assert table.schema == SeriesAnnotationTableSchema


def test_annotation_table_rejects_missing_required_column() -> None:
    with pytest.raises(AnnotationSchemaViolationError):
        AnnotationTable(_row_annotation_df().drop("annotation"), RowAnnotationTableSchema)


def test_annotation_table_rejects_wrong_dtype() -> None:
    frame = _row_annotation_df().with_columns(pl.Series("value", [1], dtype=pl.Int64))

    with pytest.raises(AnnotationSchemaViolationError):
        AnnotationTable(frame, RowAnnotationTableSchema)


def test_validate_annotation_names_accepts_declared_annotation_ids() -> None:
    table = AnnotationTable(_row_annotation_df(), RowAnnotationTableSchema)

    validate_annotation_names(table, [AnnotationSchema("quality", "Provider quality code", "string")])


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_validate_annotation_names_rejects_undeclared_annotations_for_every_on_issue(on_issue: str) -> None:
    table = AnnotationTable(_row_annotation_df(), RowAnnotationTableSchema)

    with pytest.raises(AnnotationSchemaViolationError) as exc_info:
        validate_annotation_names(table, [AnnotationSchema("timezone", "Timezone", "string")])

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


def test_validate_annotation_names_accepts_multiple_provider_schemas() -> None:
    table = AnnotationTable(_row_annotation_df(), RowAnnotationTableSchema)

    validate_annotation_names(
        table,
        [
            AnnotationSchema("timezone", "Timezone", "string"),
            AnnotationSchema("quality", "Provider quality code", "string"),
        ],
    )


def _raw_origin() -> SourceCallOrigin:
    return SourceCallOrigin(
        url="https://example.invalid/observations",
        request_parameters={"station": "station-1"},
        status_code=200,
        retrieved_at=datetime(2026, 8, 7, 12, 30, tzinfo=UTC),
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


def test_raw_carriers_and_mode_are_exact_frozen_domain_types() -> None:
    content = b'{"ok":true}'
    origin = _raw_origin()
    call = RawSourceCall(content=content, origin=origin)
    payload = RawPayload(provider_id=ProviderId("provider-a"), entries=(call,))

    assert tuple(RawMode) == (RawMode.OMIT, RawMode.INCLUDE)
    assert RawMode.OMIT.value == "omit"
    assert RawMode.INCLUDE.value == "include"
    assert tuple(field.name for field in fields(RawSourceCall)) == ("content", "origin")
    assert tuple(field.name for field in fields(RawPayload)) == ("provider_id", "entries")
    assert payload.provider_id == ProviderId("provider-a")
    assert payload.entries == (call,)
    assert payload.entries[0].content is content
    assert payload.entries[0].origin is origin
    with pytest.raises(FrozenInstanceError):
        call.content = b"changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        payload.entries = ()  # type: ignore[misc]


def test_raw_carriers_reject_mutable_entries_and_non_bytes_content() -> None:
    origin = _raw_origin()
    call = RawSourceCall(content=b'{"ok":true}', origin=origin)

    with pytest.raises(TypeError):
        RawPayload(provider_id=ProviderId("provider-a"), entries=[call])  # type: ignore[arg-type]
    for content in ('{"ok":true}', bytearray(b'{"ok":true}')):
        with pytest.raises(TypeError):
            RawSourceCall(content=content, origin=origin)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RawSourceCall(content=b'{"ok":true}', origin={})  # type: ignore[arg-type]


def test_observation_data_schema_accepts_canonical_long_table() -> None:
    data = _observation_df()

    validate_observation_data(data)


def test_observation_data_schema_accepts_native_datetime_without_utc_mandate() -> None:
    data = pl.DataFrame(
        {
            "time": pl.Series(
                "time",
                [datetime(2026, 1, 1), datetime(2026, 1, 2)],
                dtype=pl.Datetime(time_zone="Europe/Zurich"),
            ),
            "station_id": ["station-1", "station-1"],
            "product_id": ["flow", "flow"],
            "value": [1.2, 1.3],
        }
    )

    validate_observation_data(data)


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_data_schema_rejects_provider_id_column_as_extra_under_raise(on_issue: str) -> None:
    data = _observation_df().with_columns(pl.lit("provider-a").alias("provider_id"))

    with pytest.raises(ObservationDataSchemaError) as exc_info:
        validate_observation_data(data)

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_data_schema_rejects_missing_column(on_issue: str) -> None:
    with pytest.raises(ObservationDataSchemaError) as exc_info:
        validate_observation_data(_observation_df().drop("station_id"))

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize(
    "data",
    [
        _observation_df().with_columns(pl.col("time").cast(pl.Utf8)),
        _observation_df().with_columns(pl.Series("station_id", [1, 2], dtype=pl.Int64)),
        _observation_df().with_columns(pl.Series("product_id", [1, 2], dtype=pl.Int64)),
        _observation_df().with_columns(pl.Series("value", ["1.2", "1.3"], dtype=pl.Utf8)),
    ],
)
@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_data_schema_rejects_wrong_dtype(data: pl.DataFrame, on_issue: str) -> None:
    with pytest.raises(ObservationDataSchemaError) as exc_info:
        validate_observation_data(data)

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize(
    "data",
    [
        _observation_df(time=[None, datetime(2026, 1, 2)]),
        _observation_df(station_id=[None, "station-1"]),
        _observation_df(product_id=[None, "flow"]),
    ],
)
@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_data_schema_rejects_null_identity_columns(data: pl.DataFrame, on_issue: str) -> None:
    with pytest.raises(ObservationDataSchemaError) as exc_info:
        validate_observation_data(data)

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []


def test_observation_data_schema_allows_null_value() -> None:
    data = _observation_df(value=[None, 1.2])

    validate_observation_data(data)


def test_observation_result_constructs_with_exact_field_set() -> None:
    result = _result()

    assert tuple(ObservationResult.model_fields) == (
        "data",
        "row_annotations",
        "series_annotations",
        "provenance",
        "issues",
        "raw",
    )
    assert result.issues == ()
    assert result.raw == RawPayload(provider_id=ProviderId("provider-a"))


def test_observation_result_requires_non_null_raw_payload() -> None:
    values = {
        "data": _observation_df(),
        "row_annotations": _row_annotations(),
        "series_annotations": _series_annotations(),
        "provenance": _provenance(),
    }

    with pytest.raises(ValueError):
        ObservationResult(**values)
    with pytest.raises(ValueError):
        ObservationResult(**values, raw=None)

    result = ObservationResult(**values, raw=RawPayload(provider_id=ProviderId("provider-a")))
    assert result.raw.entries == ()


def test_observation_result_to_polars_returns_data_identity() -> None:
    result = _result()

    assert result.to_polars() is result.data


def test_observation_result_to_pandas_matches_polars_boundary_conversion() -> None:
    result = _result()

    pd_testing.assert_frame_equal(result.to_pandas(), result.data.to_pandas())


@pytest.mark.parametrize("on_issue", ["warn", "raise", "ignore"])
def test_observation_result_rejects_schema_violation_for_every_on_issue(on_issue: str) -> None:
    with pytest.raises(ObservationDataSchemaError) as exc_info:
        _result(_observation_df().drop("value"))

    assert on_issue in {"warn", "raise", "ignore"}
    assert _issue_policy_error_chain(exc_info.value) == []

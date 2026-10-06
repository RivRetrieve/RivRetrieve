from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo

import pandas.testing as pd_testing
import polars as pl
import pytest

from rivretrieve._internal.engine import SourceCallOrigin, UnknownOriginFact
from rivretrieve._internal.issues import (
    InvalidObservationRequestError,
    IssuePolicyError,
    ObservationDataSchemaError,
)
from rivretrieve._internal.observations import (
    ObservationDataSchema,
    ObservationProvenance,
    ObservationRequest,
    ObservationResult,
    ReceiptAuthorship,
    ReceiptEntry,
    ReceiptMode,
    Receipts,
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
        "time_zone": ["+00:00", "+00:00"],
        "station_id": ["station-1", "station-1"],
        "product_id": ["flow", "flow"],
        "series_id": ["test-series", "test-series"],
        "facts_id": ["test-facts", "test-facts"],
        "quantity": ["discharge", "discharge"],
        "source_unit": ["m3/s", "m3/s"],
        "unit": ["m3/s", "m3/s"],
        "value": [1.2, None],
    }
    data.update(overrides)
    return pl.DataFrame(data, schema=ObservationDataSchema.polars_schema)


def _provenance() -> ObservationProvenance:
    return ObservationProvenance(source="live", provider_id=ProviderId("provider-a"))


def _series_definition():
    # Authored result-contract fixture, not provider evidence.
    from rivretrieve._internal.source_series import PhysicalFacts, SourceIdentity, SourceSeries, known

    return SourceSeries(
        series_id="test-series",
        provider_id="provider-a",
        station_id="station-1",
        product_id="flow",
        identity=SourceIdentity(
            namespace="test", published_id="test-series", origin="mapping", evidence=("authored-contract-test",)
        ),
        facts=(
            PhysicalFacts(
                facts_id="test-facts",
                quantity=known("discharge", "authored-contract-test"),
                source_unit=known("m3/s", "authored-contract-test"),
                normalized_unit="m3/s",
            ),
        ),
    )


def _result(data: pl.DataFrame | None = None) -> ObservationResult:
    return ObservationResult(
        data=_observation_df() if data is None else data,
        provenance=_provenance(),
        receipts=Receipts(provider_id=ProviderId("provider-a")),
        source_series=(_series_definition(),),
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


def test_observation_request_rejects_missing_provider_id() -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id=cast(Any, None),
            stations="station-1",
            products="flow",
            start="2026-01-01",
            end="2026-01-02",
        )

    assert _issue_policy_error_chain(exc_info.value) == []


def test_observation_request_rejects_missing_start() -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations="station-1",
            products="flow",
            start=cast(Any, None),
            end="2026-01-02",
        )

    assert _issue_policy_error_chain(exc_info.value) == []


def test_observation_request_rejects_missing_end() -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations="station-1",
            products="flow",
            start="2026-01-01",
            end=cast(Any, None),
        )

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


def test_observation_request_rejects_missing_stations() -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations=cast(Any, None),
            products="flow",
            start="2026-01-01",
            end="2026-01-02",
        )

    assert _issue_policy_error_chain(exc_info.value) == []


def test_observation_request_rejects_missing_products() -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations="station-1",
            products=cast(Any, None),
            start="2026-01-01",
            end="2026-01-02",
        )

    assert _issue_policy_error_chain(exc_info.value) == []


def test_observation_request_rejects_empty_station_sequence() -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations=[],
            products="flow",
            start="2026-01-01",
            end="2026-01-02",
        )

    assert _issue_policy_error_chain(exc_info.value) == []


def test_observation_request_rejects_empty_product_sequence() -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations="station-1",
            products=[],
            start="2026-01-01",
            end="2026-01-02",
        )

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
def test_observation_request_rejects_non_string_and_empty_ids(
    stations: object,
    products: object,
) -> None:
    with pytest.raises(InvalidObservationRequestError) as exc_info:
        ObservationRequest.from_inputs(
            provider_id="provider-a",
            stations=cast(Any, stations),
            products=cast(Any, products),
            start="2026-01-01",
            end="2026-01-02",
        )

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


def _receipt_origin() -> SourceCallOrigin:
    return SourceCallOrigin(
        url="https://example.invalid/observations",
        request_parameters={"station": "station-1"},
        status_code=200,
        retrieved_at=datetime(2026, 8, 7, 12, 30, tzinfo=UTC),
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )


def test_receipt_carriers_and_mode_are_exact_frozen_domain_types() -> None:
    content = b'{"ok":true}'
    origin = _receipt_origin()
    call = ReceiptEntry(content=content, origin=origin, authorship=ReceiptAuthorship.PUBLISHER_PAYLOAD)
    payload = Receipts(provider_id=ProviderId("provider-a"), entries=(call,))

    assert tuple(ReceiptMode) == (ReceiptMode.OMIT, ReceiptMode.INCLUDE)
    assert ReceiptMode.OMIT.value == "omit"
    assert ReceiptMode.INCLUDE.value == "include"
    assert tuple(ReceiptAuthorship) == (
        ReceiptAuthorship.PUBLISHER_PAYLOAD,
        ReceiptAuthorship.STORE_EXCERPT,
    )
    assert ReceiptAuthorship.PUBLISHER_PAYLOAD.value == "publisher_payload"
    assert ReceiptAuthorship.STORE_EXCERPT.value == "store_excerpt"
    assert tuple(field.name for field in fields(ReceiptEntry)) == ("content", "origin", "authorship")
    assert tuple(field.name for field in fields(Receipts)) == ("provider_id", "entries")
    assert payload.provider_id == ProviderId("provider-a")
    assert payload.entries == (call,)
    assert payload.entries[0].content is content
    assert payload.entries[0].origin is origin
    assert payload.entries[0].authorship is ReceiptAuthorship.PUBLISHER_PAYLOAD
    with pytest.raises(FrozenInstanceError):
        call.content = b"changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        payload.entries = ()  # type: ignore[misc]


def test_receipt_carriers_reject_mutable_entries_and_non_bytes_content() -> None:
    origin = _receipt_origin()
    call = ReceiptEntry(content=b'{"ok":true}', origin=origin, authorship=ReceiptAuthorship.PUBLISHER_PAYLOAD)

    with pytest.raises(TypeError):
        Receipts(provider_id=ProviderId("provider-a"), entries=[call])  # type: ignore[arg-type]
    for content in ('{"ok":true}', bytearray(b'{"ok":true}')):
        with pytest.raises(TypeError):
            ReceiptEntry(content=content, origin=origin, authorship=ReceiptAuthorship.PUBLISHER_PAYLOAD)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ReceiptEntry(content=b'{"ok":true}', origin={}, authorship=ReceiptAuthorship.PUBLISHER_PAYLOAD)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="authorship must be ReceiptAuthorship"):
        ReceiptEntry(content=b'{"ok":true}', origin=origin, authorship="publisher_payload")  # type: ignore[arg-type]


def test_observation_data_schema_accepts_canonical_long_table() -> None:
    data = _observation_df()

    validate_observation_data(data)
    assert ObservationDataSchema.polars_schema == pl.Schema(
        {
            "time": pl.Datetime(),
            "time_zone": pl.Utf8,
            "station_id": pl.Utf8,
            "product_id": pl.Utf8,
            "series_id": pl.Utf8,
            "facts_id": pl.Utf8,
            "quantity": pl.Utf8,
            "source_unit": pl.Utf8,
            "unit": pl.Utf8,
            "value": pl.Float64,
        }
    )


def test_observation_data_schema_accepts_native_datetime_without_utc_mandate() -> None:
    data = pl.DataFrame(
        {
            "time": pl.Series(
                "time",
                [datetime(2026, 1, 1), datetime(2026, 1, 2)],
                dtype=pl.Datetime(time_zone="Europe/Zurich"),
            ),
            "time_zone": ["Europe/Zurich", "Europe/Zurich"],
            "station_id": ["station-1", "station-1"],
            "product_id": ["flow", "flow"],
            "series_id": ["test-series", "test-series"],
            "facts_id": ["test-facts", "test-facts"],
            "quantity": ["discharge", "discharge"],
            "source_unit": ["m3/s", "m3/s"],
            "unit": ["m3/s", "m3/s"],
            "value": [1.2, 1.3],
        }
    )

    validate_observation_data(data)


def test_observation_data_schema_rejects_provider_id_column_as_extra() -> None:
    data = _observation_df().with_columns(pl.lit("provider-a").alias("provider_id"))

    with pytest.raises(ObservationDataSchemaError) as exc_info:
        validate_observation_data(data)

    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize("missing_column", ObservationDataSchema.polars_schema.names())
def test_observation_data_schema_rejects_missing_column(missing_column: str) -> None:
    with pytest.raises(ObservationDataSchemaError) as exc_info:
        validate_observation_data(_observation_df().drop(missing_column))

    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize(
    "data",
    [
        _observation_df().with_columns(pl.col("time").cast(pl.Utf8)),
        _observation_df().with_columns(pl.Series("time_zone", [1, 2], dtype=pl.Int64)),
        _observation_df().with_columns(pl.Series("station_id", [1, 2], dtype=pl.Int64)),
        _observation_df().with_columns(pl.Series("product_id", [1, 2], dtype=pl.Int64)),
        _observation_df().with_columns(pl.Series("value", ["1.2", "1.3"], dtype=pl.Utf8)),
    ],
)
def test_observation_data_schema_rejects_wrong_dtype(data: pl.DataFrame) -> None:
    with pytest.raises(ObservationDataSchemaError) as exc_info:
        validate_observation_data(data)

    assert _issue_policy_error_chain(exc_info.value) == []


@pytest.mark.parametrize(
    "data",
    [
        _observation_df(time=[None, datetime(2026, 1, 2)]),
        _observation_df(time_zone=[None, "+00:00"]),
        _observation_df(station_id=[None, "station-1"]),
        _observation_df(product_id=[None, "flow"]),
    ],
)
def test_observation_data_schema_rejects_null_required_columns(data: pl.DataFrame) -> None:
    with pytest.raises(ObservationDataSchemaError) as exc_info:
        validate_observation_data(data)

    assert _issue_policy_error_chain(exc_info.value) == []


def test_observation_data_schema_allows_null_value() -> None:
    data = _observation_df(value=[None, 1.2])

    validate_observation_data(data)


def test_observation_result_constructs_with_exact_field_set() -> None:
    result = _result()

    assert tuple(ObservationResult.model_fields) == (
        "data",
        "provenance",
        "issues",
        "receipts",
        "source_series",
        "inventories",
        "outcomes",
        "supporting_outcomes",
        "scope",
        "view_scope",
    )
    assert result.issues == ()
    assert result.receipts == Receipts(provider_id=ProviderId("provider-a"), entries=())


def test_observation_result_to_polars_returns_data_identity() -> None:
    result = _result()

    assert result.to_polars() is result.data


def test_observation_result_to_pandas_matches_polars_boundary_conversion() -> None:
    result = _result()

    pd_testing.assert_frame_equal(result.to_pandas(), result.data.to_pandas())


def test_observation_result_rejects_schema_violation() -> None:
    with pytest.raises(ObservationDataSchemaError) as exc_info:
        _result(_observation_df().drop("value"))

    assert _issue_policy_error_chain(exc_info.value) == []


def test_versioned_result_bundle_preserves_authored_contract_context_and_binary_receipt() -> None:
    import polars.testing as pl_testing

    import rivretrieve as rr

    # Authored boundary values exercise binary encoding, not a source observation claim.
    result = _result()
    receipt = ReceiptEntry(
        content=b"\x00\xffsource-bytes", origin=_receipt_origin(), authorship=ReceiptAuthorship.PUBLISHER_PAYLOAD
    )
    result = result.model_copy(update={"receipts": Receipts(provider_id=ProviderId("provider-a"), entries=(receipt,))})
    restored = rr.from_bundle(rr.to_bundle(result))
    pl_testing.assert_frame_equal(restored.data, result.data)
    assert restored.source_series == result.source_series
    assert restored.scope == result.scope
    assert restored.receipts.entries[0].content == receipt.content
    assert restored.receipts.entries[0].origin == receipt.origin


def test_result_rejects_a_row_whose_unit_contradicts_its_physical_facts() -> None:
    with pytest.raises(ObservationDataSchemaError, match="admitted source-series facts"):
        _result(_observation_df().with_columns(pl.lit("cm").alias("unit")))


def test_result_rejects_missing_definition_instead_of_inventing_identity() -> None:
    with pytest.raises(ObservationDataSchemaError, match="unknown source-series"):
        ObservationResult(
            data=_observation_df(), provenance=_provenance(), receipts=Receipts(provider_id=ProviderId("provider-a"))
        )


def test_series_inspection_retains_successful_empty_and_unresolved_outcomes_without_rows() -> None:
    import rivretrieve as rr
    from rivretrieve._internal.source_series import OutcomeStatus, RetrievalOutcome, SeriesWindow

    window = SeriesWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2))
    result = ObservationResult(
        data=pl.DataFrame(schema=ObservationDataSchema.polars_schema),
        provenance=_provenance(),
        receipts=Receipts(provider_id=ProviderId("provider-a")),
        source_series=(_series_definition(),),
        outcomes=(
            RetrievalOutcome(
                outcome_id="empty",
                series_id="test-series",
                station_id="station-1",
                product_id="flow",
                window=window,
                status=OutcomeStatus.EMPTY,
                facts_ids=("test-facts",),
            ),
            RetrievalOutcome(
                outcome_id="unresolved",
                series_id=None,
                station_id="station-2",
                product_id="flow",
                window=window,
                status=OutcomeStatus.UNRESOLVED,
                reason="The response did not identify a concrete source series",
            ),
        ),
    )
    inspected = rr.series(result)
    assert inspected["provider_id"].to_list() == ["provider-a", "provider-a"]
    assert inspected.filter(pl.col("series_id") == "test-series")["outcomes"].to_list() == [["empty"]]
    assert inspected.filter(pl.col("series_id").is_null())["outcomes"].to_list() == [["unresolved"]]
    restored = rr.from_bundle(rr.to_bundle(result))
    assert restored.outcomes == result.outcomes


def test_inspection_does_not_attach_current_inventory_or_outcome_to_historical_fact_segment() -> None:
    import rivretrieve as rr
    from rivretrieve._internal.source_series import (
        InventoryCompleteness,
        InventorySnapshot,
        OutcomeStatus,
        RetrievalOutcome,
        SeriesScope,
        SeriesWindow,
    )

    definition = _series_definition()
    current = definition.facts[0]
    historical = current.model_copy(update={"facts_id": "historical-facts"})
    definition = definition.model_copy(update={"facts": (current, historical)})
    window = SeriesWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2))
    inventory = InventorySnapshot(
        snapshot_id="current-inventory",
        scope=SeriesScope(),
        members=(definition.series_id,),
        member_facts=((definition.series_id, (current.facts_id,)),),
        completeness=InventoryCompleteness.COMPLETE,
        access="authored-contract",
        origin="response",
        evidence=("authored-contract",),
        window=window,
    )
    result = ObservationResult(
        data=pl.DataFrame(schema=ObservationDataSchema.polars_schema),
        provenance=_provenance(),
        receipts=Receipts(provider_id=ProviderId("provider-a")),
        source_series=(definition,),
        inventories=(inventory,),
        outcomes=(
            RetrievalOutcome(
                outcome_id="current-empty",
                series_id=definition.series_id,
                station_id="station-1",
                product_id="flow",
                window=window,
                status=OutcomeStatus.EMPTY,
                facts_ids=(current.facts_id,),
            ),
        ),
    )
    inspected = rr.series(result)
    historical_row = inspected.filter(pl.col("facts_id") == "historical-facts")
    assert historical_row["outcomes"].to_list() == [[]]
    assert historical_row["inventory_ids"].to_list() == [[]]
    current_row = inspected.filter(pl.col("facts_id") == current.facts_id)
    assert current_row["outcomes"].to_list() == [["empty"]]
    assert current_row["inventory_ids"].to_list() == [["current-inventory"]]

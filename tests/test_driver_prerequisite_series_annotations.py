"""Regression test for #856: a prerequisite payload with no outcomes of its own must not
lose series-scope annotations it published, once the driver narrows annotations per payload.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl

import rivretrieve._internal.driver as driver_module
from rivretrieve._internal.engine import (
    Instant,
    ObservationRequest,
    Payload,
    ProductConfig,
    ProductWindowDeclarations,
    ProviderConfig,
    RequestedWindow,
    RowsSchema,
    SourceCallOrigin,
    SourceCoordinates,
    StopConvention,
    Unit,
    UnknownOriginFact,
    WindowDeclaration,
    WindowEndpoint,
    WindowGranularity,
    WindowRenderingVocabulary,
    WithIssues,
    ZoneValue,
)
from rivretrieve._internal.observations import ReceiptMode
from rivretrieve._internal.primitives import ProductId, ProviderId
from rivretrieve._internal.source_annotations import (
    SERIES_STRUCTURAL_SCHEMA,
    AnnotationBundle,
    AnnotationField,
    AnnotationSchema,
    AnnotationScope,
    SeriesAnnotationTable,
)
from rivretrieve._internal.source_series import (
    ClippingAxis,
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    ParsedSeries,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
    known,
)
from tests.test_internal_driver import _provenance

_PRODUCT = ProductId("level")
_SERIES_ID = "station-1:level"
_SCHEMA = AnnotationSchema(
    schema_id="test.series",
    provider_id="test",
    scope=AnnotationScope.SERIES,
    fields=(AnnotationField(name="note", dtype="String", description="Synthetic series fact for a regression test."),),
)


def _origin() -> SourceCallOrigin:
    unknown = UnknownOriginFact()
    return SourceCallOrigin(unknown, unknown, unknown, unknown, unknown, unknown, unknown)


def _fact() -> PhysicalFacts:
    return PhysicalFacts(
        facts_id=f"{_SERIES_ID}:facts",
        quantity=known("stage", "test"),
        source_unit=known("m", "test"),
        normalized_unit="m",
        frequency=known("instantaneous", "test"),
        clipping_axis=ClippingAxis.SOURCE_TIMESTAMP,
        label_time=None,
    )


def _series() -> SourceSeries:
    return SourceSeries(
        series_id=_SERIES_ID,
        provider_id="test",
        station_id="station-1",
        product_id=str(_PRODUCT),
        identity=SourceIdentity(namespace="test-source", published_id=_SERIES_ID, origin="response", evidence=("x",)),
        facts=(_fact(),),
    )


def _window() -> SeriesWindow:
    return SeriesWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2))


class _LookupThenFetchProvider:
    """A minimal two-payload stage: a prerequisite lookup with no outcomes of its own
    publishing a series-scope annotation, followed by a child payload that owns the
    real observation outcome and carries no annotation of its own — exactly ar_ina's shape."""

    window_declarations = ProductWindowDeclarations(
        {
            _PRODUCT: WindowDeclaration(
                WindowGranularity("date"), WindowRenderingVocabulary.DATE, StopConvention.INCLUSIVE
            )
        }
    )
    shared_acquisition_products = ()

    def __init__(self) -> None:
        self.config = ProviderConfig(
            zone=ZoneValue("+00:00"),
            products={_PRODUCT: ProductConfig(SourceCoordinates({}), Unit.M, Instant())},
        )

    def fetch(self, stations, products, rendered_windows, window, config, transport, *, scope, known_series):
        station = stations[0]
        lookup = Payload(
            source_coordinates=SourceCoordinates({"kind": "lookup"}),
            station_products=((station, _PRODUCT),),
            fetch_window=window,
            content=b"lookup",
            origin=_origin(),
            prerequisite_calls=(),
        )
        observations = Payload(
            source_coordinates=SourceCoordinates({"kind": "observations"}),
            station_products=((station, _PRODUCT),),
            fetch_window=window,
            content=b"observations",
            origin=_origin(),
            prerequisite_calls=(),
        )
        return WithIssues(value=(lookup, observations))

    def parse(self, payload: Payload, config: ProviderConfig) -> ParsedSeries:
        series = _series()
        scope = SeriesScope(provider_ids=("test",), station_ids=("station-1",), product_ids=(str(_PRODUCT),))
        if payload.content == b"lookup":
            annotation_table = SeriesAnnotationTable.from_rows(
                schema=_SCHEMA,
                rows=pl.DataFrame(
                    [{"series_id": _SERIES_ID, "note": "published by the lookup step"}],
                    schema={**SERIES_STRUCTURAL_SCHEMA, **_SCHEMA.polars_schema()},
                ),
            )
            return ParsedSeries(
                pl.DataFrame(schema=RowsSchema.polars_schema),
                (series,),
                (),
                (),
                (),
                annotations=AnnotationBundle(series_tables={_SCHEMA.schema_id: annotation_table}),
            )
        fact = series.facts[0]
        rows = pl.DataFrame(
            [
                {
                    "station_id": "station-1",
                    "product_id": str(_PRODUCT),
                    "time": datetime(2026, 1, 1, 12),
                    "value": 1.23,
                    "time_zone": "+00:00",
                    "series_id": _SERIES_ID,
                    "facts_id": fact.facts_id,
                    "source_unit": "m",
                }
            ],
            schema=RowsSchema.polars_schema,
        )
        outcome = RetrievalOutcome(
            outcome_id=f"{_SERIES_ID}:outcome",
            series_id=_SERIES_ID,
            station_id="station-1",
            product_id=str(_PRODUCT),
            window=_window(),
            status=OutcomeStatus.SUCCESS,
            facts_ids=(fact.facts_id,),
        )
        inventory = InventorySnapshot(
            snapshot_id=f"{_SERIES_ID}:inventory",
            scope=scope,
            members=(_SERIES_ID,),
            completeness=InventoryCompleteness.COMPLETE,
            access="test source",
            origin="response",
            window=_window(),
            evidence=("test",),
        )
        return ParsedSeries(rows, (series,), (inventory,), (outcome,), ())


def test_outcome_less_prerequisite_payload_keeps_its_own_series_annotation() -> None:
    requested = RequestedWindow(
        WindowEndpoint.from_datetime(datetime(2026, 1, 1)), WindowEndpoint.from_datetime(datetime(2026, 1, 1, 23))
    )
    request = ObservationRequest(ProviderId("test"), ("station-1",), (_PRODUCT,), requested)
    result = driver_module.drive(
        request,
        _LookupThenFetchProvider(),
        provenance=_provenance(request),
        receipts=ReceiptMode.OMIT,
    )
    table = result.annotations.series_tables[_SCHEMA.schema_id]
    assert table.row_count == 1
    assert table.rows["series_id"].to_list() == [_SERIES_ID]
    assert table.rows["note"].to_list() == ["published by the lookup step"]

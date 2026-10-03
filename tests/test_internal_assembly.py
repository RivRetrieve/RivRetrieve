from datetime import UTC, datetime

import polars as pl
import polars.testing as pl_testing

from rivretrieve._internal.assembly import assemble
from rivretrieve._internal.engine import CanonicalRowsSchema, SourceCallOrigin, UnknownOriginFact
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.observations import ObservationProvenance, ReceiptAuthorship, ReceiptEntry, Receipts
from rivretrieve._internal.primitives import ProviderId
from rivretrieve._internal.source_series import (
    InventoryCompleteness,
    InventorySnapshot,
    OutcomeStatus,
    PhysicalFacts,
    RetrievalOutcome,
    SeriesScope,
    SeriesWindow,
    SourceIdentity,
    SourceSeries,
)


def test_assemble_packages_populated_inputs_unchanged() -> None:
    rows = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 2, 23, 30), datetime(2026, 1, 1, 0, 0)],
            "time_zone": ["+09:00", "unknown"],
            "station_id": ["station-b", "station-a"],
            "product_id": ["flow", "stage"],
            "value": [100.0, -2.5],
            "series_id": ["flow-b", "stage-a"],
            "facts_id": ["flow-facts", "stage-facts"],
            "source_unit": ["m3/s", "m"],
            "quantity": ["discharge", "stage"],
            "unit": ["m3/s", "m"],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    expected_rows = pl.DataFrame(
        {
            "time": [datetime(2026, 1, 2, 23, 30), datetime(2026, 1, 1, 0, 0)],
            "time_zone": ["+09:00", "unknown"],
            "station_id": ["station-b", "station-a"],
            "product_id": ["flow", "stage"],
            "value": [100.0, -2.5],
            "series_id": ["flow-b", "stage-a"],
            "facts_id": ["flow-facts", "stage-facts"],
            "source_unit": ["m3/s", "m"],
            "quantity": ["discharge", "stage"],
            "unit": ["m3/s", "m"],
        },
        schema=CanonicalRowsSchema.polars_schema,
    )
    provenance = ObservationProvenance(
        source="live",
        provider_id=ProviderId("provider-a"),
        request={"stations": ["station-b", "station-a"]},
        endpoints=("https://example.invalid/observations",),
        metadata="source metadata",
    )
    first_issue = Issue(
        severity="error",
        code="station_missing",
        message="Station B returned no rows",
    )
    second_issue = Issue(
        severity="info",
        code="unit_converted",
        message="Source unit was converted",
    )
    issues = (first_issue, second_issue)
    content = b"\x00raw-provider-bytes\xff"
    origin = SourceCallOrigin(
        url="https://example.invalid/observations",
        request_parameters={"station": "station-1"},
        status_code=200,
        retrieved_at=datetime(2026, 8, 7, 12, 30, tzinfo=UTC),
        content_type="application/json",
        source_path=UnknownOriginFact(),
        query=UnknownOriginFact(),
    )
    receipts = Receipts(
        provider_id=ProviderId("provider-a"),
        entries=(ReceiptEntry(content, origin, ReceiptAuthorship.PUBLISHER_PAYLOAD),),
    )

    result = assemble(rows, provenance, issues, receipts)

    assert result.canonical_rows is rows
    pl_testing.assert_frame_equal(result.canonical_rows, rows)
    assert result.provenance is provenance
    assert result.issues is issues
    assert result.issues == (first_issue, second_issue)
    assert result.receipts is receipts
    assert result.receipts.entries is receipts.entries
    assert result.receipts.entries[0].content is content
    assert result.receipts.entries[0].origin is origin
    pl_testing.assert_frame_equal(rows, expected_rows)


def test_assemble_packages_empty_inputs_unchanged() -> None:
    rows = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)
    provenance = ObservationProvenance(
        source="live",
        provider_id=ProviderId("provider-empty"),
        request={"stations": ["missing-station"]},
    )
    issue = Issue(
        severity="warning",
        code="empty_window",
        message="No observations were returned",
    )
    issues = (issue,)
    receipts = Receipts(provider_id=ProviderId("provider-empty"))

    result = assemble(rows, provenance, issues, receipts)

    assert result.canonical_rows is rows
    pl_testing.assert_frame_equal(result.canonical_rows, rows)
    assert result.canonical_rows.schema == CanonicalRowsSchema.polars_schema
    assert result.canonical_rows.height == 0
    assert result.provenance is provenance
    assert result.issues is issues
    assert result.issues == (issue,)
    assert result.receipts is receipts
    assert result.receipts.entries == ()
    assert result.scope == SeriesScope()


def test_assemble_preserves_concrete_series_inventory_outcomes_and_scope_identity() -> None:
    rows = pl.DataFrame(schema=CanonicalRowsSchema.polars_schema)
    provenance = ObservationProvenance(source="live", provider_id=ProviderId("provider"))
    receipts = Receipts(provider_id=ProviderId("provider"))
    scope = SeriesScope(provider_ids=("provider",), station_ids=("station",), product_ids=("level",))
    series = (
        SourceSeries(
            series_id="series",
            provider_id="provider",
            station_id="station",
            product_id="level",
            identity=SourceIdentity(
                namespace="test-source", published_id="source-id", origin="response", evidence=("source payload",)
            ),
            facts=(PhysicalFacts(facts_id="facts"),),
        ),
    )
    window = SeriesWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2))
    inventories = (
        InventorySnapshot(
            snapshot_id="inventory",
            scope=scope,
            members=("series",),
            completeness=InventoryCompleteness.COMPLETE,
            access="test endpoint",
            origin="response",
            window=window,
            evidence=("source response",),
        ),
    )
    outcomes = (
        RetrievalOutcome(
            outcome_id="unsupported",
            series_id="series",
            station_id="station",
            product_id="level",
            window=window,
            status=OutcomeStatus.UNSUPPORTED,
            reason="Source unit is not established",
        ),
    )
    result = assemble(
        rows, provenance, (), receipts, source_series=series, inventories=inventories, outcomes=outcomes, scope=scope
    )
    assert result.source_series is series
    assert result.inventories is inventories
    assert result.outcomes is outcomes
    assert result.scope is scope
    assert result.canonical_rows is rows

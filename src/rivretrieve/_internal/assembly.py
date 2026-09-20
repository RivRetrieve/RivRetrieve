"""assemble : CanonicalRows × ObservationProvenance × tuple[Issue, ...] × Receipts → _AssemblyResult (pure)."""

from __future__ import annotations

from dataclasses import dataclass

from rivretrieve._internal.engine import CanonicalRows
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.observations import ObservationProvenance, Receipts
from rivretrieve._internal.source_series import InventorySnapshot, RetrievalOutcome, SeriesScope, SourceSeries


@dataclass(frozen=True, slots=True)
class _AssemblyResult:
    canonical_rows: CanonicalRows
    provenance: ObservationProvenance
    issues: tuple[Issue, ...]
    receipts: Receipts
    source_series: tuple[SourceSeries, ...] = ()
    inventories: tuple[InventorySnapshot, ...] = ()
    outcomes: tuple[RetrievalOutcome, ...] = ()
    scope: SeriesScope = SeriesScope()


def assemble(
    canonical_rows: CanonicalRows,
    provenance: ObservationProvenance,
    issues: tuple[Issue, ...],
    receipts: Receipts,
    *,
    source_series: tuple[SourceSeries, ...] = (),
    inventories: tuple[InventorySnapshot, ...] = (),
    outcomes: tuple[RetrievalOutcome, ...] = (),
    scope: SeriesScope | None = None,
) -> _AssemblyResult:
    return _AssemblyResult(
        canonical_rows=canonical_rows,
        provenance=provenance,
        issues=issues,
        receipts=receipts,
        source_series=source_series,
        inventories=inventories,
        outcomes=outcomes,
        scope=scope or SeriesScope(),
    )

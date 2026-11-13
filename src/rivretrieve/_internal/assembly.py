"""assemble : CanonicalRows × ObservationProvenance × Receipts → ObservationResult inputs."""

from __future__ import annotations

from dataclasses import dataclass, field

from rivretrieve._internal.engine import CanonicalRows
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.observations import ObservationProvenance, Receipts
from rivretrieve._internal.source_annotations import AnnotationBundle
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
    supporting_outcomes: tuple[RetrievalOutcome, ...] = ()
    annotations: AnnotationBundle = field(default_factory=AnnotationBundle.empty)


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
    supporting_outcomes: tuple[RetrievalOutcome, ...] = (),
    annotations: AnnotationBundle | None = None,
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
        supporting_outcomes=supporting_outcomes,
        annotations=annotations if annotations is not None else AnnotationBundle.empty(),
    )

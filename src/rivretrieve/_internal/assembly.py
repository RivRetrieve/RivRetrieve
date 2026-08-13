"""assemble : CanonicalRows × ObservationProvenance × tuple[Issue, ...] × Receipts → _AssemblyResult (pure)."""

from __future__ import annotations

from dataclasses import dataclass

from rivretrieve._internal.engine import CanonicalRows
from rivretrieve._internal.issues import Issue
from rivretrieve._internal.observations import ObservationProvenance, Receipts


@dataclass(frozen=True, slots=True)
class _AssemblyResult:
    canonical_rows: CanonicalRows
    provenance: ObservationProvenance
    issues: tuple[Issue, ...]
    receipts: Receipts


def assemble(
    canonical_rows: CanonicalRows,
    provenance: ObservationProvenance,
    issues: tuple[Issue, ...],
    receipts: Receipts,
) -> _AssemblyResult:
    return _AssemblyResult(
        canonical_rows=canonical_rows,
        provenance=provenance,
        issues=issues,
        receipts=receipts,
    )

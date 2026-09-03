# ADR-0026: One bulk publication may contain several publisher artifacts

## Status

Accepted

## Context

IMGW publishes daily hydrology as twelve monthly ZIP archives through hydrological year 2022 and as one annual ZIP from 2023. Compiling only the current calendar year drops the historical source. Compiling each archive into the same destination in sequence atomically replaces earlier data and leaves provenance naming only the last archive. Wrapping the files in a RivRetrieve-created archive would mislabel constructed bytes as publisher evidence.

## Decision

The existing `BulkStore` kind remains a provider-declared download and compile. Its download result and compile request carry a non-empty ordered tuple of exact publisher artifacts. A store compiled from several artifacts records every exact URL and SHA-256 in that order. A one-artifact store retains the singular spelling. Certification checks every input before decoding, performs one combined staged write and read-back, publishes once, and deletes inputs only after validation.

IMGW owns only its publication vocabulary: monthly URLs before 2023, annual URLs from 2023, and the hydrological-month calendar mapping present in each row. The shared bulk composition root owns transfer effects and the compiler/store layer owns the atomic combined publication. Each URL is bound to its exact official publication template and hydrological interval. Planned intervals must be ordered and disjoint. Overlapping coverage or cross-artifact row identity is ambiguous and is refused; duplicates within one publisher artifact remain unchanged.

## Consequences

No archive can disappear from store provenance. A failed transfer or compile cannot expose a partial historical store. Existing Canada and other one-artifact stores remain readable. Revision 2 binds the store to its provider id and accepts exactly one of `publisher_artifact` or non-empty `publisher_artifacts`; readers normalize both to an ordered tuple.

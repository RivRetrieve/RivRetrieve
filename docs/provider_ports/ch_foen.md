# ch_foen Provider Port Notes

These notes capture pain points from the `ch_foen` reference provider port. They are not provider porting rules. Promote a point to [architecture.md](../../architecture.md) only when it affects shared harness contracts, types, boundaries, or implementation expectations.

## Summary

- Provider ID: `ch_foen`
- Display name: Switzerland FOEN/BAFU
- Purpose: full reference provider port used to validate the harness and seed architecture feedback
- Status: not started

This file should be updated while implementing the harness and porting `ch_foen`. It is evidence for architecture changes, not a substitute for them. Provider-specific findings stay here; shared harness implications should be promoted to [architecture.md](../../architecture.md).

## Source Endpoints and Artifacts

Record source APIs, files, archives, documentation pages, credentials, rate limits, and terms of use discovered during the port.

## Catalogue Mapping Pain Points

Record issues mapping provider station, product, and station-product metadata into the common catalogue envelopes.

Questions to capture:

- Which common fields were ambiguous or unavailable?
- Which provider metadata fields needed typed models?
- Which original fields were difficult to preserve faithfully?
- Did packaged and live catalogue sources expose different shapes?

## Live Metadata Pain Points

Record issues with `source="live"` catalogue retrieval.

Questions to capture:

- Which live catalogue calls are supported?
- Which calls are unsupported and why?
- Were provider responses partial, paginated, unstable, or slow?
- What provenance is needed to make live catalogue results auditable?

## Product Dictionary Pain Points

Record issues mapping native variables, parameters, measures, or time-series IDs to canonical product IDs.

Questions to capture:

- Which native products matched canonical IDs?
- Which native products need provider-specific IDs?
- Which additions or revisions should be proposed in `docs/product_dictionary.md`?
- Were time semantics, period anchors, or units ambiguous?

## Observation Retrieval Pain Points

Record issues retrieving and normalizing observations.

Questions to capture:

- Which APIs are used for recent/realtime data?
- Which APIs are used for historical data?
- Did a request need to stitch multiple APIs?
- Were there gaps, overlaps, conflicts, duplicated timestamps, or timezone ambiguities?
- Which unit conversions were required?

## Annotation and Provenance Pain Points

Record provider-native row and series annotations needed for auditability.

Questions to capture:

- Which row annotations are required?
- Which series annotations are required?
- Which source/API facts belong in provenance rather than annotations?
- Were quality or provisional-status fields available?
- Were alternative overlapping values preserved when source APIs disagreed?

## Issues and Error Policy Pain Points

Record recoverable and fatal problems encountered during the port.

Questions to capture:

- Which provider failures should become structured issues?
- Which failures should raise immediately?
- Did `on_issue="warn" | "raise" | "ignore"` fit the observed cases?
- Were missing stations, products, empty intervals, or partial responses expressible as structured issues?

## Harness Changes Proposed

Use this section for concrete proposed changes to shared architecture or harness types.

Each proposal should include:

```text
Problem:
Provider evidence:
Proposed architecture change:
Alternative considered:
Status: proposed | accepted | rejected | deferred
```

## Open Questions

Track unresolved questions that need maintainer or domain review.

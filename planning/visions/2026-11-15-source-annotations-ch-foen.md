# Source annotations: ch_foen

Preserve BAFU's published observation and series annotations for the existing
`ch_foen` routes so users can inspect them without recovering original API
responses from receipts. Reuse the shared source-annotation design rather than
introducing a Swiss-specific API or quality ranking.

This vision delivers [Effort #816](https://github.com/RivRetrieve/RivRetrieve/issues/816)
under [Program #809](https://github.com/RivRetrieve/RivRetrieve/issues/809).
Implementation completes #816 only after the supported-route audit, integration,
and genuine-source verification are complete. Publishing this vision leaves
that work open. The core dependency #812 landed in #831; the completed
[Canadian adoption #814](https://github.com/RivRetrieve/RivRetrieve/issues/814)
in #834 provides another provider migration example, not evidence of Swiss
source meanings.

## Outcome and established design

Retain archive `releaseState` and recent `releaseStatus` in separate route
annotation schemas. Preserve source field names, native types and published
values. Explicit null, code `0`, and a field that does not apply to a route must
remain distinguishable. BAFU's documented equivalence of null and zero as raw
status is not permission to replace one with the other.

Follow the [approved Program decisions](https://github.com/RivRetrieve/RivRetrieve/issues/809#issuecomment-6860795374)
and [core vision](2026-11-13-source-annotations-core-and-usgs.md):

- Keep default `result.data`, `result.to_polars()` and `rr.series(result)` schemas
  unchanged. Expose annotations through the existing `annotations=` convention
  on Polars and pandas projections and through `rr.annotations(result)`.
- Provide field discovery with verified short descriptions and official source
  references. Direct schema-table access must avoid cross-route null padding
  being mistaken for a source-published null.
- Preserve annotations and their associations through clipping, `pick`, `to_utc`,
  offline cache reuse, manual refresh, and bundle export/import. Successful
  refresh can replace statuses even when values are unchanged; failed refresh
  must preserve held data under the shared coverage rules.
- Keep non-identity series attributes at series grain where the audit establishes
  them. Stream selectors remain in `SourceSeries.variant`. Do not invent interval
  annotation tables or move observation flags into the station catalogue.
- Preserve annotations on source-published null-value rows. Keep null values,
  absent rows and failed requests distinct; do not manufacture missing rows.
- Do not translate codes into a cross-provider quality score, automatically
  filter observations, or select preferred series using release status.

## Source audit and implementation context

At authoring, `official_fetch.py` requests `releaseState` for archive routes and
`releaseStatus` for `data_live`, but `official_parse.py` does not carry either
field into parsed output. `official_series.py` contains release-status vocabulary
and a misleading comment claiming the fields are retained in rows. The provider
page correctly describes their current absence from returned and cached rows.
Update these descriptions with the delivered behavior.

Audit the official BAFU routes already supported by `ch_foen` for any other
observation or series annotations. The two requested release fields are a
confirmed starting point, not a completed field inventory. Establish each
candidate's grain, native type, applicability and source description before
integrating it. Record justified inclusions and exclusions in the existing
private provider research record. Follow the
[provider port guide](../../docs/maintenance/provider-ports.md) and reuse existing
retained evidence and correspondence where applicable.

Every shipped annotation field requires a verified description and official
reference. Exhaustive in-library dictionaries for every code are unnecessary.
Do not invent meanings for unresolved source wording, including `ersetzt`, or
infer replacement lineage from it. An unresolved required source fact must be
reported as a blocker for the affected capability, not silently guessed or
omitted to declare the issue complete.

Keep the effort limited to annotation adoption for existing products and routes.
Do not expand product coverage, reinterpret temporal support, change units,
combine archive and recent streams, or change variant selection. Station metadata
remains separate under #602. The supported-route audit can establish additional
annotation fields within this boundary without reopening the shared design.

Use the current shared annotation contracts and existing provider examples.
Exact schema identifiers, parser construction and focused test organization
remain implementation choices. Retire QC-only informational issues if the audit
finds any that become redundant, while preserving retrieval and provenance
failures and diagnostics.

## Evidence of completion

Use the [testing guide](../../docs/maintenance/testing.md) to protect named
behavior at the simplest sufficient level, extending shared coverage rather
than duplicating the entire engine suite. Demonstrate:

- Both archive and recent release fields survive parsing and public annotation
  inspection with correct native values, including explicit null and zero.
- Mixed-route results preserve field applicability through separate schemas;
  published null-value rows retain their annotations and correct associations.
- Annotation discovery, opt-in projection, window clipping, selection, UTC
  conversion, cache reuse, status-only refresh and bundles preserve the supported
  fields. Failed requests do not erase held annotations.
- Additional fields adopted from the audit satisfy their verified grain and
  source contracts. Default observation schemas and existing series identities
  remain unchanged.

Run affected source-independent checks, formatting, lint and type checks through
`uv`, using temporary cache and store roots. Verify applicable archive and recent
paths against genuine retained inputs through the private verification-evidence
archive, following the [evidence guide](../../docs/maintenance/evidence.md).
Review exact code and archive revisions before controlled execution. Missing
mandatory evidence blocks acceptance; synthetic fixtures and live probes do not
replace it. Keep controlled material and credentials out of public artifacts.

Update [the Swiss provider page](../../docs/providers/ch_foen.md) with a verified
practical annotation example, field meanings and limits, following documentation
guidance. Link general annotation usage rather than duplicating API documentation.
Report the completed field audit, checks and remaining source limitations in the
implementation handoff. No Swiss source certification has been performed merely
by publishing this vision.

# Poland gauge-zero elevation and vertical references

Expose Poland's existing gauge-zero heights and their published vertical references
through `rr.metadata`, using the current elevation role and aligned summary lists.
This addresses the missing metadata described in [#513](https://github.com/RivRetrieve/RivRetrieve/issues/513)
without another API redesign. It follows the metadata presentation work in #484
and #490 and the later source-faithful presentation corrections.

## Evidence and meaning

Poland's `STATION_METADATA_FIELDS` in
`src/rivretrieve/_internal/providers/pl_imgw/origins.py` currently exposes only
`area`, with its established square-kilometre unit. The retained native table
already contains `gauge_altitude` as strings, but it has no vertical-reference
column. Consequently, the metadata source view reports `no_metadata` for elevation
at all 1,301 Polish gauges.

Discovery inspected the private verification archive at revision
`902f211f1a8a06e6a6dacdaf8a328f9093215aab` and retrieved these exact collections
through its reviewed, integrity-checking retrieval tool:

- `pl_imgw-grdc-workbook-2026-10-04-v1`: the retained GRDC workbook.
- `pl_imgw-2026-09-29-v1`: the retained native comparison table.

The workbook is `Metadata_GRDC_30.10.2025.xlsx`, with SHA-256
`dfab6ea7de80fb1570f4a8dded8743ed7c7dcb4eb67fe75e2c0e02e9b964b7bf`
and size 116,301 bytes. These match its existing public provenance identity.
Its height header explicitly identifies gauge-zero height in metres above sea
level. An adjacent vertical-reference column supplies the reference for each row:

| Published reference | Station count |
| --- | ---: |
| `EVRF2007` | 851 |
| `Kronsztadt` | 390 |
| `ND` | 60 |

The workbook and native table have the same 1,301 unique station identifiers.
All 1,241 numerical heights agree after standard Excel numeric decoding, and all
60 native `ND` entries match the workbook. The 60 height placeholders coincide
with the 60 reference placeholders. Independent inspection confirmed the column
meanings and row-wise reference association.

Excel's internal numerical serialization is not the same as the existing native
string spelling. Preserve the native strings rather than rewriting them from the
workbook. Discovery found differences in raw decimal serialization of at most
6e-14, while all numerical values compared equal as decoded floating-point values.
This is evidence for a precise reconciliation rule, not permission to introduce
an arbitrary tolerance or change published values.

The earlier suggestion in #484 to attach EVRF2007 throughout Poland is incorrect.
The workbook provides two named references and placeholders. Keep those distinctions.
Gauge-zero height does not describe ground elevation. These station metadata do
not establish which reference applies to historical water-level observations.

## Settled scope

Expose `gauge_altitude` under the existing `elevation` role in the source view and
in the aligned `elevation_field`, `elevation_value`, `elevation_unit` and
`elevation_datum` summary lists. Establish the metre unit from the workbook and
retain its per-station vertical-reference labels. Preserve `EVRF2007`, `Kronsztadt`
and `ND` exactly; do not translate labels, turn placeholders into nulls, assign a
single datum, or convert heights between references.

Retain the vertical-reference information needed for reproducible catalogue
construction and associate it with the matching station and height. Use the
existing metadata, provenance and evidence mechanisms. The implementing agent
may choose the storage and mapping details; no new public columns or parallel
evidence framework are required.

Keep the existing elevation strings and scalar type, including numeric spelling,
trailing zeros and placeholders. Preserve the established distinctions between
values, source nulls and absent metadata. Update the private review and genuine-input
checks, public source declarations, packaged metadata and necessary supporting
catalogue artifacts for this narrowly scoped adoption.

The workbook remains later corroboration of the recovered inventory. It does not
become the proven original acquisition behind the historical import. Record the
new datum support under its actual retained source identity. Do not rewrite
historical provenance to imply that the datum was retained in the old native table.

The following are excluded:

- Horizontal CRS and coordinates, including the forwarded coordinate discussion.
- Station names, water-body names, drainage-area changes and other new fields.
- Austria, other providers and broader metadata refactoring.
- Observation retrieval, stage conversion, datum shifts or derived water-surface
  elevations. No historical applicability is inferred.

## Publication authority and private material

The repository owner stated that they believe they have permission to publish
these values. They authorized this vision's publication after the summary included
both heights and vertical-reference labels. Record this as the owner's scoped
confirmation, not a source-issued licence or an independently verified grant.
The workbook itself contains no redistribution statement, and neither its retention
nor the previous area-only approval establishes broader redistribution rights.

The prior private review withholds elevation because original support and
publication authority were unestablished. Update that decision with the retained
workbook evidence and the scoped owner confirmation. Do not describe the workbook
or forwarded coordinate email as a licence, invent permission wording, or claim
that original correspondence has been recovered. The forwarded email is not an
input to this change.

Keep the workbook, correspondence, detailed source outputs and restricted receipts
out of public repositories, logs, fixtures and distributions. Publish only the
approved metadata and safe support references. No new permission to redistribute
the complete workbook or adopt other fields is granted.

## User documentation

Add a concise station-metadata section to `docs/providers/pl_imgw.md`. Explain
that metadata supplied through GRDC describe gauge-zero height in metres, with
per-station vertical references `EVRF2007`, `Kronsztadt` or the source placeholder
`ND`. Explain the distinction from ground height and the limit on using these
values with historical water-level observations. Link to the shared metadata
guide for general API usage rather than duplicating it.

Keep private correspondence, archive mechanics and verification internals out of
the provider page. Leave its coordinate and CRS statements unchanged. Update other
user documentation only where necessary for accuracy.

## Acceptance

- Reproducible genuine-input checks verify the exact workbook, its height and
  reference headers, complete station correspondence, all height values and all
  per-station reference associations. Use a documented numeric-decoding rule while
  separately proving that native value strings remain unchanged.
- Source and summary views expose the same adopted elevation information for all
  1,301 gauges. Check both named references and the 60 paired `ND` placeholders,
  list alignment, string scalar types, units and support links.
- Before-and-after comparisons prove that existing native height strings,
  drainage areas, station identities, canonical geometry, products, series and
  observation behaviour remain unchanged. New reference support and necessary
  metadata/provenance additions are expected.
- Focused regressions detect an omitted elevation mapping, a blanket EVRF2007
  assignment, incorrect station joins, placeholder loss and value reformatting.
  Extend existing contracts at the simplest sufficient level.
- Run affected source-independent tests and applicable full genuine-input checks
  against explicitly reviewed public and private revisions, following
  `docs/maintenance/evidence.md`. Discovery inspection is not implementation
  acceptance. Missing mandatory evidence blocks acceptance; synthetic inputs do
  not replace the retained workbook.
- Approved products work offline. Review distribution contents and generated
  provenance for disclosure. The Poland provider page accurately describes the
  returned metadata and its limits.

Keep the change proportional to one provider's elevation metadata. This vision
authorizes no broader source adoption or hydrological product.

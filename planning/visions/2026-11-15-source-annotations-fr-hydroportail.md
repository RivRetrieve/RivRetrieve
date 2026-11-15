# Source annotations: fr_hydroportail

Expose HydroPortail's published observation and series annotations through the
existing source-annotation API so users can inspect them without parsing raw
receipts. Preserve source vocabulary and values without inventing a quality
ranking or filtering observations.

This vision delivers [Effort #817](https://github.com/RivRetrieve/RivRetrieve/issues/817)
under [Program #809](https://github.com/RivRetrieve/RivRetrieve/issues/809).
Implementation completes #817 only after the supported-route field audit,
integration and genuine-source verification are complete. Publishing this vision
leaves that work open. The shared dependency #812 landed in #831. The
[Swiss vision](2026-11-15-source-annotations-ch-foen.md) provides a parallel
adoption scope; completed USGS (#813) and Canadian (#814) implementations provide
working examples, not evidence of HydroPortail source meanings.

## Outcome and settled design

Expose per-observation `s`, `q`, `m` and `c` as typed source annotations. Preserve
the source field names, native types, values and associations, including
annotations on source-published null-value rows. Establish field applicability
from source evidence rather than treating an absent field as an explicit null.
Keep null observations, absent rows and failed requests distinct; do not
manufacture missing observations.

Keep the four `statusData` selectors (`raw`, `validated`,
`pre_validated_and_validated`, `most_valid`) in `SourceSeries.variant` with their
existing separate identities. The selector chooses a source stream; point `s`
describes an individual observation. A `most_valid` request does not establish
that every returned observation is validated. Do not infer its selection
algorithm, rank status codes numerically, merge overlapping variants, or create
new variants for annotation changes.

Follow the [approved Program decisions](https://github.com/RivRetrieve/RivRetrieve/issues/809#issuecomment-6860795374)
and [core vision](2026-11-13-source-annotations-core-and-usgs.md):

- Keep default `result.data`, `result.to_polars()` and `rr.series(result)` schemas
  unchanged. Reuse `annotations=` on Polars and pandas projections and
  `rr.annotations(result)` for field discovery and direct schema-table access.
- Give every shipped field a verified short description and official source
  reference. Preserve native types without normalized quality labels or wrapper
  structs. Exhaustive in-library dictionaries for every code are unnecessary.
- Preserve annotations through clipping, `pick`, `to_utc`, offline cache reuse,
  manual refresh and bundle export/import. Successful refresh can replace flags
  even when values are unchanged; failed requests must preserve held data under
  the shared coverage rules.
- Retain verified non-identity series attributes at series grain. Do not duplicate
  stream selectors as a replacement for series identity, invent interval
  annotation tables, or put observation annotations in the station catalogue.

## Source audit and implementation context

At authoring, `src/rivretrieve/_internal/providers/fr_hydroportail/parse.py`
reads observation `t` and `v` and drops `s`, `q`, `m` and `c`. It already checks
station, metric, selector, unit, instantaneous title prefix and UTC envelope
metadata, including empty responses. Preserve these contracts. The provider
supports station-own instantaneous discharge and stage through the public station
series route, with four selectors for each quantity.

The [earlier HydroPortail vision](2026-09-21-hydroportail-source-published-variants.md#source-evidence-and-limits)
records published-script findings: `s` is processing status, `q` qualification,
`m` method and `c` continuity. In particular, do not inherit the word
“correction” for `c` from the earlier Program discussion. Reverify these bindings
against official evidence before shipping descriptions. Earlier bounded windows
did not establish every point-status value or the general `most_valid` algorithm.
A help-page request during this discussion returned HTTP 403; this is an access
limitation of that request, not evidence that official descriptions do not exist.

Audit observation and series payloads on the existing supported routes for other
omitted source fields. The four point codes are a starting inventory, not a claim
that the audit is complete. Establish each candidate's grain, native type,
applicability, null/absence behavior and official description before integrating
it. Existing identity, physical and time envelope fields do not automatically
become annotations because they are not repeated in the observation table.
Record justified inclusions and exclusions in the existing private provider
research record, following the [provider port guide](../../docs/maintenance/provider-ports.md).
Reuse retained evidence and earlier research where applicable, while keeping
historical findings distinct from current verification.

Unresolved required source facts block the affected capability. Do not guess
meanings, ship placeholder descriptions or silently omit a required field to
claim completion. Report material blockers for a scope decision if they cannot
be resolved. Exact schema identifiers, parser construction and focused test
organization remain implementation choices under the current shared contracts.

## Boundaries

Keep this effort limited to annotation adoption for the existing station-own
instantaneous discharge and stage routes and their four selectors. Do not add
site-combined records, authenticated exports, corrected-only or pre-validated-only
histories, new products, aggregation or observation-status filtering APIs.
Preserve existing units, time semantics, retrieval scope and variant selection.
Station metadata remains separate under #602. Do not substitute Hub'Eau routes or
transfer their source meanings or terms to HydroPortail.

Retire QC-only informational issues if the audit finds any made redundant by
annotations. Preserve retrieval, structural, coverage and provenance diagnostics,
including the existing unresolved licence and citation notices. Annotation work
does not establish reuse rights.

## Evidence of completion

Use the [testing guide](../../docs/maintenance/testing.md) to protect named
behavior at the simplest sufficient level, extending shared coverage rather than
duplicating the entire engine suite. Demonstrate:

- Adopted fields survive parsing and public annotation inspection with their
  native values and verified applicability across discharge, stage and the four
  selectors. Preserve annotations on published null-value rows and maintain
  correct associations when variant values overlap or timestamps differ.
- Field discovery, opt-in projections, clipping, selection, UTC conversion,
  offline cache reuse, status-only refresh and bundles preserve annotations.
  Failed requests do not erase held annotations or hide independent successes.
- Additional fields found by the audit satisfy their verified grain and source
  contracts. Default observation schemas and existing series identities remain
  unchanged; empty results remain distinct from failures.

Run affected source-independent checks, formatting, lint and type checks through
`uv`, using temporary cache and store roots. Verify applicable supported paths
against genuine retained inputs through the private verification-evidence archive,
following the [evidence guide](../../docs/maintenance/evidence.md). Review exact
code and archive revisions before controlled execution. Missing mandatory evidence
blocks acceptance; synthetic fixtures and live probes do not replace it. Keep
controlled material and credentials out of public artifacts. Report the completed
field audit, verification results and remaining source limitations.

Update [the HydroPortail provider page](../../docs/providers/fr_hydroportail.md)
with a verified practical annotation example, field meanings and limits, following
documentation guidance. Explain the difference between the requested selector and
point annotations. Link general annotation usage instead of duplicating API
documentation. No HydroPortail source certification has been performed merely by
publishing this vision.

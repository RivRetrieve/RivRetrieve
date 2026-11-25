# Chile verification

Verify that the completed Chile integration faithfully exposes DGA's historical
daily discharge and monthly mean discharge through RivRetrieve's public APIs.
Deliver source-verification evidence and a ten-basin CAMELS-CL comparison, with
numerical investigation by the agent and visual review by the maintainer.

This is [Step 6, #742](https://github.com/RivRetrieve/RivRetrieve/issues/742) of
[the Chile Program](https://github.com/RivRetrieve/RivRetrieve/issues/734).
Completing the verification and resolving the maintainer's visual-review concerns
completes #742. Publishing this vision does not complete it. Work and corrections
remain on `port/cl-dga`; user documentation (#737) and final review (#738) remain
separate. Thiago (@thiagovmdon) must approve the final port before merge to `main`.

## Starting point

Use the [Step 5 handoff](https://github.com/RivRetrieve/RivRetrieve/issues/741#issuecomment-7015509582)
and the continuing private research record in `verification-evidence`,
`research/cl-dga-source-access.md`. Step 5 integrated both historical products at
`0b0349de1223a1ee62dfcc0f4d5768233f64bb02`, with genuine-input verification recorded
in `RivRetrieve/verification-evidence#109`. Those checks are supporting evidence,
not a substitute for this effort's complete verification.

The selected source is the direct DGA national historical ZIP publication on
`https://mapas2.mop.gob.cl/`, not CR2 retrieval. The retained snapshot contains
784 stations and data spanning 1960–2026; these are observations, not fixed future
counts or promises of continuous station coverage. Both products use m³/s.
Daily statistic and time-zone facts remain unknown; monthly statistic is mean.
The source publication date remains explicitly unknown (`source_vintage=None`).
Preserve duplicate daily records, including conflicting values, genuine zeros,
leading-zero station identifiers, gaps, and the published monthly product.
Do not reconstruct the monthly product or invent missing source semantics.

## Verify the integration

Follow [provider-port step 6](../../docs/maintenance/provider-ports.md), the
[testing guide](../../docs/maintenance/testing.md), and the
[evidence guide](../../docs/maintenance/evidence.md). Use the existing private
archive process, not another verification framework. Review exact library and
archive revisions before running code with private evidence. Retain controlled
inputs, detailed outputs and receipts outside public repositories and artifacts;
share only reviewed safe summaries.

Verify both products against genuine original source material using independently
established expectations. Check source identity, date or month labels, values,
duplicate multiplicity, and preservation of source unknowns together. Cover
calendar-month selection, year boundaries, empty selections, and relevant
store/cache and refresh behavior. Extend existing shared contracts where needed,
including catalogue rebuild and installed-distribution checks; do not duplicate
already adequate coverage. Follow test-first guidance for any code corrections.

Observe a fresh download → compile → public-API retrieval path with isolated store
and cache roots. Distinguish that live observation from retained-input replay,
source certification and source-independent tests. Preserve exact acquisition
identities if the current publication differs from the retained snapshot.

Check historical depth separately from CAMELS overlap. Establish the sampled
stations' available history from the selected publication and any published
station-specific earliest-result metadata, and retrieve near the historical edge
for at least one long-running station. Do not infer that CAMELS date limits are
DGA source limits or expand into deferred routes to obtain older data.

## Ten-basin CAMELS-CL comparison

Use [CAMELS-CL](https://doi.pangaea.de/10.1594/PANGAEA.894885), retaining its exact
version and source references. The Program reports 507 of 516 gauges matching the
DGA snapshot; revalidate confident station identity and overlapping dates before
selection. Select exactly ten eligible basins reproducibly at random, without
selecting for agreement. Record the candidate population, matching and eligibility
rules, random selection method and seed, chosen stations, and date windows.
Fewer than ten suitable matches is a blocker, not permission to reduce the sample.

Retrieve the compared DGA values through RivRetrieve's public API. Compare on
published date labels without assuming a time zone or daily-mean interpretation.
Use explicit units and conversions, preserve gaps and duplicates, and do not
shift dates, fit values, fill gaps, deduplicate, or filter discrepancies away to
improve agreement. Keep ambiguous duplicate-date comparisons visible rather than
silently choosing one value.

The agent owns numerical analysis: examine date overlap, missing rows and values,
duplicate dates, absolute and relative differences, and systematic bias. Handle
zero flows explicitly when reporting relative differences. Investigate meaningful
discrepancies against original source evidence. Rounding and historical revisions
are possible explanations, not established causes without evidence. Choose useful
metrics and investigation thresholds transparently; no numerical agreement target
should cause values or sample selection to be altered.

CAMELS-CL derives its streamflow from DGA through CR2. This is a consistency check
of retrieval and processing, not independent measurement validation, and does not
replace direct source verification. Keep unresolved source meanings explicit.
Report unexplained differences and their consequences rather than automatically
calling them integration defects or treating them as harmless.

## Figures and human review

Produce paired hydrographs for all ten sampled basins with clear station identity,
dates, units, legends, and preserved gaps. Retain the figures with the selection,
method, numerical results, findings and limitations through the existing evidence
process. Provide readable views without concealing discrepancies.

When ready, open the figures for the maintainer to inspect; merely saving paths
is not the requested handoff. Use a local viewer or another permitted display that
does not disclose controlled material. If opening is unavailable, report that
limitation and provide accessible local paths without claiming they were opened.

The maintainer personally reviews the hydrographs and communicates suspicious
patterns. The agent investigates numerics and follows up on those concerns.
Keep #742 open while awaiting the maintainer's explicit visual-review confirmation
and resolution of any concerns. Numerical checks do not substitute for this review.

## Completion and boundaries

Deliver an account of exact reviewed revisions, selected evidence, completed checks,
comparison results, investigated discrepancies, remaining limitations, and the
maintainer's visual-review outcome. Missing mandatory evidence blocks acceptance;
a skipped or unavailable check is not a pass. Any suspected integration defect or
misleading comparison must be resolved or explicitly returned as a blocker, not
hidden by an aggregate score.

Do not expand to CR2 retrieval, regional downloads, Hidrolínea telemetry, stage,
temperature, new source interpretations, or a new verification system. Leave
reversible plotting, metric and test-organization choices to the implementing
agent. Return to the maintainer if findings require a material scope change.

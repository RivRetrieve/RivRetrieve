# USGS complete integration verification

Verify the complete supported USGS integration against genuine source evidence,
with an additional CAMELS-US comparison for daily mean discharge. This delivers
[verification effort #626](https://github.com/RivRetrieve/RivRetrieve/issues/626)
in [Program #624](https://github.com/RivRetrieve/RivRetrieve/issues/624).
Completing this vision completes #626; publishing it does not.

## Supported scope

Cover all six existing products: daily mean discharge; daily mean, maximum and
minimum stage; continuous discharge; and continuous stage. Preserve the established
50-state-plus-DC scope, non-stream and continuous-only locations, and retained
Canadian daily stations and historical identities. A station or series being
listed does not establish observations for every date or scientific suitability.

Produce one consolidated acceptance assessment for the delivered revision.
Verify source identities, physical meanings, units and conversions, timestamps
and values together, using independently established expectations. Cover catalogue
coverage and lineage, public discovery and retrieval, relevant cache behavior,
receipts, and distribution contents. Use existing shared contracts and the
all-provider catalogue rebuild rather than creating a separate verification system.

Exercise distinct supported routes and relevant source differences with genuine
retained responses. Preserve sibling series, published nulls, absent rows, empty
responses and failed requests as distinct states. Check pagination and partition
boundaries, partial results and incomplete-cache protection where relevant.
Daily date labels must not acquire an inferred time zone or support interval;
continuous observations retain established offset semantics. Cache reuse retains
original provenance with labelled store excerpts; this work does not require
adding storage of original response bytes to the cache.

## Additional daily-discharge comparison

Use the prepared CAMELS-US dataset at
`/Users/nicolaslazaro/Desktop/work/hydrologeez/data/camels-us/prepared`.
Establish its provenance, version and preparation meaning before interpreting its
observed discharge. The directory was present during discovery; its presence alone
does not verify those facts.

Select ten random, confidently matched gauges reproducibly, without selecting for
agreement. Overlay CAMELS observed discharge and daily mean discharge retrieved
through RivRetrieve's public API over a readable overlapping period. Resolve
station identities, dates and units explicitly. Preserve gaps and unshifted dates;
do not smooth, fit or filter values to force agreement. Do not collapse source
siblings or choose one because it matches CAMELS better.

Show the hydrographs to the maintainer, who decides whether they provide sufficient
confidence. There is no automated equality or pass/fail threshold. Investigate
meaningful discrepancies and retain caveats rather than concealing them.

Retain dataset provenance, gauge/date selection and reproducibility details,
comparison method, figures, findings, limitations and the maintainer's verdict
through the existing evidence process. Exact gauge/date selection and plotting
mechanics remain implementation choices.

This comparison supplements source verification only for daily mean discharge.
CAMELS discharge also originates from USGS, so it is a cross-check of retrieval,
interpretation and conversion, not independent measurement validation. It does
not validate stage or continuous products.

## Build on completed work

Use current repository facts and the linked completion records rather than
restarting the port:

- [#623](https://github.com/RivRetrieve/RivRetrieve/issues/623) established broader
  daily-discharge access and verified newly included public routes.
- [#627](https://github.com/RivRetrieve/RivRetrieve/issues/627) completed the expanded
  catalogue and its source-backed rebuild, preserving 26 historical series.
- [#631](https://github.com/RivRetrieve/RivRetrieve/issues/631) established retrieval
  findings and genuine replay across six products. Its continuous-only stage
  witness is a complete empty interval, not proof of positive observations there.
- [#628](https://github.com/RivRetrieve/RivRetrieve/issues/628), delivered at
  `a5bd6653e31d57f652fe2cbc207c0b511d19a4b6`, changed both continuous products to
  365-day request partitions. Earlier claims of 1,100 hours were incorrect;
  the old setting was 1,100 days. Its focused checks are not full certification.

Reconcile existing evidence with the actual revision under verification. Earlier
passing runs remain evidence of their own revisions and scope, not automatic
acceptance of later changes. Keep source-independent tests, recorded replay,
derived rebuilds, governing source checks and live observations distinguishable.

The physical-meaning review [#630](https://github.com/RivRetrieve/RivRetrieve/issues/630)
was still open during discovery. Reuse its findings when available and report
any required unresolved source meaning as a blocker; an open issue alone is not
proof that every verification activity must wait. The recent #631 run also could
not retrieve the exact catalogue-source collection because its download timed
out. Recheck availability through the archive process; do not substitute local
unverified bytes or treat a timeout as passing evidence.

## Evidence and completion

Follow step 6 of the [provider-port guide](../../docs/maintenance/provider-ports.md),
the [testing guide](../../docs/maintenance/testing.md), and the
[evidence guide](../../docs/maintenance/evidence.md). Keep original evidence and
provider findings in the continuing private
[USGS research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/usgs-source-access.md).
Use reviewed exact library and archive revisions, selected genuine inputs and
existing archive tools. Keep controlled material, credentials and detailed
restricted output out of public repositories and artifacts.

Completion requires a traceable account of all six products and cross-cutting
checks, exact revisions and evidence used, outcomes and remaining limitations,
plus the ten-gauge comparison and the maintainer's affirmative confidence verdict.
Missing mandatory evidence or unresolved defects affecting acceptance block
completion; report the affected claims precisely. Extend focused coverage and
resolve demonstrated verification gaps as needed, without inventing source facts
or weakening checks. Passing synthetic tests cannot replace genuine inputs.

This work does not add products, redesign the public API, establish exhaustive
national observation history, or automate full-history acquisition. Downstream
acquisition stays with hydrologeez. User documentation remains
[#625](https://github.com/RivRetrieve/RivRetrieve/issues/625); communicate findings
that affect it. Full Program completion is outside this vision.

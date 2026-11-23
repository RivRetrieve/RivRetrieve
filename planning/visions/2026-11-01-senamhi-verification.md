# SENAMHI verification

Verify the complete `pe_senamhi` integration and deliver necessary fixes under
[Effort #608](https://github.com/RivRetrieve/RivRetrieve/issues/608) and
[Program #534](https://github.com/RivRetrieve/RivRetrieve/issues/534). Users must
be able to trust that returned identities, timestamps and values faithfully
represent the supported source publications, with limitations stated honestly.

Completing this verification, the required comparison and necessary fixes completes
#608. Publishing this vision does not complete the Effort. Work stays on
`port/pe-senamhi`; leave `main` unchanged pending the Program's final review.
User-documentation completion remains #609, and merging the port into `main`
is outside this Effort.

## Verify the delivered scope

Build on completed #604–#607 rather than restarting source research. The official
JSON API integration supports PHISIS daily and hourly series and all nine
monthly-archive water-level fields through public discovery, retrieval and cache
interfaces. The [integration vision](2026-11-01-senamhi-provider-integration.md)
and its linked series and retrieval decisions define the supported scope.
#607 records delivery at `4b1e22c696cb679003cdca28e8f98673addfeaeb`, with genuine
checks retained through private archive PR #43. Inspect the actual target and
continuing research record before selecting verification inputs.

Follow [provider-port step 6](../../docs/maintenance/provider-ports.md), the
[testing guide](../../docs/maintenance/testing.md) and the
[evidence process](../../docs/maintenance/evidence.md). Assess existing checks,
fill necessary evidence and test gaps, and fix defects within the agreed scope.
This is a completed verification effort, not an assessment alone. Consequential
source-interpretation or supported-scope changes return to the maintainer.

Use genuine retained responses and independently established expected results
for distinct supported routes. Check public identities, timestamps, values and
units together. Verify applicable cache behavior, catalogue rebuild and lineage,
and distribution contents. Preserve route and field distinctions, explicit
physical unknowns, nulls, absent rows and supported source failures alongside
independent successful results. Include the integration's hourly interval
ownership when assessing overlapping or revised responses. Preserve retained
future-dated monthly observations without inventing their cause or correcting
their dates.

Existing replay, acquisition, mapping and catalogue checks are useful evidence,
but establish different claims. Keep synthetic behavior tests, genuine replay,
derived rebuilds, source-meaning checks and live observations distinct. Bounded
acquisition evidence does not promise complete national or historical coverage.

## Compare with CAMELS-PE

Complete a bounded comparison of values returned through RivRetrieve's public API
with observed streamflow in [CAMELS-PE](https://doi.org/10.5281/zenodo.21195425),
described in [the paper](https://doi.org/10.5194/essd-2026-386). This comparison is
required before completion; perfect equality is not.

First establish that the selected records can meaningfully be compared. Match
gauges confidently and establish daily-mean meaning, date alignment and units for
the selected overlap. Account for CAMELS-PE's catchment-area conversion to mm/day
and published precision. Use observed records, not simulated streamflow. Record
the exact dataset release, selected gauges and dates, comparison results and
investigated discrepancies through the existing evidence process.

The [series-meaning vision](2026-11-01-senamhi-series-identity-and-physical-meaning.md)
establishes an important unresolved fact: PHISIS DAILY `current` is labelled as
the current year, not explicitly a daily mean. Daily aggregation periods and time
conventions remain unestablished. Do not label this field a daily mean, derive an
unpublished substitute, or infer its meaning from numerical agreement with
CAMELS-PE. Investigate comparability with applicable source evidence. If a
meaningful comparison cannot be established, return the blocker and its
consequences to the maintainer rather than skipping or weakening the requirement.
Sending agency correspondence requires separate authorization.

CAMELS-PE applies quality control and removes some observations; RivRetrieve
preserves source observations without that QC. Do not filter or alter RivRetrieve
values to force agreement, or treat CAMELS-PE gaps as proof of missing source
observations. The comparison adds confidence in the daily-discharge workflow.
It neither replaces genuine-source verification of the complete integration nor
establishes independent measurement accuracy, since the datasets largely share
SENAMHI observations.

## Evidence and completion

Continue the existing private
[SENAMHI research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/pe-senamhi-source-access.md).
Keep original evidence, provider-specific findings and detailed comparison
material in the established archive process. Review exact library and archive
revisions before execution with private evidence. Keep controlled bodies,
credentials and restricted receipts out of public repositories, logs, caches,
artifacts and distributions. Any additional SENAMHI acquisition must respect
the established limit of at most one request per second and source access
constraints; do not require an exhaustive historical scan.

Run affected source-independent tests and broader checks appropriate to the
changed boundaries. Run the applicable full genuine-input checks for changed
claims, bindings, verifiers or collections, then verify the completed integration
on the target branch. Missing mandatory evidence blocks completion; a skipped
check is not acceptance.

Report exact reviewed revisions, supporting collections, completed checks,
comparison findings, fixes and remaining limitations. Hand user-facing
limitations to #609. Leave exact evidence selection, gauge selection, comparison
mechanics, test organization and code organization to implementation. Use the
existing verification system rather than adding a parallel one.

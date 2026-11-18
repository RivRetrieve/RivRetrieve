# NRFA provider verification

Verify and correct the completed NRFA integration so its public results faithfully
preserve the published source records. Deliver genuine-source verification of all
ten supported products and the required ten-gauge CAMELS-GB comparison.

Completing this work completes [#583](https://github.com/RivRetrieve/RivRetrieve/issues/583).
Publishing this vision does not complete the issue or start implementation.
Provider coordination remains in [#347](https://github.com/RivRetrieve/RivRetrieve/issues/347),
with shared UK context in [#582](https://github.com/RivRetrieve/RivRetrieve/issues/582).

## Starting point and scope

Provider integration was delivered by #869 on `port/uk-nrfa` at
`4cee2fe283f2bc4a24bbaa3326579703bfe0efe3`. The handoff in
[#590](https://github.com/RivRetrieve/RivRetrieve/issues/590) records public discovery,
retrieval, series and annotation support through `LiveStages`, plus a maximum
30-calendar-day client cache retention policy. Verify the current complete port
against explicitly reviewed revisions rather than relying on an older local branch
or treating earlier passing tests as complete acceptance.

Cover all ten current API products: `gdf`, `ndf`, `gmf`, `nmf`, `gauging-flow`,
`gauging-stage`, `amax-flow`, `amax-stage`, `pot-flow` and `pot-stage`. Current means
the archive served at retrieval time, not real-time observations. Preserve the
source contracts established in #587, #584, #595 and #594 and integrated in #590.
Reopen source conclusions when new evidence warrants it, not merely because an
alternative implementation is possible.

Keep source identities, published values, explicit nulls, absent rows, flags and
series annotations distinct. Do not filter rejected observations, rank source
quality or infer missing physical facts. Preserve nominal monthly carriers and
original labels, established window rules, and unknown time zones, water-day
applicability and stage datums. Keep supported request failures alongside independent
successful results; fatal internal contract errors must still raise.

Rainfall, numbered bulk peak-flow releases, enquiry-only records, automatic
metadata refresh, derived replacement products and stitching with EA remain outside
scope. Verification must not create new claims of gap-free histories.

## Verify and correct independently

This is a verify-and-correct effort. Investigate failures, fix defects within the
settled contract and rerun affected checks without step-by-step approval. Work as
independently as possible. Use other implemented providers, shared contracts and
maintainer guides to resolve routine engineering choices. Their implementation
patterns are guidance, not evidence of NRFA source meaning.

Return to the maintainer only when investigation leaves no obvious, defensible way
to proceed. Do not silently narrow the ten-product scope, weaken mandatory evidence
or guess source meaning to avoid a blocker. A genuinely unresolved choice about
scope, source interpretation or a meaningful limitation must remain explicit.
Leave module layout, focused test design, comparison mechanics and other reversible
implementation details to the implementing agent. Use existing verification and
annotation mechanisms rather than building parallel systems.

Follow step 6 of the [provider-port guide](../../docs/maintenance/provider-ports.md),
the [testing guide](../../docs/maintenance/testing.md) and the
[evidence guide](../../docs/maintenance/evidence.md). Extend shared contracts and
exercise genuine retained examples for distinct supported routes through the
complete integration. Establish expected results independently of the implementation
being checked. Check identities, timestamps and values together, including source
annotations, boundary handling and daily, monthly and irregular products.

Verify relevant cache/store behavior, including the established 30-day client cache
limit, catalogue lineage, the all-provider catalogue rebuild and distribution
contents. Check that empty responses, published nulls, absent rows and failed
requests remain distinguishable. Add focused regressions for discovered defects
at the simplest sufficient level and run affected source-independent tests and
applicable full genuine-source checks.

## Ten-gauge CAMELS-GB comparison

Complete the [required comparison](https://github.com/RivRetrieve/RivRetrieve/issues/583#issuecomment-6688057595)
of NRFA gauged daily mean discharge retrieved through RivRetrieve's public API
with CAMELS-GB. Establish the dataset version, product meaning, station identities,
date alignment and units before comparing values.

- Select ten gauges reproducibly at random from confidently matched stations with
  overlapping dates. Do not select for agreement.
- Plot both hydrographs, preserve gaps and make unit conversions explicit.
- Investigate meaningful discrepancies without shifting, fitting or filtering
  values to force agreement. Perfect equality is not required.
- Retain the exact dataset version, eligible population and station/date selection,
  reproducible method, figures, findings and limitations through the existing
  private evidence process.
- Report inability to obtain ten suitable comparisons as a blocker. Do not reduce
  the sample or skip the check silently.

[CAMELS-GB section 5.2](https://doi.org/10.5194/essd-12-2459-2020) describes streamflow
obtained from NRFA. This is a shared-source consistency check, not independent
measurement validation. Later NRFA revisions may explain differences, but do not
assume that explanation without investigation. The comparison does not replace
complete genuine-source verification or cover the other NRFA products.

## Evidence and completion

Continue the existing private
[NRFA research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/nrfa-source-access.md).
Reuse suitable retained material and obtain missing originals through the archive's
existing intake process. Respect the established source permissions and private
test-retention decisions. Private storage alone does not establish permission.
Review exact public and archive code revisions before execution with private inputs.
Keep controlled material, credentials, detailed outputs and figures out of public
repositories, logs, caches, artifacts and distributions.

Completion requires the complete integration checks and ten-gauge comparison,
corrections and reruns where needed, and an account of exact reviewed revisions,
retained evidence, commands, results and remaining limitations. Keep synthetic
checks, recording replay, derived rebuilds, genuine-source verification and live
observations distinct. Missing mandatory evidence blocks completion; a skip or a
synthetic replacement is not a passing result.

Keep provider-specific findings in the continuing private record. Publish only
safe summaries and handoffs on #583/#347 and safe cross-provider findings on #582.
Keep affected interface documentation accurate when correcting behavior. The broader
user-documentation effort remains #593.

All implementation and corrections stay on `port/uk-nrfa`. Thiago's explicit final
approval under #597 remains necessary before merging the provider into `main`.
Completing this verification effort does not authorize that merge.

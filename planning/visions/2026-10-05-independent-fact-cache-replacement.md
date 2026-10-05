# Independent fact cache replacement

A failure for one physical-fact segment must not prevent another segment of the
same source series from returning, saving and reusing its successful observations.
For example, a failed maximum-stage request must leave a successful mean-stage
refresh intact. The failed maximum retains its diagnostic and any previously held
successful data, with the original acquisition evidence.

Related bug: [#527](https://github.com/RivRetrieve/RivRetrieve/issues/527).
This is a standalone repair. [#516](https://github.com/RivRetrieve/RivRetrieve/issues/516)
is paused until it receives and verifies the merged repair. Publishing this vision
neither delivers the repair nor authorizes resuming #516.

## Observable outcome

The returned result, saved observations, successful coverage and later reuse must
agree about which facts succeeded. Each retains the source calls and acquisition
time that actually support those facts. An independent failure remains visible
without spreading its effects to successful siblings.

A successful empty answer has the same replacement authority as a successful
answer with rows. It clears held rows only within its established scope and records
successful coverage there. It differs from a failed request, from an absent row
without completeness evidence, and from a published row containing a null value.

Previously held successful data can still serve a failed scope. Its acquisition
time and supporting calls remain unchanged; the new failure cannot make those
observations appear newly acquired. A failed scope without previous coverage must
not become covered because another fact succeeded.

## Investigation evidence

Investigation used unchanged revision
`f1728333e509fd7b6a543b60ffe6891a36b8b070` in an isolated clean checkout. The paused
#516 changes were not used. All executed reproductions were synthetic and
source-independent. They establish library behavior, not actual agency behavior
or acceptance against retained publisher inputs.

The issue retains an executable small reproduction of `_combine_replacements`.
Additional public `fetch` probes used one invented series with independently
admitted mean/max stage facts, native unit `m`, a published `+00:00` offset, and a
row at noon on 2026-01-01. The seeded acquisition returned value 1 for both facts;
the later acquisition returned mean value 2, or an explicit successful empty mean
answer, alongside a max failure. Distinct acquisition times and calls identified
the old success and new failure.

| Probe | Observed baseline behavior |
| --- | --- |
| Cold cache, mean success and max failure | Mean value 2 is returned, but saved coverage is empty and its active successful outcome disappears. |
| Seeded cache, mean refresh and max failure | Mean value 1 is returned and retained instead of fresh value 2. |
| Seeded cache, successful empty mean and max failure | Old mean rows survive in the result and store. |
| Cold mixed result followed by mean-only reuse | The source is contacted again despite the independent mean success. |
| Seeded mixed or empty result followed by reuse | Reuse makes no source call but serves the old mean value. |
| Multi-fact success with a failure affecting only some facts or times | Failure subtraction removes unaffected successful fact scope too. |
| Native-axis success and unrelated UTC-axis failed fact | An irrelevant axis mismatch raises a fatal error, even in the tested time-disjoint case. |
| Independent same-window successes with different acquisition times | Their combined coverage takes the latest time, losing the earlier fact's distinct active acquisition attribution. |

The reuse proof required a complete acquired inventory with both member facts,
the payload scope and acquisition window, and links to the original acquisition
outcomes. With that fixture, an all-success control reused mean-only, max-only and
broad selections with zero source calls. Cold mixed success/failure required one
call for each selection. Earlier probes lacking a complete inventory also
refetched in their all-success control and do not establish the causal reuse claim.
The max failure reason and outcome/issue link survived, together with its new
acquisition time and call. Held success retained its old time and call.

Existing source-independent tests passed despite these defects: 96 passed and 2
deselected across `test_source_series_store.py`, `test_internal_driver.py`,
`test_cache_authority.py` and `test_cache_issue_equivalence.py`; another 64 passed
and 11 deselected across `test_acquisition_composition.py`,
`test_usgs_continuous_cache_axis.py` and `test_usgs_observation_acquisition.py`.
These were baseline checks, not repair acceptance. Deselected checks were not run.

## Repair boundary and repository facts

Repair acquisition-to-result and acquisition-to-store scope consistently. A local
filter in `_combine_replacements` is insufficient. At the investigated revision,
`src/rivretrieve/_internal/driver.py` contains these connected paths:

- `_combine_replacements` (lines 1299–1408) subtracts same-series failure windows
  without comparing facts. An intersection check alone would still mishandle a
  multi-fact success whose failure affects only a subset.
- `retain_held_successes` (1713–1773), its parsed-failure callers (2187–2201), and
  fresh-row exclusion (2275–2279) restore and suppress data at series/window scope.
  `_exclude_native_intervals` carries no fact scope. Acquisition-side unsupported
  exclusion also uses that broad operation.
- Replacement construction (2361–2371) widens `replaced_facts_ids` to selected
  facts from parsed and held definitions. This grants more deletion authority than
  the positive outcome establishes. Static tracing shows why allowing the success
  through without repairing this authority could delete held failed siblings.
- Same-window aggregation (1383–1404) unions unrelated facts and calls and uses the
  maximum acquisition time. Optional historical originals do not restore correct
  active row attribution. In particular, one known time cannot fill another
  independent acquisition's unknown time.

The store already distinguishes positive coverage from explicit deletion scope.
`store/accumulation.py` supports narrow fact replacements, splitting old coverage
by facts and time, and exact-key snapshot updates. The narrow sibling-preservation
and explicit broad-retirement tests in `test_source_series_store.py` protect both
capabilities. Preserve those capabilities rather than narrowing every replacement
blindly or broadening every success.

The [observation-store contract](../../docs/design/observation-store-layout.md)
requires original acquisition support, fact-scoped successful replacement and
preservation of held successes after failure. `store/authority.py` treats facts
as independent diagnostic scopes. Its `supporting_outcomes` relation keeps
acquisition evidence needed by current inventories; it is not active observation
support or a permanent attempt archive. Supporting history must not reactivate
superseded diagnostics or caller issue policy.

## Settled behavior

Use the same established success and failure domains to determine fresh accepted
rows, held fallback, successful empty replacement, active coverage and saved
updates. The implementing agent chooses the internal representation and module
boundaries. Physical write batching must not force independent evidence to merge.

- Preserve concrete source identity, fact identity, explicit time axis and the
  distinction between interval coverage and observation-key coverage. Split
  partial overlap by both facts and time, or by exact snapshot keys. Closed
  interval endpoints use the existing microsecond arithmetic.
- A concrete failure naming facts affects those facts. An empty failure fact list
  means unestablished fact scope, not an empty set that is harmless to everything.
  Keep conservative handling within the established series or route boundary.
- Identity-unknown route `FAILED` and `UNSUPPORTED` outcomes cannot masquerade as
  unrelated series. Route `UNRESOLVED` inventory evidence describes uncertainty
  about membership; it does not by itself invalidate independently successful
  concrete observations. Apply these distinctions consistently to fallback and
  persistence.
- Preserve relevant failures, their identity, reason and supporting calls whether
  or not successful siblings remain. Issue policy controls reporting, not whether
  invalid internal output is accepted or whether failure evidence is retained.
- Keep per-fact original acquisition times and calls, including unknown times.
  Independently successful facts must not inherit another fact's later time or
  source-call attribution.
- Broad retirement of obsolete facts requires established source replacement
  authority. Caller selection, partial success or missing rows alone cannot prove
  that older facts are obsolete. Applicable complete acquired fact membership and
  absence evidence may establish that authority; its scope and dependencies must
  be valid. Preserve explicit authorized retirement and protect failed or unknown
  sibling scopes. Do not invent completeness or supersession claims.
- Successful empty answers clear only authorized held rows. Published nulls and
  duplicates remain observations. Snapshot updates replace only established keys;
  they do not establish interval completeness or delete absent snapshot keys.
- Preserve fatal checks for genuinely incompatible same-fact acquisition axes.
  Unrelated facts must not trigger those checks merely because their axes differ.
  Do not infer time zones or silently treat native and UTC axes as interchangeable.
- Preserve valid dependent-page composition. USGS cursor pages can share windows
  while carrying distinct payloads and call identities. Existing provider checks
  reject conflicting repeated observations and incomplete chains. Removing all
  grouping or rejecting every overlapping positive interval would break legitimate
  acquisition behavior. Preserve source multiplicity and existing snapshot-key
  overlap safeguards.

## Acceptance

Add expectations that expose the named defects at the simplest sufficient level,
with public-path coverage where driver fallback and persistence interact. Use
invented data and temporary cache/store roots. Extend shared fixtures and contracts
rather than building a second test framework.

1. Demonstrate cold and seeded mean-success/max-failure retrieval. Assert the
   exact returned rows, saved rows, per-fact coverage, failure diagnostics and
   supporting acquisition calls/times. Check both contribution orders.
2. Demonstrate successful empty replacement beside a failed sibling. The empty
   fact must lose its old rows while keeping successful empty coverage; the failed
   fact must keep its held data and original evidence.
3. Cover disjoint and partially shared facts, partial time overlap and closed
   endpoints. Include `FAILED`, `UNSUPPORTED` and concrete `UNRESOLVED`, unknown
   fact scope, identity-unknown route failures, and inventory-only uncertainty.
   Keep `NO_MATCH` outside failure vetoes; do not reinterpret it as physical empty
   coverage. Protect distinct-series isolation.
4. Prove subsequent mean-only reuse makes no source call when complete inventory
   and successful mean coverage establish reuse. Use a reusable all-success
   control. Without previous max coverage, max-only and broad requests must remain
   uncovered. With previous max coverage, preserve the existing ability to reuse
   held success with its original evidence and the applicable failure diagnostic.
5. Check independent acquisition attribution using different times and calls,
   including one unknown time. Preserve duplicates and published nulls. Exercise
   snapshots, valid dependent-page composition, incomplete-chain refusal and
   same-fact axis contract errors as regression boundaries.
6. Protect authorized obsolete-fact retirement and prove incomplete membership or
   a caller's broad selection cannot authorize deletion of unrelated held facts.
   Publication remains atomic; fatal contract errors must not publish partial
   invalid updates.

Run affected source-independent tests and the full `uv run pytest --logic-only`
suite, with lint and type checks appropriate to the implementation. Follow the
[testing guide](../../docs/maintenance/testing.md). Keep documentation accurate
where the repair changes explained behavior.

Use the maintained private archive interface for applicable genuine-input replay
checks. Synthetic results do not establish source acceptance. Changes to provider
interpretation of completeness, fact membership or supersession, or to governing
claims, source bindings, verifiers or collections, require their applicable full
genuine-input checks under the [evidence guide](../../docs/maintenance/evidence.md).
Review exact revisions before running private evidence. Report unavailable
mandatory evidence as blocked; do not substitute derived data or expose controlled
source material and credentials.

## Boundaries and delivery

The owner requests a thorough repair without a minimal-patch constraint. Redesign
within this shared correctness boundary is allowed when the evidence justifies it;
unrelated complexity is not an outcome.

This work does not redesign the observation-store format, add a permanent attempt
archive, implement #516's selective-reader or request-evidence projection work,
change source scientific judgement, or introduce a general policy for arbitration
between overlapping independent successful acquisitions. That last concern was
observed during review, but the current carrier does not reliably distinguish it
from legitimate dependent pages. Preserve established composition rather than
inventing a new conflict rule here. `NO_MATCH` reinterpretation is also outside
this repair.

Deliver a separate implementation PR with regression evidence. Hand its merged PR
to #516 for independent verification before that work resumes. The implementation
agent must preserve unrelated work and follow the repository's publication and
verification contracts. This vision publication itself makes no implementation
or bug-resolution claim.

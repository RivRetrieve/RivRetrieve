# Preserve MLIT acquisition prerequisites

MLIT retrieval opens an HTML page, validates its source context and follows its
link to a DAT file containing measurements. A later cache read must retain both
original requests in the measurements' acquisition history. Today it returns the
same measurements but loses the HTML request. This breaks traceability even when
no numerical value changes.

Related bug: [#531](https://github.com/RivRetrieve/RivRetrieve/issues/531).
This is a standalone repair, separate from
[#516](https://github.com/RivRetrieve/RivRetrieve/issues/516) and its draft PR
[#530](https://github.com/RivRetrieve/RivRetrieve/pull/530). Publication of this
vision does not deliver the repair or authorize resuming #516. That work requires
a merged-fix handoff and independent verification first.

## Outcome and scope

Record actual dependencies between acquisitions and preserve the supporting
requests through fresh results, store publication and network-free reuse. Keep
original call identities, request details, source retrieval times and unknowns.
A local cache read must not make old observations appear newly acquired.

The dependency must be established where acquisition occurs. Matching physical
facts, stations, dates, URLs or unrelated historical calls cannot establish it.
Preserve only the dependencies needed by retained observations, coverage,
inventory evidence or still-applicable diagnoses. Full replacement must retire
obsolete chains; partial replacement must retain chains needed by surviving data.
Do not keep every historical request to avoid losing one prerequisite.

Cover successful DAT retrieval, unsupported DAT content and a failed DAT request
after successful HTML retrieval. Keep each failure's original identity and reason,
and preserve independent successful intervals and series. An HTML prerequisite
must not become a false successful-empty observation outcome. Explicit HTML
no-data answers and malformed HTML remain distinct existing outcomes.

Preserve measurement values, source facts, time axes, coverage, supported partial
results and issue-policy behavior. Fatal internal contract errors remain fatal.
Keep authentication, retry, inventory and valid dependent-page evidence intact.
Do not revive superseded failures merely because their calls support other held
evidence.

Receipt semantics do not change. Direct acquisition can return the HTML and DAT
publisher bodies. Cache reuse returns a generated local excerpt receipt; it need
not recreate publisher receipts. Call provenance must survive with receipts both
enabled and disabled.

## Investigation evidence

Investigation used clean target revision
`410df0614667921dde724db8b606521cd5e43481`, not the paused #516 candidate or the
canonical checkout's unrelated edits. The executable synthetic reproduction is
retained in #531. This discovery independently ran it with an assertion that
imports came from that clean checkout and a temporary cache root.

| Check | Observed baseline |
| --- | --- |
| Actual transport and fresh provenance | HTML, then DAT |
| Persisted manifest and held provenance | DAT only |
| Fresh versus held data | Identical frames, two observations |
| Reuse transport | Forbidden; no network call occurred |
| Receipts | Two direct publisher responses; one local excerpt on reuse |

The explicit held-HTML assertion failed. All data and no-network controls passed.
This establishes a library defect using invented source bodies, not genuine-input
or live-service acceptance.

Focused baseline checks passed 98 source-independent tests across
`test_cache_authority.py`, `test_acquisition_composition.py` and
`test_independent_fact_cache.py`. The selection also included
`test_jp_mlit_html_outcomes.py` and `test_jp_mlit_chunk_isolation.py`;
66 retained-input cases were deselected, not passed. Existing green checks do not
establish that successful HTML support survives persistence.

## Repository facts that guide the repair

At the investigated revision:

- `providers/jp_mlit/fetch.py` emits separate HTML and DAT `Payload` values with
  independent acquisition identities. `providers/jp_mlit/parse.py` deliberately
  gives valid linked HTML no rows or outcomes. DAT outcomes refer to DAT evidence.
- `store/authority.py` follows outcome and inventory references through call and
  acquisition aliases. Without an explicit link it cannot reach the successful
  HTML request and prunes it from retained evidence.
- `Payload.prerequisite_calls` in `engine.py` holds `SecretCallTrace` values.
  `transport.py` constrains these to sanitized, withheld credential-response
  evidence. Ordinary HTML must not be disguised as a credential exchange; doing
  so would misstate the response and lose its request parameters.
- Authentication already attaches sanitized exchange traces to an acquisition.
  Norway inventory calls and USGS page composition have existing explicit evidence
  relationships. Preserve their behavior rather than introducing a second,
  inconsistent meaning for those records.
- DAT transport failures have their own identities in `source_acquisition.py`.
  Linking successful payloads alone would leave their HTML support unrepresented.

These paths are under `src/rivretrieve/_internal/`. Choose a bounded shared
representation for genuine acquisition dependencies and wire MLIT to it. The
implementer owns the exact types, persistence representation and module layout.
Avoid a general workflow framework or an unrelated provider redesign.

## Existing caches

Accumulated manifests use format revision 8 at the baseline. Some already lack
the original HTML call. New in-memory linkage cannot recover that lost evidence.
Do not reconstruct it from matching station, time or URL fields, relabel old
history as complete, or silently make a new request look like the old acquisition.

Affected caches may require explicit refresh. A refresh creates new acquisition
history, not restoration of the missing original history. Make that requirement
visible and test that an old affected cache cannot silently appear repaired.
Choose the narrow validation or compatibility mechanism from the implemented
representation; a format bump is not required merely by this vision. If persisted
contracts change, update their schema, validators, refusal tests and documentation
consistently. Do not add a speculative historical reconstruction migration.

## Acceptance

Use the simplest tests that detect each claimed behavior. Add an entirely authored
public-boundary MLIT fixture with explicit series selection and temporary cache
roots. Do not require private inputs for the core defect regression.

- Run the issue reproduction successfully: unchanged frames, no transport on
  reuse, and both actual requests retained in the manifest and held provenance.
- Check original identities, HTML KIND/ID/BGNDATE/ENDDATE parameters, call order
  and distinct retrieval timestamps. Merely counting two calls is insufficient.
- Exercise receipts on and off. Preserve exact direct response bodies when
  requested without requiring those bodies in generated cache-excerpt receipts.
- Cover failed DAT transport and unsupported DAT content after valid HTML, beside
  an independent healthy interval or series. Keep the right failure and dependency
  without granting failed scope successful coverage.
- Keep explicit HTML no-data covered and malformed HTML unsupported and uncovered.
  Neither case should cause a DAT download.
- Cover full refresh and partial overlap. Retain the dependencies of surviving
  observations, remove obsolete chains and exclude unrelated intervals/products,
  even when their physical facts or source URLs coincide.
- Extend shared authority regressions for dependency retention and retirement.
  Keep existing credential, retry, inventory, page-composition and independent
  fact-replacement checks. Validate malformed dependency references as internal
  contract failures rather than allowing issue policy to conceal them.
- Test and document the chosen old-cache behavior. New acquisition timestamps
  must remain distinguishable from old ones.

Run the affected source-independent tests, the full source-independent suite and
applicable lint/type checks. Before delivery, run applicable retained MLIT replay
and shared-boundary regressions through the maintained private archive coordinator
against independently reviewed exact code revisions. Follow
[the evidence guide](../../docs/maintenance/evidence.md) and
[testing guide](../../docs/maintenance/testing.md). Required genuine-input checks
that cannot run are blocked, not replaced by synthetic controls or silent skips.
Run full governing checks if governing claims, source bindings, verifiers or
collections change. Keep private inputs, receipts and credentials outside public
repositories and publication artifacts.

## Delivery boundary

Update public documentation for changed behavior and any refresh requirement.
Obtain independent review of the implementation and its verification evidence.
Provide #516 with the merged repair revision, the reproduction result and relevant
regression results. Its owner must verify the repair independently before resuming.
The separate fresh-call projection regression and other candidate failures in
#516 remain there. This repair does not claim national read performance, #516
acceptance, catalogue recertification or live-service behavior.

# Newcomer documentation review and PR 252 delivery

## Outcome and ownership

Take ownership of [PR #252](https://github.com/RivRetrieve/RivRetrieve/pull/252),
revise and verify its documentation, obtain the human author's review, and merge
only after explicit human approval. Findings are work for the implementing agent,
not review comments handing repairs back to the original contributor.

The usage guide onboards people starting to use RivRetrieve. It gives an
approachable overview of the main features through runnable examples and plain
explanations. It is not an exhaustive API contract or an architecture manual.
The README and guide must agree and lead readers through finding stations,
retrieving observations, and inspecting the returned results, in that order.

## Scope

Revise `docs/usage.md` and `README.md`. Supporting documentation tests may change
to verify the examples and prevent regressions. Do not change library behavior,
public API exports, provider implementations, or hosted CI in this effort.

Leave `docs/examples/camels-us.md` untouched: its rewrite is independently owned by
[PR #255](https://github.com/RivRetrieve/RivRetrieve/pull/255). Do not expand into
other unreviewed documentation or provider-specific writing. Record external
problems and coordinate dependencies without modifying that independently owned
work. Recheck the current state of both PRs before implementation.

Use the existing PR #252 where safely possible. If a replacement or supporting PR
is necessary, preserve its provenance and explain the relationship. Do not discard
contributor or concurrent changes. The intended target branch is `main`.

## Reader-facing decisions

### Sequence and vocabulary

- Follow the introduction's promised order: find stations, retrieve observations,
  then inspect data and issues. Put the observation-column table after the example
  that produces those columns, not before the reader has retrieved anything.
- Explain the packaged catalogue at first use: station and product lists included
  with the installed package, searched without contacting the agencies. The
  README currently uses this phrase without explaining it too.
- Use plain, direct statements. Remove unnecessary contrastive negations and
  implementation jargon. Unknown identifiers raise errors; this needs no contrast
  with approximate matching.
- Use distinct names showing successive steps, such as `daily_gauges` and
  `chosen_gauges`, instead of repeatedly overwriting `selection`. Keep naming and
  example state consistent across the two pages.

### Executable examples and visible output

- Every retained `print` must have its own corresponding, verified output example,
  preferably in comments immediately below the code. Do not leave readers to guess
  what a frame, issues tuple, or provenance object looks like.
- Keep output manageable by printing useful columns, fields, or a small explicit
  subset. Label omissions or representative output honestly. Do not invent exact
  output, timestamps, row counts, or source responses.
- Establish whether examples build on earlier variables and make that progression
  clear. Avoid silently changing the station set used by later examples.
- Demonstrate `fetch_by_provider` with code and visible output showing its
  provider-keyed results, using a tractable example without required credentials.
- A feature can simply be useful, such as mapping station coverage. Where a real
  problem helps explain a feature, introduce it before the solution. Do not force
  or invent user needs to give every section the same formula.

### Selection and Polars filtering

- Explain lists using the actual `station=[...]` example. The existing example
  already passes a list; calling it a sequence without explanation is unhelpful.
- Explain that `pick` keeps matching entries from its input. It cannot introduce
  another station or product into that input selection.
- Explain recognised identifiers with no selectable combination in short
  sentences: the selection is empty, and `empty_reason` explains why.
- Give custom filtering a purpose that `pick` does not already serve, such as
  filtering by latitude. `find` returns a selection object; `as_frame` produces a
  Polars table; `from_frame` rebuilds a selection after custom filtering.
- Explain `from_frame` accurately: `provider_id`, `station_id`, and `product_id`
  must appear in that relative order and contain strings with no missing values.
  Their three-column combinations must be unique and correspond to selectable
  catalogue entries. Individual strings need not be unique. Other columns do not
  override catalogue metadata. Filtering an unchanged `as_frame` output preserves
  its column structure. Avoid unexplained phrases like canonical order and
  selectable triples; use concrete examples where helpful.
- Link Croissant to https://github.com/mlcommons/croissant.

### Time, issues, and credentials

- Simplify time-window language without weakening its semantics. Explain source
  wall-clock time, inclusive endpoints, accepted input types, required `start`,
  date-only endpoint behavior, omitted `end`, and future-end information at a
  level appropriate to onboarding. Link detailed contracts where necessary.
- Explain what UTC conversion does and why an unknown zone prevents conversion.
  The existing USGS daily example returns unknown zones, so its conditional UTC
  snippet skips conversion. Do not imply that it produced `utc_result` when it did
  not; demonstrate any conversion branch using genuinely established zones or
  explicitly labelled synthetic data, never an inferred USGS zone.
- Distinguish issue severity from handling. RivRetrieve assigns `info`, `warning`,
  and `error`; `on_issue` controls whether warning/error issues produce warnings,
  an exception, or no notification. Issues remain available when returned.
  Demonstrate handling with code and output, and retain the distinction between
  a failed request and a successful request with no observations.
- Public exception imports are a separate API decision. The current root does not
  re-export the exception classes; the inspected code shows no technical necessity
  for that restriction. Document existing imports plainly and leave any change to
  a separate refactoring effort. Do not implement that refactor here.
- Retain clear `.env.example` guidance. Translate credential rules into practical
  consequences: required credentials are checked even for cache reads, and all
  selected providers are checked before mixed-provider retrieval starts. If
  retaining security detail, explain that credentials are sent only to configured
  agency addresses and retained request metadata excludes credential values.
  Keep transport mechanics out of the onboarding path. Do not expand into agency
  credential-acquisition documentation owned by the provider-documentation work.

### Cache, provenance, receipts, and maps

- Keep cache location, controls, and useful consequences in usage. Detailed
  on-disk storage trees and internal formats belong in architecture; this effort
  need not add them to another page.
- Motivate provenance as a way to investigate where a result came from: provider,
  request, and cache context. Motivate receipts as the source bytes or stored rows
  available for closer inspection. Explain purpose before listing fields.
- Correct the claim that provenance always contains all addresses called. Failed
  requests can leave no recorded payload origin. Describe available call records
  without promising a complete request or transformation audit.
- Correct the claim that `store_excerpt` implies a bulk store. Both bulk stores
  and live-provider accumulated caches can return RivRetrieve-authored excerpts.
  Preserve the distinction from publisher-authored bytes.
- Be precise about retrieval timestamps and intervals: newly fetched calls and
  already cached served intervals do not necessarily populate identical fields.
- Show maps naturally as a utility for inspecting station coverage, without
  inventing a research problem. Retain necessary optional-dependency and coordinate
  interpretation guidance.

## Existing evidence and risks

The initial review executed the usage blocks in page order at PR #252 commit
`486048df2a5cf7658c161481b00479c6f257fd59`, in an isolated uv environment and cache.
Live USGS retrieval returned 365 rows without issues; cache writes, receipts, and
HTML map creation ran successfully. A separate cache hit produced `store_excerpt`
with accumulated-store format 4. The UTC guard skipped the unknown USGS zones;
a separately labelled synthetic fixed-offset row exercised conversion successfully.
The CAMELS example also ran, returning 365 rows per station, but remains out of
editing scope. These observations are historical checks, not promises about future
source availability or substitutes for executing revised examples.

The original Polars filtering example reduces three stations to one; subsequent
retrieval and mapping consequently operate on one station. Revisions must make
such state changes explicit or avoid them.

At that commit, `tests/test_documentation.py` reported six passes and one failure:
the CAMELS page links to `usage.md#request-windows-and-utc`, whose heading was renamed.
Preserve a compatible anchor in usage or coordinate with PR #255. Do not edit the
CAMELS file, suppress the check, or claim success while a broken link remains.
The PR description's claim that the documentation tests pass must be corrected
based on final evidence. Recheck current branches because this may already change.

## Verification and delivery

1. Inspect current Git/GitHub state and repository instructions; preserve unrelated
   work. Review the README and PR #252 together against this full vision.
2. Implement the scoped changes and regression checks. For identified bugs, prove
   the failing behavior before the repair, following repository rules.
3. Execute revised snippets through the project's uv environment with an isolated
   cache. Inspect real outputs, not just syntax or successful process exits. Exercise
   meaningful conditional branches separately where the main example skips them.
   Keep large national downloads explicitly disabled unless separately authorised;
   do not use or expose real credentials. Install the map extra for map checks.
4. Verify claims against implementation, check links, run documentation tests and
   appropriate local format/lint/type/test checks for changed supporting code.
   Extend existing example tests where needed: current usage syntax checks alone
   do not establish execution. Distinguish fixture-based tests from live checks.
   Do not introduce hosted CI.
5. Push changes and open or update the relevant PRs. Update their descriptions with
   actual scope, evidence, limitations, and any dependency on the CAMELS rewrite.
6. Obtain independent agent review of the complete vision, complete diff, and
   validation evidence. Repair findings and rerun affected verification. Agent
   review is necessary but never substitutes for the following human gate.

## Mandatory human review and merge gate

This gate overrides any workflow default that would let an agent merge once its
own review and checks pass. It applies to every PR delivering this effort,
including an updated PR #252, a replacement, and any supporting PR.

- First, finish implementation, open/update the PRs, run verification, and complete
  independent agent review. When agents judge the PRs ready to merge, stop.
- Give the human the PR links, a concise change summary, test and snippet evidence,
  and any remaining caveats. Explicitly state that human review is pending.
- The human reviews the actual PRs and gives feedback. Address that feedback,
  repeat affected tests and agent review, and return the revised diff for human
  verification. Do not interpret silence or prior vision approval as merge consent.
- Merge only after the human explicitly approves merging the reviewed revision
  and all repository merge requirements are satisfied. Material changes after
  approval require renewed human approval. Do not enable auto-merge or delegate
  around this gate.
- After authorised merge, verify the merged content on `main` and report the
  delivered PRs and validation evidence. Until then, report ready-for-human-review,
  not complete or merged.

Authoring this vision does not start implementation. The vision's own publication
PR is also held for human review and explicit merge approval in this session.
Implementation handoff requires the exact vision to be verified on `main` after
that publication merge.

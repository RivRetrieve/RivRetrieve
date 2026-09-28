# Czech provider documentation review

## Outcome

Update the existing [provider documentation PR #295](https://github.com/RivRetrieve/RivRetrieve/pull/295),
`docs/provider-czechia` targeting `main`, with an accurate, readable Czech CHMI
provider page and an accurate PR description. Preserve Thiago's useful work where
possible. The PR predates the API and behavior updates incorporated through
PR #300. Update the documentation to the current implementation, including later
changes on `main`; do not freeze the review at #300.

This is a migration of the documentation, not a migration guide for readers.
Describe only how RivRetrieve works now. Do not add old-versus-new API comparisons,
backward-looking explanations, or compatibility guidance.

The deliverable is the updated existing PR, not a replacement provider PR and not
a merged provider page. The human review gate below overrides any workflow's
default implementation merge or completion authority.

## Reader-facing page

Follow `docs/AGENTS.md` as mandatory writing guidance. Use the merged pages in
`docs/providers/` as strong references for structure, tone, table labels and
meaning. The Lithuania page is especially useful for historical-only access;
other pages demonstrate source/returned unit tables and useful result previews.
Match shared table entries without erasing genuine provider differences. This
work does not authorize a rewrite of the other provider pages.

Explain Czech national hydrology, who measures and publishes the data, and what
RivRetrieve provides. Preserve accurate prose, source vocabulary and references
from Thiago's draft. Write for an educated hydrology reader with basic Python
knowledge, not for an engineer inspecting provider internals.

Use one practical retrieval example with enough context to understand its
selection, returned values and issues. Prefer the existing station when it works
and suits the explanation; the station and dates are not user-mandated. Link to
`docs/usage.md` for general API instruction rather than turning the page into an
API reference. A change of example must never conceal a code defect.

Explain supported quantities and frequencies, published statistics, source and
returned units, availability limits, time labels, relevant data status, access,
and terms and attribution. Keep additional detail only when it helps readers use
or interpret this provider. Distinguish the historical service RivRetrieve reads
from other CHMI publications without presenting an exhaustive unsupported-product
inventory. Verify who actually measures and publishes; do not infer those roles
from the publisher's name alone.

Retain the documentation-index link, integrating it with the current list without
dropping other providers. Detailed verification commands and evidence belong in
maintainer records, not in the introduction.

## Repository evidence established during discovery

These are starting points, not substitutes for verification against the revision
used for implementation. Discovery inspected `main` at
`ec1586a3ede4fb0575c3104fb4f5419cb31a9511`, the PR diff and body, merged provider
pages, current CHMI source and focused tests. Offline catalogue inspection used
`uv run python`. No live CHMI retrieval was performed during discovery.

- The draft calls `rr.find(..., product="discharge_daily_mean")`. The current
  public API rejects that keyword. Select using `quantity="discharge"`,
  `frequency="daily"`, `statistic="mean"` and the station. Use `rr.pick` only
  when it serves the actual selection.
- The packaged catalogue has 831 stations and 4,155 source-series candidates.
  Station `0-203-1-180100` is present. The five CHMI codes are QD, HD and TD for
  daily mean discharge, stage and water temperature, and QH and HH for hourly
  mean discharge and stage. These listings do not establish observations for
  every station, quantity or requested period. Current public series inspection
  uses `inventory_status`; do not present the old availability field as current
  public API output.
- Stage is published in centimetres and returned in metres. Discharge is returned
  in m³/s and temperature in °C. Keep source and returned units distinct.
- `src/rivretrieve/_internal/providers/cz_chmi/fetch.py` reads annual daily and
  hourly files below CHMI's historical data route. It does not read `recent` or
  `now` and does not impose a fixed 2025 cutoff. Any latest-year claim requires
  fresh, dated source evidence and must not imply complete coverage at every
  station or for every series.
- The configuration and parser retain UTC labels as `time_zone="+00:00"`.
  Daily day definitions and hourly interval anchoring are unknown. UTC timestamp
  labels alone do not establish the boundaries of the averaging periods.
- Existing recorded tests include station `0-203-1-000400` in 2023 and cover
  source means, stage conversion, nulls, grouped annual requests and failure
  isolation. Those tests are recorded evidence, not fresh live verification or
  proof that the draft's 2020 example works.
- The existing PR description claims omitted historical series are described in
  the page, but the page does not contain that inventory. Reconcile the final PR
  description with what the revised page and verification actually establish.

Useful implementation evidence is in the CHMI provider directory, its packaged
`catalogue/`, `tests/test_data/cz_meta2.json`, CHMI recording fixtures, current
public API documentation and `docs/provider_ports/cz_chmi.md`. Historical notes
and fixtures need their dates and limitations preserved.

## Verification and acceptance evidence

Check every factual claim against current code, the packaged catalogue, or
authoritative sources, as appropriate to the claim. Recheck CHMI's institutional
roles, dataset definitions, coverage, time conventions, access conditions and
terms. A configuration value establishes current behavior, not by itself a
publisher's semantic promise. Preserve unknown facts instead of supplying an
inference. Avoid absolute claims such as “CHMI publishes no citation” unless the
evidence supports them; describe the limits of what has been established.

Execute every final Python snippet as written, in its documented order and
session context, through the current public API in the project's `uv`
environment. Use live retrieval where applicable and avoid treating a cached or
recorded response as a fresh source check. Verify all displayed output and the
behavior promised in the surrounding prose. Show a useful value preview and
issues, explain their actual meaning, and retain qualifications about possible
source revisions. Do not fabricate outputs or call an unexecuted example verified.

Keep a durable, appropriately scoped verification record containing the tested
revision, commands, dates, outputs, source references, and limitations. Clearly
separate live retrieval, offline catalogue inspection, recorded tests and any
unavailable source checks. If source access blocks required verification, report
the blocker rather than substituting recorded evidence and claiming completion.
Distinguish an upstream outage, unavailable observations and a library defect.

Use existing focused coverage and repository-native checks proportionately.
Review the complete final diff and evidence independently before requesting human
review. Success requires an accurate page, working final snippets, evidence for
its claims, a preserved index, and a PR description that accurately reports the
scope, verification and remaining limitations. Passing recorded tests alone is
insufficient.

## Mandatory code-defect stop gate

If implementation or verification reveals a code defect, stop the documentation
implementation. Open a GitHub issue labelled `bug`, assign it to `CooperBigFoot`,
and include reproduction steps, expected and actual behavior, the tested revision,
commands and supporting evidence. Use [#305](https://github.com/RivRetrieve/RivRetrieve/issues/305)
and [#324](https://github.com/RivRetrieve/RivRetrieve/issues/324) as examples of
precise reproduction and the distinction between public-path, recording-path and
upstream failures.

Do not fix production code under this vision. Do not change documentation,
examples, assertions or verification paths to conceal or work around the defect.
Preserve partial work and evidence, report the blocking issue, and wait until the
user reports that the defect is repaired. A code change or closed issue alone is
not permission to resume. After the user's report, reverify the affected path and
final examples, then continue. This gate applies to defects in verification
support as well as the ordinary retrieval path.

## Scope and human authority

Work on the existing provider documentation PR, its index integration, necessary
verification evidence and accurate PR description. Do not expand provider
capabilities, regenerate the catalogue to avoid a problem, fix production code,
or undertake unrelated documentation cleanup.

The user will review PR #295 before merging and provide feedback before the
implementation agent concludes. Present the updated PR and verification evidence,
then wait for that feedback and address it. An independent agent review does not
replace this human gate. The agent must not approve or merge PR #295 on the user's
behalf, even after receiving review feedback.

This is a standalone vision with no Program or Effort provenance. Publication of
this vision is separate from implementation. Merging the vision-only publication
PR does not authorize merging PR #295. Do not begin implementation as part of
vision publication.

# Vision: Lithuania monthly retrieval failure isolation

Related issue: https://github.com/RivRetrieve/RivRetrieve/issues/385

## Outcome and scope

A Lithuania observation request must retain successfully retrieved requested days
when another independently requested month fails. The result must explain exactly
which months failed, preserve source-call evidence, and never cache a failed month
as a successful answer.

This is a complete repair of #385, not a catch-and-continue patch. Redesign shared
retrieval contracts where needed to make acquisition, coverage, and provenance
correct together. RivRetrieve is pre-v0.1 with no users: backward compatibility
and minimizing the diff are not constraints. Correctness, clear responsibilities,
and faithful source evidence are the priorities.

Only this bugfix is in scope. Do not work on PR #293, revise its provider page,
resume its review, or take on unrelated issues, including #371 and #375. Necessary
shared-code changes and their regression tests are included; a general migration
or overhaul of other providers is not. Update directly affected contract
documentation where needed, without turning this into a documentation project.

## Confirmed defect and evidence

The investigation used production revision
`e12f9eec9f88476ec530b21c85d0b0aa4a676c91` on `main`.

### Publisher meaning

The [Meteo.lt API documentation](https://api.meteo.lt/) describes
`/hydro-stations/{station-code}/observations/historical/{date}`. It accepts
`YYYY-MM` and `YYYY-MM-DD` in UTC. Its historical section distinguishes:

- a particular measurement not taken: its field is `null`;
- no station measurements stored for the requested date: HTTP 404;
- daily mean stage (`waterLevel`, cm) and discharge (`waterDischarge`, m³/s),
  labelled by `observationDateUtc`.

A committed documentation capture is
`tests/test_data/lt_lhmt_terms_licence.html`. The historical section contains:
“Jei nurodytai datai nesaugomi jokie stoties matavimo duomenys, tai grąžinamas
404 Not Found atsakymas.” This is source-specific evidence, not permission to
interpret every HTTP 404 from every endpoint as harmless absence.

The separate historical-range endpoint reports stored-range endpoints. It does
not prove that every intervening month exists. Stations have different ranges,
some end mid-month, and some have no historical range. Do not hard-code the
first or last published year, infer publication from the current year, or use
range metadata as proof that a requested month succeeded.

### Live evidence reported in #385

On 2026-09-27, `nemajunu-vms` reported a historical range of
2000-01-01 through 2024-12-31. Public `rr.fetch` calls with
`cache="bypass", on_issue="ignore"` produced:

| Requested days | Returned rows | Failure |
| --- | ---: | --- |
| 2000-01-01..2000-01-05 | 0 | padding month 1999-12, HTTP 404 |
| 2000-01-03..2000-01-05 | 3 | none |
| 2024-12-27..2024-12-29 | 3 | none |
| 2024-12-27..2024-12-30 | 0 | padding month 2025-01, HTTP 404 |
| 2024-11-01..2024-12-31 | 0 | padding month 2025-01, HTTP 404 |

The failing results had no `provenance.calls_made`. Direct checks returned HTTP
200 for 2000-01 and 2024-12, and 404 for 1999-12 and 2025-01. These are dated
observations, not a promise that the publisher will never extend its range.

Additional local evidence exists under
`.worktrees/visions/lithuania-review-evidence/`: the reproduction script and log
in `defect/`, plus historical ranges and API documentation in `sources/`.
Those untracked files are supplementary, not prerequisites for implementing
this vision. The issue, committed source capture, and reproduction below carry
the essential evidence independently of that checkout.

### Deterministic reproduction

Using the committed
`tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json`, replay its real June
response and return synthetic HTTP 404 responses for all other requested months.
Inject that transport through the public fetch path's `discovery.HttpClient` seam.
Select `anyksciu-vms`, discharge, daily, mean; request receipts and bypass cache.

| Requested days | Actual transport calls | Rows / provenance calls / receipts |
| --- | --- | --- |
| 2023-06-03..2023-06-28 | June 200 | 26 / 1 / 1 |
| 2023-06-03..2023-06-29 | June 200, July 404 | 0 / 0 / 0 |
| 2023-06-01..2023-06-05 | May 404 only | 0 / 0 / 0 |

This was executed during discovery without live network access. It proves both
failure modes: leading padding failure prevents the desired month from being
requested, while trailing padding failure discards an already acquired response.
The synthetic 404s test library behavior; they are not claims about the live
availability of those months.

The existing targeted suite passed 129 tests during discovery:

```text
uv run pytest -q tests/test_source_failure_isolation.py tests/test_internal_window_planning.py tests/test_lt_lhmt_th_thaiwater_public.py
```

The existing Lithuania example chooses June 3..28, keeping padding inside one
month. Window-planning tests check month rendering, and source-failure tests
check independent-series isolation. They do not cover this defect.

## Causal chain and necessary design work

These paths are under `src/rivretrieve/_internal/`:

1. `driver.py` applies `_FETCH_WINDOW_PADDING = timedelta(days=2)` through
   `_padded_interval`. `window_planning.py` renders every touched month for
   Lithuania's `year-month` declaration in `providers/lt_lhmt/config.py`.
2. `providers/lt_lhmt/fetch.py` collects monthly payloads locally and returns only
   after every send succeeds. It does not return already acquired payloads when
   a later send raises, and it does not attempt subsequent months after a failure.
3. `_SourceResponseTransport.send` in `driver.py` converts a non-2xx response to
   `TransportFailure`. The driver catches that outside the provider fetch call
   and records failure over the whole requested interval for the affected scope.
4. Payload parsing, receipt retention, and payload-origin provenance happen only
   after fetch returns. Earlier successful responses never reach those steps.
5. Each Lithuania monthly payload also carries the **whole padded fetch window**.
   `provider_series.py:parse_mapped_series` uses that window for each outcome.
   The driver clips outcomes to the request and uses them for cache replacement.
   `_combine_replacements` merges same-window contributions and suppresses
   replacements overlapping failures.

The last point makes a superficial repair unsafe. Returning successful months
with only an issue for the failed month can claim the whole request succeeded,
including dates never retrieved. Refresh could then remove held observations
from failed months. Adding a whole-request failed outcome avoids false success
but prevents accurate caching of the independently successful months.

The repair must represent the actual coverage of each independently acquired
month and its success or failure. The engine owns calendar arithmetic and the
bounds used to distinguish requested coverage from padding. Bounds must not be
inferred from the first and last returned rows: an exhausted monthly response
can contain gaps or be empty.

Existing `SourceAcquisition` supports payloads, calls, issues, outcomes, and
failed requests, but its current failed-request handling is series-scoped and
assigns the whole requested window. It cannot be assumed to express precise
monthly failure without change. Also, the response wrapper currently discards
response retrieval metadata when constructing `TransportFailure`. Preserve
available call evidence rather than inventing an empty observation payload to
carry it. Choose the final types and stage interfaces from the repository's
responsibilities; these observations do not prescribe a particular class design.

## Settled behavior and constraints

- Continue acquisition of independent Lithuania months after a supported source
  failure. Keep successfully parsed observations from other months, including
  successes before and after a missing requested month.
- An unavailable requested month remains an identified failure with its actual
  interval, request identity, HTTP status when available, and reason. Return its
  issue alongside other months' observations under the existing caller-policy
  model. Do not replace warning/raise/ignore policy with blanket crashing or
  silent logging.
- A documented Lithuania no-data 404 for a month wholly outside the requested
  calendar interval is padding-only absence. Retain it in provenance without a
  warning or failed outcome for the requested interval. This exception requires
  the source-specific response meaning and engine-established partition bounds.
- Do not extend that exception to arbitrary HTTP errors, authentication failures,
  exhausted transport retries, unknown endpoint semantics, or malformed data.
  Keep their established failure classification and diagnostics. Independent
  successful months still survive supported failures.
- Preserve successful source-call provenance independently of receipt retention.
  With receipts requested, retain the exact successful publisher payloads. Keep
  failed call identity and available metadata traceable without fabricating
  response bytes, timestamps, observations, or successful empty outcomes.
- Keep HTTP failure, a successful empty observation response, an absent row,
  and a null measurement distinct. Keep unknown source facts unknown. Internal
  contract errors remain fatal regardless of caller issue policy.
- Preserve engine-owned uniform two-day outward padding, closed requested
  intervals, calendar-date clipping for daily products, and the runtime window
  invariants. Do not solve this by removing padding, adding provider-side window
  arithmetic, truncating the user's request, or guessing publication ranges.
- Scope independence correctly. An independently exhaustive month is not the same
  as a page in a dependent cursor transaction. Do not blindly invoke every
  provider once per rendered string or certify a paginated response as complete
  after a cursor failure. Necessary shared changes must preserve other providers'
  acquisition and coverage semantics.
- For bypass, reuse, and refresh, successful monthly intervals carry truthful
  evidence. Failed months must not establish coverage or erase held successful
  data. Preserve held data at its original retrieval vintage with the current
  diagnostics; do not relabel it as fresh success. A later acquisition can retry
  the failed month. Cache independently successful months at their true bounds,
  while retaining the existing inventory requirements for reuse.

The uniform padding constraint is documented in
`planning/visions/2026-09-01-the-engine-owns-the-window.md` and current
`docs/architecture.md`. The redesign should repair the mismatch between
acquisition isolation and coverage, not undo that separate window contract.

## Acceptance evidence

The implementation must provide deterministic end-to-end regressions through the
real engine and Lithuania provider, with recorded successful payloads and explicit
controlled failures. Merely testing a provider mock or observing a successful live
request is insufficient.

1. Reproduce the failure before repair and prove that published requested rows
   survive leading, trailing, and both-sided padding-only 404s. A leading failure
   must not prevent the requested months from being attempted. Final rows remain
   exactly clipped to the requested dates.
2. Exercise failed first, interior, and last **requested** months, with successful
   months on either side where applicable, and all requested months failing.
   Outcomes and issues name the failed intervals; successes remain usable. No
   failed month is described as successful empty coverage.
3. Exercise both daily mean discharge and stage, preserving source nulls, stage
   conversion from centimetres to metres, and source date labels. Distinguish a
   successful empty month, null measurements, and a failed month explicitly.
4. Assert successful provenance with receipts both omitted and included. Assert
   exact successful payload retention and failed-call traceability. Padding-only
   documented absence produces no warning about requested data; requested-month
   failure still follows caller issue policy.
5. Include non-404 failures and malformed successful responses. Keep established
   diagnostics, sibling-month isolation, and fatal internal-contract behavior.
6. Exercise bypass, reuse, and refresh, including a partially populated cache and
   explicit series scope. Failed months gain no success coverage and cannot erase
   held rows; successful months retain precise coverage. A subsequent successful
   acquisition of a previously failed month is not blocked by false cache proof.
   Do not rely on incomplete mapped inventories to hide an incorrect coverage claim.
7. Test partition bounds at month/year rollover and leap days. Test affected shared
   contracts against other providers, including dependent pagination, without
   widening this into unrelated provider migrations. Keep existing window,
   conversion, source-failure, receipt, and live-cache regressions passing.
8. Recheck the public boundary examples in #385 against the repaired code when
   the source is reachable. Record the current source ranges and statuses rather
   than assuming the September 2026 publication boundary is permanent. Report a
   live-service blocker explicitly; do not weaken the deterministic proof or
   resume PR #293 as part of verification.

Use the repository's `uv` workflow, library-specific complex-data assertions,
format/lint checks, `uv run ty check src`, and the full applicable test suite.
Do not suppress the intentional negative type-check fixture. Carry necessary
source evidence and regressions in the implementation so completion does not
depend on temporary investigation files or this conversation.

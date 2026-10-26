# Swiss API retrieval behavior

Deliver official BAFU retrieval that does not silently lose rows or misreport
coverage. This vision completes [Effort #562](https://github.com/RivRetrieve/RivRetrieve/issues/562)
when its acquisition contract, tested retrieval code and applicable evidence checks
are delivered. Publication alone does not complete the Effort. Provider activation
remains [#563](https://github.com/RivRetrieve/RivRetrieve/issues/563).

Work targets `port/swiss-official-api`, not `main`, under
[Program #545](https://github.com/RivRetrieve/RivRetrieve/issues/545).
The Program's later official-product scope supersedes the issue body's strict
Existenz-parity wording. Retrieve BAFU's published products; do not reconstruct
Existenz's historical short-interval stream.

## Scope and established context

Support acquisition for discharge, water level and water temperature across the
agreed archive routes: ten-minute/hourly means and daily/monthly/yearly
mean/minimum/maximum products, plus the separate recent raw feed. Availability
varies by station, parameter and period. Do not splice recent readings into archive
aggregates, calculate missing products, collapse parallel variants or reinterpret
source status codes.

Use the delivered [series definitions from #561](https://github.com/RivRetrieve/RivRetrieve/issues/561)
and the existing catalogue. At reviewed Swiss branch revision
`8ad836b451bb76d4ba0243397128936ffea4d14a`, `official_series.py` preserves archive
route/name identities, native unit bindings and independently established time
facts. The provider remains `CatalogueOnly`; the old `fetch.py` still implements
Existenz access, not the official API.

Continue the existing [private research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/swiss-source-access.md)
and retained evidence rather than starting another research ledger. Follow
[provider-port step 4](../../docs/maintenance/provider-ports.md#4-retrieval-behavior).
Earlier sampled probes are useful leads, not completed retrieval certification.

## Acquisition behavior

Use anonymous GraphQL acquisition through the existing provider-stage contracts.
Establish selectors, boundary inclusion, response envelopes, limits and failure
classification with genuine source evidence. Aggregate queries cannot currently
filter by `tsName`; preserve every returned variant rather than selecting one.
Unordered responses must not cause missing or duplicated boundary rows.

Omit explicit `limit`: documented omitted-limit behavior rejects overflowing
queries, whereas an explicit limit can return a capped prefix. Never mark such a
prefix as complete. Subdivide confirmed overflow into smaller disjoint intervals
through a narrow shared-engine extension. The engine owns child bounds and
rendering; the provider identifies source response meanings. Do not introduce a
provider-local date planner or a general scheduler.

Keep retrying the same request separate from splitting it into new requests.
Reuse shared transport retries and establish safe replay for read-only GraphQL
POST requests. Do not split arbitrary GraphQL errors or retry every HTTP 403 as
though it were a rate-limit response. Respect the published request limits;
request sizes and concurrency are implementation choices grounded in evidence.

Retain the overflowing parent call and its attempt evidence. If its children
complete successfully, do not report that recovered parent as a terminal failure.
If subdivision cannot resolve overflow, terminate with an explicit failed or
incomplete interval, never empty or apparently complete coverage. Establish the
source's usable timestamp precision and boundary behavior rather than inventing
a minimum split size.

Collect successful child responses alongside terminal child failures through
`SourceAcquisition`. Preserve each failure's identity, reason and actual interval.
An escaping exception at the driver's fetch-group boundary must not discard
successful siblings. Keep source failures separate from fatal internal contract
errors. Parse response envelopes at acquisition boundaries as needed for control
flow; keep observation normalization in the parser.

## Time, availability and cache behavior

Request and clipping behavior must respect both the API timestamp and the
aggregate calendar. API labels are UTC; daily/monthly/yearly aggregates use fixed
UTC+1 and interval starts. For example, February 2025 starts at
`2025-01-31T23:00:00Z` and ends at `2025-02-28T23:00:00Z`. Preserve the original
label while ensuring retrieval and clipping follow the established public window
contract and do not misclassify it merely by its UTC date. Verify exact boundaries
and adjacent requests, including summer. Keep the anomalous 7008 series' unknown
support explicit; do not assign ordinary daily support from its route alone.

Distinguish published nulls, absent rows, successful empty answers and failed
requests. A successful acquisition establishes only the coverage its response
contract supports, not continuous numeric observations or an exhaustive series
inventory. An empty recent response does not by itself prove retention expiry.

Live retention remains an unresolved publisher question. The seven-day and
roughly twelve-hour descriptions must not become an invented universal cutoff.
Record what source evidence establishes, expose relevant limits honestly, and
return any material capability blocker to the maintainer. Do not block independent
supported retrieval solely because an optional source fact remains unknown.

Reuse existing cache reuse, bypass and refresh behavior. Preserve retrieval
provenance; cached success is not proof that BAFU has not revised its publication.
Do not infer an archive revision horizon or immutability. Failed refreshes must
not erase previously successful data. Official data must not reuse Existenz cache
identities. Caching cannot reconstruct unseen expired observations.

## Delivery and acceptance

Deliver the acquisition contract in the continuing research record, official
retrieval code, and only the shared-engine changes needed to support it. Keep
`CatalogueOnly` registration until #563. Exercise assembled internal stages far
enough to prove request and clipping behavior without activating the public
provider. Coordinate any parsing needed for these proofs with the delivered
series definitions; do not turn this Effort into the full integration.

Protect these observable behaviors with focused tests:

- An overflowing request followed by successful children returns boundary rows
  exactly once, retains parent/child call evidence and has no terminal parent
  failure.
- A successful child survives a sibling failure; the failed interval and reason
  remain visible, including during refresh of held successful data.
- Unsplittable overflow terminates without creating successful or empty coverage.
- Date boundaries and clipping preserve the intended aggregate labels, including
  the fixed-UTC+1 calendar example, without changing source timestamps.
- Empty responses, null observations and failures remain distinct. Unrelated
  errors cannot trigger overflow splitting or successful coverage.

Reuse existing retry and cache contracts rather than duplicating their suites.
Use synthetic tests for engine mechanics and genuine retained inputs for source
claims and response behavior. Follow the [testing guide](../../docs/maintenance/testing.md)
and [evidence process](../../docs/maintenance/evidence.md), with independent review
of exact revisions before execution using private evidence. Run affected
source-independent tests and applicable full genuine-input checks for changed
source bindings. Missing mandatory evidence is blocked, not skipped acceptance.
Keep original responses and correspondence private; public code and artifacts
contain only approved material.

Report exact checks, supporting evidence, remaining source limits and the handoff
to #563. Request sizes, split mechanics, code layout and other reversible details
remain implementation choices. No national-download feature, runtime API/file
fallback, LINDAS integration, new cache architecture or provider activation is
included.

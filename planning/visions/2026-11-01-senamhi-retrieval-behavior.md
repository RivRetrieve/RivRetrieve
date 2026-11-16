# SENAMHI retrieval behavior

Deliver evidence-backed, tested request planning and source acquisition for
`pe_senamhi` under [Effort #606](https://github.com/RivRetrieve/RivRetrieve/issues/606)
and [Program #534](https://github.com/RivRetrieve/RivRetrieve/issues/534).
Requests must cover the requested date range without silently omitting windows
or treating failed requests as empty results.

Completing the research, acquisition code and verification described here completes
#606. Publishing this vision does not complete the Effort. Work targets
`port/pe-senamhi`; keep `main` unchanged pending the Program's final review.
Public observation retrieval remains disabled. Parsing and public API integration
belong to [#607](https://github.com/RivRetrieve/RivRetrieve/issues/607); final provider
verification and user documentation remain separate Efforts.

## Follow the existing retrieval contract

Build on the [offline catalogue](2026-10-31-senamhi-offline-station-catalogue.md)
and [series mappings](2026-11-01-senamhi-series-identity-and-physical-meaning.md).
Use the adopted unauthenticated SENAMHI JSON API, preserving PHISIS monitoring and
monthly station-archive identities. Do not revive the legacy HTML graph route.

The existing `fetch(start=..., end=...)` API requires a start and defaults the end
to the final instant of the caller's current local date. Follow that contract;
no new complete-history mode or historical-boundary discovery feature is required.
Do not clamp requests to an invented earliest date or stop traversing a requested
interval after an empty window. Catalogue associations, operational condition,
listed periods and sampled dates do not establish continuous historical coverage.

Keep the established series distinctions and physical unknowns. Do not infer time
zones, aggregation periods, timestamp meaning, named datums or missing-value rules
to make request planning work. Preserve source values and their published labels.

## Establish coverage for each route

Research and implement the selectors, anchors, date boundaries and request rules
needed for the supported routes. Check response caps, pagination if present,
retention, revisions and errors far enough to defend each adopted coverage claim.
Do not treat a successful HTTP response as proof of complete coverage.

- **PHISIS DAILY:** retained samples return September-to-August hydrological years.
  Verify anchor selection, year boundaries and leap-day behavior. The baseline is
  to request each hydrological year directly. Using `previous` to reduce requests
  is not a required optimization, and its date-axis and equivalence questions must
  not become assumptions in acquisition. Do not expose it as a new physical product.
- **PHISIS HOURLY:** establish the relationship between explicit anchors and returned
  intervals, including boundary behavior and historical access. One retained
  90-hour response does not establish a fixed whole-day window. Plan requests that
  cover the requested interval without gaps, with any overlap handled consistently
  with the shared contracts. Do not substitute the default recent window for an
  explicit historical request.
- **Monthly station archive:** establish `period=YYYYMM` selection and the meaning
  and reliability of period lists. Determine whether lists can safely restrict
  requests; a failed list is not an empty history. Check returned dates against
  request partitions and investigate the four retained future-dated monthly
  responses. Do not correct their dates, discard their values or label them
  forecasts without source authority. A monthly request partition does not imply
  monthly measurement frequency.

The catalogue campaign retained 510 failed period requests separately from two
successful empty lists. Five empty hourly windows still recognized their
station-variable products. Preserve these distinctions. Unknown source behavior
blocks the affected coverage claim or capability, not unrelated supported routes.
If a material limit cannot be resolved, report its consequence for the agreed
scope rather than silently narrowing the deliverable or claiming completeness.

## Reuse shared planning, transport and failures

The shared engine owns window arithmetic and clipping. Providers consume its
rendered bounds rather than shifting them privately. Inspect current contracts
before implementing; the following facts describe the target branch at the grill:

- `window_planning.py` already supports calendar months and fixed backward spans
  of whole days. Reuse these where source evidence establishes a fit.
- Its existing year planner uses January through December. Add the smallest
  evidence-required shared hydrological-year planning rule; do not hide this
  arithmetic in SENAMHI request code. Extend hourly planning only if verified
  source behavior requires it.
- `SourceAcquisition` supports successful payloads alongside bounded failed requests.
  Use the existing acquisition helpers so an individual failed year, hourly window
  or month retains its identity, reason and interval while independent requests
  can succeed. Do not replace this with a blanket crash or log-and-continue rule.
- The shared HTTP client already provides retries and minimum one-second spacing
  between request starts per client. Reuse one transport for related requests and
  maintain at most one request per second. This is not a process-wide limiter;
  add no separate limiter or policy framework without an established need.

Distinguish HTTP failures, failed source envelopes, malformed responses, successful
empty answers, published null values and absent rows. Classify no-data responses
only with applicable evidence. Fatal internal contract failures must still raise.
Do not interpret station conditions, alerts or envelope status as row quality.
Keep request origins and genuine bytes available through the existing stage
contracts. Leave reversible module organization and routine selector formatting
to implementation. No new public options, cache policy or series model is required.

## Evidence and verification

Follow [provider-port step 4](../../docs/maintenance/provider-ports.md), the
[evidence process](../../docs/maintenance/evidence.md) and
[testing guide](../../docs/maintenance/testing.md). Continue the existing private
[SENAMHI research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/pe-senamhi-source-access.md).
Use its exact retained collections and preserve earlier acquisitions unchanged.
Retain additional originals and receipts through the archive's established process
before adopting new source claims. Derived catalogue data cannot replace original
observation evidence.

Keep new source investigation bounded and paced at no more than one request per
second. The existing record reports access restrictions from cloud/datacenter
networks; unavailable access is a blocker, not an empty source response. Do not
require a full historical scan or live cloud-CI calls. Agency correspondence needs
explicit authorization. Keep bodies, restricted receipts and correspondence out
of public issues, logs, packages and artifacts.

Develop small test-first increments. Protect requested-range coverage, daily and
leap-year boundaries, verified hourly stepping, monthly selectors, failure
isolation and preservation of source distinctions at the simplest sufficient
level. Extend shared planner tests for any new rule. Use genuine retained responses
and independently established expectations for source-specific behavior; synthetic
tests establish code behavior rather than source completeness.

Run affected source-independent tests and applicable genuine-input checks at
reviewed exact revisions. Missing mandatory evidence blocks acceptance; a skipped
check is not a pass. Completion requires reviewed acquisition code, defensible
coverage and failure rules, retained supporting evidence and passing applicable
checks. Report exact revisions, limitations and the handoff to #607. Retrieval
must remain disabled until that integration work is completed.

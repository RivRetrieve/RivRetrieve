# Lithuania shared source acquisition

RivRetrieve must acquire a Lithuania historical station-month once when a request
selects both daily mean discharge and stage. Both products are published in the
same Meteo.lt document. Sharing that acquisition must preserve independent
per-series results, diagnostics, selection, and cache coverage.

Related defect: https://github.com/RivRetrieve/RivRetrieve/issues/389

Related documentation review: https://github.com/RivRetrieve/RivRetrieve/pull/293

This is a standalone repair vision, not a Program Effort. Target branch: `main`.

## Outcome and scope

The public API must deliver the sharing already declared by Lithuania's provider
and packaged catalogue. For each station-month requiring fresh acquisition, both
selected products must use one source request, not two identical requests. A
single-product request must still work without acquiring unrelated series.
Necessary padding months remain part of the engine's window planning.

This reduces avoidable source load. Issue #389 records Meteo.lt's limits as 180
requests per minute and a request not to exceed 20,000 per day per IP. The defect
is RivRetrieve's duplicated acquisition, not an upstream failure or a reason to
weaken the catalogue declaration.

Repair the shared-driver boundary as needed for Lithuania. Do not automatically
extend batching to other providers, introduce cross-station batching, or turn this
into a general performance project. Shared-code changes must preserve other
providers' behavior and failure isolation. No new public configuration is needed
to obtain the declared sharing. Leave reversible internal mechanisms to the
implementer; a global URL/content memoizer is not a substitute for correct
acquisition identity and evidence.

PR #293 remains a separate documentation review. After the production repair is
verified, report that it can resume and provide request-count evidence. Its owner
must reverify the examples and request-count wording before completing that PR.
This vision does not authorize merging PR #293 or replacing its review vision.

## Investigation evidence

Investigation used `main` at
`f08ea0a6da0185121f7d1e0e35bc84fc9c94cd4d`. The shared driver and Lithuania provider
were unchanged from issue #389's tested production revision, `ad06730`. File and
line references below describe that investigation revision.

The issue's live reproduction selects both products at `nemajunu-vms` for
2020-01-01 through 2020-01-07 with `cache="bypass"`. It returns 14 rows without
issues but makes four calls: December and January once per product. The required
result is two monthly calls, each attributed to both products, with the same
requested data.

Independent investigation reproduced the defect using the committed
`tests/test_data/lt_lhmt_anyksciu-vms_2023-06.recording.json`:

- Public `rr.find(provider="lt_lhmt", station="anyksciu-vms",
  frequency="daily", statistic="mean")`, followed by `rr.fetch` for June 3–28,
  2023 with cache bypass, sends two identical June requests. A counting replay
  transport was injected at `rivretrieve._internal.discovery.HttpClient`.
- The shared driver returns 52 clipped rows and two receipts for that selection.
- Calling the provider fetch stage directly with both products and the June
  monthly rendering sends one request and returns one payload identifying both
  station-product pairs. Parsing it yields 60 native rows before clipping.
- Changing the first observation's `waterLevel` to a nonnumeric string in that
  shared payload yields 30 discharge rows, a successful discharge outcome, and an
  unsupported stage outcome. Sharing bytes does not inherently couple parsing
  success across products.
- `uv run pytest -q tests/test_lt_lhmt_live.py
  tests/test_source_failure_isolation.py` passed all 10 tests despite duplication.

One preliminary public probe patched the driver rather than the public
composition boundary and reached the live service, returning two successful
calls. The corrected replay probe independently counted the same two requests.
No production changes were made during investigation. The temporary probes were
run in memory; the committed recording and the steps above are the reproducible
inputs, not an assumed unpublished script.

## Cause and existing capabilities

`src/rivretrieve/_internal/discovery.py:885–893` supplies all selected products for
a station to observations. The loss of sharing occurs later:

- `driver.py:1118–1119` iterates station-product pairs.
- `driver.py:1325–1340` plans one product and calls provider fetch with singleton
  station and product tuples.
- `providers/lt_lhmt/fetch.py:64–69` already groups products by rendered window,
  but the driver never gives it both products.
- The resulting payload already supports multiple station-product pairs
  (`engine.py:319–327`; Lithuania fetch at line 99).
- `provider_series.py:115–205` parses mapped series independently by narrowing
  the payload to each product before native parsing and recording outcomes.

The singleton loop dates to `62e3d06c` (evidence-aware source-series retrieval).
That history identifies the boundary to investigate, not permission to undo the
source-series contracts introduced there.

## Contracts the repair must preserve

Separate compatible source acquisition from per-series accounting. Simply
passing more products at the existing call site is insufficient:

- Scope, known identities, physical-fact selection, requested intervals, and
  cache eligibility are computed per pair (`driver.py:1118–1149`). Downstream
  payload defaults, row filtering, outcome filtering, and cache replacement also
  use that pair scope (`1570–1573`, `1610–1617`, `1676–1695`, `1723–1747`).
- Preserve each product's time semantics, engine padding, rendered bounds, and
  clipping axis. Do not collapse incompatible source work merely because it
  belongs to one public request.
- Cache reuse must avoid unnecessary fresh work for a fully reusable pair. Mixed
  reusable and fresh products must retain correct selection and attribution.
  Incidental co-published fields in fetched bytes do not authorize refreshing
  an unrequested or already-reused series.
- Only independently successful or successful-empty intervals establish fresh
  coverage and replace held rows. Failed or unsupported reacquisition must
  retain held successful values and their original retrieval vintage. Preserve
  sibling physical facts, inventories, and successful months.
- Keep null values, absent observations, successful empty results, and failed
  requests distinct. Preserve source identity, units, unknown time support, and
  established conversion. Do not infer quality, averaging-day boundaries, or
  other unpublished facts.
- Preserve the #387 repair: a historical monthly 404 wholly outside the requested
  dates remains in provenance without a requested-data warning or failed outcome.
  Requested-month failures and other padding failures remain diagnostic, without
  discarding independent successes.
- Source failures retain their affected series, interval, identity, and reason.
  Fatal internal stage-contract errors still raise regardless of issue policy;
  do not hide them as ordinary source issues.

### Calls and receipts

One physical source attempt must not become two provenance calls simply because
it serves two products. Evidence must identify all affected selected series.
Distinct real attempts, including retries to the same URL, must remain distinct.

Successful call provenance currently follows payload origins
(`driver.py:181–216`). Receipt entries likewise follow received payloads, not an
intrinsic one-receipt-per-series rule (`1570–1578`). Do not preserve duplicate
network requests merely to satisfy old receipt counts. Retained publisher bytes
must remain exact, correctly attributed, and available when receipts are requested;
call evidence must remain available when receipts are omitted. The representation
must consistently distinguish shared acquisition from per-series outcomes.

Two additional risks require explicit tests:

1. Lithuania creates a separate failed-request UUID for each product affected by
   one failed grouped request (`lt_lhmt/fetch.py:78–94`). The driver serializes
   each event as a call (`1464–1489`) and links outcomes to those events. Preserve
   separate series failures without pretending that two HTTP attempts occurred.
2. Cached calls are looked up and appended per pair (`driver.py:832–874`, `1208`).
   A stored shared call may therefore appear twice when both products are reused.
   This duplication risk was identified by inspection, not reproduced. Test it
   and retain truthful historical attribution without inventing a fresh time.

## Tests that need deliberate revision

`tests/test_lt_lhmt_th_thaiwater_public.py:47–95` currently asserts two transport
requests and two receipts for both providers. Change the Lithuania duplication
expectation without assuming Thaiwater is authorized for new batching.
`tests/test_lt_lhmt_live.py:78–101` also asserts two receipts.
`tests/test_internal_driver.py:264–346` requires singleton products and two fetches;
retain its immutable rendering and per-product planning guarantees while revising
any assumptions incompatible with safe Lithuania sharing.

Existing Lithuania monthly-isolation tests mostly exercise products separately.
Extend relevant cases to both products. Preserve the live-cache, physical-cache,
source-failure, and fatal-contract regression tests, not just row-count assertions.
Use Polars and other library-specific equality assertions for complex results.

Acceptance evidence must exercise the public path with a counting transport and
check both actual attempts and their provenance. Cover:

- One and multiple padded months with both products, plus single-product controls.
- Multiple stations with independent success and failure; no new cross-station
  batching is required.
- Receipts included and omitted, with exact bytes and correct attribution.
- Bypass, reuse, and refresh; warm and cold selections; mixed cache eligibility;
  cached shared-call evidence; failed refresh preserving held values and vintage.
- A malformed or null field and an absent observation while independent data
  remains valid; source-level empty responses and failed requests remain distinct.
- Requested-month versus padding-only 404, other HTTP/network failures, and
  independent successful months in the same request.
- A fatal internal parser-contract defect that still raises.

Check rows and physical facts, inventories, outcomes and failure reasons, coverage,
and held retrieval times alongside the request counts. The expected result is
less network work, not less evidence or weaker isolation. Run the affected suites,
the repository test suite, and normal lint/type checks through `uv`; distinguish
pre-existing failures from regressions. Fresh live checks, if needed, should be
small and respectful of source limits; recorded replay is the primary repeatable
regression proof.

## Wider risks, not additional delivery scope

Inspection found grouping blocked by the same singleton boundary in Thaiwater,
Czech CHMI, and Swiss FOEN; Bosnia also repeats shared metadata acquisition. These
are structural observations, not measured live performance claims or instructions
to repair all providers here. Several of those fetchers call transport directly
and return accumulated payloads only after completing all work. Broadening their
acquisition groups could lose earlier successful work when a later request raises.
Preserve their current isolation unless separately scoped work establishes a safe
change. Report any newly discovered blocker rather than silently expanding this
vision into a provider-wide redesign.

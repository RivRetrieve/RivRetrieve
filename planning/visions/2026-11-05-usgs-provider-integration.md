# USGS provider integration

Make the established USGS scope work reliably through ordinary `rr.find` and
`rr.fetch`, including supplied long historical ranges. Complete provider-port
step 5 in [Effort #628](https://github.com/RivRetrieve/RivRetrieve/issues/628)
within [Program #624](https://github.com/RivRetrieve/RivRetrieve/issues/624).
Verified implementation of this vision completes #628; publication leaves it open.

## Scope and design freedom

Keep the existing public API and all six products: `discharge_daily_mean`,
`discharge_instantaneous`, `stage_daily_mean`, `stage_daily_min`,
`stage_daily_max`, and `stage_instantaneous`. Preserve the established catalogue
scope across 50 states and DC, supported Canadian daily stations, continuous-only
and non-stream locations, and retained historical identities. A catalogue entry
does not guarantee observations for a requested period or scientific suitability.

Build on the completed station-access fix (#623), catalogue expansion (#627),
and retrieval research (#631). The provider is already registered and its six
products already use the public retrieval path. This effort closes demonstrated
integration gaps rather than assuming that missing infrastructure must be built.

Refactoring or rewriting existing code is permitted when a better design serves
this outcome. The earlier preference against a provider rewrite is not a binding
restriction. Keep changes proportionate, explain the design improvement, and
preserve the agreed public behavior and source fidelity. Do not retain a flawed
design merely to minimize the diff or expand scope to justify a rewrite.

Do not add products, public station-registration interfaces, automatic historical
range discovery, alternate observation routes, or scientific suitability filters.
Automatic full-history acquisition remains downstream. Full provider verification
in #626 and user documentation in #625 remain separate; this effort still requires
verification of its own changes and accurate documentation of changed interfaces.

## Correct continuous request partitioning

The current continuous declaration in
[`config.py`](../../src/rivretrieve/_internal/providers/usgs_nwis/config.py)
sets a capped span of `1100`. The shared planner interprets this as **days**.
Earlier source-access and retrieval vision references to hours are incorrect.
The completed retrieval research reports publisher guidance allowing three years
per continuous query and recommending yearly queries for performance. Neither
statement establishes a rolling retention horizon.

Replace the unsupported 1,100-day span with source-supported roughly yearly
partitions. Follow the yearly recommendation instead of maximizing request size
against the three-year ceiling. The implementing agent chooses the exact
calendar or duration mechanics using the source evidence and existing shared
planner. Do not blindly substitute 1,095 days or change shared units to hours.

The shared engine owns window arithmetic and rendering. Providers consume its
bounds without shifting them. Cover the full supplied interval, including leap
years, endpoint conventions and adjacent partitions, without silent omissions or
duplicate logical observations. Verify independently expected emitted bounds,
including the actual acquisition bounds after any padding; do not derive expected
results from the requests being tested. Explain the chosen units and any changed
constants. A successful small request alone does not validate a duration limit.

## Preserve retrieval and storage contracts

Apply the established acquisition contract to the existing public path:

- Preserve exact native network-qualified location and source-series identities.
  Explicit selections restrict retrieval; unrestricted selections retain matching
  siblings without choosing a preferred series.
- Preserve daily date labels without inventing timezone or temporal support.
  Preserve source offsets for continuous observations while comparing acquisition
  instants on the UTC axis. Keep established units and physical meaning.
- Follow every valid next link. A first-page success cannot establish completion
  of a paginated request. Preserve source-call origins and original page receipts.
- Keep published null values, absent rows, complete empty responses, unresolved
  explicit selectors and failed requests distinct. Retain the identity and reason
  of supported failures alongside independent successful series and intervals.
  Internal stage-contract violations remain fatal.
- Never publish incomplete acquisition or refresh as complete cache coverage.
  Preserve held successful observations and their original retrieval provenance
  when reacquisition fails. Reuse must retain original receipts and source facts.
- Keep optional credentials optional, preserve polite request discipline, and
  honor publisher Retry-After responses.

Current fetch and cache code already implements substantial parts of these
contracts. Inspect and reuse it and its tests; fix demonstrated gaps. Bounded
read-only inspection during discovery confirmed the span mismatch, not another
specific runtime defect. It did not execute tests or certify the whole provider.

## Evidence and completion

Use the [provider-port guide](../../docs/maintenance/provider-ports.md),
[testing guide](../../docs/maintenance/testing.md), and
[evidence process](../../docs/maintenance/evidence.md). The continuing private
[USGS research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/usgs-source-access.md)
contains the corrected retrieval findings, original-response references, executed
replays, and limits. Later retrieval findings supersede the earlier hours claim.
Coordinate newly exposed physical-interpretation questions with #630; do not infer
missing source facts to make an integration pass.

Start with a representative public path and extend checks to the six products and
real source differences. Reuse focused coverage in
`tests/test_usgs_observation_acquisition.py`,
`tests/test_usgs_continuous_cache_axis.py`,
`tests/test_usgs_nwis_public_routes.py`, and shared planner tests. Develop fixes in
small test-first increments with independent expectations. Required outcomes are:

1. Public selection and supplied-date retrieval preserve the established scope
   and six products with corrected continuous request partitioning.
2. Focused checks establish emitted boundaries, pagination, explicit/unrestricted
   identities, failure isolation, cache reuse and incomplete-refresh behavior,
   and receipt preservation for affected paths. Reuse existing coverage where it
   already proves a requirement rather than duplicating it.
3. Applicable genuine-response checks pass on reviewed revisions through the
   existing private evidence process. Distinguish synthetic tests, genuine replay
   and live observations. Reuse retained originals where they support the changed
   path; collect missing evidence rather than manufacturing replacements.
4. Report changed behavior, design choices, executed checks and remaining limits
   on #628, retaining original evidence and detailed findings privately.

The existing continuous-only witness establishes a complete empty interval, not
positive observations or absence of historical data. Complete cursor traversal
establishes the finite returned request, not immutable snapshots or exhaustive
history. Do not strengthen these claims during integration. Unavailable mandatory
evidence blocks acceptance. In particular, the retrieval research reported a
fetch timeout for a catalogue-source collection; it did not invalidate or repeat
#627's certification. Resolve access if that exact input is required for changed
boundaries, without substituting derived data for originals.

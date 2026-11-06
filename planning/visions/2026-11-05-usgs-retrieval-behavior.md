# USGS retrieval behavior

Establish an evidence-backed acquisition contract for reliable retrieval over
user-supplied dates, including long historical ranges. This completes retrieval
research in [Effort #631](https://github.com/RivRetrieve/RivRetrieve/issues/631)
within [Program #624](https://github.com/RivRetrieve/RivRetrieve/issues/624).
Verified completion of this vision completes #631; publication leaves it open.

The result is a defensible account of what a successful retrieval establishes,
which source limits apply, and what implementation changes are needed. This is
provider-port step 4, not a provider rewrite or delivery of the later integration
and full-verification efforts.

## Scope and boundaries

Cover the six existing products: `discharge_daily_mean`,
`discharge_instantaneous`, `stage_daily_mean`, `stage_daily_min`,
`stage_daily_max`, and `stage_instantaneous`. Preserve the Program's 50-states-plus-DC
scope and previously supported Canadian daily stations. Include continuous-only
and non-stream monitoring locations without treating source classification as a
judgement of scientific suitability.

Build on the completed source/access work in [#629](https://github.com/RivRetrieve/RivRetrieve/issues/629),
station-access fix in [#623](https://github.com/RivRetrieve/RivRetrieve/issues/623),
and catalogue expansion in [#627](https://github.com/RivRetrieve/RivRetrieve/issues/627).
Catalogue presence, including retained historical series identities, does not
establish retrievable observation history.

Automatic full-history acquisition remains downstream. Do not add new quantities,
derived products, station-registration interfaces, or automatic historical-range
discovery. Investigate historical access enough to establish the limits of
requests for supplied dates. Do not promise an observation on every date or a
stable historical snapshot.

## Acquisition contract to establish

Use source documentation and representative genuine responses to establish:

- Selectors for monitoring locations, products and explicit published series,
  including unrestricted retrieval of matching sibling series without choosing
  a preferred series or collapsing identities.
- Daily date boundaries, continuous time boundaries and splitting of long
  requests. Providers consume shared-engine bounds without shifting them.
- Pagination, response caps, request limits and termination conditions. A
  successful first page must not stand for a complete request. Determine what
  exhausting the publisher's pages supports within the requested scope.
- Empty-answer meanings. Keep a published null value, an absent observation,
  an empty answer for an established series, an unestablished selector, and a
  failed request distinct. An empty interval does not prove that a station has
  no historical observations.
- Failure isolation, including later-page failures. Preserve independent valid
  results and the failed request's identity and reason; incomplete acquisition
  must not be certified complete. Internal contract errors remain fatal.
- Historical-access and rolling-retention limits, and source revisions that
  affect repeated requests or consistency across pages. Distinguish observed
  behavior from a documented guarantee. Report unknowns without inventing a
  retention horizon, immutable history, or snapshot-consistency guarantee.

Existing code in
[`fetch.py`](../../src/rivretrieve/_internal/providers/usgs_nwis/fetch.py) already
implements cursor-chain checks, explicit series selection, finite-window empty
outcomes and partial-failure handling.
[`config.py`](../../src/rivretrieve/_internal/providers/usgs_nwis/config.py)
declares inclusive daily windows and continuous spans capped at 1,100 hours;
requests currently specify a 10,000-row page limit. These are investigation
starting points, not proof of publisher guarantees. In particular, the
1,100-hour cap is a request-span constraint, not an established retention horizon.
Recheck current code and upstream findings before adopting claims.

Preserve established access conditions from #629, including optional credentials,
polite rate discipline and publisher retry-after handling. Do not introduce an
alternate observation route or infer missing temporal or physical meaning to
make a request appear supported. Coordinate interpretation questions with
[#630](https://github.com/RivRetrieve/RivRetrieve/issues/630).

## Evidence and completion

Follow [provider-port step 4](../../docs/maintenance/provider-ports.md) and the
[maintainer evidence process](../../docs/maintenance/evidence.md). Extend the
continuing private record
[`research/usgs-source-access.md`](https://github.com/RivRetrieve/verification-evidence/blob/main/research/usgs-source-access.md)
rather than creating a parallel research system. Retain original responses and
acquisition provenance through the archive's intake process. Keep controlled
material and credentials out of public files and logs. Review exact revisions
before executing tools with private inputs.

The reviewed research does not establish full-history availability or cross-page
snapshot consistency. Bounded single-page examples cannot prove multi-page
completion or all continuous behavior. First inspect existing route recordings
and tests; reuse evidence that actually supports the claim and collect only the
missing material. Synthetic failure tests can establish library behavior but
cannot establish source guarantees.

Completion requires:

1. A cited acquisition contract covering the six products and the behavior above,
   with genuine evidence for material source claims and explicit limits on what
   each observation proves.
2. An account of existing implementation behavior against that contract. Reuse
   focused coverage such as `tests/test_usgs_observation_acquisition.py`,
   `tests/test_usgs_continuous_cache_axis.py`, and public-route tests. Distinguish
   inspected code, executed tests, genuine replay and live checks.
3. A concrete handoff of necessary provider or shared-engine changes and any
   unresolved blockers to [#628](https://github.com/RivRetrieve/RivRetrieve/issues/628).
   Production integration, full port verification in
   [#626](https://github.com/RivRetrieve/RivRetrieve/issues/626), and user-facing
   documentation in [#625](https://github.com/RivRetrieve/RivRetrieve/issues/625)
   remain separate. This vision does not require delivering those efforts.
4. A concise, disclosure-safe summary on #631 linking the continuing research
   record, established limits, verification performed and downstream work.

Unknown source facts may remain unknown when retrieval can represent them
honestly. If a material completeness claim would require guessing, report the
affected capability as blocked and bring the scope trade-off to the maintainer.
Unavailable mandatory evidence is a blocker, not a passing check. Obtain
separate authorization before sending agency correspondence.

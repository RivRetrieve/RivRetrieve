# Swiss API provider integration

Make official BAFU observations available through RivRetrieve's normal `ch_foen`
discovery, retrieval and cache interfaces, and remove the superseded Existenz
implementation. This vision completes [Effort #563](https://github.com/RivRetrieve/RivRetrieve/issues/563)
when the integration and its applicable checks are delivered. Publishing this
vision does not complete the Effort.

Work targets `port/swiss-official-api`, not `main`, under
[Program #545](https://github.com/RivRetrieve/RivRetrieve/issues/545).
The Program's later official-product scope supersedes the issue body's strict
Existenz-parity requirement. Retrieve BAFU's products without reconstructing
Existenz's historical short-interval stream.

## Starting point

Steps [#559](https://github.com/RivRetrieve/RivRetrieve/issues/559),
[#560](https://github.com/RivRetrieve/RivRetrieve/issues/560),
[#561](https://github.com/RivRetrieve/RivRetrieve/issues/561) and
[#562](https://github.com/RivRetrieve/RivRetrieve/issues/562) are delivered.
At Swiss branch revision `d15bc310504cd9991625827bf14d635c71523e3b`:

- The packaged official catalogue supports offline discovery and preserves
  witnessed products, raw variants and explicit unknowns.
- `official_series.py` supplies shared series definitions.
- `official_config.py`, `official_fetch.py` and `official_parse.py` provide official
  request configuration, acquisition and parsing. Shared behavior supports
  overflow subdivision, independent failures and calendar-aware retrieval/cache
  handling.
- `declaration.py` deliberately remains `CatalogueOnly`. The older Swiss
  configuration, fetch and parse modules still contain the Existenz implementation.

Build on those deliveries and their linked evidence. Follow
[provider-port step 5](../../docs/maintenance/provider-ports.md#5-provider-integration)
and continue the existing
[private research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/swiss-source-access.md).
Do not restart source research or introduce a second evidence record.

## Deliver the replacement

Connect the catalogue, official configuration, window declarations, fetch/parse
stages and provider registration through the existing public APIs. Use anonymous
GraphQL access. Reuse shared conversion, clipping, assembly and storage.

Support discharge, water level and water temperature across the agreed archive
routes: ten-minute/hourly means and daily/monthly/yearly mean/minimum/maximum
products, plus the separate recent raw feed. Availability varies by station,
parameter and period. Preserve the delivered catalogue identities; do not invent
station/product availability or promise an exhaustive inventory.

Start with a representative public end-to-end retrieval and extend to the agreed
products and real source differences. Registration alone is insufficient: users
must be able to discover products, retrieve observations and use the normal cache
policies with faithful results and provenance.

Remove the obsolete Existenz implementation, its exclusive configuration and tests,
and obsolete runtime wiring. Retain shared behavior and useful assertions by
adapting them to the official integration where appropriate. Do not keep an
Existenz fallback, compatibility layer or credential requirement. Historical
research records remain evidence, not runtime dependencies. Official observations
must never reuse Existenz cache identities or be populated from old cached
Existenz data; removal does not require deleting users' stored data.

Keep distinct archive variants and the recent feed separate. Preserve native unit
bindings, original timestamps, published values and statuses, and explicit unknown
physical facts. Do not splice products, calculate unpublished products, select a
preferred variant, or rank source quality. Published nulls, absent rows and failed
requests remain distinct. Supported source failures must retain their identity
and reason alongside independent successful results; fatal internal contract errors
must still raise.

Use the established UTC labels and fixed-UTC+1 aggregate calendar correctly through
public requests, clipping and cache reuse. Preserve the unusual 7008 series'
unknown temporal support. Recent retention and exact per-series recent durations
remain unknown; do not invent a cutoff or interval, or claim that caching restores
unseen expired observations. Return to focused research if integration exposes a
required fact that the delivered definitions cannot establish.

## Acceptance and handoff

Protect observable public behavior with focused tests using the
[testing guide](../../docs/maintenance/testing.md). Extend existing contracts rather
than duplicating the completed lower-level suites. Demonstrate:

- Offline selection reaches official retrieval without Existenz requests or
  credentials, across the supported archive routes and separate recent feed.
- Public results preserve distinct variants, unit conversion, source timestamps
  and established calendar boundaries, including adjacent requests and summer.
- Independent success survives a source failure, and failures, empty answers and
  published nulls remain distinguishable.
- Cache reuse, bypass and refresh preserve official identity and provenance;
  failed refreshes do not erase held successful data, and old Existenz observations
  cannot satisfy official requests.

Use representative genuine retained inputs for source-specific integration claims,
including recent access. The #562 handoff explicitly did not claim exact recent
single-parameter runtime replay; do not treat its internal-stage checks as proof of
that public path. Follow the [evidence process](../../docs/maintenance/evidence.md),
review exact revisions before private-evidence execution, and run affected
source-independent tests plus applicable full genuine-input checks. Missing
mandatory evidence blocks acceptance. Keep controlled inputs and correspondence
out of public code, logs and artifacts.

Full-port verification remains [#564](https://github.com/RivRetrieve/RivRetrieve/issues/564)
and the user-documentation finish remains
[#565](https://github.com/RivRetrieve/RivRetrieve/issues/565). Those separate Efforts
do not defer integration checks or justify leaving changed interfaces and access
requirements misleading. Keep documentation accurate for changes made here without
expanding into the full provider-page work.

Report the delivered public behavior, exact checks, evidence limits and handoff to
those Efforts. Code layout, wiring details and test mechanics remain implementation
choices. No new public retrieval interface, national-download feature, runtime
API/file fallback, LINDAS integration or new cache architecture is in scope.

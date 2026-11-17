# NRFA provider integration

Make the ten agreed NRFA flow and stage products available through RivRetrieve's
public discovery, retrieval and series-inspection APIs. Users should be able to
select NRFA stations and products, retrieve published observations, and inspect
their identities and source annotations without using provider internals.

This vision delivers [#590](https://github.com/RivRetrieve/RivRetrieve/issues/590).
Completing and verifying this integration completes that issue; publishing this
vision does not. [#347](https://github.com/RivRetrieve/RivRetrieve/issues/347)
coordinates the port and its later verification, documentation and final review.

## Starting point

Steps 2–4 have delivered the offline catalogue, series interpretation and tested
source-acquisition code on `port/uk-nrfa`. At the Step 4 merge, `3eba750d`,
`src/rivretrieve/_internal/providers/uk_nrfa/declaration.py` still declares
`CatalogueOnly()`, so public observation retrieval remains unavailable.

Use the existing `uk_nrfa` modules: `config.py` provides configuration, window
declarations and shared peak-product acquisition groups; `fetch.py`, `parse.py`
and `series.py` provide acquisition, parsing and source interpretation. Connect
these to the existing provider registration and shared engine contracts. Routine
wiring and focused integration-test design belong to the implementing agent.

The [Step 4 handoff](https://github.com/RivRetrieve/RivRetrieve/issues/594#issuecomment-6919484483)
and the continuing private
[research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/nrfa-source-access.md)
carry request rules, evidence references and remaining source limitations. Follow
`docs/maintenance/provider-ports.md`, `docs/maintenance/testing.md` and
`docs/maintenance/evidence.md`; do not duplicate source research or introduce a
separate verification system.

## Preserve the agreed source contract

Support all ten current API products: `gdf`, `ndf`, `gmf`, `nmf`, `gauging-flow`,
`gauging-stage`, `amax-flow`, `amax-stage`, `pot-flow` and `pot-stage`. Current means
the archive served at retrieval time, not real-time observations. Keep NRFA
separate from EA and preserve each published series identity.

- Preserve published values, explicit nulls, absent rows, source flags and series
  annotations. Do not filter rejected observations or interpret source quality as
  a ranking. Keep failed requests distinct from empty results.
- Retain established units and physical facts, and retain unknown time zones,
  daily water-day definitions, stage datums and other unresolved source semantics.
  Monthly labels retain their nominal month-start carriers and verbatim source
  labels; do not invent monthly temporal support.
- Preserve the adopted request rules: inclusive date windows for daily and
  event/gauging products, unwindowed monthly acquisition followed by shared
  clipping, and shared per-station peak metadata acquisition for peak products.
  Reuse shared conversion, clipping, assembly and storage.
- Preserve supported source failures alongside independent successful results.
  Fatal internal contract errors must still raise.
- Integrate observation caching consistently with the established NRFA terms
  and attribution rules. The recorded client performance-cache limit is at most
  30 days; `ProviderConfig.cache=None` is not a licence exemption. Keep source
  availability, cache policy and user-held results conceptually distinct. Do not
  silently choose a more permissive licence or claim new retention permission.

Rainfall, numbered bulk peak-flow releases, enquiry-only records, automatic
metadata refresh, derived replacement products and automatic stitching with EA
remain outside scope. Do not claim water-temperature support or gap-free histories.

## Observable completion

Establish a representative end-to-end path through the public API, then extend
coverage to all ten products and their real source differences. Focused tests
must demonstrate that:

- Public `rr.find`, `rr.fetch` and `rr.series` expose the supported NRFA scope
  through normal library use, including the existing offline catalogue.
- Results preserve identities, timestamps, values and annotations through the
  complete engine path, including daily, monthly and irregular products.
- Window handling does not silently lose observations at the adopted boundaries;
  shared peak metadata remains attached to the relevant products.
- Empty responses, explicit null values, absent rows and failed requests remain
  distinguishable, and an isolated supported source failure does not discard
  independent successful results.
- Cache behavior respects the established terms and does not change the source
  interpretation or conceal supported failures.

Use the simplest meaningful tests and the repository's existing contracts.
Registration alone is insufficient. Run affected source-independent tests and
checks appropriate to the changed boundaries. Where genuine retained inputs are
required, use the private archive's reviewed process; unavailable mandatory
evidence is a blocker, not a passing check. Keep originals and controlled material
out of the public repository and artifacts.

Full completed-port verification and the ten-gauge CAMELS-GB comparison remain
in [#583](https://github.com/RivRetrieve/RivRetrieve/issues/583). User documentation
remains in [#593](https://github.com/RivRetrieve/RivRetrieve/issues/593). These
boundaries do not excuse missing tests or inaccurate interface documentation for
changes made here.

## Delivery boundary

Keep implementation and corrections on `port/uk-nrfa`. Do not merge the port into
`main`: Thiago's explicit approval under
[#597](https://github.com/RivRetrieve/RivRetrieve/issues/597) remains required.

Return to the maintainer if evidence requires narrowing scope or accepting a
meaningful limitation. Reopen settled source decisions only when new evidence
warrants it. Leave reversible wiring and test mechanics to implementation rather
than adding new user-facing choices or speculative architecture.

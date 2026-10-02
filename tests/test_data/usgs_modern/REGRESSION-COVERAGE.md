# Active regression coverage

The retired WaterML fetch/parse tests asserted the dv/iv request protocol,
methodID/methodCode blocks, sentinel markers and naive WaterML daily timestamps.
Those are not modern API contracts. Their original tests remain in Git history;
all original source recordings and provenance remain preserved in the private archive. No retired
provider implementation is kept as a test-only duplicate or runtime fallback.

Current protections:

- `test_usgs_modern_parse.py`: station/parameter/statistic/unit contradictions;
  mandatory values, booleans, finite decimals, present nulls; malformed containers;
  independent siblings; identity vs record IDs; exact descriptions; timestamp
  offsets/date labels; unknown statistics and exact physical predicates.
- `test_usgs_observation_acquisition.py`: engine renderings, source coordinates,
  receipts, optional source fields, failure identity, pagination/security,
  late page/chunk failures, explicit subsets and successful empty coverage.
- `test_usgs_nwis_public_routes.py`: all six actual modern routes, conversions,
  clipping, receipts and positive cache reuse/refresh.
- `test_public_series_cache.py`: subset vs all, failed refresh, newly observed
  identity, explicit empty answer, native cache and bundle round trips.
- `test_usgs_modern_discovery.py`: offline variants, ended sibling, exact v1
  multi-page receipts, all-series cache reuse, broad unknown-statistic access.
- `test_usgs_artifact_boundaries.py`: non-destructive legacy artifact refusal
  and independent French/USGS mixed-provider identity fields.

Raw legacy counts and method-description checks do not exercise the current
provider and are retired. Their original inputs remain archived. The bounded
historical-to-modern comparisons in `test_usgs_modern_evidence.py` remain.
No legacy method ID is joined to a modern series through coincident values or dates.


Shared tests keep their behavioral contracts while replaying the active service:

- `test_live_cache.py`: all fourteen controls remain, including source vintage,
  bypass non-mutation, incomplete-scope reacquisition, fewer/empty refresh,
  interrupted publication, fatal parse boundaries, and policy-after-publication.
- `test_series_driver.py`: payload contributions, partial interval proof,
  fact-segment filtering, ambiguous outcome rejection before writes, and
  independent nonconflicting rows remain tested.
- Inventory, partial-explicit-scope, physical-cache-scope and bundle tests retain
  subset/all intent, unknown selectors, round trips and independent providers.
- Unit normalization and measurement tests retain dimensional rejection and
  finite numeric controls. Modern null values replace WaterML sentinel protocol
  tests; an ordinary negative modern number is not silently turned into null.
- Executable README, usage and CAMELS examples keep literal output contracts,
  all non-USGS workflows, exact source comparisons and saved-result checks.

Authored partial-window over-response controls identify themselves as such;
they do not claim that a publisher issued those requests. Actual documentation
requests have separate exact-coordinate recordings and acquisition manifests.

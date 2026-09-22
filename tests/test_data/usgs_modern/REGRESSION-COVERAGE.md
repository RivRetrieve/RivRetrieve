# Active regression coverage

The retired WaterML fetch/parse tests asserted the dv/iv request protocol,
methodID/methodCode blocks, sentinel markers and naive WaterML daily timestamps.
Those are not modern API contracts. Their original tests remain in Git history;
all original source recordings and provenance remain unchanged. No retired
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

Legacy body hashes, counts, method descriptions and explicit unknown acquisition
facts remain tested in `test_source_series_usgs.py`. Historical local-offset
interpretation remains separate in the boundary and UTC tests. No legacy method
ID is joined to a modern series through coincident values or dates.

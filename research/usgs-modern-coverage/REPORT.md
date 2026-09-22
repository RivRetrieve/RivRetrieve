# USGS modern catalogue coverage audit

Related: #331. Evidence acquired 2026-09-22. This is an audit, not migration acceptance.

## Result

All 26,258 baseline stations have publisher identity evidence. None is confirmed entirely missing.
Of 57,961 supported station/product combinations, **57,950 match**, **5 are missing from modern metadata**, and **6 remain unresolved for a precise instantaneous-statistic match**.
The complete 157,548-row denominator also includes 99,587 baseline-unavailable combinations; these are not coverage gaps.

Missing means absent from the completed metadata acquisition, not proof of historical observation unavailability. No confirmed historical observation loss remains in the valid bounded probes. Neither matched metadata nor finite samples prove historical parity.

## Frozen baseline

Revision: `9c05cf933bd1ad04e2e77ae7733cd0caf757e487`. Native vintage: `2026-08-02T01:14:11Z`.
Scope: original 50 states plus DC; Site Service filters `siteType=ST`, `hasDataTypeCd=dv`, `parameterCd=00060,00065`. No scope expansion or active-only filtering.
Native table: 26,258 stations, 2,036,546 series claims. SHA256 `90fede218826b640963e98515a6e3c4c106bf310a2e5bcf1606f805b55d5e701`.
`baseline.json` freezes every native/packaged artifact hash, bytes, source acquisition coordinates and availability counts. `baseline_stations.parquet`, `baseline_station_products.parquet` and `baseline_claims.parquet` preserve station agency, all product rows, and relevant source period/ts_id claims. Native numeric ts_id is never mapped to a modern series ID.

## Acquisition and completeness

Actual request count: **105** (14 national pages; 91 bounded investigation requests). Sequential requests, limit 10,000, no sorting, no API key, no active/discontinued exclusion.
National metadata has 129,710 distinct IDs across 8 discharge and 6 stage pages. Each cursor chain terminated with no next link; no duplicate IDs occurred. `metadata-*-completion.json` records counts and termination. The service does not give a transactional national snapshot or an independent numberMatched total; acquisitions span their recorded UTC instants.
All national requests succeeded. One deliberately retained wrong-prefix monitoring-location request returned NotFound; that is not an access failure or evidence that the correct station is absent. No rate-limit failure occurred.
`requests.json` indexes exact request/final URLs, UTC acquisition times, status, headers, raw SHA256, byte counts and receipt paths. `.json.gz` files losslessly retain exact response bodies. Each body hash covers decompressed bytes. `comparison.jsonl.gz` accounts for every baseline product row and links source claims, modern IDs, evidence and reasons. `stations.json` accounts for every station. `missing.json` and `unresolved.json` enumerate all exceptions.

## Every missing or unresolved product

Counts below are first/last seven-day source-coordinate windows, not time-aligned parity comparisons. Exact date bounds and URLs are in each exception's `bounded_checks`; legacy requests use source-calendar dates, modern continuous requests use explicit UTC bounds. Different counts alone are not a discrepancy.

| Station | Product | Classification | Modern rows first/last | Legacy rows first/last |
| --- | --- | --- | ---: | ---: |
| 02246518 | discharge_instantaneous | unresolved | 217/652 | 217/651 |
| 03291585 | stage_instantaneous | unresolved | 611/672 | 631/672 |
| 04208504 | stage_instantaneous | confirmed_missing | 0/0 | 0/0 |
| 05414213 | discharge_instantaneous | unresolved | 1/1 | 1/1 |
| 06129000 | discharge_instantaneous | unresolved | 1/1 | 1/1 |
| 09385701 | discharge_daily_mean | confirmed_missing | 0/0 | 0/0 |
| 09423560 | discharge_instantaneous | unresolved | 616/672 | 644/672 |
| 09429070 | stage_instantaneous | unresolved | 577/786 | 605/672 |
| 10079500 | discharge_instantaneous | confirmed_missing | 0/0 | 0/0 |
| 13297380 | discharge_instantaneous | confirmed_missing | 0/0 | 0/0 |
| 13297380 | stage_instantaneous | confirmed_missing | 0/0 | 0/0 |

The five metadata gaps have successful empty modern AND legacy responses in both checked windows. This does not prove that legacy has no relevant observations elsewhere in its claimed record. One station, 09385701, has no 00060/00065 metadata but its monitoring-location item exists; the other four missing products are at stations with other matching products.

The six unresolved products publish `computation_period_identifier=Points`, `computation_identifier=Unknown`, and null `statistic_id`. Every observed modern row in their probes also has null `statistic_id`. Numerical continuous data exists, but the audit does not silently assign `00011` or claim a precise instantaneous match. Original descriptions and unknowns remain in the receipts.

## Source agency correction and invalid controls

All 26,258 identities were recomputed from native `agency_cd` plus `site_no`: 26,256 USGS, one USFS (09489082), one CA574 (09527500). Legacy sourceInfo.siteCode.agencyCode and modern monitoring-location agency_code independently confirm the two non-USGS identities. This is published identity, not a heuristic rename or legacy-method alias.

Initial investigator queries incorrectly used USGS-09489082 and USGS-09527500. Those metadata/location/modern probe files remain as **invalid-coordinate controls**, excluded from gap and discrepancy conclusions. Correct-prefix files contain `USFS-09489082` or `CA574-09527500` in their filenames. Both stations and all three formerly suspected products match national metadata and have modern observations in both corrected finite windows. Preliminary 14-candidate/2-station conclusions are superseded by this full recomputation. `probes/location-number-09489082` records the publisher's USFS identifier.

## Reproduce offline

```sh
uv run python scripts/audit_usgs_coverage.py --compare-only
uv run pytest -q tests/test_usgs_coverage_audit.py
```

Existing receipts are reused and hash checked. Online acquisition in a new output directory: `uv run python scripts/audit_usgs_coverage.py --output PATH --max-pages 40`. Bounded checks: `--probe-gaps` and `--probe-agencies`. Do not overwrite retained evidence to refresh a vintage; use a new directory. Authored test controls are explicitly synthetic, not publisher recordings.

## Decision and limits

No production catalogue was replaced. Migration acceptance remains blocked pending owner treatment of the five metadata gaps and six unresolved precise-product matches. A fallback is not implemented or authorized. A future legacy fallback needs its own issue and an explicit decision, and must account for announced WaterServices retirement on 2027-02-22 (delays from 2026-11-16): https://waterdata.usgs.gov/blog/wdfn-waterservices-degradation/.

No issue is closed by this report. Independent review is required before relying on these conclusions.

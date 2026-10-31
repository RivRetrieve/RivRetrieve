# USGS daily discharge station access

Make published USGS daily mean discharge discoverable and retrievable through RivRetrieve regardless of monitoring-location site type. Deliver a source-backed catalogue correction that removes the station-access blocker in [#623](https://github.com/RivRetrieve/RivRetrieve/issues/623), without requiring completion of the broader [USGS review #624](https://github.com/RivRetrieve/RivRetrieve/issues/624).

Implementation and verification of this outcome complete #623. Publishing this vision does not complete the issue or the downstream acquisition.

## Outcome and boundaries

Include eligible daily-mean-discharge stations and their distinct published series across the provider's existing 50 states and District of Columbia. Eligibility follows established source identity and physical meaning, not stream-only site classification, active status, minimum record length, drainage area or scientific suitability. Preserve current supported products and station access while correcting daily discharge coverage.

The immediate consumer is [hydrologeez #119](https://github.com/CooperBigFoot/hydrologeez/issues/119). Its [acquisition vision](https://github.com/CooperBigFoot/hydrologeez/blob/main/planning/visions/2026-10-31-usgs-streamflow-acquisition-on-hetzner.md) requires all available published daily mean discharge in the contiguous 48 states plus DC. Hydrologeez owns geographic selection, full-history acquisition and remote delivery. RivRetrieve must provide the station and series access needed for that work. Report provider-wide and CONUS counts separately; neither a bounding box nor a national missing-station count establishes CONUS coverage.

Continuous-only completeness and the comprehensive review of all supported products belong to #624. Do not add new quantities, geographic coverage, a public station-registration workaround, remote-cache support (#620), or quality-field retention changes (#621). No provider rewrite is prescribed.

USGS publishes discharge at river gauges and other monitoring locations. Its [Discovery Farms description](https://www.usgs.gov/centers/upper-midwest-water-science-center/science/edge-field-monitoring-discovery-farms) includes field-edge runoff and subsurface drainage monitoring. Preserve source meaning without calling every discharge series river streamflow or declaring it suitable for calibration. Do not infer a site's instrument from its classification.

## Established starting facts

Investigation began at `9026dd9b41372bf5d3a2b3669b586dba72d3a6ac`; inspect the implementation target before changing it.

- `generate_catalogue.py` uses `siteType=ST&hasDataTypeCd=dv&parameterCd=00060,00065` in both legacy site-service queries, across 50 states plus DC. Native station identity, geometry and descriptive metadata come from these retained inputs.
- Modern metadata pagination discovers source series, but catalogue construction restricts them to the legacy native station set. Modern discovery cannot currently add missing stations.
- Daily mean discharge corresponds to parameter `00060`, computation period `Daily`, and statistic `00003`. Preserve each distinct source time-series ID. Published metadata dates must not become invented observation-support bounds.
- Wisconsin station `435444087462300`, classified `FA-FON`, has series `03384f9dd532449689539f674a9174a7`. The linked endpoints in #623 returned three daily observations for 2006-10-31 through 2006-11-02, each `0.0000 ft^3/s`, with `Approved` status and null qualifier. These endpoints were independently rechecked during the discussion. Retain genuine inputs through the archive process before adopting them as verification evidence.
- The issue's 1,266 absent IDs is a reported national count, not an independently reproduced count or a CONUS count.

## Establish and correct coverage

Removing `siteType=ST` from both legacy queries is a candidate, not proof that the fix is sufficient. Reconcile both station identities and daily-mean-discharge series against complete modern metadata pagination, including historical and discontinued series. Establish the geographic scope of each comparison and distinguish catalogue inclusion from actual observation availability.

Account for modern-only and legacy-only locations, agency identity, missing metadata and exclusions. If broader legacy queries still omit eligible modern locations, establish a faithful station-metadata path rather than silently dropping them. Do not invent required identity or geometry; preserve absent optional metadata and unknown facts under existing contracts. Leave the choice of acquisition and build mechanisms to implementation after this investigation.

The result must explain the compared inventory, dates, source scopes and remaining differences. A snapshot cannot promise perpetual or exhaustive historical completeness. Unexplained missing eligible stations or series prevent claiming the blocker resolved; surface a material source-access or metadata limitation rather than narrowing the agreed outcome silently.

## Public behavior and verification

Newly included sites must work through ordinary `rr.find` and `rr.fetch`, with the existing cache and receipt interfaces. Keep separate source-series identities, source daily date labels, units and conversions, null values, absent rows and failed requests distinct. Do not infer a daily time zone or reaggregate instantaneous observations.

Demonstrate:

- The Wisconsin regression and representative distinct newly included source cases are selectable and return independently established identities, dates, values and units.
- Matching sibling series are retained rather than averaged or arbitrarily selected.
- Original acquisition preserves exact publisher receipt bytes and acquisition identity, including source approval and qualifiers in those payloads. Cache reuse works without observation-network requests where the established reuse contract permits it. Cache-hit excerpts do not replace original publisher receipts or recover omitted source quality fields.
- Existing supported product access remains intact, and the corrected station/series inventory is reconciled against source discovery.
- The approved catalogue, metadata, lineage and distribution artifacts reproduce from their selected genuine inputs.

Extend existing focused tests and shared contracts. The current public-route tests already cover observation identity, values, receipt bytes and cache calls; modern discovery tests cover pagination and sibling identities. Add expectations capable of detecting missing-station exclusion rather than duplicating the full six-route suite. Follow the [testing guide](../../docs/maintenance/testing.md) and test-first development requirements. Run affected source-independent checks and broader checks appropriate to catalogue and distribution changes.

## Evidence, publication and handoff

Follow the [provider-port guide](../../docs/maintenance/provider-ports.md) for the affected boundaries and the [evidence guide](../../docs/maintenance/evidence.md) for acquisition, review, build and acceptance. Reuse the continuing USGS research record in the private archive.

New acquisition requires retained original responses and receipts with new identities. Preserve historical inputs; do not relabel them or use a derived native rebuild as proof of missing originals. Update selected inputs, source bindings and pins through the established process. Use independently reviewed RivRetrieve and archive revisions for private-evidence execution, run applicable full checks, and review candidate runtime artifacts before packaging. Keep controlled material out of public code, logs and distributions.

Private repository access was confirmed during discovery. Exact release assets, selected new inputs and acceptance have not been verified. Missing mandatory evidence blocks acceptance rather than becoming a skipped or weakened check.

Update user documentation and affected counts to match the delivered catalogue. Explain that discharge can come from monitoring settings other than river gauges, without expanding the provider page into the research record.

Report the delivered revision, source-backed inventory comparison, verification results and any limitations. Link evidence and completed work from #623 so #624 can reuse it. Hydrologeez can then repin RivRetrieve and verify its own acquisition requirements; this work does not execute that acquisition or complete the broader USGS review.

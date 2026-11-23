# USGS source, scope and access

Complete [Effort #629](https://github.com/RivRetrieve/RivRetrieve/issues/629), the first step of the comprehensive USGS review in [Program #624](https://github.com/RivRetrieve/RivRetrieve/issues/624), with an evidence-backed source-and-access handoff. This is progressive discovery and research consolidation, not a provider rewrite or complete port verification. Verified completion of this vision completes #629; publishing this vision leaves #629 open for implementation.

Follow [provider-port step 1](../../docs/maintenance/provider-ports.md) and the established [evidence process](../../docs/maintenance/evidence.md). Work proceeds as an addendum and extension to the existing `usgs_nwis` provider and the verified work delivered in [#623](https://github.com/RivRetrieve/RivRetrieve/issues/623), building on existing code, evidence, and approved runtime artifacts.

## Settled scope

Establish supported publication and access scope across all six products RivRetrieve already supports for USGS:
- `discharge_daily_mean`: parameter `00060`, statistic `00003`, daily frequency (ft³/s returned as m³/s)
- `discharge_instantaneous`: parameter `00060`, continuous telemetry (ft³/s returned as m³/s)
- `stage_daily_mean`: parameter `00065`, statistic `00003`, daily frequency (ft returned as m)
- `stage_daily_max`: parameter `00065`, statistic `00001`, daily frequency (ft returned as m)
- `stage_daily_min`: parameter `00065`, statistic `00002`, daily frequency (ft returned as m)
- `stage_instantaneous`: parameter `00065`, continuous telemetry (ft returned as m)

Inclusion is determined strictly by the presence of supported published measurements, not stream-only site classification or daily-data availability:
1. **Continuous-only monitoring locations**: Include monitoring locations that publish instantaneous continuous discharge or stage without published daily summary averages.
2. **Non-stream monitoring locations**: Include eligible monitoring locations publishing supported discharge or stage across canals, flumes, lakes, reservoirs, estuaries, and agricultural runoff sites (such as Discovery Farms).
3. **Geographical coverage**: Cover the 50 states and District of Columbia. Retain all previously registered stations and series, including the 11 Canadian daily stations already present in historical metadata.

RivRetrieve preserves established physical meaning and published source identity, not scientific suitability or comparability. Stage is USGS gage height, not water surface elevation above sea level. Discharge represents physical volumetric flow across diverse monitoring settings; documentation will explain this without filtering sites based on study-specific suitability. No new quantities (such as water temperature or sediment transport) or synthetic frequencies (such as hourly re-aggregation) are added.

## Access architecture and request conditions

Confirm the existing [`LiveStages`](../../src/rivretrieve/_internal/providers/registration.py) architecture in [`declaration.py`](../../src/rivretrieve/_internal/providers/usgs_nwis/declaration.py) as the established runtime access contract. No transition to `BulkStore` or `CatalogueOnly` is required:
- **Observation routes**:
  - Daily values: `GET https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items`
  - Continuous observations: `GET https://api.waterdata.usgs.gov/ogcapi/v1/collections/continuous/items`
- **Station identity and metadata routes**:
  - Monitoring location details: `GET https://api.waterdata.usgs.gov/ogcapi/v1/collections/monitoring-locations/items/{id}`
  - Legacy site service (catalogue support): `GET https://waterservices.usgs.gov/nwis/site/`
- **Request conditions and rate discipline**:
  - Continuous requests use 1,100-hour capped spans (`_CONTINUOUS_WINDOW` in [`config.py`](../../src/rivretrieve/_internal/providers/usgs_nwis/config.py)), UTC time axis, and dynamic cursor pagination.
  - Daily requests use calendar date windows and inclusive bounds.
  - Polite rate discipline (≤ 2 requests per second) and strict adherence to publisher retry-after deadlines.
  - Optional `USGS_API_KEY` header binding (`X-Api-Key`); public unauthenticated access is supported and remains default.

## Terms and attribution

Data authored by the U.S. Geological Survey are in the U.S. Public Domain.

Attribution adheres to the official USGS citation specification:
> U.S. Geological Survey, USGS Water Data for the Nation: U.S. Geological Survey National Water Information System database, https://doi.org/10.5066/F7P55KJN.

## Private research record and evidence handoff

Consolidate findings, verified routes, request conditions, terms, and evidence references into a continuing private research document in `verification-evidence` (`research/usgs-source-access.md`).

Reference existing verified archive collections:
- `usgs_nwis-2026-10-31-v1` (inventory collection)
- `usgs_nwis-native-2026-11-01-v1` (native collection)
- `usgs_nwis-public-routes-2026-11-01-v1` (exact public route recordings)
- `usgs_nwis-historical-catalogue-2026-11-01-v1` (historical catalogue baseline)

Keep original responses, receipts, and private correspondence out of public repositories and distribution artifacts.

## Downstream Program boundaries

This source, scope, and access handoff establishes the foundation for subsequent Efforts in Program #624:
- [Effort #627](https://github.com/RivRetrieve/RivRetrieve/issues/627) (Step 2: Station catalogue and metadata): Reconcile inventory discovery and build reproducible offline catalogue artifacts without stream-only (`siteType=ST`) or daily-only (`hasDataTypeCd=dv`) omissions.
- [Effort #630](https://github.com/RivRetrieve/RivRetrieve/issues/630) (Step 3: Series identity and physical meaning): Verify parameter codes, statistics, units, and coordinate/elevation references across expanded monitoring locations.
- [Effort #631](https://github.com/RivRetrieve/RivRetrieve/issues/631) (Step 4: Retrieval behavior): Establish retrieval, cursor pagination, and empty-vs-failed response handling for continuous-only and non-stream series.
- [Effort #628](https://github.com/RivRetrieve/RivRetrieve/issues/628) (Step 5: Provider integration): Connect the expanded catalogue and retrieval behavior into public discovery, engine caching, and receipt verification.
- [Effort #626](https://github.com/RivRetrieve/RivRetrieve/issues/626) (Step 6: Verification): Full source-backed verification against genuine inputs, including offline rebuilds, provenance, and distribution checks.
- [Effort #625](https://github.com/RivRetrieve/RivRetrieve/issues/625) (Step 7: User documentation): Update user documentation with verified examples, explaining river vs. non-river monitoring settings and gage height semantics.

## Completion and verification

Implementation of Effort #629 requires:
1. Authoring the continuing research record `research/usgs-source-access.md` in `verification-evidence` with documented scope, route definitions, rate discipline, license terms, and cited evidence collections.
2. Publishing a concise, disclosure-safe completion summary on [#629](https://github.com/RivRetrieve/RivRetrieve/issues/629) linking the research record and Program #624 context.

Publication of this vision leaves Effort #629 open. It does not authorize implementation of catalogue changes, code modifications, or downstream Efforts.

# USGS station catalogue and metadata

Deliver reproducible offline station discovery and metadata coverage for the USGS NWIS provider, `usgs_nwis`, under [Effort #627](https://github.com/RivRetrieve/RivRetrieve/issues/627) and [Program #624](https://github.com/RivRetrieve/RivRetrieve/issues/624). This completes Step 2 of the [provider-port guide](../../docs/maintenance/provider-ports.md), building upon the settled source and access scope from [Effort #629](https://github.com/RivRetrieve/RivRetrieve/issues/629) and the daily discharge work from [#623](https://github.com/RivRetrieve/RivRetrieve/issues/623). Verified delivery of this vision completes #627; publishing this vision leaves #627 open for implementation.

Work proceeds under the established [evidence process](../../docs/maintenance/evidence.md). It replaces the immediate patch introduced in #623 with a clean, extensible architectural design for offline station discovery and metadata across all six supported products.

## Supported scope and coverage

Include eligible monitoring locations and distinct published series across the 50 United States and District of Columbia without stream-only (`siteType=ST`) or daily-data availability (`hasDataTypeCd=dv`) exclusions. Retain all previously registered stations (27,934) and all 11 Canadian daily stations (`04010500`, `04024000`, `04024430`, `04040500`, `04045500`, `04071058`, `04071765`, `040851385`, `04087119`, `04087130`, `04240105`):

1. **Continuous-only monitoring locations**: Include stations publishing instantaneous continuous telemetry (`uv`) for discharge (`00060`) or stage (`00065`) without published daily summary averages (`dv`).
2. **Non-stream monitoring locations**: Include eligible monitoring locations publishing supported discharge or stage across canals, flumes, lakes, reservoirs, estuaries, and agricultural runoff sites (such as Discovery Farms).
3. **Six supported products**: Cover `discharge_daily_mean`, `discharge_instantaneous`, `stage_daily_mean`, `stage_daily_max`, `stage_daily_min`, and `stage_instantaneous`.

RivRetrieve preserves established physical meaning and source identity, not scientific comparability. Stage is USGS gage height relative to gauge datum, not water surface elevation above sea level. Discharge represents physical volumetric flow across diverse monitoring settings. No new quantities (such as water temperature) or synthetic aggregations are added.

## Clean catalogue architecture and pipeline redesign

The immediate fix in [#623](https://github.com/RivRetrieve/RivRetrieve/issues/623) treated legacy NWIS site-service RDB tables as the exclusive station universe and bolted on modern-only locations by synthesising mock legacy RDB records through `supplement_native_stations` with hardcoded daily-discharge checks.

This Effort refactors that pipeline into a clean multi-source model:

- **Primary Station Universe from Modern OGC API**: Authoritative station existence, series existence, station names, and canonical WGS84 (`EPSG:4326`) geometry derive directly from the modern USGS Water Data OGC API Features service (`time-series-metadata` and `monitoring-locations` collections). Because RivRetrieve executes runtime retrieval over these OGC API collections, driving the station universe from modern discovery guarantees alignment between catalogue availability and retrieval capability.
- **Legacy Attribute Enrichment**: The 51-state legacy NWIS site service (queried with parameters `00060,00065` without `hasDataTypeCd=dv` or `siteType=ST`) enriches registered stations with physical sitefile attributes (`drain_area_va`, `contrib_drain_area_va`, `alt_va`, `alt_datum_cd`, `huc_cd`). Modern-only stations lacking legacy sitefile records receive `no_metadata` for catchment area and elevation without requiring mock RDB records.
- **Elimination of Patch Functions**: Fully remove `supplement_native_stations`, fake legacy RDB row synthesis, and product-specific filters. Unify station discovery and enrichment into a clean join.
- **Single-Pass Modern Build**: Generate [`station_products.parquet`](../../src/rivretrieve/_internal/catalogues/schemas.py) and [`source_series.json`](../../src/rivretrieve/_internal/catalogues/source_series.py) directly from modern metadata and retained historical series in a single pass. Remove the intermediate legacy catalogue build step and its arbitrary legacy threshold assertions (`_validate_national_products`).
- **Decoupled Legacy Claims**: Retain historical NWIS `ts_id` claims in [`series_claims.parquet`](../../src/rivretrieve/_internal/providers/usgs_nwis/catalogue_series.py) for backward traceability, decoupled from runtime station availability.
- **Declarative Historical Retention**: Consolidate retained historical inputs (the 22 explicitly selected historical series and 11 Canadian daily stations) into a declarative manifest under `declarations/usgs_nwis/` in `verification-evidence`, eliminating disjoint CLI flags.

## Station metadata and unknowns

Follow the established station metadata contract in [`docs/station-metadata.md`](../../docs/station-metadata.md) and provider precedents across the repository:

- **Station Name**: `station_nm` maps to `station_name`.
- **Drainage Area**: `contrib_drain_area_va` and `drain_area_va` map to `drainage_area` (sq mi).
- **Elevation**: `alt_va` and `alt_datum_cd` map to `elevation` (feet), constrained strictly to USGS-issued gauges (`agency_cd == "USGS"`). Other agencies receive `no_metadata` for elevation.
- **Source Fidelity for Unknowns**: Where source records omit drainage area, datum, or altitude (such as non-stream sites without catchments or continuous-only locations without survey elevations), fields evaluate strictly to `None` / `no_metadata`. No values, datums, or watershed areas are defaulted or estimated.
- **Unlocated Stations**: Stations without coordinates remain selectable by ID (`latitude=None`, `longitude=None`, `crs="unknown"`).

## Reconciliation and acceptance standard

Catalogue verification requires strict reconciliation against genuine source discovery:

1. **Complete Modern Feature Reconciliation**: 100% of modern OGC API `time-series-metadata` features for parameters `00060` and `00065` within the 50 states + DC matching any of the six supported products must resolve to a registered, selectable station in `stations.parquet`. Zero unexplained eligible omissions are permitted.
2. **Historical Retention Reconciliation**: The 22 explicitly selected historical series absent from current modern metadata must reconcile exactly against the retained series manifest.
3. **Zero Regression**: Every previously registered station (27,934) and all previously selectable series must remain selectable.
4. **Reproducible Offline Build**: The approved catalogue artifacts (`stations.parquet`, `products.parquet`, `station_products.parquet`, `station_metadata.parquet`, `source_series.json`, `monitoring_locations.json`, `series_claims.parquet`, `provenance.json`) must reproduce identically from selected genuine inputs without network access.

## Downstream Program boundaries

This Effort delivers the station catalogue and metadata foundation for subsequent Efforts in Program #624:

- [Effort #630](https://github.com/RivRetrieve/RivRetrieve/issues/630) (Step 3: Series identity and physical meaning): Verify parameter codes, statistics, units, and coordinate/elevation references across expanded monitoring locations.
- [Effort #631](https://github.com/RivRetrieve/RivRetrieve/issues/631) (Step 4: Retrieval behavior): Establish retrieval, cursor pagination, and empty-vs-failed response handling for continuous-only and non-stream series.
- [Effort #628](https://github.com/RivRetrieve/RivRetrieve/issues/628) (Step 5: Provider integration): Connect the expanded catalogue and retrieval behavior into public discovery, engine caching, and receipt verification.
- [Effort #626](https://github.com/RivRetrieve/RivRetrieve/issues/626) (Step 6: Verification): Full source-backed verification against genuine inputs, including offline rebuilds, provenance, and distribution checks.
- [Effort #625](https://github.com/RivRetrieve/RivRetrieve/issues/625) (Step 7: User documentation): Update user documentation with verified examples, explaining river vs. non-river monitoring settings and gage height semantics.

## Completion and verification

Implementation of Effort #627 requires:

1. Refactoring [`generate_catalogue.py`](../../src/rivretrieve/_internal/providers/usgs_nwis/generate_catalogue.py) and associated modules to implement the modern OGC API-driven discovery model with legacy attribute enrichment, removing `supplement_native_stations` and fake RDB row generation.
2. Generating the expanded offline catalogue artifacts and acquisition provenance with complete reconciliation against modern discovery.
3. Extending unit and contract tests in [`tests/test_usgs_nwis_generate_catalogue.py`](../../tests/test_usgs_nwis_generate_catalogue.py) and [`tests/test_usgs_modern_catalogue.py`](../../tests/test_usgs_modern_catalogue.py) to protect the refactored builder, multi-source joining, and continuous-only station discovery.
4. Publishing a concise completion summary on [#627](https://github.com/RivRetrieve/RivRetrieve/issues/627) linking the verified catalogue revision and reconciliation ledger.

Publication of this vision leaves Effort #627 open. It does not authorize implementation of code changes, catalogue rebuilding, or downstream Efforts.

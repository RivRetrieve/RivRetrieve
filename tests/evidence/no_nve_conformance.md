# HydAPI published series and retrieval conformance

## Publisher contract and acquired boundaries

[HydAPI user documentation](https://hydapi.nve.no/UserDocumentation/) states that
`Series` lists all available series and that unfiltered requests return all series.
Series metadata is updated approximately every 180 minutes. The retained source is
`tests/test_data/no_nve_terms_licence.html`; its scope includes the full public
user documentation, not only the licence paragraph. The retained OpenAPI in
`no_nve_swagger.json` describes the station/parameter filters, published `versionNo`,
source `unit`, and each resolution's `method`.

An omitted observation `VersionNumber` selects a source default, described as the
version with newest data. It is not an all-version request. `Series.methodKey` is
not substituted for the individual `resolutionList.method` values. Resolution
alone does not establish averaging. Exact response units govern admission;
configured fallback units cannot admit contradictory metadata.

Discovery remains offline over the acquired 2026-09-04 station inventory.
Unrestricted retrieval now requests `/api/v1/Series` for each requested
station/parameter access coordinate, enumerates its published versions at the requested
resolution, evaluates their physical facts against the original selection, and
requests every matching version explicitly. Explicit selections do not widen and
do not require a current all-version metadata call. Historical catalogue versions
absent from current metadata are still requested; the discrepancy is unresolved,
not an assertion of historical nonexistence. Metadata acquisition failures retain
scoped diagnostics alongside independently retrieved known versions.

A valid current metadata inventory describes the supported access and acquisition
vintage. It is not a timeless historical census, an assertion of observation
availability, or a successful observation-window coverage claim. Each observation
request independently establishes success, successful empty, null-valued rows or
failure. Native source labels remain paired with their explicit UTC offset. Daily
labels and source resolution do not resolve the disputed exact day definition.

## Exact recordings and regression controls

`no_nve_109.42.0_1001_series.recording.json` is an exact scoped metadata response.
It publishes versions 1, 2 and 3. The existing explicit January 2024 observations
retain a null version 1 and different versions 2 and 3. No version wins.
`test_recorded_current_inventory_finds_versions_outside_acquired_subset` supplies
only version 1 as an **authored partial catalogue control**, then replays exact
publisher metadata and observations. It failed through the previous real fetch
path with `{1}` rather than `{1,2,3}` before the inventory acquisition repair.
This control does not claim that the real packaged catalogue omitted those three
versions. The test observes actual transport dispatch, not a mocked parser.

A bounded comparison of current parameter-filtered inventories with the retained
station capture found no additional version at an already captured
station/parameter pair. Current metadata also published stations absent from that
snapshot: 32.11.0 (stage/discharge), and 14.7.0, 14.8.0, 14.9.0 (temperature).
An explicit daily discharge observation request for 32.11.0 returned five rows.
These are station-snapshot differences, not an established selected-coordinate
version omission, and do not activate dynamic station discovery. Some metadata
coverage dates were in the future; they remain publisher claims, not verified
observation extent. Large national comparison responses remain investigation
artifacts rather than duplicating them as regression fixtures.

All nine supported parameter/resolution combinations have newly captured explicit
version requests at station 1.200.0, with the engine's exact padded bounds for
2025-07-10. Public tests replay physical discovery, fetch, clipping, source values,
identity, conversion, provenance and exact observation receipts. The 1.46.0 daily
stage recordings preserve separate Mean version 1 and Instantaneous version 2;
a precise mean predicate requests only version 1, not a renamed preferred series.

Original omitted-version recordings remain exact historical evidence for parser
cells and boundary labels. Their requests are not rewritten as explicit-version
captures and do not prove the new public request path. Credential headers are
origin-bound; recording envelopes preserve their names, never their values.

Authored structural controls explicitly cover unavailable metadata, missing
historical members, malformed member units, wrong-station metadata and a successful
empty current list. They are not described as real publisher responses. Invalid
members cannot establish complete inventory, erase valid siblings, or turn failed
acquisition into successful empty observation coverage.

## Removal and remaining limits

`NoNveSourceCoordinates` now contains only request selectors: parameter,
resolution and optional concrete version. Its old fixed method/source-unit fields
were not request parameters and no longer controlled parsing. Source-owned
version/resolution facts remain authoritative. The unused static inventory wrapper
was replaced by the scoped inventory acquisition operation. The catalogue and
lineage were rebuilt to keep raw-resolution cadence unknown and to remove fixed
method, temporal-support and anchor claims at the access-product grain. Published
version-specific methods remain available in source-series facts; a raw resolution
does not itself establish irregular sampling or an instantaneous statistic.

Stage reference/datum and exact interval/day support remain unknown where source
evidence does not establish them. Source quality and correction codes remain
uninterpreted diagnostics, not harmonised observation-quality columns.

## Inventory and successful cache reuse

The engine preserves the original acquired metadata inventory and every observation
inventory. It adds a separately identified reconciliation snapshot for one
`SourceAcquisition` transaction only. That snapshot is scoped to the actual
requested window and physical/identity predicates, not the padded transport bounds.
Its evidence names the original metadata snapshot and concrete retrieval outcomes.
The original metadata acquisition instant remains inspectable.

A settled complete snapshot requires every admitted matching member to have a
concrete, matching response definition and successful or successful-empty coverage
for the entire requested interval. Unexpected response identities, fact differences,
missing responses, unsupported structures and failed calls refuse that proof.
Metadata with unknown unit facts may be refined by admitted response facts without
losing valid rows; exact-fact reconciliation remains conservative about cache reuse.
No failure or source limitation is converted into fresh successful coverage.

All nine public routes now prove bypass, refresh and ALL reuse after this bounded
reconciliation. Additional tests prove subset acquisition cannot satisfy ALL,
subset refresh leaves siblings available, a later incomplete subset acquisition
invalidates older ALL reuse. Literal refresh returns only fresh successful rows and
identified failures. A failed version remains intact in native storage. Explicit
later reuse exposes its old row and original retrieval instant, while unrestricted
reuse reacquires rather than certifying that failed interval as fresh coverage. Store receipts
are native-row excerpts, never reconstructed publisher bytes. Publisher observation
receipts stay exact; metadata calls remain identified separately in provenance.

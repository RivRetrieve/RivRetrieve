# Native French publication inventory research

Acquired 2026-09-21 through the repository HttpClient using `uv run python acquire.py NAME URL PARAMS_JSON`. No production files were changed. Raw `.body` files and `.receipt.json` sidecars retain exact parameters, UTC retrieval instant, status, media type, length and SHA-256. No credentials or observation census were used.

## Builder inputs

- `national-tests.body`: HydroPortail-native test-inclusive public inventory. 9,271 sites, 6,409 nested stations. Use full `bookmarkCode`; site relationships come from nesting, never station-code truncation.
- `national-tests.receipt.json`: governing query. GET `/rechercher/ajax/entites-hydrometriques` with active=1, closed=1, test=1 and every site type published in `search-form.body`, including PONCTUEL. The current site-type values are opaque UUIDs; discover their published values from the form, do not assume UUID stability.
- `hubeau-stations-valid.body`: current complete hydrometry reference response, size=10000, count=6475, next=null. The unsuccessful size=20000 request is retained separately, with its explicit validation message.
- `hubeau-temperature.body`: independent HubEau temperature reference response, count=872, next=null.
- `reconcile.py`: rerunnable offline full-ID reconciliation. Outputs `summary.json`, `unmatched-stations.json` and `metadata-comparison.json`.

## Coverage and limits

The HTML form defaults to active checked, closed unchecked, test unchecked and PONCTUEL unselected. Never use the form defaults as national coverage. National explicit active+closed with no site-type filters and national explicit all-five-types produced the same 9,245 sites/6,389 stations. Including test=1 adds 26 sites and 20 stations. Preserve the test-inclusive population; the differential records inclusion by the source test filter, not a guessed station attribute. `test-identity.body` independently shows `Station hydrométrique d'essais Oui` for H312042201. Search rows themselves have no test marker.

All requests were anonymous. The legal page explicitly describes access to public reference entities and data, across metropolitan and overseas France. Complete export menus require optional login; this does not apply to public search. Claim a snapshot of the anonymously published inventory, not an unrestricted PHyC census.

`search-js.body` passes the entire returned array to rendering and sets itemsPerPage=10. `chunk-9392.e5b6654f.js.body`, module 57766, makes a single AJAX GET with serialized form criteria, without server pagination. No total/next/page envelope exists in the response. No arbitrary count cap was observed. Independent Mayotte region 3 (22 sites, 23 stations) and Dordogne region P (330 sites, 197 stations) requests exactly match corresponding national full IDs. This is an independent truncation check, not proof about every unpublished entity. The form includes metropolitan regions, five DROM, Etranger, Zone Atlantique and Zone Pacifique. No territory filter was supplied nationally. Site and station codes are not limited to metropolitan letter prefixes.

Native statuses are active=3527, closed=2289, inactive=593. Preserve these source words; HubEau en_service is not a direct three-way equivalent. Every returned station has isEntityAccessLimited=false. This is not a licence assertion or a statement about omitted stations.

## Reconciliation

Current HubEau contains 21 added full station IDs and no removed IDs relative to the old 6454-station fixture. HydroPortail contains 6409 matching IDs and zero IDs not in HubEau. All 6409 labels and explicit site relationships agree exactly. Source coordinate precision differs and must remain distinct.

There are 66 HubEau IDs absent from test-inclusive HydroPortail search; 65 are old supported IDs. These are recorded individually in unmatched-stations.json, with original HubEau metadata and native identity-page response receipts. All 66 native identity pages returned HTTP404, with no failed or unchecked acquisitions. Separately, ten bounded observation route probes returned HTTP404; see COVERAGE.md. A missing search result or an HTTP404 establishes only current anonymous native publication behavior, not station nonexistence, rights, deletion or lack of historical observations. Do not insert HubEau metadata into the HydroPortail native inventory. Do not reinterpret unsuccessful metadata access as empty observation history.

The initial 86-ID gap comprises 20 test-filter exclusions and these 66 further gaps. Native code-specific search for site 40510003 independently returns station 4051000301 but not HubEau station 4051000302; the latter identity page returns HTTP404. Search omission is not explained by code truncation, national paging, activity, or PONCTUEL filtering.

## Coordinates

Use station.coordinates.x as longitude and station.coordinates.y as latitude from the native search. Do not use the containing site's coordinates. The source's own module 71324 in `chunk-8529.fdb00780.js.body` creates a GeoJSON Point for each station using `[station.coordinates.x, station.coordinates.y]`, separately from sites, without transformation. GeoJSON geographic coordinate order is longitude/latitude. Empty proj.label is not itself CRS evidence; use the published GeoJSON conversion as the evidence. Station identity pages show the original projected coordinates and projection (for example Mayotte EPSG:4471), whereas search already returns geographic values. Do not apply another projection or the HubEau axis correction to HydroPortail search.

Across all 6409 matches, native geographic coordinates differ from HubEau geographic values after the separately justified HubEau projection-31 axis correction by at most 9.1e-8 degrees. Native search generally retains seven decimals. Do not replace these with the finer HubEau values. For projection31 HubEau rows, original x equals erroneous latitude_station and y equals erroneous longitude_station; compare after swapping only those fields. This live comparison supports the existing signature for this new snapshot, not a universal snapshot-specific bounding box. `station-projection31.body` provides independent native identity for R521001101. Preserve original source values and transformation lineage.

## Terms and attribution

`legal.body` identifies Service Central Vigicrues (SCV, ex-SCHAPI) as editor. It distinguishes Vigicrues network authors from external producers. `about.body` identifies PHyC as the shared platform and HydroPortail as its principal interaction service. Neither page states an Etalab licence. The `BASE LEGALE` heading concerns personal data, not a blanket reuse licence. Do not transfer HubEau's Etalab statement to HydroPortail. Retain native source legal/about references and explicitly unknown reuse licence unless another applicable native statement is acquired. Matching codes do not establish original measurement authorship.

## Proposed acquisition/build interface

At composition: `acquire_inventory(transport, receipt_writer)` obtains form and all-types/test-inclusive inventory with exact query and records failures. It resolves current form option values. It returns publisher bytes plus acquisition metadata, not cross-provider facts.

Pure boundary: `decode_inventory(payload, retrieved_at)` validates root array, site/station type identity, full unique string codes, station/site relationships, labels, status vocabulary, coordinate finite/range/null behavior and typed access flag. Null coordinates must remain unknown; never fill them from the site or another service. Empty type/publicationRight/projection labels remain empty source facts, not expanded guesses. Fail invalid internal/decoded contracts instead of silently dropping records. Keep original native row content or stable source columns sufficient for exact lineage.

Pure build: `build_catalogue(native_table, origins, availability)` emits station identity/geometry and the retained raw Q/H product cross-product. Membership alone cannot mark either pair available. Attach existing HydroPortail historical witnesses only with station, raw status, Q/H identity, exact bounded query and acquisition date; do not migrate HubEau observations_tr count claims. New and unchecked pairs remain selectable unknowns.

Acquisition validation should compare repeated national/territorial or code-specific queries when coverage evidence changes, rather than freezing current counts as completeness constants. HubEau should independently follow its own count/next pagination contract for both hydrometry and temperature.

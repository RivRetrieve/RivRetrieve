# Independent French publication-service providers

Program: https://github.com/RivRetrieve/RivRetrieve/issues/312
Effort: https://github.com/RivRetrieve/RivRetrieve/issues/310

## Outcome

France has two independently discoverable and selectable providers: `fr_hubeau`
and `fr_hydroportail`. Each represents its own publication service, uses its own
source-published station catalogue, and carries its own observation access,
source evidence and applicable terms. Neither service is hidden inside the other.

Shared PHyC origins and matching station identifiers do not make the services
interchangeable. Independence does not prohibit shared internal code or require
pretending that the services have different original measurement producers.
Neither provider substitutes observations from the other or uses the other's
observation counts to assert its own series availability.

## Retained observation scope

Preserve the existing supported physical products and their source semantics:

| Provider | Published observations |
|---|---|
| Hub’Eau | Daily mean discharge (`QmnJ`), daily maximum instantaneous discharge (`QIXnJ`), daily maximum instantaneous stage (`HIXnJ`), and Naïades water temperature (`resultat`, parameter `1301`) |
| HydroPortail | Station-own instantaneous discharge (`Q`) and stage (`H`), currently raw |

Keep the distinction between publication service, underlying network and original
measurement author. Naïades temperature remains within the Hub’Eau provider, not
within the PHyC hydrometric network. Preserve units, source time labels, unknown
day definitions and unknown temperature temporal support. Do not calculate new
products or substitute site-combined discharge for a station's own record.

Additional Hub’Eau products, including its recent instantaneous route and monthly
products, are tracked separately in
https://github.com/RivRetrieve/RivRetrieve/issues/314. HydroPortail processing-status
variants belong to Effort #311. This split must not pre-empt their discovery or
silently introduce those capabilities.

## Independent source catalogues

Acquire each service's own station inventory and establish its source-specific
coverage. Hub’Eau hydrometry and temperature are distinct catalogue routes within
one provider. HydroPortail discovery must use its native inventory, not merely a
copy of the existing Hub’Eau-derived station list with a different provider name.

Reconcile the inventories using full source station codes and explicit published
station/site relationships. Record and investigate unmatched records and metadata
differences without forcing populations to match. Do not truncate station codes,
merge stations by name or coordinates, or substitute site coordinates for station
coordinates. Station-only observation access remains the scope; acquiring site
relationships does not add site-level retrieval.

Do not silently exclude inactive or historical stations. Investigate source search
defaults, filters, territorial coverage, pagination or response limits, test-entity
rules and source access restrictions before making completeness claims. Preserve
existing supported station access unless source investigation establishes a
specific reason for a difference. Explain such differences rather than enforcing
a frozen population or treating all differences as new capabilities. Unsupported
completeness claims are not acceptable; material unresolved access or coverage
limits must be surfaced to the owner rather than hidden by a fallback catalogue.

Each metadata fact retains its actual publication origin. Matching codes do not
permit relabelling Hub’Eau metadata as HydroPortail-native. Preserve source values,
precision and unknowns. Revalidate coordinate transformations against their actual
source representation; do not generalize snapshot-specific corrections or bounds
to new populations without evidence.

Catalogue membership establishes an entity, not observations for every product.
Availability must identify its publication service, product or series, status,
request scope and acquisition date. Retain supported unknown pairs as selectable.
Distinguish positive witnesses, empty bounded requests, unchecked history and
failed requests. A source-specific positive witness does not promise continuity
or availability in every requested period. No national observation campaign is
required merely to establish station identity or catalogue membership.

## Evidence established during discovery

The following are dated findings, not enduring counts or acceptance constants.

- The packaged native catalogue captured on 2026-08-02 contains 6,454 Hub’Eau
  hydrometry stations and 869 temperature stations. Its 33,139 selectable pairs
  are a designed product cross-product, not proof of observations or complete
  HydroPortail coverage. The hydrometry snapshot includes 2,314 inactive stations.
- Existing instantaneous availability mixes services: 5,624 positive claims rely
  only on Hub’Eau `observations_tr` counts; 59 have positive HydroPortail historical
  witnesses. Do not transfer the former into HydroPortail availability. Preserve
  useful evidence with its real scope rather than deleting it or turning lack of
  HydroPortail evidence into absence.
- Live Hub’Eau counts on 2026-09-21 were 6,475 stations, including 2,321 inactive,
  and 9,286 sites. These totals alone do not establish the exact changes in IDs.
  The official filter is `en_service`; a checked `in_use=true` request did not
  restrict the count. Do not repeat the disproven active-only explanation.
- HydroPortail has an anonymously accessible native search at
  https://hydro.eaufrance.fr/rechercher/entites-hydrometriques and public station
  identity pages. Its published scripts route search to a GET at
  `/rechercher/ajax/entites-hydrometriques`. The form defaults to active stations,
  excludes closed stations and omits the PONCTUEL site type. Defaults are not an
  all-station census.
- A bounded native request with `hydro_entities_search[hydroRegion]=3`,
  `hydro_entities_search[active]=1`, `hydro_entities_search[closed]=1`, and no other
  explicit filters returned 22 Mayotte sites with 23 nested stations. All 23 full
  station codes and labels matched Hub’Eau's `code_departement=976` response.
  National HydroPortail completeness and equivalence were not established.
- Native identity pages for `1011000201`, `F700000109` and `3094000102` confirmed
  matching historical/overseas station identities. Metadata still differs:
  HydroPortail gives `3094000102` an opening time of 20/10/2016 18:00 TU, while
  Hub’Eau gives midnight on that date; the historical Paris station's closing
  time also differs. Do not infer that identical calendar dates mean identical
  source precision or time values.
- Public native search worked through the project's `HttpClient`. Initial direct
  httpx requests returned 403, which did not establish a service access failure.
  The checked native station export-selection route presented a login form.
  Do not assume that export is anonymously available or that login is required
  for the public search.
- The separately published SANDRE Mayotte extract had 21 records, while both live
  services had 23. SANDRE snapshots are not a substitute authority for exhaustive
  HydroPortail membership.

Authoritative entry points:
https://hubeau.eaufrance.fr/page/api-hydrometrie,
https://hubeau.eaufrance.fr/api/v2/hydrometrie/api-docs,
https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations,
https://hubeau.eaufrance.fr/api/v1/temperature/station,
https://hydro.eaufrance.fr/edito/a-propos-dhydroportail,
and the native search and `/stationhydro/{full_code}/fiche` pages above.
Recheck current responses during implementation and retain reproducible acquisition
evidence. The findings here are sufficient context without access to the interview
or local research files.

## Complete the provider boundary

Carry the separation through public `find` / `series` / `pick` / `fetch`, provider
registration and declarations, catalogue construction and packaged artifacts,
source mappings, evidence and receipts, and directly affected cache/export
identities and references. The same physical station may legitimately appear
under both provider identities without implying interchangeable series.

Remove superseded combined-provider behavior. `fr_hubeau` names only Hub’Eau after
the change. There are no compatibility aliases, legacy combined-provider facade,
or migration guide. Do not destructively reinterpret stored evidence or old data
under new identities; prevent stale combined artifacts from being mistaken for
new source-specific records.

Preserve independent successful results and identified source failures. Keep null
observations, absent rows, empty successful series and failed requests distinct.
Fatal internal contract errors remain fatal. Preserve station identity, requested
raw-series identity and unit/time checks, including empty response envelopes.

Keep source terms scoped to the material they actually govern. Hub’Eau's Etalab
statement must not become a HydroPortail licence assertion. Publication operators
and station-reference dataset producers are not automatically the authors of every
historical measurement.

Effort #313 owns the final two-page provider documentation rewrite and coherent
shared documentation. This Effort must nevertheless keep directly affected
examples, descriptions, references and declarations truthful. Preserve useful
scientific regressions and source evidence instead of keeping obsolete assertions.

## Observable completion

A user can discover each provider independently and retrieve all retained supported
products through their correct publication service. Provider and source identity
remain traceable through discovery, results, receipts and exports. Selecting one
service cannot route observations to the other.

Both catalogues have reproducible source-owned acquisition and explicit coverage
accounts. Reconciliation explains population and metadata differences; it does
not demand equal counts. Historical stations, station/site identity, source-specific
availability and unknowns are verified rather than assumed from the old catalogue.

Public-path regressions cover the separate providers, retained products, independent
failures, empty/null distinctions and affected cache/export identity. Representative
live checks verify actual access and source semantics. For discovered bugs, first
add a failing regression on the real path, then repair it and pass that same test.
Run relevant repository checks through `uv` and follow the project architecture.

National inventory reconciliation remains implementation work. If discovery during
implementation exposes additional products, contradictory evidence or unrelated
defects, discuss the outcome-level scope with the owner and record follow-up issues
where appropriate. Do not silently expand scope or dismiss a source mismatch.

This is a vision for the provider split only. It neither delivers Effort #310 nor
authorizes combining the separate variants, additional-coverage or documentation
Efforts into this delivery.

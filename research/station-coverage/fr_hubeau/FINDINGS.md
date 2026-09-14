# France (`fr_hubeau`) — producer and station-product coverage research

Research for [#222](https://github.com/RivRetrieve/RivRetrieve/issues/222). Research owner
@thiagovmdon; delivery and integration owner @CooperBigFoot.

Research only. No production adapter, canonical catalogue artifact or provenance check is modified.

| | |
| --- | --- |
| Baseline commit | `67796ab8d793867aaaaf9c6fb55bec208adaeab8` |
| Native table captured | `2026-08-02T17:33Z` (7,323 stations) |
| First survey | `2026-09-08` / `09` |
| Replacement captures (this revision) | `2026-09-11` / `12` |
| Inventory | 33,139 rows = 6,454 × 5 + 869 |
| Final reconciliation | 2026-09-13 governing acquisitions; see §10 |

## 1. Headline

The pre-integration provider exposes **3 stations and 6 series**. The reconciled
baseline accounts for **33,139 applicable pairs**, all intended to remain selectable:
**20,966 available and 12,173 unknown**. This is research, not a completed catalogue expansion.

| Governing basis | Pairs | Availability |
| --- | ---: | --- |
| Publisher count positive or exact numerical historical witness | 20,966 | available |
| Publisher whole-record count zero at acquisition | 4,948 | unknown |
| Empty in both specified historical windows | 524 | unknown |
| Historical check failed | 97 | unknown |
| Recent-empty; history unchecked | 6,604 | unknown |

Positive evidence consists of 20,907 publisher-count conclusions and 59 numerical
historical witnesses. A positive count is not a guarantee of numerical values in every
row or requested window. Counts of zero do not establish permanent absence.

`inventory/governing_evidence.json.xz` carries the governing per-pair acquisitions;
`inventory/retired_historical_totals.json` records the 59 retired precise old totals.
The CSV and summary are derived accounting, not substitutes for source responses.

The three daily products have different availability populations. Applicability uses
the two source populations below, not every station crossed with all six products.

## 2. Two disjoint populations

The 7,323 baseline is the union of two referentials with **zero overlapping station codes**: 6,454
hydrometry stations and 869 temperature stations. Temperature stations carry no `code_site`,
`en_service` or `type_station`, so the five hydrometric products do not apply to them.

## 3. How availability is established, and what each negative means

| Instrument | Products | A zero means |
| --- | --- | --- |
| `obs_elab` / `temperature/chronique` `count`, `size=1`, `fields=code_station`, **no date filter** | the three daily products, temperature | the publisher's **whole-record** total is zero (`empty_no_data_published`) |
| `observations_tr` `count` | instantaneous H and Q | nothing in the **rolling 30 days** — never absence |
| HydroPortail station series over two windows | the 682-pair sample only | nothing **in those two windows** — never absence |

A request settles only when the publisher answered it: HTTP 200/206 with a parseable count, or HTTP
200 with a parseable series. **A failed attempt never becomes a count, a zero or an empty window**;
it remains a failure. No further survey or retries are required for this outcome.
The governing ledger identifies the actual acquisitions for every pair.

## 4. Catalogue metadata cannot establish availability

`referentiel/sites` publishes `grandeur_hydro`, which reads like a per-site declaration. It is **`Q`
for all 9,284 sites** — a constant. `date_premiere_donnee_dispo_site` is **empty for all 9,284**.
`referentiel/stations` has no availability or measurand field. Recorded in
`recordings/hubeau_sites_grandeur_declaration` so the negative is checkable.

## 5. A site's discharge series is not its stations' discharge series

The station-to-site mapping is published as `code_site` for all 6,454 hydrometry stations (non-null;
`Y251002001` → `Y2510020`, exactly the value `fetch.py` hard-codes). It is **many-to-one**: 5,505
sites, of which 755 carry 1,704 stations, up to eight on one site.

That mapping does **not** mean a station's discharge is its site's discharge. HydroPortail states it:

> Un site peut comporter plusieurs stations, dont l'une au plus est active à un instant donné : c'est
> elle qui produit le débit du site.

(`recordings/doc_hydroportail_station_hydrometrique`; the site calendar page adds that the activation
table traces which station supplies the site's data.)

The earlier `evidence/station_site_comparison.json` contains derived anecdotes:
it reports 576-point comparisons for site `25210001`, and 282 station-Q points
versus an empty site `12320001` over 1–8 June 2026. The observation-bearing
comparison bodies were not retained in that research package. These precise figures
are **historical unsupported derived anecdotes**, not full-body-verified governing
facts. Later witnesses do not recover those old bytes or certify those totals.

The approved decision is settled: a station selection returns **that station's own Q**.
A complete private response from `/stationhydro/ajax/1232000101/series` verifies the
selected station code, Q metric, UTC, actual series unit and numerical values for
**1 June 2026 only**. It supports the route, not a population-wide inference.
Retain the published station/site mapping; never derive it by truncating identifiers.
Site access and activation-calendar research are outside this outcome.

## 6. Historical checks and retired totals

The original bounded historical sample used 1–8 June 2026 and 1–8 June 2023.
Final governing evidence has 524 two-window empties and 97 failed checks.
There are 6,604 recent-empty pairs with history unchecked: 1,976 in-service and
4,628 out-of-service pairs. Being out of service does not establish lack of history.
These are accounted limitations with unknown availability, not exclusions or a
request to complete an exhaustive historical survey.

Fifty-nine unsupported precise old historical totals are retired. Their replacement
positive witnesses are exact **one-day requests**, not replays of the old eight-day
windows. Read actual request URLs, dates and bodies in the governing acquisitions;
old receipt names, `w1`/`w2` filenames and original request URLs are not replacement
request identities. Do not reproduce old precise totals from derived summaries.

## 7. Failed checks remain failures

The 96 retained historical failures are supplemented by `J783301020` instantaneous Q:
**1–8 June 2026 returned HTTP 500; 1–8 June 2023 was empty**. Its earlier
two-window-empty classification is superseded. This gives 97 failures, not 97 empty
series. Do not retry this pair or the unchecked population merely to complete accounting.
Normal future retrieval can return values, a valid empty result or an explicit source issue.

## 8. Organisations: names are established, roles are not

Two bulk Sandre requests give an organisation name for **6,235 of 7,323 stations** — not 7,323 lookups.

| Population | Layer | Field | Named |
| --- | --- | --- | --- |
| Hydrometry | `sa:StationHydro` | `NomIntervenant` | 5,366 / 6,454 |
| Temperature | `sa:StationMesureEauxSurface` | `ProducteurDuJeu` | **869 / 869** |

**Neither field is established as the producer of the series RivRetrieve retrieves**, and the
inventory no longer has a `producer` column. What the source actually says:

- `NomIntervenant` is "le nom de l'intervenant … son appellation courante ou sa dénomination sociale
  intégrale" (`recordings/doc_sandre_nomintervenant`) — a name, with **no role attached**. The layer's
  own schema declares none (`sandre_wfs_hyd_describe_stationhydro`), and its metadata says only that
  Sandre collects the layer yearly from SCHAPI (`doc_sandre_hyd_layer_metadata`).
- `ProducteurDuJeu` sits beside `DateDuJeuDeDonnee` in the schema, and the referential's metadata says
  the data is collected "auprès des producteurs (Agences de l'eau et Offices de l'Eau)" while station
  information "relèvent de la responsabilité du ou des maîtres d'ouvrages des réseaux de mesure"
  (`doc_sandre_stq_dataset_metadata`). It identifies the producer **of the station-referential
  dataset**, not of the temperature series.

Each row carries the source's field name and a scope code (`nomintervenant_role_unstated`,
`producteurdujeu_station_dataset_producer`, `station_absent_from_sandre_layer`,
`nomintervenant_blank`). A name is not extended to a station's historical measurements, nor to a
shared site's series. **1,088 hydrometry stations have no name**: 1,023 absent from the layer, 65
blank. Two hypotheses failed — not closure (879 of the 1,023 are in service), not station type (873
are `STD`). See [UNRESOLVED.md](UNRESOLVED.md) §4 and §5.


### Official publication and citation

Official retained legal/about documents identify Service Central Vigicrues (SCV,
ex-SCHAPI) as HydroPortail editor and manager of PHyC. Content comes from the
Vigicrues network and external hydrometric producers. Hub'Eau terms name OFB, SCV
and BRGM as editors. Publication, platform operation, referential production,
collection and original measurement production are distinct roles.

This establishes traceable official publication, not authorship of every historical
measurement. The earlier three-station assertion that identity lookups name the
“producing SIE body” exceeds those fields' evidence and needs correction in production
provenance. No new original-producer inquiry is required before expansion.

Retain the source's citation words verbatim:
“L'utilisateur de ces données doit néanmoins veiller à citer l'auteur des Jeux de données.”
The dataset-author citation question remains unresolved; an SCV/Hub'Eau publisher
label does not settle it. Retain source terms without classifying licences or inferring
redistribution permission.

## 9. Routes

[ROUTE_DECISIONS.md](ROUTE_DECISIONS.md) records what each route was measured to do. The correction
that matters: **the two instantaneous routes tie on freshness in the preserved captures** — both
HydroPortail and `observations_tr` return `2026-09-08T12:15:00Z` as their latest H instant. An earlier
version of this survey claimed a five-minute HydroPortail advantage; it was wrong and is withdrawn,
along with per-route reliability counts no recording supports. Retain HydroPortail for **historical access**, supported by the governing historical
witnesses. The old January 2020 example remains receipt-only research history, not a
newly body-certified numerical total. `observations_tr` rejected the captured request
beyond 30 days with HTTP 400 `ValidateDateMin`.

## 10. Evidence and verification boundary

The retained Hub'Eau bundle contains complete primary count bodies. The historical
bundle contains retained empty/error bodies. The final controlled private corpus adds
complete governing positive witness bodies and replacement checks. Each acquisition
must identify its actual request, retrieval instant, status, byte size and digest;
compressed bundle identity and response-member identity are distinct.

- `inventory/governing_evidence.json.xz`: reviewed, rich per-pair acquisition accounting.
- `inventory/retired_historical_totals.json`: explicit retirement of 59 old totals.
- `scripts/verify_governing_evidence.py --evidence-root PATH`: explicit private full-body
  verification against retained inputs, without acquisition.
- Public offline checks: deterministic ledger/binding checks, **not source certification**.

The private root is the controlled `review-evidence/effort-225/fr_hubeau/` corpus.
It is not available in a fresh clone. Arrange an authorised handoff if absent; do not
substitute hashes for bodies or rerun the survey. Private evidence stays out of public
artifacts. This is a publication boundary, not a blanket prohibition on measurement
values or a legal conclusion about source terms. Existing genuine-recording test
requirements remain in force. Old receipt-only anecdotes remain uncertified.

## 11. Earlier research corrections (historical record)

The author previously corrected the following defects. Final counts and evidence
limits in §§1, 6, 7 and 10 supersede that earlier revision.

1. **96 failed checks were recorded as emptiness.** Now failures are a status of their own, retried,
   and never convertible into a zero (§7). The verifier fails if that conversion reappears.
2. **The second window's outcome was discarded.** Each window is now its own request with its own
   receipt, and a two-window emptiness claim requires both windows answered.
3. **Station Q results were being read as site availability.** Now separated, with the source's own
   explanation and a derived historical comparison whose limits are explicit (§5).
4. **Availability rested on counts with no responses behind them.** Every governing primary count has its response
   body retained; replacement witnesses have exact private bodies (§10).
5. **The freshness comparison contradicted the saved responses.** Withdrawn (§9).
6. **Organisation names were presented as `producer`.** Now the source's field name plus a scope code,
   with the role explicitly unestablished (§8).
7. **The zero-count example addressed a temperature station** (`01004000`) on the hydrometry route.
   Replaced by a valid hydrometry example, with a positive control on the same station; the old
   recording is kept and relabelled as the warning it is.
8. **Removed as unsupported:** the claim that `sa:StationHydro` is the exact union of its six regional
   layers. No recording of those layers was ever committed.

## 12. Relation to the withheld facts

The packaged `provenance.json` withholds **47,773 fact groups**, all `no_acquisition_record_established`,
of which **7,320 are `withheld_station:<code>`** — France withholds station identities as well as
availability. This survey supplies acquisition records against both: the Sandre captures carry official
identity and position, and the whole-record counts settle the four daily and temperature products at
every station. Converting any of it into catalogue rows is implementation work.

## 13. Review status and checks

The original PR reported 30/30 checks from `scripts/verify_evidence.py`. That result
predates final reconciliation and is not certification of discarded positive bodies.
Do not adopt its blanket measurement-value scanner as project policy. Use the public
deterministic checks and explicit private-body verifier described in §10, and report
which one was run. Nicolas owns review, acceptance and delivery; research publication
still requires normal review and merge. No production changes are supplied here.

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
| Verification | `scripts/verify_evidence.py` — 30/30 checks pass, offline |

## 1. Headline

Today the provider exposes **3 stations and 6 series**. This survey establishes **20,966 series**, and
says precisely what it does not establish.

| Product | available | none published | empty in both history windows | never history-checked | check failed |
| --- | --- | --- | --- | --- | --- |
| `stage_daily_max` | **5,266** | 1,188 | — | — | — |
| `discharge_daily_mean` | **4,942** | 1,512 | — | — | — |
| `discharge_daily_max` | **4,206** | 2,248 | — | — | — |
| `stage_instantaneous` | **3,221** | — | 202 | 3,021 | 10 |
| `discharge_instantaneous` | **2,462** | — | 323 | 3,583 | 86 |
| `water_temperature_reported` | **869** | 0 | — | — | — |

Per-station detail: [STATION_TABLE.md](STATION_TABLE.md); machine-readable:
`inventory/station_product_evidence.csv`; generated counts: `inventory/inventory_summary.json`.

**The three daily products differ by over a thousand stations each.** A station having stage says
nothing about it having discharge. No station × product cross-product holds.

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
it is recorded as a failure and retried. Every row names the receipts it rests on in `evidence_refs`.

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

The preserved responses show the same thing, same window, same variable
(`evidence/station_site_comparison.json`):

| Site | Window | Site series | Its stations |
| --- | --- | --- | --- |
| `25210001` | 1–2 Sep 2026 | 576 points | `…01`: 576 points, equal to the site at **1** of 576 instants · `…02`: 576 points, equal at **all 576** |
| `12320001` | 1–8 Jun 2026 | **no point** | `…01`: **282 points** · `…02`: none |

So the two entities can disagree in both directions: a station can report while its site is empty, and
two stations on one site carry different series. **Every `discharge_instantaneous` row in this
inventory is therefore a station-level finding** (`tested_entity_kind = station`), and none is
transferred to the site series production requests. What that means for implementation, and the exact
open question, are in [HANDOFF.md](HANDOFF.md) §3 and [UNRESOLVED.md](UNRESOLVED.md) §3.

## 6. Instantaneous availability: what is settled, and what is not

`observations_tr` settles every station with data in its rolling 30 days. For the rest, a bounded
sample of **682 pairs** (441 Q, 241 H — the same pairs the first survey probed) was re-probed against
HydroPortail over two windows, 1–8 June 2026 and 1–8 June 2023:

| Outcome | Pairs |
| --- | --- |
| available (points in a probed window) | 61 |
| empty in **both** windows | 525 |
| check failed (§7) | 96 |

Everything outside that sample is **never history-checked**, and the inventory says so rather than
calling it absence:

| Never history-checked | Pairs |
| --- | --- |
| in-service stations, outside the sample | 1,976 |
| **out-of-service stations** | **4,628** |

The out-of-service pairs matter and were previously under-described: a station being out of service
and having no recent reading **does not establish that it lacks historical measurements**. They were
never checked against history at all.

**What more probing could establish, and what it could not.** Applying the same two windows to the
6,604 unchecked pairs and retrying the 96 failures is an upper bound of **13,400 requests**. At the
median spacing actually observed against HydroPortail in this survey (3.52 s between requests,
measured from the receipts) that is roughly **13.1 hours** of sustained load on a public portal. It
would move pairs into "available" where those windows happen to contain data, and otherwise produce
more two-window emptiness. **It would not establish whole-history absence for any station**: two empty
windows are two empty windows. No whole-record total exists for the instantaneous products, and none
of this touches the site-series question in §5. See [UNRESOLVED.md](UNRESOLVED.md) §1 — the decision
is the delivery owner's.

## 7. 96 checks the portal did not answer

Of the 682 sampled pairs, **96 never answered**: 86 `discharge_instantaneous` and 10
`stage_instantaneous`, with HTTP 500 and HTTP 404. They were retried across three passes on two
different days (982 HTTP 500 and 120 HTTP 404 attempts in total) and **the same 96 pairs failed every
time**, with no pair recovering and no previously-answered pair starting to fail.

They are recorded as `history_check_failed`: **no claim about the source**. The reproducibility is a
fact about those requests, not evidence that the stations lack measurements.

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

## 9. Routes

[ROUTE_DECISIONS.md](ROUTE_DECISIONS.md) records what each route was measured to do. The correction
that matters: **the two instantaneous routes tie on freshness in the preserved captures** — both
HydroPortail and `observations_tr` return `2026-09-08T12:15:00Z` as their latest H instant. An earlier
version of this survey claimed a five-minute HydroPortail advantage; it was wrong and is withdrawn,
along with per-route reliability counts no recording supports. What remains evidenced in HydroPortail's
favour is **historical access**: it served January 2020, where `observations_tr` refuses anything
beyond 30 days with HTTP 400 `ValidateDateMin`.

## 10. The evidence package, and how to check it

| Part | Size | What it is |
| --- | --- | --- |
| `evidence/hubeau_counts.tar.xz` | 2.59 MB | 33,162 receipts and **all 33,145 answered bodies** for every baseline station × product |
| `evidence/hydroportail_history.tar.xz` | 131 KB | 2,296 receipts and 2,039 observation-free bodies for the sample |
| `evidence/station_site_comparison.json` | 2.5 KB | the §5 comparison, derived |
| `recordings/` | 18.5 MB | 44 recordings; 16.7 MB of it is two complete official Sandre metadata responses |
| `inventory/station_product_evidence.csv` | 10.1 MB | the 33,139-row inventory |
| **Folder total** | **33.1 MB** | |

Each receipt carries the exact request URL, HTTP status, media type, UTC acquisition instant, byte size
and SHA-256 of the full response. `verify_evidence.py` re-derives every count from the stored body,
re-classifies every inventory row from the receipts it cites, and checks that each cited request
addressed that row's own station with that product's own filter.

**Retention limit, and it is a real one.** This project does not commit source observation values.
Bodies are kept whole only where they carry none — which is every Hub'Eau count response, because each
is requested with `fields=code_station`. Responses that do carry observations (HydroPortail series with
points, the sample-row recordings) keep their receipt and derived readings, and their bytes are not
stored. **That is short of "preserve the actual source responses" and needs the reviewer's explicit
acceptance** — see [UNRESOLVED.md](UNRESOLVED.md) §6.

## 11. What changed in this revision

Every item below was a defect in the previous version of this PR.

1. **96 failed checks were recorded as emptiness.** Now failures are a status of their own, retried,
   and never convertible into a zero (§7). The verifier fails if that conversion reappears.
2. **The second window's outcome was discarded.** Each window is now its own request with its own
   receipt, and a two-window emptiness claim requires both windows answered.
3. **Station Q results were being read as site availability.** Now separated, with the source's own
   explanation and a preserved comparison (§5).
4. **Availability rested on counts with no responses behind them.** Every count now has its response
   body stored and re-derivable (§10).
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

## 13. Checks run

```
uv run python research/station-coverage/fr_hubeau/scripts/verify_evidence.py
```

**30/30 pass**, offline. Integrity, reproduction of every reading from stored bodies, independent
re-classification of all 33,139 rows, failure handling, entity/filter checks, station/site scope,
organisation scope codes, and a scan proving no observation value is stored anywhere in the folder —
also run in the suite by `tests/test_fr_hubeau_research_stores_no_observation_values.py`.

These checks were proved to bite: each defect above was deliberately reintroduced into a scratch copy
and the verifier failed on it, including the original failure-to-emptiness defect, which changes 96
rows. The clean copy passes.

**Access etiquette:** unauthenticated GET against public routes with a descriptive User-Agent, one
reused connection. Hub'Eau answered 33,162 requests at about 5 per second without refusal;
HydroPortail was paced at 3.5 s between requests. Only counts, identities and instants were retained —
no observation history was accumulated to establish support.

# fr_hubeau implementation handoff

For the implementing agent. The agreed Effort #225 vision supersedes the earlier
open research decisions. `inventory/governing_evidence.json.xz` binds all 33,139 pairs
to their governing acquisitions. Available: 20,966. Unknown: 12,173 (4,948 publisher
whole-record count zeros, 524 two-window empties, 97 failures, 6,604 unchecked).
Receipt-only historical anecdotes are not full-body-certified facts.

Baseline commit `67796ab8d793867aaaaf9c6fb55bec208adaeab8` · native table captured
`2026-08-02T17:33Z` (7,323 stations) · first survey `2026-09-08`/`09` · replacement captures
`2026-09-11` (the acquisition instant of every receipt is in its bundle).

Read [`ROUTE_DECISIONS.md`](ROUTE_DECISIONS.md) for what each route was measured to do.

## 1. Two disjoint populations

| Endpoint | Stations | Products |
| --- | --- | --- |
| `hydrometrie/referentiel/stations` | 6,454 | the five hydrometric products |
| `temperature/station` | 869 | `water_temperature_reported` only |

No station code appears in both. A temperature station carries no `code_site`, `en_service` or
`type_station`.

## 2. Identity

`code_station` identifies every station. `code_site` is published for all 6,454 hydrometry stations,
non-null, in the committed native table and `hydrometrie/referentiel/stations`
(`recordings/referentiel_stations_code_site`). For `Y251002001` it is `Y2510020`, the value
`_HYDROPORTAIL_IDENTITIES` hard-codes.

**Do not derive the site code.** It equals `code_station[:-2]` for all 6,454, but that is an
observation about the published field, not a rule; Sandre states only that a station's code "is
attached to" its site (`recordings/doc_sandre_stationhydro`).

The mapping is many-to-one: 5,505 sites, of which 755 carry 1,704 stations, up to eight on one site.

## 3. Station-level and site-level instantaneous discharge

### What the source says

| Statement | Source |
| --- | --- |
| A site may carry several stations, **at most one active at a time, and that one produces the site's discharge** | `recordings/doc_hydroportail_station_hydrometrique` |
| Stations on a site may succeed one another or alternate; the site's activation table traces **which station supplies the site's data** | `recordings/doc_hydroportail_calendrier_site` |
| A site is the carrier of discharge data; a station may carry stage and/or discharge | `recordings/doc_hubeau_api_hydrometrie` (receipted: the page embeds example observations) |

### Settled implementation decision

Return the selected station's own Q using
`/stationhydro/ajax/{code_station}/series`, not its shared site's series. The complete
private `station_Q_1232000101.body` and receipt verify station identity, Q, UTC,
series unit `l` and numerical values for 1 June 2026 only. The actual series unit,
not top-level display preference `unitQ=m3`, controls conversion from litres/second.

Remove the one-station identity gate and hard-coded site-Q response identity.
Validate response entity, metric, unit and timezone before iterating rows, including
valid empty responses. Keep source site mappings visible in native evidence without
using them to substitute site measurements for station measurements.

The old `evidence/station_site_comparison.json` is retained as historical unsupported
derived anecdotes. Its 576-point comparisons and 282-point total lack retained full
comparison bodies; the new one-day witness does not certify them. Source documentation,
not those figures, establishes the distinction between site and station objects.
Site-level access and activation-calendar research are outside this outcome.

## 4. Availability basis, by product

| Product | Instrument | Entity | What a zero means |
| --- | --- | --- | --- |
| `discharge_daily_mean`, `discharge_daily_max`, `stage_daily_max` | `obs_elab` `count`, `size=1`, `fields=code_station`, no date filter | station | the publisher's whole-record total is zero |
| `water_temperature_reported` | `temperature/chronique` `count`, same shape | station | as above |
| `stage_instantaneous`, `discharge_instantaneous` | `observations_tr` `count` (rolling 30 days), then for a fixed sample HydroPortail station series over two windows | station | nothing in the windows tested — never whole-history absence |

The final classifications and acquisitions are in `inventory/governing_evidence.json.xz`. A request settles only if the publisher
answered it: HTTP 200/206 with a parseable count, or HTTP 200 with a parseable series. A failed attempt
never supplies a count or a point total, so it can never become an empty result.

**Catalogue metadata cannot establish availability.** `referentiel/sites` publishes `grandeur_hydro`,
which is `Q` for all 9,284 sites, and `date_premiere_donnee_dispo_site`, empty for all
(`recordings/hubeau_sites_grandeur_declaration`).

**Zero counts and entities.** `obs_elab` answers an unknown entity with a count of 0 exactly as it
answers a known one with no data: `recordings/obs_elab_QmnJ_zero_count` asks for temperature station
`01004000` and reads 0. A zero is therefore used only where the request addresses the row's own
station, in the right population, with the product's own filter; `verify_evidence.py` checks that for
every cited request. `recordings/obs_elab_QmnJ_zero_count_valid_hydrometry_station` is a valid example:
hydrometry station `1232000102` reads 0 for `QmnJ` and 237 for `HIXnJ`, returning its own code.

## 5. Request shape, pagination, limits

| Route | Parameters |
| --- | --- |
| `obs_elab` v2 | `code_entite`, `grandeur_hydro_elab` (`QmnJ`/`QIXnJ`/`HIXnJ`), `date_debut_obs_elab`, `date_fin_obs_elab` |
| `temperature/chronique` v1 | `code_station`, `date_debut_mesure`, `date_fin_mesure` |
| HydroPortail | `hydro_series[startAt]`, `hydro_series[endAt]`, `hydro_series[variableType]`, `hydro_series[simpleAndInterpolatedAndHourlyVariable]`, `hydro_series[statusData]` |

- `code_entite` accepts several comma-separated codes, and the `count` is the aggregate across them.
- HydroPortail dates are `DD/MM/YYYY` with slashes; hyphens are rejected as an invalid date.
- Hub'Eau pagination follows the response's `next` URL as a new request.
- No rate-limit statement was established in the inspected/captured evidence. The replacement capture ran one connection with a 0.1 s pause and was
  not refused.

## 6. Organisation fields

Two Sandre layers supply an organisation name per station. **Neither field establishes measurement production or series publication.** The inventory keeps each name under
its source field and a scope code.

| | Hydrometry: `NomIntervenant` (`sa:StationHydro`) | Temperature: `ProducteurDuJeu` (`sa:StationMesureEauxSurface`) |
| --- | --- | --- |
| Stations with a name | 5,366 of 6,454 (1,023 absent from the layer, 65 blank) | 869 of 869 |
| What the source says the field is | an organisation's name (`doc_sandre_nomintervenant`); the layer schema declares no role (`sandre_wfs_hyd_describe_stationhydro`); the layer is collected yearly from SCHAPI (`doc_sandre_hyd_layer_metadata`) | sits beside `DateDuJeuDeDonnee` (`sandre_wfs_stq_describe_stationmesure`); the referential is collected "auprès des producteurs (Agences de l'eau et Offices de l'Eau)", and station information falls under "the owners of the measurement networks" (`doc_sandre_stq_dataset_metadata`) |
| Role established | none — an organisation associated with the station record | producer of the station-referential dataset |
| Scope code in the inventory | `nomintervenant_role_unstated` | `producteurdujeu_station_dataset_producer` |

Related HydroPortail terms, recorded so they are not conflated: an *intervenant* is an organisation
(`doc_hydroportail_glossaire`); a station's *gestionnaires* (generally the UH) administer its
referential; an *administrative responsibility* is the collection arrangement under which an entity's
data is communicated (`doc_hydroportail_responsabilites_administratives`). The Sandre layer does not
say which of these `NomIntervenant` holds.

Roles kept apart:

- **Organisation associated with a station** — what both fields establish.
- **Operator / distributor** — Hub'Eau *diffuses*, and says so: the hydrometry data comes from the
  PHyC platform "opérée par le Service Central Vigicrues", and the measurement network itself is
  "opéré par les Directions Régionales de l'Environnement de l'Aménagement et du Logement (DREAL) et
  autres producteurs" (`recordings/doc_hubeau_api_hydrometrie`, quotes verified at capture). So the
  network is run by many bodies, not one; Hub'Eau and HydroPortail carry the data, and SCHAPI supplies
  the hydrometric layer to Sandre (`doc_sandre_hyd_layer_metadata`).
- **Original measurement producer** — not established by either field. Official
  publication is established separately, as described below.

Limits: a name is a present-day attribute of a station record. It is not extended to the station's
historical measurements, and it does not identify the supplier of a shared site's series (§3).


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

## 7. Time semantics

Unchanged. `obs_elab` and `temperature/chronique` establish no zone, so `unknown` stands.
`observations_tr` and HydroPortail publish UTC. Temperature temporal support remains unknown.

## 8. Things that must not be done

- Do not treat a failed request as a count, a zero, or an empty window.
- Do not treat two empty windows as whole-history absence.
- Do not present a site series as each linked station's measurements, or transfer a station's
  discharge availability to its site.
- Do not treat `NomIntervenant` or `ProducteurDuJeu` as the producer of a retrieved series.
- Do not use a zero count whose request addressed another entity.
- Do not derive `code_site` by truncation, or treat `grandeur_hydro` as a per-site declaration.
- Do not assume the five hydrometric products apply to the 869 temperature stations.

## 9. Governing history and portable verification

`inventory/retired_historical_totals.json` retires 59 precise historical totals.
The replacement numerical witnesses are exact one-day requests; do not attach old
eight-day URLs or totals to their bodies. `J783301020` Q returned HTTP 500 for
1–8 June 2026 and an empty 1–8 June 2023 response. Its governing status is failed.
No survey, retry pass or original-producer enquiry is required for this outcome.
Unknown availability remains selectable; failed/empty/unchecked are distinct reasons.

From the repository root, run explicit private full-body verification:

```bash
uv run python research/station-coverage/fr_hubeau/scripts/verify_governing_evidence.py --native src/rivretrieve/_internal/providers/fr_hubeau/catalogue/native.parquet --ledger research/station-coverage/fr_hubeau/inventory/governing_evidence.json.xz --evidence-root /authorised/private/fr_hubeau
```

Replace `/authorised/private/fr_hubeau` with the authorised retained France evidence
root. `--native` and `--ledger` are required. Public deterministic consistency checks
use the same command with `--evidence-root` and its path omitted. The controlled corpus stays private; an absent corpus requires
an authorised handoff, not automatic reacquisition. Public deterministic ledger checks
do not re-verify source bytes. No blanket measurement-value scanner or legal inference
is an approved prerequisite. Preserve genuine-recording requirements.

One-day positive Q witnesses cannot replay a normal public request padded by two days
on each side or establish a midnight-straddling boundary probe. Two supplementary,
narrowly authorised padded station-Q captures are now retained privately, including
a 30 May–4 June 2026 source request for a June 1–2 user window. See
`EVIDENCE_INDEX.md` for their scope and material identity. The accepted source-only
independent report verifies that the second capture supplies the positive padded
midnight evidence. Use that exact private recording for later production tests, not
the governing one-day witnesses. This does not assert that production tests pass or
that recording publication is approved. These captures do not replace or backdate
the 59 governing one-day witnesses.
Never relabel site-Q recordings or replay one-day bytes for a longer request.

# fr_hubeau implementation handoff

For the implementing agent. Everything below is established by a recording in `recordings/` or a
receipt in `evidence/`, unless it appears under "not established". Figures for availability are
generated into `inventory/inventory_summary.json`; they are not repeated here so they cannot drift.

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

### What the preserved responses show

Same window, same variable (`Q`), site route and station routes (`evidence/station_site_comparison.json`):

| Site | Window | Site series | Station series |
| --- | --- | --- | --- |
| `25210001` | 1–2 Sep 2026 | 576 points | `2521000101`: 576 points, equal to the site at **1** of 576 instants · `2521000102`: 576 points, equal to the site at **all 576** |
| `12320001` | 1–8 Jun 2026 | **no point** | `1232000101`: 282 points · `1232000102`: no point |

`observations_tr` addressed by the site code returns rows for each linked station **and** rows whose
`code_station` is null; addressed by a station code it returns that station only
(`recordings/observations_tr_Q_*_identities`).

These are consistent with the source's statement: the site series is one series, supplied by the
station active at each instant, and linked stations carry their own discharge series, which can
differ from it. Two matching or differing samples do not prove the relationship holds everywhere;
the statement is the source's, the samples illustrate it.

### Implications

- **The site route returns the site's series, not each linked station's measurements.** It must not
  be presented as independent measurements from every station on the site.
- **Two discharge series exist for a station on a shared site**: its own
  (`/stationhydro/ajax/{code_station}/series`, `Q`) and its site's
  (`/sitehydro/ajax/{code_site}/series`). Which one a station selection should return is a product
  decision for the delivery owner. The existing site route is appropriate if the product is the site's
  discharge; it is not a station's own series.
- **Identity that must stay visible**: for a site series, `code_site`, and that it is supplied by
  whichever station is active; for a station series, `code_station`.
- **Every `discharge_instantaneous` row in the inventory is a station-level finding**
  (`tested_entity_kind = station`, `site_series_relation =
  station_series_tested_site_series_not_established`). Site-level availability was not surveyed for
  the population.

### Not established

- The activation calendar of any site (which station supplied the site series, when). HydroPortail
  documents it; no route for it was captured.
- How `observations_tr`'s null-`code_station` rows relate to HydroPortail's site series beyond sharing
  the site code; only identities were captured.
- Site-level instantaneous availability for any site other than the two above.

## 4. Availability basis, by product

| Product | Instrument | Entity | What a zero means |
| --- | --- | --- | --- |
| `discharge_daily_mean`, `discharge_daily_max`, `stage_daily_max` | `obs_elab` `count`, `size=1`, `fields=code_station`, no date filter | station | the publisher's whole-record total is zero |
| `water_temperature_reported` | `temperature/chronique` `count`, same shape | station | as above |
| `stage_instantaneous`, `discharge_instantaneous` | `observations_tr` `count` (rolling 30 days), then for a fixed sample HydroPortail station series over two windows | station | nothing in the windows tested — never whole-history absence |

The statuses are defined in `scripts/build_inventory.py`. A request settles only if the publisher
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
- No rate limit is published. The replacement capture ran one connection with a 0.1 s pause and was
  not refused.

## 6. Organisation fields

Two Sandre layers supply an organisation name per station. **Neither field is established as the
producer or issuing body of the series RivRetrieve retrieves.** The inventory keeps each name under
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
- **Operator / distributor** — Hub'Eau and HydroPortail transport the data; SCHAPI supplies the
  hydrometric layer to Sandre.
- **Producer or issuing body of a retrieved series** — not established by either field.

Limits: a name is a present-day attribute of a station record. It is not extended to the station's
historical measurements, and it does not identify the supplier of a shared site's series (§3).

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

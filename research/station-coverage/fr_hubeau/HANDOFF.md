# fr_hubeau implementation handoff

For the implementing agent. Everything below is established by a recording in `recordings/` or a
probe table in `inventory/` unless it appears under "not established".

Baseline commit `67796ab8d793867aaaaf9c6fb55bec208adaeab8` · native table captured
`2026-08-02T17:33Z` (7,323 stations) · this survey `2026-09-08`/`09`.

**Read [`ROUTE_DECISIONS.md`](ROUTE_DECISIONS.md) first** — it records which route serves what and
why, including why the instantaneous products should stay on HydroPortail.

## 1. Two disjoint populations

The baseline is the union of two referentials with **no overlapping station codes**:

| Endpoint | Stations | Products |
| --- | --- | --- |
| `hydrometrie/referentiel/stations` | 6,454 | the five hydrometric products |
| `temperature/station` | 869 | `water_temperature_reported` only |

A temperature station carries no `code_site`, `en_service` or `type_station`. Do not expect the five
hydrometric products to apply to it.

## 2. Identity, and the mapping that is already published

`code_station` is the identity for every product. `code_site` is the entity for
`discharge_instantaneous` only.

**`code_site` is published for all 6,454 hydrometry stations** in the committed native table and in
`hydrometrie/referentiel/stations`. For `Y251002001` it is `Y2510020` — exactly the value
`_HYDROPORTAIL_IDENTITIES` hard-codes. There is no need for a hard-coded map.

**Do not derive the site code.** It equals `code_station[:-2]` for 100% of the 6,454 with no
exceptions, but that is corroboration of the published field, not a rule to compute with. Station
codes are 10 characters and site codes 8, but a station added later need not follow that.

**The mapping is many-to-one.** 5,505 distinct sites; 755 of them carry 1,704 stations between them,
up to eight on one site. Stations sharing a site share a discharge series. See
`UNRESOLVED.md` §3.

## 3. Availability basis, and why it differs by product

**Daily and temperature — whole-record totals.** `obs_elab` and `temperature/chronique` return a
`count` field. Requested with `size=1` and **no date filter**, that count is the station's total for
that product over its whole record. Availability therefore rests on a published total, not on whether
data happens to fall inside a tested window, and a zero is a published fact recorded as
`empty_no_data_published`.

**Instantaneous — window-bounded.** No whole-record total is available. `observations_tr` gives a
count over its rolling 30 days only; HydroPortail returns the series itself and takes ~6.8 s per
request. Negatives there are therefore window-bounded and are recorded as `empty_in_tested_window`,
or as `uninvestigated` where the survey did not reach them. Neither is a claim that the station lacks
the product.

**Catalogue metadata cannot establish availability.** `referentiel/sites` publishes `grandeur_hydro`,
which looks like a declaration and is not: it is `Q` for **all 9,284 sites**.
`date_premiere_donnee_dispo_site` is empty for all of them. `referentiel/stations` has no
availability or measurand field among its 39. Do not build on either.

## 4. Request shape, pagination, limits

| Route | Parameters |
| --- | --- |
| `obs_elab` v2 | `code_entite`, `grandeur_hydro_elab` (`QmnJ`/`QIXnJ`/`HIXnJ`), `date_debut_obs_elab`, `date_fin_obs_elab` |
| `temperature/chronique` v1 | `code_station`, `date_debut_mesure`, `date_fin_mesure` |
| HydroPortail | `hydro_series[startAt]`, `hydro_series[endAt]`, `hydro_series[variableType]`, `hydro_series[simpleAndInterpolatedAndHourlyVariable]`, `hydro_series[statusData]` |

- **`code_entite` accepts up to 100 comma-separated codes**, and supports patterns such as `K*`. The
  returned `count` is the **aggregate** across them, so batching cannot attribute rows to a station.
  Per-station facts need per-station requests.
- **HydroPortail dates are `DD/MM/YYYY` with slashes.** Hyphens are rejected with
  `"Veuillez entrer une date valide."` — a validation error, not a source limitation.
- **Pagination** on Hub'Eau follows the response `next` URL as a new request without re-appending the
  original parameters, as the port notes already record.
- **No rate limit is published**: no `X-RateLimit` or `Retry-After` headers, nothing in the OpenAPI
  spec. This survey sustained roughly 1.7 requests per second against Hub'Eau without refusal, and
  found HydroPortail far slower at about 6.8 s per request.

## 5. Client behaviour that matters

Opening a new connection per request exhausted the local DNS resolver during this survey and produced
566 spurious `URLError: nodename nor servname provided` failures against HydroPortail — which, taken
at face value, would have looked like a station having no data. **Reuse one connection.** A session
with keep-alive removed the failures entirely.

Any sweep must also treat a transport failure as retryable rather than settled: a resumable run that
skips "already recorded" rows must skip only rows that carry a result.

## 6. Producer

Established for **6,235 of 7,323 stations** from two bulk requests, not per-station lookups:

| Population | Source | Field | Covered |
| --- | --- | --- | --- |
| Hydrometry | `services.sandre.eaufrance.fr/geo/hyd`, `sa:StationHydro` | `NomIntervenant` | 5,366 / 6,454 |
| Temperature | `services.sandre.eaufrance.fr/geo/stq`, `sa:StationMesureEauxSurface` | `ProducteurDuJeu` | **869 / 869** |

These WFS layers return the same properties as the per-station `id.eaufrance.fr` lookups already in
the repository — same station, same `NomIntervenant` — so that endpoint is a single-record view of
this layer. `sa:StationHydro` is the exact union of its six regional layers.

Hub'Eau publishes no producer field, so Sandre is the only bulk route. 1,088 hydrometry stations
remain without a producer; see `UNRESOLVED.md` §2.

Producers are transports-versus-producers distinct: Hub'Eau and HydroPortail are operators, the
DREAL/DEAL units and Agences de l'Eau are the producing bodies, as the port notes already state.

## 7. Time semantics

Unchanged and deliberately not extended. `obs_elab` and `temperature/chronique` establish no zone, so
`unknown` stands. `observations_tr` and HydroPortail both publish UTC, which says nothing about the
daily products. Temporal support for temperature remains unknown per the recorded OpenAPI contract.

## 8. Things that must not be done

- Do not treat `grandeur_hydro` in `referentiel/sites` as a per-site declaration; it is a constant.
- Do not derive `code_site` from `code_station` by truncation; use the published field.
- Do not treat an instantaneous zero as absence — the 30-day route cannot see further back.
- Do not treat a transport failure as absence, and do not let a resumable sweep settle on one.
- Do not assume the five hydrometric products apply to the 869 temperature stations.
- Do not infer a timezone or record bounds for the daily products.

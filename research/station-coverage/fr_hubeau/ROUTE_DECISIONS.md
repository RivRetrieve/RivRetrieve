# fr_hubeau — what each observation route was measured to do

Six products are served by three routes. This document records what each route was measured to do and
the approved route decision from Effort #225. Retain HydroPortail historical access
for instantaneous H and Q, with Q corrected to the selected station’s own series.

---

## 1. The routes

| Product | Approved route | Host |
| --- | --- | --- |
| `discharge_daily_mean` (`QmnJ`), `discharge_daily_max` (`QIXnJ`), `stage_daily_max` (`HIXnJ`) | Hub'Eau `hydrometrie/obs_elab` v2 | `hubeau.eaufrance.fr` |
| `water_temperature_reported` | Hub'Eau `temperature/chronique` v1 | `hubeau.eaufrance.fr` |
| `stage_instantaneous` (`H`) | HydroPortail `/stationhydro/ajax/{code_station}/series` | `hydro.eaufrance.fr` |
| `discharge_instantaneous` (`Q`) | HydroPortail `/stationhydro/ajax/{code_station}/series` | `hydro.eaufrance.fr` |

Both hosts are official French services. The comparison below is between two routes, not between an
official and an unofficial source.

---

## 2. Instantaneous products: HydroPortail and `observations_tr`

The port notes record that Hub'Eau `observations_tr` "reproducibly returned HTTP 500", the stated reason
instantaneous H and Q are served from HydroPortail. That premise no longer holds: `observations_tr`
answered for H and Q during this survey (`recordings/observations_tr_Y251002001_H`,
`..._Q_working`), and one HTTP 503 was captured (`..._Q`).

### What was demonstrated

| | HydroPortail (in use) | `observations_tr` | Evidence |
| --- | --- | --- | --- |
| **Historical access** | Historical January 2020 access reported in old receipt; its precise point total is not body-certified | Serves a rolling 30 days; day 31 is refused with HTTP 400 `ValidateDateMin` | `hydroportail_historical_2020_H`; `observations_tr_horizon_30d_ok`, `observations_tr_horizon_31d_rejected` |
| **Latest H instant, one capture each** | `2026-09-08T12:15:00Z` (captured 12:26:21Z) | `2026-09-08T12:15:00Z` (captured 12:26:24Z) | `hydroportail_recent_H` reading `last_t`; `observations_tr_latest_H` reading `date_obs_max` |
| **Identifiers returned** | the series code of the entity requested | `code_site` and `code_station` on each row | `hydroportail_*` readings `series_code`; `observations_tr_*_identities` |
| **Timezone** | UTC (`Z`) | UTC (`Z`) | same recordings |
| **Date format** | `DD/MM/YYYY` (slashes; hyphens are rejected) | ISO 8601 | — |
| **Path** | unversioned `/ajax/` | versioned `/api/v2/` | — |

**The two routes tie on freshness in the preserved comparison.** An earlier version of this document
said HydroPortail's latest reading was 12:15 and `observations_tr`'s 12:10, and used the five minutes as
a reason to keep HydroPortail. The saved `observations_tr_latest_H` response carries `date_obs =
2026-09-08T12:15:00Z` — the same instant HydroPortail returned. The five-minute difference was wrong
and is withdrawn.

### What was not established

- **General freshness.** One pair of captures three seconds apart shows a tie at one station. It says
  nothing about which route is fresher in general.
- **Reliability.** No like-for-like comparison was made. An earlier version stated attempt counts for
  each route that no preserved recording supports; they are withdrawn.
- **Which entity `observations_tr` should be asked for discharge.** Addressed by site, it returns rows
  for every station on the site plus rows with a null `code_station` (`observations_tr_Q_site_25210001_identities`).
  Their relationship to the site's series is outside this station-own outcome.

### What bears on the choice

**Evidenced in favour of HydroPortail:** it serves history that `observations_tr` refuses, and
`obs_elab` has no instantaneous product to fall back on. Historical access is the only evidenced
data difference between the two routes.

**Evidenced in favour of `observations_tr`:** a versioned path, and both identifiers on every row.
Neither is a data difference.

**Uncertain:** the `/ajax/` route carries no version guarantee; freshness and reliability were not
compared beyond the single tie above; station-own Q is settled by the approved vision and complete private representative evidence.

Keep HydroPortail for instantaneous historical access. No recent-route switch or
redundancy feature is required. No further route-choice interview is needed.

---

## 3. The instantaneous coverage is not a route problem

Instantaneous products are selectable at one station today because `fetch.py` holds

```python
_HYDROPORTAIL_IDENTITIES = {"Y251002001": {"station": "Y251002001", "site": "Y2510020"}}
```

and raises `FatalContractError` for any other station. The station-to-site mapping it encodes is
published for every hydrometry station as `code_site` (`recordings/referentiel_stations_code_site`; the
committed native table), non-null for all 6,454.

That settles the identifier, not the meaning. A published mapping does not establish that a station
selection should retrieve its site's discharge series: HydroPortail states that at most one station on a
site is active at a time and produces the site's discharge, while the old numerical comparison is only an unsupported derived anecdote
(`FINDINGS.md` §5). The complete private station-Q witness establishes the station route. **Do not derive the site code by
truncation** either: `code_site` equals `code_station[:-2]` for all 6,454, but that is an observation
about the published field, not a rule.

---

## 4. The daily and temperature products

`obs_elab` and `temperature/chronique` were not reconsidered. Both are versioned Hub'Eau routes that
accept the station code directly. Their whole-record counts are in `evidence/hubeau_counts.tar.xz`.

- **`code_entite` accepts several comma-separated codes** on `obs_elab`, but the returned `count` is
  the aggregate across them (`recordings/obs_elab_batch_aggregate_count`), so per-station facts need
  per-station requests.
- **No rate-limit statement was established in the inspected/captured evidence.**
  Absent `X-RateLimit` or `Retry-After` headers and the inspected OpenAPI specification
  do not establish that no limit exists or that none is published elsewhere.

## 5. Evidence limits

The earlier comparison entries marked `receipt + readings` do not carry complete
response bytes. Their precise historical totals and site/station numerical comparisons
are not certified by the new governing evidence. Preserve them as historical derived
anecdotes only. The freshness advantage is withdrawn: the comparison records the same
latest instant, not a general freshness finding.

The new complete station-Q witness addresses 1 June 2026 only, with source series
unit `l`, UTC and matching station/metric. It is not an eight-day response or a public
padded-request recording. See `HANDOFF.md` §9 for exact replay requirements.

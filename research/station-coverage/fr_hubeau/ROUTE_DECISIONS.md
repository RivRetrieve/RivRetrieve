# fr_hubeau — why each observation route is what it is

Six products are served by three different routes. This document records what each route was
measured to do on 2026-09-08 and why the current arrangement holds, so the reasoning does not have to
be rediscovered.

**Headline: the currently-used route for instantaneous products is the better one, and should stay.**
The obvious-looking alternative is worse on data and would lose years of history for nothing.

---

## 1. The routes

| Product | Route in use | Host |
| --- | --- | --- |
| `discharge_daily_mean` (`QmnJ`), `discharge_daily_max` (`QIXnJ`), `stage_daily_max` (`HIXnJ`) | Hub'Eau `hydrometrie/obs_elab` v2 | `hubeau.eaufrance.fr` |
| `water_temperature_reported` | Hub'Eau `temperature/chronique` v1 | `hubeau.eaufrance.fr` |
| `discharge_instantaneous` (`Q`), `stage_instantaneous` (`H`) | HydroPortail series route | `hydro.eaufrance.fr` |

Both hosts are official French services. The distinction below is between two *routes*, not between an
official and an unofficial source.

---

## 2. The instantaneous products: HydroPortail vs `observations_tr`

The port notes record that Hub'Eau `observations_tr` "reproducibly returned HTTP 500", which is the
stated reason instantaneous H and Q are served from HydroPortail instead.

**That premise no longer holds.** `observations_tr` responds normally today for both H and Q. Issue
#222 asked for exactly this check, so it is recorded rather than left as a stale note.

**But the conclusion it might suggest is wrong.** Measured side by side on station `Y251002001`:

| | HydroPortail (in use) | `observations_tr` |
| --- | --- | --- |
| **History depth** | **Serves 2020 and 2026**; 1,440 points for a 4-day window in January 2020 | **30 days only** — day 31 is refused with HTTP 400 `ValidateDateMin`, *"date can't be < 1 month from now"* |
| **Freshness** | latest observation **12:15:00Z** | latest observation **12:10:00Z** |
| **Reliability observed** | 200 on every attempt | 4 of 5 attempts succeeded; one transient 503 |
| **Route stability** | unversioned `/ajax/` path | official versioned `/api/v2/` path |
| **Identifiers returned** | series only | `code_site` and `code_station` together |
| **Timezone** | UTC (`Z`) | UTC (`Z`) |
| **Date format** | `DD/MM/YYYY` (slashes; hyphens are rejected) | ISO 8601 |

Freshness was measured against a wall clock of `2026-09-08T12:22Z`. Both routes were within roughly
ten minutes of live; HydroPortail was the fresher of the two in this sample.

### Why HydroPortail stays

**There is no data advantage to switching, and a large data loss.** The intuition that a real-time
API must be better for real-time products does not survive measurement: HydroPortail is equally
real-time, and additionally serves years of history that `observations_tr` cannot reach at all.

Even if historicity were traded away deliberately, there would be nothing to gain in exchange —
`observations_tr` is not fresher.

The two genuine points in `observations_tr`'s favour are about governance, not data:

1. it is a versioned API path rather than an `/ajax/` route that may change without notice, and
2. it returns both identifiers in one response.

Point 2 does not justify a switch, because the identifier problem is already solved by other
published evidence — see §3.

### What would justify revisiting this

- HydroPortail's `/ajax/` route changing or being withdrawn, since it carries no version guarantee.
- `observations_tr` gaining history beyond its 30-day window.
- A decision to serve the recent window from `observations_tr` **in addition to** HydroPortail, for
  redundancy. That is a design question, not a research finding, and is left to the delivery owner.

---

## 3. The instantaneous coverage problem is not a route problem

Instantaneous products are selectable at exactly one station today. The cause is not the route:
`fetch.py` holds

```python
_HYDROPORTAIL_IDENTITIES = {"Y251002001": {"station": "Y251002001", "site": "Y2510020"}}
```

a hard-coded dictionary with one entry, and raises `FatalContractError` for any station not in it.

The mapping it encodes is **already published for every station**. Hub'Eau's
`hydrometrie/referentiel/stations` publishes `code_site` alongside `code_station`, it is non-null for
all 6,454 hydrometry stations in the committed native table, and for `Y251002001` it is exactly
`Y2510020` — the same value the dictionary hard-codes.

So the blocker is a hard-coded lookup standing in for a published field, not a missing source and not
a broken route.

**Do not derive the site code by truncation.** It happens to equal `code_station[:-2]` for 100% of the
6,454 stations with no exceptions, but that is corroboration, not the basis. The published field is
the evidence; the pattern is an observation about it and may not hold for stations added later.

**One consequence to decide.** `discharge_instantaneous` is requested per **site**, and the mapping is
many-to-one: 755 sites carry 1,704 stations between them. Stations sharing a site would therefore
share one discharge series. Whether that product is station-level or site-level is a modelling
question for the delivery owner, not something this survey can settle.

---

## 4. The daily and temperature products

`obs_elab` and `temperature/chronique` are unchanged and were not reconsidered. Both are official
versioned Hub'Eau routes, both accept the station code directly with no identifier mapping, and both
answer for the whole population. Availability for every station and product was established from
their published `count` field — see `FINDINGS.md`.

Two facts recorded for implementation:

- **`code_entite` accepts up to 100 comma-separated codes** on `obs_elab`, but the returned `count` is
  the aggregate across all of them, so batching cannot attribute rows to individual stations.
  Per-station facts require per-station requests.
- **No rate limit is published.** No `X-RateLimit` or `Retry-After` headers are returned and the
  OpenAPI specification states no quota. That is not the same as there being no limit; this survey ran
  at roughly 1.7 requests per second without being refused.

---

## 5. What was measured, and what is recorded

| Claim | Evidence |
| --- | --- |
| `observations_tr` works today for H and Q | `recordings/observations_tr_Y251002001_H.recording.json`, `..._Q_working.recording.json` |
| It is limited to 30 days, refused explicitly beyond | `recordings/observations_tr_horizon_30d_ok.recording.json`, `..._31d_rejected.recording.json` |
| It intermittently returns 503 | `recordings/observations_tr_Y251002001_Q.recording.json` (a captured 503) |
| HydroPortail serves 2026 and 2020 | `recordings/hydroportail_recent_H.recording.json`, `..._historical_2020_H.recording.json` |
| HydroPortail is the fresher of the two | `recordings/hydroportail_recent_H...` (12:15:00Z) vs `observations_tr_latest_H...` (12:10:00Z) |
| `code_site` is published for every station | committed `catalogue/native.parquet`; `inventory/station_site_mapping.csv` |

# France (`fr_hubeau`) — producer and station-product coverage research

Research for [#222](https://github.com/RivRetrieve/RivRetrieve/issues/222). Research owner
@thiagovmdon; delivery and integration owner @CooperBigFoot.

Research only. No production adapter, canonical catalogue artifact or provenance check is modified.

| | |
| --- | --- |
| Baseline commit | `67796ab8d793867aaaaf9c6fb55bec208adaeab8` |
| Native table captured | `2026-08-02T17:33Z` (7,323 stations) |
| This survey | `2026-09-08` / `2026-09-09` |
| Inventory | 33,139 rows = 6,454 × 5 + 869, none omitted |
| Verification | `scripts/verify_evidence.py` — 15/15 checks pass |

## 1. Headline

Today the provider exposes **3 stations and 6 series**. This survey establishes **20,961 series**.

| Product | available | none published | empty in window | uninvestigated |
| --- | --- | --- | --- | --- |
| `stage_daily_max` | **5,261** | 1,193 | — | — |
| `discharge_daily_mean` | **4,941** | 1,513 | — | — |
| `discharge_daily_max` | **4,205** | 2,249 | — | — |
| `stage_instantaneous` | **3,218** | — | 2,527 | 709 |
| `discharge_instantaneous` | **2,467** | — | 2,723 | 1,264 |
| `water_temperature_reported` | **869** | 0 | — | — |

Per-station detail is in [STATION_TABLE.md](STATION_TABLE.md); machine-readable form in
`inventory/station_product_evidence.csv`.

**The three daily products differ sharply** — 5,261 vs 4,941 vs 4,205. A station having stage says
nothing about it having discharge, and daily-mean discharge reaches 736 more stations than daily-max.
Any station × product cross-product would be wrong.

**Temperature is 869 of 869** — every station in that population has data.

## 2. Two disjoint populations

The 7,323 baseline is the union of two referentials with **zero overlapping station codes**: 6,454
hydrometry stations and 869 temperature stations. Temperature stations carry no `code_site`,
`en_service` or `type_station`, so the five hydrometric products do not apply to them. The inventory
is sized accordingly: 6,454 × 5 + 869.

## 3. Availability is established from published totals, where the source offers them

For the daily and temperature products, `obs_elab` and `temperature/chronique` return a `count`.
Requested with `size=1` and **no date filter**, that count is the station's total over its whole
record. Availability therefore rests on a published total rather than on whether data happens to fall
in a tested window, and a zero is a published fact — recorded as `empty_no_data_published`.

That distinction matters, and it is why the daily products carry no window-bounded negatives at all.

## 4. Catalogue metadata cannot establish availability — and one field looks like it can

Issue #222 asks whether official metadata answers this for the population. It does not.

`referentiel/sites` publishes a **`grandeur_hydro`** field. It is `Q` for **all 9,284 sites** — a
constant, not a per-site declaration. `date_premiere_donnee_dispo_site` is **empty for all 9,284**.
`referentiel/stations` carries no availability or measurand field among its 39. Recorded in
`recordings/hubeau_sites_grandeur_declaration.recording.json` so the negative is checkable.

This is worth stating plainly because the next person will find `grandeur_hydro` and reasonably
assume it means something.

## 5. The station-to-site mapping is already published

`fetch.py` holds a hard-coded `_HYDROPORTAIL_IDENTITIES` with one entry, and raises for any other
station — which is why instantaneous products are selectable at exactly one station.

**The mapping is published for all 6,454 hydrometry stations** as `code_site`, non-null throughout,
and for `Y251002001` it is `Y2510020` — exactly the hard-coded value. It equals `code_station[:-2]`
for 100% of rows with no exceptions, but that is **corroboration of a published field, not a rule to
compute with**.

The mapping is **many-to-one**: 5,505 distinct sites, of which 755 carry 1,704 stations between them,
up to eight on one site. Since `discharge_instantaneous` is requested per site, those stations would
share a series. See [UNRESOLVED.md](UNRESOLVED.md) §3.

## 6. `observations_tr` works, and the current route is still the right one

The port notes record that Hub'Eau `observations_tr` "reproducibly returned HTTP 500", the stated
reason instantaneous products use HydroPortail. **That premise no longer holds** — it answers for
both H and Q today.

**But the current arrangement should stand.** Measured side by side, HydroPortail serves 2020 and
2026 where `observations_tr` serves a rolling 30 days, and HydroPortail was the *fresher* of the two
(12:15:00Z against 12:10:00Z). There is no data advantage to switching and years of history to lose.
The full comparison, and what would justify revisiting it, is in
[ROUTE_DECISIONS.md](ROUTE_DECISIONS.md).

`observations_tr` refuses an over-long window explicitly — HTTP 400 `ValidateDateMin`,
*"date can't be < 1 month from now"*. That is worth contrasting with ThaiWater, which silently clamps
a three-year request to one year with HTTP 200: the same class of constraint, opposite failure mode.

## 7. Instantaneous availability is partial, and says so

The instantaneous products have no whole-record total. `observations_tr` sees 30 days; HydroPortail
takes ~6.8 s per request. So:

- **Settled available** where the 30-day route reports observations.
- **All 2,314 out-of-service stations read zero for both products, with no exceptions** — the
  expected behaviour of a real-time route, and an explanation grounded in a published field rather
  than a guess.
- In-service stations reading zero were re-probed against HydroPortail over June 2026 and June 2023.
  That probe was **bounded to a sample**, because completing it means roughly five hours of sustained
  requests against a slow public portal.
- The remainder are **`uninvestigated`** — 1,973 pairs. `verify_evidence.py` asserts every such row
  states it is not a claim about the source.

Issue #222 is explicit that unfinished investigation must not be relabelled as source absence. This
is that rule being followed rather than a complete-looking answer. See [UNRESOLVED.md](UNRESOLVED.md)
§1 for how to finish it.

## 8. Producer

Established for **6,235 of 7,323 stations** from **two bulk requests**, not 7,323 lookups.

| Population | Sandre WFS layer | Field | Covered |
| --- | --- | --- | --- |
| Hydrometry | `sa:StationHydro` | `NomIntervenant` | 5,366 / 6,454 |
| Temperature | `sa:StationMesureEauxSurface` | `ProducteurDuJeu` | **869 / 869** |

These layers return the same properties as the per-station `id.eaufrance.fr` lookups already in the
repository — same station, same `NomIntervenant` — so that endpoint is a single-record view of this
layer. `sa:StationHydro` is the exact union of its six regional layers (5,180 + 59 + 80 + 53 + 47 +
21 = 5,440).

59 producing bodies for hydrometry, dominated by DREAL regional units; 7 for temperature, the Agences
de l'Eau and the Office de l'Eau de la Réunion. Hub'Eau and HydroPortail remain transports, not
producers.

**1,088 hydrometry stations have no producer** — 1,023 absent from Sandre and 65 with an empty field.
Two hypotheses were tested and both failed: not closure (879 are in service), not station type (873
are `STD`). See [UNRESOLVED.md](UNRESOLVED.md) §2.

## 9. Two errors made and corrected during this survey

Recorded because both are exactly what the issue warns against.

**A failed request was briefly counted as absence.** The first HydroPortail probe reported 779 pairs
with no data. 566 of those rows were DNS failures on the surveying machine, caused by opening a new
connection per request. All 568 failed rows were discarded, the client changed to reuse one
connection, and only genuinely answered rows kept. **No inventory row rests on that pass.**

**A route comparison was framed before it was measured.** `observations_tr` being alive was initially
described as though switching were the obvious conclusion. Measurement showed the opposite.

## 10. Contents

| Path | What it is |
| --- | --- |
| [`FINDINGS.md`](FINDINGS.md) | This document |
| [`ROUTE_DECISIONS.md`](ROUTE_DECISIONS.md) | Which route serves what, and why each was chosen |
| [`STATION_TABLE.md`](STATION_TABLE.md) | The station list: one row per station, per-product status |
| [`HANDOFF.md`](HANDOFF.md) | Identity, availability basis, request shape, client pitfalls |
| [`UNRESOLVED.md`](UNRESOLVED.md) | Unresolved cases and decisions required |
| [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md) | Every recording with integrity fields |
| `inventory/` | The 33,139-row inventory and the probe tables behind it |
| `scripts/` | Acquisition, composition and verification scripts |

## 11. Checks run

```
uv run python research/station-coverage/fr_hubeau/scripts/verify_evidence.py
```

**15/15 pass**, offline: recording hash integrity; required recording fields; no credential-like
request parameters; inventory 33,139 rows = 6,454 × 5 + 869; all 7,323 baseline stations accounted
for; no duplicate pairs; statuses within the declared vocabulary; no `unsupported` claim; every
available row citing an observation count; every `none published` row resting on a whole-record total
rather than a window; only products with a whole-record total recorded that way; window-bounded
negatives confined to the instantaneous products; `uninvestigated` confined to them too; every
`uninvestigated` row stating it is not a claim about the source; producer established for 6,235
stations.

`uv run ruff format`, `uv run ruff check`, `uv run ty check` clean.

**Access etiquette:** unauthenticated GET against public routes with a descriptive User-Agent.
Hub'Eau sustained ~1.7 req/s without refusal; HydroPortail is far slower at ~6.8 s per request, which
is why the probe against it was bounded rather than exhaustive. Only counts and point totals were
retained from the sweeps — no observation history was accumulated to establish support. No
credentials, cookies or tokens were sent or stored.

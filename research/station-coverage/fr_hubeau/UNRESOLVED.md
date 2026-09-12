# fr_hubeau — unresolved cases and decisions required

Separated from the established findings. Each entry states what was attempted, the exact remaining
question, and who must act: **@CooperBigFoot** (a decision or an acceptance) or further research.

---

## 1. Instantaneous history is checked for 682 pairs out of 7,286 — DECISION REQUIRED

**Established.** `observations_tr` settles every station reporting in its rolling 30 days. A fixed
sample of 682 pairs was re-probed against HydroPortail over 1–8 June 2026 and 1–8 June 2023: 61
available, 525 empty in both windows, 96 never answered (§2 below).

**Not checked against history at all:**

| | Pairs |
| --- | --- |
| in-service stations outside the sample | 1,976 |
| out-of-service stations | 4,628 |
| **total** | **6,604** |

The out-of-service pairs are included deliberately. Being out of service and silent for 30 days says
nothing about a station's historical record.

**Exact remaining question.** For those 6,604 pairs, does HydroPortail serve instantaneous data outside
the 30-day window?

**What finishing it would and would not establish.** Applying the same two windows to all 6,604, plus
retrying the 96 failures, is an upper bound of **13,400 requests** — two windows per pair — at a
measured median spacing of 3.52 s, about **13.1 hours** of sustained requests against a slow public
portal. It would settle "available" wherever those particular windows contain data. It would **not**
establish that any station lacks history: two empty windows are evidence about two windows only. There
is no whole-record total for the instantaneous products.

**Needed.** A decision on whether to spend that. `scripts/acquire_hydroportail_history.py` resumes;
widening the sample means widening `inventory/history_sample.csv`. Nothing here is a claim about the
source in the meantime.

---

## 2. 96 pairs that HydroPortail will not answer — REPORTED, RESEARCH INCOMPLETE

**Established.** 86 `discharge_instantaneous` and 10 `stage_instantaneous` pairs returned HTTP 500 or
HTTP 404 on every attempt, across three passes on 2026-09-08, 09-11 and 09-12 (982 HTTP 500 and 120
HTTP 404 attempts). The same 96 pairs failed every time; none recovered, and no answering pair began to
fail. They are `history_check_failed` in the inventory: **no claim about the source**.

**Exact remaining question.** Why does the station-series route refuse these particular stations —
station unknown to the portal, a station-type restriction, or a portal-side fault? Not investigated;
the status codes are the fact, the cause is not.

**Needed.** Further research if the delivery owner wants these resolved; a request to the HydroPortail
team is the obvious route. They must not be read as absence in the meantime.

---

## 3. Which discharge series a station selection should return — DECISION REQUIRED

**Established.** The site and station discharge series are different objects. HydroPortail states that
at most one station on a site is active at a time and that it produces the site's discharge, and the
preserved comparison shows a station reporting 282 points while its site series is empty, and two
stations on one site carrying series that agree with the site at 576/576 and 1/576 instants
respectively (`FINDINGS.md` §5, `evidence/station_site_comparison.json`).

Production requests the **site** series for `discharge_instantaneous` (`/sitehydro/ajax/{code_site}`)
and the **station** for `stage_instantaneous`. The mapping is many-to-one: 755 sites carry 1,704
stations.

**Exact remaining question.** Should a station selection return that station's own discharge series, or
its site's? Every population-scale discharge finding in this inventory is station-level; site-level
availability was surveyed only for the two example sites. A site series must not be presented as
independent measurements from each linked station.

**Not established, and needed if the site route is kept:** the activation calendar — which station
supplied a site's series over a given period. HydroPortail documents that such a calendar exists; no
route serving it was captured.

**Needed.** A modelling decision from the delivery owner. If the answer is "the station's own series",
the station route already exists and this inventory already describes it; if it is "the site's", the
population-scale availability for that product has not been surveyed.

---

## 4. 1,088 hydrometry stations with no organisation name — RESEARCH INCOMPLETE

1,023 are absent from `sa:StationHydro` entirely; 65 are present with an empty `NomIntervenant`.
Two hypotheses failed: not closure (879 of the 1,023 are in service), not station type (873 are `STD`).
Hub'Eau's own referential carries no producer-like field among its 39.

**Exact remaining question.** Where is the responsible organisation for those stations published?

**Needed.** Further research, most likely a direct enquiry to Sandre or Hub'Eau. Nine Sandre stations
are also absent from our baseline, possibly the same boundary seen from the other side.

---

## 5. What the organisation fields actually attest — ACCEPTANCE REQUIRED

**Established.** `NomIntervenant` (hydrometry) and `ProducteurDuJeu` (temperature) give a name for
6,235 stations. The sources define `NomIntervenant` as an organisation's name with no role, and
`ProducteurDuJeu` as the producer of the **station-referential dataset** (`FINDINGS.md` §8).

**Exact remaining question.** Which organisation issued or produced the observation series RivRetrieve
retrieves? Neither field answers it, and no captured source does.

**Consequence to accept.** This survey supplies **verified organisation-name matches**, not established
attribution for the retrieved data. The inventory records each name under its source field with a scope
code, and the handoff forbids extending it to historical measurements or to a shared site's series.

**Related, and flagged rather than changed:** the committed `catalogue/provenance.json` already names
DEAL Guadeloupe, DREAL Occitanie and Agence de l'Eau Artois-Picardie as `issuer` for the three
certified stations, each resting on an `id.eaufrance.fr` lookup described as "naming the producing SIE
body". Those lookups return exactly these two fields — the same fields whose role the source does not
state. Production code is out of scope for this research issue, so nothing was changed; the delivery
owner may want to look at it.

---

## 6. Response bytes are kept only where they carry no observation — ACCEPTANCE REQUIRED

**The request.** Review 3 asked to "preserve the actual source responses supporting availability
conclusions".

**What is delivered.** Every response — successful or failed — keeps its exact request URL, HTTP
status, media type, UTC acquisition instant, byte size and SHA-256 of the full bytes, plus derived
readings. Whole bodies are kept wherever they carry no observation value, which covers **all 33,145
answered Hub'Eau count responses**, so every availability count for the daily, temperature and 30-day
products re-derives offline from the stored response.

**What is not delivered.** Bodies that carry observation values are not stored: the HydroPortail series
responses with points (the 61 available and the site/station comparison captures), and the illustrative
sample-row recordings. For those, the digest and readings stand in for the bytes.

**Why.** This project does not commit source observation data to the repository. No agency here grants
redistribution, and the rule is enforced mechanically by `scripts/observation_scan.py` and
`tests/test_fr_hubeau_research_stores_no_observation_values.py`.

**This bullet is therefore met in part, and only @CooperBigFoot can close it.** If full byte retention
for observation-bearing responses is required, that is a policy decision about redistribution, not
something this survey can decide.

**One related piece of history.** Earlier commits on this branch did commit recordings containing
observation values; they were stripped in this revision, but the bytes remain reachable in the branch's
git history. Whether to squash or rewrite before merging is the maintainers' call.

---

## 7. Facts the source does not publish — CLOSED AS UNKNOWN

- **Per-station product availability.** Neither referential declares it; `grandeur_hydro` is the
  constant `Q` for all 9,284 sites and `date_premiere_donnee_dispo_site` is empty for all.
- **Timezone of the daily and temperature products.** No captured source establishes one.
- **Published record bounds.** Counts establish that observations exist, not the span they cover.
- **Rate limits.** None published — no `X-RateLimit` or `Retry-After` header, no quota in the OpenAPI
  specification. Not the same as there being no limit.

---

## 8. The hard-coded HydroPortail identity map — REPORTED, NO DECISION NEEDED

`fetch.py` holds `_HYDROPORTAIL_IDENTITIES` with one entry and raises for any other station. The
mapping is published as `code_site` for every hydrometry station and matches for `Y251002001`.
Reported, not proposed: production code is out of scope here. See `ROUTE_DECISIONS.md` §3.

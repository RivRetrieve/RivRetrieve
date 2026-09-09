# fr_hubeau — unresolved cases and decisions required

Separated from the established findings. Each entry states what was attempted, the exact remaining
question, and whether it needs a decision from the delivery owner (@CooperBigFoot) or further
research.

---

## 1. Instantaneous availability is not fully established — DECISION REQUIRED

**Established.** `observations_tr` gives a per-station count for H and Q, so every station with data
in the last 30 days is settled as `available`. All 2,314 out-of-service stations read zero for both
products, with no exceptions — the expected behaviour of a real-time route.

**Attempted for the rest.** Stations marked `en_service = True` that still read zero are the
surprising cases. They were re-probed against HydroPortail — the route actually used in production —
over two windows outside the real-time horizon (June 2026 and June 2023).

**Why it stopped.** A single HydroPortail request takes about 6.8 seconds. Probing all 2,655
in-service zero pairs would mean roughly five hours of sustained requests against a slow public
portal. The probe was therefore bounded to a sample, and the remainder are recorded as
`uninvestigated`.

**Exact remaining question.** For the in-service stations outside the sample, does HydroPortail serve
instantaneous data outside the 30-day window? This survey does not say, and deliberately does not
guess. Issue #222 is explicit that unfinished investigation must not be relabelled as source absence,
and `verify_evidence.py` asserts that every `uninvestigated` row states it is not a claim about the
source.

**Needed.** A decision on whether to spend the time to complete the probe. It is mechanical:
`scripts/probe_instantaneous_history.py` resumes where it left off, and raising `SAMPLE_LIMIT`
finishes it. The cost is hours of load on a slow public portal, which is why it was not taken
unilaterally.

---

## 2. 1,023 stations absent from the Sandre producer referential — RESEARCH INCOMPLETE

**Established.** The producer is established for 6,235 of 7,323 stations from two bulk Sandre WFS
requests: `NomIntervenant` for hydrometry stations, `ProducteurDuJeu` for temperature stations. All
869 temperature stations are covered.

**The gap.** 1,023 hydrometry stations are absent from `sa:StationHydro` entirely, and 65 more are
present with an empty `NomIntervenant`.

**Attempted.** Two hypotheses were tested and both failed. It is not closure — 879 of the 1,023 are
`en_service = True`. It is not station type — 873 are ordinary `STD`. Hub'Eau's own
`referentiel/stations` carries no producer field at all (39 fields, none producer-like), so it cannot
fill the gap. `sa:StationHydro` was confirmed to be the union of its six regional layers, so nothing
is missed by querying the parent layer.

**Exact remaining question.** Why do 1,023 stations published by Hub'Eau's hydrometry referential not
appear in the Sandre station referential, and where is their producing body published?

**Needed.** Further research, most likely a direct enquiry to Sandre or the Hub'Eau team. Nine Sandre
stations are also absent from our baseline, which may be the same boundary seen from the other side.

---

## 3. Instantaneous discharge is requested per site, and sites are shared — DECISION REQUIRED

`discharge_instantaneous` is declared with `entity_kind = "site"`, while `stage_instantaneous` uses
the station. The station-to-site mapping is many-to-one: **755 sites carry 1,704 stations between
them**, up to eight stations on one site.

Stations sharing a site would therefore resolve to the same discharge series. Whether
`discharge_instantaneous` is a station-level or a site-level product, and how the catalogue should
express that, is a modelling question this survey cannot settle.

---

## 4. The hard-coded HydroPortail identity map — REPORTED, NO DECISION NEEDED

`fetch.py` holds `_HYDROPORTAIL_IDENTITIES` with a single entry and raises `FatalContractError` for
any other station. The mapping it encodes is published for every station as `code_site` in the
committed native table, and matches the hard-coded value exactly for `Y251002001`.

This is reported rather than proposed as a change, because production code is out of scope for a
research issue. See `ROUTE_DECISIONS.md` §3.

---

## 5. Facts the source does not publish — CLOSED AS UNKNOWN

Reported so they are not mistaken for gaps in the research.

- **Per-station product availability.** Neither referential declares it. `referentiel/sites` has a
  `grandeur_hydro` field that looks like it should: it is `Q` for **all 9,284 sites**, a constant
  rather than a per-site fact. `date_premiere_donnee_dispo_site` is **empty for all 9,284**. Recorded
  in `recordings/hubeau_sites_grandeur_declaration.recording.json` so the negative is checkable.
- **Timezone of the daily and temperature products.** Unchanged: no captured source establishes one,
  so it stays `unknown`. `observations_tr` and HydroPortail both publish UTC, but that says nothing
  about `obs_elab`.
- **Published record bounds.** Not published. Counts establish that observations exist, not the span
  they cover.
- **Rate limits.** None published: no `X-RateLimit` or `Retry-After` headers and no quota in the
  OpenAPI specification. That is not the same as there being no limit.

---

## 6. Two corrections made during this survey — REPORTED

Recorded because both are the kind of error the issue warns against, and both were made here.

**A failed request was briefly counted as absence.** The first HydroPortail probe reported 779 pairs
with no data in either window. 566 of those rows were `URLError: nodename nor servname provided` —
DNS failures on the surveying machine, caused by opening a new connection per request. Those 568 rows
were discarded, the client was changed to reuse one connection, and only genuinely answered rows were
kept. No inventory row rests on that first pass.

**A route comparison was framed before it was measured.** `observations_tr` being alive was initially
described as though switching to it were the obvious conclusion. Measurement showed the opposite: it
serves 30 days where HydroPortail serves years, and it is not fresher. See `ROUTE_DECISIONS.md`.

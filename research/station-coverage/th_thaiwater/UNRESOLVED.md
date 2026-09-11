# th_thaiwater — unresolved cases and decisions required

Separated from the established findings. Each entry states what was attempted, the exact remaining
question, and whether it needs a decision from the delivery owner (@CooperBigFoot) or further
research.

---

## 1. Long requests are shortened without saying so; exact limit not established — DECISION REQUIRED

Day counts are inclusive calendar dates (both endpoints counted; elapsed days = dates − 1).

**Established** (`inventory/window_limit_readings.csv`, station `1373273`, recorded 2026-09-07).
Requests ending 2026-09-06 of 7, 91, 364, 365 and 366 dates came back exactly as requested. Requests
of 458 dates (from 2025-06-06) and 1,097 dates (from 2023-09-06) both came back as
2025-09-06 .. 2026-09-06, 366 dates, with HTTP 200, `result: "OK"` and no indication of the
shortening. At the public surface, `rr.fetch` for `2023-01-01 .. 2026-09-06` (1,345 dates) returned
rows from 2025-09-08 to 2026-09-06, 364 dates or 27% of the period, with no issue or warning naming
the shortfall (`inventory/window_truncation_observation.json`).

**Corrected.** Earlier text said the 366-date request was clamped and that calendar-year chunks
would therefore fail in leap years. The 366-date request was honoured, and the leap-year conclusion
does not follow from this evidence; both are withdrawn.

**Not established — the exact maximum.** The clamped start 2025-09-06 is both `end_date` − 365
elapsed days and `end_date` − one calendar year; these endpoints cannot distinguish the two. No
tested window contains 29 February, and 367–457 dates were not tested. The largest size demonstrated
to work is 366 dates ending 2026-09-06; that is not a measured general maximum. A request whose two
candidate starts differ — for example one ending 2024-03-01, where end − 365 days is 2023-03-02 and
end − one year is 2023-03-01 — would distinguish them. It was not run.

**Reported but not evidenced here.** The original survey reported walking `end_date` backwards a year
at a time to a continuous 2023-02-02 .. 2026-09-06 record for station `1117894`. No recording or table
of that walk is committed.

**Exact remaining question.** Should retrieval split requests with `capped-span`, and at what `size`?
The planner's `size` counts inclusive dates; 366 is the largest demonstrated, and a smaller size such
as 365 is a conservative choice, not a measured limit. Should a split or a source-side shortening be
surfaced to callers as an issue? Is the distinguishing probe above wanted before choosing?

**Needed.** A decision from the delivery owner. This survey changes no retrieval code. `HANDOFF.md`
§3 records what a fix must respect: the shortening keeps `end_date` and moves `start_date`, so each
chunk must carry its own `end_date`.

---

## 2. Population churn between captures — DECISION REQUIRED

`waterlevel_load` returned 825 stations on 2026-08-02 and 1,405 on 2026-09-07: 605 present now that
were not in the baseline, and 25 baseline stations not present today.

**Attempted.** `generate_catalogue.py` was read to rule out a filter on our side — it applies none and
fails the build rather than dropping rows, so the difference is upstream. Three of the 25 absent
stations were probed on the graph route: all three answer `result: "OK"`, and one (`1119916`) still
publishes values, so absence from the snapshot is not evidence that a station is gone. Every live row
carries telemetry from the preceding week, which is consistent with the endpoint returning currently
reporting stations rather than a stable registry.

**Exact remaining question.** Is the 605-station difference genuine onboarding, or does
`waterlevel_load` return a varying subset of a larger station set? This survey cannot separate the
two from two captures five weeks apart. The existing port notes already record comparable churn
("87 new IDs are present and 16 legacy IDs are absent"), so this is a continuing property of the
source rather than a new anomaly.

**Needed.** A scope decision on whether coverage extends to the 1,405-station live population. This
survey deliberately scopes its inventory to the committed 825-station baseline, as issue #224 does.
The 605 additional stations are **not** surveyed and **not** merged.

---

## 3. Twelve stations empty over 91 dates — REPORTED, NO DECISION NEEDED

Twelve stations return a complete time grid with no non-null value for either product over
2026-06-08 .. 2026-09-06 (91 dates): `11688546`, `11688685`, `11688715`, `11688749`, `11688817`,
`11688823`, `11688849`, `11689002`, `11689003`, `11689067`, `11689072`, `11689150`. Each response is
kept whole in `evidence/graph_bodies_without_observations.zip`, under the `request_id` its inventory
rows cite.

They form a contiguous id block, which is consistent with a batch of registered stations not yet
reporting. Recorded as `empty_in_tested_window`, never as unsupported — the source states nothing
about whether they can supply a measurement. A window longer than 91 dates was not tested.

---

## 4. Facts the source does not publish — CLOSED AS UNKNOWN

- **Timezone.** `graph_data[].datetime` is naive wall clock with no offset or zone field. Stays
  `unknown`; Asia/Bangkok must not be inferred.
- **Temporal support, statistic, frequency, period type, period anchor.** The source declares none.
- **Published record bounds.** Not published. This survey observed a record beginning for one station
  by probing, which is an observation about that station's returned data and not a published bound.
- **Horizontal CRS.** Unchanged: the captured coordinate-standard page specifies ISO 6709 formatting
  but no datum, CRS, EPSG code or projection.

---

## 5. Datum wording on the stage field — NOTED, NOT REOPENED

The already-recorded official application bundle maps `graph_data.value` to **water level in m MSL**,
while the packaged product is `stage_reported` in m. That mapping was established by earlier recorded
evidence and this survey does not reopen it; it is noted because the datum wording bears on how the
product is interpreted.

---

## 6. Producer — CLOSED

Resolved before this survey and confirmed by it. Four issuing agencies with HII additionally
operating the platform; `origins.py` binds every station to its agency and fails the build on
disagreement. No further research needed. See `HANDOFF.md` §8.

---

## 7. Retention of response bytes — YOUR ACCEPTANCE REQUIRED

**This does not meet your request literally.** You asked to "Preserve the actual source responses
supporting each availability conclusion" and to retain "the exact non-secret request, HTTP status,
media type, actual acquisition date and integrity hash with the response". Everything in that list
is retained for every response **except the response bytes of the 1,336 graph responses that carry
observations**, and of the 13 recordings that carried them.

**Retained, for all 1,377 graph requests** (`evidence/graph_receipts.csv`):

- exact request URL, HTTP status, media type, UTC acquisition instant, byte size and SHA-256 of the
  full response;
- derived readings: grid rows, non-null counts per field, grid endpoints and the `result` field.

Whole bytes are retained for the 39 responses carrying no observation value
(`evidence/graph_bodies_without_observations.zip`, 129,554 B) and for 8 recordings. Every inventory
row links to its own receipt.

**Why the rest is not.** This project does not redistribute source observations, so committing them
is not available to us.

**Consequence, stated plainly.**

- **What offline verification can check:** every inventory row against its receipt, and, for the 39
  retained bodies, digest, size and every derived reading.
- **What it cannot do:** for the other 1,336 responses it cannot recompute the digest or re-derive a
  count. The digest fixes what was received, but it cannot be checked against bytes from this
  repository.
- **Why a re-fetch settles nothing:** re-fetching the same URL is not guaranteed to return the same
  bytes. The 2026-09-11 replacement did reproduce the 2026-09-07 counts exactly for all 1,374
  requests, but bytes could not be compared, because the original survey recorded no digests.

**Size estimate for retaining everything, and a proposed handoff — for agreement before any
arrangement.** Your review asked for this if preserving the required responses would be too large.

- **Measured size:** the 1,374 successful graph responses total 504,130,869 B (25,998,678 B gzip-6).
  The 1,336 carrying observations total 500,847,708 B (25,874,399 B gzip-6).
- **What exists now:** these bodies were read in memory to derive the receipts and were never written
  to disk, so no copy exists.
- **What a handoff would take:** retaining them would mean a further acquisition, identified by its
  own dates, held outside this repository under access the project controls. That has not been done
  and will not be without your agreement. It would still be a copy of the agency's observations, so
  the redistribution question applies to it too.

**History.** The 13 stripped recordings' observation-bearing bytes remain in this branch's history
(commits `67ed409` .. `e5c8907`) unless the branch is squash-merged or rewritten. That is a
repository decision, noted here so it is not assumed to be settled.

**Needed.** Your explicit acceptance that request, status, media type, acquisition instant, byte
size, full-response digest and derived readings — with whole bytes only for responses carrying no
observation — are sufficient evidence for this survey. If they are not, say what would be.

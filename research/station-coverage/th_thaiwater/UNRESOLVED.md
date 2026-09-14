# th_thaiwater — unresolved cases and decisions required

Separated from the established findings. Each entry states what was attempted, the exact remaining
question, and whether it needs a decision from the delivery owner (@CooperBigFoot) or further
research.

---

## 1. Conservative source window — SETTLED; exact maximum remains unknown

The agreed vision selects 365 inclusive source dates per `capped-span` request. Complete
normal 2025-09-09 .. 2026-09-08 and leap-containing 2023-03-03 .. 2024-03-01 captures
honoured that size. The leap response is null-only and supports no history claim.
The older 366-inclusive-date example was honoured too, not shortened. These captures do
not measure the source's exact maximum or a universal leap-year rule.

Engine padding precedes splitting; no 361-date public restriction or backwards walk
is required. The source end of the earlier public fetch was 2026-09-08 after padding,
not the direct probe's 2026-09-06. Its two-day shift is explained by padding and clipping.
D11's unstable-floor inference is withdrawn. No new survey is a prerequisite.

---

## 2. Population churn between captures — BASELINE SCOPE SETTLED

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

**Settled scope.** Keep the original 825 station identities, including the 25 absent from
this later snapshot. The 605 additional stations are not part of this outcome. No new
live station discovery or investigation of platform onboarding is required.

---

## 3. Twelve stations empty over 91 dates — REPORTED, NO DECISION NEEDED

Twelve stations return a complete time grid with no non-null value for either product over
2026-06-08 .. 2026-09-06 (91 dates): `11688546`, `11688685`, `11688715`, `11688749`, `11688817`,
`11688823`, `11688849`, `11689002`, `11689003`, `11689067`, `11689072`, `11689150`. Each response is
kept whole in `evidence/graph_bodies_without_observations.zip`, under the `request_id` its inventory
rows cite.

They are recorded as `empty_in_tested_window` for those acquired windows and map to
selectable `unknown`, never unsupported. Their numeric ID proximity is not evidence
of onboarding state. Longer history was not established by those responses.

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

## 6. Supplying agencies and platform — SCOPE SETTLED

Retain the verified per-station supplying agencies and HII's distinct platform role.
`origins.py` rejects mismatched station/agency IDs. These bindings do not reconstruct
all original measurement producers or historical operators; that limit remains explicit.
No upstream-producer inquiry is a prerequisite. See `HANDOFF.md` §8.

---

## 7. Private body verification and research publication — REVIEW REQUIRED

The September 11 research revision discarded 1,336 observation-bearing graph bodies and
stripped 13 example recordings. Those historical facts remain disclosed in FINDINGS;
hashes and derived readings alone do not certify the missing bytes.

Nicolas subsequently preserved complete governing answers for all 825 baseline stations:
813 September 13 replacement responses and 12 reused complete September 11 null responses.
The final 1650 counts/statuses match the revised research; their actual dates/material
identities now live in `inventory/governing_station_product_evidence.csv`. Agreement of
counts does not recover discarded original bytes or certify adaptive-survey anecdotes.

The controlled full bundle is 25,582,314 bytes, SHA-256
`46320ee0fa6b908c6009f223f59d6daa94f836bdfe3bbf82fee6d4354779c73f`.
Keep it private and out of distributions. A portable explicit-root verifier reads the
full bodies at acceptance and final integration; public CI verifies ledger/binding
consistency only. See HANDOFF §10. Missing controlled inputs require arranging an
authorized handoff, not repeating the survey or passing a hash-only check.

This does not create a rule banning measurement values from genuine source recordings.
The new blanket scanners/stripping script are not adopted. Minimal recorded-test inputs
must follow existing review and recording conventions; no corpus upload is authorized.
Source terms/citation words stay verbatim, without licence classification or a legal
inference about publication permission.

The older stripped recordings remain in branch history. Nicolas chooses the normal
reviewed merge strategy explicitly. No branch history is rewritten here. Research
acceptance and merged-input conditions remain open until reviewed delivery is complete.

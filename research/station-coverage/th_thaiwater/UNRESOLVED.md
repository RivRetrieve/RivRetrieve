# th_thaiwater — unresolved cases and decisions required

Separated from the established findings. Each entry states what was attempted, the exact remaining
question, and whether it needs a decision from the delivery owner (@CooperBigFoot) or further
research.

---

## 1. Multi-year requests return one year without saying so — DECISION REQUIRED

**Established.** The graph route silently clamps `start_date` to `end_date` minus 365 days
(`inventory/window_limit_probe.csv`). Measured at the public surface, a request for
`2023-01-01 .. 2026-09-06` returns 2025-09-08 .. 2026-09-06 — 27% of the requested period — with no
issue or warning naming the shortfall (`inventory/window_truncation_observation.json`, reproducible
with `scripts/reproduce_window_truncation.py`).

**Established that the data is reachable.** Walking `end_date` backwards a year at a time retrieved a
continuous 2023-02-02 .. 2026-09-06 record for station `1117894`.

**Exact remaining question.** Should retrieval split requests into ≤365-day chunks (the repository
already does this for `br_ana` and `ca_eccc`), and should a split or a source-side cap be surfaced to
callers as an issue?

**Needed.** A decision from the delivery owner. This survey changes no retrieval code. `HANDOFF.md`
§3 records the two constraints a fix must satisfy: chunks must carry their own `end_date` because the
clamp is anchored there, and 365 days is the safe maximum because 366 is already clamped.

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

## 3. Twelve stations empty over 90 days — REPORTED, NO DECISION NEEDED

Twelve stations return a complete time grid with no non-null value for either product over
2026-06-08 .. 2026-09-06: `11688546`, `11688685`, `11688715`, `11688749`, `11688817`, `11688823`,
`11688849`, `11689002`, `11689003`, `11689067`, `11689072`, `11689150`.

They form a contiguous id block, which is consistent with a batch of registered stations not yet
reporting. Recorded as `empty_in_tested_window`, never as unsupported — the source states nothing
about whether they can supply a measurement. A longer window than 90 days was not tested.

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

# th_thaiwater implementation handoff

For the implementing agent. Everything below is established by a recording in `recordings/` or a
probe table in `inventory/` unless it appears under "Not established".

Baseline commit `67796ab8d793867aaaaf9c6fb55bec208adaeab8` · native table captured
`2026-08-02T12:42:03Z` (825 stations) · catalogue snapshot, window probe and recordings `2026-09-07` ·
availability evidence re-acquired `2026-09-11` (FINDINGS §3). Day counts are inclusive calendar
dates (both endpoints counted; elapsed days = dates − 1).

## 1. Identity and population

`station.id` is the identity, as the existing port notes already require; `station.tele_station_oldcode`
is never identity. Ids are unique with no nulls across the population.

The catalogue endpoint `waterlevel_load` returns the currently reporting telemetry stations, not a
stable registry — every row in the live capture carries telemetry from the preceding week. Station
counts therefore move: 825 at the 2026-08-02 baseline capture, 1,405 on 2026-09-07. Absence from a
snapshot does not mean a station is gone; see §6.

## 2. Route

```
GET https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph
    ?station_type=tele_waterlevel&station_id=<station.id>&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
```

One response publishes **both** products: `data.graph_data[]` rows carry `datetime`, `value`
(stage) and `discharge`. The existing coalescing behaviour is correct — one call per
station-window serves both products.

Access requires no credentials. No pagination exists on either route: the graph response is a
single complete array, and `waterlevel_load` returns the whole population in one body.

## 3. THE WINDOW LIMIT — read this before implementing retrieval

**The source silently shortens long requests.** The port notes currently state that no publisher
cap is claimed; this survey recorded one.

Day counts below are **inclusive calendar dates** (both endpoints counted; elapsed days = dates − 1).
Measured for station `1373273` on 2026-09-07, every request ending 2026-09-06
(`inventory/window_limit_readings.csv`, derived from `inventory/window_limit_probe.csv`):

| Requested | Dates | Rows | Returned |
| --- | --- | --- | --- |
| 2026-08-31 .. 2026-09-06 | 7 | 1,008 | as requested |
| 2026-06-08 .. 2026-09-06 | 91 | 13,104 | as requested |
| 2025-09-08 .. 2026-09-06 | 364 | 52,416 | as requested |
| 2025-09-07 .. 2026-09-06 | 365 | 52,560 | as requested |
| 2025-09-06 .. 2026-09-06 | **366** | 52,704 | **as requested** |
| 2025-06-06 .. 2026-09-06 | 458 | 52,704 | **shortened** to 2025-09-06 .. 2026-09-06 (366 dates) |
| 2023-09-06 .. 2026-09-06 | 1,097 | 52,704 | **shortened** to 2025-09-06 .. 2026-09-06 (366 dates) |

The shortening is silent: HTTP 200, `result: "OK"`, no warning field, and the response is
indistinguishable in shape from an honoured request.

**What is demonstrated and what is not.** A request of 366 dates ending 2026-09-06 is honoured; that
is a demonstrated working size. The source's exact maximum is **not** established: the clamped start
2025-09-06 is both `end_date` − 365 elapsed days and `end_date` − one calendar year, no tested window
contains 29 February, and 367–457 dates were not tested. See `UNRESOLVED.md` §1.

**Observed consequence at the public surface** (`inventory/window_truncation_observation.json`,
reproducible with `scripts/reproduce_window_truncation.py`): `rr.fetch` for
`2023-01-01 .. 2026-09-06` (1,345 dates) returned rows from 2025-09-08 through 2026-09-06 (364 dates) —
**27% of the requested period**, with no issue or warning naming the shortfall. The two issues
emitted are unrelated provenance notices.

**The engine already owns this.** ADR 0017 makes window splitting engine-owned and names "a capped
response size" as one of the two reasons a provider declares a granularity. `window_planning.py`
registers a `capped-span` planner whose `size` is the number of inclusive dates per chunk (a chunk
runs from `cursor` to `cursor + size − 1` days); `tests/test_internal_window_planning.py` exercises it
with `size=365`.

`th_thaiwater/config.py` currently declares:

```python
WindowDeclaration(
    granularity=WindowGranularity("date"),
    rendering=WindowRenderingVocabulary.DATE,
    stop_convention=StopConvention.INCLUSIVE,
)
```

which renders one request for the whole window and never splits. The source shortens long requests,
so the declaration under-states it. A declaration consistent with the recorded behaviour is
`capped-span` with the same rendering and stop convention. Its `size` counts inclusive dates: 366 is
the largest size demonstrated to be honoured (ending 2026-09-06). A smaller size such as 365 is a
conservative working choice, not a measured limit; which to declare is the delivery owner's
decision. No new engine capability is required and no provider-side arithmetic is involved — the
granularity is a fact about the source, the splitting is the engine's.

What the probe establishes for a fix:

- The shortening keeps `end_date` and moves `start_date`: holding `end_date` fixed and moving
  `start_date` earlier than 2025-09-06 returned the same 2025-09-06 .. 2026-09-06 span. Each chunk
  must therefore carry its own `end_date`.
- It does **not** establish a rule for windows containing 29 February, nor whether calendar-year
  chunks are honoured in leap years; no tested window distinguishes the candidate rules
  (`UNRESOLVED.md` §1).

The original survey reported that walking `end_date` backwards a year at a time reached a continuous
2023-02-02 .. 2026-09-06 record for station `1117894`; no recording or table of that walk is
committed, so it is not evidenced here.

What remains a decision — whether to emit an issue when a request is split, and whether to surface
the source's cap to callers — is the delivery owner's, not this survey's.

Worth checking beyond this provider: no provider in `src/rivretrieve/_internal/providers/` currently
declares `capped-span` or `n-year-chunk`, and none sets `size`. Both planners are implemented and
unit-tested but unused. Whether other sources cap their windows and are similarly under-declared was
not surveyed here.

## 4. Availability basis

Availability is established per station from the graph route, not from catalogue metadata.

**The catalogue snapshot cannot establish it.** The `waterlevel_load` snapshot (acquired
2026-09-07T15:08:00Z) reports each station's latest reading at one instant. The inventory's graph
status covers a 7- or 91-date window ending 2026-09-06 (graph responses acquired 2026-09-11). Those
are different time questions (`inventory/metadata_vs_graph.csv`, `metadata_vs_graph_summary.json`):

- **800 baseline stations are present in the snapshot.** For 778 of them (97.25%) the `discharge`
  field agrees with the graph window. For 22 it does not: 18 have a null field where the graph
  publishes discharge, and 4 have a set field where the graph publishes none.
- **25 baseline stations are absent from the snapshot**, so it says nothing about them; 4 of them
  publish discharge on the graph route.
- **Counting absent as null** gives 26 disagreements over 825.

These disagreements show that the snapshot does not predict window availability. They are not
evidence that the source's metadata is wrong. For stage, `waterlevel_m` is null for all 1,405 live
and all 825 baseline stations. `waterlevel_msl` is a different quantity and is not evidence for the
graph's `value` field.

A station is recorded `available` for a product when its cited graph response publishes at least
one non-null value for that product's field. It is recorded `empty_in_tested_window` when the cited
response is a complete time grid containing no non-null value for that field. Every inventory row
cites the one receipt it copies (`evidence/graph_receipts.csv`); the two products of a station share
one response.

## 5. Null and error behaviour

**HTTP status carries no availability signal.** All 825 7-date requests and 546 of the 549 first
91-date attempts (2026-09-11) returned 200 with `result: "OK"`, including stations with no data at
all — the route answers with a full time grid of nulls rather than an error or an empty array.

Recorded error behaviour (`recordings/error_*.recording.json`, and one receipted body in
`evidence/graph_bodies_without_observations.zip`):

| Condition | Response |
| --- | --- |
| Nonexistent `station_id` | **HTTP 500** with a Go panic stack trace, not JSON |
| Unknown `station_type` | **HTTP 500** with a Go panic stack trace, not JSON |
| Missing `station_id` | **HTTP 200** with body `{"result":"NO","data":"422:  No station id"}` |
| `end_date` before `start_date` | **HTTP 200**, `result: "OK"`, zero rows — no error |
| Source database error (station `1109499`, 2026-09-11) | **HTTP 200** with body `{"result":"NO","data":"500:  Internal Database Error ...pq: out of shared memory"}`; a retry 44 minutes later returned a full grid |

Two 91-date requests (`1109525`, `1117431`) also timed out after 300 s and succeeded on retry.

Two consequences for implementation: a 200 response may still carry a `result: "NO"` error body and
must be checked, and a malformed request can return a non-JSON 500 body that will fail a naive
decode.

## 6. Sparse reporting and window length

Grid cadence differs per station: over 7 dates (2026-08-31 .. 2026-09-06), 424 baseline stations
returned 144 rows per date (10-minute) and 401 returned 24 (hourly)
(`inventory/inventory_summary.json`).

This makes short windows unsafe for availability claims. Of 26 stations with no values in the 7-date
window, 14 published a value over the 91 dates 2026-06-08 .. 2026-09-06; across all re-probed
stations 14 gained stage and 7 gained discharge. The 12 that remained empty over 91 dates are a
contiguous id block (`11688546`–`11689150`).

Any future availability check should use a window of at least 91 dates before recording a station as
empty.

## 7. Fields, units, time semantics

| Graph field | Product | Unit |
| --- | --- | --- |
| `value` | `stage_reported` | m |
| `discharge` | `discharge_reported` | m³/s |

`value_out` remains uninterpreted, as today. No unit conversion is required.

The already-recorded official application bundle maps `graph_data.value` to **water level in m MSL**.
The packaged product is `stage_reported` in m. This survey does not reopen that mapping; it is noted
because the datum wording bears on interpretation.

`graph_data[].datetime` values are naive wall clock with no offset or zone field. No captured source
establishes a zone. `time_zone` stays `unknown`; Asia/Bangkok must not be inferred from country,
coordinates or station code. Temporal support, statistic, frequency, period type and period anchor
remain `unknown` — the source declares none, and no daily means may be derived.

## 8. Producer

Already established in the committed provenance and confirmed by this survey: four issuing agencies
— Electricity Generating Authority of Thailand, Hydro–Informatics Institute, Royal Irrigation
Department, and Friend in Need (of "Pa") Volunteers Foundation — with HII additionally operating the
ThaiWater API platform. `origins.py` binds every station to its agency and fails the build when
`agency.id` and `station.agency_id` disagree, so the producer/operator distinction needs no further
research.

The live platform lists ten agencies; the baseline population draws on four of them.

## 9. Things that must not be done

- Do not send a window longer than 366 dates — the largest demonstrated to be honoured — and assume
  it was; compare the first returned date with the requested start. The exact maximum is not
  established.
- Do not treat HTTP 200 or `result: "OK"` as evidence that data exists.
- Do not treat absence from `waterlevel_load` as evidence that a station is gone or dataless.
- Do not use the snapshot `discharge` field as the availability basis. It disagrees with the graph
  window for 22 of the 800 baseline stations present in the snapshot, and it says nothing about the
  25 that are absent.
- Do not use `waterlevel_msl` as evidence for the graph `value` field.
- Do not record a station empty on a short window; use 91 dates or more.
- Do not infer a timezone, statistic, frequency or record bound, and do not derive daily means.

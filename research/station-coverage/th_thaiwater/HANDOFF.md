# th_thaiwater implementation handoff

For the implementing agent. Everything below is established by a recording in `recordings/` or a
probe table in `inventory/` unless it appears under "Not established".

Baseline commit `67796ab8d793867aaaaf9c6fb55bec208adaeab8` · native table captured
`2026-08-02T12:42:03Z` (825 stations) · this survey captured `2026-09-07`.

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

**The source silently clamps `start_date` to `end_date` minus 365 days.** The port notes currently
state that no publisher cap is claimed; this survey establishes one.

Measured behaviour for station `1373273` (`inventory/window_limit_probe.csv`):

| Requested span | Rows | Returned span |
| --- | --- | --- |
| 7 days | 1,008 | exactly as requested |
| 90 days | 13,104 | exactly as requested |
| 364 days | 52,416 | exactly as requested |
| **365 days** | 52,560 | **exactly as requested** |
| 366 days | 52,704 | **clamped** to end − 1 year |
| 15 months | 52,704 | **clamped** to end − 1 year |
| 3 years | 52,704 | **clamped** to end − 1 year |

The clamp is silent: HTTP 200, `result: "OK"`, no warning field, and the response is
indistinguishable in shape from an honoured request.

**Observed consequence at the public surface** (`inventory/window_truncation_observation.json`,
reproducible with `scripts/reproduce_window_truncation.py`): a request for
`2023-01-01 .. 2026-09-06` returns 2025-09-08 .. 2026-09-06 — **27% of the requested period**, with
no issue or warning naming the shortfall. The two issues emitted are unrelated provenance notices.

**The engine already owns this.** ADR 0017 makes window splitting engine-owned and names "a capped
response size" as one of the two reasons a provider declares a granularity. `window_planning.py`
registers a `capped-span` planner that takes a size in days and splits the fetch window into chunks
of that size; `tests/test_internal_window_planning.py` exercises it with `size=365`.

`th_thaiwater/config.py` currently declares:

```python
WindowDeclaration(
    granularity=WindowGranularity("date"),
    rendering=WindowRenderingVocabulary.DATE,
    stop_convention=StopConvention.INCLUSIVE,
)
```

which renders one request for the whole window and never splits. The source's cap is real, so the
declaration under-states it. The declaration that matches the measured behaviour is `capped-span`
with `size=365` and the same rendering and stop convention. No new engine capability is required and
no provider-side arithmetic is involved — the granularity is a fact about the source, the splitting
is the engine's.

Two constraints established by probing:

- The clamp is anchored at `end_date`, so each chunk must carry its own `end_date` and walk
  backwards. Holding `end_date` fixed and moving `start_date` earlier changes nothing.
- **365 days is honoured; 366 is not.** A chunk size of exactly one calendar year will be clamped in
  leap years — 365 days is the safe maximum, and a smaller chunk is safer still.

Walking `end_date` backwards does reach older data: station `1117894` yielded a continuous record
from 2023-02-02 to 2026-09-06 through four consecutive yearly windows.

What remains a decision — whether to emit an issue when a request is split, and whether to surface
the source's cap to callers — is the delivery owner's, not this survey's.

Worth checking beyond this provider: no provider in `src/rivretrieve/_internal/providers/` currently
declares `capped-span` or `n-year-chunk`, and none sets `size`. Both planners are implemented and
unit-tested but unused. Whether other sources cap their windows and are similarly under-declared was
not surveyed here.

## 4. Availability basis

Availability is established per station from the graph route, not from catalogue metadata.

**Catalogue metadata cannot establish it.** The snapshot `discharge` field predicts graph discharge
at only **97.7%**: across the 825 baseline stations it is wrong for 19 — 15 stations where the
snapshot is null but the graph publishes discharge, and 4 where the snapshot carries a value but the
graph publishes none. The snapshot's `waterlevel_m` field is null for every station in both
captures, so it establishes nothing about stage at all; `waterlevel_msl` is a different quantity and
is not evidence for the graph's `value` field.

A station is recorded `available` for a product when the graph route publishes at least one non-null
value for that product's field in the tested window. It is recorded
`empty_in_tested_window` when the route answers with a complete time grid containing no non-null
value for that field.

## 5. Null and error behaviour

**HTTP status carries no availability signal.** All 825 sweep requests returned 200 with
`result: "OK"`, including stations with no data at all — the route answers with a full time grid of
nulls rather than an error or an empty array.

Recorded error behaviour (`recordings/error_*.recording.json`):

| Condition | Response |
| --- | --- |
| Nonexistent `station_id` | **HTTP 500** with a Go panic stack trace, not JSON |
| Unknown `station_type` | **HTTP 500** with a Go panic stack trace, not JSON |
| Missing `station_id` | **HTTP 200** with body `{"result":"NO","data":"422:  No station id"}` |
| `end_date` before `start_date` | **HTTP 200**, `result: "OK"`, zero rows — no error |

Two consequences for implementation: a 200 response may still carry a `result: "NO"` error body and
must be checked, and a malformed request can return a non-JSON 500 body that will fail a naive
decode.

## 6. Sparse reporting and window length

Grid cadence differs per station: over a 7-day window, 424 baseline stations returned 1,008 rows
(10-minute) and 401 returned 168 rows (hourly). Reporting is also sparse within the grid — station
`1117894` averages 13 non-null hourly observations per day against a 24-slot grid.

This makes short windows unsafe for availability claims. Of 26 stations with no values in the 7-day
window, re-probing over 90 days recovered **14**: thirteen gained thousands of stage values and one
(`700592`) gained both products. The 12 that remained empty over 90 days are a contiguous id block
(`11688546`–`11689150`).

Any future availability check should use a window of at least 90 days before recording a station as
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

- Do not send a window longer than 365 days and assume it was honoured.
- Do not treat HTTP 200 or `result: "OK"` as evidence that data exists.
- Do not treat absence from `waterlevel_load` as evidence that a station is gone or dataless.
- Do not use the snapshot `discharge` field as the availability basis; it is wrong for 19 stations.
- Do not use `waterlevel_msl` as evidence for the graph `value` field.
- Do not record a station empty on a short window; use 90 days or more.
- Do not infer a timezone, statistic, frequency or record bound, and do not derive daily means.

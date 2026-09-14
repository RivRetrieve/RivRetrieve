# Thailand (`th_thaiwater`) — measurement availability research

Research for [#224](https://github.com/RivRetrieve/RivRetrieve/issues/224). Research owner
@thiagovmdon; delivery and integration owner @CooperBigFoot.

Research only. No production adapter, canonical catalogue artifact or provenance check is modified.

Day counts in this folder are **inclusive calendar dates** (both endpoints counted; elapsed days =
dates − 1).

## Governing verification and implementation handoff (2026-09-14)

Nicolas completed the remaining source verification under Effort #225. The earlier
research capture described below is retained as dated history, not substituted for
newly acquired bytes. The governing input is
[`inventory/governing_station_product_evidence.csv`](inventory/governing_station_product_evidence.csv):
825 original station IDs and all 1,650 source-evidenced product pairs. It binds each
pair to its own graph URL, complete-body material identity, actual acquisition date,
window and existing supplying agency. Both products of a station share one acquisition.

The final account is **1,096 positive pairs and 554 selectable unknown pairs**:
stage 813 positive / 12 unknown, discharge 283 positive / 542 unknown. An all-null
window does not establish unsupported products. The observations establish these
counts in the adopted 7- or 91-date windows, not whole-history or future availability.

Complete governing bodies are held privately: 813 replacement responses acquired
September 13 and 12 reused complete null responses from September 11. The controlled
bundle is 25,582,314 bytes, SHA-256
`46320ee0fa6b908c6009f223f59d6daa94f836bdfe3bbf82fee6d4354779c73f`.
All 1,650 current counts/statuses agree with the historical derived inventory below;
the discarded earlier bytes were not recovered by that agreement. The original
adaptive short-to-long recovery anecdotes were not independently recertified.

Public CI checks the committed ledger, exact native identities/agency bindings and
deterministic metadata consistency. It does **not** verify unavailable private bodies.
Acceptance and final integration require the explicit-root offline command in
[HANDOFF.md](HANDOFF.md), which hashes and reads every complete governing response.
No automatic reacquisition or private-corpus publication is part of that command.

The accepted retrieval declaration is conservative `capped-span`, size **365 inclusive
SOURCE dates**, with engine padding before planning. Direct preserved normal and
leap-containing windows honour that size; the leap case contains only nulls and does
not prove historical observations. This is not the source's exact maximum. The original
825-ID baseline stays unchanged, including the 25 IDs absent from a later snapshot.
The additional 605 IDs are outside scope. A 365-date user request can split after the
engine adds two days to each end. No 361-date public limit is introduced.

The earlier value-stripping choices are historical packaging facts, not an approved
project-wide measurement-value policy. Existing genuine recorded-source test conventions
remain in force. Nicolas owns research acceptance and delivery; this correction does
not itself constitute merged implementation or acceptance of the entire research PR.


| | |
| --- | --- |
| Baseline commit | `67796ab8d793867aaaaf9c6fb55bec208adaeab8` |
| Native table captured | `2026-08-02T12:42:03Z` (825 stations) |
| Catalogue snapshot, window probe, recordings | `2026-09-07` |
| Availability evidence | replacement capture `2026-09-11T07:55:50Z` .. `2026-09-11T09:38:16Z`, 1,377 receipts (§3) |
| Recordings | 21: 8 kept whole, 13 stripped of observation values with their digests kept |
| Inventory | 1,650 rows = 825 stations × 2 products, none omitted, each citing its own response |
| Verification | `scripts/verify_evidence.py` — 34/34 checks pass |

## 1. Historical research headline (September 11 capture)

Users can request measurements from **1 station / 2 series** today. The graph route's published
values provide positive evidence for **1,096 pairs across the 825-station baseline**;
all 1,650 governing pairs are selectable as available or unknown after integration.

| Product | available | empty in tested window |
| --- | --- | --- |
| `stage_reported` | **813** / 825 | 12 |
| `discharge_reported` | **283** / 825 | 542 |
| **total series** | **1,096** | |

In the adopted windows, every discharge-positive station was also stage-positive.
There are zero access failures and zero uninvestigated pairs in the final inventory. Three requests
failed on first attempt and succeeded on retry (§3).

Per station, across the three combinations issue #224 asks for:

| Combination | Stations |
| --- | --- |
| stage **and** discharge | 283 |
| stage only | 530 |
| neither (complete grid, no non-null value for either product over 91 dates) | 12 |

No station had a discharge-positive/stage-empty combination in the adopted windows.

The station-by-station breakdown is in [STATION_TABLE.md](STATION_TABLE.md); the machine-readable
form is `inventory/station_product_evidence.csv`. Every number in this section is generated in
`inventory/inventory_summary.json`.

## 2. What the catalogue snapshot can and cannot establish

Issue #224 asks whether official metadata can establish availability for the whole population.

**Compared.** The `discharge` field of the `waterlevel_load` snapshot acquired
`2026-09-07T15:08:00Z` was compared with each baseline station's graph discharge status in the final
inventory. For 276 stations that status rests on 7 dates (2026-08-31 .. 2026-09-06); for 549 it rests
on 91 dates (2026-06-08 .. 2026-09-06). The graph responses were acquired 2026-09-11.
`scripts/build_metadata_comparison.py` writes the per-station classes to
`inventory/metadata_vs_graph.csv` and the counts to `inventory/metadata_vs_graph_summary.json`.

A baseline station absent from the snapshot response is counted separately from one present with a
null `discharge` field. No present station carries a blank string; "null" means JSON `null`.

| Baseline station in the snapshot | graph publishes discharge | graph publishes none | total |
| --- | --- | --- | --- |
| present, `discharge` set | 261 | 4 | 265 |
| present, `discharge` null | 18 | 517 | 535 |
| absent from the snapshot | 4 | 21 | 25 |
| **total** | **283** | **542** | **825** |

- **Among the 800 present stations**, the field agrees with the graph window for 778 (97.25%) and
  disagrees for 22. For 18 of those the field is null but the graph publishes discharge; for 4 it is
  set but the graph publishes none.
- **The 25 absent stations** are ones the snapshot says nothing about; 4 of them publish discharge on
  the graph route.
- Counting absent stations as null, as an earlier version of this comparison did, gives 22 + 4 = 26
  disagreements over all 825 baseline stations.

An earlier version of this section reported 19 disagreements (15 + 4, 97.7%). That figure came from
an earlier comparison and did not match the final inventory. The figures above are recomputed from
the final inventory, with the method stated.

**What this supports.** The snapshot records each station's latest reading at one instant. The graph
answers whether any value exists in a 7- or 91-date window ending 2026-09-06. Those are different time
questions. The comparison therefore shows that this snapshot cannot by itself establish the
window-based availability the inventory records. It is not evidence that the source's metadata is
wrong.

For stage the snapshot offers nothing to compare. `waterlevel_m` is null for all 1,405 stations in
the live snapshot and all 825 in the baseline capture. `waterlevel_msl` is populated for every station, but its snapshot presence does not
establish graph-window availability. The graph `value` field meaning comes from the
recorded official application mapping, not an inferred equivalence of metadata names.

Availability is therefore taken from the graph route per station, and `verify_evidence.py` asserts
that every `available` row cites the route rather than metadata. An early 8-station hypothesis sample
(`recordings/hypo_*`) agreed 8/8; only the population comparison shows the disagreements.

## 3. Evidence behind each result

**What was corrected.** The original survey (2026-09-07) kept derived counts and discarded every
response body. Its inventory had two linkage defects:

- 1,098 rows combined a widened count with the earlier short request's grid rows and acquisition
  instant; in 538 of them the non-null count exceeded the stated grid rows.
- Every row linked to one of two example recordings from other stations.

**Replacement capture.** `scripts/acquire_graph_evidence.py` re-requested the same explicit windows
between `2026-09-11T07:55:50Z` and `2026-09-11T09:38:16Z`. It asked all 825 baseline stations over 7
dates (2026-08-31 .. 2026-09-06), then the 549 stations with a product empty on 7 dates over 91 dates
(2026-06-08 .. 2026-09-06).

There are 1,377 receipts in `evidence/graph_receipts.csv`: 1,374 requests plus 3 retries.

- Station `1109499` first answered HTTP 200 with
  `{"result":"NO","data":"500:  Internal Database Error ...pq: out of shared memory"}`.
- Stations `1109525` and `1117431` timed out after 300 s.
- Each retry returned a full grid. The failed attempts remain in the receipt table.

These are new responses, identified by their own acquisition instants. They are not the original
survey's answers, whose counts remain in git history at `e5c8907`.

**Linkage.** Every inventory row cites one receipt by `request_id` and copies that receipt's window,
grid rows, non-null count, HTTP status, media type, acquisition instant, byte size and SHA-256. Both
products of a station cite the same response, which serves both and is receipted once.

**Result.** The replacement reproduces the original survey's counts exactly: identical grid rows and
non-null counts for all 825 7-date and all 549 91-date requests, and identical status and non-null
count for all 1,650 inventory rows. What changed is linkage. 1,098 rows now report the grid rows of
the 91-date response they rest on. Station `1` stage, for example, is now 13,069 non-null values in
13,104 rows over 91 dates; it was previously shown against the 1,008 rows of a 7-date request. No row
reports more non-null values than grid rows.

**Historical retention.** This research revision discarded observation-bearing bodies.
This records what happened, not a rule forbidding genuine recorded test inputs.

- **Every response keeps:** request URL, HTTP status, media type, UTC acquisition instant, byte size
  and SHA-256 of the full response, plus counts and grid endpoints.
- **Kept whole:** the 39 responses carrying no observation value, in
  `evidence/graph_bodies_without_observations.zip` (129,554 B). They are the all-null grids and error
  bodies.
- **Not kept:** the 1,336 responses carrying observations, 500,847,708 B in total (25,874,399 B
  gzip-6). Their digests cannot be recomputed from this repository. See
  [UNRESOLVED.md](UNRESOLVED.md) §7.

**Window length.** A station with no values in a short window may simply report rarely. Of 26
stations empty for both products on 7 dates, 14 published a value on 91 dates. Across all re-probed
stations, 14 gained stage and 7 gained discharge on 91 dates. Every empty row rests on the 91-date
response, which `verify_evidence.py` asserts.

Grid cadence differs per station: over 7 dates, 424 baseline stations returned 144 rows per date
(10-minute) and 401 returned 24 (hourly).

## 4. The route publishes a full grid of nulls rather than an error

All 825 7-date requests and 546 of the 549 first 91-date attempts returned HTTP 200 with
`result: "OK"`, including stations with no data at all. The route answers a silent station with a
complete time grid of null values, so neither the status code nor the response shape carries an
availability signal.

Recorded error behaviour (`recordings/error_*.recording.json`, and one receipted body in the
evidence bundle):

| Condition | Response |
| --- | --- |
| Nonexistent `station_id` | HTTP **500**, Go panic stack trace, not JSON |
| Unknown `station_type` | HTTP **500**, Go panic stack trace, not JSON |
| Missing `station_id` | HTTP **200**, body `{"result":"NO","data":"422:  No station id"}` |
| `end_date` before `start_date` | HTTP **200**, `result: "OK"`, zero rows |
| Source database error (station `1109499`, 2026-09-11; retry succeeded) | HTTP **200**, body `{"result":"NO","data":"500:  Internal Database Error ...pq: out of shared memory"}` |

## 5. The source silently shortens long requests

The port notes state that no publisher cap is claimed. This survey recorded one for station
`1373273` on 2026-09-07 (`inventory/window_limit_probe.csv`; day counts derived from its dates in
`inventory/window_limit_readings.csv`). Every request ends on 2026-09-06:

| Requested | Dates | Returned | Dates | Rows |
| --- | --- | --- | --- | --- |
| 2026-08-31 .. 2026-09-06 | 7 | as requested | 7 | 1,008 |
| 2026-06-08 .. 2026-09-06 | 91 | as requested | 91 | 13,104 |
| 2025-09-08 .. 2026-09-06 | 364 | as requested | 364 | 52,416 |
| 2025-09-07 .. 2026-09-06 | 365 | as requested | 365 | 52,560 |
| 2025-09-06 .. 2026-09-06 | 366 | as requested | 366 | 52,704 |
| 2025-06-06 .. 2026-09-06 | 458 | 2025-09-06 .. 2026-09-06 | 366 | 52,704 |
| 2023-09-06 .. 2026-09-06 | 1,097 | 2025-09-06 .. 2026-09-06 | 366 | 52,704 |

Every response is HTTP 200 with `result: "OK"`, and nothing in a shortened response indicates that it
was shortened. An earlier version of this section said the 366-date request was clamped. It was not:
2025-09-06 .. 2026-09-06 came back exactly as requested.

**Demonstrated:** requests of up to 366 dates ending 2026-09-06 are honoured, and both longer requests
are returned from 2025-09-06.

**Historical probe limitation: the exact rule was not established.** 2025-09-06 is both `end_date` minus 365 elapsed days and
`end_date` minus one calendar year, so these endpoints cannot tell the two apart. That historical comparison contained no 29 February, and requests of 367–457 dates
were not tested. A subsequent complete null-grid capture for 2023-03-03 .. 2024-03-01
honoured 365 inclusive dates including 29 February, without resolving the maximum. No conclusion about leap years
or calendar-year chunks follows from this evidence. See [UNRESOLVED.md](UNRESOLVED.md) §1.

**Measured at the public surface** (`inventory/window_truncation_observation.json`; the historical acquisition script
`scripts/reproduce_window_truncation.py` is now retired): `rr.fetch(..., start="2023-01-01", end="2026-09-06")` — 1,345
dates — returned rows from 2025-09-08 00:00 through 2026-09-06 23:50: 364 dates, **27% of the requested
period**, with no issue or warning naming the shortfall. The two issues emitted are unrelated
provenance notices. That file's `requested_days` and `returned_days` fields are elapsed days (1,344
and 363). The historical artifact did not record the adapter request. The retained follow-up
`effective_public_long` captured the actual padded source bounds 2022-12-30 .. 2026-09-08.
The response begins 2025-09-08; final clipping to the user end gives 52,416 rows per
product through 2026-09-06. The direct probe instead used source end 2026-09-06.
These are not the same source request end, so the two-day difference is explained by
padding and clipping, not evidence of an unstable source floor.

The original survey reported walking `end_date` backwards a year at a time to retrieve a continuous
2023-02-02 .. 2026-09-06 record for station `1117894`. No recording or table of that walk is
committed, so this folder does not evidence it. `HANDOFF.md` §3 records what a fix must respect; the
design decision is the delivery owner's.

## 6. Population churn

`waterlevel_load` returned 825 stations on 2026-08-02 and **1,405** on 2026-09-07: 605 present now
that were not in the baseline, 25 baseline stations not present today.

The difference is upstream, not ours — `generate_catalogue.py` applies no row filter and fails the
build rather than dropping rows. But absence from a snapshot is not absence of a station: three of
the 25 were probed on the graph route and all three answer `result: "OK"`, one still publishing
values. Every live row carries telemetry from the preceding week, consistent with the endpoint
returning currently reporting stations rather than a stable registry.

Every changed id is enumerated in `inventory/population_churn.csv` — 605 rows marked
`added_since_baseline` with the identity the source publishes for each, and 25 marked
`absent_from_latest_snapshot` with the identity the committed baseline holds. The reconciliation
closes arithmetically: 825 − 25 + 605 = 1,405. The committed list is shown as changed, never
silently replaced.

The existing port notes already record comparable churn ("87 new IDs are present and 16 legacy IDs
are absent"), so this is a continuing property of the source. This survey scopes its inventory to the
committed 825-station baseline, as #224 does; the 605 additional stations are not surveyed and not
merged. See [UNRESOLVED.md](UNRESOLVED.md) §2.

## 7. Supplying agencies and platform

Already established in the committed provenance and confirmed here: four issuing agencies —
Electricity Generating Authority of Thailand, Hydro–Informatics Institute, Royal Irrigation
Department, and Friend in Need (of "Pa") Volunteers Foundation — with HII additionally operating the
ThaiWater API platform. `origins.py` binds every station to its agency and fails the build when
`agency.id` and `station.agency_id` disagree.

The verified per-station supplying-agency bindings remain distinct from HII platform
operation. These bindings do not establish every original measurement producer or
historical sensor operator; no new upstream-producer inquiry is a prerequisite. The live platform
lists ten agencies; the baseline draws on four.

## 8. Time semantics

Unchanged and deliberately not extended. `graph_data[].datetime` is naive wall clock with no offset
or zone field; no captured source establishes a zone, so `time_zone` stays `unknown` and Asia/Bangkok
is not inferred. Temporal support, statistic, frequency, period type and period anchor remain
`unknown`. No daily means are derived.

## 9. Relation to the withheld facts

The packaged `provenance.json` withholds **1,648 fact groups**, every one
`station_product:{id}:{product}:availability` with reason `no_acquisition_record_established`.
Station identities are not withheld — consistent with #224's framing that this is principally a
measurement-availability gap.

The governing ledger now supplies an actual complete-body acquisition for every pair.
Its 554 null-only results remain unknown availability, not acquisition withholding.
The older receipt-only inputs in §3 are not the admission basis. Catalogue/provenance
changes must bind the exact final acquisition before removing the 1,648 withholdings;
that implementation belongs to Nicolas.

## 10. Contents

| Path | What it is |
| --- | --- |
| [`FINDINGS.md`](FINDINGS.md) | This document |
| [`STATION_TABLE.md`](STATION_TABLE.md) | The station list: one row per station with per-product status and window |
| [`HANDOFF.md`](HANDOFF.md) | Route, window limit, fields, units, availability basis, error behaviour |
| [`UNRESOLVED.md`](UNRESOLVED.md) | Unresolved cases and the decisions required |
| [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md) | The evidence package and every recording, with integrity fields |
| `evidence/` | Receipts for every graph request; whole bodies of responses carrying no observation |
| `inventory/` | The 1,650-row inventory, generated summaries, comparison, churn and window-limit tables |
| `recordings/` | 21 recordings in the repository's recording convention |
| `scripts/` | Acquisition, composition and verification scripts |

## 11. Checks run

```
uv run python research/station-coverage/th_thaiwater/scripts/verify_evidence.py
```

The historical revision reported **34/34**, offline. Its limits and current checks are
separate from mandatory full governing-body verification. The historical checks covered:

- **Recordings:** fields, digests and sizes.
- **Historical retention:** exact bytes are checked only for retained historical bodies.
- **Receipts:** unique ids; each URL names its own station and window; no count exceeds grid rows;
  every grid spans exactly its requested dates at 24 or 144 rows per date.
- **Retained bodies:** all 39 reproduce digest, size and every derived reading; every response
  carrying no observation is retained.
- **Inventory completeness.**
- **Linkage:** every row cites a receipt for its own station and copies it exactly.
- **Statuses:** every status reproduces from its receipt; both products share one response; empty
  rows rest on 91 dates.
- **Churn:** it reconciles.
- **Snapshot state:** per row, with absent kept distinct from null.
- **Reproduction:** the metadata comparison reproduces from the final inventory, and the
  window-limit readings reproduce from the recorded probe.

The unapproved blanket measurement-value scanner was removed. Genuine recorded-source
tests remain valid. The new governing verifier checks actual complete bodies rather
than comparing two derived assertions.

**Access etiquette:** all requests were unauthenticated GET against public routes with a descriptive
User-Agent and 0.35 s spacing. Response bodies carrying observations were read in memory to derive
counts and never written to disk. No observation history beyond the stated windows was downloaded.
No credentials, cookies or tokens were sent or stored.

# Thailand (`th_thaiwater`) — measurement availability research

Research for [#224](https://github.com/RivRetrieve/RivRetrieve/issues/224). Research owner
@thiagovmdon; delivery and integration owner @CooperBigFoot.

Research only. No production adapter, canonical catalogue artifact or provenance check is modified.

| | |
| --- | --- |
| Baseline commit | `67796ab8d793867aaaaf9c6fb55bec208adaeab8` |
| Native table captured | `2026-08-02T12:42:03Z` (825 stations) |
| This survey captured | `2026-09-07` |
| Recordings | 21, all hash-verified |
| Inventory | 1,650 rows = 825 stations × 2 products, none omitted |
| Verification | `scripts/verify_evidence.py` — 13/13 checks pass |

## 1. Headline

Users can request measurements from **1 station / 2 series** today. The graph route's published
values establish **1,096 series across the 825-station baseline**.

| Product | available | empty in tested window |
| --- | --- | --- |
| `stage_reported` | **813** / 825 | 12 |
| `discharge_reported` | **283** / 825 | 542 |
| **total series** | **1,096** | |

Discharge is a strict subset of stage: no station publishes discharge without also publishing stage.
Zero access failures and zero uninvestigated pairs.

Per station, across the three combinations issue #224 asks for:

| Combination | Stations |
| --- | --- |
| stage **and** discharge | 283 |
| stage only | 530 |
| neither (complete grid, no non-null value for either product over 90 days) | 12 |

No station publishes discharge alone.

The station-by-station breakdown is in [STATION_TABLE.md](STATION_TABLE.md); the machine-readable
form is `inventory/station_product_evidence.csv`.

## 2. Catalogue metadata cannot establish availability

Issue #224 asks whether official metadata can answer this for the whole population. It cannot, and
relying on it would produce wrong answers for 19 stations.

The `waterlevel_load` snapshot carries a `discharge` field. Compared against what the graph route
actually publishes across all 825 baseline stations, it agrees only **97.7%** of the time:

- **15 stations** where the snapshot field is null but the graph route publishes discharge — these
  would have been wrongly excluded.
- **4 stations** where the snapshot carries a value but the graph route publishes none — these would
  have been wrongly included.

For stage the metadata is not merely imprecise but empty: `waterlevel_m` is **null for all 825
stations** in both the baseline and the live capture. `waterlevel_msl` is populated for every
station, but it is a different quantity (mean sea level datum) and is not evidence for the graph's
`value` field.

Availability is therefore taken from the graph route per station, and `verify_evidence.py` asserts
that every `available` row cites the route rather than metadata.

An early 8-station sample agreed 8/8, which would have looked like confirmation. The full sweep is
what exposed the 19 disagreements.

## 3. Window length changes the answer

A station with no values in a short window may simply report rarely, so a negative claim is only as
strong as the window behind it.

The first pass used a 7-day window and found 26 stations with no values for either product. Widening
to 90 days recovered **14 of those 26** — thirteen gained thousands of stage values, one gained both
products.

That recovery rate exposed a hole in the method: stations empty for *discharge only* had not been
re-probed. All 549 stations with at least one empty product were then re-probed over 90 days,
recovering **7 further discharge stations**. Every negative claim in the inventory now rests on the
90-day window, which `verify_evidence.py` asserts.

Reporting is genuinely sparse: cadence is 10-minute for 424 baseline stations and hourly for 401, and
even reporting stations leave gaps — station `1117894` averages 13 non-null hourly observations
against a 24-slot day.

## 4. The route publishes a full grid of nulls rather than an error

All 825 sweep requests returned HTTP 200 with `result: "OK"`, including stations with no data at all.
The route answers an unknown or silent station with a complete time grid of null values, so neither
the status code nor the response shape carries an availability signal.

Recorded error behaviour (`recordings/error_*.recording.json`):

| Condition | Response |
| --- | --- |
| Nonexistent `station_id` | HTTP **500**, Go panic stack trace, not JSON |
| Unknown `station_type` | HTTP **500**, Go panic stack trace, not JSON |
| Missing `station_id` | HTTP **200**, body `{"result":"NO","data":"422:  No station id"}` |
| `end_date` before `start_date` | HTTP **200**, `result: "OK"`, zero rows |

## 5. The source silently caps windows at 365 days

The port notes state that no publisher cap is claimed. This survey establishes one
(`inventory/window_limit_probe.csv`): `start_date` is clamped to `end_date` minus 365 days. Requests
of 7, 90, 364 and 365 days are honoured exactly; 366 days, 15 months and 3 years all return the
identical one-year span — with HTTP 200, `result: "OK"`, and nothing in the response indicating a
clamp.

**Measured at the public surface** (`inventory/window_truncation_observation.json`, reproducible via
`scripts/reproduce_window_truncation.py`): a request for `2023-01-01 .. 2026-09-06` returns
2025-09-08 .. 2026-09-06 — **27% of the requested period** — with no issue or warning naming the
shortfall. The two issues emitted are unrelated provenance notices.

The data is reachable: walking `end_date` backwards a year at a time retrieved a continuous
2023-02-02 .. 2026-09-06 record for station `1117894`. `HANDOFF.md` §3 records the two constraints a
fix must satisfy; the design decision is the delivery owner's.

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

## 7. Producer

Already established in the committed provenance and confirmed here: four issuing agencies —
Electricity Generating Authority of Thailand, Hydro–Informatics Institute, Royal Irrigation
Department, and Friend in Need (of "Pa") Volunteers Foundation — with HII additionally operating the
ThaiWater API platform. `origins.py` binds every station to its agency and fails the build when
`agency.id` and `station.agency_id` disagree.

The producer/operator distinction needs no further research for this provider. The live platform
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

This survey supplies recorded acquisitions covering per-station-per-product availability across the
whole baseline, which is the evidence those 1,648 groups were waiting on. Converting them into
catalogue rows is implementation work and belongs to the delivery owner.

## 10. Contents

| Path | What it is |
| --- | --- |
| [`FINDINGS.md`](FINDINGS.md) | This document |
| [`STATION_TABLE.md`](STATION_TABLE.md) | The station list: one row per station with per-product status |
| [`HANDOFF.md`](HANDOFF.md) | Route, window limit, fields, units, availability basis, error behaviour |
| [`UNRESOLVED.md`](UNRESOLVED.md) | Unresolved cases and the decisions required |
| [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md) | Every recording with integrity fields and what it establishes |
| `inventory/station_product_evidence.csv` | The 1,650-row inventory |
| `recordings/` | 21 recordings in the repository's existing convention |
| `scripts/` | Acquisition, composition and verification scripts |

## 11. Checks run

```
uv run python research/station-coverage/th_thaiwater/scripts/verify_evidence.py
```

**13/13 pass**, offline: recording hash integrity (21/21); required recording fields; no
credential-like request parameters; inventory 1,650 rows = 825 × 2; all 825 baseline stations
accounted for; no duplicate pairs; statuses within the declared vocabulary; no `unsupported` claim;
HTTP 200 not treated as availability; all 1,096 available rows citing at least one non-null
observation; all 554 empty rows citing zero; all 554 empty rows resting on the 90-day window; every
available row citing the graph route rather than catalogue metadata.

`uv run ruff format`, `uv run ruff check`, `uv run ty check` clean.

**Access etiquette:** all requests were unauthenticated GET against public routes with a descriptive
User-Agent and 0.35 s spacing. Only derived counts were retained from the sweeps — response bodies
were not accumulated, so no observation history was downloaded merely to establish support.
Representative responses are recorded separately. No credentials, cookies or tokens were sent or
stored.

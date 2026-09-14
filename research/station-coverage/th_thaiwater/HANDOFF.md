# th_thaiwater implementation handoff

For the implementing agent. Current admission uses the complete privately verified
acquisitions in `inventory/governing_station_product_evidence.csv`. The older research
recordings/receipts remain dated history; discarded bodies are not certified by their
derived counts. See the verification commands below.

Baseline commit `67796ab8d793867aaaaf9c6fb55bec208adaeab8` · native table captured
`2026-08-02T12:42:03Z` (825 stations) · catalogue snapshot, window probe and recordings `2026-09-07` ·
availability evidence re-acquired `2026-09-11` (FINDINGS §3). Day counts are inclusive calendar
dates (both endpoints counted; elapsed days = dates − 1).

## 1. Identity and population

`station.id` is the identity, as the existing port notes already require; `station.tele_station_oldcode`
is never identity. Ids are unique with no nulls across the population.

The `waterlevel_load` snapshot population changed between captures. Every row in the
later capture carries telemetry from the preceding week; this does not establish an
exhaustive rule for how the publisher chooses snapshot membership. Station
counts therefore move: 825 at the 2026-08-02 baseline capture, 1,405 on 2026-09-07. Absence from a
snapshot does not mean a station is gone; see §6.

## 2. Route

```
GET https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_graph
    ?station_type=tele_waterlevel&station_id=<station.id>&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
```

One response publishes **both** products: `data.graph_data[]` rows carry `datetime`, `value`
(stage) and `discharge`. The provider fetch stage can coalesce two fields when called for both products. The
current public driver calls each product separately, so public requests make one call
per product/sub-window. Keep that driver behavior; do not expand coalescing scope.

Access requires no credentials. No pagination was observed in these captured routes: each graph capture is a single
array, and each metadata snapshot is one body. This is not an exhaustive source API claim.

## 3. Source-window handling: settled implementation contract

Use existing engine-owned `capped-span` with `size=365`, DATE rendering and inclusive
stop. This is a conservative working size per **SOURCE request**, not an exact maximum.
The engine widens the user's window by two days at each end before planning; a
365-date user request therefore needs two source requests. Do not add a 361-date
public restriction, provider padding or date arithmetic. Each sub-window carries its
own start and end. Backwards traversal is not required.

The historical seven-request comparison remains in FINDINGS §5. Its 366-inclusive-date
request was honoured, not clamped. Subsequent complete private captures directly
honoured 365 dates for both 2025-09-09 .. 2026-09-08 and leap-containing
2023-03-03 .. 2024-03-01. The latter is a full null grid, evidence of honoured bounds,
not evidence of historical measurements or a universal leap-year source rule.

The earlier public request 2023-01-01 .. 2026-09-06 was padded to actual source bounds
2022-12-30 .. 2026-09-08. Its complete source response begins 2025-09-08; clipping to
the user end produces 52,416 ten-minute grid rows per product through 2026-09-06.
The direct probe used source end 2026-09-06 instead. The two-day difference is explained
by padding and clipping, not an unstable source floor. Correct D11 accordingly.

A successful unsplit capped response can cause accumulated-cache coverage to record an
interval that was not actually requested in full. Test the corrected real public bypass,
reuse/remainder and refresh paths with exact request-resolving recordings, not only
planner arithmetic. No publisher record bound is inferred from a returned envelope.

The unrecorded station 1117894 multi-year walk is not accepted history evidence. No new
maximum survey or repeat-floor probe is required. A new independent boundary expectation
must be authored from source bytes by someone without access to the port or its output.

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
and all 825 baseline stations. The differently named `waterlevel_msl` snapshot field does not establish graph-window
availability; official application evidence establishes the graph `value` field meaning.

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

These final null-only conclusions refer to their actual adopted 91-date windows. They
do not establish a minimum-window policy for future retrieval or make shorter empty
results invalid. Every null-only conclusion remains selectable unknown availability.

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

## 8. Supplying agencies and platform

The existing verified per-station supplying-agency bindings identify four issuing agencies
— Electricity Generating Authority of Thailand, Hydro–Informatics Institute, Royal Irrigation
Department, and Friend in Need (of "Pa") Volunteers Foundation — with HII additionally operating the
ThaiWater API platform. `origins.py` binds every station to its agency and fails the build when
`agency.id` and `station.agency_id` disagree, with HII platform operation kept separate. These facts do not establish every original
measurement producer or historical sensor operator. Disclose that limit without
restarting an upstream-producer inquiry.

The live platform lists ten agencies; the baseline population draws on four of them.

## 9. Things that must not be done

- Do not send more than 365 inclusive source dates per request under the accepted
  conservative declaration. This does not claim 365 is the source maximum.
- Do not treat HTTP 200 or `result: "OK"` as evidence that data exists.
- Do not treat absence from `waterlevel_load` as evidence that a station is gone or dataless.
- Do not use the snapshot `discharge` field as the availability basis. It disagrees with the graph
  window for 22 of the 800 baseline stations present in the snapshot, and it says nothing about the
  25 that are absent.
- Do not use `waterlevel_msl` as evidence for the graph `value` field.
- Describe an empty response only over its actual tested window; do not turn the
  adopted 91-date research windows into a public retrieval restriction.
- Do not infer a timezone, statistic, frequency or record bound, and do not derive daily means.

## 10. Governing acquisitions and portable verification

`inventory/governing_station_product_evidence.csv` accounts for the exact 825 baseline
IDs and 1650 pairs:1096 positive and 554 unknown. Each row carries its own actual
September 11 or September 13 acquisition, source URL, tested bounds, complete-body hash
and byte count, and supplying-agency ID. Do not copy the old September 11 inventory's
dates onto the newer captures. Both product facts share their station's one body.

Keep the complete corpus private. Production admission can use the existing
`AcquisitionRecord.material` filename/byte_count/sha256 plus exact requested_from and
retrieval instant, with no fabricated public recording URI. Public HII field/unit
and terms documentation continues using genuine repository-relative EvidenceReferences.
The full corpus is not required in wheels and must not be added to source distributions.

Public repository check (metadata consistency only):

```
uv run python research/station-coverage/th_thaiwater/scripts/verify_evidence.py
```

Required at research acceptance and final integration, with the controlled
`baseline-capture-2026-09-13` directory supplied explicitly:

```
uv run python research/station-coverage/th_thaiwater/scripts/verify_governing_evidence.py \
  --ledger research/station-coverage/th_thaiwater/inventory/governing_station_product_evidence.csv \
  --native src/rivretrieve/_internal/providers/th_thaiwater/catalogue/native.parquet \
  --evidence-root "$THAIWATER_EVIDENCE_ROOT"
```

The command reads each exact body/receipt once, checks all graph timestamps and both
native numeric-or-null fields, and derives every count. It fails if input is absent,
changed or inconsistent. It performs no network requests and writes nothing. Public
CI cannot claim this private-body certification. The retained discovery verifier that
rewrites bundles must not be run against the governing corpus in place.

The two historical count stores could formerly be forged together while all 34 checks
passed. A regression reproduces that path. A separate test forges positive availability
against an unchanged genuine null-response body and requires rejection. The corrected
metadata checks are still not a substitute for this required full-body acceptance pass.

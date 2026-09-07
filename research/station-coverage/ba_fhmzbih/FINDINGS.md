# Bosnia (`ba_fhmzbih`) — station and measurement coverage research

Research for [#223](https://github.com/RivRetrieve/RivRetrieve/issues/223). Research owner
@thiagovmdon; delivery and integration owner @CooperBigFoot.

This is research only. No production adapter, canonical catalogue artifact or provenance check is
modified by this PR.

| | |
| --- | --- |
| Baseline commit | `67796ab8d793867aaaaf9c6fb55bec208adaeab8` |
| Native table captured | `2026-08-02T12:42:03Z` (60 rows) |
| This survey captured | `2026-09-07` |
| Recordings | 21, all hash-verified |
| Inventory | 297 rows = 99 stations × 3 products, none omitted |
| Verification | `scripts/verify_evidence.py` — 14/14 checks pass |

## 1. Headline

Today the provider exposes **2 stations and 3 series**. The publisher's own statements establish
**208 retrievable series across 99 stations**, of which **132 series across the committed 60-station
baseline**.

| Population | Q | H | WT | series |
| --- | --- | --- | --- | --- |
| Committed baseline (60 stations) | 60 | 60 | 12 | **132** |
| Additional published stations (39) | 36 | 36 | 4 | **76** |
| **Total (99 stations)** | **96** | **96** | **16** | **208** |
| *Currently public* | *1* | *1* | *1* | *3* |

The station-by-station breakdown is in [STATION_TABLE.md](STATION_TABLE.md); the machine-readable
form is `inventory/station_product_evidence.csv`.

## 2. Why the baseline is 60, and what that omitted

`native.parquet` is byte-for-byte the membership of **layer 20**, the publisher's *Proticaj*
(discharge) display layer. The port notes confirm the mechanism: "Each request fetches
`layers/20/index.json` once."

The publisher's layer manifest (`layers/index.json`) declares ten layers. RivRetrieve's three
products correspond to three of them:

| Product | Layer | Label | Stations |
| --- | --- | --- | --- |
| `discharge_reported` | 20 | Proticaj | 60 |
| `stage_reported` | 10 | Vodostaj | 99 |
| `water_temperature_reported` | 30 | Temperatura vode | 13 |

The union is **99 stations**, all carrying object type `General;Hidrološka stanica` — the same type
as the committed 60. Taking only layer 20 therefore excluded 39 river gauges of the identical kind.

**Layer 20 is not "the stations that have discharge."** Of the 39 excluded stations, **36 have
populated discharge workbooks** — data for a product RivRetrieve already supports, on the Sava, Una,
Bosna, Miljacka and Lašva.

This survey does not merge those 39 into the baseline. Every inventory row carries `in_baseline`.
The scope decision belongs to the delivery owner — see [UNRESOLVED.md](UNRESOLVED.md) §3.

## 3. Reconciling the 230-object station document

The committed CRS evidence document holds 230 objects, against a 60-station baseline. The
difference is fully accounted for:

- **99** are hydrological stations across layers 10/20/30 (97 of them appear in the document).
- **133** document objects are not in those three layers: groundwater stations
  (`General;Stanica podzemnih voda`, layers 40/50), meteorological stations
  (`General;Meteorološka stanica`, layers 60/70), and the EPP "ekološki prihvatljiv protok" series
  (layers 80/90).
- **2** hydrological stations (`4228`, `9025`) are absent from the document; both also return 404
  for every workbook. See [UNRESOLVED.md](UNRESOLVED.md) §4.

No document object is treated as a missing station without evidence that it is one.

## 4. Population reconciliation against the baseline

All 60 baseline stations were present in the live layer-20 document on 2026-09-07. **Zero
additions, zero removals** since the 2026-08-02 capture. Station ids are unique with no nulls; one
is non-numeric (`2101-B`) and must stay a string.

## 5. How availability was established

Availability is taken from the publisher's own **`#Rows`** header field in each workbook — a
published statement, not an inference. Two things had to be ruled out first, and both would have
produced a wrong answer:

**HTTP status is not availability.** All 297 probed pairs returned 200 except 7 genuine 404s. Empty
and populated workbooks are indistinguishable by status code.

**Layer membership is not availability.** Station `4110` is absent from layer 30 yet its WT workbook
declares 2,002 rows. Layers reflect current live telemetry; the workbooks are a one-year rolling
archive, and the archive is broader. Classifying by layer would have wrongly excluded `1020` and
`4110` — one of which is a station the provider already publishes.

**Content-Length is not availability either.** An earlier pass classified by file size against a
boundary-verified threshold. Reading `#Rows` for all 297 pairs showed that heuristic
**misclassifying 7 workbooks** — stations `1110`, `4023`, `4911`, `9001`, `9020`, `9043` and `9130`
hold between 1 and 338 real observations in files small enough to look empty. Each of those seven
workbooks is recorded (`recordings/lowrow_*.recording.json`) so the correction is checkable. The
size heuristic was discarded; `Content-Length` is retained in the inventory as a recorded
observation only.

## 6. The distinction this survey holds

An empty workbook declares `#Rows = 0` **while still declaring the station's parameter name and
unit**. That is the publisher saying "no observations in the rolling year", not "this station cannot
measure this". The inventory has no `unsupported` status, because no recorded evidence supports that
claim about any station.

| Status | Rows | Meaning |
| --- | --- | --- |
| `available` | 208 | publisher declares `#Rows > 0` |
| `declared_empty_in_rolling_window` | 82 | publisher declares `#Rows = 0`, parameter and unit still declared |
| `access_failed` | 7 | HTTP 404 — route serves nothing; **not** evidence of absence |
| `uninvestigated` | 0 | — |

## 7. Temporal horizon

Two workbook periods exist and no others: `_1M` (one month) and `_1Y` (one year, span
2025-09-07 → 2026-09-06). `_1D`, `_1W`, `_3M`, `_6M`, `_2Y`, `_5Y`, `_10Y`, `_ALL`, `_COMPLETE` and
`_HIST` all return 404, as do `.csv`, `.json` and `.zip` variants. Directory listing is refused with
403; it was recorded, not bypassed.

**Historical requests beyond one year cannot be fulfilled through this route.** An empty result for
an older window is a horizon limit, never evidence that a station lacks data.

## 8. Units and time semantics

The publisher states units in every workbook header, and they match the committed `config.py`
exactly: `m³/s` (Q, 97 workbooks), `cm` (H, 97), `°C` (WT, 96).

`#Timeseries Name` is `81 Web Kontinuirani` at every station and product. It names a timeseries
without stating statistic, frequency, period type or period anchor — these stay `unknown`.
Workbook timestamps are naive with no zone marker, so `zone` stays `unknown`. Nothing here is
inferred; see [UNRESOLVED.md](UNRESOLVED.md) §5.

## 9. Producer

The portal is operated by **Agencija za vodno području rijeke Save** — the portal root's title is
that name, and the host is a subdomain of the agency's own `voda.ba`. The committed `origins.py`
issuer is therefore correct, and the provider id `ba_fhmzbih` (Federalni hidrometeorološki zavod
BiH) does not match any publisher evidence found.

Whether that agency *produces* the observations or republishes them is **not established**. The
`BODY_RESPONSIBLE` field is empty for 59 of the 60 baseline stations, and only 8 stations carry a
jurisdiction statement (`JP Spreča d.d. Tuzla`). See [UNRESOLVED.md](UNRESOLVED.md) §1 and §2.

## 10. Relation to the withheld facts

The packaged `catalogue/provenance.json` carries **293 withheld fact groups**, every one with reason
`no_acquisition_record_established`: 58 withheld station identities, 58 withheld observation facts
and 177 withheld candidate availability facts. Its single source record names issuer *Agencija za
vodno području rijeke Save* with operator *vodostaji.voda.ba*, which this survey's portal evidence
corroborates.

Those facts were withheld for want of an acquisition record, not because the source denies them.
This survey supplies recorded acquisitions covering station identity, the retrieval route and
per-station-per-product availability across the whole published population, which is the evidence
those withheld groups were waiting on. Converting them into catalogue rows is implementation work
and belongs to the delivery owner.

## 11. Contents

| Path | What it is |
| --- | --- |
| [`FINDINGS.md`](FINDINGS.md) | This document |
| [`STATION_TABLE.md`](STATION_TABLE.md) | The station list: one row per station with per-product status |
| [`HANDOFF.md`](HANDOFF.md) | Implementation handoff: routes, fields, units, availability basis, limits |
| [`UNRESOLVED.md`](UNRESOLVED.md) | Unresolved cases and the decisions required from the delivery owner |
| [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md) | Every recording, its integrity fields, and the finding it supports |
| `inventory/station_product_evidence.csv` | The 297-row inventory |
| `recordings/` | 21 recordings in the repository's existing convention |
| `scripts/` | Acquisition, composition and verification scripts |

## 12. Checks run

```
uv run python research/station-coverage/ba_fhmzbih/scripts/verify_evidence.py
```

14/14 checks pass: recording hash integrity (21/21), required recording fields, no credential-like
URL parameters, inventory completeness (297 = 99 × 3), no duplicate pairs, all 60 baseline stations
accounted for, `in_baseline` reproduces the baseline exactly, statuses within the declared
vocabulary, no `unsupported` claim, all cited recordings present on disk, HTTP 200 not treated as
availability, all 82 empty rows citing `#Rows = 0`, all 208 available rows citing `#Rows > 0`, all 7
access failures citing a real HTTP failure.

Access etiquette: all requests were unauthenticated GET/HEAD against public routes at ~4 requests
per second with a descriptive User-Agent. HEAD was used for population probing so that observation
history was not downloaded merely to establish that a route exists. The one refused route (403
directory listing) was recorded and not circumvented.

# Bosnia (`ba_fhmzbih`) — station and measurement coverage research

Research for [#223](https://github.com/RivRetrieve/RivRetrieve/issues/223). Research owner
@thiagovmdon; delivery and integration owner @CooperBigFoot.

This is research only. No production adapter, canonical catalogue artifact or provenance check is
modified by this PR.

| | |
| --- | --- |
| Baseline commit | `67796ab8d793867aaaaf9c6fb55bec208adaeab8` |
| Native table revision | `f805d2556a72617644f9bf90de2e3438e743b888` |
| Native table captured | `2026-08-02T12:42:03Z` (60 rows) |
| This survey captured | `2026-09-09` |
| Evidence | 28 response-shape examples + 361 per-pair and per-attempt files |
| Inventory | 297 rows = 99 stations × 3 products, none omitted |
| Verification | `scripts/verify_evidence.py` — 25/25 checks pass |

## 1. Headline

Today the provider exposes **2 stations and 3 series**. This survey establishes **173 series
carrying measurements across 99 stations**, of which **132 across the committed 60-station
baseline**.

| Population | Q | H | WT | series |
| --- | --- | --- | --- | --- |
| Committed baseline (60 stations) | 60 | 60 | 12 | **132** |
| Additional published stations (39) | 2 | 36 | 3 | **41** |
| **Total (99 stations)** | **62** | **96** | **15** | **173** |
| *Currently public* | *1* | *1* | *1* | *3* |

The station-by-station breakdown is in [STATION_TABLE.md](STATION_TABLE.md); the machine-readable
form is `inventory/station_product_evidence.csv`.

### Correction to an earlier revision of this survey

An earlier revision reported **208** series. It classified a station × product as available
whenever the workbook header declared `#Rows > 0`. That header counts *timestamped rows*, and 35
of those pairs are rows whose measurement cell is published empty — timestamps with no values.
Reading the measurement cells rather than the header removes them.

Two consequences matter more than the headline number:

- **The committed baseline is unaffected.** All 132 baseline series carry real measurements. Every
  one of the 35 blank-only pairs lies outside the baseline.
- **The case for extending the population collapses.** The earlier revision argued for adding the
  39 extra stations because 36 of them had "populated discharge workbooks". In fact **34 of those
  36 carry no discharge values at all** — only `1030` (HS Orašje) and `4230` (HS Obre) do. See
  [UNRESOLVED.md](UNRESOLVED.md) §3.

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

The union is **99 stations**. Layer 20 is not "the stations that have discharge": 39 stations
outside it are declared in the stage layer, and two of them do serve discharge measurements.

This survey does not merge those 39 into the baseline. Every inventory row carries `in_baseline`.
The scope decision belongs to the delivery owner — see [UNRESOLVED.md](UNRESOLVED.md) §3.

**Object type does not separate this population from the rest of the portal.** Layers 80 and 90
(`EPPVodostaj`, `EPPProticaj`) carry 81 further stations of the identical object type
`General;Hidrološka stanica`, 40 of them publishing Q. The criterion that actually selects the 99
is the publisher's layer alias, not the object type. Recorded in
[UNRESOLVED.md](UNRESOLVED.md) §7 as an explained exclusion, not a proposal to enable them.

## 3. Reconciling the 230-object station document

The committed CRS evidence document holds 230 objects, against a 60-station baseline. The
difference is fully accounted for:

- **99** are hydrological stations across layers 10/20/30 (97 of them appear in the document).
- **133** document objects are not in those three layers: groundwater stations
  (`General;Stanica podzemnih voda`, layers 40/50), meteorological stations
  (`General;Meteorološka stanica`, layers 60/70), and the EPP "ekološki prihvatljiv protok" series
  (layers 80/90 — hydrological in object type, see §2).
- **2** hydrological stations (`4228`, `9025`) are absent from the document; both also return 404
  for every workbook. See [UNRESOLVED.md](UNRESOLVED.md) §4.

No document object is treated as a missing station without evidence that it is one.

## 4. Population reconciliation against the baseline

All 60 baseline stations were present in the live layer-20 document on 2026-09-09. **Zero
additions, zero removals** since the 2026-08-02 capture. Station ids are unique with no nulls; one
is non-numeric (`2101-B`) and must stay a string.

## 5. How availability was established

Availability is read from the **measurement cells** of each workbook, taken from the worksheet XML
(`xl/worksheets/sheet1.xml`). A published blank is a cell element carrying no value child:

```
<c r="B171" s="3"/>                        no measurement
<c r="B5196" s="5" t="n"><v>1.331</v></c>  a measurement
```

A dataframe loader renders both as `NaN`, so it cannot tell a published blank from a decode
failure. Reading the cell elements keeps that distinction.

Four things had to be ruled out, each of which produces a wrong answer:

**The declared row count is not availability.** `#Rows` counts timestamped rows. For **35** pairs
it is positive while every measurement cell is empty. This is the defect corrected in this
revision; it was the basis of the earlier 208 figure.

**HTTP status is not availability.** 290 of 297 pairs returned 200. Populated, blank-only and
empty workbooks are indistinguishable by status code.

**Layer membership is not availability.** Station `4110` is absent from layer 30, yet its WT
workbook carried 1,827 populated values in the 2026-09-09 capture. Classifying by layer would have
excluded it.

**Content-Length is not availability.** File size does not separate blank from populated: the
blank-only `4023` and `4911` workbooks sit at roughly 12 bytes per row, inside the same band as
populated workbooks. Only 7 pairs carrying measurements are under 10 KB. `Content-Length` is
retained in the inventory as a recorded observation and is not used to classify.

## 6. The distinction this survey holds

| Status | Rows | Meaning |
| --- | --- | --- |
| `measurements_present` | 173 | at least one populated measurement cell in the download |
| `timestamped_without_measurements` | 35 | timestamped rows, every measurement cell published empty |
| `no_data_rows` | 82 | no data rows; parameter and unit still declared |
| `access_failed` | 7 | the route served no workbook (HTTP 404); **not** evidence of absence |
| `uninvestigated` | 0 | — |

An empty or blank-only download declares the station's parameter name and unit throughout. That is
the publisher stating what this download contained, not that the station cannot measure the
parameter. The inventory has no `unsupported` status, because no recorded evidence supports that
claim about any station; `verify_evidence.py` asserts none is ever claimed.

## 7. Temporal horizon — what was established, and what was not

**Established.** Two workbook periods serve measurements: `_1M` and `_1Y`. The `_1Y` workbooks
carry a recent rolling window; across the measurement-carrying downloads captured on 2026-09-09
the observed span runs **2025-09-10 → 2026-09-09**. Each capture's own observed window is recorded
per pair in the inventory (`observed_window_start`, `observed_window_end`), tied to that capture's
acquisition instant.

**Attempted and refused.** 64 attempts across 4 stations and 3 products
(`inventory/horizon_probe.csv`, each with its own preserved response in `evidence/horizon/`):
`_1D`, `_1W`, `_3M`, `_6M`, `_2Y`, `_5Y`, `_10Y`, `_ALL`, `_COMPLETE`, `_HIST` and the `.csv`,
`.json`, `.zip` variants each returned 404 on every target tried. Directory listing returned 403;
recorded, not bypassed.

**Not established.** That no longer-history access method exists. These attempts establish only
that the guessed filename variants above are not served on the stations tried. The publisher may
offer history by some route this survey did not attempt — no archive discovery was performed. See
[UNRESOLVED.md](UNRESOLVED.md) §6.

**Consequence for implementation.** An older requested window returning no measurements through
this rolling download is a limit of this route. It is never evidence that a station lacks
historical measurements.

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
per-station-per-product availability across the whole published population. Converting them into
catalogue rows is implementation work and belongs to the delivery owner.

## 11. What evidence is preserved

Every one of the 297 pairs has its own evidence file recording the exact request URL, HTTP status,
media type, UTC acquisition instant, byte size and the SHA-256 **of the full publisher response**.
`verify_evidence.py` checks that each file's station, product, URL, instant and digest match the
inventory row citing it — correspondence, not merely that a cited file exists.

**No observation values are committed anywhere in this survey.** Workbooks that carry
measurements keep their request, HTTP status, media type, acquisition instant and full-response
digest, plus a derived reading (row counts, unit, parameter, observed window) and an excerpt that
records, per row, only *whether* the publisher's cell carried a value — never the value.
`verify_evidence.py` fails if any measurement value appears.

**180 of the 361 evidence files retain the complete response bytes.** That is every response
carrying no observation values: all 35 blank-only pairs, all 82 empty pairs, all 7 access
failures, and every historical-access attempt. Establishing that a file is blank requires every
cell, and there is no observation value in these files to withhold. These are exactly the
classifications the review disputed, and they are fully checkable offline.

**Limitation, stated plainly.** A digest over bytes that are not retained cannot be recomputed
later: the source serves a rolling window, so a re-fetch returns different bytes. The digest fixes
what was received at the recorded instant; it is not a re-verification route. Whether the full
bytes should be committed is a redistribution decision for the delivery owner —
[UNRESOLVED.md](UNRESOLVED.md) §8.

## 12. Contents

| Path | What it is |
| --- | --- |
| [`FINDINGS.md`](FINDINGS.md) | This document |
| [`STATION_TABLE.md`](STATION_TABLE.md) | The station list: one row per station with per-product status |
| [`HANDOFF.md`](HANDOFF.md) | Implementation handoff: routes, fields, units, availability basis, limits |
| [`UNRESOLVED.md`](UNRESOLVED.md) | Unresolved cases and the decisions required from the delivery owner |
| [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md) | Every preserved response and what it establishes |
| `inventory/station_product_evidence.csv` | The 297-row inventory |
| `inventory/population_sweep.csv` | Raw sweep output, one row per pair |
| `inventory/horizon_probe.csv` | Every historical-access attempt |
| `evidence/` | Per-station-per-product evidence, and the horizon attempts |
| `recordings/` | 28 response-shape examples, in the repository's existing convention |
| `scripts/` | Acquisition, composition and verification scripts |

## 13. Checks run

```
uv run python research/station-coverage/ba_fhmzbih/scripts/verify_evidence.py
```

**25/25 checks pass**, offline. They include the check that would have caught the defect corrected
in this revision: no pair with timestamped rows and zero populated measurement cells may be
classified as carrying measurements. Also verified: per-row evidence correspondence (station,
product, URL, instant, digest); that no evidence file is reused across rows as a stand-in; that
full bytes are retained for every response carrying no observations; that excerpt digests are never
presented as response digests; that every measurements-present row preserves a witness value; and
that every historical-access attempt cites its own response and names its station and product.

Access etiquette: all requests were unauthenticated GET against public routes at ~4 requests per
second with a descriptive User-Agent. Observation bytes were read, classified and discarded rather
than retained. The one refused route (403 directory listing) was recorded and not circumvented. No
credentials, cookies or tokens were sent or stored.

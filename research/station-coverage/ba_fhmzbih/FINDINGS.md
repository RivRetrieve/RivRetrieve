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
| Verification | Protected baseline source check; public survey checks have narrower scope (see §13) |

## 1. Headline

At discovery close the provider exposes **2 stations and 3 series**. The approved
integration destination is **60 baseline stations / 180 selectable series**.

The governing baseline account is [inventory/baseline_workbook_access.json](inventory/baseline_workbook_access.json).
All 180 baseline pairs have complete responses retained in the controlled private corpus:
60 Q and 60 H positive, 12 WT positive, and 48 valid WT workbooks with zero data rows.
All 60 stations and 180 applicable pairs remain selectable after integration, including
48 unknown-availability pairs. Positive-only selection is not the approved contract.
Acquisition dates are mixed: 3 pairs on September 2, 3 on September 7, 48 on September 9,
and 126 on September 13, 2026. These are not a simultaneous snapshot.

The public account is derived accounting, not raw-body proof. Source certification must
read the exact retained bodies. Keep the whole controlled corpus private and out of
wheels and other distributed artifacts. A different review environment needs an
authorised controlled handoff, not an automatic new survey.

The September 9 survey remains historical context: 99 stations / 297 pairs, with
173 positive summaries (132 baseline and 41 outside it), 35 blank-only, 82 empty,
and 7 access failures. Its positive workbook bodies were discarded, so its precise
positive totals are not source-certified by the public summaries. The later governing
baseline captures supersede those summaries for baseline delivery, not for the extra 39.
[STATION_TABLE.md](STATION_TABLE.md) and `inventory/station_product_evidence.csv`
retain that historical survey, not a new scope or the final acquisition dates.

The earlier 208-positive claim incorrectly used `#Rows`. Thirty-five surveyed pairs
had timestamped rows but blank measurement cells. The retained blank responses support
that correction. All 35 are outside the baseline. This does not justify excluding
unknown availability or expanding the approved population.

## 2. Why the baseline is 60, and what that omitted

`native.parquet` has the same station-ID membership as recorded **layer 20**, the publisher's *Proticaj*
(discharge) display layer. The baseline capture selected that layer. Membership equality does not mean byte equality
between a Parquet table and a JSON response, or that runtime routing caused the population limit.

The publisher's layer manifest (`layers/index.json`) declares ten layers. RivRetrieve's three
products correspond to three of them:

| Product | Layer | Label | Stations |
| --- | --- | --- | --- |
| `discharge_reported` | 20 | Proticaj | 60 |
| `stage_reported` | 10 | Vodostaj | 99 |
| `water_temperature_reported` | 30 | Temperatura vode | 13 |

The union is **99 stations**. Layer 20 is not "the stations that have discharge": 39 stations
outside it are declared in the stage layer, and two have positive discharge summaries in the historical survey.

This survey does not merge those 39 into the baseline. Every inventory row carries `in_baseline`.
The agreed scope remains the original 60 — see [UNRESOLVED.md](UNRESOLVED.md) §3.

**Object type does not separate this population from the rest of the portal.** Layers 80 and 90
(`EPPVodostaj`, `EPPProticaj`) carry 81 further stations of the identical object type
`General;Hidrološka stanica`, 40 of them declared in the Q layer. The criterion that actually selects the 99
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

All 60 baseline stations were present in the retained layer-20 response acquired on 2026-09-07. **Zero
additions, zero removals** since the 2026-08-02 capture. Station ids are unique with no nulls; one
is non-numeric (`2101-B`) and must stay a string.

## 5. How availability was established

Availability is read from the **measurement cells** of each workbook, taken from the worksheet XML
(`xl/worksheets/sheet1.xml`). A published blank is a cell element carrying no value child:

```
<c r="B171" s="3"/>                        no measurement
<c r="B5196" s="5" t="n"><v>1.331</v></c>  a measurement
```

Read cell type and finite numerical content as well as timestamped blanks. A nonempty
text cell is not numerical evidence. The protected baseline check compared independent
worksheet XML counts with the pinned production parser; both agree on 1,201,474 numerical
cells and 1,270 timestamped blanks in 16 positive workbooks. The historical survey reader
counted populated cells, which alone is not a finite-numeric check.

Four things had to be ruled out, each of which produces a wrong answer:

**The declared row count is not availability.** `#Rows` counts timestamped rows. For **35** pairs
it is positive while every measurement cell is empty. This is the defect corrected in this
revision; it was the basis of the earlier 208 figure.

**HTTP status is not availability.** 290 of 297 pairs returned 200. Populated, blank-only and
empty workbooks are indistinguishable by status code.

**Layer membership is not availability.** Station `4110` is absent from layer 30, yet its governing WT workbook contains
numerical measurements. The September 9 survey separately reports 1,827 populated cells;
that older exact total is not certified from its discarded body. Classifying by layer would have
excluded it.

**Content-Length is not availability.** File size does not separate blank from populated: the
blank-only `4023` and `4911` workbooks sit at roughly 12 bytes per row, inside the same band as
populated workbooks. Only 7 pairs carrying measurements are under 10 KB. `Content-Length` is
retained in the inventory as a recorded observation and is not used to classify.

## 6. Historical survey classifications (not governing baseline totals)

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

**Established.** The configured `_1Y` route serves rolling workbooks. A recorded
`4024/Q` `_1M` example also exists. This does not establish exactly two possible periods
or rule out other date parameters. The historical September 9 positive summaries report
a combined span **2025-09-10 → 2026-09-09**; their discarded bodies do not certify it. The historical inventory reports per-pair
`observed_window_start` and `observed_window_end`. Use the governing baseline account
for the actual spans and acquisition instants of the complete private replacements.

**Historical attempts.** There were 64 attempts across 4 stations and 3 products:
56 refusals retain complete response bodies, and 8 positive attempts retain summaries
without bodies. Each has request/response accounting in `evidence/horizon/` and a row
in `inventory/horizon_probe.csv`. Among the refused attempts, `_1D`, `_1W`, `_3M`,
`_6M`, `_2Y`, `_5Y`, `_10Y`, `_ALL`, `_COMPLETE`, `_HIST` and the `.csv`, `.json`
and `.zip` variants returned 404 on the targets tried. Directory listing returned 403;
recorded, not bypassed.

**Not established.** That no longer-history access method exists. These attempts establish only
that the guessed filename variants above are not served on the stations tried. The publisher may
offer history by some route this survey did not attempt — no archive discovery was performed. See
[UNRESOLVED.md](UNRESOLVED.md) §6.

**Consequence for implementation.** An older requested window returning no measurements through
this rolling download is a limit of this route. It is never evidence that a station lacks
historical measurements.

## 8. Units and time semantics

The governing baseline workbook headers match station, parameter and configured units:
`m³/s` (60 Q workbooks), `cm` (60 H), `°C` (60 WT, including the 48 empty workbooks).

`#Timeseries Name` is `81 Web Kontinuirani` at every station and product. It names a timeseries
without stating statistic, frequency, period type or period anchor — these stay `unknown`.
Workbook timestamps are naive with no zone marker, so `zone` stays `unknown`. Nothing here is
inferred; see [UNRESOLVED.md](UNRESOLVED.md) §5.

## 9. Publication and upstream responsibility

**Agencija za vodno područje rijeke Save (AVP Sava)** is the evidenced issuer of
the directly acquired station/workbook material. The portal title names that agency.
Keep the stable public key `ba_fhmzbih`; correct institutional display descriptions and
provenance, not the provider ID.

Original measurement production and further upstream responsibility are not established.
A station-reference responsibility field is not authorship of every observation. No
new original-producer enquiry is a prerequisite under the approved official-publication
scope. This issuer evidence does not settle an unestablished dataset-author citation.
Preserve source terms and citation words verbatim; infer no legal classification or
redistribution permission.

## 10. Relation to the withheld facts

The packaged `catalogue/provenance.json` carries **293 withheld fact groups**, every one with reason
`no_acquisition_record_established`: 58 withheld station identities, 58 withheld observation facts
and 177 withheld candidate availability facts. Its single source record names issuer *Agencija za
vodno područje rijeke Save* with operator *vodostaji.voda.ba*, which this survey's portal evidence
corroborates.

Those facts were withheld for want of an acquisition record, not because the source denies them.
The complete controlled governing acquisitions now account for all 180 baseline pairs and
their exact routes. Integration must bind those acquisitions and the official station identity
evidence through the existing catalogue authority and provenance checks. The historical
297-pair survey does not certify acquisitions across the whole published population; its
41 nonbaseline positive summaries remain outside this delivery scope.

## 11. What evidence is preserved

The historical 297-pair survey has per-pair request, status, media type, acquisition instant,
body size and digest accounting. Of its 361 evidence files, 180 retain full bodies:
35 blank-only pairs, 82 empty pairs, 7 access failures and 56 horizon refusals. The
64 horizon attempts include 8 positive summaries without bodies. These counts are separate
from the **180 governing baseline responses**, all retained privately.

Historical positive excerpts carry `has_value` booleans, not measurement values.
Neither those booleans nor a digest without the original body can prove a numerical
classification. A later rolling download does not recover discarded September 9 bytes.

There is no approved project-wide ban on measurement values in research or recordings.
Layer JSON includes `L1_ts_value` snapshots, so a blanket “no values anywhere” assertion
was false. Do not extend a research scanner into repository policy or infer a legal
verdict from absent terms. Genuine recorded-source testing remains required. Publishing
any needed representative recordings requires normal review; do not automatically
upload the private corpus or selected files from it.

## 12. Contents

| Path | What it is |
| --- | --- |
| [`FINDINGS.md`](FINDINGS.md) | This document |
| [`STATION_TABLE.md`](STATION_TABLE.md) | The station list: one row per station with per-product status |
| [`HANDOFF.md`](HANDOFF.md) | Implementation handoff: routes, fields, units, availability basis, limits |
| [`UNRESOLVED.md`](UNRESOLVED.md) | Remaining limits and settled decisions |
| [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md) | Retained responses, historical summaries and their limits |
| `inventory/station_product_evidence.csv` | Historical 297-row survey inventory |
| `inventory/baseline_workbook_access.json` | Governing 180-pair derived baseline account |
| `inventory/population_sweep.csv` | Raw sweep output, one row per pair |
| `inventory/horizon_probe.csv` | Every historical-access attempt |
| `evidence/` | Per-station-per-product evidence, and the horizon attempts |
| `recordings/` | 24 complete response recordings and 4 historical digest-only summaries; see `EVIDENCE_INDEX.md` |
| `scripts/` | Acquisition, composition and verification scripts |

## 13. Verification boundaries

The old “25/25 checks pass” result was a false assurance: a deliberately false positive
summary passed despite unchanged blank source bytes. Comparing derived assertions did
not verify classification. That result is retired, not acceptance evidence.

Public survey check (offline, no controlled root):

```sh
uv run python research/station-coverage/ba_fhmzbih/scripts/verify_evidence.py
```

This mode verifies retained public survey bytes and correspondence. It cannot prove
positive classifications whose private source bodies are absent. It must not report
baseline source certification from the public ledger alone.

Protected baseline source certification (offline):

```sh
uv run python research/station-coverage/ba_fhmzbih/scripts/verify_evidence.py --evidence-root <controlled-ba-directory> --baseline-native src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet
```

This check requires all 180 governing bodies and checks digest/size, exact pair membership,
station/parameter/unit identity, metadata routes, worksheet cells and governing accounting.
A missing required body is a failure. The completed independent audit also checked the
pinned production parser. Those parser observations are not independently authored new
boundary expectations. Review verifier execution and accepted research before claiming
delivery; this documentation does not itself merge research or expand production.

The historical survey used unauthenticated GETs and recorded, rather than bypassed, a
403 directory refusal. Do not rerun acquisition scripts to repair evidence gaps.

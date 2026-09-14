# ba_fhmzbih implementation handoff

For the implementing agent. Use complete governing baseline source responses, not
historical survey summaries, to certify workbook access. Response-shape examples in
`recordings/` cannot prove another station’s result. Nothing is inferred from identifiers.

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


Baseline commit: `67796ab8d793867aaaaf9c6fb55bec208adaeab8` · native table captured `2026-08-02T12:42:03Z`
· this survey captured `2026-09-09`.

## 1. Population and identity

The publisher exposes per-parameter **layers**. The authoritative list is
`layers/index.json` (`recordings/layers_manifest.recording.json`), which declares ten layers.
The three RivRetrieve products map to exactly three of them:

| Product | Layer | Layer label | Source code |
| --- | --- | --- | --- |
| `discharge_reported` | 20 | Proticaj | `Q` |
| `stage_reported` | 10 | Vodostaj | `H` |
| `water_temperature_reported` | 30 | Temperatura vode | `WT` |

The remaining seven layers are outside the surveyed population:
40 `GroundWaterLevel` and 50 `GroundWaterTemp` carry object type `General;Stanica podzemnih voda`;
60 `Precipitation` and 70 `AirTemp` carry `General;Meteorološka stanica`.
80 `EPPWaterLevel` and 90 `EPPFlow` are the "ekološki prihvatljiv protok" series — note these carry
object type `General;Hidrološka stanica`, the *same* type as the surveyed 99, so object type does
not distinguish them. They are excluded by layer alias. See `UNRESOLVED.md` §7.

**Identity.** `metadata_station_no` is the public `station_id` (unique, no nulls, 0 duplicates
across the population). `metadata_site_no` is the workbook path group. Both come from the layer
documents. One station id is non-numeric (`2101-B`), so station ids must stay strings.

**Population.** The committed baseline of 60 is exactly the layer-20 membership. The union of
layers 10/20/30 is **99** hydrological stations. See `FINDINGS.md` §2 for the reconciliation and
the settled original-60 scope. No expansion to the other 39 or EPP objects is included.

## 2. Retrieval route

```
https://vodostaji.voda.ba/data/internet/stations/{site_no}/{station_no}/{code}/{workbook}
```

| Product | code | workbook |
| --- | --- | --- |
| `discharge_reported` | `Q` | `Q_1Y.xlsx` |
| `stage_reported` | `H` | `H_1Y.xlsx` |
| `water_temperature_reported` | `WT` | `Tvode_1Y.xlsx` |

`site_no` must be resolved from a layer document, never derived from the station id. The current
adapter resolves it from `layers/20/index.json`. The historical baseline capture selected
that layer; runtime routing did not cause the population limit. All baseline route groups
were checked against the retained September 7 layer-20 response. `2101-B` routes to site
`3`; preserve its string identity. Do not rewrite the existing exact-route fetch logic
to solve the catalogue’s sample-only acquisition bindings.

## 2a. Request shape, pagination and access requirements

**Observed access.** The surveyed requests succeeded without authentication where the
route was served. No API key, token, cookie or session was sent. Do not interpret that
access observation as a legal permission or a guarantee about future source behaviour.

**Observed pagination: none.** Layer documents are unpaginated JSON arrays returned whole (layer 10 is the
largest at 99 objects / 106 KB). The layer manifest is a single object. Workbooks are single-sheet
XLSX files returned whole. No `Link` header, cursor, offset or page parameter appears on any route.

**Configured request windows.** The adapter uses source-fixed rolling-year workbook
filenames and the engine renders no date arguments for these calls. A recorded `4024/Q`
monthly example also exists. This does not establish that the publisher accepts no other
date parameters or offers exactly two possible periods. Clipping to the user’s requested
window happens after parsing. Preserve ordinary requested-window behaviour.

**Distinct response shapes recorded:** unpaginated JSON array (layer documents), JSON object (layer
manifest), XLSX with a populated body, XLSX with a header block and zero data rows, HTTP 404 for an
absent route, HTTP 403 for a refused directory listing.

## 3. Source fields and units

Every workbook begins with an 8-row header block, then `#Timestamp` / `Value` rows.

| Header field | Meaning |
| --- | --- |
| `#Station Name`, `#Station Number` | station identity |
| `#Station Parameter Name` | `Proticaj` / `Vodostaj` / `Temperatura vode` |
| `#Timeseries Name` | `81 Web Kontinuirani` for all three products, at every station observed |
| `#Unit Symbol` | `m³/s` (Q), `cm` (H), `°C` (WT) |
| `#Rows` | the publisher's count of **timestamped rows** — not of measurements (see §4) |

Units match the committed `config.py` exactly.

## 4. Availability basis

**Availability is established from the measurement cells, not from `#Rows`.** The header's `#Rows`
field counts timestamped rows. A workbook can declare hundreds of rows while every measurement cell
is published empty: 35 of the 297 surveyed pairs are exactly that.

Read the measurement cells from the worksheet XML. A published blank is a cell element with no
value child:

```
<c r="B171" s="3"/>                        no measurement
<c r="B5196" s="5" t="n"><v>1.331</v></c>  a measurement
```

Check finite numerical content and cell type, not merely nonempty text. The historical
survey reader counted populated cells; that alone cannot certify numerical availability.
The protected baseline verification compares source XML and governing counts. Independent
XML and the pinned production parser agreed on 1,201,474 numerical cells and 1,270
timestamped blanks in 16 positive workbooks. Do not promote these observed parser outputs
into independently authored new boundary expectations.

| Status | Meaning |
| --- | --- |
| `measurements_present` | governing baseline: at least one finite numerical measurement |
| `timestamped_without_measurements` | timestamped rows, every measurement cell published empty |
| `no_data_rows` | no data rows at all; parameter and unit still declared |
| `access_failed` | the route served no workbook (HTTP 404) |

A blank-only or empty download still declares the station's parameter name and unit. That states
what this download contained. It is **not** a statement that the station cannot measure the
parameter, and must not be recorded as one.

HTTP status carries no availability signal: populated, blank-only and empty workbooks all return
200. A recorded 404 is a dated access failure, not proof of permanent absence.

## 5. Temporal horizon

**Established.** Keep configured `Q_1Y.xlsx`, `H_1Y.xlsx` and `Tvode_1Y.xlsx`
rolling-year access. `horizon_4024_Q_1M_exists.recording.json` identifies a known monthly
example, not a historical archive or an exhaustive list of periods.

Each governing capture’s actual observed span and acquisition instant are recorded in
[inventory/baseline_workbook_access.json](inventory/baseline_workbook_access.json).
Do not substitute the September 9 survey’s older reported span for these mixed-date
captures. Rolling windows can change on later requests.

**Historical attempts.** There were 64 attempts across 4 stations and 3 products:
56 refusals retain complete response bodies, and 8 positive attempts retain summaries
without bodies. Each has request/response accounting in `evidence/horizon/` and a row
in `inventory/horizon_probe.csv`. Among the refused attempts, `_1D`, `_1W`, `_3M`,
`_6M`, `_2Y`, `_5Y`, `_10Y`, `_ALL`, `_COMPLETE`, `_HIST` and the `.csv`, `.json`
and `.zip` variants returned 404 on the targets tried. Directory listing returned 403;
recorded, not bypassed.

**Not established.** That no longer-history access method exists. The attempts above establish only
that these filename variants are not served at this route on the stations tried. Whether the
publisher offers an archive by some other means was not investigated — see `UNRESOLVED.md` §6.

**Consequence for the adapter.** The configured route provides a recent rolling window only. That
is a limitation of this route, and it must not be stated as a limitation of every access method the
publisher might offer.

## 6. Time semantics

Workbook timestamps are naive — the cells carry no zone marker. No official zone statement was
found, so `zone` must stay `unknown`, as it is today.

One adjacent fact, recorded but deliberately **not** promoted to a zone claim: the live layer
documents carry `L1_timestamp` values with a `+02:00` offset. That describes the live snapshot
field, not the workbook timestamps, and the two were not shown to share a zone.

`#Timeseries Name` is `81 Web Kontinuirani` throughout, which names a timeseries but does not state
statistic, frequency, period type or period anchor. Those remain `unknown`.

Station descriptions in the station document give founding and renovation years (e.g. "Stanica
osnovana 1963. godine"). These are **not** published record bounds and must not be used as such.

## 7. Publication responsibility

**Agencija za vodno područje rijeke Save (AVP Sava)** is the evidenced issuer of the
directly acquired station/workbook material (`recordings/portal_root.recording.json`
identifies the portal). Keep the public key `ba_fhmzbih`; correct institutional display
and provenance descriptions without a provider-ID migration.

Original measurers and further upstream responsibility remain unestablished, not a new
producer-enquiry prerequisite. Issuer evidence does not settle an absent dataset-author
citation. Preserve source terms and citation words verbatim; infer no legal verdict.

Keep responsibilities in the existing provider catalogue authority/generation and
fetch/parse boundaries. Source-workbook evidence reading and station-product acquisition
accounting are stable domain responsibilities, not ticket-named product architecture.

## 8. Things that must not be done

- **Do not treat the `#Rows` header as a measurement count.** It counts timestamped rows. 35 of the
  297 surveyed pairs declare rows > 0 with every measurement cell published empty. Read the cells.
- **Do not classify from nonempty text or a derived `has_value` flag.** Check actual
  numerical cells and preserve timestamped blanks as a distinct source fact.
- Do not treat layer membership as availability. Station `4110` is absent from layer 30 yet its WT
  governing workbook has numerical measurements; the older September 9 exact summary
  is not source-certified from its discarded body.
- Do not treat HTTP 200 as availability. 290 of 297 pairs returned 200, across three different
  classifications.
- Do not treat file size as availability. Blank-only and populated workbooks overlap in bytes per row.
- Do not derive `site_no` from the station id.
- Do not convert a blank-only or empty download into "unsupported measurement". It establishes what
  that download contained, nothing about the station's capability.
- **Do not treat an older requested window returning no measurements as evidence that a station
  lacks historical data.** It is a limit of this rolling route.
- Do not state that longer history cannot be retrieved by any means. That was not established.
- Do not infer a timezone, statistic, frequency, or record bound from anything in this survey.

## 9. Offline verification and publication boundary

The old 25/25 verifier result accepted a false positive summary over unchanged blank
bytes and is retired as acceptance evidence. Public no-root mode checks retained survey
bytes but cannot prove private positives. Use this explicit protected source check:

```sh
uv run python research/station-coverage/ba_fhmzbih/scripts/verify_evidence.py --evidence-root <controlled-ba-directory> --baseline-native src/rivretrieve/_internal/providers/ba_fhmzbih/catalogue/native.parquet
```

Missing required source bodies must fail. The whole corpus stays private. Public derived
accounting is not raw-body proof. Review any required genuine representative recording
publication separately; retain existing source-recording and independent-expectation
requirements. No blanket measurement-value ban is approved. Do not reacquire the survey.

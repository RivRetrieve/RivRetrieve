# ba_fhmzbih — remaining limits and settled decisions

The agreed implementation vision settles baseline scope, publication responsibility and
retention. Nicolas (@CooperBigFoot) owns remaining verification, acceptance and delivery.
These limits do not reopen a correction-request cycle with Thiago or require new acquisition.

---

## 1. Publication responsibility — SCOPE SETTLED

**Established.** The portal is operated by Agencija za vodno područje rijeke Save (AVP Sava): the
portal root's title is that name, and `vodostaji.voda.ba` is a subdomain of the agency's `voda.ba`.

**Attempted.** The exact-host impressum (`tests/test_data/ba_fhmzbih_terms_absence.html`) names no
organisation — it states purpose and disclaims official status only. The station document carries a
`BODY_RESPONSIBLE` field, but it is **empty for 59 of the 60 baseline stations**; where populated
across the full 230 objects it names cantonal ministries (54 Srednjebosanski, 16 Ze-Do, 9 BPK) and
"AVP Sava" (5), predominantly on EPP stations. Per-station `ObjectDescription` text was searched for
jurisdiction statements: of 96 non-empty descriptions among our hydrological stations, only **8**
name a responsible body, all `JP Spreča d.d. Tuzla`. The remainder record founding/renovation years.

**Remaining limit.** Original measurement production and additional upstream responsibility
are not established. The approved requirement is traceable official publication: AVP Sava
is the issuer of the directly acquired station/workbook material. No new producer enquiry
is a prerequisite for baseline expansion. This does not resolve a dataset-author citation
or authorise inventing an original measurer.

---

## 2. Provider identity — SETTLED

Keep the stable public key `ba_fhmzbih`. Institutional display descriptions and provenance
must identify the evidenced AVP Sava issuer. A public provider key is an authored identity,
not evidence that its historical abbreviation names the publisher. No provider-ID migration
is in scope.

---

## 3. Population scope: original 60 only — SETTLED

The committed baseline is exactly the layer-20 (discharge) membership. The union of the three
surface-water layers is 99 stations.

**An earlier revision of this survey overstated the case for extending.** It reported that 36 of
the 39 additional stations had populated discharge workbooks. Reading the measurement cells rather
than the `#Rows` header shows **34 of those 36 carry no discharge values at all** — timestamped
rows with every measurement cell published empty. Only two additional stations have positive discharge summaries
in the historical survey (their positive bodies were discarded):

| Station | Name | Populated Q values |
| --- | --- | --- |
| `1030` | HS Orašje | 2,161 |
| `4230` | HS Obre | 8,484 |

What the historical 2026-09-09 summaries report for the 39 additional stations: **2** discharge series,
**36** stage series, **3** water-temperature series — 41 series in total, not 76.

Of the 34 blank-only discharge workbooks, 29 belong to stations named `HS …` (hidrološka stanica)
and 5 to stations named `CS …`. The station name therefore does not predict which stations serve
discharge values, and no reason for the blanks was established: the publisher exposes a `Q` route
for these stations and returns timestamps without values on it. Recorded as observed.

This survey **does not** merge them into the baseline. Every inventory row carries `in_baseline`
so the committed population stays distinguishable.

**Settled.** Integration remains the original 60-station baseline and all 180 applicable
pairs, including 48 selectable unknown WT pairs. The additional 39 stations / 117 pairs
are historical survey context only. Their 41 positive summaries are not certified by the
new baseline captures. No population expansion decision is pending for this delivery.

---

## 4. Two stations listed but not served — REPORTED, NO DECISION NEEDED

`4228` (HS Bakovići-Željeznica, Bosna) and `9025` (HS Tržac, Mutnica) appear in the stage layer but

- are absent from the 230-object station document, and
- return HTTP 404 for every workbook, including the `H` workbook their layer membership implies.

Recorded as `access_failed` in the inventory, never as "no data". Both are outside the committed
baseline, so they block nothing. They remain dated source access outcomes, not permanent absence or an automatic
exclusion policy for any future scope.

---

## 5. Unestablished source semantics — RETAIN UNKNOWN

Reported so they are not mistaken for gaps in the research:

- **Timezone of workbook timestamps.** Cells are naive; no zone statement was found. Stays `unknown`.
- **Statistic, frequency, period type, period anchor.** `#Timeseries Name` is `81 Web Kontinuirani`
  at every station and product, which names a timeseries without stating any of these.
- **Published record bounds.** Not established in the reviewed material. Station founding years exist in descriptions but are
  not record bounds and were not used as such.
- **Horizontal CRS.** Unchanged from the committed position: the station document publishes no
  horizontal-CRS token.

---

## 6. Longer-history method — UNESTABLISHED, NOT A DELIVERY BLOCKER

**Reopened.** An earlier revision closed this as "CLOSED WITH EVIDENCE", stating that data older
than one year is not retrievable through this route at all. The preserved evidence does not carry
that conclusion.

**What is established.** The configured `_1Y` rolling route and a recorded `4024/Q`
`_1M` example serve measurements. This is not an exhaustive list of periods or parameters.

**Historical attempts.** There were 64 attempts across 4 stations and 3 products:
56 refusals retain complete response bodies, and 8 positive attempts retain summaries
without bodies. Each has request/response accounting in `evidence/horizon/` and a row
in `inventory/horizon_probe.csv`. Among the refused attempts, `_1D`, `_1W`, `_3M`,
`_6M`, `_2Y`, `_5Y`, `_10Y`, `_ALL`, `_COMPLETE`, `_HIST` and the `.csv`, `.json`
and `.zip` variants returned 404 on the targets tried. Directory listing returned 403;
recorded, not bypassed.

**What is not established.** That no longer-history access method exists. A 404 for a guessed
filename establishes that this filename is not served at this route — not that the publisher
offers no archive by any other means. No archive discovery was attempted, and issue #223 does not
ask for one.

**Settled.** Keep configured rolling-year access and the monthly example distinct from
an archive. Longer-history methods remain unestablished, and no further archive survey
is required for this outcome. Ordinary future requested windows are not restricted to
the research windows.

**Must not be inferred.** An older requested window returning no measurements through this rolling
download is a limit of this route. It is never evidence that a station lacks historical
measurements.

---

## 7. EPP layers 80/90: 81 further hydrological-typed stations — EXPLAINED EXCLUSION

The publisher's layers 80 (`EPPVodostaj`) and 90 (`EPPProticaj`) carry 81 stations in the `7xxx`
range, all under site `7000`, all of object type `General;Hidrološka stanica` — the same object
type as the 99 surveyed — with the same `81 Web Kontinuirani` timeseries name. 40 appear in the Q layer and 81 in the H layer; layer membership is not workbook
availability evidence.

They are excluded from the surveyed population, and the honest statement of why is that they sit
outside the three layers RivRetrieve's products map to. **Object type does not separate them**, so
the "identical object type" argument for extending the population (see §3) does not distinguish
these from the 39.

Their names identify them as hydro-plant environmental-flow monitoring points
(`EPP mHE Kaljani nizvodno` / `uzvodno`, and similar upstream/downstream pairs), which is a
different kind of measurement site from a river gauge. That is a reading of the names, not a
publisher statement of scope, and it is recorded here as such.

**No decision needed** unless the delivery owner wants them investigated. Issue #223 limits
coverage to this provider's captured inventory and directs that extra published objects be
explained rather than assumed to be missing stations. This entry is that explanation.

---

## 8. Governing body retention — COMPLETE PRIVATELY; PUBLICATION REVIEW REMAINS

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

The historical survey discarded positive workbook bodies, and `has_value` excerpts are
only derived assertions. Acceptance of those excerpts as a substitute is not pending:
complete governing baseline responses now replace that insufficient basis, with their
actual mixed dates. They do not recover discarded September 9 bytes or certify the
nonbaseline positive summaries.

Public accounting can identify acquisitions by route, date, digest, size and derived
counts without publishing the bodies. It does not itself recalculate numerical cells.
Use the protected verifier command in [FINDINGS.md](FINDINGS.md) §13. Fail when a
required governing body is unavailable; arrange an authorised controlled handoff.

Keep the whole verification corpus private. Publishing accepted derived accounting,
source documentation and any required genuine representative test recordings follows
normal review. There is no blanket no-values policy, legal classification or inferred
redistribution permission. Layer recordings contain measurement snapshots. Preserve
source terms and citation words verbatim and leave unestablished citation fields absent.

Remaining gates are reviewed publication, controlled portability where needed, authorised
recorded-test inputs, independent source-derived boundary expectations, and accepted/merged
research and implementation. Public-only checks or an open PR do not complete delivery.

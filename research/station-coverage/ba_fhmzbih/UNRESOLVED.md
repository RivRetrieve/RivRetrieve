# ba_fhmzbih — unresolved cases and decisions required

Separated deliberately from the established findings. Each entry states what was attempted, the
exact remaining question, and whether it needs a scope decision from the delivery owner
(@CooperBigFoot) or further research.

---

## 1. Producer versus distributor — RESEARCH INCOMPLETE

**Established.** The portal is operated by Agencija za vodno području rijeke Save (AVP Sava): the
portal root's title is that name, and `vodostaji.voda.ba` is a subdomain of the agency's `voda.ba`.

**Attempted.** The exact-host impressum (`tests/test_data/ba_fhmzbih_terms_absence.html`) names no
organisation — it states purpose and disclaims official status only. The station document carries a
`BODY_RESPONSIBLE` field, but it is **empty for 59 of the 60 baseline stations**; where populated
across the full 230 objects it names cantonal ministries (54 Srednjebosanski, 16 Ze-Do, 9 BPK) and
"AVP Sava" (5), predominantly on EPP stations. Per-station `ObjectDescription` text was searched for
jurisdiction statements: of 96 non-empty descriptions among our hydrological stations, only **8**
name a responsible body, all `JP Spreča d.d. Tuzla`. The remainder record founding/renovation years.

**Exact remaining question.** For the ~88 hydrological stations with no `BODY_RESPONSIBLE` value and
no jurisdiction statement, which organisation produces the observations? AVP Sava is established as
*publisher*; it is not established as *producer*, and this survey does not assert it.

**Needed.** Further research, most likely a direct enquiry to the agency. A reviewer with knowledge
of the BiH institutional landscape may resolve it faster than further web survey.

---

## 2. Provider identifier appears to name the wrong institution — DECISION REQUIRED

The provider id is `ba_fhmzbih`, i.e. Federalni hidrometeorološki zavod BiH. No evidence found in
this survey ties the data at `vodostaji.voda.ba` to that institute; all publisher evidence points to
AVP Sava. The committed `origins.py` already records the issuer as AVP Sava, so the identifier and
the provenance disagree.

**Needed.** A decision from the delivery owner. This survey changes no production identifier.

---

## 3. Population scope: 60 committed versus 99 published — DECISION REQUIRED

The committed baseline is exactly the layer-20 (discharge) membership. The union of the three
surface-water layers is 99 stations.

**An earlier revision of this survey overstated the case for extending.** It reported that 36 of
the 39 additional stations had populated discharge workbooks. Reading the measurement cells rather
than the `#Rows` header shows **34 of those 36 carry no discharge values at all** — timestamped
rows with every measurement cell published empty. Only two additional stations serve discharge
measurements:

| Station | Name | Populated Q values |
| --- | --- | --- |
| `1030` | HS Orašje | 2,161 |
| `4230` | HS Obre | 8,484 |

What the 39 additional stations actually offer, on the 2026-09-09 capture: **2** discharge series,
**36** stage series, **3** water-temperature series — 41 series in total, not 76.

Of the 34 blank-only discharge workbooks, 29 belong to stations named `HS …` (hidrološka stanica)
and 5 to stations named `CS …`. The station name therefore does not predict which stations serve
discharge values, and no reason for the blanks was established: the publisher exposes a `Q` route
for these stations and returns timestamps without values on it. Recorded as observed.

This survey **does not** merge them into the baseline. Every inventory row carries `in_baseline`
so the committed population stays distinguishable.

**Needed.** A decision whether coverage extends to the published hydrological population or stays
at the captured layer-20 baseline. Issue #223 says not to assume every published object should be
enabled, and limits coverage to "this existing provider and its captured inventory"; it also says
the difference must be explained rather than left silent. This entry is that explanation. The
36 stage series are the substantive gain; the discharge argument is now down to two stations.

---

## 4. Two stations listed but not served — REPORTED, NO DECISION NEEDED

`4228` (HS Bakovići-Željeznica, Bosna) and `9025` (HS Tržac, Mutnica) appear in the stage layer but

- are absent from the 230-object station document, and
- return HTTP 404 for every workbook, including the `H` workbook their layer membership implies.

Recorded as `access_failed` in the inventory, never as "no data". Both are outside the committed
baseline, so they block nothing. If the scope decision in §3 extends coverage to the published
population, these two must be excluded with this evidence rather than silently dropped.

---

## 5. Facts the source does not publish — CLOSED AS UNKNOWN

Reported so they are not mistaken for gaps in the research:

- **Timezone of workbook timestamps.** Cells are naive; no zone statement was found. Stays `unknown`.
- **Statistic, frequency, period type, period anchor.** `#Timeseries Name` is `81 Web Kontinuirani`
  at every station and product, which names a timeseries without stating any of these.
- **Published record bounds.** Not published. Station founding years exist in descriptions but are
  not record bounds and were not used as such.
- **Horizontal CRS.** Unchanged from the committed position: the station document publishes no
  horizontal-CRS token.

---

## 6. Longer history: is any other access method available? — RESEARCH INCOMPLETE

**Reopened.** An earlier revision closed this as "CLOSED WITH EVIDENCE", stating that data older
than one year is not retrievable through this route at all. The preserved evidence does not carry
that conclusion.

**What is established.** `_1M` and `_1Y` workbooks serve measurements. Across 64 attempts on 4
stations and 3 products, the period suffixes `_1D`, `_1W`, `_3M`, `_6M`, `_2Y`, `_5Y`, `_10Y`,
`_ALL`, `_COMPLETE`, `_HIST` and the `.csv`, `.json` and `.zip` variants each returned 404, and
directory listing returned 403. Every attempt has its own preserved response in `evidence/horizon/`
and names the station, product and request it concerns (`inventory/horizon_probe.csv`).

**What is not established.** That no longer-history access method exists. A 404 for a guessed
filename establishes that this filename is not served at this route — not that the publisher
offers no archive by any other means. No archive discovery was attempted, and issue #223 does not
ask for one.

**Needed.** Either acceptance that the adapter's configured route is limited to a recent rolling
window, with longer history left as an open question, or a decision to research publisher archive
access directly (likely an enquiry to the agency, as in §1).

**Must not be inferred.** An older requested window returning no measurements through this rolling
download is a limit of this route. It is never evidence that a station lacks historical
measurements.

---

## 7. EPP layers 80/90: 81 further hydrological-typed stations — EXPLAINED EXCLUSION

The publisher's layers 80 (`EPPVodostaj`) and 90 (`EPPProticaj`) carry 81 stations in the `7xxx`
range, all under site `7000`, all of object type `General;Hidrološka stanica` — the same object
type as the 99 surveyed — with the same `81 Web Kontinuirani` timeseries name. 40 of them publish
Q and 81 publish H.

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

## 8. Retention of workbook bytes — YOUR ACCEPTANCE REQUIRED

Every response carrying **no** observation values is committed in full: all 35 blank-only pairs,
all 82 empty pairs, all 7 access failures, all 64 historical-access attempts (180 files). Those
are the disputed classifications, and establishing that a file is blank requires every cell.

Workbooks that carry measurements are **not** committed. They keep the exact request, HTTP status,
media type, acquisition instant, byte size and full-response SHA-256, plus a derived reading and a
per-row record of whether each cell carried a value. No measurement value is stored anywhere;
`verify_evidence.py` fails if one appears.

**This does not meet your bullet literally.** You asked to "retain the exact non-secret request,
response bytes, HTTP status, media type, actual acquisition time and digest". Everything in that
list is retained except **response bytes, for the 173 workbooks that carry measurements**.

Your own next sentence — that the correction "does not require downloading complete histories" —
suggests this is what you meant, and #223 says the same ("do not download whole observation
histories merely to prove access"). The source also records `"license": None`
(`generate_catalogue.py:403`) and no redistribution grant. But none of that is you saying the gap
is closed, so it stays open here.

**Needed.** Your explicit acceptance that request + HTTP status + media type + acquisition instant
+ full-response digest + a per-row populated/empty record is sufficient evidence for a workbook
that carries measurements. If it is not sufficient, say what would be — noting that committing the
observations themselves is not available to us: this project does not redistribute source data.

**Consequence, stated plainly.** A digest over bytes that are not retained cannot be recomputed
later: the source serves a rolling window, so a re-fetch returns different bytes. The digest fixes
what was received at the recorded instant. Re-running `sweep_population.py` reproduces the
classification, not the original bytes.

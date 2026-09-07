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
surface-water layers is 99 stations of the identical object type `General;Hidrološka stanica`.

The 39 additional stations are not a different kind of object. Evidence in
`inventory/station_product_evidence.csv` shows they carry populated workbooks for products
RivRetrieve already supports, including 29 with populated **discharge** workbooks despite being
absent from the discharge layer.

This survey **does not** merge them into the baseline. Every inventory row carries `in_baseline`
so the committed population stays distinguishable.

**Needed.** A decision whether coverage extends to the published hydrological population or stays
at the captured layer-20 baseline. Issue #223 says not to assume every published object should be
enabled; it also says the difference must be explained rather than left silent. This entry is that
explanation.

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

## 6. Availability outside the one-year horizon — CLOSED WITH EVIDENCE

Only `_1M` and `_1Y` workbooks exist; ten other period suffixes and three alternate formats return
404, and directory listing is refused with 403 (not bypassed). Data older than one year is therefore
not retrievable through this route at all. An empty result for an older window is a horizon limit,
never evidence that a station lacks data.

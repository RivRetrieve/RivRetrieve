# Australia BoM series identity and physical meaning

Settle scope and design for [Effort #645](https://github.com/RivRetrieve/RivRetrieve/issues/645)
(step 3 of the [provider-port guide](../../docs/maintenance/provider-ports.md))
for `au_bom`. This vision covers the physical meaning of the 18 products
settled in Effort #643/#644, resolves the two questions those earlier visions
deliberately left open, and hands off the duplicate-`ts_id` finding to its
actual implementation point. It does not implement `series.py` or change the
merged catalogue.

The port belongs to [Program #334](https://github.com/RivRetrieve/RivRetrieve/issues/334).
Builds on the merged
[source-access](2026-11-01-au-bom-source-scope-and-access.md) and
[catalogue](2026-11-02-au-bom-station-catalogue-and-metadata.md) visions.

## Timestamp anchoring: a period-start label, confirmed, not assumed

Checked live on 2026-11-03 across discharge, stage and water temperature, for
every one of the 18 admitted series, not just daily means: `DailyMax.24HR`
and `DailyMin.24HR` are stamped `00:00:00+10:00` on every one of 365 checked
days in 2025 — a pure period-start label, **not** the clock time of the
actual daily extreme. This is the opposite of `at_ehyd`'s `Monatsmaxima`,
which stamps the time of the extreme itself; the two sources are genuinely
different here, confirmed rather than assumed from precedent.

| Series | Anchor | Confirmed |
|---|---|---|
| `HourlyMean.HR` | Each hour's start, `+10:00` | 8,760 rows/year, one per hour |
| `DailyMean.24HR`, `DailyMax.24HR`, `DailyMin.24HR` | `00:00:00+10:00`, every day | 365/365 days checked |
| `DailyMean.09HR` | `09:00:00+10:00`, every day | Matches the `09:00`-to-`09:00` day definition `#334` already established |
| `MonthlyMean.CalMonth` | `00:00:00+10:00` on the 1st of the month | 12/12 months checked |
| `YearlyMean.CalYear` | `00:00:00+10:00` on 1 January | Checked |

**`day_definition`**: `24HR` series are midnight-to-midnight; `09HR` series
are 09:00-to-09:00 (both already named in #334; now confirmed as the actual
labeling convention, not just a documented rule).

## Time zone: resolvable now, more than step 1 could say

Step 1's vision left the time zone as a recorded unknown because BoM's site
text never names it (e.g. as AEST). That caution was about the *name*. The
*offset* is a different, resolvable fact: every timestamp checked across all
18 series explicitly carries `+10:00` — not inferred from station location,
stated directly in every row. Per `no_nve`'s precedent (`time_zone=known("+00:00", ...)`
from its explicit `Z` labels), `PhysicalFacts.time_zone` should be
`known("+10:00", <evidence>)` for every admitted series. This does not name
the zone (still unknown whether it's a fixed offset like AEST without DST,
or something else) and does not imply DST handling; it records only the
explicit label.

## Quality codes: present and named, uniformly

Confirmed on 2026-11-03: `Quality Code` and `Quality Code Name` are
requestable and present for every one of the 18 series, at every
aggregation level (checked hourly, daily, monthly, yearly), not just the
daily means #334 originally checked. Values match #334's findings
(`quality-A`/`-B`/`-C`/`-E`, and an unnamed `-1`). This vision does not design
the retrieval-time issue-emission mechanism (that is Effort #646's job,
alongside the duplicate-series question below) — it establishes that the
fact is available and named at the source, for `series.py` to carry forward.

## Resolving the non-`DMQaQc` question (deferred by #644's vision)

Checked live on 2026-11-03: `getTimeseriesList` for station `410730` with
`ts_unitname`/`ts_unitsymbol` returned for every discharge series.

- **`PR01QaQc.*` and `PR01ManQC.*` consistently report `megalitre per day`
  (`Ml/d`)** -- a different *quantity* from `DMQaQc.Merged`'s
  `cubic meter per second` (`cumec`), at every frequency checked
  (`AsStored.1`, `Hourly.HR`, `Daily.09HR`). This settles the question for
  this family: it is not a raw/checked duality of discharge comparable to
  `br_ana`'s `bruto`/`consistido` -- it is a different measurement
  (most plausibly a regulated water-take or extraction metering product
  reported as daily volume, not streamflow). **Out of scope for `au_bom`'s
  discharge products, not merely deferred.** It remains a candidate for a
  distinct future product (a volume-based quantity), not an alternate
  discharge series, and is not pursued further here.
- **`Received.*`, `Harmonised.*`, `ObsPOR.Merged`, `CombinedProv.Merged`,
  `DMmanQC.Manual` and `Derived.*` all report the same `cubic meter per
  second` unit as `DMQaQc.Merged`.** This is consistent with #334's
  original description ("processing stages of the same measurement"), and
  distinguishes them from `PR01*`. No BoM documentation stating this
  explicitly was found in this check -- the same-unit finding supports the
  "pipeline stage" reading over a `br_ana`-style user-facing duality, but
  does not prove it. **Recommendation: keep these excluded from `au_bom`'s
  admitted series**, on the basis that no evidence found so far shows BoM
  intends end users to choose between them (unlike `br_ana`'s `bruto`/
  `consistido`, which ANA explicitly names as two levels), while recording
  that this is a reasoned call, not a certainty, in case direct
  correspondence with BoM later says otherwise.

## `AsStored.1`: deferred to a separate catalogue-expansion Effort

The catalogue vision flagged `DMQaQc.Merged.AsStored.1` (confirmed present
for all three quantities) as a same-family candidate needing no new access
research. Adding it means adding new `product_id`s to the already-merged
catalogue (#644), not just establishing physical facts for the existing 18 --
out of this step's stated scope ("map the 18 admitted series"). Recommend a
small, separate future Effort scoped specifically to that addition, rather
than reopening #644 as part of #645.

## The duplicate-`ts_id` finding becomes a `series.py` requirement, not a question

Already recorded in the private research record and posted to this issue and
#646: 74 discharge, 79 stage and 4 water-temperature stations each carry two
distinct `ts_id` for the same admitted series, with no field distinguishing
them. This vision settles the design (it does not implement it): follow
`usgs_nwis`'s precedent exactly --

```python
series_id = stable_id("au_bom", station_no, namespace, ts_id)
```

-- so `series.py`'s `describe_series()` must be written to key identity on
the native `ts_id` from the start, not retrofitted after a single-series
assumption breaks. `variant` stays `None` for every `au_bom` series (BoM
names no distinction between a station's two `ts_id`s, unlike `no_nve`'s
versioned series or `br_ana`'s named consistency levels).

## Vertical datum for stage: still unknown

No further evidence found this pass. Stays unknown, per step 1's original
finding; `vertical_reference`/`vertical_datum` remain unestablished
`EvidenceFact`s in `PhysicalFacts`.

## Required handoff

- **Implementation (this Effort, a separate PR):** `series.py` with
  `describe_series()` building `PhysicalFacts` per the anchoring/time-zone/
  quality-code facts above, and `SourceSeries` keyed by `stable_id(...,
  ts_id)` per the duplicate-series design.
- **[Retrieval #646](https://github.com/RivRetrieve/RivRetrieve/issues/646):**
  Consumes `series.py`'s identities; designs the actual issue emitted for a
  quality code below `quality-A` (an informational issue naming the source
  code, analogous to `jp_mlit`'s `source_tentative`, not a judgement
  RivRetrieve itself makes); handles the transient `DatasourceError` retry
  behaviour already flagged in Effort #643.
- **A future, separate Effort:** adding `DMQaQc.Merged.AsStored.1` as new
  products, if wanted.

## Completion

Post a concise scope update on #645 referencing this vision. Keep #645 open
until the `series.py` implementation PR is merged, matching the
vision-then-implementation split used for Efforts #643 and #644.

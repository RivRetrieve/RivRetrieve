# Australia BoM source, scope and access

Complete [Effort #643](https://github.com/RivRetrieve/RivRetrieve/issues/643) with an
evidence-backed source-and-access handoff for the Australian hydrographic provider
(`au_bom`). This Effort covers source consolidation, scope definition, and bounded
access verification, not provider implementation. Verified completion of this
vision completes #643; publishing this vision alone does not.

The port belongs to [Program #334](https://github.com/RivRetrieve/RivRetrieve/issues/334).
Follow [provider-port step 1](../../docs/maintenance/provider-ports.md) and the
[evidence process](../../docs/maintenance/evidence.md). Keep all provider port work
on the dedicated `port/au-bom` branch until the full port is complete and approved
in final review [#650](https://github.com/RivRetrieve/RivRetrieve/issues/650).

## Settled scope

Publish `au_bom` using direct, unauthenticated `LiveStages` retrieval from the
Australian **Bureau of Meteorology**'s Water Data Online **KiWIS** service
(`https://www.bom.gov.au/waterdata/services?service=kisters&type=queryServices`),
the Commonwealth agency responsible for national hydrological monitoring under the
*Water Act 2007* and the *Meteorology Act 1955*.

This supersedes legacy `australia.py` and the comparable hydrodownloadR `AU_BOM`
adapter (see #334), neither of which filters series lookup on both `ts_name` and
`parametertype_name` together with hydrodownloadR's robustness, and neither of
which uses the `https://` endpoint consistently. Live re-verification on
2026-11-01 (recorded in the private research record) confirmed `http://` still
301s to `https://`, confirmed the exact series mapping at station `410730`
(`1573010`=discharge `DailyMean.24HR`, `1572010`=discharge `DailyMean.09HR`,
`1598010`=stage `DailyMean.24HR`, `380167010`=water temperature
`DailyMean.24HR`), and found a provisional-processing discharge series
(`PR01QaQc.Merged.DailyMean.09HR`) not described in #334, which stays out of
scope: `au_bom` admits only the `DMQaQc.Merged.*` quality-controlled family,
matching the legacy fetcher and #334's own analysis of the processing-stage
ladder.

Use `LiveStages` rather than `BulkStore`: KiWIS answers per station and per time
window through `getTimeseriesValues`, with no large archive file comparable to
Poland's or Canada's bulk publications, and the catalogue can be built from
`getStationList` filtered per parameter type rather than one unfiltered dump.

Include:

1. **Discharge (`discharge`, native `m³/s`, returned `m3/s`):** Daily mean
   (`DMQaQc.Merged.DailyMean.24HR` and `...DailyMean.09HR`), both published at the
   same ~5,710–5,784 stations network-wide (#334). Keep both as distinct source
   identities and selectable `variant`s; do not merge the midnight-anchored and
   09:00-anchored daily means into one series. Series lookup must filter on both
   `parametertype_name="Water Course Discharge"` and the exact `ts_name`, not on
   `ts_name` alone, to avoid the ambiguity hydrodownloadR's adapter does not
   resolve (ts_name alone can match a non-discharge series at some stations).
2. **Stage (`stage`, native `m`, source values already in m per the live CSV
   header's unit field; confirm exactly during step 3 rather than assuming the
   cm/m behavior of the legacy fetcher or hydrodownloadR's conditional
   divide-by-100):** Daily mean (`DMQaQc.Merged.DailyMean.24HR`) only. BoM
   publishes no `DailyMean.09HR` stage series anywhere in the network (#334);
   this absence is a source fact to preserve, not an implementation gap.
3. **Water temperature (`temperature`, native `°C`):** Daily mean
   (`DMQaQc.Merged.DailyMean.24HR`), published at ~2,846–2,849 stations (#334).

### Documented upstream options excluded from `au_bom`

- **Non-`DMQaQc` processing stages**, including `PR01QaQc.*`, `Received.*`,
  `Harmonised.*`, `ObsPOR.Merged`, `CombinedProv.Merged` and `DMmanQC.Manual`:
  each station carries roughly 25 further series names in these families (#334).
  They are processing stages of the same underlying measurement, not new
  variables; `au_bom` admits only the `DMQaQc.Merged.*` quality-controlled
  family. Record their existence in the research record without implementing
  them.
- **Hourly, monthly and yearly aggregations** (`HourlyMean.HR`,
  `MonthlyMean.CalMonth`, `YearlyMean.CalYear`) and **daily max/min**
  (`DailyMax.24HR`, `DailyMin.24HR`): published ready-made at the same stations
  as the daily mean (#334), but out of this port's scope. Defer them while
  recording their availability; a future Effort can extend `au_bom` to them
  without revisiting source access.
- **Other parameter types** available at the same stations or network-wide:
  electrical conductivity, pH, turbidity, storage volume/level, groundwater
  level, rainfall, evaporation and the long tail `getParameterTypeList` returns
  (145 types total, confirmed 146-row response including header on 2026-11-01).
  None of these are river discharge, stage or water temperature; excluded as
  out of RivRetrieve's river-gauge scope.
- **Groundwater bores and other non-gauge sites** mixed into the unfiltered
  station list (#334: "It includes groundwater bores and other sites, not only
  river gauges"). The catalogue Effort (#644) filters to stations exposing at
  least one admitted `DMQaQc.Merged.*` river series, analogous to how `at_ehyd`
  filtered lakes out of its `owf` station list.

## Access conditions and operational boundaries

- **Anonymous HTTPS access:** All `www.bom.gov.au/waterdata/services` requests
  respond over standard HTTPS `GET` without credentials, cookies or session
  tokens. `http://` 301s to `https://`; use `https://` directly.
- **The unfiltered `getStationList` request is unreliable.** Re-verification on
  2026-11-01 got `HTTP 500` (`DatasourceError`, "Error connecting to WDP") on 3
  consecutive attempts for the unfiltered station list, where #334 recorded a
  successful 139,864-row response on 2026-09-22. A `getStationList` request
  filtered by `parametertype_name` (confirmed working: 6,923 rows for `Water
  Course Discharge`, HTTP 200) is both the reliable route today and the one
  that naturally returns the river-gauge-relevant subset; the catalogue Effort
  (#644) should build on the filtered route, not the unfiltered dump, regardless
  of whether the unfiltered failure is permanent or transient.
- **`getTimeseriesValues` returns a transient `DatasourceError` under normal
  use.** The identical request (same `ts_id`, window and `returnfields`) 500'd
  on one attempt and then returned HTTP 200 on immediate retry, repeated across
  isolation tests that varied only the requested fields. This is not a
  parameter-shape bug; retrieval code (#646) needs retry-with-backoff on this
  exact failure shape, distinguished from a station or series that genuinely
  has no data for the requested window.
- **No documented rate limit from BoM itself.** hydrodownloadR's self-imposed
  3 requests/second is that adapter author's own choice, not a confirmed source
  rule; keep this as an unverified default rather than a cited BoM limit.
- **Quality codes** have published names and descriptions, retrievable via
  `returnfields=...,Quality Code Name,Quality Code Description` (confirmed
  working on 2026-11-01, consistent with #334: `quality-A`/`-B`/`-C`/`-E` and an
  unnamed `-1` code).

## Terms and attribution

Checked live on 2026-11-01, not inferred from hydrodownloadR's licence labels:

- BoM's general copyright page (`bom.gov.au/other/copyright.shtml`) states that,
  absent page-specific terms, content is for **personal or in-organisation use
  only** — no third-party redistribution, no commercial use — unless a page
  states a licence. Where BoM states a Creative Commons Attribution licence
  applies, its preferred attribution wording is: "Bureau of Meteorology, ©
  Commonwealth of Australia. Licensed from the Commonwealth of Australia under a
  Creative Commons Attribution 4.0 International licence."
- The Water Data Online portal page itself
  (`bom.gov.au/waterdata/`) states in its footer: "Unless otherwise noted, all
  material on this page is licensed under the **Creative Commons Attribution
  Australia Licence**" — the Australian-ported CC BY licence, not explicitly the
  4.0 International text the general copyright page prefers. These two BoM
  pages state licence text that does not match verbatim; record both exactly and
  let the documentation Effort (#649) reconcile which applies to API-retrieved
  observation data specifically, rather than assuming they are interchangeable.
- No separate Water Data Online API terms-of-service page was found. Direct,
  on-demand retrieval by end users, attributed to the Bureau of Meteorology, is
  consistent with both stated licence texts; no finding here licenses bulk
  redistribution of raw observation values.

## Recorded unknowns

Per step 1's guidance, these stay unknown rather than inferred:

- The named time zone for the stated `+10:00` offset (BoM's site text does not
  name it, e.g. as AEST, for this service).
- The vertical datum for stage values.
- Whether quality-code values carry any redistribution implication.
- Whether the 2026-11-01 unfiltered `getStationList` failure is permanent or a
  one-day incident (observed on a single day only).

## Required handoff

The handoff establishes downstream responsibilities across the port:

- **[Catalogue #644](https://github.com/RivRetrieve/RivRetrieve/issues/644):**
  Build the station catalogue from `getStationList` filtered per admitted
  parameter type (not the unreliable unfiltered route), reconcile station
  identity (`station_no`) and coordinates, and derive the river-gauge subset as
  stations exposing at least one admitted `DMQaQc.Merged.*` series.
- **[Series meaning #645](https://github.com/RivRetrieve/RivRetrieve/issues/645):**
  Map the four admitted series (`24HR`/`09HR` discharge, `24HR` stage, `24HR`
  water temperature) to distinct `SourceIdentity` and `PhysicalFacts` records;
  confirm the stage unit directly from a live response rather than assuming
  legacy `australia.py`'s or hydrodownloadR's conflicting cm/m behavior; verify
  the `+10:00` timestamp convention and quality-code propagation.
- **[Retrieval #646](https://github.com/RivRetrieve/RivRetrieve/issues/646):**
  Implement `fetch.py`/`parse.py` with retry-with-backoff on the transient
  `DatasourceError` failure shape identified above, distinguishing it from a
  genuinely empty window.
- **[Integration #647](https://github.com/RivRetrieve/RivRetrieve/issues/647),
  [verification #648](https://github.com/RivRetrieve/RivRetrieve/issues/648), and
  [user documentation #649](https://github.com/RivRetrieve/RivRetrieve/issues/649).**

## Completion

Maintain the continuing Australia research record in the private
`verification-evidence` repository
(`research/au-bom-source-access.md`, branch `research/au-bom-source-access`),
which retains exact request receipts (UTC time, HTTP status, byte size, SHA-256)
for every call made during this Effort. No observation value is stored in that
record or anywhere in this vision. Post a concise, disclosure-safe scope update
on #334 and a completion summary on #643 before closing #643. Keep #334 and
Efforts #644 through #650 open, and do not assign final review (#650) until
Efforts #643 through #649 are complete.

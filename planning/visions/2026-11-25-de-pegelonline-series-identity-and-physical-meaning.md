# Germany PEGELONLINE (`de_pegelonline`) — series identity and physical meaning

Associated issue:
[#1018](https://github.com/RivRetrieve/RivRetrieve/issues/1018)
("PEGELONLINE provider port: 3. Series identity and physical meaning").
Executing and verifying this vision completes #1018 only; it does not by
itself deliver retrieval ([#1019](https://github.com/RivRetrieve/RivRetrieve/issues/1019))
or engine integration ([#1020](https://github.com/RivRetrieve/RivRetrieve/issues/1020)).

Builds on the merged step-1 vision
([`2026-11-24-de-pegelonline-source-scope-and-access.md`](2026-11-24-de-pegelonline-source-scope-and-access.md),
#1025/#1030) and step-2 vision
([`2026-11-24-de-pegelonline-station-catalogue-and-metadata.md`](2026-11-24-de-pegelonline-station-catalogue-and-metadata.md),
#1031/#1042), both already implemented on `port/de-pegelonline`
(catalogue builder merged via #1041). The primary research record is issue
[#874](https://github.com/RivRetrieve/RivRetrieve/issues/874)
(live-verified 2026-11-17) plus the step-1/step-2 grills; this vision does
not reproduce that evidence beyond what's needed to act.

**Branch currency:** `port/de-pegelonline` was synced with `main` via
[#1045](https://github.com/RivRetrieve/RivRetrieve/pull/1045) specifically
before this step, to pick up the canonical ISO 8601 `Frequency` domain type
(#992/[#1032](https://github.com/RivRetrieve/RivRetrieve/pull/1032)) this
vision depends on. Confirm the implementing branch still has it
(`git merge-base --is-ancestor <PR #1032 merge commit> HEAD`) before
starting; if `main` has moved further, sync again first.

## Outcome

Give each of the five already-catalogued products (`W`, `Q`, `WT`, `TRM`,
`TRM_WT`) a defensible `SourceIdentity`/`PhysicalFacts` record using the
shared contracts in
[`source_series.py`](../../src/rivretrieve/_internal/source_series.py) and
[`provider_series.py`](../../src/rivretrieve/_internal/provider_series.py),
plus `AnnotationSchema` declarations
([`source_annotations.py`](../../src/rivretrieve/_internal/source_annotations.py))
for the non-identity fields. Follow `at_ehyd`'s bespoke-builder pattern
(`src/rivretrieve/_internal/providers/at_ehyd/series.py`) rather than the
one-size-fits-per-product `SeriesMapping` shortcut
(`cl_dga/series.py`'s simpler usage), since several facts here genuinely
vary per station for the same product. Create
`src/rivretrieve/_internal/providers/de_pegelonline/series.py` for this.

## Quantity and unit — settled, direct from the catalogue

`W`→`stage`, `Q`→`discharge`, `WT`→`water_temperature`, `TRM`→`stage` (own
identity, not folded into `W`), `TRM_WT`→`water_temperature` (own identity,
not folded into `WT`). This was already fixed in step 1/2; do not revisit
it here.

## Vertical reference on `W` (and `TRM`, which shares `W`'s gauge) — three branches, confirmed by live evidence

Branch purely on the native `unit` string, independently of everything
else, exactly as `at_ehyd/series.py` already does for its own two-way split
on `cm` vs `m ü.A`:

| Native `unit` | `source_unit` | `normalized_unit` | `vertical_reference` | `vertical_datum` |
|---|---|---|---|---|
| `cm` | `cm` | `m` (÷100) | `gauge_zero` | from `gaugeZero.unit` (e.g. `"m. ü. NN"`) when present, else `unknown` |
| `m+PNP` | `m+PNP` | `m` (×1, no scaling) | `gauge_zero` | from `gaugeZero.unit` |
| `m+NN` | `m+NN` | `m` (×1, no scaling) | `above_sea_level` | `"NN"` |

`m+PNP` and `cm` land on the **same** `vertical_reference` despite
different units and different scaling — this is the one place a naive
unit-only branch would need care; branch on unit first for scaling, then on
unit again (not on the resulting value) for the reference, as the table
above does. Never scale `m+NN` or `m+PNP` by ÷100 — that is the exact bug
present in the existing `wetterdienst` Python adapter.

## Frequency — per-series, from a real source field, using the canonical `Frequency` type

PEGELONLINE states `equidistance` (an integer, in minutes) directly on each
station's `timeseries` entry in `stations.json` — confirmed present in the
committed fixture (`tests/test_data/de_pegelonline_stations.json`:
`"equidistance": 15` on a sample `W` entry). This is a genuine per-station,
per-series source fact, not something to infer: map it straight through
`canonicalize_frequency()`
(`src/rivretrieve/_internal/frequency.py`) — `1`→`PT1M`, `5`→`PT5M`,
`10`→`PT10M`, `15`→`PT15M`, `60`→`PT1H` (canonicalizes automatically).

Per #874's live tabulation (2026-11-17), this genuinely varies by station
for the same product — e.g. `W`: `15 min` (502), `1 min` (225), `10 min`
(10), `5 min` (1); `WT`: `60 min`, `1 min`, `15 min`, `5 min` all occur;
**77 stations mix intervals across their own parameters** (e.g.
`HOFKIRCHEN` reports `W`/`Q` every 15 min but `WT` every 60 min). This is
exactly why the bespoke-builder pattern is required instead of
`SeriesMapping`'s one-frequency-per-product shortcut — `PhysicalFacts` is
already per-series, so this needs no new mechanism, just the per-station
code path.

**`TRM`/`TRM_WT` frequency stays `not_established`.** Their *Terminwerte*
readings are 1–3 scheduled fixed-local-clock-time readings per day (varying
in count by station), not a regular elapsed or calendar interval — they do
not fit the `Frequency` grammar's `PT_H`/`P_D`/`P_M` families at all. Do
not force a value; record why in the fact's evidence.

## Statistic — stays `unknown`, confirmed not a judgment call

PEGELONLINE's own documentation never states whether a 15-min or 60-min
reading is an instantaneous sample or an interval mean (confirmed across
both the REST API docs and the SOS service's bare `"Einzelwert"` label,
per #874 §4.3). This was already settled in step 1 and carried through
step 2's catalogue (`statistic = "unknown"`); do not infer a value here
either.

## Missing values — per series' own parser, no shared mechanism

`W`/`Q`/`WT`: missing sensor slots are **absent rows** (no JSON `null`).
`TRM`/`TRM_WT`: missing slots are published as explicit JSON **`null`**
("*Fehlwerte werden als null publiziert*"). Each series' own parser handles
its own convention; use the existing "unmeasured slot" concept in
`ObservationAnnotationTable` (`source_annotations.py`, `unmeasured_count`)
for `TRM`/`TRM_WT`'s nulls. Never treat a reading of `0.0` as missing on
any series — `WT = 0.0 °C` and low/negative coastal `W` in `cm` are valid
physical readings, and `TRM`'s `difference = 0.0` is equally valid.

## Annotations

Declare these as `AnnotationSchema` entries, `reference_url =
"https://www.pegelonline.wsv.de/webservice/dokuRestapi"`:

- `longname` (SERIES scope, `String`) — distinguishes e.g. `ABFLUSS` vs
  `ABFLUSS_ROHDATEN` variants of the same shortname.
- `comment_short` / `comment_long` (SERIES scope, `String`) — the
  catalogue-time outage/malfunction note (e.g. `"Ausfall"`) some
  timeseries carry. Honest only "as of catalogue-check-time," same
  existing limitation every SERIES-scope catalogue fact already carries
  (`InventorySnapshot.catalogue_check_date`); not a new caveat to invent.
- `difference` (OBSERVATION scope, `Float64`, on `TRM`/`TRM_WT` only) — the
  scheduled reading's change from the previous day's scheduled value. This
  will be the first `Float64` annotation in the codebase; unremarkable —
  `Float64` is already a supported scalar dtype
  (`source_annotations.py`'s `_SUPPORTED_SCALAR_DTYPES`), just not yet used
  by an existing provider.

## Explicitly out of scope / excluded

- **PEGELONLINE's live `currentMeasurement.stateMnwMhw`/`stateNswHsw`
  status codes are not captured at all.** Decided during this vision's
  discussion: the field describes only the single most-recent live
  reading, disconnected from any specific retrievable historical
  timestamp — it fits neither SERIES scope (not a stable per-series fact)
  nor OBSERVATION scope (never co-located with the historical rows a user
  actually retrieves from `measurements.json`). It is also non-reproducible
  live state, not a property of any data point RivRetrieve serves. A user
  can derive a low/normal/high classification themselves from the stage
  value and the station's own `characteristicValues`, which are already in
  scope.
- `WV`, `F`, `T` have no products and therefore no series identities here
  — already excluded in step 1/2.
- Retrieval mechanics (explicit `start`/`end`, `.json`-only, rolling-window
  empty-response handling) are [#1019](https://github.com/RivRetrieve/RivRetrieve/issues/1019)'s
  job, not this vision's.
- `day_definition`/`timestamp_anchor` facts: PEGELONLINE's raw `W`/`Q`/`WT`
  are sub-daily regular readings, not daily/monthly aggregates (step 1
  confirmed **no daily/monthly aggregated series exist anywhere on
  PEGELONLINE** — only long-term static multi-year scalar summaries in
  `characteristicValues`, which are not observation series). These facts
  likely stay `not_established` for everything in this provider; confirm
  during implementation but do not invent a day boundary or anchor that
  isn't source-stated.

## Completion evidence and boundaries

Verify quantity, unit, and vertical-reference mappings against a fresh live
fetch (not just the committed fixture) before considering this complete,
per the provider-port guide's step 3. Continue the private research record
(`research/de-pegelonline-source-access.md` in
[verification-evidence](https://github.com/RivRetrieve/verification-evidence))
rather than starting a parallel history. Run `uv run pytest
tests/test_de_pegelonline_*.py --logic-only` plus the full suite before
calling this done, and confirm no regression in the already-merged
catalogue tests.

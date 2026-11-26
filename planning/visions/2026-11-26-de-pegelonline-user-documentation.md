# Germany PEGELONLINE (`de_pegelonline`) — user documentation

Associated issue:
[#1022](https://github.com/RivRetrieve/RivRetrieve/issues/1022)
("PEGELONLINE provider port: 7. User documentation"). Executing and
verifying this vision completes #1022, the final step of the de_pegelonline
port (#1017–#1022, tracked under #874).

Builds on steps 1–6, all merged into `port/de-pegelonline`: step 5
(provider integration, [#1077](https://github.com/RivRetrieve/RivRetrieve/pull/1077))
registered `de_pegelonline` as a built-in provider, and step 6
(verification, [#1081](https://github.com/RivRetrieve/RivRetrieve/pull/1081))
confirmed it behaves correctly against genuine recorded interactions.

## Outcome

A `docs/providers/de_pegelonline.md` page, per [step 7 of the provider-port
guide](../../docs/maintenance/provider-ports.md#7-user-documentation): users
can understand what they can retrieve and its real limits without
reconstructing the investigation. Follow [documentation
guidance](../../docs/AGENTS.md) and the shared shape in
[`docs/providers/`](../../docs/providers/) — reuse it verbatim rather than
inventing a new one. `docs/providers/lt_lhmt.md` is the closest structural
template (another single-endpoint `LiveStages` provider with no archive
member selection); `docs/providers/ch_foen.md` is useful precedent for
wording a vertical-datum caveat carefully.

## A correction to carry into the writing

Issue #1022 asks to explain "the mixed per-issuer provenance for the
mirrored foreign/non-WSV stations." Check the actual settled fact before
writing this section: PEGELONLINE mirrors 39 non-WSV stations (26 foreign
cross-border gauges across the Netherlands, Austria, Czechia and
Switzerland; 13 domestic non-WSV German institutions), but licensing is
**not** mixed. Step 1's vision
(`planning/visions/2026-11-24-de-pegelonline-source-scope-and-access.md`,
"Terms and attribution" section) corrected an earlier reading on
2026-11-24: PEGELONLINE's terms page states `DL-DE->Zero-2.0` as one
provider-level licence over everything the site redistributes, with no
origin-based exception. All 787 stations carry this one licence alike. An
earlier draft of that section had concluded the opposite (per-issuer
licensing, with the 13 domestic non-WSV stations' terms left "unknown") and
was explicitly superseded in the vision itself — do not resurrect the
superseded reading.

What genuinely varies is *who operates* each gauge, not who licenses the
data. Separately, the native `agency` field that would identify a station's
operator has no declared metadata role (`src/rivretrieve/_internal/providers/de_pegelonline/origins.py`'s
`STATION_METADATA_FIELDS`) and is not exposed through either `rr.metadata()`
view (`summary` or `source`) — confirmed by reading `metadata()`'s
implementation in `src/rivretrieve/_internal/discovery.py`, which builds the
`source` view strictly from the packaged `station_metadata.parquet` file,
itself built only from the declared role-mapped fields (`station_name`,
`water_body_name`, `elevation`). So this is a real, statable limitation:
users cannot currently query which stations are non-WSV through
RivRetrieve itself.

Write this as one concise paragraph: who else PEGELONLINE mirrors (named
generally — a modest number of German institutions plus a few neighboring
countries' agencies — not enumerated station-by-station), the uniform-licence
fact stated plainly, and the `agency` field's non-exposure as a stated
limitation. Link the private research record (issue #874) for the full
39-station breakdown rather than reproducing it, per step 7's own
instruction not to publish the whole investigation.

## `TRM`/`TRM_WT` wording

The issue's own text calls `TRM` a "variant." It is deliberately not
RivRetrieve's `variant` concept (confirmed earlier this port, and already
settled architecture from step 2/3): `TRM`/`TRM_WT` are separate
`product_id`s from `W`/`WT`, because they have no regular reporting interval
at all (scheduled "Terminwerte" readings, 1–3 fixed local-clock-time
readings/day) — confirmed directly from the native fixture, `W`/`WT` report
on a fixed continuous interval while `TRM`/`TRM_WT`'s own `equidistance` is
always `None`. The shared "What you can retrieve" table header literally
includes a `variant` column (`` Source field / `variant` ``); do not use the
word "variant" in prose next to `TRM`/`TRM_WT` in a way that implies that
column applies to them. Describe them as their own products, not a
`variant` of `W`/`WT`, with that one-sentence mechanism as the reason. Give
each its own table row, with its native shortname (`TRM`, `TRM_WT`) in the
`Source field` column, not the `variant` column. This mirrors established
precedent elsewhere in the codebase for the same underlying reason
(`ba_fhmzbih`, `th_thaiwater`, `fi_syke`'s `_reported`-suffixed products:
temporal structure is part of a product's identity, not a `variant` axis).

## What else the page needs to explain

Per the issue and step 7's own checklist, cover (concisely, each a
paragraph or a table row, not a research reproduction):

- **The rolling ~31-day window.** A request for dates older than PEGELONLINE's
  rolling retention returns `HTTP 200` with an empty result (`OutcomeStatus.EMPTY`),
  not a failure — this is rolling retention, not station inactivity or a dry
  riverbed. (`src/rivretrieve/_internal/providers/de_pegelonline/fetch.py`'s
  module docstring and `tests/test_de_pegelonline_fetch.py`'s
  `test_http_200_empty_array_outside_retention_is_empty_not_error` already
  establish this exact behavior; `tests/test_de_pegelonline_observations.py`'s
  future-window test is a genuine recorded instance of it.)
- **The `cm`/`m+NN`/`m+PNP` vertical-datum distinction on `W`/`TRM`.** Three
  native units: `cm` (relative to the station's own gauge zero,
  *Pegelnullpunkt*; RivRetrieve converts ÷100 to metres), `m+NN` (already in
  metres, absolute elevation above sea level, *Normalnull* — not rescaled),
  `m+PNP` (already in metres, but still relative to gauge zero, not sea
  level). `source_unit` keeps the published unit; follow `ch_foen.md`'s
  cautious wording style (what a label is relative to vs. which named datum
  applies) rather than overclaiming precision the source itself doesn't
  state. Do not enumerate every observed `gaugeZero.unit` string
  (`"m. ü. NHN"`, `"m. ü. NN"`, `"m ü. A."`, `"mü.M."`) in the page itself —
  mention that this per-station datum text is preserved as source evidence,
  without listing every variant spelling.
- **The "What you can retrieve" table**, exact shared header
  (`` | Quantity filter | Source field / `variant` | Frequency | Statistic | Source unit | Returned unit | ``),
  one row per product (`W`→stage, `Q`→discharge, `WT`→water_temperature,
  `TRM`→stage, `TRM_WT`→water_temperature). `Frequency`/`Statistic` are
  `Unknown` for every row (matching `ba_fhmzbih`'s established precedent for
  filling, not dropping, a column that doesn't obviously apply) — de_pegelonline's
  own catalogue declares `frequency: "unknown"` uniformly, since actual
  per-station reporting intervals vary (`15 min` at most `W`/`Q` stations,
  but not all; see `series.py`) and cannot be pinned at the catalog level.
- **Who measures and publishes.** WSV/GDWS operates the federal waterway
  gauge network; PEGELONLINE (ITZBund-hosted, EES GmbH-developed) is its
  near-real-time publication platform. Link the agency documentation
  (`https://www.pegelonline.wsv.de/webservice/ueberblick`,
  `https://www.pegelonline.wsv.de/webservice/guideRestapi`).
- **A verified live example.** Retrieve a short window of one product at one
  station (e.g. discharge at a real, well-populated station such as
  HOFKIRCHEN) through the real public API, matching `lt_lhmt.md`'s worked
  example shape (code, output, a dated "checked on" note). Do not present
  this success as proof of continuous coverage.
- **Terms and citation.** `DL-DE->Zero-2.0` (Datenlizenz Deutschland – Zero
  – Version 2.0) permits unrestricted use, modification and redistribution
  without mandatory attribution. Quote the exact German sentence already
  established in `origins.py`'s `build_acquisition_provenance()` docstring
  and `catalogue/provenance.json`, with an unofficial English gloss, matching
  `lt_lhmt.md`'s treatment of non-English source text.

## Explicitly out of scope / excluded

- Any change to `de_pegelonline`'s implementation. This step documents
  existing, already-verified behavior.
- The deferred `test_native_composition_root_rebuilds_committed_artifacts_without_network`
  extension (named and deferred in step 6, #1081) — unrelated to this step,
  not reopened here.
- Enumerating the full 39-station non-WSV/foreign breakdown or every observed
  `gaugeZero.unit` spelling in the page itself — link the research record
  (issue #874) instead.

## Completion evidence and boundaries

- `docs/providers/de_pegelonline.md` exists, following the shared shape,
  reviewed against `docs/providers/lt_lhmt.md` and the "What you can
  retrieve" table convention.
- The worked example in the page is independently re-run against the live
  API at write time and its output matches what's shown.
- Linked from the three places every other provider page is indexed from:
  `docs/README.md`'s provider list, `mkdocs.yml`'s nav (alphabetically,
  between `cz_chmi` and `dk_vanda`), and `docs/station-metadata.md`'s
  "fields by provider" table (between the `cz_chmi` and `dk_vanda` rows,
  matching `STATION_METADATA_FIELDS` from step 2: `longname`, `shortname`
  under station name; `water_longname`, `water_shortname` under water body
  name; `—` under drainage area (not published); `w_gauge_zero_value` (m)
  under elevation).

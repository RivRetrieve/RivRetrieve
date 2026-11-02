# Austria eHYD retrieval behavior

Deliver evidence-backed, tested observation retrieval for Austria's federal
hydrographic provider, `at_ehyd`, under
[Effort #615](https://github.com/RivRetrieve/RivRetrieve/issues/615) and
[Program #525](https://github.com/RivRetrieve/RivRetrieve/issues/525) without
silently dropping rows, fabricating coverage across unpublished years, or merging
distinct publication routes. Completing the research updates, retrieval stages,
and source/synthetic verification described here completes #615; publishing this
vision alone does not complete the Effort. Work targets `port/at-ehyd` and leaves
`main` unchanged until
[final review #619](https://github.com/RivRetrieve/RivRetrieve/issues/619). Keep
`at_ehyd` registered as `CatalogueOnly()` during #615; public `LiveStages`
activation belongs to [#616](https://github.com/RivRetrieve/RivRetrieve/issues/616).

## Scope and established context

Build on the delivered [station catalogue (#613)](2026-10-31-at-ehyd-offline-station-catalogue.md)
and [series definitions (#614)](2026-11-01-at-ehyd-series-identity-and-physical-meaning.md)
at reviewed `port/at-ehyd` revision `69586a6cb6eec5e9290dce0ad93e1f204e89690a`.
Support anonymous HTTP `GET` acquisition across all `11` canonical river products:

- **`owf` yearbook-validated CSV series (`ehyd.owf`, `7` products):**
  `owf_abfl_tagesmittel`, `owf_abfl_monatsminima`, `owf_abfl_monatsmaxima`,
  `owf_wasserst_tagesmittel`, `owf_wasserst_monatsminima`,
  `owf_wasserst_monatsmaxima`, and `owf_wassertemp_monatsmittel`.
- **`pegelBgis` rolling sub-daily telemetry (`ehyd.pegel_bgis.*`, `2` products):**
  `pegel_bgis_abfluss` and `pegel_bgis_wasserstand`.
- **`pegelLongterm` current-year daily comparison JSON (`ehyd.pegel_longterm.*`, `2` products):**
  `pegel_longterm_abfluss` and `pegel_longterm_wasserstand`.

Do not splice `Pegel Aktuell` telemetry onto `owf` historical series, reconstruct
unpublished `2024` records, collapse routes, or fall back at runtime to the ~97 MB
national `ehyd_messstellen_all_owf.zip` archive. Continue the existing
[private research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/at-ehyd-source-access.md)
following [provider-port step 4](../../docs/maintenance/provider-ports.md#4-retrieval-behavior).

## Acquisition behavior and runtime file resolution

None of the three eHYD endpoints accepts date-range query parameters: every
endpoint returns a source-fixed window (`owf` full historical record, `pegelBgis`
rolling ~7-day telemetry, `pegelLongterm` current calendar year). Declare
`WindowDeclaration(WindowGranularity("none"), WindowRenderingVocabulary.NONE, StopConvention.INCLUSIVE)`
across all `11` products and let the shared engine clip returned observations to
the caller's `RequestedWindow`.

For `owf` CSV acquisition, `fileNr` indices in
`GET https://ehyd.gv.at/services/MessstellenExtraData/owf?id={hzbnr}&file={fileNr}`
vary per gauge depending on which series a station publishes (`Q-Tagesmittel`
appears at `file=2`, `3`, `4`, or `5` across stations). Group the `7` `owf`
products in `shared_acquisition_products` so each station issues one prerequisite
`GET https://ehyd.gv.at/services/Messstellen/info?hzbnr={hzbnr}` call per fetch
transaction, resolves `<Prefix>-<station>.csv` entries from `dl_mstfiles.data.fileData`
(`msttyp == "owf"`), and fetches each matching CSV linked via
`prerequisite_acquisition_ids`. Independent sibling `owf` downloads must survive
if one `owf` CSV request fails or returns a corrupt payload.

Acquire sub-daily telemetry from
`GET https://ehyd.gv.at/services/Diagram/pegelBgis?hzbnr={hzbnr}` and current-year
daily telemetry from
`GET https://ehyd.gv.at/services/Diagram/pegelLongterm?hzbnr={hzbnr}` as separate
route groups so cached `owf` history does not couple to live telemetry calls. Reuse
shared transport retry and safe `GET` replay mechanics without adding provider-local
retry loops or schedulers.

## Observation normalization, gaps, and route boundaries

- **`owf` CSV preamble verification and value decoding:** Decode Windows-1252
  (`cp1252`) CSV payloads, verify `HZB-Nummer:` and `Exportzeitreihe:` in the
  preamble against the requested `(station, product)`, parse decimal-comma floats,
  and preserve legitimate zero flow, negative river stages below `Pegelnullpunkt`
  (`cm` converted to `m` via `admission`), negative water temperatures (`degC`),
  exact `DD.MM.YYYY HH:MM:SS` wall-clock timestamps (including non-midnight
  commissioning/anchor times and December 31 `24:00` monthly extrema stamped
  `01.01.YYYY 00:00:00`), and station `207340`'s `T,1` `W-Monatsminima` facts
  (`frequency` and `temporal_support` `not_established`).
- **`'Lücke'` state-transition sentinels:** Validate timestamps on every `'Lücke'`
  line after `Werte:`. Treat `Invalid; Lücke` bodies (`WT-Monatsmittel` on `208058`
  and `213041`) as `0` observation rows (`OutcomeStatus.EMPTY` where covered). Omit
  `'Lücke'` transition markers from numeric `Rows` so sparse multi-year gap markers
  (such as `01.01.1977` followed by `01.01.2024` on `201806`) are not misread as
  single missing timestamps and trailing closing-boundary `t_end; Lücke` lines on
  interval series do not synthesize extra timestamps. When interior `'Lücke'` gap
  transitions occur before the final closing boundary, emit an aggregated
  `info`-severity `source.gap_marker` `Issue` recording their count and boundary
  labels.
- **`pegelBgis` JSON:** Parse `categories` (`YYYY-MM-DD HH:MM:SS` in fixed
  `UTC+01:00` / `+01:00` `MEZ`) and `data`, preserving published `null` entries
  inside the rolling window while excluding scalar snapshot fields (`wert`, `zp`)
  and static thresholds (`niedrigwasser`, `mittelwasser`, `erhmittelwasser`,
  `hochwasser1..3`).
- **`pegelLongterm` JSON:** Parse `current_value` on `points_in_time`
  (`YYYY-MM-DD`, `time_zone="unknown"`, `ClippingAxis.CALENDAR_DATE`), preserving
  interior `null` days up to the last non-null observation of the year, trimming
  the trailing future-year `null` padding tail, and excluding `last_year_value` and
  all five 30-year climatology arrays (`min_data`, `max_data`, `mit_data`,
  `p5_data`, `p95_data`). Keep `statistic` `not_established` pending publisher
  confirmation even where empirical comparison against `pegelBgis` matches
  unweighted `00:00..24:00 MEZ` daily means.

## Coverage, cache reuse, and failure classification

- **Bounded `owf` interval coverage and the `2024` gap:** When `Exportzeitraum:`
  establishes finite closed-open `[t_start, t_end]` bounds (in either `[t0,t1]` or
  `t0; bis ;t1` header form, expanded to include `min(numeric_ts)` on commissioning
  headers such as `204032` and `t_end` when a December 31 `24:00` extreme is stamped
  at `t_end`, otherwise `t_end - 1 us`), emit `coverage="interval"` over that
  published span and disjoint `OutcomeStatus.UNRESOLVED` outcomes on any requested
  pre-`t_start` or post-`covered_end` tail. Historical queries within the published
  yearbook span therefore reuse the local store offline (`cache="reuse"`), whereas
  requests extending into `2024..present` keep the unpublished post-yearbook tail
  `UNRESOLVED` rather than caching `2024` as permanently empty. When
  `Exportzeitraum:` uses open tokens (`Datenbeginn`, `+-Infty`, `Invalid`), fall
  back to `coverage="observations"`.
- **Rolling and current-year telemetry coverage:** Emit `coverage="observations"`
  with explicit `observation_keys` on `pegelBgis` and `pegelLongterm` so the local
  store accumulates overlapping rolling snapshots without claiming unseen historical
  intervals are empty, and failed refreshes preserve held rows.
- **Outcome boundaries:**
  - `OutcomeStatus.UNRESOLVED`: live/telemetry or open-bound responses that establish
    no durable interval coverage (`0`-byte HTTP `200` on `pegelBgis`/`pegelLongterm`
    such as `201087`, `212167`, `215541`; empty `pegelLongterm` JSON skeleton on
    `213801`; `valCount: 0` with `categories: null, data: null` on `209288`; all-`null`
    current-year `pegelLongterm` `current_value` on `212167`; or open-bound
    `Invalid; Lücke` on `208058` and `213041`).
  - `OutcomeStatus.NO_MATCH`: `Messstellen/info` lacks a matching `owf` `fileNr`
    (including `[[]]` on telemetry-only stations) or a `Pegel Aktuell` endpoint
    publishes the opposite parameter (`Abfluss` vs `Wasserstand`).
  - `OutcomeStatus.UNSUPPORTED`: cleared or unsupported published units
    (`Einheit: ;[]` on `203539`, `204388`, `211078`; cleared `einheit: ""`; or
    `einheit: "m ü.A"` on elevation-referenced gauges such as `210120`).
  - `OutcomeStatus.FAILED`: transport failures, `0`-byte HTTP `200` on an
    advertised `owf` `fileNr`, CSV `HZB-Nummer` or `Exportzeitreihe` mismatches, or
    corrupt `cp1252` / JSON structures, isolated per series so sibling downloads
    remain intact.

## Delivery and acceptance

Deliver `src/rivretrieve/_internal/providers/at_ehyd/{config,fetch,parse}.py` (with
shared preamble support in `series.py`), synthetic unit and assembled internal
driver/store tests in `tests/test_at_ehyd_retrieval.py`, recorded replay checks in
`tests/test_at_ehyd_retrieval_recorded.py`, and private source-certification
updates in `RivRetrieve/verification-evidence` against the already-retained
collections `at_ehyd-access-2026-10-31-v1` and `at_ehyd-catalogue-2026-10-31-v1`.
Keep `at_ehyd/declaration.py` as `CatalogueOnly()` until #616.

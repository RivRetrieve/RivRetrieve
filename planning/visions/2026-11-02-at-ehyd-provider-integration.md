# Austria eHYD provider integration

Make Austria eHYD observations available through RivRetrieve's public selection,
retrieval, and cache interfaces under `at_ehyd`. Deliver the agreed scope for
[Effort #616](https://github.com/RivRetrieve/RivRetrieve/issues/616) and
[Program #525](https://github.com/RivRetrieve/RivRetrieve/issues/525).
Completing this integration and its applicable verification completes #616;
publishing this vision alone does not.

Work targets `port/at-ehyd` and leaves `main` unchanged until
[final review #619](https://github.com/RivRetrieve/RivRetrieve/issues/619)
approves merging. Full-provider verification remains in
[#617](https://github.com/RivRetrieve/RivRetrieve/issues/617), and the dedicated
provider documentation page remains in
[#618](https://github.com/RivRetrieve/RivRetrieve/issues/618). Those separate
Efforts do not defer checks required to establish correct public integration.

## Build on the delivered provider work

At target `port/at-ehyd` revision `2297b7d0c3e3db351385434f264051ba08f2d9d0`,
[#613](https://github.com/RivRetrieve/RivRetrieve/issues/613),
[#614](https://github.com/RivRetrieve/RivRetrieve/issues/614), and
[#615](https://github.com/RivRetrieve/RivRetrieve/issues/615) are complete:

- The packaged catalogue supports offline discovery of `746` canonical river
  station identities (`744` with selectable river series across `11` products,
  and `2` river gauges publishing only excluded sediment series).
- `providers/at_ehyd/series.py` defines distinct source identities and
  established physical facts across `ehyd.owf`, `ehyd.pegel_bgis.*`, and
  `ehyd.pegel_longterm.*`, keeping unresolved facts explicit.
- `providers/at_ehyd/{config,fetch,parse}.py` implement route coordinates,
  source-fixed windows, station-scoped `Messstellen/info` prerequisite lookup,
  isolated route acquisition, `cp1252` CSV and JSON parsing, bounded
  `Exportzeitraum` interval coverage, and rolling telemetry observation keys.
- `providers/at_ehyd/declaration.py` still declares `CatalogueOnly()`, leaving
  public observation retrieval disabled.

Use the delivered
[catalogue](2026-10-31-at-ehyd-offline-station-catalogue.md),
[series](2026-11-01-at-ehyd-series-identity-and-physical-meaning.md), and
[retrieval](2026-11-02-at-ehyd-retrieval-behavior.md) contracts and their
retained evidence. Follow
[provider-port step 5](../../docs/maintenance/provider-ports.md#5-provider-integration)
and continue the existing
[private eHYD research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/at-ehyd-source-access.md).
Do not restart completed research or create a parallel evidence archive.

## Deliver working public retrieval

Connect `config()`, `window_declarations()`, `SHARED_ACQUISITION_PRODUCTS`,
`fetch`, and `parse` to `LiveStages` in
`src/rivretrieve/_internal/providers/at_ehyd/declaration.py` with
`required_credentials=()`. Reuse shared discovery, transport, unit conversion,
clipping, assembly, receipt recording, and local store machinery across all `11`
agreed river products:

- **`owf` validated yearbook CSV routes (`7` products):**
  `owf_abfl_tagesmittel`, `owf_abfl_monatsminima`, `owf_abfl_monatsmaxima`,
  `owf_wasserst_tagesmittel`, `owf_wasserst_monatsminima`,
  `owf_wasserst_monatsmaxima`, and `owf_wassertemp_monatsmittel`, grouped in
  `shared_acquisition_products` so multi-product `owf` fetches at one station
  issue a single `Messstellen/info` lookup while isolating per-file failures.
- **`pegelBgis` rolling sub-daily telemetry (`2` products):**
  `pegel_bgis_abfluss` and `pegel_bgis_wasserstand`, grouped separately from
  `owf` and `pegelLongterm`.
- **`pegelLongterm` current-year daily comparison JSON (`2` products):**
  `pegel_longterm_abfluss` and `pegel_longterm_wasserstand`, exposing only
  `current_value` on `points_in_time`.

Keep validated `owf` exports and live `Pegel Aktuell` routes separate even at
the same gauge. Preserve canonical `hzbnr` station IDs and distinct series
identities. Do not splice telemetry onto `owf` history, synthesize unpublished
`2024` values, select a preferred series when multiple discharge or stage routes
match a broad query, or expose lakes, springs, river sediment series, scalar
telemetry snapshots, static warning thresholds, `last_year_value`, or 30-year
climatology envelopes.

Follow the standard `rr.fetch(..., start=..., end=...)` contract without adding
new public options, custom rate-limiter infrastructure, or provider-specific
issue suppression. Update shipped capability summaries
(`docs/_generated/reference-tables.md`), the selectable station coverage map
(`docs/scripts/coverage_map.py` and `docs/assets/coverage-map.png`), and the
root `README.md` provider table (`744` selectable stations out of `746` retained
river gauges, `Open` access) so repository-wide capability contracts reflect
live `at_ehyd` retrieval while keeping the dedicated `docs/providers/at_ehyd.md`
guide scoped to #618.

## Preserve source meaning, provenance, and cache semantics

Public retrieval must preserve the established series facts, absence states, and
store invariants end-to-end:

- Convert stage from `cm` to `m` (`factor=0.01`, `vertical_reference="gauge_zero"`)
  and `m ü.A` / `m ü.A.` (`Meter über Adria`, `factor=1.0`, `vertical_reference="above_sea_level"`),
  preserving negative stages below `Pegelnullpunkt`, zero discharge, and
  negative water temperatures (`°C` to `degC`).
- Preserve row time zones (`"unknown"` on `owf` and `pegelLongterm`; `"+01:00"`
  on `pegelBgis`) and calendar-date clipping on `pegelLongterm` without
  fabricating midnight clock precision or daylight-saving shifts.
- Enforce physical-predicate selection honestly: querying
  `frequency="daily", statistic="mean"` selects `owf` daily means while
  withholding `pegelLongterm` (`statistic` is `not_established`), and querying
  `frequency="monthly", statistic="min"` on station `207340` withholds its
  `T,1` `W-Monatsminima` export.
- Distinguish published `null` values (`pegelBgis` / interior `pegelLongterm`),
  omitted `'Lücke'` state-transition markers (`source.gap_marker` info issues),
  trimmed future-year `pegelLongterm` `null` tails, `NO_MATCH`, `UNSUPPORTED`
  (`Einheit: ;[]`, cleared `einheit`, or unrecognized unit strings), `UNRESOLVED` (`0`-byte or empty
  `Pegel Aktuell` responses and unpublished post-yearbook `2024..present`
  intervals), and `FAILED` requests.
- Reuse cached `owf` observations offline (`0` network requests) when queries
  fall inside the bounded `Exportzeitraum` span, keep `2024..present`
  `UNRESOLVED` so unpublished years are never cached as empty, accumulate
  rolling `pegelBgis` and `pegelLongterm` snapshots across refreshes, preserve
  held rows when refreshes fail, and attach verified `CC BY 4.0` license and
  `Datenquelle: ehyd.gv.at` attribution to `ObservationResult.provenance`.

## Verification and handoff

Verify observable behavior through public selection and retrieval alongside
updated repository contracts:

- Offline discovery (`rr.find`, `rr.pick`, `rr.series`, `rr.metadata`,
  `rr.describe`) remains network-free after `LiveStages` registration.
- Public synthetic integration tests (`tests/test_at_ehyd_public.py`) cover all
  `11` products without credentials, shared-acquisition request batching, unit
  conversions, physical-predicate filtering, provenance statements, `cache`
  modes (`reuse`, `bypass`, `refresh`), held-data survival across failed
  refreshes, partial sibling survival, and `on_issue` (`raise`, `warn`,
  `ignore`) behavior.
- Genuine recorded public replay (`tests/test_at_ehyd_recorded_public.py`)
  exercises retained `Messstellen/info`, `owf`, `pegelBgis`, and `pegelLongterm`
  HTTP captures through public `rr.find` and `rr.fetch`, comparing returned
  rows against independently parsed publisher bytes without embedding private
  response literals in public code.
- Repository-wide reference, boundary-probe obligation, coverage-map, and
  wheel/sdist packaging checks pass alongside private source-certification
  checks under the [evidence process](../../docs/maintenance/evidence.md).

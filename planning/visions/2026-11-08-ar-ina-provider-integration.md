# Argentina INA Alerta5 provider integration

Make Argentina Instituto Nacional del Agua (INA) Alerta5 observations available
through RivRetrieve's public selection, retrieval, and cache interfaces under
`ar_ina`. Deliver the agreed scope for
[Effort #717](https://github.com/RivRetrieve/RivRetrieve/issues/717) and
[Program #348](https://github.com/RivRetrieve/RivRetrieve/issues/348),
following [provider-port step 5](../../docs/maintenance/provider-ports.md#5-provider-integration).
Completing this integration and its applicable verification completes #717;
publishing this vision alone does not.

Work targets `port/ar-ina` and leaves `main` unchanged until
[final review #720](https://github.com/RivRetrieve/RivRetrieve/issues/720)
approves merging. Full-provider verification (including regional comparison)
remains in [#718](https://github.com/RivRetrieve/RivRetrieve/issues/718), and
the dedicated provider documentation page remains in
[#719](https://github.com/RivRetrieve/RivRetrieve/issues/719). Those separate
Efforts do not defer checks required to establish correct public integration.

## Build on the delivered provider work

At target `port/ar-ina`, [#713](https://github.com/RivRetrieve/RivRetrieve/issues/713),
[#714](https://github.com/RivRetrieve/RivRetrieve/issues/714),
[#715](https://github.com/RivRetrieve/RivRetrieve/issues/715), and
[#716](https://github.com/RivRetrieve/RivRetrieve/issues/716) are complete:

- The packaged catalogue supports offline discovery of `829` punctual river
  station identities across `13` admitted products (`5` discharge and `8`
  stage), with `2,611` witnessed `"available"` pairs and `8,166` `"unknown"`
  pairs.
- `providers/ar_ina/series.py` defines distinct source identities under
  `INA.Alerta5.series_id` (`variant == str(series_id)`) and established
  physical facts (`quantity`, `source_unit`, `normalized_unit`, `frequency`,
  `statistic`, `temporal_support`, `timestamp_anchor`, `time_zone="UTC"`,
  `vertical_reference="gauge_zero"` for stage, and withheld unestablished
  `day_definition` and `vertical_datum`).
- `providers/ar_ina/{config,fetch,parse}.py` implement punctual series lookup
  on `GET /a5/obs/puntual/series` (whenever concrete `INA.Alerta5.series_id`
  identities are not already established), bounded chunked observation
  retrieval on `GET /a5/obs/puntual/series/{series_id}/observaciones` with
  `skip_nulls=true`, omission of counterfeit `id: null`
  `generateRegularSeries` grid-padding slots (`source.synthesized_grid_null`),
  preservation of genuine stored database null intervals (`id > 0, valor: null`
  as `value=None`), and preservation of explicit UTC (`...Z`) timestamps across
  `03:00Z` standard-time and historical `02:00Z` Argentina daylight-saving
  civil midnights.
- `providers/ar_ina/catalogue/provider.json` already records
  `"bulk_observations": "none"`, verified
  `"license": "Creative Commons Atribución 4.0 Internacional"`, and
  `"citation": null`, so the Step 3 packaged catalogue artifact remains
  byte-identical.
- `providers/ar_ina/declaration.py` still declares `CatalogueOnly()`, leaving
  public observation retrieval disabled.

Use the delivered
[source scope](2026-11-06-ar-ina-source-scope-and-access.md),
[catalogue](2026-11-06-ar-ina-offline-station-catalogue.md),
[series](2026-11-06-ar-ina-series-identity-and-physical-meaning.md), and
[retrieval](2026-11-07-ar-ina-retrieval-behavior.md) contracts and their
retained evidence, continuing the existing
[private INA Alerta5 research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/ar-ina-source-access.md).

## Deliver working public retrieval

Connect `config()`, `window_declarations()`, `fetch`, and `parse` to
`LiveStages` in `src/rivretrieve/_internal/providers/ar_ina/declaration.py`
with `required_credentials=()`. Do not declare `shared_acquisition_products`:
each INA punctual series has its own `series_id` endpoint
(`/obs/puntual/series/{series_id}/observaciones`) with no shared multi-product
HTTP prerequisite, so independent product requests stay isolated per
`(station_id, product_id)` pair.

Reuse shared discovery, transport, unit validation, clipping, assembly, receipt
recording, and local store machinery across all `13` agreed punctual river
products (`discharge_daily_mean`, `discharge_instantaneous`,
`discharge_monthly_max`, `discharge_monthly_mean`, `discharge_monthly_min`,
`stage_4hourly`, `stage_daily_mean`, `stage_hourly`, `stage_instantaneous`,
`stage_monthly_max`, `stage_monthly_mean`, `stage_monthly_min`, and
`stage_weekly_mean`). Keep simulated/forecast procedures (`proc_id=4, 5, 6`),
rating-curve/derived non-observed procedures, areal series, and unverified
SSRH SNIH routes outside `ar_ina`.

Follow the standard `rr.fetch(..., start=..., end=...)` contract without adding
new public options, custom rate-limiter infrastructure, or provider-specific
issue suppression. Update repository-wide capability contracts:

- `docs/_generated/reference-tables.md` (`scripts/generate_reference.py`):
  `ar_ina` flips from `catalogue-only` to `live`.
- `docs/scripts/coverage_map.py` and `docs/assets/coverage-map.png`:
  move `"ARG"` from `PLANNED_COUNTRY` to `PROVIDER_COUNTRY` (`"ar_ina": "ARG"`)
  and regenerate the country coverage map against Natural Earth 1:50m Admin 0
  boundaries.
- Root `README.md`: add Argentina (`Instituto Nacional del Agua (INA), Alerta5`,
  `ar_ina`, `829` stations, `Open` access), update the summary sentence to
  fifteen providers in fourteen countries, and remove Argentina from the
  "Countries coming soon" list while keeping `docs/providers/ar_ina.md` scoped
  to #719.

## Preserve source meaning, provenance, and cache semantics

Public retrieval must preserve established series facts, absence states, and
store invariants end-to-end:

- Preserve discharge in `m3/s` (including `0.0 m3/s`) and stage in `m` with
  `vertical_reference="gauge_zero"` (including negative gauge-zero stages such
  as `-0.27 m`), plus UTC timestamps (`time_zone="+00:00"` on rows, series
  `time_zone="UTC"`, and `03:00Z` / historical `02:00Z` civil-midnight
  intervals) under `ClippingAxis.SOURCE_TIMESTAMP`.
- Enforce physical-predicate selection honestly: querying
  `frequency="daily", statistic="mean"` selects `discharge_daily_mean` /
  `stage_daily_mean`, while querying `frequency="hourly", statistic="mean"`
  withholds `stage_hourly` because its statistic is `not_established`, and
  querying `day_definition` leaves the selection unresolved because
  `day_definition` is `not_established`.
- Distinguish genuine stored database null intervals (`id > 0, valor: null` ->
  preserved `value=None`), counterfeit `generateRegularSeries` grid-padding
  nulls (`id is None, valor is None` -> omitted row +
  `source.synthesized_grid_null` info issue), empty windows
  (`OutcomeStatus.EMPTY`), absent runtime series (`OutcomeStatus.NO_MATCH`),
  and failed requests (`OutcomeStatus.FAILED` with `source.request_failed` or
  `source.unsupported_structure`) without failing unaffected sibling series.
- Reuse cached observations offline (`0` additional HTTP requests) under
  `cache="reuse"`, re-fetch cleanly under `cache="bypass"` and
  `cache="refresh"`, preserve held observations when refreshes fail, and attach
  verified `Creative Commons Atribución 4.0 Internacional` license provenance
  alongside an explicit `provenance.citation_not_established` info issue.

## Verification and handoff

Verify observable behavior through public selection and retrieval alongside
updated repository contracts:

- Offline discovery (`rr.find`, `rr.pick`, `rr.series`, `rr.metadata`,
  `rr.describe`) remains network-free after `LiveStages` registration.
- Public synthetic integration tests (`tests/test_ar_ina_public.py`) cover all
  `13` products without credentials, negative stage and historical `02:00Z` /
  `03:00Z` DST UTC timestamps, stored DB nulls vs synthesized boundary-null
  omission, runtime `/obs/puntual/series` lookup for uncatalogued pairs and
  explicit variants, partial sibling failure isolation, `on_issue` (`raise`,
  `warn`, `ignore`), local store `cache` modes (`reuse`, `bypass`, `refresh`)
  and store inspection/audit/clear helpers, and result bundle round-tripping.
- Public recorded replay (`tests/test_ar_ina_recorded_public.py`) exercises
  retained original INA Alerta5 HTTP captures across all `13` products, local
  store reuse, and absence/failure boundaries through `rr.find`, `rr.pick`, and
  `rr.fetch`, comparing returned rows against independently parsed publisher
  JSON bytes without embedding recorded payloads in source code.
- Repository-wide reference, boundary-probe obligation, coverage-map, and
  packaging checks pass alongside controlled `verify.py` execution under the
  [evidence process](../../docs/maintenance/evidence.md).

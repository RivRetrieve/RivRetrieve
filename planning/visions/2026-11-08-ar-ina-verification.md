# Argentina INA Alerta5 verification

Verify the integrated Argentina INA Alerta5 provider (`ar_ina`) against genuine
retained source evidence, close remaining public-replay and shared-contract
verification gaps, and record the external hydrological cross-check on
`port/ar-ina`. Delivering this vision and its controlled verification completes
[Effort #718](https://github.com/RivRetrieve/RivRetrieve/issues/718) under
[Program #348](https://github.com/RivRetrieve/RivRetrieve/issues/348);
publishing this vision alone does not complete the Effort.

Work targets `port/ar-ina` and leaves `main` unchanged.
[Effort #719](https://github.com/RivRetrieve/RivRetrieve/issues/719) delivers
the dedicated user documentation (`docs/providers/ar_ina.md`).
[Effort #720](https://github.com/RivRetrieve/RivRetrieve/issues/720) covers
final review and merge into `main` once both #718 and #719 are complete.

## Verify the delivered scope

Steps [#713](https://github.com/RivRetrieve/RivRetrieve/issues/713) through
[#717](https://github.com/RivRetrieve/RivRetrieve/issues/717) are delivered on
`port/ar-ina` at revision `7baca9b134608aaad1d4123d4e240b13a852ab7d`:

- Offline discovery exposes `829` canonical river gauges (`2,611` witnessed
  `"available"` `(station_id, product_id)` pairs across `13` canonical river
  discharge and stage products, plus `8,166` `"unknown"` pairs and `0`
  `"unavailable"` pairs), while excluding virtual model nodes (`real: false` or
  `tipo == "V"`), non-observational simulation/forecast procedures
  (`procedimiento.id` `3..9`), coastal tide-gauge networks (`estaciones_shn`,
  `estaciones_pvnymm`), spot calibration gaugings (`var_id=29`), groundwater
  depth (`var_id=96`), and empty water-temperature placeholders (`var_id=73`).
- `providers/ar_ina/declaration.py` wires `LiveStages` (`required_credentials=()`)
  across all `13` products (`5` discharge: `discharge_daily_mean`,
  `discharge_instantaneous`, `discharge_monthly_mean`, `discharge_monthly_min`,
  `discharge_monthly_max`; `8` stage: `stage_daily_mean`, `stage_instantaneous`,
  `stage_hourly`, `stage_4hourly`, `stage_weekly_mean`, `stage_monthly_mean`,
  `stage_monthly_min`, `stage_monthly_max`). `providers/ar_ina/series.py`
  preserves agency-published `INA.Alerta5.series_id` identities, converts
  `m^3/s -> m3/s` and gauge-zero `m -> m`, and keeps `day_definition` across
  pre-2009 Argentina DST transitions plus slotted `stage_hourly` (`var_id=85`)
  and `stage_4hourly` (`var_id=101`) aggregation facts explicitly
  `not_established`.

Follow [provider-port step 6](../../docs/maintenance/provider-ports.md#6-verification),
the [testing guide](../../docs/maintenance/testing.md), and the
[evidence guide](../../docs/maintenance/evidence.md). Build on the existing
`ar_ina` tests and the
[continuing private research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/ar-ina-source-access.md)
rather than creating a parallel verification harness.

## Close remaining public-replay and shared-contract gaps

Assess and verify the complete path from offline discovery and request planning
through unit normalization, interval-containment `stop_extension`, chunk
clipping, provenance, bundle round-trip, local store reuse, and distribution
packaging:

- **Byte-exact (`strict_params=True`) public replay and manifest boundary probes
  across all `13` products:** Retain a bounded HTTP supplement
  (`ar_ina-verification-2026-11-08-v1`) in the private archive so every one of
  the `13` admitted `ar_ina` products replays through both public
  `rr.find -> rr.pick -> rr.fetch` (`strict_params=True`) and
  `run_manifest_boundary_probes` (`tests/test_ar_ina_boundary_probe.py`) against
  exact engine-planned query parameters without parameter-relaxed fallbacks:
  - all `13` products across stations `8`, `52`, `151`, `1701`, and `2112`,
    including genuine negative gauge-zero stage (`-0.27 m` on `25587`
    `stage_monthly_min`), `:10`-second sub-daily stage (`3307`), slotted
    `1 h` / `4 h` stage (`31605`, `38398`), and `7 d` weekly stage (`36030`),
  - two-span `365`-day `.999999Z` microsecond chunking through public `rr.fetch`
    on catalogued river gauge `8` (`a5-obs-857-var4-span1-20230530-20240528` and
    `a5-obs-857-var4-span2-20240529-20240607`, `375` canonical rows),
  - `strict_params=True` pre-2009 Argentina DST replay across spring-forward
    (`23 h` `03:00Z -> 02:00Z` on `26616`), autumn fall-back (`25 h`
    `02:00Z -> 03:00Z` on `26616` recovered via `stop_extension=timedelta(hours=25)`),
    and monthly (`24665`),
  - counterfeit `generateRegularSeries` boundary-null rejection (`id: null`,
    `valor: null` -> `source.synthesized_grid_null` `info` issue), pre-record
    `EMPTY` (`1900` on `26605` and pre-2024 `sat2` on `2832`), offline
    withholding of `"unknown"` pairs (`EmptySelectionError`), and runtime
    `/obs/puntual/series` `NO_MATCH` verification for nonexistent explicit
    variants (`999999999`).
- **Shared cross-provider contracts:** Enroll `ar_ina` in the manifest boundary
  probe suite (`tests/test_ar_ina_boundary_probe.py`), the public
  selection/result bundle and `ReceiptAuthorship.STORE_EXCERPT` cache round-trip
  contract (`tests/test_public_representative_source_series.py`), live
  numeric-cell overflow, boolean, and non-finite rejection
  (`OutcomeStatus.FAILED` in `tests/test_live_numeric_values.py`), the offline
  `STATION_METADATA_NOTICE` and station-metadata distribution contract
  (`tests/test_station_metadata_packaging.py`), alongside existing enrollment in
  `tests/test_package.py` (`(10_777, 0, 0)` and `CC BY 4.0` attribution) and
  `tests/test_packaging_carries_catalogues.py`.
- **Catalogue lineage and distribution hygiene:** Re-verify native rebuild
  determinism, Croissant/provenance certification, and wheel/sdist exclusions so
  `native.parquet` and private verification inputs never enter built packages.

## Record the GRDC-Caravan hydrological cross-check

Record the empirical comparison against the peer-reviewed **GRDC-Caravan
extension v0.6** (Färber et al., 2025, `doi:10.5281/zenodo.15349031`) in the
private research record and acceptance report:

- Evaluate **all `7` Argentine gauges** in GRDC-Caravan (`59` Argentine gauges
  total; `44` match `ar_ina` river stations overall, `7` match `ar_ina`
  `discharge_daily_mean` stations, so the full national intersection is tested
  exhaustively without sampling): `1967` (`El Tunal`), `1964` (`Caimancito`),
  `1978` (`La Paz`), and `2046` (`El Colorado`) in `alturas_bdhi`; `14`
  (`Posadas`) and `19` (`Corrientes`) in `alturas_prefe`; and `2832`
  (`Paso Lucero`, commissioned `2024-01-16`) in `sat2`.
- Account explicitly for unit conversion (`Q [m3/s] = streamflow [mm/d] * area [km2] / 86.4`
  using GRDC-Caravan's published catchment `area`), Caravan's `0.01 mm/d` CSV
  quantization (`0.00 mm/d` discrepancy after 2-decimal rounding across all
  `1,464` `alturas_bdhi` station-days, `r = 0.99838..0.999995`), operational
  Prefectura Naval `Q(H)` rating curves versus historical SNIH/EVARSA gaugings on
  the mainstem *Río Paraná* (`r = 0.97300` and `0.98653` across `729`
  station-days), and post-2024 `sat2` commissioning (`OutcomeStatus.EMPTY` on
  `2832` over `2019-2020`).
- Keep empirical agreement distinct from publisher specification (`day_definition`
  remains `not_established` due to pre-2009 DST), and never commit external
  GRDC-Caravan files to either repository.

## Evidence and completion

Review exact `RivRetrieve` and `verification-evidence` revisions independently
before running controlled checks against archive-fetched collections. Fix any
in-scope defect uncovered during verification with focused regression tests and
re-verify affected suites. Keep synthetic controls, recorded HTTP replay,
governing source checks, GRDC-Caravan comparison, and distribution checks
distinct in `acceptance/2026-11-08-ar-ina-verification/README.md` so #719 and
#720 inherit an exact, auditable verification baseline.

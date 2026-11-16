# Austria eHYD verification

Verify the integrated Austria eHYD provider (`at_ehyd`) against genuine retained
source evidence, close remaining public-route and shared-contract verification
gaps, and record the external hydrological cross-check on `port/at-ehyd`.
Delivering this vision and its controlled verification completes
[Effort #617](https://github.com/RivRetrieve/RivRetrieve/issues/617) under
[Program #525](https://github.com/RivRetrieve/RivRetrieve/issues/525);
publishing this vision alone does not complete the Effort.

Work targets `port/at-ehyd` and leaves `main` unchanged.
[Effort #618](https://github.com/RivRetrieve/RivRetrieve/issues/618) delivers
the dedicated user documentation (`docs/providers/at_ehyd.md`).
[Effort #619](https://github.com/RivRetrieve/RivRetrieve/issues/619) covers
final review and merge into `main` once both #617 and #618 are complete.

## Verify the delivered scope

Steps [#612](https://github.com/RivRetrieve/RivRetrieve/issues/612) through
[#616](https://github.com/RivRetrieve/RivRetrieve/issues/616) are delivered on
`port/at-ehyd` at revision `0920345761fc3427114fd22c06cea41d944c7597`:

- Offline discovery exposes `746` canonical river gauges (`744` with selectable
  in-scope river series across `11` canonical products, plus `2` sediment-only
  river gauges with `unknown` in-scope availability), while excluding `59`
  standing-water lake gauges, springs, and river sediment transport series.
- `providers/at_ehyd/declaration.py` wires `LiveStages` (`required_credentials=()`)
  across the `7` validated historical `MessstellenExtraData/owf` CSV products
  (sharing a station-scoped `Messstellen/info` `fileNr` lookup), the `2`
  rolling sub-daily `Diagram/pegelBgis` JSON products, and the `2` current-year
  daily `Diagram/pegelLongterm` JSON products (`current_value` only).
  `providers/at_ehyd/series.py` preserves distinct source identities and
  established physical facts, converting `cm` gauge-zero stage (`factor=0.01`,
  `vertical_reference="gauge_zero"`), `m ü.A` / `m ü.A.` stage (`Meter über Adria`,
  `factor=1.0`, `vertical_reference="above_sea_level"`, certified at parser level
  on retained `210120` captures and via response-unit override on `rr.fetch`, as
  `0` active river gauges publish `m ü.A` in the packaged snapshot), and `°C` water
  temperature (`degC`) while keeping unestablished `owf` time-zone/day-boundary
  facts, `pegelLongterm` aggregation statistics, and `207340` `W-Monatsminima`
  `T,1` frequency/support explicitly `not_established`.

Follow [provider-port step 6](../../docs/maintenance/provider-ports.md#6-verification),
the [testing guide](../../docs/maintenance/testing.md), and the
[evidence guide](../../docs/maintenance/evidence.md). Build on the existing
`at_ehyd` tests and the
[continuing private research record](https://github.com/RivRetrieve/verification-evidence/blob/main/research/at-ehyd-source-access.md)
rather than creating a parallel verification harness.

## Close remaining public-replay and shared-contract gaps

Assess and verify the complete path from offline discovery and request planning
through unit harmonisation, clipping, provenance, bundle round-trip, local store
reuse, and distribution packaging:

- **End-to-end public replay across all `11` routes and documented source
  boundaries:** Retain a small bounded HTTP supplement
  (`at_ehyd-verification-2026-11-03-v1`) in the private archive so all `11`
  public routes and selectable `owf` edge cases replay through `rr.find`,
  `rr.pick`, and `rr.fetch` without synthetic prerequisites, while keeping
  non-selectable and fault-injected controls explicitly distinguished:
  - the 11th public route `owf_wassertemp_monatsmittel` on `201350` (via genuine
    `Messstellen/info?hzbnr=201350`) and negative water temperatures on `200352`
    (`-2.8 °C -> -2.8 degC`),
  - negative gauge-zero stage scaling on `207068` (`-227.0 cm -> -2.27 m`),
  - sparse multi-year `'Lücke'` state-transition markers on `201806` (omitted
    from numeric rows while emitting `info`-severity `source.gap_marker`),
  - unbracketed `Einheit: ;m³/s`, `; bis ;` `Exportzeitraum`, and pre-header
    `00:00:00` first observation timestamp on `204032` (`Werfen`),
  - physical-predicate withholding of `207340` `W-Monatsminima` (`T,1` daily
    step) under `frequency="monthly"` while preserving explicit `series_id` /
    `statistic="min"` retrieval with `frequency=not_established`,
  - sibling survival across exact-request `UNRESOLVED` (`[01.01.2024 00:00,+-Infty]`
    with `Invalid; Lücke` on `208058` via `rr.fetch`), parameter-remapped `FAILED`
    fault isolation (`0`-byte `owf` response from `file=99` served on `file=2`
    for `209486` via `rr.fetch`, alongside exact-request `file=99` parser replay),
    and `UNSUPPORTED` cleared unit (`Einheit: ;[]` on `211078`, verified
    withheld from offline `rr.find` discovery and replayed for sibling survival
    through assembled `drive(...)` on the retained `211078` captures).
- **Shared cross-provider contracts:** Enroll `at_ehyd` in the packaged
  reduced-carrier and `CC BY 4.0` / `Datenquelle: ehyd.gv.at` terms audit
  (`tests/test_package.py`), the offline `STATION_METADATA_NOTICE` and verbatim
  `orogr.Einzugsgebiet [km²]` drainage-area metadata distribution contract
  (`tests/test_station_metadata_packaging.py`), the public selection/result
  bundle and `ReceiptAuthorship.STORE_EXCERPT` cache round-trip contract
  (`tests/test_public_representative_source_series.py`), and live numeric-cell
  finiteness/overflow rejection across `owf` CSV, `pegelBgis` JSON, and
  `pegelLongterm` JSON (`tests/test_live_numeric_values.py`).
- **Catalogue lineage and distribution hygiene:** Re-verify native rebuild
  determinism, Croissant/provenance certification, and wheel/sdist exclusions so
  `native.parquet` and private verification inputs never enter built packages.

## Record the LamaH-CE hydrological cross-check

Record the empirical comparison against the peer-reviewed LamaH-CE dataset
(Klingler et al., 2021, `doi:10.5194/essd-13-4529-2021`) in the private research
record and acceptance report as independent hydrological corroboration:

- Compare active Austrian gauge coverage (`592 / 609` historical LamaH-CE
  Austrian gauges selectable in `at_ehyd`) and overlapping `1981-2017` daily
  mean discharge (`owf_abfl_tagesmittel`) across a reproducible `5`-station
  random sample (`63,905` station-days).
- Account explicitly for the three physical sources of minor differences between
  LamaH-CE and current `eHYD` exports: LamaH-CE's standardization of daily
  windows to `00:00..23:00 UTC` versus BMLUK `MEZ` (`UTC+01:00`), sub-hourly
  (`15`-minute) source integration versus rounded hourly values, and post-2017
  HZB hydrographic yearbook rating-curve revisions.
- Keep empirical agreement distinct from publisher specification: do not promote
  `owf` `time_zone` or `day_definition` from `not_established` to `known`
  without written BMLUK confirmation across historical gauge epochs, and do not
  introduce local LamaH-CE files as repository or test dependencies.

## Evidence and completion

Review exact `RivRetrieve` and `verification-evidence` revisions independently
before running final controlled checks against archive-fetched collections. Fix
any in-scope defect uncovered during verification with focused regression tests
and re-verify affected suites. Keep synthetic controls, recorded HTTP replay,
national archive certification, LamaH-CE comparison, and distribution checks
distinct in `acceptance/2026-11-03-at-ehyd-verification/README.md` so #618 and
#619 inherit an exact, auditable verification baseline.

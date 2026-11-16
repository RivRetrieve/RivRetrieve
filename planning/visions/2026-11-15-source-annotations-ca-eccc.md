# Source annotations: ca_eccc

Expose Environment and Climate Change Canada (ECCC) HYDAT daily qualifier symbols
and water-level recording precision codes as compiled-store source annotations for
`ca_eccc`. Keep source vocabulary and native types without inventing quality scores,
translating codes into normalized labels, or filtering observations.

This vision delivers [Effort #814](https://github.com/RivRetrieve/RivRetrieve/issues/814)
under [Program #809](https://github.com/RivRetrieve/RivRetrieve/issues/809).
Implementation completes [#814](https://github.com/RivRetrieve/RivRetrieve/issues/814)
only when source-independent checks and genuine-artifact compiled-store
certification pass. Publishing this document does not complete `#814`.
The [approved Program decisions](https://github.com/RivRetrieve/RivRetrieve/issues/809#issuecomment-6860795374),
the [core source-annotations vision](2026-11-13-source-annotations-core-and-usgs.md),
and the [HYDAT table audit](https://github.com/RivRetrieve/RivRetrieve/issues/814#issuecomment-6891337753)
record the governing scope.

## Desired outcome

Today `src/rivretrieve/_internal/providers/ca_eccc/bulk.py` compiles `DLY_FLOWS`
(`discharge_daily_mean`) and `DLY_LEVELS` (`stage_daily_mean`) from `Hydat.sqlite3`
into a revision-10 bulk store (`src/rivretrieve/_internal/providers/ca_eccc/config.py`),
retaining all 62 wide monthly symbol columns (`FLOW_SYMBOL1..31` and
`LEVEL_SYMBOL1..31`) and `DLY_LEVELS.PRECISION_CODE` on every daily Parquet row
while `StoreReader` strips them on read and `rr.annotations(result)` returns empty.

Migrate `ca_eccc` to the compiled-store annotation contract landed in `#831`:

- Unpivot daily `DLY_FLOWS.FLOW_SYMBOL1..31` and `DLY_LEVELS.LEVEL_SYMBOL1..31`
  into daily observation annotations in the compiled bulk store, and mark those
  62 wide columns `RECONSTRUCTIBLE` in the store manifest.
- Expose `DLY_LEVELS.PRECISION_CODE` (`PRECISION_CODES`: `8` for metres to
  millimetres, `9` for metres to centimetres) as an `Int64` observation annotation
  on the `DLY_LEVELS` annotation schema, and mark `DLY_LEVELS.PRECISION_CODE`
  `RECONSTRUCTIBLE`.
- Keep the 8 monthly summary columns per table (`FULL_MONTH`, `NO_DAYS`,
  `MONTHLY_MEAN`, `MONTHLY_TOTAL`, `FIRST_DAY_MIN`, `MIN`, `FIRST_DAY_MAX`, `MAX`)
  `RETAINED` in `part-0.parquet`, since they describe the monthly source record
  rather than individual daily observations or an entire series.
- Bind verified short field descriptions and official ECCC references
  (`https://collaboration.cmc.ec.gc.ca/cmc/hydrometrics/www/HYDAT_Definition_EN.pdf`)
  for every shipped annotation field.

Default `result.data`, `result.to_polars()`, and `rr.series(result)` keep their
existing harmonized schemas. Callers opting into `rr.annotations(result)`,
`rr.annotations(result, schema=...)`, `result.to_polars(annotations=...)`, or
`result.to_pandas(annotations=...)` receive the HYDAT annotations preserved across
compiled-store reads, `pick`, `to_utc`, and `to_bundle` / `from_bundle`.

## Source fidelity and repository facts

The HYDAT audit and `#831` store contracts establish these invariants for
implementation:

- **Null-value days within valid calendar months:** `_unpivot_month` in
  `src/rivretrieve/_internal/providers/ca_eccc/bulk.py` already emits a daily row
  (`value=None`, `value_state="published_null"`) for every valid calendar day
  (`1..calendar.monthrange(year, month)[1]`) of every present monthly SQLite row,
  and rejects any non-null value or symbol in out-of-calendar tail slots
  (`day > valid_days`, where `Hydat.sqlite3` has zero non-null values or symbols).
  Daily symbols on null-value days within valid calendar months, including `'D'`
  (Dry) water-level days in `DLY_LEVELS` and `'B'` or `'E'` null-flow days in
  `DLY_FLOWS`, therefore attach directly to those `published_null` rows with
  `measured=True` and `unmeasured_count=0`.
- **Legacy single-space symbol strings:** Across valid calendar days in
  `Hydat.sqlite3`, symbol columns contain SQL `NULL`, `DATA_SYMBOLS` letter codes
  (`A`, `B`, `D`, `E` observed in daily tables; `S` also defined in `DATA_SYMBOLS`),
  zero empty strings `""`, and legacy single-space `' '` strings (`1914..2013` in
  `DLY_LEVELS` and `1961..1969` in `DLY_FLOWS`). Under RivRetrieve's source-fidelity
  rules and `docs/design/observation-store-layout.md`, marking `FLOW_SYMBOL1..31`
  and `LEVEL_SYMBOL1..31` `RECONSTRUCTIBLE` requires exact deterministic recovery
  of every source cell from retained store data. Preserve raw SQLite `TEXT` values
  verbatim (`" "` stays `" "` and SQL `NULL` stays `null`) without whitespace
  stripping or blank-to-null normalization, and document legacy `' '` values in
  `docs/providers/ca_eccc.md`.
- **Monthly precision variation:** `DLY_LEVELS.PRECISION_CODE` is non-null on every
  `DLY_LEVELS` row in genuine `Hydat.sqlite3` and changes across months
  (including mid-year) within a station, so it cannot be stored as a static
  series annotation. Preserve SQLite `INTEGER | NULL` values verbatim in the
  `Int64` annotation column so existing synthetic SQLite fixtures inserting
  `PRECISION_CODE = NULL` remain valid. Because every present `DLY_LEVELS` month
  emits 28 to 31 valid daily rows carrying that month's value,
  `DLY_LEVELS.PRECISION_CODE` is deterministically recoverable from the daily
  `DLY_LEVELS` annotation table.
- **StoreReader behavior on unmarked windows:** `StoreReader._read_annotations`
  (`src/rivretrieve/_internal/store/reader.py`) populates an observation schema
  table only when filtered annotation Parquet rows exist for the queried window.
  Emit per-observation annotation rows consistently (matching `usgs_nwis` in `#831`,
  with `null` symbol where unmarked) so `rr.annotations(result)`,
  `rr.annotations(result, schema=...)`, and `result.to_polars(annotations=...)`
  expose the declared schema even when every day in a requested slice has a `null`
  symbol.
- **Lineage and existing store-excerpt assertions:** `src/rivretrieve/_internal/providers/ca_eccc/origins.py`
  pins `("src/rivretrieve/_internal/providers/ca_eccc/bulk.py", "_unpivot_month")`
  for catalogue lineage (checked offline in `tests/test_catalogue_build_provenance.py`
  and under `@pytest.mark.governing` in `tests/test_catalogue_origin_certification.py`).
  Existing tests that inspect unpivoted symbol columns in `part-0.parquet` or
  `StoreExcerptReceipt` (`tests/store/test_receipts_store_excerpt.py`,
  `tests/test_ca_eccc_boundary_probe.py`, and `tests/test_ca_eccc_no_days_evidence.py`)
  must be updated for the new `RECONSTRUCTIBLE` dispositions and annotation
  partitions; `tests/store/test_ca_eccc_streaming.py` also monkeypatches
  `_unpivot_month` and bounds per-batch row lists.

## Scope boundaries and exclusions

Keep `ca_eccc` bulk compilation scoped strictly to `DLY_FLOWS` and `DLY_LEVELS`
(`HYDAT_SOURCE_SCHEMAS`), with no series annotations (`series_annotations` remains
empty) and no expansion of the two-table SQLite publisher-schema contract:

- Unenrolled HYDAT product tables (`ANNUAL_INSTANT_PEAKS`, `ANNUAL_STATISTICS`,
  `PEAK_CODES`, `SED_*`, `SAMPLE_REMARK_CODES`, `CONCENTRATION_SYMBOLS`) are out
  of scope.
- Lookup tables (`DATA_SYMBOLS`, `PRECISION_CODES`, `DATA_TYPES`, `MEASUREMENT_CODES`,
  `OPERATION_CODES`, `STN_REMARK_CODES`, `STN_STATUS_CODES`, `AGENCY_LIST`,
  `DATUM_LIST`, `REGIONAL_OFFICE_LIST`, `VERSION`) remain unjoined; preserve raw
  source codes and link official documentation.
- Station-grain metadata (`STATIONS`, `STN_REGULATION`, `STN_DATUM_CONVERSION`,
  `STN_DATUM_UNRELATED`) belongs to `#602`.
- Multi-year and annual interval tables (`STN_DATA_COLLECTION`,
  `STN_OPERATION_SCHEDULE`, annual `STN_REMARKS` code `2`) are excluded under
  `#809`, and historical station-remark or year-span summary tables (`STN_REMARKS`
  codes `4` and `5`, `STN_DATA_RANGE`) remain outside the observation store.
- `ca_eccc` already emits zero QC-flag `Issue`s and zero `SourceSeries.variant`s;
  do not alter stream identities, `ObservationResult.data`, or packaged station
  catalogue files unless provenance bindings legitimately change.

Routine engineering choices remain with the implementing agent, following `#831`
conventions: exact provider-prefixed schema identifiers, lowercase column names
(including sharing an identical `AnnotationField` definition for the daily
`DATA_SYMBOLS` code across discharge and stage so combined fetches project one
column without cross-product `null` padding), exact reconstruction rule prose,
internal batch construction, and test structure.

## Evidence of completion

Protect the migration with source-independent tests (`uv run pytest --logic-only`,
`uv run ruff check`, `uv run ty check src`) covering:

- Manifest column dispositions (`63` newly `RECONSTRUCTIBLE` columns with non-empty
  deterministic reconstruction rules alongside the existing `68` `RECONSTRUCTIBLE`
  key/value columns and `16` `RETAINED` monthly summary columns), absence of the
  unpivoted columns from `part-0.parquet`, and streaming `certify_store_batches` /
  `validate_store` acceptance.
- End-to-end annotation discovery and projection (`rr.annotations`,
  `to_polars(annotations=...)`, `to_pandas(annotations=...)`) across discharge,
  stage, and combined discharge-and-stage queries, including symbols on
  `published_null` days within valid calendar months, windows whose days all have
  `null` symbols, verbatim legacy `' '` strings, `pick`, `to_utc`, and bundles.
- Verified field descriptions and official ECCC `reference_url` bindings, plus
  passing `tests/test_catalogue_build_provenance.py`.

Update `docs/providers/ca_eccc.md` following `docs/AGENTS.md` to show practical
inspection and projection of `ca_eccc` annotations and explain `DATA_SYMBOLS`,
`PRECISION_CODES`, and legacy single-space `' '` symbol cells.

Follow [the testing guide](../../docs/maintenance/testing.md) and
[the evidence guide](../../docs/maintenance/evidence.md). Verify the compiled
`ca_eccc` store against the genuine `Hydat.sqlite3` publisher artifact and
applicable `ca_eccc` checks (including `@pytest.mark.governing` catalogue-origin
checks in `tests/test_catalogue_origin_certification.py`) on an independently
reviewed revision using the private `verification-evidence` archive. Report
unavailable mandatory evidence as blocked; do not weaken checks or substitute
synthetic fixtures for genuine archive inputs. Keep controlled material and
private paths out of public repositories, logs, and artifacts.

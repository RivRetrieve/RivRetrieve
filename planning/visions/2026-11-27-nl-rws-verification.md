# Vision: Netherlands (`nl_rws`) Verification (Step 6)

- **Effort:** [#1053](https://github.com/RivRetrieve/RivRetrieve/issues/1053)
- **Coordination:** [#355](https://github.com/RivRetrieve/RivRetrieve/issues/355) (tracker [#870](https://github.com/RivRetrieve/RivRetrieve/issues/870))
- **Target branch:** `port/nl-rws` (never merge to `main` until Step 8 [#1055](https://github.com/RivRetrieve/RivRetrieve/issues/1055))
- **Depends on:**
  - Step 1 ([#1048](https://github.com/RivRetrieve/RivRetrieve/issues/1048)): `planning/visions/2026-11-25-nl-rws-source-scope-and-access.md`
  - Step 2 ([#1049](https://github.com/RivRetrieve/RivRetrieve/issues/1049)): `planning/visions/2026-11-25-nl-rws-station-catalogue-and-metadata.md`
  - Step 3 ([#1050](https://github.com/RivRetrieve/RivRetrieve/issues/1050)): `planning/visions/2026-11-26-nl-rws-series-identity-and-physical-meaning.md`
  - Step 4 ([#1051](https://github.com/RivRetrieve/RivRetrieve/issues/1051)): `planning/visions/2026-11-26-nl-rws-retrieval-behavior.md`
  - Step 5 ([#1052](https://github.com/RivRetrieve/RivRetrieve/issues/1052)): `planning/visions/2026-11-27-nl-rws-provider-integration.md`

## Goal

Establish independent, reproducible verification evidence that `nl_rws` behaves
correctly across all 10 admitted products, historical depth, DST/timezone
handling, missing-value sentinels, cache reuse, catalogue origin/rebuild
certification, wheel packaging, and a number-by-number external hydrograph
comparison against the local E-STREAMS dataset.

## Scope and Design Decisions

### 1. Retained verification evidence & `verification-evidence` bindings

- Reuse the already-published Step 1 collection `nl_rws-access-2026-11-25-v1`
  (16 members covering `OphalenCatalogus`, all 10 admitted products, 1990
  `GEM24H`-only discharge, parallel `other:F216` + `other:F230` series,
  2020-03-29 spring DST fixed `+01:00`, `Kwaliteitswaardecode = "25"`, HTTP 204
  empty window, and HTTP 400 invalid station).
- Publish a companion verification collection `nl_rws-verification-2026-11-27-v1`
  in `RivRetrieve/verification-evidence` containing:
  1. `native.parquet` (exact SHA-256 matching the Step 2 packaged catalogue's
     `provenance.json`: `b9ea91a1285fdc1476592c75e4636f3bbb0ec5b215dc3c715155815ebf92dc0c`).
  2. A genuine far-back historical-depth capture for `lobith.bovenrijn.tolkamer`
     `discharge_m3s_gem24h` near the start of its record (e.g. `1901-01-01` to
     `1901-01-31`, verifying historical reach beyond modern comparison windows).
  3. A genuine `Kwaliteitswaardecode = "99"` / `9.99999e+37` missing-sentinel
     DDAPI 2.0 capture.
  4. E-STREAMS external comparison outputs (comparison summary JSON/CSV,
     per-gauge metrics, and hydrograph comparison figures).
- Wire `nl_rws` into `RivRetrieve/verification-evidence`
  `inventory/test-bindings.json` under `maintenance/catalogue/nl_rws/official`
  and update `research/nl-rws-source-access.md` with the Step 6 verification and
  E-STREAMS comparison findings.

### 2. Recorded observation verification (`tests/test_nl_rws_recorded.py`)

Replay genuine retained DDAPI 2.0 responses (marked `@pytest.mark.recorded(...)`)
end-to-end through `rr.fetch(..., cache="bypass")` and/or `nl_rws.fetch` +
`nl_rws.parse` / `parse_group`, checking identities, timestamps/offsets,
canonical units/values, and annotations together:

- **All 10 admitted products:**
  - `discharge_m3s_nvt` + `discharge_m3s_gem24h` (Lobith `2020-03-01..05`,
    co-acquired single `POST`, parallel `other:F216` and `other:F230` series
    kept separate)
  - `discharge_m3d_nvt` (Den Oever `2011-12`, converted `m3/d → m3/s`)
  - `stage_nap_nvt` + `stage_nap_gem24h` (Lobith `2020-03-01..03`, `cm → m`)
  - `stage_msl_nvt` (A12 `2026-11-20..22`, `cm → m`)
  - `stage_taw_nvt` (Eijsden Grens `2026-11-20..22`, `cm → m`,
    `Kwaliteitswaardecode = "25"` preserved in `nl_rws.observation`)
  - `stage_plaatslr_nvt` (Markermeer Midden `2024-02-28`, `cm → m`)
  - `water_temperature_nvt` + `water_temperature_gem24h` (Maarssen Kanaal
    `2026-11-20..22`, `oC → degC`)
- **Timezone / DST invariance:** Lobith across 2020-03-29 spring DST transition
  (`12_obs_dst_lobith_2020_03_29_meting.json`) confirming fixed `+01:00` with
  no wall-clock shift or dropped boundary hour.
- **Historical depth:** Lobith `1990-03-01..10` (`GEM24H`-only) and far-back
  `1901-01` `GEM24H` capture verifying `NVT` returns `OutcomeStatus.NO_MATCH`
  while `GEM24H` returns genuine historical daily values.
- **Missing-value sentinel:** Genuine `Kwaliteitswaardecode = "99"` /
  `9.99999e+37` recording verifying `value = None` alongside valid numeric rows
  and `kwaliteitswaardecode == "99"` in `nl_rws.observation`.
- **Empty & error responses:** Genuine HTTP 204 (`13_obs_empty_1800.json`) →
  `OutcomeStatus.NO_MATCH` and HTTP 400 (`14_obs_error_bad_station.json`) →
  `OutcomeStatus.FAILED`.

### 3. Cache reuse & wheel packaging verification

- Add offline cache round-trip tests in `tests/test_nl_rws_integration.py`
  verifying `cache="reuse"` on both single-product (`stage_nap_nvt`) and
  co-acquired (`discharge_m3s_nvt` + `discharge_m3s_gem24h`) requests: second
  `rr.fetch()` issues 0 HTTP requests and returns identical `series_id`,
  `facts_id`, values, and `nl_rws.observation` annotations.
- Run `tests/test_packaging_carries_catalogues.py` (wheel/sdist distribution
  verification) confirming all `nl_rws` packaged catalogue files ship in built
  distributions.

### 4. All-provider catalogue origin certification & rebuild

- Add `read_catalogue_sources()` and `main()` CLI entrypoint to
  `src/rivretrieve/_internal/providers/nl_rws/generate_catalogue.py` matching
  the shared catalogue certification contract.
- Complete the `nl_rws` wiring in `tests/test_catalogue_origin_certification.py`
  (`_adapter()` binding `associations`/`checked_on`/`provenance`, and
  parametrizing `"nl_rws"` in
  `test_native_composition_root_rebuilds_committed_artifacts_without_network`)
  and run both `test_catalogue_origin_certification.py` and
  `test_catalogue_descriptor.py` against `--evidence-root`.

### 5. Number-by-number E-STREAMS external hydrograph sanity comparison

- **Data source (local only, never downloaded automatically):**
  - Time series CSVs: `/Users/nascimth/Documents/data/EStreams/time_series_csv`
  - Station metadata:
    `/Users/nascimth/Documents/data/EStreams/streamflow_gauges/estreams_gauging_stations.csv`
- **Confident station matching:** Match the 17 Netherlands (`NL_RWS`) gauges in
  E-STREAMS against `nl_rws`'s 1,706 packaged stations by coordinates and name.
  Explicitly report any E-STREAMS gauges that belong to regional water boards
  (e.g. Limburg brooks absent from Rijkswaterstaat DDAPI 2.0) or have no
  overlapping observations.
- **Strict number-by-number rule:** Every gauge counted in the comparison must
  compare actual non-null numeric observations retrieved through `rr.fetch()`
  against actual non-null E-STREAMS numeric values on aligned dates
  (`n > 0` overlapping non-null pairs). A matched station that returns zero
  observations or has no overlapping non-null values in the comparison window
  does **not** count as a comparison and is reported separately as unavailable
  or non-overlapping.
- **Comparison protocol:**
  - Retrieve daily discharge (`discharge_m3s_gem24h`; and where a gauge only
    publishes `discharge_m3s_nvt` in the overlap window, note that explicitly)
    through RivRetrieve's public `rr.fetch()` API on a bounded overlapping
    multi-year window (e.g., 2015–2020 or the station's available overlap).
  - Compare value by value without filtering, shifting, or fitting: report
    exact overlap count `n`, Pearson `r`, MAE, RMSE, bias, max absolute
    difference, and gap alignment.
  - Plot both hydrographs side-by-side / overlaid with explicit units (`m³/s`)
    and preserved gaps.
  - Check far-back historical reach on Lobith (`NL000010`, E-STREAMS start
    `1901-01-01`) with real retrieved numbers from `1901`.
  - Retain the E-STREAMS comparison summary, scripts/method, metrics, and
    hydrograph figures in `nl_rws-verification-2026-11-27-v1` and document
    findings/limitations in `RivRetrieve/verification-evidence`'s
    `research/nl-rws-source-access.md`.

### 6. Deferred to Steps 7–8

- **Step 7 (`#1054` User documentation):** Author `docs/providers/nl_rws.md`
  (explicitly documenting `Kwaliteitswaardecode = "99"` / `9.99999e+37`
  missing-value behavior and `statuswaarde`/`kwaliteitswaardecode`
  annotations).
- **Step 8 (`#1055` Final review):** Final review and merge of `port/nl-rws`
  into `main`.

## Evidence of Completion

1. `nl_rws-verification-2026-11-27-v1` published and bound in
   `RivRetrieve/verification-evidence` (`inventory/collections.json`,
   `inventory/test-bindings.json`, `research/nl-rws-source-access.md`).
2. `tests/test_nl_rws_recorded.py`, `tests/test_nl_rws_integration.py` (cache
   reuse), `tests/test_catalogue_origin_certification.py` (full `nl_rws`
   rebuild), `tests/test_catalogue_descriptor.py`, and
   `tests/test_packaging_carries_catalogues.py` all pass (both `--logic-only`
   and `--evidence-root`).
3. Number-by-number E-STREAMS comparison completed across all matched gauges
   with overlapping numeric data (`n > 0`), hydrograph figures and metrics
   retained in `verification-evidence`, and far-back `1901` Lobith reach
   verified.
4. `ruff format --check`, `ruff check`, and `ty check src` pass with zero
   errors; independent review approves both `RivRetrieve` and
   `verification-evidence` PRs; `#1053` closed as `COMPLETED`.

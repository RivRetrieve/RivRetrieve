# 03-m3-closeout-docs-and-report Plan

## 1. Goal and scope

Close M3 with provider-port notes, one final negative-control sweep, and an M3 milestone report.

In scope:

- Populate `docs/provider_ports/ch_foen.md` from M3 step 02 evidence.
- Audit the requested negative controls against `tests/` and add only minimal tests for uncovered single-test gaps.
- Write `docs/milestones/m3-ch-foen-catalogue-provider/REPORT.md` in the M1/M2 report shape.
- Verify the 369-test baseline remains green, or update the report with the exact new count if one or two negative-control tests are added.

Out of scope:

- Code behavior changes.
- Catalogue artifact regeneration.
- Public API changes.
- Internal API refactors.
- Observation retrieval implementation.
- Product dictionary or architecture edits.
- Real token handling or live observation calls.

Source material:

- M3 tracker goal and exit criteria: `docs/milestone-tracker.md:166`, `docs/milestone-tracker.md:198`.
- Step 02 plan: `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:7`.
- Step 02 execution: `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:3`.
- M1/M2 report shape: `docs/milestones/m1-harness-foundation/REPORT.md:9`, `docs/milestones/m2-discovery-and-observation-contracts/REPORT.md:9`.

## 2. API surface touched

Expected: **NONE**.

This is a docs + sweep + REPORT step. No public, internal, or test-surface behavior change is expected. The existing T117/T119/T120 public-surface controls stay green:

- T117: `tests/test_provider_handle.py::test_provider_handle_protocol_method_signatures_match_tracker` (`tests/test_provider_handle.py:92`).
- T119: `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` (`tests/test_package.py:11`).
- T120: `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion` (`tests/test_package.py:26`).

The test-count baseline is:

- M2 close: 335 tests (`docs/milestones/m2-discovery-and-observation-contracts/REPORT.md:18`).
- M3 step 01: 335 tests (`docs/milestones/m3-ch-foen-catalogue-provider/steps/01-catalogue-typealiases-and-schema-rename/execution.md:39`).
- M3 step 02: 369 tests (`docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:57`).

Only new tests added by the negative-control sweep are allowed. If added, they must be assertion-only coverage of already-shipped behavior, not behavior changes.

## 3. Documents to write

### 3.1 `docs/provider_ports/ch_foen.md`

Replace the current stub (`docs/provider_ports/ch_foen.md:1`) with section-level provider-port notes. Keep the file as evidence and handoff notes, not user documentation and not a new architecture contract.

Required sections:

1. **Source Endpoints**
   - Short table.
   - Include Existenz.ch `/apiv1/hydro/locations` as the M3 catalogue input.
   - Include BAFU/Existenz docs/reference as M4 observation background only.
   - Include token status from step 02 Q12 plus the latest upstream classification: legacy `origin/switzerland` HEAD is `cd9b030` (`Restore public Switzerland token`), which intentionally restores the literal `INFLUX_TOKEN` as a public service credential; target M3 still intentionally carries no token because it is catalogue-only (`docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:81`; thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:40,200).
   - Cite `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:172` and `src/rivretrieve/_internal/providers/ch_foen/catalogue/provider.json:1`.

2. **Catalogue Mapping**
   - Use a Markdown table, not bullets. Recommended columns: `Legacy/source field`, `Canonical target`, `Provider metadata`, `Decision`, `Citation`.
   - Include station common fields, nullable `elevation_m` and `drainage_area_km2`, station-product availability as `unknown`, provider info row, and JSON metadata encoding.
   - Cite station metadata and nullability decisions from `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:54`, `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:77`, `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:127`, and `docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:172`.
   - Legacy citation examples: thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:151,159,161,162.

3. **Product Dictionary**
   - Use a Markdown table: `Legacy variable`, `Native fields`, `Canonical product_id`, `M3 classification`, `M4 note`.
   - State that M3 introduced no `ch_foen`-specific product IDs and dropped no legacy SwitzerlandFetcher variables. This follows step 02 plan §3.4 (`docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/plan.md:155`).
   - Include all six canonical mappings.
   - Legacy citations: thirdparty/RivRetrieve-Python @ origin/switzerland:rivretrieve/switzerland.py:22,44-80.

4. **Annotation**
   - 1-2 short paragraphs.
   - State that row and series annotation schemas are empty in M3, by design; M4 owns real observation annotations.
   - Cite module tests and implementation: `tests/test_ch_foen_module.py:43`, `tests/test_ch_foen_module.py:47`, `src/rivretrieve/_internal/providers/ch_foen/module.py:68`, `src/rivretrieve/_internal/providers/ch_foen/module.py:72`.

5. **Issues**
   - Short list or table.
   - Include token handling status and M4 handoff: confirm upstream's public-token classification still holds at M4 start, then decide embedding mechanics (`literal`, configuration override, or both), not whether the token is secret.
   - Include maintainer-only generator invocation and offline import invariant.
   - Include D6-D9 discoveries:
     - D6 path shadowing (`docs/discoveries.md:128`).
     - D7 Pydantic extras + ty (`docs/discoveries.md:144`).
     - D8 catalogue encoding round-trip (`docs/discoveries.md:172`).
     - D9 `Mapping` narrowing under ty (`docs/discoveries.md:158`).
   - Include M4 observations placeholder shape to replace (`src/rivretrieve/_internal/providers/ch_foen/module.py:76`).
   - Include station-product catalogue size explicitly: `246 * 6 = 1476` availability rows (`docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:61`).

Q1 answer for the plan: the current `docs/provider_ports/ch_foen.md` does not yet say the token finding; it is still a stub with `Status: not started` (`docs/provider_ports/ch_foen.md:10`). Step 02 records the historical finding: legacy carries a literal Influx token and target M3 carries no token-bearing runtime code. Latest upstream `origin/switzerland` commit `cd9b030` (`Restore public Switzerland token`) classifies the token as public by restoring it deliberately. Recommended M4 framing: "M4 should confirm upstream's public-token classification still holds at M4 start, document that classification in `docs/provider_ports/ch_foen.md`, and then decide embedding mechanics such as literal, configuration override, or both. Fixture-backed observation CSVs should isolate observation semantics from credential mechanics."

Q2 answer: use Markdown tables for catalogue and product mapping. The matrix is small, citation-heavy, and benefits from side-by-side canonical/provider/dropped classification.

### 3.2 `docs/milestones/m3-ch-foen-catalogue-provider/REPORT.md`

Create the M3 report with the same nine-section spine as M1/M2.

Required outline:

1. **Steps executed**
   - Table with M3 step 01 commit `760f3fe` / tag `v0.1.15`, step 02 commit `99fa125` / tag `v0.1.16`, step 03 commit TBD / tag `v0.1.17`.
   - Include test counts: 335 -> 335 -> 369 -> 369 or 370/371 if minimal sweep tests are added.
   - Include tag state: current latest tag is `v0.1.16`; M3 step 03 should bump and tag `v0.1.17` after the step-03 commit.

2. **Public API shipped vs tracker**
   - State `rr.providers()` now includes `"ch_foen"`.
   - State the six provider module functions plus `info()` are reachable through the existing `_ProviderHandle`/`ProviderHandle` surface; no signature or package-root shape changed.
   - State public surface remains the M2 set guarded by T119.

3. **Internal types introduced**
   - Include `ChFoenStationMetadata`, `ChFoenProductMetadata`, `ChFoenStationProductMetadata`.
   - Include `src/rivretrieve/_internal/providers/ch_foen/module.py` functions.
   - Include `generate_catalogue.py` as maintainer-only implementation, not runtime API.
   - Include implementation-required additions from step 01: catalogue aliases and `*_SCHEMA` rename as D3 resolution (`docs/milestones/m3-ch-foen-catalogue-provider/steps/01-catalogue-typealiases-and-schema-rename/execution.md:5`).

4. **Runtime dependencies added**
   - Expected: none. M3 consumes M1 dependencies only.

5. **Test count delta and negative-control inventory**
   - Include total and net count.
   - Call out fixture facts: 246 stations, station `2016` / `Brugg`, and `1476` station-product rows (`tests/test_ch_foen_generate_catalogue.py:41`, `tests/test_ch_foen_generate_catalogue.py:50`, `tests/test_ch_foen_registration.py:28`; thirdparty/RivRetrieve-Python @ origin/switzerland:tests/test_switzerland.py:36-45).
   - Inventory T117/T119/T120, offline import, metadata leak, live unsupported routing, annotation-empty controls, observations placeholder, fixture binding.

6. **Discoveries logged**
   - D3 resolution.
   - D6, D7, D8, D9.
   - State no missing D-entry was found during report preparation unless the executor discovers one; if found, stop and log it first.

7. **Surprises and candidate updates for M4 prep**
   - Annotation schemas are empty lists and M4 extends them.
   - Token status: upstream `cd9b030` (`Restore public Switzerland token`) classifies the legacy literal token as public; M3 target has none because it is catalogue-only; M4 must confirm this remains true at M4 start and choose embedding mechanics before live observation runtime.
   - Placeholder observations return empty data plus `observations_not_yet_implemented`; M4 replaces it.
   - Observation result generation will face the same D8 serialization/provenance obligations.
   - D7 and D9 apply directly to M4 observation parsing: Pydantic `extra="allow"` tests should use `model_validate({...})`, and `json.loads` parser shape checks should use concrete `dict`/`list`, not `Mapping`/`Sequence`.
   - Capability flags must be revisited: implementing observations likely changes `bulk_observations` away from `"false"`; if any provider-info capability changes, re-run `generate_catalogue.py` and re-commit packaged `provider.json`. The three `live_*` catalogue flags should stay `False` unless M4 also adds live catalogue calls, which is out of M4 scope.

8. **Escalations**
   - D6 was the only architecture-prompt vs M1/M2 public-surface contradiction.
   - Q3 answer: do not promote D6-D9 to `architecture.md`; they are project-pattern lessons, not shared architecture commitments. Surface D6 here as the only escalation-like event because it changed the provider package path.

9. **Ready for M4**
   - Q6 answer: yes, include a brief handoff checklist.
   - Checklist items: annotation schemas to define, public-token classification to confirm, token embedding mechanics to select, observation result/parser types to implement, fixture-backed observation CSVs to commit/use, placeholder issue to remove, row/series provenance and issue obligations to test, provider-info capability flags and `provider.json` regeneration to revisit, top-level `rr.observations(...)` wrapper to add.

## 4. Negative-control sweep

### 4.1 Already covered by step 02

Recorded in step 02 execution:

- Full suite: `369 passed` (`docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:57`).
- Explicit T117/T119/T120 plus metadata-leak invocation passed (`docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:58`).
- Offline-import probe passed (`docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:59`).
- Fixture facts passed: `246`, `Brugg` (`docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:60`).
- Provider discovery/station-products probe passed: `["ch_foen"]`, `1476` (`docs/milestones/m3-ch-foen-catalogue-provider/steps/02-ch-foen-full-implementation/execution.md:61`).

Existing test anchors:

- T117: `tests/test_provider_handle.py::test_provider_handle_protocol_method_signatures_match_tracker`.
- T119/T120: `tests/test_package.py`.
- Offline import: `tests/test_offline_import.py::test_import_rivretrieve_does_not_import_providers_stubs_or_generators`.
- ch_foen runtime import control: `tests/test_ch_foen_registration.py::test_import_rivretrieve_does_not_import_ch_foen_runtime_modules`.
- Metadata leak: `tests/test_ch_foen_registration.py::test_ch_foen_internal_metadata_import_does_not_leak_public_names`.
- Fixture count / Brugg: `tests/test_ch_foen_generate_catalogue.py::test_ch_foen_generator_station_count_matches_legacy_fixture` and `tests/test_ch_foen_generate_catalogue.py::test_ch_foen_generator_station_2016_brugg_matches_legacy_fixture`.
- Live unsupported routing: `tests/test_ch_foen_capabilities.py`.
- Annotation schemas empty: `tests/test_ch_foen_module.py::test_ch_foen_row_annotation_schema_is_empty` and `tests/test_ch_foen_module.py::test_ch_foen_series_annotation_schema_is_empty`.

### 4.2 Step 03 audit

Q4 answer from planner's test walk: two narrow explicitness gaps appear, both suitable for minimal tests if still present at execution time. They are not substantive coverage holes.

Audit each item against HEAD before editing:

1. **Catalogue envelopes**
   - Confirm `rr.stations()`, `rr.products()`, `rr.provider_info()`, and `rr.provider("ch_foen").station_products()` each return `CatalogResult` with Polars `data` and packaged/global provenance.
   - Note: there is no public `rr.station_products()` in the M2/M3 API; interpret the prompt's `rr.station_products` as `rr.provider("ch_foen").station_products()`. If a global function has appeared, stop because public API changed.
   - Existing tests prove data rows but not all envelope/provenance details for `ch_foen` (`tests/test_ch_foen_registration.py:13`, `tests/test_ch_foen_registration.py:21`, `tests/test_ch_foen_registration.py:28`, `tests/test_ch_foen_registration.py:35`).
   - If still uncovered, add one focused test, e.g. `test_ch_foen_catalogue_methods_return_catalog_results_with_provenance`.

2. **`source="live"` rejection**
   - Already covered for `products`, `stations`, and `station_products`, including `warn`, `raise`, and `ignore` behavior (`tests/test_ch_foen_capabilities.py:18`, `tests/test_ch_foen_capabilities.py:34`, `tests/test_ch_foen_capabilities.py:50`).
   - No new test expected.

3. **Provider-handle observations placeholder**
   - Module-level placeholder is covered under all `on_issue` settings (`tests/test_ch_foen_module.py:51`).
   - Public handle path `rr.provider("ch_foen").observations(...)` is not explicitly covered by a `ch_foen`-specific test.
   - If still uncovered, add one parametrized test over `on_issue in ("raise", "ignore", "warn")` that asserts it returns `ObservationResult`, does not raise, has empty data/annotations, and contains `observations_not_yet_implemented`.
   - Include default `on_issue` call in the same test or a tiny sibling test.

4. **Annotation schemas empty**
   - Already covered at module level (`tests/test_ch_foen_module.py:43`, `tests/test_ch_foen_module.py:47`).
   - Optional: the provider-handle observation test indirectly validates the empty schemas through handle validation.

5. **`generate_catalogue.py` not imported by package import**
   - Covered by subprocess tests (`tests/test_offline_import.py:7`, `tests/test_ch_foen_registration.py:55`).
   - Re-run offline import probe after edits.

6. **Suite pass**
   - Re-run `uv run pytest`; expected `369 passed` if no tests added, otherwise `370+ passed`.

Stopping rule: if the audit finds a whole behavior family missing rather than the one or two focused explicitness gaps above, stop and surface before expanding step scope.

## 5. Tests

Expected new tests: likely 1-2 minimal negative-control tests, only if the §4.2 audit confirms the gaps still exist.

Candidate additions:

- `tests/test_ch_foen_registration.py::test_ch_foen_catalogue_methods_return_catalog_results_with_provenance`
  - Covers `rr.stations`, `rr.products`, `rr.provider_info`, and `rr.provider("ch_foen").station_products`.
  - Assertion style: `isinstance(result, CatalogResult)`, `isinstance(result.data, pl.DataFrame)`, provenance present/source expected, row count where already known.

- `tests/test_ch_foen_registration.py::test_ch_foen_handle_observations_placeholder_returns_result_for_all_on_issue`
  - Parametrize `on_issue`.
  - Assert public handle path returns `ObservationResult` and never raises under `raise`, `ignore`, `warn`, plus default.
  - Assert empty row/series annotation tables survive the public handle's always-on annotation validation seam.

Existing negative controls to cite in the report:

- T117: `tests/test_provider_handle.py::test_provider_handle_protocol_method_signatures_match_tracker`.
- T119: `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface`.
- T120: `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion`.
- `tests/test_offline_import.py::test_import_rivretrieve_does_not_import_providers_stubs_or_generators`.
- `tests/test_ch_foen_registration.py::test_import_rivretrieve_does_not_import_ch_foen_runtime_modules`.
- `tests/test_ch_foen_registration.py::test_ch_foen_internal_metadata_import_does_not_leak_public_names`.
- `tests/test_ch_foen_capabilities.py::test_ch_foen_live_products_unsupported_uses_m2_routing`.
- `tests/test_ch_foen_capabilities.py::test_ch_foen_live_stations_unsupported_uses_m2_routing`.
- `tests/test_ch_foen_capabilities.py::test_ch_foen_live_station_products_unsupported_uses_m2_routing`.
- `tests/test_ch_foen_module.py::test_ch_foen_observations_placeholder_returns_issue_result`.
- `tests/test_ch_foen_generate_catalogue.py::test_ch_foen_generator_station_count_matches_legacy_fixture`.
- `tests/test_ch_foen_generate_catalogue.py::test_ch_foen_generator_station_2016_brugg_matches_legacy_fixture`.

## 6. Files

### 6A. `docs/provider_ports/ch_foen.md`

Write/update the provider-port notes using the outline in §3.1.

Checkpoint:

- File is complete.
- No code changes.
- No architecture or product dictionary edits.
- After REPORT §7 is drafted, diff the token-status and placeholder bullets between this file and the REPORT for substantive consistency.

### 6B. Negative-control sweep audit

Read existing tests, run targeted tests, and add only the minimal test(s) identified in §4.2 if still uncovered.

Checkpoint:

- `uv run pytest` passes.
- §4.2 coverage confirmed.
- Any new tests assert existing behavior only.

### 6C. `docs/milestones/m3-ch-foen-catalogue-provider/REPORT.md`

Write the milestone report using the outline in §3.2.

Checkpoint:

- REPORT structure matches M1/M2.
- Sections §1-§9 are filled with verified facts.
- Test counts and commit SHAs are current.
- Discoveries are summarized accurately.
- M4 handoff checklist is present.
- After writing, compare REPORT §7 and `docs/provider_ports/ch_foen.md` Issues for consistent token-status and placeholder framing.

### 6D. Final verification

Run:

- `uv run ruff format`
- `uv run ruff check --fix`
- `uv run ty check`
- `uv run pytest`
- `uv run pytest tests/test_provider_handle.py::test_provider_handle_protocol_method_signatures_match_tracker tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion`
- Re-run metadata leak test.
- Re-run offline-import probe.

Report exact outputs in `execution.md` if this step gets an execution record.

## 7. Open questions

1. **What should `docs/provider_ports/ch_foen.md` say about token status?**
   - Recommendation: document upstream `origin/switzerland` HEAD `cd9b030` (`Restore public Switzerland token`) as the current public-token classification, and explicitly state target M3 contains no runtime token because it is catalogue-only. M4 should confirm the classification still holds at its start, then choose embedding mechanics.

2. **Should catalogue mapping be a table or bullets?**
   - Recommendation: table.

3. **Should D6-D9 be promoted to `architecture.md`?**
   - Recommendation: no. They are project-pattern lessons and provider-port execution lessons. D6 belongs in REPORT §8 as the only path/prompt contradiction, not as a shared architecture rule.

4. **Does the §4.2 audit reveal any negative-control gap?**
   - Recommendation: yes, likely two narrow explicitness gaps: ch_foen-specific catalogue envelope/provenance assertions and public-handle observations placeholder assertions. Add minimal tests only if the executor confirms no existing coverage.

5. **What is the M3 closeout tag?**
   - Recommendation: `v0.1.17` after the step-03 commit. Current tag inventory ends at `v0.1.16`, and current configured version is `0.1.16`; run the mandatory patch bump before commit, then tag.

6. **Does REPORT §9 need an explicit M4 handoff checklist?**
   - Recommendation: yes; keep it brief and operational.

## 8. Deferrals

- Real `ch_foen` observation retrieval: M4.
- Top-level `rr.observations(...)`: M4.
- Public-token classification confirmation and embedding mechanics: M4.
- Observation row and series annotation schema population: M4.
- Fixture-backed observation CSVs from legacy Switzerland tests: M4.
- `rr.map_stations()`: M5.
- Public `__all__` cleanup from D5: post-M3 or V1 closeout unless coordinator scopes it.
- Any second provider: post-V1 unless architecture changes.
- Product dictionary expansion beyond the six canonical SwitzerlandFetcher variables: post-V1 unless M4 observation evidence forces a proposal.

## 9. Stopping conditions for the executor

- Stop if the §4.2 audit reveals a substantive behavior family uncovered by tests rather than the narrow test gaps listed here.
- Stop if a step-02 decision appears wrong on inspection, especially product classification or station-product availability semantics.
- Stop if token status cannot be reconciled into the M4 handoff framing in §3.1.
- Stop if REPORT §6 uncovers a missing discovery that should have been logged; log it first, then resume.
- Stop if any public API surface changes are needed to satisfy the docs or sweep.
- Stop if `docs/provider_ports/ch_foen.md` would need architecture commitments rather than provider evidence.
- Stop if final verification cannot keep T117/T119/T120 green.

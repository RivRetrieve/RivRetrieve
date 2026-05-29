# 02-conformance-and-v1-closeout Plan

## 1. Goal and scope

Produce the V1 closeout evidence, not new feature behavior.

This step lands:

- `docs/v1-conformance.md`, an executor-authored architecture-conformance checklist that maps `architecture.md` §0-§18 to implemented behavior and §19 to explicit deferral evidence.
- Minimal gap-filler conformance tests only where existing tests do not provide an honest negative control.
- Final `docs/provider_ports/ch_foen.md` V1 feedback, including the M5 map closeout note and a reconciliation of the old token concern now that map rendering is packaged/offline.
- `docs/discoveries.md` closeout notes only if useful. Step 01 found no architecture contradiction, so do not add D11+ unless execution finds one. Record the status of D5, D6, D7, D9 as closeout context if doing so improves handoff clarity.
- Minimal README/user-facing documentation only because the V1 public API, including `rr.map_stations(...)`, is currently not documented for users.
- Full verification with `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, and `uv run pytest`.
- One patch-bumped commit and tag per D1.

Out of scope:

- `REPORT.md`. The orchestrator writes the final M5 report after this step closes.
- Any implementation change to `rr.map_stations`, provider runtime behavior, catalogue generation, observations, or the harness except narrowly scoped gap-filler tests.
- Any architecture amendment, second provider, §19 feature, wide-form export, RivRetrieve-derived product, or product vocabulary expansion.
- Promoting discoveries into `architecture.md`.

Hard rule: every conformance checklist entry must cite real tests or observable behavior that actually prove the claim, including a negative control where a regression could otherwise pass silently. If execution finds a §0-§18 commitment with no implementation milestone behind it, stop and escalate as a V1 sign-off blocker.

## 2. Deliverables

Primary artifact:

- `docs/v1-conformance.md`

Recommended structure for that artifact:

1. Purpose and verification date.
2. Evidence rules: named tests, observable behavior, and negative-control requirement.
3. Checklist table for `architecture.md` §0-§18.
4. §19 reaffirmed deferrals table.
5. Known structural/process commitments, clearly labeled.
6. Verification commands and results.
7. Coordinator follow-up queue, if any.

Checklist row format:

```text
Section | Commitment | Evidence | Negative control | Status
```

Column rationale:

- `Section`: keeps every row traceable to `architecture.md`.
- `Commitment`: one-line summary only; this prevents the checklist from becoming a second architecture document.
- `Evidence`: named tests and/or observable behavior that prove the positive claim.
- `Negative control`: named test that would fail if the commitment silently regressed, or an explicit structural/process control when a behavioral negative control is not meaningful.
- `Status`: `realized`, `deferred`, `structural/process`, or `blocker`. Do not use `realized` without evidence.

Do not place the checklist inside `REPORT.md`. Keep `docs/v1-conformance.md` separate so the orchestrator-authored report can reference it without mixing execution evidence and report narrative.

## 3. Intended architecture-evidence mapping

The executor should use the following as the intended citation map, then verify every test name before writing `docs/v1-conformance.md`. This table is planning evidence, not the final checklist rows.

| Architecture section | Existing positive evidence to cite | Existing negative control to cite | Planned gap-filler needed? |
| --- | --- | --- | --- |
| §0 Document roles and change process | `docs/provider_ports/ch_foen.md` exists as provider-port notes; `docs/discoveries.md` records D1-D10 without promoting local lessons into architecture; M1-M4 reports record no silent architecture drift. | `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion`, `tests/test_provider_handle.py::test_provider_handle_protocol_declares_exactly_seven_public_methods`, and `tests/test_offline_import.py::test_import_rivretrieve_does_not_import_providers_stubs_or_generators` structurally limit speculative public surface and imports. | No. Label no-speculative-abstractions as structural/process. |
| §1 Architectural goals | `tests/test_providers_empty_registry_returns_default_ch_foen`, `tests/test_global_stations_include_ch_foen_rows`, `tests/test_ch_foen_observations_2206_discharge_fallback_converts_to_m3s`, `tests/test_ch_foen_observations_2282_stage_instant_returns_all_samples`, `tests/test_ch_foen_observations_2016_temperature_daily_mean`. | `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion` blocks provider/API internals from root; the shared §19 absence controls prove V1 scope did not expand into derived products or non-river vocabulary. | Yes, but cite the §19 absence controls as shared evidence, not as independent §1-only controls. |
| §2 Provider identity | `tests/test_providers_empty_registry_returns_default_ch_foen`, `tests/test_providers_sorted_independent_of_registration_order`, `tests/test_registry_rejects_invalid_provider_id_format`, `tests/test_provider_lookup_malformed_id_is_membership_miss`, `tests/test_global_stations_aggregates_registered_packaged_artifacts`. | `tests/test_registry_rejects_provider_id_mismatch`, `tests/test_packaged_artifact_duplicate_station_key_raises_corrupt`, `tests/test_packaged_artifact_duplicate_station_product_key_raises_corrupt`. | No. |
| §3 Public API surface | `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface`, `tests/test_provider_handle_protocol_declares_exactly_seven_public_methods`, `tests/test_observations_wrapper_delegates_to_provider_handle`, `tests/test_map_stations_fake_backend_receives_filtered_station_frame`. | `tests/test_deferred_public_names_remain_absent_after_provider_handle_promotion`, `tests/test_observations_wrapper_requires_core_keywords`, `tests/test_map_stations_signature_has_no_on_issue_parameter`, `tests/test_map_stations_reads_stations_not_products`. | No. |
| §4 Packaged catalogue architecture | `tests/test_global_discovery_uses_reader_for_table_selection_and_validation`, `tests/test_ch_foen_catalogue_methods_return_catalog_results_with_provenance`, `tests/test_map_stations_uses_packaged_station_catalogue_only`. | `tests/test_import_rivretrieve_does_not_import_providers_stubs_or_generators`, `tests/test_ch_foen_generator_uses_committed_fixture_without_network`, `tests/test_map_stations_reads_stations_not_products`. | No. |
| §5 Live catalogue queries | `tests/test_catalogue_reader_live_products_warn_returns_empty_result_with_issue`, `tests/test_catalogue_reader_live_stations_warn_returns_empty_result_with_issue`, `tests/test_catalogue_reader_live_station_products_warn_returns_empty_result_with_issue`, plus the `ch_foen` capability tests. Label this row precisely: V1 realizes packaged default, unsupported-live warning/raise/ignore routing, live-never-mutates-packaged, and defensive fatal behavior for live-capable-but-unimplemented stubs; no V1 provider performs a real live fetch. | `tests/test_catalogue_reader_invalid_source_remains_direct_fatal_for_all_methods`, `tests/test_catalogue_reader_packaged_products_unchanged_by_live_capability`, `tests/test_catalogue_reader_live_capable_products_raise_defensive_fatal_for_every_on_issue`, `tests/test_catalogue_reader_live_capable_stations_raise_defensive_fatal_for_every_on_issue`, `tests/test_catalogue_reader_live_capable_station_products_raise_defensive_fatal_for_every_on_issue`, and the `..._raise_wraps_unsupported_issue` / `..._ignore_returns_issue_without_warning` live-source controls. | No. |
| §6 Catalogue result shape | `tests/test_m2_exit_criteria_public_surface_sweep`, `tests/test_ch_foen_catalogue_methods_return_catalog_results_with_provenance`, `tests/test_catalogue_reader_products_returns_packaged_catalog_result`. | `tests/test_global_discovery_disabled_defaults_empty_registry_returns_empty_catalog_result`, `tests/test_packaged_artifact_schema_wrong_dtype_raises_corrupt`. | No. |
| §7 Catalogue record model | `tests/test_catalogue_schema_objects_define_expected_columns`, `tests/test_metadata_column_is_opaque_json_object_string`, `tests/test_ch_foen_station_metadata_preserves_extra_fields`, `tests/test_ch_foen_generator_artifacts_validate_against_all_catalogue_schemas`. | `tests/test_metadata_column_rejects_non_object_json`, `tests/test_non_nullable_station_column_rejects_null`, `tests/test_availability_rejects_invalid_value`, duplicate-key/fk artifact tests. | No. |
| §8 Product dictionary | `docs/product_dictionary.md`; `tests/test_catalogue_reader_product_filters_are_exact_and_case_sensitive`; `tests/test_catalogue_reader_product_filters_do_not_parse_metadata`; `tests/test_ch_foen_generator_rejects_unknown_variable_code`. | Shared §19 vocabulary/derived absence tests plus `tests/test_catalogue_reader_product_filter_no_match_returns_empty_result`. Do not present the §19 controls as separate §8-only behavioral controls in the artifact. | Yes, explicit V1 vocabulary/derived absence, shared with §1/§19. |
| §9 Provider module contract | `tests/test_ch_foen_module_matches_provider_module_protocol`, `tests/test_stub_provider_module_satisfies_expanded_provider_module_protocol`, `tests/test_private_provider_handle_structurally_conforms_to_public_protocol`, `tests/test_provider_handle_protocol_method_signatures_match_tracker`. | `tests/test_deferred_public_names_remain_absent_after_provider_handle_promotion`, `tests/test_ch_foen_internal_metadata_import_does_not_leak_public_names`, `tests/test_import_rivretrieve_does_not_import_ch_foen_runtime_modules`. | No. |
| §10 Maintainer catalogue generation | `tests/test_ch_foen_generator_uses_committed_fixture_without_network`, `tests/test_ch_foen_generator_writes_artifacts`, `tests/test_ch_foen_generator_artifacts_validate_against_all_catalogue_schemas`. | `tests/test_import_rivretrieve_does_not_import_providers_stubs_or_generators`, `tests/test_ch_foen_generator_rejects_corrupt_fixture`, `tests/test_ch_foen_generator_provider_json_drift_is_limited_to_bulk_observations`. | No. |
| §11 Observation request | `tests/test_observation_request_from_single_station_product_normalizes_to_tuples`, `tests/test_provider_handle_observations_constructs_normalized_request_before_dispatch`, `tests/test_ch_foen_observations_multi_station_single_product_bulk`, `tests/test_ch_foen_observations_cross_product_bulk`. | `tests/test_observation_request_rejects_missing_start_for_every_on_issue`, `tests/test_provider_handle_observations_missing_start_raises_before_provider_execution`, `tests/test_observations_wrapper_requires_core_keywords`. | No. |
| §12 Observation result | `tests/test_observation_data_schema_accepts_canonical_long_table`, `tests/test_observation_result_constructs_with_exact_field_set`, `tests/test_observation_result_to_polars_returns_data_identity`, `tests/test_observation_result_to_pandas_matches_polars_boundary_conversion`, real `ch_foen` observation tests. | `tests/test_observation_data_schema_rejects_provider_id_column_as_extra_under_raise`, `tests/test_observation_result_rejects_schema_violation_for_every_on_issue`; planned no-wide-helper §19 test. | Yes, explicit no wide-form helper. |
| §13 Annotation schemas | `tests/test_ch_foen_row_annotation_schema_declares_m4_observation_names`, `tests/test_ch_foen_series_annotation_schema_declares_m4_observation_names`, `tests/test_ch_foen_row_annotations_all_declared_ids_are_emitted`, `tests/test_ch_foen_series_annotations_all_declared_ids_are_emitted`. | `tests/test_validate_annotation_names_rejects_undeclared_annotations_for_every_on_issue`, `tests/test_provider_handle_observations_undeclared_row_annotation_raises_direct_fatal`, `tests/test_provider_handle_observations_undeclared_series_annotation_raises_direct_fatal`. | No. |
| §14 Provenance | `tests/test_observation_provenance_constructs_without_scientific_metadata`, `tests/test_ch_foen_provenance_contains_sanitized_calls`, `tests/test_ch_foen_catalogue_methods_return_catalog_results_with_provenance`. | `tests/test_ch_foen_raw_payload_metadata_is_sanitized`, `tests/test_ch_foen_tests_tree_does_not_contain_public_token_literal`, `tests/test_ch_foen_observation_client_repr_redacts_token`. | No. |
| §15 Issues and error policy | `tests/test_on_issue_warn_emits_for_warning_and_error`, `tests/test_on_issue_raise_raises_for_warning_and_error`, `tests/test_ch_foen_on_issue_raise_converts_recoverable_issue`, `tests/test_ch_foen_missing_data_issue`. | `tests/test_fatal_contract_error_is_separate_from_on_issue`, `tests/test_corrupt_artifact_still_raises_under_ignore`, `tests/test_provider_unknown_raises_unknown_provider_error`, `tests/test_map_stations_missing_backend_raises_fatal_contract`. | No. |
| §16 Time and units | `tests/test_ch_foen_timestamp_generator_normalizes_utc`, `tests/test_ch_foen_timezone_ambiguity_issue`, `tests/test_ch_foen_flow_ls_generator_converts_value_before_result`, `tests/test_ch_foen_observations_2206_discharge_fallback_converts_to_m3s`. | `tests/test_ch_foen_unit_conversion_ambiguity_issue`, `tests/test_ch_foen_native_unit_returned_generator_serializes_json_array`, `tests/test_ch_foen_datetime_annotations_generator_serializes_iso_z`. | No. |
| §17 Multi-API providers and stitching | `tests/test_ch_foen_observations_decomposes_over_366_days_and_stitches`, `tests/test_ch_foen_provenance_contains_sanitized_calls`, `tests/test_ch_foen_partial_failure_returns_well_formed_result`. | `tests/test_ch_foen_overlap_annotation_and_issue`, `tests/test_ch_foen_conflict_annotation_and_issue`, `tests/test_ch_foen_gap_issue`, `tests/test_ch_foen_all_transport_calls_fail_returns_empty_with_issues`. | No. |
| §18 Reference provider and feedback loop | M3/M4 reports, `docs/provider_ports/ch_foen.md`, `tests/test_providers_empty_registry_returns_default_ch_foen`, `tests/test_providers_includes_ch_foen_after_discovery_call`, final provider-port update in this step. | `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion`, `tests/test_import_rivretrieve_does_not_import_ch_foen_runtime_modules`; no second-provider assertion via `test_providers_empty_registry_returns_default_ch_foen`. | No. Label feedback-loop parts as structural/process. |
| §19 Deferred design questions | Existing evidence: `result.to_pandas()` long-form tests; product dictionary says V1 vocabulary is discharge/stage/water_temperature; generated `ch_foen` product rows have `derived=False`. | Existing tests are suggestive but not direct enough for sign-off. Add explicit absence tests below. | Yes. |

If any test listed above has been renamed before execution, use `rg` and cite the current name. Do not cite stale names.

## 4. Gap-filler tests

Recommendation: add a small `tests/test_m5_exit_criteria.py`, following `tests/test_m1_exit_criteria.py` and `tests/test_m2_exit_criteria.py`, but keep it targeted to evidence gaps rather than duplicating the entire checklist.

Add these tests only if the current suite still lacks equivalent direct controls:

1. `test_v1_deferred_wide_form_helpers_remain_absent`
   - Construct or obtain an `ObservationResult`.
   - Assert `to_pandas()` is present and returns the canonical long table.
   - Assert expected wide-form helper names are absent, for example `to_wide`, `to_wide_pandas`, `to_pivot`, and `to_dataframe_wide`.
   - This proves §19 wide-form export remains deferred beyond long-form `to_pandas()`.

2. `test_v1_products_are_not_rivretrieve_derived`
   - Call `rr.products()`.
   - Assert the public product catalogue has no `derived=True` rows and all `derivation_method` values are null/none-equivalent for V1 rows.
   - This proves §19 derived products are not implemented.

3. `test_v1_observed_property_vocabulary_remains_river_gauge_scope`
   - Call `rr.products()`.
   - Assert observed properties are a subset of exactly `{"discharge", "stage", "water_temperature"}`.
   - Assert common deferred/non-river properties such as `precipitation`, `rainfall`, `catchment_rainfall`, and meteorological examples are absent.
   - This proves §19 vocabulary expansion is not silently implemented.

Do not add tests that require live network, `folium`, new provider code, new product rows, or architecture changes. If any gap-filler would require feature work rather than absence checks, stop and escalate.

## 5. Documentation updates

`docs/v1-conformance.md`:

- Author after all evidence and gap-filler tests are in place.
- Cite test names exactly.
- Include observable behavior only when a test alone is not the right evidence, such as the presence and content role of `docs/provider_ports/ch_foen.md`.
- For §0 and §18 process commitments, label rows as `structural/process` and explain the control. Do not pretend they are ordinary behavioral tests.
- For §19, use `deferred` status, not `realized`.

`docs/provider_ports/ch_foen.md`:

- Add a V1 map closeout note under Pain Points or a short M5/V1 section.
- State that `rr.map_stations(...)` consumes packaged station catalogue rows only, uses the existing latitude/longitude/country/provider fields, and does not touch observation transport, Influx token resolution, or live catalogue paths.
- Reconcile the old M5 token concern: token handling remains observation-only; map shipped without depending on token access.
- Keep the note provider-specific. Do not promote map implementation details into architecture.

`docs/discoveries.md`:

- Do not add D11+ unless execution finds an architecture contradiction. Step 01 reported none.
- Optionally add a short closeout note, not a new numbered discovery, recording:
  - D5 `__all__` remains a post-V1 hygiene candidate; T119/T120 still guard module attributes.
  - D6 path shadowing remains resolved by `_internal.providers`.
  - D7 and D9 did not fire in M4/M5 map work and should not become permanent lenses unless future provider code triggers them.
- Do not edit `architecture.md`.

README/user docs:

- Recommend a minimal `Usage` section because no user-facing V1 method is currently documented.
- Include only already-implemented behavior: `rr.providers()`, `rr.stations()`, `rr.products()`, provider-handle `observations(...)`, top-level `rr.observations(...)`, and `rr.map_stations(...)`.
- For map docs, mention the optional extra: `pip install rivretrieve[map]`.
- Do not add a tutorial, live-network promises, second-provider examples, wide-form export examples, derived products, or vocabulary expansion.

## 6. Files in execution order

1. Evidence audit
   - Re-run targeted `rg` over tests for every citation in §3.
   - Confirm no §0-§18 commitment lacks a backing milestone and evidence.
   - If a real implementation gap appears, stop and escalate before editing docs.

2. `tests/test_m5_exit_criteria.py`
   - Add only the §19 absence/gap-filler tests described in §4 if equivalent tests are still absent.
   - Keep tests offline and deterministic.

3. `docs/v1-conformance.md`
   - Add the final checklist artifact with row format from §2.
   - Cite actual test names and structural/process evidence.
   - Do not copy this plan's table verbatim as the final checklist; write the concise acceptance artifact.

4. `docs/provider_ports/ch_foen.md`
   - Add the final V1 map/token closeout note.

5. `docs/discoveries.md`
   - Add only the optional closeout note or any genuinely new D11+ contradiction discovered during execution.

6. `README.md`
   - Add minimal user-facing V1 usage docs only.

7. Verification
   - Run `uv run ruff format`.
   - Run `uv run ruff check --fix`.
   - Run `uv run ty check`.
   - Run `uv run pytest`.

8. Version bump and commit
   - Run `uv run bump-my-version bump patch`.
   - Re-run any verification command affected by formatting/version changes if needed.
   - Stage docs, tests, version files, and any tool-touched files.
   - Commit once.
   - Tag `v$(uv run bump-my-version show current_version)`.

## 7. Open questions and recommendations

Q1. Checklist location.

Recommendation: use `docs/v1-conformance.md`, not a section inside `REPORT.md`. This keeps the executor-authored acceptance artifact separate from the orchestrator-authored M5 report. The report can reference the checklist and add coordinator synthesis without owning the evidence rows.

Q2. Row format.

Recommendation: `Section | Commitment | Evidence | Negative control | Status`. These columns force traceability, prevent bare prose sign-off, and make the negative-control obligation visible. The `Status` column allows honest labels for `realized`, `deferred`, and `structural/process`.

Q3. Checklist-as-doc vs conformance tests.

Recommendation: map rows primarily to existing named tests. Add only `tests/test_m5_exit_criteria.py` with the three §19 absence controls if no equivalent direct tests exist. Do not write broad "architecture checklist" tests that duplicate documentation without improving regression detection.

Q4. Non-testable/process commitments.

Recommendation: label them honestly as `structural/process`. Use structural negative controls such as T119/T120, ProviderHandle exact-method tests, offline-import tests, and the existence/content of provider-port notes. Do not invent behavioral tests for "no speculative abstractions" or the feedback-loop process.

Q5. §19 reaffirmation evidence.

Recommendation:

- Wide-form helpers: negative control is the new absence test for wide helper method names, paired with existing `to_pandas()` long-form tests.
- Derived products: negative control is the new catalogue assertion that V1 public products have `derived=False` and no derivation method.
- Vocabulary expansion: negative control is the new observed-property assertion restricted to `discharge`, `stage`, and `water_temperature`, with deferred terms absent.

Q6. README map/user docs.

Recommendation: add a minimal `Usage` section. The current README only covers development commands, so V1 user behavior is effectively undocumented. Keep it compact and strictly limited to implemented APIs and the optional `map` extra.

## 8. Risks and stopping conditions

- Stop if any §0-§18 commitment has no implementation evidence from M1-M5. This is a V1 sign-off blocker.
- Stop if a proposed checklist row would cite a non-existent test, a renamed test not verified by `rg`, or a test that would pass even if the commitment regressed.
- Stop if proving a row requires feature work rather than a narrowly scoped negative-control test.
- Stop if execution starts implementing §19 work: wide-form helpers, RivRetrieve-derived products, or vocabulary expansion.
- Stop if any change reaches toward a second provider, live global discovery, plugin entry points, architecture amendments, or map-specific schema extensions.
- Stop if final verification cannot be made green with docs/test-only work; surface the blocker.

## 9. Verification plan

Required final commands:

```bash
uv run ruff format
uv run ruff check --fix
uv run ty check
uv run pytest
```

Expected test state before this step: 439 collected, 437 passed, 2 skipped offline, where the skips are folium-gated real-backend map tests. If `folium` is installed locally during execution, the skipped count may differ; report the actual count and explain the backend-dependent difference.

Expected post-gap-filler state, if the three §19 tests in `tests/test_m5_exit_criteria.py` are added, is about 442 collected with the same folium-skip caveat. Report the exact final count rather than treating 439 as the post-step target.

After verification:

```bash
uv run bump-my-version bump patch
git tag v$(uv run bump-my-version show current_version)
```

Commit once. The final answer should report changed files, verification results, any new conformance tests added, and whether any architecture-conformance blocker was found.

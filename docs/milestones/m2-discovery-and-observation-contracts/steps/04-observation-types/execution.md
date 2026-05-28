# 04-observation-types Execution

## 1. What shipped

- Commit: `75e0a10` (initial commit SHA before report-only amend).
- Tag: `v0.1.12`.
- Test count: `185` baseline to `286` collected items. The added logical inventory is T46-T83; parametrization expands the item count.
- Version: `0.1.11` to `0.1.12`.

## 2. Files added / modified

- Added `src/rivretrieve/_internal/observations.py`: internal observation schema constants, request/provenance/annotation/raw/result contracts, and validators.
- Added `tests/test_internal_observations.py`: T46-T82 logical inventory.
- Modified `src/rivretrieve/_internal/issues.py`: added the three step-04 fatal classes.
- Modified `tests/test_package.py`: extended T23 deferred public-name absence list without changing T22.
- Modified `pyproject.toml` / `uv.lock`: added `pyarrow` for Polars `DataFrame.to_pandas()` support and bumped version.
- Modified `src/rivretrieve/__init__.py`: version literal bump only.
- Added this `execution.md` alongside `plan.md` and `critique.md`.

## 3. Test enumeration T46-T83

- T46 PASS: `test_observation_request_from_single_station_product_normalizes_to_tuples`, `tests/test_internal_observations.py:108`.
- T47 PASS: `test_observation_request_from_sequences_preserves_order`, `tests/test_internal_observations.py:122`.
- T48 PASS: `test_observation_request_coerces_typed_temporal_inputs`, `tests/test_internal_observations.py:135`.
- T49 PASS: `test_observation_request_rejects_missing_provider_id_for_every_on_issue`, `tests/test_internal_observations.py:158`.
- T50 PASS: `test_observation_request_rejects_missing_start_for_every_on_issue`, `tests/test_internal_observations.py:173`.
- T51 PASS: `test_observation_request_rejects_missing_end_for_every_on_issue`, `tests/test_internal_observations.py:188`.
- T52 PASS: `test_observation_request_rejects_unparseable_temporal_values`, `tests/test_internal_observations.py:203`.
- T53 PASS: `test_observation_request_rejects_missing_stations_for_every_on_issue`, `tests/test_internal_observations.py:220`.
- T54 PASS: `test_observation_request_rejects_missing_products_for_every_on_issue`, `tests/test_internal_observations.py:235`.
- T55 PASS: `test_observation_request_rejects_empty_station_sequence_for_every_on_issue`, `tests/test_internal_observations.py:250`.
- T56 PASS: `test_observation_request_rejects_empty_product_sequence_for_every_on_issue`, `tests/test_internal_observations.py:265`.
- T57 PASS: `test_observation_request_rejects_non_string_and_empty_ids`, `tests/test_internal_observations.py:291`.
- T58 PASS: `test_observation_provenance_constructs_without_scientific_metadata`, `tests/test_internal_observations.py:309`.
- T59 PASS: `test_observation_provenance_metadata_may_be_json_string`, `tests/test_internal_observations.py:326`.
- T60 PASS: `test_annotation_schema_constructs_per_annotation_declaration`, `tests/test_internal_observations.py:336`.
- T61 PASS: `test_annotation_schema_declaration_reuses_catalogue_schema_pattern`, `tests/test_internal_observations.py:350`.
- T62 PASS: `test_annotation_schema_rejects_invalid_annotation_id`, `tests/test_internal_observations.py:361`.
- T63 PASS: `test_annotation_schema_rejects_invalid_value_type`, `tests/test_internal_observations.py:367`.
- T64 PASS: `test_annotation_table_validates_row_annotation_shape`, `tests/test_internal_observations.py:372`.
- T65 PASS: `test_annotation_table_validates_series_annotation_shape`, `tests/test_internal_observations.py:379`.
- T66 PASS: `test_annotation_table_rejects_missing_required_column`, `tests/test_internal_observations.py:386`.
- T67 PASS: `test_annotation_table_rejects_wrong_dtype`, `tests/test_internal_observations.py:391`.
- T68 PASS: `test_validate_annotation_names_accepts_declared_annotation_ids`, `tests/test_internal_observations.py:398`.
- T69 PASS: `test_validate_annotation_names_rejects_undeclared_annotations_for_every_on_issue`, `tests/test_internal_observations.py:405`.
- T70 PASS: `test_validate_annotation_names_accepts_multiple_provider_schemas`, `tests/test_internal_observations.py:415`.
- T71 PASS: `test_raw_payload_constructs_minimal_payload`, `tests/test_internal_observations.py:427`.
- T72 PASS: `test_observation_data_schema_accepts_canonical_long_table`, `tests/test_internal_observations.py:439`.
- T73 PASS: `test_observation_data_schema_accepts_native_datetime_without_utc_mandate`, `tests/test_internal_observations.py:445`.
- T74 PASS: `test_observation_data_schema_rejects_provider_id_column_as_extra_under_raise`, `tests/test_internal_observations.py:463`.
- T75 PASS: `test_observation_data_schema_rejects_missing_column`, `tests/test_internal_observations.py:474`.
- T76 PASS: `test_observation_data_schema_rejects_wrong_dtype`, `tests/test_internal_observations.py:492`.
- T77 PASS: `test_observation_data_schema_rejects_null_identity_columns`, `tests/test_internal_observations.py:509`.
- T78 PASS: `test_observation_data_schema_allows_null_value`, `tests/test_internal_observations.py:517`.
- T79 PASS: `test_observation_result_constructs_with_exact_field_set`, `tests/test_internal_observations.py:523`.
- T80 PASS: `test_observation_result_to_polars_returns_data_identity`, `tests/test_internal_observations.py:538`.
- T81 PASS: `test_observation_result_to_pandas_matches_polars_boundary_conversion`, `tests/test_internal_observations.py:544`.
- T82 PASS: `test_observation_result_rejects_schema_violation_for_every_on_issue`, `tests/test_internal_observations.py:551`.
- T83 PASS: `test_deferred_public_names_remain_absent_after_catalogue_surface`, `tests/test_package.py:18`.

## 4. Negative-control inventory

- T49-T57: all `ObservationRequest` fatal cases raise `InvalidObservationRequestError` directly across ignored local `on_issue` values and assert no `IssuePolicyError` chain.
- T69: undeclared annotation names raise `AnnotationSchemaViolationError` directly across ignored local `on_issue` values and assert no `IssuePolicyError` chain.
- T74: extra `provider_id` column is detected before `validate_catalogue`; the raised `ObservationDataSchemaError` has no `IssuePolicyError` in cause/context.
- T75-T77, T82: observation schema failures raise `ObservationDataSchemaError` directly across ignored local `on_issue` values and assert no `IssuePolicyError` chain.
- T80: `ObservationResult.to_polars()` returns `self.data` by identity.
- T81: `ObservationResult.to_pandas()` equals `self.data.to_pandas()` exactly; no widening or annotation join.
- T83: T23 public absence list includes all new internal observation names and fatal exception names; T22 public present set is unchanged.
- T24: offline import sentinel still passes at `tests/test_offline_import.py:7`.
- T25: stub catalogue methods still raise `NotImplementedError` at `tests/test_internal_registry.py:139`, `tests/test_internal_registry.py:149`, and `tests/test_internal_registry.py:159`.

## 5. Deviations from plan §6

- Added `pyarrow` as a runtime dependency because the required `ObservationResult.to_pandas() == self.data.to_pandas()` behavior cannot execute in this environment without Polars' pandas conversion dependency. The method itself remains exactly `self.data.to_pandas()`.
- No architecture contradiction was found; no D3 entry was added.

## 6. Surprises

- Pydantic frozen models with `arbitrary_types_allowed=True` accepted `pl.DataFrame` as expected.
- `validate_catalogue(..., on_issue="raise")` does route extra columns through `IssuePolicyError`; the explicit observation extra-column pre-check is necessary and is covered by T74.
- The datetime no-UTC mandate did require a custom datetime-kind path: Polars requires fully specified `pl.Datetime()` schema dtypes, and timezone-aware frames need validation against the actual datetime dtype while preserving the canonical `time` column contract.

## 7. Ready for step 05

Step 04 is ready for step 05. The internal contracts exist without public exports, provider-module protocol changes, `_ProviderHandle` changes, or observation retrieval behavior.

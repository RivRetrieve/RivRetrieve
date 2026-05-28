# 02-observation-retrieval-and-bulk Execution

## 1. What Landed

- `src/rivretrieve/_internal/providers/ch_foen/query.py` - added product policies, product validation against packaged `products.parquet`, Flux query construction, 366-day window decomposition, native-unit mapping, and compact `provider_query_fields` JSON serialization.
- `src/rivretrieve/_internal/providers/ch_foen/observation_client.py` - replaced the constructor-only shell with transport injection, default HTTP POST transport, constructor/env/embedded token resolution, runtime Authorization headers, and redacted repr.
- `tests/test_ch_foen_observation_client.py` - updated client tests for optional token defaults, injected transport, redacted repr, and token resolution order.
- `src/rivretrieve/_internal/providers/ch_foen/raw_payload.py` - added sanitized station/product/window metadata fields to raw CSV response records.
- `src/rivretrieve/_internal/providers/ch_foen/parser.py` - changed `ChFoenObservationParserError` to subclass `FatalContractError` and added recoverable timezone-ambiguity detection for synthetic offsetless timestamps.
- `src/rivretrieve/_internal/providers/ch_foen/transform.py` - added native-field preference/fallback selection, `flow_ls` L/s -> m3/s conversion, daily aggregation, instant filtering, gap/overlap/conflict/unit-ambiguity handling, and row/series annotation generation.
- `src/rivretrieve/_internal/providers/ch_foen/retrieval.py` - added N x M request decomposition, per-window transport calls, parser integration, stitching, raw/provenance assembly, issue accumulation, one-shot `apply_on_issue`, and sanitized metadata assertions.
- **Atomic placeholder-removal checkpoint:** `src/rivretrieve/_internal/providers/ch_foen/issue_codes.py`, `src/rivretrieve/_internal/providers/ch_foen/module.py`, `tests/test_ch_foen_module.py`, and `tests/test_ch_foen_registration.py` removed `observations_not_yet_implemented`, delegated module observations to retrieval, and replaced placeholder tests with fixture-backed real retrieval tests.
- `tests/test_ch_foen_observations.py` - added public-handle fixture, bulk, failure, provenance/raw, annotation coverage, D8 generator-side encoding, and network-bypass tests.
- `src/rivretrieve/__init__.py` and `pyproject.toml` - patch-bumped `0.1.19` -> `0.1.20`.

## 2. Test Count Delta and Negative Controls

- Starting point from handoff: 385 tests passing.
- End state: 416 tests passing.
- Delta: +31 tests.
- T119 `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface`: unchanged and passing.
- T120 `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion`: unchanged and passing.
- Offline import `tests/test_offline_import.py::test_import_rivretrieve_does_not_import_providers_stubs_or_generators`: passing.
- Network-bypass sentinel `tests/test_ch_foen_observations.py::test_ch_foen_observation_client_default_transport_is_not_used_in_tests`: passing.
- Token-literal absence `tests/test_ch_foen_observations.py::test_ch_foen_tests_tree_does_not_contain_public_token_literal`: passing.
- T119/T120 still pin the same public surface; no `rr.observations` wrapper landed.

## 3. Two-Channel Routing Summary

| Plan row | Implementation |
| --- | --- |
| Provider has no observation module registered | Implemented by existing `_ProviderHandle.observations` module-presence guard. |
| Missing `start` | Implemented by existing `ObservationRequest.from_inputs`; negative control `test_ch_foen_missing_start_raises_before_provider_execution`. |
| Missing `end` | Implemented by existing `ObservationRequest.from_inputs`; provider module is not reached. |
| Empty/malformed stations/products input | Implemented by existing `ObservationRequest.from_inputs`; unchanged M2 tests cover request normalization. |
| Unsupported product ID | Implemented at `query.resolve_product_policy`; raises `InvalidObservationRequestError` before transport. |
| Malformed CSV bytes | Implemented at `parser.parse_ch_foen_observation_csv`; raises `ChFoenObservationParserError(FatalContractError)`. |
| Missing required Flux CSV columns | Implemented at `parser.parse_ch_foen_observation_csv`; raises `ChFoenObservationParserError(FatalContractError)`. |
| Unknown native unit/conversion rule in code | Fatal for real policy drift via `query.native_unit_for`; synthetic provider ambiguity is recoverable at `transform._select_points`. |
| Transformed result violates schema | Implemented by `ObservationResult` construction in `retrieval.retrieve_observations`. |
| Annotation table wrong columns/dtypes | Implemented by `AnnotationTable` construction in `retrieval.retrieve_observations`. |
| Undeclared annotation emitted | Implemented by existing `_ProviderHandle.observations` always-on `validate_annotation_names`. |
| Provenance/raw metadata would include auth | Implemented at `retrieval._assert_sanitized`; direct `FatalContractError`. |
| Invalid `on_issue` value | Existing issue-policy contract; no ch_foen issue created. |
| Empty successful CSV / parser no records | Implemented at `parser._missing_data_issue`, scoped in `retrieval._scope_issue`, routed once by `retrieval.retrieve_observations`. |
| All windows technically succeed but filtering removes rows | Implemented at `transform.transform_series`; emits `missing_data`, routed by retrieval. |
| One call fails while another succeeds | Implemented at `retrieval.retrieve_observations` / `_source_request_failed`; emits `source_request_failed` plus request-level `partial_response`. |
| Every transport call fails | Implemented at `retrieval.retrieve_observations`; emits per-call `source_request_failed` plus request-level `missing_data`, no `partial_response`. |
| Parser recoverable row drops | Implemented at `parser.parse_ch_foen_observation_csv`, scoped by `retrieval._scope_issue`, routed by retrieval. |
| N x M partial result | Implemented at `retrieval.retrieve_observations`; request-level `partial_response` when failures and successes both occur. |
| Daily missing days | Implemented at `transform._gap_issues`; emits `gap`. |
| Instant concrete window/range gap | No speculative irregular-sampling gap emitted; only concrete transformed evidence routes through `transform._gap_issues` where applicable. |
| Duplicate same canonical value | Implemented at `transform.stitch_transformed_series`; emits `overlap`. |
| Duplicate/conflicting canonical value or preferred/fallback disagreement | Implemented at `transform._select_points` and `transform.stitch_transformed_series`; emits `conflict` and alternative annotations. |
| Preferred and fallback fields in one window | Implemented at `transform._select_points`; preferred wins at shared timestamps, fallback fills missing timestamps, annotations record fallback use. |
| Unit conversion ambiguity | Implemented at `transform._select_points`; recoverable synthetic path emits `unit_conversion_ambiguity`. |
| Timezone ambiguity | Implemented at `parser.parse_ch_foen_observation_csv` plus `retrieval.retrieve_observations`; recoverable issue and `timezone_mismatch_flag=true`. |

## 4. Annotation Emission Audit

Row annotations:

- `native_field` - `test_ch_foen_row_annotations_all_declared_ids_are_emitted`.
- `native_unit` - `test_ch_foen_observations_2206_discharge_fallback_converts_to_m3s`.
- `converted_unit` - `test_ch_foen_observations_2206_discharge_fallback_converts_to_m3s`.
- `source_endpoint_or_query` - `test_ch_foen_row_annotations_all_declared_ids_are_emitted`.
- `raw_value` - `test_ch_foen_float_annotations_generator_serializes_decimal_utf8`.
- `alternative_native_field` - `test_ch_foen_overlap_annotation_and_issue`.
- `alternative_raw_value` - `test_ch_foen_float_annotations_generator_serializes_decimal_utf8`.
- `alternative_native_unit` - `test_ch_foen_row_annotations_all_declared_ids_are_emitted`.

Series annotations:

- `preferred_source` - `test_ch_foen_series_annotations_all_declared_ids_are_emitted`.
- `fallback_source_used` - `test_ch_foen_boolean_annotations_generator_serializes_utf8`.
- `native_unit_returned` - `test_ch_foen_native_unit_returned_generator_serializes_json_array`.
- `converted_unit` - `test_ch_foen_series_annotations_all_declared_ids_are_emitted`.
- `returned_time_range_start` - `test_ch_foen_datetime_annotations_generator_serializes_iso_z`.
- `returned_time_range_end` - `test_ch_foen_datetime_annotations_generator_serializes_iso_z`.
- `resolved_timezone` - `test_ch_foen_series_annotations_all_declared_ids_are_emitted`.
- `timezone_mismatch_flag` - `test_ch_foen_boolean_annotations_generator_serializes_utf8` and true path in `test_ch_foen_timezone_ambiguity_issue`.
- `provider_endpoint` - `test_ch_foen_series_annotations_all_declared_ids_are_emitted`.
- `provider_query_fields` - `test_ch_foen_provider_query_fields_generator_serializes_json`.

## 5. Asymmetric-Encoding Round-Trip Status

- Test 25 `test_ch_foen_provider_query_fields_generator_serializes_json`: compact sorted JSON string with `windows` array round-trips through `json.loads`.
- Test 26 `test_ch_foen_boolean_annotations_generator_serializes_utf8`: booleans emit exact `"true"` / `"false"` Utf8 strings.
- Test 27 `test_ch_foen_datetime_annotations_generator_serializes_iso_z`: datetimes emit exact UTC ISO strings ending in `Z`.
- Test 28 `test_ch_foen_float_annotations_generator_serializes_decimal_utf8`: float annotations emit `format(value, ".15g")` strings.
- Test 29 `test_ch_foen_native_unit_returned_generator_serializes_json_array`: native units emit compact sorted JSON-array strings.
- Test 30 `test_ch_foen_flow_ls_generator_converts_value_before_result`: canonical result values are generated in `m3/s`.
- Test 31 `test_ch_foen_timestamp_generator_normalizes_utc`: result timestamps are generated as UTC Polars datetimes.

## 6. Token Policy Outcome

The embedded public token literal lives only in the private constant `observation_client._EMBEDDED_PUBLIC_TOKEN`. Retrieval touches it only through `ChFoenObservationClient.resolved_token`, which is inserted into the runtime Authorization header. It is not copied into provenance, raw metadata, issues, logs, fixtures, or tests. Test 20 confirms the literal is absent under `tests/`; test 34 confirms constructor token overrides env, env overrides the embedded credential, and `token=None` is accepted.

## 7. Tactical Fixes

- Replaced stale placeholder registration tests with injected-transport real retrieval tests after the ch_foen slice revealed they could touch the live default transport.
- Kept row-annotation `time` as the M2 no-timezone annotation dtype while observation data remains UTC, matching the existing annotation schema validator.
- Added synthetic timezone-ambiguity propagation so `timezone_mismatch_flag=true` has an emission path without changing fixture timezone interpretation.
- Used provider-private `RawPayload.metadata` JSON rather than exposing `ChFoenRawPayload` through the public result field, preserving sanitized raw metadata while staying within the existing `ObservationResult.raw` type.

## 8. New Discoveries

No D11+ discovery was appended. `L_D7_probe` did not fire because no new Pydantic model with `extra="allow"` was introduced. `L_D9_probe` did not fire because JSON work is serialization-only for annotations/raw metadata; no JSON provider walk was added.

## 9. Next Step Notes

- `bulk_observations` is now behaviorally true for provider-handle observations, but the descriptive capability flag remains unchanged for step 03 to decide.
- Step 03 delegation-spy tests can assert that the root wrapper delegates to `rr.provider("ch_foen").observations(...)` / provider-handle observations and receives a real `ObservationResult`.
- New internal-only symbols landed under `_internal/providers/ch_foen/`: `query.py`, `transform.py`, `retrieval.py`, and transport dataclasses in `observation_client.py`. None are exported at package root.
- T119/T120 expansion remains a step 03 concern; this step deliberately did not add `rr.observations`.

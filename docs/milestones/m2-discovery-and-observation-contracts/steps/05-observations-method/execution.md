# 05-observations-method Execution

## 1. What shipped

- Commit: this commit, tagged `v0.1.13`.
- Tag: `v0.1.13`.
- Test count delta: `286 -> 326` collected tests (`+40`). Logical inventory T84-T109 is covered; parametrization expands T88-T94 and T97-T98.
- Version: `0.1.12 -> 0.1.13`.

## 2. Files added / modified

Added:

- `tests/test_internal_handle_observations.py`
- `docs/milestones/m2-discovery-and-observation-contracts/steps/05-observations-method/execution.md`

Modified:

- `pyproject.toml`
- `src/rivretrieve/__init__.py`
- `src/rivretrieve/_internal/issues.py`
- `src/rivretrieve/_internal/observations.py`
- `src/rivretrieve/_internal/provider_module.py`
- `src/rivretrieve/_internal/registry.py`
- `tests/_stubs/stub_provider.py`
- `tests/conftest.py`
- `tests/test_internal_provider_module.py`
- `tests/test_internal_registry.py`
- `tests/test_package.py`

Step artifacts committed with implementation:

- `docs/milestones/m2-discovery-and-observation-contracts/steps/05-observations-method/plan.md`
- `docs/milestones/m2-discovery-and-observation-contracts/steps/05-observations-method/critique.md`
- `docs/milestones/m2-discovery-and-observation-contracts/steps/05-observations-method/execution.md`

## 3. Test enumeration T84-T109

- T84 PASS: `test_provider_handle_observations_single_station_product_returns_valid_result`, `tests/test_internal_handle_observations.py:129`.
- T85 PASS: `test_provider_handle_observations_bulk_station_product_returns_valid_result`, `tests/test_internal_handle_observations.py:201`.
- T86 PASS: `test_provider_handle_observations_unknown_station_or_product_returns_empty_result`, `tests/test_internal_handle_observations.py:217`.
- T87 PASS: `test_provider_handle_observations_constructs_normalized_request_before_dispatch`, `tests/test_internal_handle_observations.py:233`.
- T88 PASS: `test_provider_handle_observations_passes_on_issue_to_module`, `tests/test_internal_handle_observations.py:265`.
- T89 PASS: `test_provider_handle_observations_missing_start_raises_before_provider_execution`, `tests/test_internal_handle_observations.py:291`.
- T90 PASS: `test_provider_handle_observations_missing_end_raises_before_provider_execution`, `tests/test_internal_handle_observations.py:319`.
- T91 PASS: `test_provider_handle_observations_empty_stations_raises_before_provider_execution`, `tests/test_internal_handle_observations.py:347`.
- T92 PASS: `test_provider_handle_observations_empty_products_raises_before_provider_execution`, `tests/test_internal_handle_observations.py:375`.
- T93 PASS: `test_provider_handle_observations_bad_station_product_types_raise_before_provider_execution`, `tests/test_internal_handle_observations.py:403`.
- T94 PASS: `test_provider_handle_observations_no_module_registered_raises_direct_fatal_for_every_on_issue`, `tests/test_internal_handle_observations.py:431`.
- T95 PASS: `test_provider_handle_row_annotation_schema_no_module_registered_raises_direct_fatal`, `tests/test_internal_handle_observations.py:449`.
- T96 PASS: `test_provider_handle_series_annotation_schema_no_module_registered_raises_direct_fatal`, `tests/test_internal_handle_observations.py:458`.
- T97 PASS: `test_provider_handle_observations_undeclared_row_annotation_raises_direct_fatal`, `tests/test_internal_handle_observations.py:468`.
- T98 PASS: `test_provider_handle_observations_undeclared_series_annotation_raises_direct_fatal`, `tests/test_internal_handle_observations.py:491`.
- T99 PASS: `test_provider_handle_observations_validates_row_and_series_annotation_names`, `tests/test_internal_handle_observations.py:513`.
- T100 PASS: `test_provider_handle_row_annotation_schema_delegates_to_module`, `tests/test_internal_handle_observations.py:551`.
- T101 PASS: `test_provider_handle_series_annotation_schema_delegates_to_module`, `tests/test_internal_handle_observations.py:555`.
- T102 PASS: `test_stub_provider_module_satisfies_expanded_provider_module_protocol`, `tests/test_internal_provider_module.py:19`.
- T103 PASS: `test_stub_catalogue_functions_remain_explicitly_unimplemented`, `tests/test_internal_provider_module.py:52`.
- T104 PASS: `test_registry_register_with_module_round_trips_handle_dispatch`, `tests/test_internal_registry.py:39`.
- T105 PASS: `test_registry_register_artifact_only_remains_back_compatible`, `tests/test_internal_registry.py:61`.
- T106 PASS: `test_registered_stub_fixture_registers_artifact_and_module_in_fresh_registry_only`, `tests/test_internal_handle_observations.py:559`.
- T107 PASS: `test_stub_provider_does_not_register_at_import_time`, `tests/test_internal_provider_module.py:44`.
- T108 PASS: `test_import_rivretrieve_does_not_import_providers_stubs_or_generators`, `tests/test_offline_import.py:7`.
- T109 PASS: `test_deferred_public_names_remain_absent_after_catalogue_surface`, `tests/test_package.py:18`.

Final gates:

- `uv run ruff format`: pass
- `uv run ruff check --fix`: pass
- `uv run ty check`: pass
- `uv run pytest`: pass, `326 passed`

## 4. Negative-control inventory

- T89-T93: registered-module request fatals raise `InvalidObservationRequestError` before provider execution; each parametrized case asserts `_issue_policy_error_chain(exc) == []` and spy not called.
- T94-T96: artifact-only handles raise `ObservationsUnavailableError` directly for observations and both schema methods; T94 asserts no `IssuePolicyError` chain across all `on_issue` values.
- T97-T98: undeclared row and series annotations raise `AnnotationSchemaViolationError` directly across all `on_issue` values with no `IssuePolicyError` chain.
- T99: distinct `row.bad` and `series.bad` module results prove both row and series annotation-name validation paths execute.
- T102: the test stub satisfies the expanded seven-member `ProviderModule` Protocol.
- T103: `products`, `stations`, and `station_products` still raise `NotImplementedError`.
- T106: `registered_stub` uses a fresh registry carrying artifact plus module, while module-level `_registry` remains empty.
- T107: importing `tests._stubs.stub_provider` still performs no registration.
- T108: subprocess `import rivretrieve` still avoids importing `tests._stubs`.
- T109: public surface still excludes `ObservationsUnavailableError`, `ProviderModule`, and `_ProviderHandle`.

## 5. Deviations from plan §6

- No behavioral deviations. `ObservationRequest.from_inputs(...)` input annotations were widened to `object` so the loose handle surface type-checks while the factory continues to own malformed-input fatal validation.
- No architecture contradiction was found; no D3 entry was added.

## 6. Surprises

- The `provider_module.py` / `registry.py` import path did not create a circular import.
- The `@staticmethod` Protocol pattern worked cleanly with module instances and `isinstance(stub_provider, ProviderModule)`.
- Pydantic frozen `ObservationResult` accepted the stub Polars frames as expected with the existing `arbitrary_types_allowed=True`.
- `ty` correctly forced the public-input boundary to be explicit: handle inputs are loose, and provider modules receive only the normalized `ObservationRequest`.

## 7. Ready for step 06

Step 05 is ready for step 06. Observation dispatch exists on the private handle only, annotation-name validation is always-on for both row and series tables, registry module binding is back-compatible, and the public package surface is unchanged.

# 01-provider-info-and-module-contract Execution

## 1. What shipped

- Commit: this commit, tagged `v0.1.9`
- Tag: `v0.1.9`
- Test count delta: `91 -> 123` collected tests (`+32`) covering T01-T17.
- Version: `0.1.8 -> 0.1.9`.

## 2. Files added / modified

Added:

- `src/rivretrieve/_internal/provider_info.py`
- `src/rivretrieve/_internal/provider_module.py`
- `tests/__init__.py`
- `tests/_stubs/__init__.py`
- `tests/_stubs/stub_provider.py`
- `tests/test_internal_provider_info.py`
- `tests/test_internal_provider_module.py`
- `docs/milestones/m2-discovery-and-observation-contracts/steps/01-provider-info-and-module-contract/execution.md`

Modified:

- `pyproject.toml`
- `src/rivretrieve/__init__.py`
- `src/rivretrieve/_internal/registry.py`
- `tests/conftest.py`
- `tests/test_internal_registry.py`
- `tests/test_offline_import.py`
- `tests/test_package.py`
- `uv.lock`

Step artifacts committed with implementation:

- `docs/milestones/m2-discovery-and-observation-contracts/steps/01-provider-info-and-module-contract/plan.md`
- `docs/milestones/m2-discovery-and-observation-contracts/steps/01-provider-info-and-module-contract/critique.md`
- `docs/milestones/m2-discovery-and-observation-contracts/steps/01-provider-info-and-module-contract/execution.md`

## 3. Test enumeration

- T01 pass: `tests/test_internal_provider_info.py::test_provider_info_from_row_matches_provider_info_catalog_contract`
- T02 pass: `tests/test_internal_provider_info.py::test_provider_info_to_row_round_trips_catalogue_row`
- T03 pass: `tests/test_internal_provider_info.py::test_provider_info_metadata_is_raw_json_string`
- T04 pass: `tests/test_internal_provider_info.py::test_provider_info_rejects_missing_required_field`
- T05 pass: `tests/test_internal_provider_info.py::test_provider_info_rejects_wrong_field_type`
- T06 pass: `tests/test_internal_provider_info.py::test_provider_info_rejects_invalid_metadata_json`
- T07 pass: `tests/test_internal_provider_info.py::test_provider_info_rejects_non_object_metadata_json`
- T08 pass: `tests/test_internal_registry.py::test_provider_handle_info_fatal_failures_are_direct`
- T09 pass: `tests/test_internal_registry.py::test_provider_handle_info_reads_packaged_artifact_row`
- T10 pass: `tests/test_internal_registry.py::test_provider_handle_info_malformed_artifact_row_raises_provider_info_validation_error`
- T11 pass: `tests/test_internal_provider_module.py::test_stub_provider_module_has_provider_module_attributes`
- T12 pass: `tests/test_internal_provider_module.py::test_stub_provider_info_matches_registered_handle_info`
- T13 pass: `tests/test_internal_provider_module.py::test_stub_provider_registers_into_fresh_registry_only`
- T14 pass: `tests/test_internal_provider_module.py::test_stub_provider_does_not_register_at_import_time`
- T15 pass: `tests/test_offline_import.py::test_import_rivretrieve_does_not_import_providers_or_generators`
- T16 pass: `tests/test_package.py::test_init_public_surface_exports_m1_discovery_only`
- T17 pass: `tests/test_internal_provider_module.py::test_stub_catalogue_functions_are_explicitly_unimplemented_in_step_01`

Final gates:

- `uv run ruff format`: pass
- `uv run ruff check --fix`: pass
- `uv run ty check`: pass
- `uv run pytest`: pass, `123 passed`

## 4. Negative-control inventory

- T13 fresh-registry-only registration: `tests/test_internal_provider_module.py:23`
- T14 no stub registration at import time: `tests/test_internal_provider_module.py:29`
- T15 offline import keeps `tests._stubs` absent: `tests/test_offline_import.py:16`
- T16 public surface excludes `ProviderInfo`, `ProviderModule`, and `ProviderHandle`: `tests/test_package.py:15`
- T17 catalogue functions remain explicitly unimplemented: `tests/test_internal_provider_module.py:36`

Additional direct-fatal negative control:

- `_ProviderHandle.info()` raises `ProviderInfoValidationError` without `IssuePolicyError` in the exception chain: `tests/test_internal_registry.py:88`

## 5. Deviations from plan §6

- Added `tests/__init__.py` so the required `tests._stubs.stub_provider` module path is importable under pytest and in subprocess checks. This is a packaging marker only; it performs no registration and has no import side effects.

## 6. Surprises

- `pl.DataFrame(..., schema=...)` can coerce some wrong Python values into the requested dtype. `ProviderInfo.from_row` therefore builds strict one-value `pl.Series` columns before calling `validate_catalogue`, preserving the plan's wrong-dtype fatal behavior while still reusing `ProviderInfoCatalog`.
- No D3 entry needed; this was an implementation detail, not an architecture contradiction.

## 7. Ready for step 02

Ready. The private `_ProviderHandle.info()` contract is in place, `ProviderModule` is limited to the four step-01 members, the tests-only stub is isolated from global discovery state, and the public package surface remains unchanged apart from the version bump.

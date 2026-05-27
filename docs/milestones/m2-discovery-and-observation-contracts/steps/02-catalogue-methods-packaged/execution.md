# 02-catalogue-methods-packaged Execution

## 1. What shipped

- Commit: this commit, tagged `v0.1.10`
- Tag: `v0.1.10`
- Test count delta: `123 -> 150` collected tests (`+27`) covering T01-T27.
- Version: `0.1.9 -> 0.1.10`.

## 2. Files added / modified

Added:

- `src/rivretrieve/_internal/catalogue_reader.py`
- `tests/test_internal_catalogue_reader.py`
- `docs/milestones/m2-discovery-and-observation-contracts/steps/02-catalogue-methods-packaged/execution.md`

Modified:

- `pyproject.toml`
- `src/rivretrieve/__init__.py`
- `src/rivretrieve/_internal/discovery.py`
- `src/rivretrieve/_internal/issues.py`
- `src/rivretrieve/_internal/registry.py`
- `tests/conftest.py`
- `tests/test_discovery.py`
- `tests/test_internal_provider_module.py`
- `tests/test_internal_registry.py`
- `tests/test_offline_import.py`
- `tests/test_package.py`
- `uv.lock`

Step artifacts committed with implementation:

- `docs/milestones/m2-discovery-and-observation-contracts/steps/02-catalogue-methods-packaged/plan.md`
- `docs/milestones/m2-discovery-and-observation-contracts/steps/02-catalogue-methods-packaged/critique.md`
- `docs/milestones/m2-discovery-and-observation-contracts/steps/02-catalogue-methods-packaged/execution.md`

## 3. Test enumeration

- T01 pass: `tests/test_internal_catalogue_reader.py::test_catalogue_reader_products_returns_packaged_catalog_result` at `tests/test_internal_catalogue_reader.py:62`
- T02 pass: `tests/test_internal_catalogue_reader.py::test_catalogue_reader_stations_returns_packaged_catalog_result` at `tests/test_internal_catalogue_reader.py:76`
- T03 pass: `tests/test_internal_catalogue_reader.py::test_catalogue_reader_station_products_returns_packaged_catalog_result` at `tests/test_internal_catalogue_reader.py:90`
- T04 pass: `tests/test_internal_catalogue_reader.py::test_catalogue_reader_product_filters_are_exact_and_case_sensitive` at `tests/test_internal_catalogue_reader.py:104`
- T05 pass: `tests/test_internal_catalogue_reader.py::test_catalogue_reader_product_filter_no_match_returns_empty_result` at `tests/test_internal_catalogue_reader.py:122`
- T06 pass: `tests/test_internal_catalogue_reader.py::test_catalogue_reader_product_filters_do_not_parse_metadata` at `tests/test_internal_catalogue_reader.py:132`
- T07 pass: `tests/test_internal_catalogue_reader.py::test_catalogue_reader_station_products_filters_station_ids` at `tests/test_internal_catalogue_reader.py:140`
- T08 pass: `tests/test_internal_catalogue_reader.py::test_catalogue_reader_station_products_empty_sequence_matches_none` at `tests/test_internal_catalogue_reader.py:148`
- T09 pass: `tests/test_internal_catalogue_reader.py::test_catalogue_reader_station_products_unknown_ids_are_dropped` at `tests/test_internal_catalogue_reader.py:160`
- T10 pass: `tests/test_internal_catalogue_reader.py::test_catalogue_reader_invalid_source_raises_direct_fatal` at `tests/test_internal_catalogue_reader.py:175`
- T11 pass: `tests/test_internal_catalogue_reader.py::test_catalogue_reader_invalid_source_ignores_on_issue_policy` at `tests/test_internal_catalogue_reader.py:192`
- T12 pass: `tests/test_internal_catalogue_reader.py::test_catalogue_reader_non_string_filter_raises_direct_fatal` at `tests/test_internal_catalogue_reader.py:204`
- T13 pass: `tests/test_internal_registry.py::test_provider_handle_products_reads_artifact_not_provider_module` at `tests/test_internal_registry.py:138`
- T14 pass: `tests/test_internal_registry.py::test_provider_handle_stations_reads_artifact_not_provider_module` at `tests/test_internal_registry.py:148`
- T15 pass: `tests/test_internal_registry.py::test_provider_handle_station_products_reads_artifact_not_provider_module` at `tests/test_internal_registry.py:158`
- T16 pass: `tests/test_internal_registry.py::test_provider_handle_catalogue_methods_have_registered_provider_provenance` at `tests/test_internal_registry.py:168`
- T17 pass: `tests/test_discovery.py::test_global_stations_aggregates_registered_packaged_artifacts` at `tests/test_discovery.py:138`
- T18 pass: `tests/test_discovery.py::test_global_products_aggregates_registered_packaged_artifacts` at `tests/test_discovery.py:154`
- T19 pass: `tests/test_discovery.py::test_global_product_info_matches_products_contract` at `tests/test_discovery.py:170`
- T20 pass: `tests/test_discovery.py::test_global_discovery_empty_registry_returns_empty_catalog_result` at `tests/test_discovery.py:183`
- T21 pass: `tests/test_discovery.py::test_global_discovery_provenance_is_global_packaged` at `tests/test_discovery.py:199`
- T22 pass: `tests/test_package.py::test_init_public_surface_exports_m2_step_02_packaged_catalogue_surface` at `tests/test_package.py:11`
- T23 pass: `tests/test_package.py::test_deferred_public_names_remain_absent_after_catalogue_surface` at `tests/test_package.py:18`
- T24 pass: `tests/test_offline_import.py::test_import_rivretrieve_does_not_import_providers_stubs_or_generators` at `tests/test_offline_import.py:7`
- T25 pass: `tests/test_internal_provider_module.py::test_stub_catalogue_functions_remain_explicitly_unimplemented` at `tests/test_internal_provider_module.py:37`
- T26 pass: `tests/test_internal_catalogue_reader.py::test_reader_preserves_polars_schema_after_empty_filter` at `tests/test_internal_catalogue_reader.py:215`
- T27 pass: `tests/test_discovery.py::test_global_discovery_uses_reader_for_table_selection_and_validation` at `tests/test_discovery.py:223`

Final gates:

- `uv run ruff format`: pass
- `uv run ruff check --fix`: pass
- `uv run ty check`: pass
- `uv run pytest`: pass, `150 passed`

## 4. Negative-control inventory

- T10 source fatal raises direct before filter work: `tests/test_internal_catalogue_reader.py:175`; reader source checks are at `src/rivretrieve/_internal/catalogue_reader.py:34`, `src/rivretrieve/_internal/catalogue_reader.py:59`, and `src/rivretrieve/_internal/catalogue_reader.py:73`.
- T11 invalid source ignores `on_issue` and has no `IssuePolicyError` chain: `tests/test_internal_catalogue_reader.py:192`.
- T12 non-string filters raise direct `FatalContractError` with no `IssuePolicyError` chain: `tests/test_internal_catalogue_reader.py:204`; guard is at `src/rivretrieve/_internal/catalogue_reader.py:103`.
- T22 public surface present set is exactly `providers`, `provider`, `provider_info`, `stations`, `products`, `product_info`, plus `__version__`: `tests/test_package.py:11`.
- T23 deferred public names remain absent, including handle, issue, schema, result, observation, annotation, and artifact names: `tests/test_package.py:18`.
- T24 subprocess import still avoids provider modules, test stubs, and generators: `tests/test_offline_import.py:7`.
- T25 stub provider catalogue functions still raise `NotImplementedError`: `tests/test_internal_provider_module.py:37`.
- T27 global discovery delegates table selection and validation through `CatalogueReader` methods: `tests/test_discovery.py:223`.

## 5. Deviations from plan §6

- None. The implementation follows the packaged-only reader, private handle delegation, internal-import global discovery tests, atomic public promotion, and version/tag workflow described in §6.

## 6. Surprises

- No architecture contradiction found; no D3 entry needed.
- `uv run bump-my-version show current_version` prints the expected `0.1.10` and also notes that the last existing tag is `0.1.9` until this commit is tagged. That is expected before the final tag step.

## 7. Ready for step 03

Ready. The fatal `source != "packaged"` stopgap is centralized in `CatalogueReader`, handle methods are pure reader delegations over registered artifacts, global discovery builds global provenance at the discovery layer, and the public surface is exactly the M2 step-02 catalogue surface.

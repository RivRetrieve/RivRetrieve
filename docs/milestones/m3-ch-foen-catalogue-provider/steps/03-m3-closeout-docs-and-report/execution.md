# 03-m3-closeout-docs-and-report Execution

## 1. What was implemented

Closed M3 with provider-port notes for `ch_foen`, a negative-control sweep, the M3 milestone REPORT, and the mandatory closeout version bump. The sweep found the two narrow explicitness gaps predicted by the plan, so this step added focused assertion-only tests for existing catalogue envelope/provenance behavior and public-handle observation placeholder routing; no substantive provider behavior changed.

## 2. Files changed

- `docs/provider_ports/ch_foen.md` -> replaced the provider-port stub with Source Endpoints, Catalogue Mapping, Product Dictionary, Annotation, and Issues sections.
- `docs/milestones/m3-ch-foen-catalogue-provider/REPORT.md` -> added the M3 closeout report in the M1/M2 nine-section shape.
- `tests/test_ch_foen_registration.py` -> added focused negative-control coverage for catalogue result envelopes/provenance and public-handle observation placeholder routing.
- `docs/milestones/m3-ch-foen-catalogue-provider/steps/03-m3-closeout-docs-and-report/plan.md` -> staged plan of record.
- `docs/milestones/m3-ch-foen-catalogue-provider/steps/03-m3-closeout-docs-and-report/critique.md` -> staged critique of record.
- `docs/milestones/m3-ch-foen-catalogue-provider/steps/03-m3-closeout-docs-and-report/execution.md` -> added this execution record.

## 3. Tests run + audit results

Negative-control audit against `tests/`:

| Audit item | Result | Test anchor |
|---|---|---|
| Catalogue envelopes for global `rr.stations()`, `rr.products()`, `rr.provider_info()`, and `rr.provider("ch_foen").station_products()` | Gap confirmed and covered with one focused test. | `tests/test_ch_foen_registration.py::test_ch_foen_catalogue_methods_return_catalog_results_with_provenance` |
| `source="live"` rejection for ch_foen catalogue methods | Already covered; no new test. | `tests/test_ch_foen_capabilities.py::test_ch_foen_live_products_unsupported_uses_m2_routing`, `tests/test_ch_foen_capabilities.py::test_ch_foen_live_stations_unsupported_uses_m2_routing`, `tests/test_ch_foen_capabilities.py::test_ch_foen_live_station_products_unsupported_uses_m2_routing` |
| Provider-handle observations placeholder | Gap confirmed and covered with parametrized `on_issue` plus default-call tests. | `tests/test_ch_foen_registration.py::test_ch_foen_handle_observations_placeholder_returns_result_for_all_on_issue`, `tests/test_ch_foen_registration.py::test_ch_foen_handle_observations_placeholder_uses_default_on_issue` |
| Annotation schemas empty | Already covered; no new test. | `tests/test_ch_foen_module.py::test_ch_foen_row_annotation_schema_is_empty`, `tests/test_ch_foen_module.py::test_ch_foen_series_annotation_schema_is_empty` |
| `generate_catalogue.py` not imported by package import | Already covered; re-run in final verification. | `tests/test_offline_import.py::test_import_rivretrieve_does_not_import_providers_stubs_or_generators`, `tests/test_ch_foen_registration.py::test_import_rivretrieve_does_not_import_ch_foen_runtime_modules` |
| T117/T119/T120 public-surface controls | Already covered; re-run explicitly in final verification. | `tests/test_provider_handle.py::test_provider_handle_protocol_method_signatures_match_tracker`, `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface`, `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion` |
| Metadata leak control | Already covered; re-run explicitly in final verification. | `tests/test_ch_foen_registration.py::test_ch_foen_internal_metadata_import_does_not_leak_public_names` |
| 246 / Brugg fixture facts | Already covered; re-run explicitly in final verification. | `tests/test_ch_foen_generate_catalogue.py::test_ch_foen_generator_station_count_matches_legacy_fixture`, `tests/test_ch_foen_generate_catalogue.py::test_ch_foen_generator_station_2016_brugg_matches_legacy_fixture` |

Command results:

- `uv run pytest tests/test_ch_foen_registration.py` -> passed (`12 passed`).
- `uv run ruff format` -> passed (`44 files left unchanged`).
- `uv run ruff check --fix` -> passed (`All checks passed!`).
- `uv run ty check` -> passed (`All checks passed!`).
- `uv run pytest` -> passed before bump (`374 passed in 1.28s`) and after bump (`374 passed in 0.99s`).
- Explicit T117/T119/T120 + metadata leak -> passed (`4 passed`).
- Offline-import probe -> passed (`2 passed`).
- 246 / Brugg fixture facts plus station-products height -> passed (`3 passed`).

## 4. Deviations from plan

None. The only tag adjustment is factual reporting: local tags do not point at the M3 step 01 / step 02 commits even though the plan expected them to; the REPORT records the actual tag inventory and still tags the step 03 closeout commit as `v0.1.17`.

## 5. Surprises

- The local tag inventory has `v0.1.15` on `c64e96f` and `v0.1.16` on `4f68b68`; M3 step 01 (`760f3fe`) and step 02 (`99fa125`) are untagged locally.
- The sweep confirmed both planned explicitness gaps, so the final count rose from 369 to 374 tests.

## 6. Discoveries

None. No missing D-numbered discovery was found during closeout.

## 7. Hand-off notes for M4

M4 should replace the placeholder observation path, define row and series annotation schemas before emitting annotations, confirm upstream's `cd9b030` public-token classification still holds, choose token embedding mechanics, and revisit `bulk_observations` plus packaged `provider.json` if observation capability changes. D7, D8, and D9 are directly relevant to M4 parser/test shape: use `model_validate({...})` for Pydantic extras, test generator/result-side serialization obligations, and prefer concrete `dict` / `list` checks for JSON-loaded data.

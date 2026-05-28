# M3 — ch_foen Catalogue Provider — Milestone Report

**Status:** closed.
**Range:** `760f3fe` (M3 step 01) ... closeout commit (M3 step 03), branch `docs/provider-redesign-proposal`, not pushed.
**Tracker entry:** [docs/milestone-tracker.md §3 "M3 — ch_foen Catalogue Provider"](../../milestone-tracker.md).

M3 ships `ch_foen` as the first real provider port. It resolves the catalogue type-alias shorthand from D3, generates packaged Switzerland FOEN/BAFU catalogue artifacts from the committed Existenz.ch locations fixture, registers `ch_foen` lazily behind the existing provider handle surface, and closes with provider-port notes plus a negative-control sweep. Observation retrieval remains an explicit M4 hand-off.

## 1. Steps executed

| Step | Commit | Tag | Tests after | Net new |
|------|--------|-----|-------------|---------|
| 01-catalogue-typealiases-and-schema-rename | `760f3fe` | none in local tag inventory | 335 | 0 |
| 02-ch-foen-full-implementation | `99fa125` | none in local tag inventory | 369 | +34 |
| 03-m3-closeout-docs-and-report | closeout commit | `v0.1.17` | 374 | +5 |

Tag reality at closeout: local tags exist through `v0.1.16`, but `v0.1.15` points at `c64e96f` (M1/M2 closeout housekeeping) and `v0.1.16` points at `4f68b68` (D2 architecture addenda). The M3 step 01 and step 02 commits are not tagged locally. Step 03 bumps the configured version from `0.1.16` to `0.1.17` and tags the closeout commit `v0.1.17`.

## 2. Public API shipped — vs. tracker

| Tracker entry | Shipped | Location | Divergence |
|---|---|---|---|
| `rr.providers()` includes `"ch_foen"` | Yes | Lazy default registration in `_internal.discovery` | none |
| Existing provider handle exposes `info`, `products`, `stations`, `station_products`, `row_annotation_schema`, `series_annotation_schema`, `observations` | Yes | `rr.provider("ch_foen")` returns the M2 `ProviderHandle` surface backed by the internal ch_foen module | no signature change |
| Global packaged discovery functions include ch_foen rows | Yes | `rr.stations()`, `rr.products()` / `rr.product_info()`, `rr.provider_info()` | no new global `rr.station_products()` |
| Package-root public names remain M2 set | Yes | Guarded by T119/T120 | no ch_foen internals exported |

The public surface remains `{ProviderHandle, product_info, products, provider, provider_info, providers, stations, __version__}`. M3 adds provider data and registration behavior, not package-root symbols or public signatures.

## 3. Internal types introduced — vs. tracker

M3 step 01 resolved D3 by introducing `StationCatalog`, `ProductCatalog`, `StationProductCatalog`, and `ProviderInfoCatalog` as PEP 695 aliases for `pl.DataFrame`, while renaming the runtime schema instances to `STATION_CATALOG_SCHEMA`, `PRODUCT_CATALOG_SCHEMA`, `STATION_PRODUCT_CATALOG_SCHEMA`, and `PROVIDER_INFO_CATALOG_SCHEMA`.

M3 step 02 introduced these provider-internal artifacts:

| Internal artifact | Role |
|---|---|
| `ChFoenStationMetadata` | Pydantic metadata model for station rows, with source extras preserved |
| `ChFoenProductMetadata` | Pydantic metadata model for product rows and legacy variable mapping |
| `ChFoenStationProductMetadata` | Pydantic metadata model for station-product availability assumptions |
| `src/rivretrieve/_internal/providers/ch_foen/generate_catalogue.py` | Maintainer-only catalogue generator, not runtime API |
| `src/rivretrieve/_internal/providers/ch_foen/module.py` | ProviderModule-conformant runtime module for packaged catalogue methods, empty annotation schemas, and placeholder observations |
| Packaged artifacts under `catalogue/` | `provider.json`, `products.parquet`, `stations.parquet`, and `station_products.parquet` |

None of these are package-root exports. The generator is intentionally maintainer-only and protected by offline-import tests.

## 4. Runtime dependencies added

None. M3 consumes the M1 dependency set (`polars`, `pandas`, `pydantic`, `requests`) and adds no runtime package dependency.

## 5. Test count delta and negative-control inventory

**Total: 374 passing.** Net **+39** from M2 close: +0 in step 01, +34 in step 02, +5 in step 03. The step 03 additions are assertion-only negative controls for already-shipped behavior: catalogue envelope/provenance shape and public-handle observation placeholder routing.

Fixture facts are pinned in tests and match the legacy source: 246 stations, station `2016` named `Brugg`, and `246 * 6 = 1476` station-product rows (`tests/test_ch_foen_generate_catalogue.py:41`, `tests/test_ch_foen_generate_catalogue.py:50`, `tests/test_ch_foen_registration.py:28`; thirdparty/RivRetrieve-Python @ origin/switzerland:tests/test_switzerland.py:36-45).

| Negative control | Test anchor |
|---|---|
| T117 ProviderHandle signature shape unchanged | `tests/test_provider_handle.py::test_provider_handle_protocol_method_signatures_match_tracker` |
| T119 package-root public surface unchanged | `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` |
| T120 deferred public names absent | `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion` |
| ch_foen metadata models do not leak to package root | `tests/test_ch_foen_registration.py::test_ch_foen_internal_metadata_import_does_not_leak_public_names` |
| `import rivretrieve` does not import providers/stubs/generators | `tests/test_offline_import.py::test_import_rivretrieve_does_not_import_providers_stubs_or_generators` |
| `import rivretrieve` does not import ch_foen runtime modules | `tests/test_ch_foen_registration.py::test_import_rivretrieve_does_not_import_ch_foen_runtime_modules` |
| Catalogue envelopes return `CatalogResult`, Polars data, packaged/global provenance | `tests/test_ch_foen_registration.py::test_ch_foen_catalogue_methods_return_catalog_results_with_provenance` |
| Live catalogue source rejection follows M2 `on_issue` routing | `tests/test_ch_foen_capabilities.py::test_ch_foen_live_products_unsupported_uses_m2_routing`, `tests/test_ch_foen_capabilities.py::test_ch_foen_live_stations_unsupported_uses_m2_routing`, `tests/test_ch_foen_capabilities.py::test_ch_foen_live_station_products_unsupported_uses_m2_routing` |
| Annotation schemas are empty in M3 | `tests/test_ch_foen_module.py::test_ch_foen_row_annotation_schema_is_empty`, `tests/test_ch_foen_module.py::test_ch_foen_series_annotation_schema_is_empty` |
| Module-level observations placeholder is non-raising and issue-carrying | `tests/test_ch_foen_module.py::test_ch_foen_observations_placeholder_returns_issue_result` |
| Public handle observations placeholder routes through M2 validation and remains non-raising | `tests/test_ch_foen_registration.py::test_ch_foen_handle_observations_placeholder_returns_result_for_all_on_issue`, `tests/test_ch_foen_registration.py::test_ch_foen_handle_observations_placeholder_uses_default_on_issue` |
| 246 / Brugg fixture binding | `tests/test_ch_foen_generate_catalogue.py::test_ch_foen_generator_station_count_matches_legacy_fixture`, `tests/test_ch_foen_generate_catalogue.py::test_ch_foen_generator_station_2016_brugg_matches_legacy_fixture` |

## 6. Discoveries logged

- **D3 resolution** landed in M3 step 01: catalogue names are now real type aliases and runtime schemas use `*_SCHEMA` names.
- **D6** recorded the path-shadowing failure where `rivretrieve.providers.ch_foen` overwrote the public `rr.providers()` callable. Resolution: provider code lives under `rivretrieve._internal.providers.ch_foen`.
- **D7** recorded the `Pydantic extra="allow"` / `ty` test-shape issue. Extras assertions should use `model_validate({...})`.
- **D8** recorded generator-side JSON metadata serialization obligations for asymmetric catalogue encodings.
- **D9** recorded the `Mapping` narrowing problem under `ty`; JSON-loaded parser code should prefer concrete `dict` / `list` checks.

No missing D-numbered discovery was found during report preparation.

## 7. Surprises and candidate updates for the coordinator's M4 prep

1. **Annotation schemas are intentionally empty in M3.** M4 must define row and series annotation schemas before emitting any observation annotations, because the M2 handle validates annotation names on every call.

2. **Token status should start from upstream's current classification.** `origin/switzerland` HEAD is `cd9b030` (`Restore public Switzerland token`), and the legacy source intentionally carries `INFLUX_TOKEN` as a public service credential. M3 target has no token because it is catalogue-only. M4 should confirm this public-token classification still holds at its start, then choose embedding mechanics (`literal`, configuration override, or both).

3. **The observations placeholder is deliberately non-raising.** It returns empty data and annotation tables plus `observations_not_yet_implemented`. M4 replaces this path with real retrieval and removes placeholder-only assertions.

4. **Observation result generation inherits D8-style serialization and provenance obligations.** Anything metadata-like that crosses a Parquet/result boundary needs generator-side or result-construction tests, not only loader-side tests.

5. **D7 and D9 apply directly to observation parsing.** If M4 uses Pydantic models with `extra="allow"`, tests should pass extras through `model_validate({...})`. If M4 walks `json.loads` output, parser shape checks should use concrete `dict` / `list`, not `Mapping` / `Sequence`.

6. **Capability flags must be revisited.** M3 honestly reports `live_stations=False`, `live_products=False`, `live_station_products=False`, and `bulk_observations="false"`. Implementing observations likely changes `bulk_observations` away from `"false"`; if any provider-info capability changes, rerun `generate_catalogue.py` and recommit packaged `provider.json`. The three `live_*` catalogue flags should stay `False` unless M4 also adds live catalogue calls, which is out of M4 scope.

## 8. Escalations

D6 was the only architecture-prompt versus M1/M2 public-surface contradiction: the originally suggested provider package path would have shadowed the public `rr.providers()` callable. It was resolved inside M3 step 02 by moving the provider under `_internal/providers` and logging D6.

D6-D9 were not promoted to `architecture.md`; they are project-pattern and provider-port lessons, not shared architecture commitments.

## 9. Ready for M4

M3 is ready for M4 observation work.

M4 hand-off checklist:

- Define `ch_foen` row and series annotation schemas.
- Confirm upstream's public-token classification still holds at M4 start.
- Choose token embedding mechanics: literal, configuration override, or both.
- Implement observation result/parser types and fixture-backed observation CSV tests.
- Remove the `observations_not_yet_implemented` placeholder path.
- Test row/series provenance and issue obligations through the public handle.
- Revisit `bulk_observations` and regenerate `provider.json` if provider-info capabilities change.
- Keep `live_*` catalogue flags `False` unless live catalogue calls are explicitly added.
- Add the top-level `rr.observations(...)` wrapper if M4 owns that public API step.

# 02-catalogue-methods-packaged Plan

## 1. Goal and scope

Ship the packaged-source catalogue method slice in one commit:

- Add `CatalogueReader`, an internal packaged-artifact reader that is the single source of truth for catalogue table selection, filters, schema validation, handle-level packaged provenance defaults, and `CatalogResult[pl.DataFrame]` construction.
- Add private `_ProviderHandle.products()`, `_ProviderHandle.stations()`, and `_ProviderHandle.station_products()` methods. These methods read directly from the registered `PackagedCatalogArtifact`; they do not call provider-module functions.
- Add public global discovery functions `rr.stations()`, `rr.products()`, and `rr.product_info()` over the module-level registry's packaged artifacts.
- Add `InvalidCatalogueSourceError(FatalContractError)` for any `source` value other than `"packaged"`, including `"live"`, as a direct fatal raise and not an `Issue`.
- Extend public-surface, offline-import, handle-level, reader-level, global-discovery, fatal-source, provenance, and empty-registry tests.

This step is packaged/offline only. It must not add live catalogue issue routing, public `ProviderHandle`, observation contracts, annotation contracts, real providers, top-level observations, map rendering, or any live API call.

Legacy divergence: the old fetchers expose cached metadata and variable lists through class methods and then retrieve one gauge/variable at a time, for example `USAFetcher.get_cached_metadata()` and `get_available_variables()` in `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/usa.py:29-50`, and `UKEAFetcher.get_metadata()` plus per-station measure probing in `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/uk_ea.py:53-79` and `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/uk_ea.py:93-109`. This step deliberately diverges from the legacy "everything is a gauge_id/variable fetcher concern" shape: packaged catalogue discovery returns normalized Polars catalogue tables and filters only on schema-owned product dimensions, not by parsing product IDs or inspecting metadata.

## 2. API surface touched (public + internal)

Public surface:

- Add `rivretrieve.stations() -> CatalogResult[pl.DataFrame]`.
- Add `rivretrieve.products() -> CatalogResult[pl.DataFrame]`.
- Add `rivretrieve.product_info() -> CatalogResult[pl.DataFrame]`.
- Keep `rivretrieve.providers()`, `rivretrieve.provider()`, and `rivretrieve.provider_info()` unchanged.
- Modify `src/rivretrieve/__init__.py` to re-export only the three new discovery functions plus the mandatory version-literal bump. Do not export `ProviderHandle`, `_ProviderHandle`, `CatalogueReader`, `CatalogResult`, schema objects, `Issue`, or any observation/annotation/raw-payload names.

Private handle surface:

- Add `_ProviderHandle.products(*, source: CatalogSource = "packaged", observed_property: str | None = None, frequency: str | None = None, statistic: str | None = None, on_issue: OnIssue = "warn") -> CatalogResult[pl.DataFrame]`.
- Add `_ProviderHandle.stations(*, source: CatalogSource = "packaged", on_issue: OnIssue = "warn") -> CatalogResult[pl.DataFrame]`.
- Add `_ProviderHandle.station_products(stations: Sequence[str] | None = None, *, source: CatalogSource = "packaged", on_issue: OnIssue = "warn") -> CatalogResult[pl.DataFrame]`.
- These signatures intentionally match the existing `ProviderModule` Protocol methods in `src/rivretrieve/_internal/provider_module.py:18-41`.

Internal surface:

- Add `src/rivretrieve/_internal/catalogue_reader.py`.
- Modify `src/rivretrieve/_internal/registry.py` only to import/use `CatalogueReader` and add the three private handle methods. Do not add fields to `_ProviderHandle`.
- Modify `src/rivretrieve/_internal/discovery.py` to add the three public global discovery implementations over `_registry.iter_records()`.
- Modify `src/rivretrieve/_internal/issues.py` to add `InvalidCatalogueSourceError(FatalContractError)`.

Critical separation:

- `ProviderModule.products()`, `ProviderModule.stations()`, and `ProviderModule.station_products()` are provider-package functions for future live/provider-owned behaviour. In the tests-only stub they must continue to raise `NotImplementedError`, preserving step 01 T17.
- `_ProviderHandle.products()`, `_ProviderHandle.stations()`, and `_ProviderHandle.station_products()` are harness methods over the already-registered packaged artifact. They must never call the stub provider module functions.

## 3. Data structures and types (CatalogueReader contract, filters, provenance)

Define `CatalogueReader` as a frozen class in `src/rivretrieve/_internal/catalogue_reader.py`:

- Fields: `artifact: PackagedCatalogArtifact`, `provider_id: ProviderId | None`.
- Construction remains lightweight; no provider module, registry, network client, path, or hash fields.
- Methods:
  - `read_products(*, source: CatalogSource = "packaged", observed_property: str | None = None, frequency: str | None = None, statistic: str | None = None, on_issue: OnIssue = "warn") -> CatalogResult[pl.DataFrame]`.
  - `read_stations(*, source: CatalogSource = "packaged", on_issue: OnIssue = "warn") -> CatalogResult[pl.DataFrame]`.
  - `read_station_products(stations: Sequence[str] | None = None, *, source: CatalogSource = "packaged", on_issue: OnIssue = "warn") -> CatalogResult[pl.DataFrame]`.

Reader invariants:

- Source validation is first: if `source != "packaged"`, raise `InvalidCatalogueSourceError(source)` directly. Do not call `apply_on_issue`.
- Reader output always wraps a Polars `DataFrame` in `CatalogResult`.
- Reader copies/selects rows from `artifact.products`, `artifact.stations`, or `artifact.station_products`; it must not mutate artifact frames.
- Reader validates the final frame with the matching `CatalogueSchema` and passes through schema warning issues from extra columns according to `on_issue`. Fatal schema failures still raise direct `FatalContractError`.
- Empty filter result sets are valid: return an empty `CatalogResult` with the same schema and no issue.

Filter behaviour:

- Product filters are exact, case-sensitive equality on `ProductCatalog` columns `observed_property`, `frequency`, and `statistic`, which exist in `src/rivretrieve/_internal/catalogues/schemas.py:53-70`.
- Product filters are `str | None` only. Do not add multi-value support.
- Runtime callers that pass any non-string, non-`None` filter value get a direct `FatalContractError`; do not rely on Polars comparison coercion or static typing alone.
- `None` means no filter for that dimension.
- A filter value that matches zero rows returns an empty result, not a warning and not a fatal error.
- Filters must not parse product IDs and must not decode `metadata`.
- `station_products(stations=...)` filters by exact, case-sensitive `station_id` membership on the `StationProductCatalog.station_id` column from `src/rivretrieve/_internal/catalogues/schemas.py:72-87`.
- `stations is None` and `stations == []` both return all station-product rows in this step.
- Unknown station IDs in a non-empty sequence are silently absent from the filtered result. They are not fatal and not warning issues in this packaged-reader step.

Provenance:

- `CatalogProvenance` fields are currently `source`, `provider_id`, `rivretrieve_version`, `catalogue_version`, `artifact_id`, `artifact_path`, `artifact_hash`, `generated_at`, `retrieved_at`, `endpoints`, `query`, and `response_version` (`src/rivretrieve/_internal/results.py:12-26`).
- `PackagedCatalogArtifact` currently has only `provider_info`, `products`, `stations`, and `station_products` (`src/rivretrieve/_internal/catalogues/artifact.py:34-40`). It does not carry `artifact_id`, `artifact_path`, `artifact_hash`, or `generated_at`.
- Therefore this plan does not require an artifact-shape migration in step 02. For packaged catalogue calls, set `artifact_id=None`, `artifact_path=None`, `artifact_hash=None`, `generated_at=None`, `retrieved_at=None`, `endpoints=()`, `query=None`, and `response_version=None`.
- Set `source="packaged"`.
- Set `provider_id` to the registered provider ID for handle-level calls and to `None` for global discovery calls.
- Set `catalogue_version` from `artifact.provider_info["catalogue_version"]` for handle-level calls. For global calls, set `catalogue_version=None` because multiple providers may contribute rows.
- Set `rivretrieve_version` from `rivretrieve.__version__` inside the method body to avoid import-cycle surprises.

Global discovery aggregation:

- `rr.stations()` aggregates every registered provider's `stations` table.
- `rr.products()` aggregates every registered provider's `products` table.
- `rr.product_info()` is a public alias-shaped product catalogue discovery call in this step: it returns the same aggregate product catalogue contract as `rr.products()`. This follows the tracker's M2 public API wording that lists both names as `CatalogResult[ProductCatalog]` and avoids inventing a second product-detail schema.
- Global discovery instantiates `CatalogueReader(record.artifact, record.provider_id)` once per registered record and calls the relevant reader method, then aggregates only the returned `result.data` frames. Per-provider reader provenance is intentionally discarded in the global path, and `discovery.py` constructs one global provenance object after aggregation. This preserves a single reader for source validation, table selection, filters, and schema validation while allowing global provenance to differ from handle-level provenance; see Q1 for the class-shape rationale.
- Global rows retain the schema-owned `provider_id` column already present in all three catalogue schemas. Do not add duplicate provider columns.
- Deterministic sorting:
  - Stations by `provider_id`, `station_id`.
  - Products/product_info by `provider_id`, `product_id`.
  - Station-products if a global helper is ever added later would sort by `provider_id`, `station_id`, `product_id`; this step does not add `rr.station_products()`.
- Empty registry returns an empty typed Polars frame with the relevant schema and provenance `source="packaged"`, `provider_id=None`, `catalogue_version=None`, and all unavailable artifact/live fields set to `None` or `()`.

## 4. Errors and failure modes (separate fatal-raise from Issue-routed paths)

Fatal direct raises, never routed through `apply_on_issue`:

- `source != "packaged"` for handle-level methods raises `InvalidCatalogueSourceError`, including `source="live"`.
- Invalid `source` values for any direct `CatalogueReader` method raise `InvalidCatalogueSourceError`.
- Non-string, non-`None` filter values raise `FatalContractError` directly before Polars filtering.
- Catalogue schema violations on final frames raise direct `FatalContractError` through `validate_catalogue`, preserving M1 behaviour.
- If an executor discovers that a requested filter keyword lacks a backing `CatalogueSchema` column, stop and surface rather than implementing an ad hoc filter spec. The planned filters are backed by `ProductCatalog` columns at `src/rivretrieve/_internal/catalogues/schemas.py:58-60`.

Issue-routed paths:

- Extra columns in final frames remain warning `Issue` objects from `validate_catalogue`, subject to `on_issue`, as in M1.
- Empty result sets are not issues.
- Unknown station IDs in `station_products(stations=[...])` are not issues in this step.
- Unsupported live-source capability is not an issue in this step. Step 03 replaces the fatal `"live"` arm with capability-aware routing.

Error placement:

- Add `InvalidCatalogueSourceError` to `src/rivretrieve/_internal/issues.py` because it is a cross-cutting fatal contract error for catalogue method inputs. Unlike `UnknownProviderError`, which is registry-specific and raised only from `registry.py`, and unlike `CorruptCatalogArtifactError`, which is artifact-specific and raised from `catalogues/artifact.py`, invalid source values will be raised by `CatalogueReader` and provider-handle methods now and by live-capability routing later.

## 5. Tests (enumerated, one-line each; include negative controls)

T01. `test_catalogue_reader_products_returns_packaged_catalog_result`: reader returns `CatalogResult[pl.DataFrame]` for products with packaged provenance.

T02. `test_catalogue_reader_stations_returns_packaged_catalog_result`: reader returns stations with the `StationCatalog` schema.

T03. `test_catalogue_reader_station_products_returns_packaged_catalog_result`: reader returns station-products with the `StationProductCatalog` schema.

T04. `test_catalogue_reader_product_filters_are_exact_and_case_sensitive`: `observed_property`, `frequency`, and `statistic` filters match exact values only.

T05. `test_catalogue_reader_product_filter_no_match_returns_empty_result`: unmatched product filter returns an empty `CatalogResult`, not an issue or exception.

T06. `test_catalogue_reader_product_filters_do_not_parse_metadata`: richer fixture metadata should not affect product filter matches.

T07. `test_catalogue_reader_station_products_filters_station_ids`: non-empty station sequence returns only matching station IDs.

T08. `test_catalogue_reader_station_products_empty_sequence_matches_none`: `stations=[]` and `stations=None` return identical all-row results.

T09. `test_catalogue_reader_station_products_unknown_ids_are_dropped`: unknown station IDs produce an empty or partially filtered result with no issue.

T10. `test_catalogue_reader_invalid_source_raises_direct_fatal`: parametrized over `source="live"` and another invalid string, with no `IssuePolicyError` in the exception chain.

T11. `test_catalogue_reader_invalid_source_ignores_on_issue_policy`: parametrized over `on_issue in ("warn", "raise", "ignore")`, invalid source still raises `InvalidCatalogueSourceError` and `_issue_policy_error_chain(exc) == []`.

T12. `test_catalogue_reader_non_string_filter_raises_direct_fatal`: representative bad values such as `observed_property=123` raise `FatalContractError` with no `IssuePolicyError` in the exception chain.

T13. `test_provider_handle_products_reads_artifact_not_provider_module`: registered handle returns products while stub provider `products()` still raises `NotImplementedError`.

T14. `test_provider_handle_stations_reads_artifact_not_provider_module`: registered handle returns stations while stub provider `stations()` still raises `NotImplementedError`.

T15. `test_provider_handle_station_products_reads_artifact_not_provider_module`: registered handle returns station-products while stub provider `station_products()` still raises `NotImplementedError`.

T16. `test_provider_handle_catalogue_methods_have_registered_provider_provenance`: handle-level provenance has `provider_id="stub_provider"`, `source="packaged"`, `catalogue_version` from provider info, and unavailable artifact/live fields empty.

T17. `test_global_stations_aggregates_registered_packaged_artifacts`: module-level registry with two stub providers returns station rows from both, sorted by `provider_id`, `station_id`.

T18. `test_global_products_aggregates_registered_packaged_artifacts`: products aggregate across providers, sorted by `provider_id`, `product_id`.

T19. `test_global_product_info_matches_products_contract`: `rr.product_info()` returns the same product catalogue contract and deterministic rows as `rr.products()` under the explicit Q10 Option A decision.

T20. `test_global_discovery_empty_registry_returns_empty_catalog_result`: `rr.stations()`, `rr.products()`, and `rr.product_info()` return empty typed frames and packaged global provenance.

T21. `test_global_discovery_provenance_is_global_packaged`: global provenance uses `provider_id=None`, `source="packaged"`, `catalogue_version=None`, and empty artifact/live fields.

T22. `test_init_public_surface_exports_m2_step_02_packaged_catalogue_surface`: exact public surface is `{"providers", "provider", "provider_info", "stations", "products", "product_info"}` plus `__version__`.

T23. `test_deferred_public_names_remain_absent_after_catalogue_surface`: preserve the explicit union of M1 absences minus the three newly exported names, plus new deferred observation/handle names. The absent set is `{"ProviderInfo", "ProviderModule", "ProviderHandle", "_ProviderHandle", "observations", "map_stations", "ObservationResult", "ObservationRequest", "ObservationProvenance", "AnnotationSchema", "AnnotationTable", "RawPayload", "Issue", "CatalogResult", "StationCatalog", "ProductCatalog", "StationProductCatalog", "ProviderInfoCatalog", "PackagedCatalogArtifact", "CorruptCatalogArtifactError"}`.

T24. `test_import_rivretrieve_does_not_import_providers_stubs_or_generators`: offline-import subprocess still proves no provider modules, test stubs, or `generate_catalogue.py` import on package import.

T25. `test_stub_catalogue_functions_remain_explicitly_unimplemented`: rename step 01's `tests/test_internal_provider_module.py::test_stub_catalogue_functions_are_explicitly_unimplemented_in_step_01` in place, dropping the stale step-01 suffix while preserving the same assertions.

T26. `test_reader_preserves_polars_schema_after_empty_filter`: empty filtered results retain the relevant schema dtypes, including `AvailabilityDtype` for station-products.

T27. `test_global_discovery_uses_reader_for_table_selection_and_validation`: monkeypatch `CatalogueReader.read_stations` and `read_products` rather than monkeypatching the frozen dataclass constructor, proving `rr.stations()`, `rr.products()`, and `rr.product_info()` delegate table selection/schema-validation work to the shared reader while constructing global provenance in `discovery.py`.

## 6. Files (new + modified, in implementation order keeping pytest green at each)

1. Add `src/rivretrieve/_internal/issues.py::InvalidCatalogueSourceError` with no call sites yet. Run `uv run pytest`.
2. Add `src/rivretrieve/_internal/catalogue_reader.py` with `CatalogueReader`, source validation, product filters, station-products filter, schema validation, and handle-level provenance construction. Run `uv run pytest`.
3. Add `tests/test_internal_catalogue_reader.py` covering T01-T12 and T26 against the existing one-row fixture. T11 and T12 must assert `_issue_policy_error_chain(exc) == []`, reusing the project-standard helper pattern from discovery tests. Run `uv run pytest`.
4. Extend `tests/conftest.py` fixture builders to optionally produce richer products/stations/station-products rows for filter and aggregation coverage. Keep default fixture calls compatible with existing tests. The richer station-products fixture must add matching station catalogue rows in lockstep, for example both `station-1` and `station-2`, so artifact foreign-key validation remains valid. Run `uv run pytest`.
5. Extend, do not re-implement, `tests/test_internal_catalogue_reader.py` T04-T09 against the richer fixture data so station and product filters are tested with at least two candidate rows. Run `uv run pytest`.
6. Modify `src/rivretrieve/_internal/registry.py` to add `_ProviderHandle.products()`, `.stations()`, and `.station_products()` delegating to `CatalogueReader(self._artifact, self.provider_id)`. Run `uv run pytest`.
7. Add or extend `tests/test_internal_registry.py` for T13-T16, and rename the existing step-01 stub-module test in `tests/test_internal_provider_module.py` for T25. Run `uv run pytest`.
8. Modify `src/rivretrieve/_internal/discovery.py` to add `stations()`, `products()`, and `product_info()` over `_registry.iter_records()` using `CatalogueReader`. Run `uv run pytest`.
9. Add `tests/test_discovery.py` global discovery coverage for T17-T21 and T27, importing the new functions directly from `rivretrieve._internal.discovery` until step 10 promotes them through `rivretrieve.__init__`; do not call `rr.stations()`, `rr.products()`, or `rr.product_info()` at this checkpoint. Run `uv run pytest`.
10. Atomically modify `src/rivretrieve/__init__.py` to re-export `stations`, `products`, and `product_info`, and modify `tests/test_package.py` to rename the negative-control test, update the exact surface set, and preserve/extend deferred absences for T22-T23. This is an API-shape edit owned by this step; the mandatory version-literal bump still happens later. Run `uv run pytest`.
11. Extend `tests/test_offline_import.py` only if the new imports change the sentinel path; otherwise keep the current invariant and ensure T24 still passes. Run `uv run pytest`.
12. Run `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, and `uv run pytest`.
13. Run `uv run bump-my-version bump patch`, stage version files with the docs/code/test changes, commit, and tag with `v$(uv run bump-my-version show current_version)` per project instructions and D1.

## 7. Open questions (with recommendation per question)

Q1. CatalogueReader shape: class or free functions?

Recommendation: class with `read_products`, `read_stations`, and `read_station_products`. A small frozen class keeps artifact, provider ID, filter logic, schema validation, and handle-level provenance construction together and makes it hard for global discovery and handle methods to drift on table semantics. Global discovery still constructs global provenance at the discovery layer because its `provider_id` and `catalogue_version` semantics differ by design. This does not pre-empt step 03 live design because the class is explicitly packaged-artifact scoped and source validation still rejects `"live"` in this step. Free functions would be leaner, but they would repeatedly thread the same artifact/provider state through every call and make the source-validation, filtering, and schema-validation contract easier to diverge across handle and global paths.

Q2. Where does `InvalidCatalogueSourceError` live?

Recommendation: `src/rivretrieve/_internal/issues.py`. The error is not specific to one registry lookup or one artifact loader; it is a fatal public-contract input error shared by catalogue handle methods now and by capability-aware catalogue routing later. This differs from `UnknownProviderError` living next to registry lookup and `CorruptCatalogArtifactError` living next to artifact validation because the source-value contract spans more than one raiser.

Q3. Product filter semantics for `observed_property`, `frequency`, and `statistic`.

Recommendation: exact, case-sensitive equality on schema columns; no substring matching and no canonical vocabulary remapping. Unknown filter values return an empty `CatalogResult`, not an issue and not a fatal error. Multi-value filters are deferred because the current `ProviderModule` signature is `str | None` for each filter. The backing columns exist in `ProductCatalog` at `src/rivretrieve/_internal/catalogues/schemas.py:58-60`, so there is no schema gap. Do not inspect JSON metadata or parse product IDs.

Q4. `station_products(stations: Sequence[str] | None)` semantics.

Recommendation: `None` and an empty sequence both mean "all stations" in this step. Unknown station IDs are silently dropped by the filter and may produce an empty result. This mirrors normal table-filter semantics, keeps empty results non-exceptional, and avoids inventing warning issue codes before step 03's issue-routing work.

Q5. Global aggregation details.

Recommendation: do not add a new `provider_id` column because every catalogue schema already includes `provider_id` (`StationCatalog` at `src/rivretrieve/_internal/catalogues/schemas.py:38`, `ProductCatalog` at line 56, `StationProductCatalog` at line 75). Keep rows deterministic by sorting stations by `(provider_id, station_id)` and products/product_info by `(provider_id, product_id)`. Empty registry returns an empty typed frame with global packaged provenance: `provider_id=None`, `source="packaged"`, `catalogue_version=None`, and unavailable artifact/live fields set to `None` or `()`.

Q6. Filter parameters on global functions.

Recommendation: no filter parameters on `rr.stations()`, `rr.products()`, or `rr.product_info()` in step 02. The milestone tracker lists these as global packaged discovery functions but does not enumerate filter parameters, and M1's `provider_info()` pattern kept global discovery minimal. Provider-level filters are load-bearing for later observation selection; global filters can be added later with architecture authority if a real workflow requires them. No later step in the current tracker depends on global filter parameters.

Q7. Public surface negative-control test rename.

Recommendation: rename to `test_init_public_surface_exports_m2_step_02_packaged_catalogue_surface`. The step suffix is useful because M2 intentionally grows the public surface across multiple steps, so a milestone-only name would become stale as soon as public `ProviderHandle` or observation names land. This test will likely be renamed again; that churn is acceptable because it is the exact public-surface guard for each step boundary.

Q8. Provenance details and artifact fields.

Recommendation: handle-level calls return `CatalogProvenance(source="packaged", provider_id=<registered provider>, rivretrieve_version=__version__, catalogue_version=<artifact provider_info catalogue_version>, artifact_id=None, artifact_path=None, artifact_hash=None, generated_at=None, retrieved_at=None, endpoints=(), query=None, response_version=None)`. Global calls use the same shape with `provider_id=None` and `catalogue_version=None`. The requested artifact fields do not exist on `PackagedCatalogArtifact` today (`src/rivretrieve/_internal/catalogues/artifact.py:34-40`), so this plan explicitly does not populate them. If non-null artifact ID/path/hash are mandatory for step 02 acceptance, that is an artifact-contract change and should be escalated before execution rather than hidden inside `CatalogueReader`.

Q9. Stub provider strategy.

Recommendation: enrich the stub packaged-artifact factory in `tests/conftest.py`, not the stub provider module functions. Add optional parameters or helper builders so tests can create multiple products, stations, and station-product rows for filters and global aggregation. Keep the default one-row artifact compatible with existing tests. The stub module's `products`, `stations`, and `station_products` functions remain `NotImplementedError`-raising; handle methods read from the registered artifact directly.

Q10. What does `rr.product_info()` mean in step 02?

Options:

- Option A: `rr.product_info()` is semantically equivalent to `rr.products()` in this step and returns the aggregate registered-provider `ProductCatalog`.
- Option B: `rr.product_info()` materializes a canonical product dictionary, distinct from registered-provider products, as a `CatalogResult[ProductCatalog]`.

Recommendation: Option A for step 02. The milestone tracker pins both `rr.products()` and `rr.product_info()` to the same `CatalogResult[ProductCatalog]` contract and does not authorize a canonical product-dictionary materialization path in this step. Option B is plausible product design, but it would require architecture/product-dictionary authority because `docs/product_dictionary.md` is maintainer-side documentation, not yet a runtime catalogue artifact. If Option B is intended, stop before execution and escalate.

## 8. Deferrals (with hard rationale: which later step or milestone handles each)

- Capability-aware `source="live"` handling and `LiveCatalogueUnsupportedIssue`: M2 step 03. Hard rationale: this step's explicit stopgap is fatal for any non-packaged source.
- Public `ProviderHandle` Protocol promotion and `rr.provider()` return-type narrowing: later M2 step. Hard rationale: this step only adds three methods to the private handle and must not export a partial public Protocol.
- Provider-module live catalogue implementations: M3 or provider-specific later work. Hard rationale: packaged harness methods do not call provider-module catalogue functions.
- `ObservationRequest`, `ObservationResult`, `ObservationProvenance`, `AnnotationSchema`, `AnnotationTable`, and `RawPayload`: M2 steps 04-05. Hard rationale: no observation or annotation behaviour is introduced here.
- `observations()`, `row_annotation_schema()`, and `series_annotation_schema()` on `_ProviderHandle`: M2 steps 04-05. Hard rationale: these depend on observation/annotation contracts not present yet.
- Top-level `rr.observations(...)`: M4. Hard rationale: the tracker makes it a wrapper around provider observations after provider observation behaviour exists.
- `rr.map_stations()`: M5. Hard rationale: map rendering depends on station catalogue availability but is its own public feature.
- Real provider modules and `ch_foen` packaged artifacts: M3. Hard rationale: step 02 uses only tests-only stubs.
- Global discovery filters: deferred until architecture/product authority requests them. Hard rationale: tracker does not require them and provider-level filters cover the current M2 need.
- Canonical product-dictionary-backed `rr.product_info()` semantics: deferred until architecture/product authority requests Q10 Option B. Hard rationale: step 02 deliberately chooses Option A, equivalence with `rr.products()`, because no runtime product-dictionary catalogue artifact exists yet.
- Non-null packaged artifact provenance fields (`artifact_id`, `artifact_path`, `artifact_hash`, `generated_at`): deferred until an artifact-contract step. Hard rationale: current in-memory `PackagedCatalogArtifact` has no such fields, and adding them here would widen scope beyond catalogue method surface.
- Wide-form pandas export helpers: post-V1 deferral. Hard rationale: catalogue methods return Polars `CatalogResult`, and observation exports are later.

## 9. Stopping conditions for the executor

Stop and surface if any of these happen:

- Implementing `"live"` requires anything other than `InvalidCatalogueSourceError` direct fatal raise.
- A fatal failure path is routed through `apply_on_issue` or encoded as an `Issue`.
- A product filter is proposed without a backing `ProductCatalog` column.
- Non-string, non-`None` filter values would fall through to Polars filtering instead of raising direct `FatalContractError`.
- Product filtering requires parsing product IDs, decoding JSON metadata, or introducing a canonical vocabulary mapper.
- Global discovery needs a reader path different from handle-level discovery.
- Adding `rr.stations()`, `rr.products()`, or `rr.product_info()` requires exporting or promoting `ProviderHandle`.
- Stub provider module catalogue functions stop raising `NotImplementedError`.
- `CatalogueReader` imports provider modules, test stubs, `rivretrieve.providers`, or any `generate_catalogue.py`.
- The implementation needs network access or a live provider API call.
- The executor tries to add `rr.station_products()` as a public global function; it is not in this step's public surface.
- Non-null artifact provenance fields become mandatory without an explicit artifact-contract change.
- Empty filter results are treated as warning or error issues.
- `station_products(stations=[])` is treated as fatal or as an impossible filter without planner/coordinator confirmation.
- Any intermediate file order listed in §6 leaves `uv run pytest` failing or `import rivretrieve` broken.
- D2's queued architecture §7/§9 addenda become necessary for step-02 correctness rather than merely desirable documentation.

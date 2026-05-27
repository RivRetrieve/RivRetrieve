# 03-registry-and-surface Plan

## 1. Goal and scope

This step closes M1 by shipping the registry and public discovery surface authorized in `docs/milestone-tracker.md` lines 39-89:

- Introduce an internal `ProviderRegistry` that can hold registered providers, while production M1 remains empty.
- Add an internal test/M3 registration path for packaged provider artifacts without importing provider modules during `import rivretrieve`.
- Add `UnknownProviderError` as a fatal contract error raised by `rr.provider(provider_id)` when the ID is not registered.
- Export exactly three new public functions from `rivretrieve`: `providers()`, `provider(provider_id)`, and `provider_info()`.
- Return `rr.provider_info()` as `CatalogResult[ProviderInfoCatalog]` over the installed registry, with packaged provenance and Polars data.
- Add the offline-import negative-control test that proves `import rivretrieve` does not import provider modules or `generate_catalogue.py`.
- Add a narrow M1 exit-criteria smoke sweep, update the public-surface negative control, keep `uv run pytest` green, then run the normal patch bump and tag flow.

The step must not introduce the public `ProviderHandle` Protocol, provider catalogue methods, observation contracts, real provider packages, plugin discovery, live catalogue behavior, or global discovery functions beyond `provider_info()`. The legacy package exposes country fetcher classes from `rivretrieve/__init__.py`; this redesign intentionally does not copy that shape.

## 2. API surface touched

Public package surface:

- `rivretrieve.providers() -> list[str]`
  - Returns the sorted registered provider IDs.
  - Deterministic and offline.
  - Empty list in M1 production.
- `rivretrieve.provider(provider_id: str) -> object`
  - Returns a private concrete placeholder handle for registered providers.
  - Public return type remains `object`, per tracker lines 56-59.
  - Raises `UnknownProviderError` for missing IDs.
- `rivretrieve.provider_info() -> CatalogResult[ProviderInfoCatalog]`
  - Returns an aggregate `ProviderInfoCatalog` Polars `DataFrame` wrapped in `CatalogResult`.
  - Uses packaged provenance because global discovery is packaged/offline per `architecture.md` lines 89 and 152-180.

Internal surface:

- `rivretrieve._internal.registry.ProviderRegistry`
- `rivretrieve._internal.registry.UnknownProviderError`
- `rivretrieve._internal.registry._ProviderRecord`
- `rivretrieve._internal.registry._ProviderHandle`
- `rivretrieve._internal.registry._registry`
- `rivretrieve._internal.discovery.providers`
- `rivretrieve._internal.discovery.provider`
- `rivretrieve._internal.discovery.provider_info`

Internal test/support registration methods:

- `ProviderRegistry.register(provider_id: str, packaged_artifact: PackagedCatalogArtifact) -> _ProviderHandle`
- `ProviderRegistry.get(provider_id: str) -> _ProviderHandle`
- `ProviderRegistry.list_provider_ids() -> list[str]`
- `ProviderRegistry.iter_records() -> tuple[_ProviderRecord, ...]`
- `ProviderRegistry.clear() -> None`

`clear()` is internal and only for tests. It must not be re-exported from `rivretrieve`.

## 3. Data structures and types

### ProviderRegistry

Use a frozen-ish normal class with a private mutable dictionary:

- `_providers: dict[str, _ProviderRecord]`

Methods:

- `register(provider_id: str, packaged_artifact: PackagedCatalogArtifact) -> _ProviderHandle`
  - Validates provider ID format.
  - Verifies `packaged_artifact.provider_info["provider_id"] == provider_id`.
  - Raises on duplicate registration.
  - Stores a `_ProviderRecord` and returns its handle.
- `get(provider_id: str) -> _ProviderHandle`
  - Membership lookup only.
  - Raises `UnknownProviderError` if missing.
- `list_provider_ids() -> list[str]`
  - Returns sorted ascending IDs.
- `iter_records() -> tuple[_ProviderRecord, ...]`
  - Returns records sorted by `provider_id` for deterministic aggregation.
- `clear() -> None`
  - Clears the registry for test isolation.

Rationale: a class is narrow and testable, unlike a loose module-level dict; it can be called from M3 provider package imports without making package import itself discover/import providers. Pydantic adds no useful validation here and would obscure the intentionally private mutable registry. This follows `architecture.md` line 22 and tracker line 10: no speculative shared abstractions.

### _ProviderRecord

Use a frozen dataclass:

- `provider_id: ProviderId`
- `artifact: PackagedCatalogArtifact`
- `handle: _ProviderHandle`

The record is internal only. It binds the registered provider ID to its validated packaged artifact and stable handle.

### _ProviderHandle

Use a frozen private dataclass:

- `provider_id: ProviderId`
- `_artifact: PackagedCatalogArtifact`

M1 methods: none.

Rationale: tracker line 58 pins `rr.provider()` as returning `object` in M1, but the runtime still needs a concrete object. A private frozen handle gives M2 a place to add the public provider methods and later satisfy the `ProviderHandle` Protocol without renaming the object or changing registry storage.

### UnknownProviderError

Define in `rivretrieve._internal.registry` next to the lookup that raises it:

- Subclass: `FatalContractError`
- Constructor input: `provider_id: str`
- Stored field: `provider_id: str`
- Message: include the unknown provider ID and make clear it is not registered.

Rationale: step 02 placed `CorruptCatalogArtifactError` next to artifact loading/validation in `rivretrieve._internal.catalogues.artifact` lines 30-31. Apply the same locality pattern here.

### Provider ID validation

Validate provider IDs at registration only with:

```text
^[a-z][a-z0-9_]*$
```

This accepts examples in `architecture.md` lines 60-67 (`usgs_nwis`, `uk_ea`, `uk_nrfa`, `ch_foen`) and rejects IDs that do not start with lowercase ASCII or that contain hyphens, spaces, dots, or uppercase characters.

Lookup does not separately validate. `rr.provider("BAD-Provider")` should raise `UnknownProviderError` because no valid registration can create that key. This keeps the user-facing failure simple and reserves format enforcement for provider self-registration, consistent with `architecture.md` lines 51-58.

### ProviderInfoCatalog aggregation

`ProviderInfoCatalog` has columns defined in `schemas.py` lines 89-101:

- `provider_id: pl.Utf8`
- `name: pl.Utf8`
- `live_stations: pl.Boolean`
- `live_products: pl.Boolean`
- `live_station_products: pl.Boolean`
- `bulk_observations: pl.Utf8`
- `catalogue_version: pl.Utf8 | null`
- `metadata: pl.Utf8`

For an empty registry, construct:

- `pl.DataFrame(schema=ProviderInfoCatalog.polars_schema)`
- zero rows
- all expected columns and dtypes

Then validate with `validate_catalogue(df, ProviderInfoCatalog, on_issue="warn")`. Step 02 validation already checks missing columns, dtypes, nullability, JSON metadata, and uniqueness in `schemas.py` lines 105-131 and 160-180. Empty tables satisfy these checks.

For a non-empty registry:

- Convert each `_ProviderRecord.artifact.provider_info` dict into a row.
- Build a `pl.DataFrame(rows, schema=ProviderInfoCatalog.polars_schema)`.
- Sort by `provider_id` for deterministic output.
- Validate with `validate_catalogue(..., ProviderInfoCatalog)`.

Duplicate provider IDs should be impossible because `register()` raises on duplicate key, but validation still reaffirms the unique key at `schemas.py` lines 175-180.

### CatalogProvenance for rr.provider_info()

Populate aggregate packaged provenance as:

- `source="packaged"`
- `provider_id=None`
- `rivretrieve_version=__version__`
- `catalogue_version=None`
- `artifact_id=None`
- `artifact_path=None`
- `artifact_hash=None`
- `generated_at=None`
- `retrieved_at=None`
- `endpoints=()`
- `query=None`
- `response_version=None`

This uses the fields already present in `CatalogProvenance` (`results.py` lines 12-26). `provider_id` is `None` because `rr.provider_info()` is aggregate, not provider-scoped; `catalogue_version` is `None` because there is no single catalogue version across providers in M1.

## 4. Errors and failure modes

- Unknown provider lookup:
  - `rr.provider("missing")` calls the registry lookup.
  - Raises `UnknownProviderError`, a `FatalContractError` subclass.
  - Fatal means it raises immediately regardless of `on_issue`, matching `architecture.md` lines 607-609 and tracker lines 28-29.
- Duplicate provider registration:
  - `ProviderRegistry.register()` raises `FatalContractError`.
  - This catches M3 accidental double registration early.
- Invalid provider ID at registration:
  - `ProviderRegistry.register()` raises `FatalContractError`.
  - Use the exact regex in section 3.
- Artifact/provider ID mismatch:
  - `ProviderRegistry.register("stub_provider", artifact)` raises `FatalContractError` if `artifact.provider_info["provider_id"] != "stub_provider"`.
  - Step 02 artifact construction already enforces one internally consistent provider ID across tables in `artifact.py` lines 176-194; registry still enforces the registration key matches the artifact key.
- Invalid aggregate provider info:
  - `rr.provider_info()` validates the aggregate frame and lets `FatalContractError` raise if schema/dtype/unique-key invariants are broken.
  - This is a harness/provider contract failure, not recoverable data quality.
- Corrupt packaged artifacts:
  - Existing `CorruptCatalogArtifactError` remains fatal and independent of `on_issue`, already implemented as `FatalContractError` in `artifact.py` lines 30-31 and wrapped in `artifact.py` lines 72-85.
- Offline-import regression:
  - Subprocess negative control fails if `import rivretrieve` imports `rivretrieve.providers`, anything below `rivretrieve.providers.`, or any module whose final segment is `generate_catalogue`.

## 5. Tests

1. `test_registry_initially_empty`: a fresh `ProviderRegistry` lists no IDs and has no records.
2. `test_registry_registers_stub_provider_and_returns_handle`: registering a valid stub artifact returns a private handle with the expected `provider_id`.
3. `test_registry_rejects_duplicate_provider_id`: double registration raises `FatalContractError`.
4. `test_registry_rejects_invalid_provider_id_format`: uppercase, hyphenated, dotted, empty, and leading-digit IDs raise `FatalContractError`.
5. `test_registry_rejects_provider_id_mismatch`: registration key must match `artifact.provider_info["provider_id"]`.
6. `test_registry_get_unknown_provider_raises_unknown_provider_error`: missing lookup raises `UnknownProviderError`, the exception is a `FatalContractError`, and it is not an `IssuePolicyError`.
7. `test_providers_empty_registry_returns_empty_list`: public `rr.providers()` returns `[]` in M1 production/fresh registry.
8. `test_providers_sorted_independent_of_registration_order`: registered IDs are returned sorted ascending, not insertion order.
9. `test_provider_returns_registered_placeholder_object`: public `rr.provider("stub_provider")` returns the registered private handle but is only typed publicly as `object`.
10. `test_provider_unknown_raises_unknown_provider_error`: public lookup of a missing provider raises the fatal unknown-provider error; assert `UnknownProviderError` is not an `IssuePolicyError` subclass and no `IssuePolicyError` appears in the exception chain, because `rr.provider()` has no `on_issue` parameter and must not route through `apply_on_issue`.
11. `test_provider_info_empty_registry_returns_schema_conformant_catalog_result`: empty data has `ProviderInfoCatalog` columns/dtypes, issues are empty, and provenance equals the full expected `CatalogProvenance` object field-for-field.
12. `test_provider_info_aggregates_registered_provider_rows`: two stub provider rows are concatenated, sorted, validated, and wrapped in `CatalogResult`; one stub uses `catalogue_version=None` and the other a real string to exercise nullable-`Utf8` coercion from artifact dict rows.
13. `test_import_rivretrieve_does_not_import_providers_or_generators`: subprocess negative-control for the M1 offline-import invariant, plus an affirmative assertion that `rivretrieve._internal.catalogues.artifact` loaded so the subprocess proves a real package import path.
14. `test_init_public_surface_exports_m1_discovery_only`: update `tests/test_package.py` so `providers`, `provider`, and `provider_info` are present, while deferred/private names remain absent.
15. `test_m1_exit_criteria_smoke_sweep`: small direct assertions for the novel M1 closure criteria, while relying on existing step 01/02 tests for already-covered schema/artifact criteria.

Stub fixture strategy:

- Add a test-local fixture that builds a stub artifact with `packaged_catalogue_artifact_from_components(...)` (`artifact.py` lines 64-71).
- Use the schemas already validated in step 02.
- Use per-test registry cleanup through `_registry.clear()` in a fixture; never expose reset/clear publicly.
- Prefer Polars testing helpers for frame comparisons, per project instructions.

Offline-import mechanism:

- Use a subprocess, not in-process import state:
  - `sys.executable -c "..."`
  - import `rivretrieve`
  - inspect `sys.modules`
- Check exactly:
  - `"rivretrieve._internal.catalogues.artifact" in sys.modules`
  - `"rivretrieve.providers" not in sys.modules`
  - no module starts with `"rivretrieve.providers."`
  - no module final segment equals `"generate_catalogue"`
- This is meaningful before provider packages exist because it is a prospective guard: when M3 adds `src/rivretrieve/providers/ch_foen`, the same import-path assertions will catch accidental eager imports.

M1 exit-criteria sweep shape:

- Use one well-named smoke test rather than duplicating all step 01/02 tests.
- Directly assert:
  - `rr.providers()` is deterministic/offline using stub registration order.
  - `rr.provider("missing")` raises `UnknownProviderError`.
  - `rr.provider_info()` returns `CatalogResult(data, provenance, issues)`.
  - Stub artifact construction still validates.
  - Corrupt artifact fatal behavior and nullable station fields remain covered by existing tests; mention through comments/test naming only if direct duplication adds no value.
  - Offline import is covered by the dedicated subprocess test.
  - `uv run pytest` passing is the verifier, not an in-test assertion.

## 6. Files

Implementation order must keep `uv run pytest` green at every intermediate state:

1. `tests/conftest.py` or a new shared test helper module if needed
   - Add only a stub artifact builder/fixture that depends on step 02's already-shipped `packaged_catalogue_artifact_from_components(...)`.
   - Do not add a registry cleanup fixture in this slice, because importing `_registry` before `registry.py` exists would break repository-wide test collection.
   - Keep helpers test-only.
   - If adding this alone, existing tests should still pass.

2. `src/rivretrieve/_internal/registry.py`
   - Add `UnknownProviderError`, `_ProviderHandle`, `_ProviderRecord`, `ProviderRegistry`, and `_registry`.
   - Add the registry cleanup fixture that calls `_registry.clear()` in the same slice as `registry.py`, after the module exists.
   - No public imports yet.
   - Add focused internal registry tests in `tests/test_internal_registry.py`.
   - Run `uv run pytest tests/test_internal_registry.py`.

3. `src/rivretrieve/_internal/discovery.py`
   - Add internal implementations for `providers()`, `provider()`, and `provider_info()` backed by `_registry`.
   - Import `rivretrieve.__version__` inside the `provider_info()` function body so version access is deferred until call time and avoids module-load circular import pressure. Do not import provider packages.
   - Add tests in `tests/test_discovery.py` or `tests/test_public_discovery.py` that import through `_internal.discovery` first if `__init__.py` has not been updated yet.
   - Run targeted tests.

4. `src/rivretrieve/__init__.py`
   - Re-export only `providers`, `provider`, and `provider_info` in addition to the existing `__version__`.
   - D1 guard: this step may add only the three tracker-authorized public function symbols plus the version bump line. No `ProviderHandle`, `CatalogResult`, `Issue`, catalogue schemas, provider classes, or rearranged legacy-style imports.
   - Run `uv run pytest tests/test_package.py`.

5. `tests/test_package.py`
   - Replace the "only version" assertion with:
     - `__version__` exists.
     - `providers`, `provider`, and `provider_info` are public names.
     - no other public planned/deferred/private names leak.
   - Explicit absence list: `ProviderHandle`, `observations`, `stations`, `products`, `product_info`, `map_stations`, `ObservationResult`, `AnnotationSchema`, `Issue`, `CatalogResult`, `StationCatalog`, `ProductCatalog`, `StationProductCatalog`, `ProviderInfoCatalog`, `PackagedCatalogArtifact`, `CorruptCatalogArtifactError`.

6. `tests/test_offline_import.py`
   - Add the subprocess negative control.
   - Run the test alone and then with public-surface tests.

7. `tests/test_m1_exit_criteria.py`
   - Add the compact M1 sweep.
   - Avoid re-testing all artifact/schema edge cases already covered by step 02.

8. `docs/milestones/m1-harness-foundation/steps/03-registry-and-surface/execution.md`
   - Executor creates this after implementation, not during planning, with self-review and command evidence.
   - The staged step-doc set for the implementation commit must include `docs/milestones/m1-harness-foundation/steps/03-registry-and-surface/{plan.md, critique.md, execution.md}` alongside source/test files and the version bump.

9. Version files
   - After code/tests are green, run `uv run bump-my-version bump patch`.
   - This updates `pyproject.toml` and `src/rivretrieve/__init__.py` per D1 (`docs/discoveries.md` lines 5-33).
   - Commit and tag `v$(uv run bump-my-version show current_version)`.

Required verification before commit:

- `uv run ruff format`
- `uv run ruff check --fix`
- `uv run ty check`
- `uv run pytest`

## 7. Open questions

### Q1. ProviderRegistry shape

Recommendation: option (a), a frozen-ish class with `._providers: dict[str, _ProviderRecord]` and explicit register/get/list/iter/clear methods.

Rationale: M3 needs provider packages to register themselves when they are explicitly imported, but `import rivretrieve` must not import provider modules. A class provides a small state boundary without plugin discovery or eager imports. A module-level dict is too loose; a Pydantic model is unnecessary for private mutable process state.

### Q2. Where public functions live

Recommendation: option (b), implement in `src/rivretrieve/_internal/discovery.py` and re-export from `src/rivretrieve/__init__.py`.

Rationale: this keeps `__init__.py` small while respecting the internal naming convention established in steps 01 and 02. It also makes public-surface tests distinguish implementation from export.

### Q3. UnknownProviderError location and shape

Recommendation: option (b), define in `_internal/registry.py`.

Rationale: it is raised by registry lookup, and step 02 already established the local-exception pattern with `CorruptCatalogArtifactError` beside artifact validation (`artifact.py` lines 30-31).

### Q4. Provider handle placeholder type

Recommendation: private frozen dataclass `_ProviderHandle(provider_id: ProviderId, _artifact: PackagedCatalogArtifact)` with no M1 methods.

Rationale: public type remains `object` as tracker line 58 requires. The concrete object can be extended in M2 to satisfy the public `ProviderHandle` Protocol without changing the registry contract.

### Q5. Internal registration API

Recommendation: `_registry.register(provider_id: str, packaged_artifact: PackagedCatalogArtifact) -> _ProviderHandle`; duplicate registration raises.

Rationale: M1 tests and M3 provider package imports need only an ID and a validated artifact. Returning the handle is convenient for tests and avoids a second lookup. Double-registration should fail fast because duplicate IDs would make deterministic public discovery ambiguous.

### Q6. Provider ID format validation

Recommendation: validate at registration only, using `^[a-z][a-z0-9_]*$`.

Rationale: provider self-naming is the contract in `architecture.md` lines 51-58. User lookup failures should be "not registered" even when malformed, because no valid provider registration can create the malformed key.

### Q7. Determinism of rr.providers()

Recommendation: sorted ascending by provider ID.

Rationale: deterministic regardless of registration/import order, which will matter once M3 provider package registration exists.

### Q8. rr.provider_info() empty-registry behavior

Recommendation: return `CatalogResult(data=empty_provider_info_df, provenance=packaged_aggregate_provenance, issues=())`.

Rationale: `ProviderInfoCatalog.polars_schema` (`schemas.py` lines 89-101) gives the exact empty Polars frame shape; `CatalogResult` requires `data`, `provenance`, and tuple issues (`results.py` lines 29-34). This closes tracker lines 83-85 with no providers installed.

### Q9. Aggregate ProviderInfoCatalog row construction

Recommendation: concatenate/build rows from each registered artifact's `provider_info`, sort by `provider_id`, then validate against `ProviderInfoCatalog`.

Rationale: `PackagedCatalogArtifact.provider_info` is the validated row source (`artifact.py` lines 34-39 and 87-92). Duplicate provider IDs are blocked by the registry and rechecked by schema unique-key validation.

### Q10. CatalogProvenance for rr.provider_info()

Recommendation: use the field set in section 3 exactly.

Rationale: aggregate `provider_info()` is packaged/offline discovery, not a provider-scoped artifact result. Provenance should state the source and package version while leaving per-provider artifact fields empty until provider-scoped methods arrive.

### Q11. Offline-import test mechanism

Recommendation: subprocess.

Rationale: only a fresh interpreter gives a clean `sys.modules` view. In-process tests may already have imported test helpers or internals and can produce false positives or false negatives. This test is the binding M1 exit criterion from tracker line 88 and architecture lines 436-448.

### Q12. Stub-provider test fixture

Recommendation: per-test cleanup of the module-level `_registry` using internal `clear()`, plus local artifact construction with `packaged_catalogue_artifact_from_components(...)`.

Rationale: shared state would make determinism tests order-dependent. A private reset/clear method is acceptable for internal tests and must not be public.

### Q13. Public-surface negative-control update

Recommendation: assert the exact public names exported by `rivretrieve` are the three new functions, while checking `__version__` separately because it is intentionally present but starts with an underscore.

Assertion shape:

- `assert "__version__" in vars(rivretrieve)`
- `module_defined_names = {name for name in vars(rivretrieve) if not name.startswith("_")}`
- `assert module_defined_names == {"providers", "provider", "provider_info"}`
- Loop over deferred/private names and assert `not hasattr(rivretrieve, name)`.

Rationale: D1 says public-surface negative controls should assert symbol absence rather than file-content equality (`docs/discoveries.md` lines 21-29).

### Q14. M1 exit-criteria sweep test

Recommendation: one compact `test_m1_exit_criteria_smoke_sweep` plus dedicated offline-import and public-surface tests.

Rationale: step 01 and step 02 already cover issue policy, fatal errors, schema nullable fields, artifact validation, and corrupt artifacts. The sweep should close the novel registry/public-surface criteria without duplicating the full prior test matrix.

## 8. Deferrals

- Public `ProviderHandle` Protocol: M2. Hard rationale: tracker lines 22 and 52 state it must not be introduced empty; tracker line 115 introduces it only in M2.
- Provider handle catalogue methods (`info()`, `products()`, `stations()`, `station_products()`): M2. Hard rationale: tracker lines 100-126 put these in the complete no-provider harness milestone.
- `ProviderInfo` singular public object: M2. Hard rationale: M1 only ships aggregate `ProviderInfoCatalog` as `CatalogResult`.
- `ObservationRequest`, `ObservationResult`, `AnnotationSchema`, annotation tables, and observation provenance: M2. Hard rationale: tracker lines 101-107 and 130-140 assign them to M2.
- Real `src/rivretrieve/providers/` packages, `ch_foen`, packaged artifacts, and `generate_catalogue.py`: M3. Hard rationale: tracker lines 164-208 assign first real provider work to M3.
- Plugin entry points or `importlib.metadata.entry_points()` discovery: post-V1/out of scope. Hard rationale: tracker line 339 defers plugin entry points and tracker line 10 forbids speculative abstractions.
- `rr.stations()`, `rr.products()`, `rr.product_info()`, `rr.observations()`, and `rr.map_stations()`: M2/M4/M5. Hard rationale: tracker lines 117-119, 235, and 285 assign those APIs later.
- Live catalogue behavior or a `source=` argument on `rr.provider_info()`: defer. Hard rationale: `architecture.md` lines 217-218 keep top-level global discovery packaged/offline; M1 tracker line 59 gives no `source` parameter.
- Provider-owned Pydantic metadata models: M3. Hard rationale: architecture lines 256-266 describe provider-owned models, and tracker lines 169-175 place the first concrete provider metadata work in M3.
- Cross-provider crosswalks, quality harmonization, derived products, broad product vocabulary expansion, and backend policy abstractions: post-V1 or later milestones per tracker lines 333-345.

M3 handoff note: provider packages should explicitly call `_registry.register("ch_foen", artifact)` from the provider runtime package import path after loading packaged artifacts. M1 must not add a discovery loop that imports provider packages automatically.

## 9. Stopping conditions for the executor

Stop and escalate before committing if any of these occurs:

- `import rivretrieve` would need to import `rivretrieve.providers`, any provider submodule, `generate_catalogue.py`, `importlib.metadata.entry_points()`, or any plugin mechanism.
- The offline-import subprocess test cannot be made meaningful before providers exist.
- `rr.provider_info()` cannot return a schema-conformant empty Polars `DataFrame` under the existing `ProviderInfoCatalog.polars_schema`.
- Implementing the registry appears to require a public `ProviderHandle` Protocol, ABC, abstract provider class, or observation/annotation contract.
- Architecture, tracker, or prior step outputs conflict on registry behavior, fatal unknown-provider semantics, or the public M1 API shape; record the contradiction in `docs/discoveries.md` and surface it.
- `src/rivretrieve/__init__.py` changes beyond adding `providers`, `provider`, `provider_info`, and the patch-version line.
- Any public symbols leak beyond the authorized M1 surface.
- Any step leaves `uv run pytest` failing, imports broken, or package import non-offline.
- The executor is drawn toward live catalogue refresh, global `source=`, provider package layout, real `ch_foen`, plugin entry points, or other deferred work.

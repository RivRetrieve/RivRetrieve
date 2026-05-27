# 01-provider-info-and-module-contract Plan

## 1. Goal and scope

Ship the first M2 discovery contract slice without widening the public API:

- Add singular `ProviderInfo`, a frozen typed row view isomorphic to the M1 `ProviderInfoCatalog` one-row contract.
- Add internal `ProviderModule`, a `typing.Protocol` for the currently typeable subset of the flat provider runtime module contract from `architecture.md:394-425`, with only `info()` exercised in this step.
- Extend the existing private `_ProviderHandle` dataclass with `info() -> ProviderInfo`.
- Add a tests-only stub provider scaffold under `tests/` and a fixture that registers it into a fresh `ProviderRegistry`.
- Extend tests for ProviderInfo round-trip, `_ProviderHandle.info()`, ProviderModule attribute presence, offline import preservation, direct fatal raises, and public-surface negative control.

This step must not promote `_ProviderHandle` to public `ProviderHandle`, add catalogue handle methods, introduce observation/annotation real types, create real provider modules, or edit tracker/architecture/product dictionary docs. M2 does not block on the queued D2 architecture addenda; the singular `ProviderInfo` row contract cites the pinned M1 step 02 plan lines instead.

Legacy divergence: do not recreate `RiverDataFetcher`, `get_cached_metadata()`, or `get_available_variables()` from `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/base.py:9-23` and `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/base.py:51-77`. This step continues the redesign toward flat module functions and packaged Polars artifacts.

## 2. API surface touched (public + internal)

Public surface:

- No new public symbols.
- No `src/rivretrieve/__init__.py` API-shape edit. Only the mandatory version-literal bump is allowed before commit.
- `tests/test_package.py::test_init_public_surface_exports_m1_discovery_only` must still assert exactly `{"providers", "provider", "provider_info"}` as the module-defined public names.

Internal surface:

- Add `src/rivretrieve/_internal/provider_info.py`.
- Add `src/rivretrieve/_internal/provider_module.py`.
- Modify `src/rivretrieve/_internal/registry.py` to import `ProviderInfo` and add `_ProviderHandle.info(self) -> ProviderInfo`.
- Keep `ProviderRegistry.register(provider_id: str, packaged_artifact: PackagedCatalogArtifact) -> _ProviderHandle` unchanged.
- Keep `rivretrieve._internal.discovery.provider(provider_id: str) -> object` unchanged in this step; return-type narrowing is a later public promotion step.

Test-only surface:

- Add `tests/_stubs/` as a normal test package.
- Add one stub provider module under `tests/_stubs/` that implements `ProviderModule`.
- Add a fixture that constructs a fresh `ProviderRegistry`, registers the stub provider's artifact directly with `ProviderRegistry.register(...)`, and returns the registered handle and/or registry for tests.

## 3. Data structures and types (field-level for ProviderInfo and ProviderModule)

### ProviderInfo

Source of truth: M1 step 02 plan `docs/milestones/m1-harness-foundation/steps/02-catalogue-schemas/plan.md:124-139` pins the `ProviderInfoCatalog` row contract as `{provider_id, name, live_stations, live_products, live_station_products, bulk_observations, catalogue_version, metadata}` with `metadata` canonicalized to a sorted-key JSON object string. `ProviderInfo` must be isomorphic to exactly that row.

Define in `src/rivretrieve/_internal/provider_info.py`:

- `class ProviderInfoValidationError(FatalContractError)`: direct fatal exception for malformed provider info rows.
- `@dataclass(frozen=True) class ProviderInfo`.
- `provider_id: ProviderId`.
- `name: str`.
- `live_stations: bool`.
- `live_products: bool`.
- `live_station_products: bool`.
- `bulk_observations: str`.
- `catalogue_version: str | None`.
- `metadata: str`.

Construction API:

- `ProviderInfo.from_row(row: Mapping[str, object]) -> ProviderInfo`.
- `ProviderInfo.to_row() -> dict[str, object]`.

Validation path:

- `from_row` should build a one-row `pl.DataFrame` with `ProviderInfoCatalog.polars_schema`, call `validate_catalogue(..., ProviderInfoCatalog, on_issue="raise")`, then convert the validated row into the frozen dataclass.
- Catch `FatalContractError` and `pl.exceptions.PolarsError` and raise `ProviderInfoValidationError` with exception chaining.
- Before validation, select only the exact `ProviderInfoCatalog` columns from `row`. Extra keys in the input mapping are ignored by the typed row view and remain recoverable/ignored at this boundary rather than being escalated into a fatal `ProviderInfoValidationError`.
- After validation, wrap the row's provider ID with `ProviderId(...)` before assigning it to `ProviderInfo.provider_id`, matching the M1 registry boundary pattern for `NewType` values.
- Do not introduce a parallel `CatalogueSchema`; reuse `ProviderInfoCatalog`.
- Keep `metadata` as a raw JSON string. It must parse as a JSON object string under the reused catalogue validator; no parsed dict is exposed in this step.

### _ProviderHandle.info()

Implementation contract in `src/rivretrieve/_internal/registry.py`:

- `_ProviderHandle.info(self) -> ProviderInfo` returns `ProviderInfo.from_row(self._artifact.provider_info)`.
- It reads only the registered packaged artifact row.
- It performs no provider import, no network call, and no `apply_on_issue`.
- Malformed rows raise `ProviderInfoValidationError` directly.

### ProviderModule

Define in `src/rivretrieve/_internal/provider_module.py`:

- `@runtime_checkable class ProviderModule(Protocol)`.
- `def info() -> ProviderInfo: ...`
- `def products(*, source: CatalogSource = "packaged", observed_property: str | None = None, frequency: str | None = None, statistic: str | None = None, on_issue: OnIssue = "warn") -> CatalogResult[pl.DataFrame]: ...`
- `def stations(*, source: CatalogSource = "packaged", on_issue: OnIssue = "warn") -> CatalogResult[pl.DataFrame]: ...`
- `def station_products(stations: Sequence[str] | None = None, *, source: CatalogSource = "packaged", on_issue: OnIssue = "warn") -> CatalogResult[pl.DataFrame]: ...`

Recommendation for Q3: declare only the architecture.md §9 provider-module functions whose dependency types already exist in this commit: `info`, `products`, `stations`, and `station_products`. Do not add a `register()` member; architecture.md §9 names seven provider-module functions and does not authorize registration as part of the provider-module contract. Do not declare `row_annotation_schema`, `series_annotation_schema`, or `observations` in step 01 because their signatures depend on `AnnotationSchema`, `ObservationRequest`, and `ObservationResult`, which are intentionally not real types yet. This is Q3 option (a), not the full forward-ref option. It avoids unverified static-checker behavior for unresolved string annotations and avoids placeholder observation/annotation types that would look like real contracts.

The three catalogue methods use `CatalogResult[pl.DataFrame]` in this internal Protocol because that is the concrete M1 implementation shape in `rivretrieve._internal.discovery.provider_info()`. The architecture/tracker wording `CatalogResult[ProductCatalog]` treats schema objects as conceptual table contracts rather than runtime generic parameters; D2's queued architecture addendum should reconcile that wording before public promotion.

The stub module should implement exactly these Protocol function names. Only `info()` needs meaningful step-01 behavior; catalogue functions should raise `NotImplementedError` because public catalogue methods on handles are deferred to M2 step 02 and must not be called as harness behavior in step 01 tests. Stub-private artifact construction lives in `tests/_stubs/stub_provider.py` as `build_artifact()`, which delegates to the existing `stub_packaged_catalogue_artifact` factory passed in by the fixture; it is not part of `ProviderModule`.

## 4. Errors and failure modes (separate fatal-raise from Issue-routed paths)

Fatal direct raises, never routed through `apply_on_issue`:

- Missing required ProviderInfo field: `ProviderInfoValidationError`.
- Wrong field dtype, including non-string `provider_id`, `name`, `bulk_observations`, `metadata`, non-boolean capability flags, or invalid `catalogue_version`: `ProviderInfoValidationError`.
- Null in a non-nullable ProviderInfo field: `ProviderInfoValidationError`.
- Invalid metadata JSON string: `ProviderInfoValidationError`.
- Metadata JSON that parses but is not an object, such as `[]` or `null`: `ProviderInfoValidationError`.
- ProviderInfo cannot be converted to a one-row `ProviderInfoCatalog` DataFrame: `ProviderInfoValidationError`.
- ProviderInfo row has zero rows or multiple rows after conversion, if an executor chooses a tabular helper path internally: `ProviderInfoValidationError`.
- `_ProviderHandle.info()` sees a malformed packaged artifact row: `ProviderInfoValidationError`.
- Stub registration attempts invalid or duplicate provider IDs: existing `FatalContractError` / `UnknownProviderError` paths remain direct raises from `ProviderRegistry`.

Issue-routed paths:

- None are introduced as public step-01 behavior.
- Extra columns are not fatal in `ProviderInfo.from_row`; select only the pinned `ProviderInfoCatalog` columns before validation. This preserves M1's recoverable-extra-column decision instead of silently escalating a warning-channel condition into a fatal contract error. No `on_issue` parameter is exposed on `ProviderInfo.from_row` or `_ProviderHandle.info()`.
- Future provider catalogue methods will own `Issue + apply_on_issue` behavior for live unsupported catalogues and recoverable catalogue diagnostics in later M2 steps.

## 5. Tests (enumerated, one-line each; include negative controls)

T01. `test_provider_info_from_row_matches_provider_info_catalog_contract`: valid row becomes the expected frozen `ProviderInfo`.

T02. `test_provider_info_to_row_round_trips_catalogue_row`: `ProviderInfo.from_row(row).to_row()` returns an isomorphic row with canonical raw JSON metadata string.

T03. `test_provider_info_metadata_is_raw_json_string`: metadata remains `str`, not a parsed dict.

T04. `test_provider_info_rejects_missing_required_field`: omitting each required field raises `ProviderInfoValidationError`.

T05. `test_provider_info_rejects_wrong_field_type`: representative wrong dtypes raise `ProviderInfoValidationError`.

T06. `test_provider_info_rejects_invalid_metadata_json`: malformed metadata JSON raises `ProviderInfoValidationError`.

T07. `test_provider_info_rejects_non_object_metadata_json`: metadata JSON values such as `[]` raise `ProviderInfoValidationError`.

T08. `test_provider_handle_info_fatal_failures_are_direct`: construct `_ProviderHandle` with a hand-built artifact carrying malformed `provider_info` and assert `handle.info()` raises direct `ProviderInfoValidationError` with no `IssuePolicyError` in the cause/context chain.

T09. `test_provider_handle_info_reads_packaged_artifact_row`: a handle registered with a synthetic artifact returns matching `ProviderInfo`.

T10. `test_provider_handle_info_malformed_artifact_row_raises_provider_info_validation_error`: direct handle construction with a bad artifact row raises the fatal subclass.

T11. `test_stub_provider_module_has_provider_module_attributes`: the tests-only stub satisfies `isinstance(stub_provider, ProviderModule)`, proving runtime-checkable Protocol attribute presence for the step-01 subset.

T12. `test_stub_provider_info_matches_registered_handle_info`: stub `info()` and registered handle `info()` agree.

T13. `test_stub_provider_registers_into_fresh_registry_only`: fixture-scoped registration populates the fresh registry, leaves module-level `_registry.list_provider_ids() == []`, and proves the stub module does not write to global discovery state.

T14. `test_stub_provider_does_not_register_at_import_time`: importing the stub module alone leaves a fresh registry empty.

T15. `test_import_rivretrieve_does_not_import_test_stubs`: subprocess `import rivretrieve` leaves every `tests._stubs...` module absent from `sys.modules`.

T16. `test_init_public_surface_exports_m1_discovery_only`: keep the M1 four-name public surface invariant, including `__version__` plus the three discovery functions and no `ProviderInfo`, `ProviderModule`, or `ProviderHandle`.

T17. `test_stub_catalogue_functions_are_explicitly_unimplemented_in_step_01`: assert the stub `products()`, `stations()`, and `station_products()` functions raise `NotImplementedError`, proving they exist for Protocol attribute presence but are not step-01 harness behavior.

## 6. Files (new + modified, in implementation order keeping pytest green at each)

1. Add `src/rivretrieve/_internal/provider_info.py` with `ProviderInfoValidationError`, `ProviderInfo`, `from_row`, and `to_row`. Run `uv run pytest`.
2. Add `tests/test_internal_provider_info.py` covering T01-T07 with existing synthetic row helpers. Run `uv run pytest`.
3. Modify `src/rivretrieve/_internal/registry.py` to add `_ProviderHandle.info() -> ProviderInfo`, without changing registry public behavior. Run `uv run pytest`.
4. Add or extend registry tests for T08-T10. Run `uv run pytest`.
5. Add `src/rivretrieve/_internal/provider_module.py` with the `ProviderModule` Protocol subset: `info`, `products`, `stations`, and `station_products`. Do not add `register`, observation, or annotation members. Run `uv run pytest`.
6. Add `tests/_stubs/__init__.py` and `tests/_stubs/stub_provider.py`. The module must not register itself at import time. Run `uv run pytest`.
7. Add fixture(s) in `tests/conftest.py` that create a fresh `ProviderRegistry`, pass the existing `stub_packaged_catalogue_artifact` factory into `tests._stubs.stub_provider.build_artifact(...)`, and call `fresh_registry.register("stub_provider", artifact)` directly. `build_artifact()` must delegate to the existing conftest factory rather than duplicating synthetic artifact construction. Run `uv run pytest`.
8. Add `tests/test_internal_provider_module.py` covering T11-T14 and T17. Run `uv run pytest`.
9. Extend `tests/test_offline_import.py` for T15. Run `uv run pytest`.
10. Extend `tests/test_package.py` absence list to include `ProviderInfo` and `ProviderModule` for T16. Run `uv run pytest`.
11. Run `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, and `uv run pytest`.
12. Run `uv run bump-my-version bump patch`, stage the version files with the docs/code/test changes, commit, and tag per project instructions and D1's tag-after-bump convention in `docs/discoveries.md`.

## 7. Open questions (with recommendation per question)

Q1. ProviderInfo.metadata: parsed dict or raw JSON string?

Recommendation: raw JSON string. It preserves exact isomorphism with `ProviderInfoCatalog.metadata` from M1 step 02 plan lines 124-139, avoids decode/re-encode drift, keeps the singular row a lossless artifact view, and does not pre-empt a later public ergonomics decision. Public dictionary metadata can be introduced at a later boundary if the architecture addendum requires it.

Q2. ProviderInfo construction path: artifact dict, one-row DataFrame, or typed kwargs?

Recommendation: expose `ProviderInfo.from_row(row: Mapping[str, object])` and internally validate through a one-row `ProviderInfoCatalog` DataFrame. The artifact already stores `provider_info` as a validated row-shaped dict, so callers do not need to build Polars frames. Internally using the DataFrame validator avoids duplicating schema rules and keeps the fatal behavior aligned with M1.

Q3. Which ProviderModule Protocol methods are declared in step 01?

Recommendation: declare the architecture.md §9 functions whose dependency types already exist: `info`, `products`, `stations`, and `station_products`. Do not add `register()` because it is not one of the seven architecture-owned provider-module functions and would be speculative. Defer `row_annotation_schema`, `series_annotation_schema`, and `observations` until M2 steps 04-05 introduce real `AnnotationSchema`, `ObservationRequest`, and `ObservationResult` types. This accepts one later Protocol edit, but it is the most truthful static-checking path and avoids unverified unresolved forward refs or placeholder contracts.

Q4. Where exactly does the stub provider live?

Recommendation: `tests/_stubs/stub_provider.py`, with `tests/_stubs/__init__.py`. The underscore marks it as test support, it is importable by explicit pytest tests, and it is invisible to `import rivretrieve` because it is outside `src/rivretrieve`. Avoid `tests/_stubs/test_provider.py` because pytest may collect it as a test module; avoid `tests/conftest_stubs/...` because it blurs fixture plumbing with provider-module shape.

Q5. How is the stub registered?

Recommendation: option (a), fixture calls `ProviderRegistry.register(...)` on a fresh `ProviderRegistry` using the stub provider's artifact. Do not monkeypatch the module-level `_registry` singleton and do not put registration on the `ProviderModule` Protocol. Existing `tests/conftest.py` already has an autouse clear for `_registry`, but T13 must still explicitly assert that the fresh registry has the stub provider while `_registry.list_provider_ids() == []` after fixture registration. This choice forces no refactor of `rivretrieve._internal.discovery` in step 01 because discovery functions are not under test for stub-provider module registration; they continue to use `_registry`.

Q6. What fatal validation happens when constructing ProviderInfo from an artifact row?

Recommendation: use one new subclass, `ProviderInfoValidationError(FatalContractError)`, for missing fields, wrong dtypes, null non-nullable fields, invalid JSON metadata, non-object metadata JSON, DataFrame conversion failures, and non-single-row conversion results. These raise directly from `ProviderInfo.from_row` and `_ProviderHandle.info()`. They must never become `Issue` objects and never pass through `apply_on_issue`. The direct-raise negative control should inspect the exception chain for absence of `IssuePolicyError`; it should not parametrize through `packaged_catalogue_artifact_from_components(..., on_issue=...)`, because that artifact boundary correctly rewraps malformed provider info as `CorruptCatalogArtifactError`.

Q7. Negative-control test inventory for this step.

Recommendation: own these negative controls:

- Public surface remains the M1 set: `{"providers", "provider", "provider_info"}` plus `__version__` present; `ProviderInfo`, `ProviderModule`, and `ProviderHandle` absent.
- Offline import subprocess confirms `tests._stubs` and `tests._stubs.stub_provider` are absent from `sys.modules` after `import rivretrieve`.
- Stub import alone does not register into any registry.
- Stub registration fixture uses a fresh `ProviderRegistry`, proves the fresh registry contains the stub provider, and proves `_registry` remains empty.
- Fatal ProviderInfo validation paths raise `ProviderInfoValidationError` directly from `ProviderInfo.from_row` / `_ProviderHandle.info()`, with no `IssuePolicyError` in the cause/context chain.
- Deferred ProviderModule catalogue methods are not called by step-01 harness tests.

## 8. Deferrals (with hard rationale: which later step or milestone handles each)

- Public `ProviderHandle` Protocol promotion: later M2 step. Hard rationale: this step adds only `info()` to the private handle; tracker §2 forbids an empty or partial public Protocol.
- `_ProviderHandle` rename or export: later M2 step when all seven methods have real behavior. Hard rationale: M1 intentionally returned `object`; step 01 should only extend the private runtime object.
- `products()`, `stations()`, and `station_products()` on handles: M2 step 02. Hard rationale: catalogue method behavior needs `CatalogResult`, packaged table readers, filters, and source semantics beyond singular provider info.
- Global `rr.stations()`, `rr.products()`, and `rr.product_info()`: M2 step 02. Hard rationale: this step does not alter public surface.
- `source="packaged" | "live"` validation and `LiveCatalogueUnsupportedIssue`: M2 step 03. Hard rationale: no public catalogue source parameter is introduced here.
- Real `ObservationRequest`, `ObservationResult`, `ObservationProvenance`, `AnnotationSchema`, `AnnotationTable`, and `RawPayload`: M2 steps 04-05. Hard rationale: step 01 does not declare Protocol members that depend on these names.
- `observations()`, `row_annotation_schema()`, and `series_annotation_schema()` ProviderModule members and implementations: M2 steps 04-05. Hard rationale: their signature types do not exist yet, and this plan chooses not to rely on unresolved forward refs or placeholders.
- `to_polars()` / `to_pandas()` exports: M2 step 05. Hard rationale: no observation result exists in this step.
- Real provider modules, including `ch_foen`: M3. Hard rationale: step 01 uses only tests-only stubs and must not create `src/rivretrieve/providers/...`.
- D2 queued architecture §7/§9 addenda and edits to `docs/milestone-tracker.md`, `architecture.md`, or `docs/product_dictionary.md`: project coordinator work before M3 unless a later step proves a real contradiction. This step can cite the M1 row contract directly and does not need those edits.
- Parsed public metadata dictionaries: later public API design. Hard rationale: step 01 is a private exact artifact row view; public ergonomics should not break the Parquet row contract.

## 9. Stopping conditions for the executor

Stop and surface if any of these happen:

- Implementing `ProviderModule` appears to require adding `register()` or any provider-module function not named by `architecture.md:399-425`.
- Implementing `ProviderModule` appears to require real `ObservationRequest`, `ObservationResult`, `AnnotationSchema`, annotation tables, raw payload types, observation implementations, unresolved forward refs, or placeholder aliases/classes.
- Preserving offline import requires moving the stub provider under `src/` or importing it from `rivretrieve`.
- The fresh-registry fixture cannot test provider registration without monkeypatching `_registry` or refactoring `rivretrieve._internal.discovery`.
- Adding `_ProviderHandle.info()` tempts promotion, rename, public export, or a parallel public `ProviderHandle`.
- ProviderInfo validation cannot reuse `ProviderInfoCatalog` without introducing a parallel schema representation.
- ProviderInfo fatal failures would be silenceable through `on_issue="ignore"` or routed as `Issue` objects.
- `metadata` cannot remain a raw JSON object string while round-tripping through the existing artifact row contract.
- The executor needs to import provider packages, add `src/rivretrieve/providers/...`, or touch maintainer-only `generate_catalogue.py`.
- The implementation reaches for catalogue handle methods, global discovery methods, source validation, live unsupported issues, observation contracts, annotation schemas, or export helpers.
- D2's queued architecture addenda become necessary for step-01 correctness rather than merely desirable documentation.
- Any intermediate file-sized boundary leaves `uv run pytest` failing or package import broken.

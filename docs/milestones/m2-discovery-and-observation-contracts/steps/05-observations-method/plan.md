# 05-observations-method Plan

## 1. Goal and scope

Ship the internal observation-dispatch slice in one commit:

- Extend `ProviderModule` to the full seven-member architecture surface: `info`, `products`, `stations`, `station_products`, `row_annotation_schema`, `series_annotation_schema`, and `observations`.
- Extend `ProviderRegistry.register(...)` so a registered provider can carry an optional provider module reference alongside its packaged catalogue artifact.
- Extend the private `_ProviderHandle` with `row_annotation_schema()`, `series_annotation_schema()`, and `observations(...)`.
- Make `_ProviderHandle.observations(...)` own public-call normalization by constructing `ObservationRequest.from_inputs(...)`, dispatch to the registered module, validate emitted annotation names against the provider's declared row and series schemas, and return the module's `ObservationResult`.
- Extend `tests/_stubs/stub_provider.py` with real observation and annotation-schema implementations while preserving the catalogue-method `NotImplementedError` invariant.
- Extend the `registered_stub` fixture so the stub artifact and module are registered together.
- Add tests for single and bulk observation calls, fatal request validation before provider execution, missing module dispatch, undeclared annotation names, schema delegation, ProviderModule conformance, and registration back-compat.

This step does not promote `_ProviderHandle` to public `ProviderHandle`, narrow `rr.provider()`'s return type, add public observation exports, add top-level `rr.observations(...)`, create real providers under `src/rivretrieve/providers/`, or perform network I/O. The public package surface remains the M2 step-02 catalogue surface.

Legacy divergence: the old base class accepts one `gauge_id`, one `variable`, optional `start_date` / `end_date`, and returns an indexed single-variable pandas frame (`/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/base.py:17-23`, `:39-42`). `USAFetcher.get_data` and `UKEAFetcher.get_data` format missing dates, call provider-specific download/parse helpers, and return wide single-variable pandas frames or empty frames on broad exceptions (`/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/usa.py:126-169`, `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/uk_ea.py:175-224`). Step 05 deliberately diverges: dates are required, request normalization is handle-owned, modules receive `ObservationRequest`, results are `ObservationResult` with long Polars data and annotation tables, and no provider network behavior exists yet.

## 2. API surface touched (public + internal)

Public surface:

- No new public symbols.
- No `src/rivretrieve/__init__.py` API-shape edit. Only the mandatory version-literal bump is allowed before commit.
- Keep public names exactly `{"providers", "provider", "provider_info", "stations", "products", "product_info"}` plus `__version__`.
- Extend the deferred-public-name absence test to include `ObservationsUnavailableError` if this plan's recommended exception name is used.

Internal surface:

- Modify `src/rivretrieve/_internal/provider_module.py`:
  - Import `ObservationRequest`, `ObservationResult`, and `AnnotationSchema`.
  - Add `@staticmethod def row_annotation_schema() -> list[AnnotationSchema]`.
  - Add `@staticmethod def series_annotation_schema() -> list[AnnotationSchema]`.
  - Add `@staticmethod def observations(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult`.
- Modify `src/rivretrieve/_internal/registry.py`:
  - Import `ProviderModule`, `ObservationRequest`, `ObservationResult`, `AnnotationSchema`, and `validate_annotation_names`.
  - Add an optional provider-module field to `_ProviderHandle`.
  - Add `_ProviderHandle.row_annotation_schema() -> list[AnnotationSchema]`.
  - Add `_ProviderHandle.series_annotation_schema() -> list[AnnotationSchema]`.
  - Add `_ProviderHandle.observations(*, stations: str | Sequence[str], products: str | Sequence[str], start: object, end: object, on_issue: OnIssue = "warn") -> ObservationResult`.
  - Extend `ProviderRegistry.register(provider_id, packaged_artifact, provider_module: ProviderModule | None = None) -> _ProviderHandle`.
- Modify `src/rivretrieve/_internal/issues.py`:
  - Add `ObservationsUnavailableError(FatalContractError)` for calling `handle.observations(...)` or schema methods when no module was registered.

Test-only surface:

- Modify `tests/_stubs/stub_provider.py` to add real `observations(request, *, on_issue=...)`, `row_annotation_schema()`, and `series_annotation_schema()`.
- Keep `stub_provider.products`, `.stations`, and `.station_products` as `NotImplementedError`-raising functions.
- Modify `tests/conftest.py::registered_stub` to pass `provider_module=stub_provider` into `fresh_registry.register(...)`.
- Add `tests/test_internal_handle_observations.py` for the new handle-observation behavior.
- Extend `tests/test_internal_provider_module.py`, `tests/test_internal_registry.py`, and `tests/test_package.py` narrowly.

## 3. Data structures and behavior

### Provider module registration

Recommendation: extend `ProviderRegistry.register` to:

```python
def register(
    self,
    provider_id: str,
    packaged_artifact: PackagedCatalogArtifact,
    provider_module: ProviderModule | None = None,
) -> _ProviderHandle: ...
```

The registry already owns the one place that binds a provider ID to an artifact and returns the handle (`src/rivretrieve/_internal/registry.py:83-103`). Adding the module there keeps registration atomic and avoids a two-phase "registered but half-dispatchable" state. It also avoids lazy imports from `rivretrieve.providers.<provider_id>`, which cannot support the M2 tests-only stub at `tests/_stubs/stub_provider.py`.

Do not change `PackagedCatalogArtifact`. The module reference is registry state, not artifact shape.

### _ProviderHandle module field

Add a private field:

- `_module: ProviderModule | None = None`.

Use `_module`, not `provider_module`, because `_ProviderHandle._artifact` already uses a leading underscore for stored implementation dependencies. The field must default to `None` so existing direct constructions in `tests/test_internal_registry.py:103` and `tests/test_internal_registry.py:132` continue to compile and remain behaviorally focused on `info()` before observation tests are added.

`_ProviderRecord` does not need a separate module field in this step because its `handle` carries the dispatch reference. Keep `provider_id`, `artifact`, and `handle` unless implementation evidence shows `iter_records()` needs direct module access; global discovery does not.

### ProviderModule observation signature

Recommendation: use the architecture-owned internal module signature:

```python
def observations(
    request: ObservationRequest,
    *,
    on_issue: OnIssue = "warn",
) -> ObservationResult: ...
```

This follows `architecture.md:423-425` and `architecture.md:428`: the public/provider handle adapts loose user keyword arguments into typed internal requests, and provider modules receive normalized objects. It prevents duplicated request validation in every provider module. The public-shaped signature with loose `stations`, `products`, `start`, and `end` belongs on `_ProviderHandle` now and public `ProviderHandle` in step 06, not on `ProviderModule`.

This means `ObservationRequest` is part of the internal `ProviderModule` contract from step 05 onward. That is acceptable because step 04 has already shipped `ObservationRequest` and the request carries `provider_id`, normalized station/product tuples, and typed temporal values.

### _ProviderHandle.observations()

Behavior:

- Signature is keyword-only for `stations`, `products`, `start`, `end`, and `on_issue`, matching tracker §2 line 13 and `architecture.md:128-130`.
- If `_module is None`, raise `ObservationsUnavailableError` directly before request construction or provider dispatch.
- Construct:
  - `ObservationRequest.from_inputs(provider_id=self.provider_id, stations=stations, products=products, start=start, end=end)`.
- Let `ObservationRequest.from_inputs` own missing/malformed request fatals (`InvalidObservationRequestError`).
- Call `self._module.observations(request, on_issue=on_issue)`.
- Fetch declarations from the same module with `row_annotation_schema()` and `series_annotation_schema()`.
- Call:
  - `validate_annotation_names(result.row_annotations, row_schemas)`.
  - `validate_annotation_names(result.series_annotations, series_schemas)`.
- Return the `ObservationResult` unchanged if validation passes.

The module-presence check intentionally happens before request construction. A missing module is a stable registry wiring fatal, so reporting `ObservationsUnavailableError` first is clearer for artifact-only handles than letting call-site input errors mask the unregistered dispatch path. Registered-module calls still construct `ObservationRequest` before provider execution, so no fatal-input case can reach the provider module.

Annotation-name validation should happen on every handle observation call. This is an explicit tightening of `architecture.md:556`, which says the harness validates names in tests or debug validation. The architecture does not forbid production-time enforcement, and the check is cheap, structural, and enforces the provider contract that declarations precede emitted names (`architecture.md:539-557`). Always validating avoids a production/debug split that would silently emit undeclared annotation IDs in normal use. No architecture addendum is needed unless a later provider port shows the cost is material.

Do not route module absence, request validation, malformed result construction, or undeclared annotation names through `apply_on_issue`. Step 05 introduces no new recoverable observation issue paths.

### _ProviderHandle schema methods

Behavior:

- `row_annotation_schema()` raises `ObservationsUnavailableError` if `_module is None`; otherwise returns `self._module.row_annotation_schema()`.
- `series_annotation_schema()` raises `ObservationsUnavailableError` if `_module is None`; otherwise returns `self._module.series_annotation_schema()`.
- These methods do not validate result data and do not call catalogue methods.

### Stub observations

The stub provider should produce deterministic long-form data from the request, not inspect network state and not call its catalogue functions. Use its known test IDs as the accepted universe:

- Known station IDs: `"station-1"`, `"station-2"`.
- Known product IDs: `"level"`, `"flow"`, `"level_hourly"`, `"level_max"`.

These IDs are hardcoded into `stub_provider.observations`, independent of the registered artifact's stations/products tables. The default artifact contains only `"station-1"` / `"level"` and the rich fixture contains the rest, but the stub observation implementation does not consult either catalogue.

Rows:

- For every requested `(station_id, product_id)` pair where both IDs are known, emit two rows at `request.start` and `request.end`.
- Use `value` as a deterministic float based on station/product position, for example `1.0`, `2.0`, `3.0`, ... in stable loop order. The exact formula is less important than deterministic results and easy expected-frame construction.
- For unknown station/product combinations, emit no rows and no issue. This mirrors packaged catalogue filter behavior where no-match filters return empty results, not fatal errors.
- Empty station/product sequences never reach the stub because `ObservationRequest.from_inputs` rejects them.
- Unknown-only calls still return a fully typed empty `ObservationResult`: `data`, `row_annotations.data`, and `series_annotations.data` are zero-row Polars frames carrying the canonical `ObservationDataSchema`, `RowAnnotationTableSchema`, and `SeriesAnnotationTableSchema` dtypes.

Result shape:

- `data`: Polars frame satisfying `ObservationDataSchema` with columns `time`, `station_id`, `product_id`, `value`.
- `row_annotations`: `AnnotationTable(..., RowAnnotationTableSchema)` with one declared row annotation per emitted data row, e.g. `annotation="stub.quality"`, `value="good"`.
- `series_annotations`: `AnnotationTable(..., SeriesAnnotationTableSchema)` with one declared series annotation per emitted station/product pair, e.g. `annotation="stub.native_unit"`, `value="m"`.
- `provenance`: `ObservationProvenance(source="stub", provider_id=request.provider_id, catalogue_version="2026.01", request={"provider_id": str(request.provider_id), "stations": list(request.stations), "products": list(request.products), "start": request.start.isoformat(), "end": request.end.isoformat()})`.
- `issues=()`.
- `raw=None`.

The stub should not use `on_issue` because it emits no recoverable issues in this step.

### Stub annotation schemas

`stub_provider.row_annotation_schema()` returns at least:

- `AnnotationSchema(annotation_id="stub.quality", description="Stub row quality flag.", value_type="string", allowed_values=("good", "suspect"), source_field="quality")`.

`stub_provider.series_annotation_schema()` returns at least:

- `AnnotationSchema(annotation_id="stub.native_unit", description="Stub native unit returned for the series.", value_type="string", allowed_values=("m", "m3/s"), source_field="unit")`.

These IDs are test scaffolding, not provider namespace policy for future real providers. Provider-specific annotation ID conventions belong to M3+ provider ports.

## 4. Errors and failure modes

Fatal direct raises, never routed through `apply_on_issue`:

- `_ProviderHandle.observations(...)` called when `_module is None`: `ObservationsUnavailableError`.
- `_ProviderHandle.row_annotation_schema()` or `.series_annotation_schema()` called when `_module is None`: `ObservationsUnavailableError`.
- Missing `start` or `end`: existing `InvalidObservationRequestError` from `ObservationRequest.from_inputs`.
- Missing, empty, non-sequence, or malformed `stations` / `products`: existing `InvalidObservationRequestError`.
- Wrong temporal input types or unparseable timestamp strings: existing `InvalidObservationRequestError`.
- Provider module returns malformed observation data: existing `ObservationDataSchemaError` from `ObservationResult` construction.
- Provider module returns malformed annotation tables: existing `AnnotationSchemaViolationError` from `AnnotationTable` construction.
- Provider module emits row or series annotation names not declared by the corresponding schema method: `AnnotationSchemaViolationError` from `validate_annotation_names`.
- Provider module raises its own fatal contract error: propagate directly.

Issue-routed paths:

- None are introduced by step 05.
- `on_issue` is accepted by the handle and passed to the module so future providers can report recoverable observation issues, but the M2 stub returns no issues and no `apply_on_issue` call is added at the handle layer.
- Do not invent missing-station/product issues here. Unknown stub station/product combinations produce empty data, not a warning.

Error placement:

- Add `ObservationsUnavailableError` to `src/rivretrieve/_internal/issues.py`. It is a cross-cutting handle/module dispatch fatal, not a registry lookup error and not an artifact-validation error. It should subclass `FatalContractError`.

## 5. Tests (enumerated, one-line each; include negative controls)

Step 04 ended at T83. Step 05 starts at T84 and should add about 22-28 tests after parametrization:

T84. `test_provider_handle_observations_single_station_product_returns_valid_result`: registered stub handle returns an `ObservationResult` with canonical rows for `stations="station-1"` and `products="level"` and provenance `request` mirroring the normalized input.

T85. `test_provider_handle_observations_bulk_station_product_returns_valid_result`: the same handle method accepts station and product sequences and returns rows for the known cross-product.

T86. `test_provider_handle_observations_unknown_station_or_product_returns_empty_result`: unknown IDs produce empty but typed canonical data, empty but typed row/series annotation tables, and no issues, not a fatal.

T87. `test_provider_handle_observations_constructs_normalized_request_before_dispatch`: monkeypatch or spy the stub module observations function and assert it receives `ObservationRequest` with provider ID, tuple stations/products, and typed temporal values.

T88. `test_provider_handle_observations_passes_on_issue_to_module`: spy module receives `"warn"`, `"raise"`, and `"ignore"` unchanged.

T89. `test_provider_handle_observations_missing_start_raises_before_provider_execution`: parametrized over `on_issue`; missing `start` raises `InvalidObservationRequestError` with no `IssuePolicyError` chain and the provider spy is not called.

T90. `test_provider_handle_observations_missing_end_raises_before_provider_execution`: same for missing `end`, including no `IssuePolicyError` chain.

T91. `test_provider_handle_observations_empty_stations_raises_before_provider_execution`: parametrized over `on_issue`; empty stations raise direct fatal with no `IssuePolicyError` chain and no provider call happens.

T92. `test_provider_handle_observations_empty_products_raises_before_provider_execution`: same for empty products, including no `IssuePolicyError` chain.

T93. `test_provider_handle_observations_bad_station_product_types_raise_before_provider_execution`: representative wrong ID values raise `InvalidObservationRequestError` with no `IssuePolicyError` chain.

T94. `test_provider_handle_observations_no_module_registered_raises_direct_fatal_for_every_on_issue`: artifact-only handle raises `ObservationsUnavailableError` for all policies with no `IssuePolicyError` chain.

T95. `test_provider_handle_row_annotation_schema_no_module_registered_raises_direct_fatal`: schema method on artifact-only handle raises `ObservationsUnavailableError`.

T96. `test_provider_handle_series_annotation_schema_no_module_registered_raises_direct_fatal`: same for series schema.

T97. `test_provider_handle_observations_undeclared_row_annotation_raises_direct_fatal`: monkeypatch module result to include an undeclared row annotation and assert `AnnotationSchemaViolationError` for every `on_issue`.

T98. `test_provider_handle_observations_undeclared_series_annotation_raises_direct_fatal`: same for series annotations.

T99. `test_provider_handle_observations_validates_row_and_series_annotation_names`: use distinct row and series annotation IDs and bad module results to prove both tables are checked, avoiding monkeypatch dependence on how `validate_annotation_names` is imported.

T100. `test_provider_handle_row_annotation_schema_delegates_to_module`: handle method returns the stub row schema exactly.

T101. `test_provider_handle_series_annotation_schema_delegates_to_module`: handle method returns the stub series schema exactly.

T102. `test_stub_provider_module_satisfies_expanded_provider_module_protocol`: `isinstance(stub_provider, ProviderModule)` still passes after the seven-member expansion; this retains the existing T11 conformance intent at the full surface.

T103. `test_stub_catalogue_functions_remain_explicitly_unimplemented`: preserve T25's invariant for `products`, `stations`, and `station_products`.

T104. `test_registry_register_with_module_round_trips_handle_dispatch`: registering artifact plus module returns a handle whose `_module` enables schema delegation and observations.

T105. `test_registry_register_artifact_only_remains_back_compatible`: existing two-argument registration still returns a handle and catalogue/info methods continue to work.

T106. `test_registered_stub_fixture_registers_artifact_and_module_in_fresh_registry_only`: fixture has dispatchable observations while module-level `_registry` remains empty.

T107. `test_stub_provider_does_not_register_at_import_time`: existing import-time isolation still passes after adding observation functions.

T108. `test_import_rivretrieve_does_not_import_test_stubs`: offline import subprocess still leaves `tests._stubs` absent.

T109. `test_init_public_surface_still_excludes_observation_dispatch_names`: public surface remains unchanged; `ObservationsUnavailableError`, `ProviderModule`, and `_ProviderHandle` remain absent.

If test count pressure is high, combine T89-T93 and T97-T98 with parametrization while keeping the behavior intent visible in test names or comments.

## 6. Files (new + modified, in implementation order keeping pytest green at each)

1. Modify `src/rivretrieve/_internal/issues.py` to add `ObservationsUnavailableError(FatalContractError)` with no call sites. Run `uv run pytest`.
2. Modify `tests/_stubs/stub_provider.py` to add real `row_annotation_schema`, `series_annotation_schema`, and `observations(request, *, on_issue=...)`, while preserving `products`, `stations`, and `station_products` as `NotImplementedError`. These functions are not yet required by the four-member `ProviderModule`, so the existing conformance test remains green. Run `uv run pytest`.
3. Modify `src/rivretrieve/_internal/provider_module.py` to import step-04 observation/annotation types and add the three new `@staticmethod` Protocol members. The stub already has those members from step 2, so `test_stub_provider_module_has_provider_module_attributes` remains green. Run `uv run pytest`.
4. Extend `tests/test_internal_provider_module.py`: add or rename T102 for the seven-member Protocol and keep T103 for catalogue `NotImplementedError`. T11 (`test_stub_provider_module_has_provider_module_attributes`) is unchanged in intent; T102 is its expanded seven-member sibling. Run `uv run pytest`.
5. Modify `src/rivretrieve/_internal/registry.py` to add `_module: ProviderModule | None = None` to `_ProviderHandle`, extend `ProviderRegistry.register(..., provider_module=None)`, and pass the module to the handle. Because the field has a default, direct `_ProviderHandle(provider_id=..., _artifact=...)` constructions at `tests/test_internal_registry.py:103` and `tests/test_internal_registry.py:132` remain green. Run `uv run pytest`.
6. Extend `tests/test_internal_registry.py` for T104-T105. Existing tests at lines 26-36 and 111-119 continue using two-argument registration; add one module-registration round-trip without moving catalogue tests. Run `uv run pytest`.
7. Modify `tests/conftest.py::registered_stub` to call `fresh_registry.register("stub_provider", artifact, provider_module=stub_provider)` at `tests/conftest.py:340`. `RegisteredStub` itself does not need a `module` field because the module reference lives inside the handle. Fresh registry isolation remains unchanged. Run `uv run pytest`.
8. Modify `src/rivretrieve/_internal/registry.py` again to add `_ProviderHandle.row_annotation_schema()`, `.series_annotation_schema()`, and `.observations(...)` with module-presence checks, request construction, module dispatch, and annotation-name validation. Run `uv run pytest`.
9. Add `tests/test_internal_handle_observations.py` covering T84-T101 and T106. Use `polars.testing.assert_frame_equal` for result data and annotation tables. Use the existing `_has_issue_policy_error` / `_issue_policy_error_chain` pattern from registry/catalogue/observation tests for direct-fatal assertions. Run `uv run pytest`.
10. Extend `tests/test_offline_import.py` only if sentinel imports change; otherwise keep T108 unchanged and run `uv run pytest`.
11. Modify `tests/test_package.py` deferred absence list to include `ObservationsUnavailableError` for T109. Do not change the public present set. Run `uv run pytest`.
12. Run `uv run ruff format`, `uv run ruff check --fix`, `uv run ty check`, and `uv run pytest`.
13. Run `uv run bump-my-version bump patch`, stage the plan plus code/test/version changes, commit, and tag `v$(uv run bump-my-version show current_version)` per project instructions.

Important ordering note: the stub-first order in steps 2-3 is required. Do not expand the Protocol before adding the stub functions, because that would make the existing runtime-checkable conformance test fail at a file-sized checkpoint.

## 7. Open questions (with recommendation per question)

Q1. Provider module registration path.

Recommendation: option (a), extend `ProviderRegistry.register(provider_id, packaged_artifact, provider_module: ProviderModule | None = None)`. It is atomic, preserves existing two-argument calls, keeps the tests-only stub outside `src/rivretrieve/providers/`, and avoids lazy import behavior that M2 cannot exercise. Option (b) creates a two-phase registration state with more invariants and no current benefit. Option (c) is forbidden for M2 because the only executable provider module is `tests/_stubs/stub_provider.py`.

Q2. `_ProviderHandle` field for the module.

Recommendation: `_module: ProviderModule | None = None`. The leading underscore matches `_artifact`; `None` preserves artifact-only providers and back-compat tests. The default is required because step 02/04 tests directly construct `_ProviderHandle` at `tests/test_internal_registry.py:103` and `tests/test_internal_registry.py:132`. With a default, those tests do not need immediate edits and remain focused on malformed provider info.

Q3. ProviderModule.observations signature.

Recommendation: option (b), `observations(request: ObservationRequest, *, on_issue: OnIssue = "warn") -> ObservationResult`. This is the exact internal provider-module contract in `architecture.md:425` and keeps validation ownership in the handle. Option (a) would force every provider to duplicate loose public input validation and would contradict `architecture.md:428`.

Q4. Annotation-name validation timing.

Recommendation: always validate in `_ProviderHandle.observations()` after the module returns a result and before returning to the caller. Although `architecture.md:556` says tests/debug validation, undeclared names are provider implementation schema violations under `architecture.md:607`; the check is cheap and deterministic. This is a deliberate stricter-than-debug interpretation, not an accidental read of §13. Always validating makes the M2 contract stronger without adding recoverable issue behavior.

Q5. Handle observations when module is unregistered.

Recommendation: option (a), fatal direct raise. Artifact-only registration is valid for catalogue/info methods, but observation dispatch cannot proceed without a module. Check module presence before request construction so the stable registry wiring problem is reported even when the call also contains malformed inputs. Returning an `Issue` would introduce a new recoverable observation path that step 05 explicitly avoids, and capability flags describe provider capability rather than registry wiring.

Q6. Stub provider observation behavior.

Recommendation: emit deterministic long-form rows for known station/product pairs and empty results for unknown combinations. Known IDs should align with the existing stub fixtures: default `"station-1"` / `"level"` and rich-fixture IDs `"station-2"`, `"flow"`, `"level_hourly"`, `"level_max"` from `tests/conftest.py:44-245`, but they are hardcoded in the stub observation function rather than read from the registered artifact. Use two timestamps per known pair (`request.start`, `request.end`) and stable float values. Unknown combinations are empty, not fatal, matching the catalogue no-match pattern, and still return typed zero-row data and annotation frames.

Q7. Stub provider annotation schemas.

Recommendation: one row schema declaration and one series schema declaration:

- Row: `AnnotationSchema("stub.quality", "Stub row quality flag.", "string", ("good", "suspect"), "quality")`.
- Series: `AnnotationSchema("stub.native_unit", "Stub native unit returned for the series.", "string", ("m", "m3/s"), "unit")`.

The stub result should actually emit both names so tests cover the declared-pass path. Undeclared-fail tests should monkeypatch a bad module/result rather than changing the canonical stub.

Q8. Fatal exception name.

Recommendation: `ObservationsUnavailableError(FatalContractError)` in `src/rivretrieve/_internal/issues.py`. It is concise and user-actionable: this handle cannot provide observations because no provider module was registered. `ProviderModuleNotRegisteredError` is accurate but leaks registry wiring more than the method-level failure needs. `ObservationDispatchNotAvailableError` is longer without adding clarity.

Q9. Test file placement.

Recommendation: new file `tests/test_internal_handle_observations.py`. `tests/test_internal_registry.py` already covers registration, provider lookup, info, and catalogue handle methods; adding 15+ observation-dispatch tests there would blur registry mechanics with observation behavior. `tests/test_internal_provider_module.py` should stay focused on Protocol conformance and stub invariants. The new file owns handle observation dispatch and annotation validation.

Q10. Test inventory.

Recommendation: T84-T109 as listed in §5, about 22-28 test functions after parametrization. This covers single/bulk normalization, module dispatch, request fatals before provider execution, missing-module fatals, row/series undeclared annotations, schema delegation, ProviderModule seven-member conformance, register with and without a module, fixture isolation, offline import, public-surface absence, and T25 preservation.

Q11. Step 02 `_ProviderHandle` direct-construction tests.

Current direct constructions are:

- `tests/test_internal_registry.py:103`: `test_provider_handle_info_fatal_failures_are_direct`.
- `tests/test_internal_registry.py:132`: `test_provider_handle_info_malformed_artifact_row_raises_provider_info_validation_error`.

Both construct `_ProviderHandle(provider_id=..., _artifact=...)`. Adding `_module` with a default keeps them green unchanged. If an executor chooses a non-default field, these tests must be updated in the same edit as the dataclass shape change to pass `_module=None`, but that is not recommended because it creates needless churn and a brittle intermediate state.

Q12. Stub provider module loading.

Recommendation: the `registered_stub` fixture imports `tests._stubs.stub_provider` and passes the module object to `register(...)`. The offline-import invariant remains unchanged because normal `import rivretrieve` does not import tests, provider modules, or generators; `tests/test_offline_import.py:15-20` should keep asserting that. The stub module itself must not register at import time; `tests/test_internal_provider_module.py:29-33` should still pass after adding observation functions.

## 8. Deferrals (with hard rationale: which later step or milestone handles each)

- Public `ProviderHandle` Protocol promotion and `_ProviderHandle` rename/export: M2 step 06. Hard rationale: step 05 completes private runtime behavior but does not alter public typing or exports.
- `rr.provider()` return-type narrowing: M2 step 06. Hard rationale: public type narrowing belongs with the public Protocol promotion.
- Public exports for `ObservationResult`, `ObservationRequest`, `AnnotationSchema`, `AnnotationTable`, `RawPayload`, or observation fatal exceptions: M2 step 06 or later public-surface decision. Hard rationale: step 05 is internal wiring only.
- Top-level `rr.observations(...)`: M4. Hard rationale: architecture requires it to be only a wrapper around provider-handle observations, and the tracker assigns it to M4.
- Real `ch_foen` observations: M4. Hard rationale: M2 is stub-only and offline.
- Real provider modules under `src/rivretrieve/providers/`: M3+. Hard rationale: step 05 uses tests-only stubs.
- Recoverable observation issues for gaps, conflicts, missing data, partial responses, fallback sources, or timezone ambiguity: M4. Hard rationale: step 05 introduces no new `Issue`-routed observation behavior.
- Provider-specific annotation namespaces and complete annotation value validation against `value_type` / `allowed_values`: M3+ / later debug validation. Hard rationale: step 05 only enforces declared-name membership.
- ProviderModule `register()` or plugin entry points: out of scope. Hard rationale: `architecture.md:398-425` names seven provider module functions and no registration member.
- Artifact-shape changes to carry modules or artifact identity fields: deferred to artifact/provider packaging work if needed. Hard rationale: module references are registry state, not packaged catalogue data.
- Wide-form pandas helpers: permanently deferred by architecture/tracker. Hard rationale: `ObservationResult.to_pandas()` already exists as long-form conversion from step 04.
- D2 queued architecture §7/§9 addenda: coordinator work before M3 unless a contradiction appears. Hard rationale: step 05 can execute within current architecture by following `architecture.md:423-428`.

## 9. Stopping conditions for the executor

Stop and surface if any of these happen:

- Implementing this step requires public `ProviderHandle` Protocol promotion, public exports, or `rr.provider()` return-type narrowing.
- Implementing this step reaches for top-level `rr.observations(...)`.
- Implementing this step requires a real provider package under `src/rivretrieve/providers/` or real `ch_foen` behavior.
- Observation dispatch requires network I/O, live API calls, or legacy `_download_data` / `_parse_data` behavior.
- ProviderModule expansion requires adding a `register()` member or any eighth provider-module function.
- The chosen registration path requires changing `PackagedCatalogArtifact`.
- `_ProviderHandle.observations()` passes loose public kwargs to the module instead of constructing `ObservationRequest`.
- Missing `start` / `end`, empty station/product inputs, unregistered modules, malformed result data, or undeclared annotation names are routed through `apply_on_issue` or encoded as recoverable `Issue` objects.
- Annotation-name validation is omitted from the handle call site or only validates row annotations but not series annotations.
- The stub provider catalogue functions stop raising `NotImplementedError`.
- The stub provider imports or mutates the global registry at import time.
- `import rivretrieve` imports `tests._stubs`, `rivretrieve.providers`, or any `generate_catalogue.py`.
- Observation data gains `provider_id` in provider-scoped rows, uses wide-form data, or changes the step-04 six-field `ObservationResult` shape.
- The implementation requires provider-specific annotation IDs beyond stub test scaffolding.
- The §6 file order would leave `uv run pytest` failing at a file-sized checkpoint, especially around the `ProviderModule` Protocol expansion and `_ProviderHandle` dataclass shape change.
- D2's queued architecture addenda become necessary for correctness rather than documentation cleanup.

# 06-providerhandle-protocol-promotion Plan

## 1. Step scope summary

Close M2 by promoting the already-implemented provider handle behavior to the public typing surface in one shippable commit:

- Introduce a public `ProviderHandle` Protocol exposing the full seven-method catalogue and observation surface.
- Narrow `rr.provider(provider_id)` from `object` to `ProviderHandle` on the success branch.
- Keep `_ProviderHandle` as the private frozen dataclass returned by the registry.
- Rebound the package surface tests so `ProviderHandle` is public while private/runtime-only observation and catalogue support types remain absent.
- Add one `tests/test_m2_exit_criteria.py` integration sweep that proves the M2 exit criteria in `docs/milestone-tracker.md` lines 149-158 are met through public `rivretrieve as rr` calls and the registered stub provider.

This step is surface promotion and closeout verification only. Step 05 already shipped the behavior: catalogue methods, observation dispatch, required request validation, annotation schema delegation, always-on annotation-name validation, and canonical long-form exports.

## 2. Tracker exit-criterion bullets covered

- T118: Public `ProviderHandle` Protocol exposes the full catalogue and observation method set; there is no empty public Protocol phase.
- T118: Provider and global catalogue methods return `CatalogResult` with Polars data and do not call provider APIs for packaged source.
- T118: Invalid `source` raises as a fatal contract error.
- T118: Unsupported `source="live"` produces a warning issue under `on_issue="warn"`, raises under `"raise"`, and remains in `issues` under `"ignore"`.
- T118: A fake provider returns valid `ObservationResult` for one station/product and multiple stations/products through the same public method.
- T118: Missing `start` or `end` raises before provider execution.
- T118: Annotation names not declared by provider schemas fail validation.
- T118: `result.data`, `result.to_polars()`, and `result.to_pandas()` expose the same canonical long table.
- Verification gate: `uv run pytest` passes.

## 3. Detailed contract decisions

### Q1. Protocol-or-rename

Introduce `ProviderHandle` as a new public Protocol class. Keep `_ProviderHandle` as the private concrete frozen dataclass constructed by `ProviderRegistry.register(...)` and returned by `ProviderRegistry.get(...)` / `rr.provider(...)`.

Rationale: the architecture calls for a public handle contract, not a public concrete registry implementation. Structural conformance lets the runtime object remain private and stable while the public API advertises the behavioral surface users can rely on.

### Q2. runtime_checkable

Decorate `ProviderHandle` with `@runtime_checkable`.

Rationale: this mirrors the internal `ProviderModule` pattern and gives tests a cheap runtime structural assertion (`isinstance(handle, ProviderHandle)`) without making users depend on `_ProviderHandle` or its `_module` wiring slot.

### Q3. Protocol method shapes

Declare the seven Protocol methods with the exact signatures from `docs/milestone-tracker.md` lines 120-126, including keyword-only markers and default values:

- `info() -> ProviderInfo`
- `products(*, source: CatalogSource = "packaged", observed_property: str | None = None, frequency: str | None = None, statistic: str | None = None, on_issue: OnIssue = "warn") -> CatalogResult[pl.DataFrame]`
- `stations(*, source: CatalogSource = "packaged", on_issue: OnIssue = "warn") -> CatalogResult[pl.DataFrame]`
- `station_products(stations: Sequence[str] | None = None, *, source: CatalogSource = "packaged", on_issue: OnIssue = "warn") -> CatalogResult[pl.DataFrame]`
- `row_annotation_schema() -> list[AnnotationSchema]`
- `series_annotation_schema() -> list[AnnotationSchema]`
- `observations(*, stations: str | Sequence[str], products: str | Sequence[str], start: object, end: object, on_issue: OnIssue = "warn") -> ObservationResult`

The tracker names catalogue aliases (`ProductCatalog`, `StationCatalog`, `StationProductCatalog`) as return payload concepts; the current implementation surface is `CatalogResult[pl.DataFrame]` across discovery and handle methods. The Protocol should match the implementation's existing generic shape unless type aliases are introduced elsewhere before this step.

### Q4. _ProviderHandle inheritance

Do not make `_ProviderHandle` inherit from `ProviderHandle`.

Protocol conformance is structural. Explicit inheritance would couple the private registry object to the public type and may create Protocol/dataclass MRO friction for no runtime benefit. T112 verifies conformance with `isinstance(_ProviderHandle_instance, ProviderHandle)`.

### Q5. _module field

Do not declare `_module` on the public Protocol.

The module slot is registry wiring, not user behavior. The public Protocol declares only the seven public methods.

### Q6. Unknown provider behavior

Do not change unknown-provider behavior. `rr.provider("missing")` still raises `UnknownProviderError`, a fatal contract error introduced in M1 step 03.

The return-type narrowing applies only to successful lookup. It does not imply a nullable return and does not alter fatal lookup behavior.

### Q7. Import ordering and circular imports

Current read:

- `src/rivretrieve/__init__.py` imports public functions only from `_internal.discovery`.
- `_internal.discovery` imports `_registry` from `_internal.registry` and exposes `provider(provider_id) -> object`.
- `_internal.registry` currently imports observation/catalogue primitives and defines `_ProviderHandle`.
- `_internal.observations` does not import `registry` or `discovery`.

Recommended shape:

- Add `src/rivretrieve/_internal/handle.py` defining only `ProviderHandle`.
- `handle.py` imports `Sequence`, `Protocol`, `runtime_checkable`, `polars as pl`, `AnnotationSchema`, `ObservationResult`, `CatalogSource`, `OnIssue`, `ProviderInfo`, and `CatalogResult`.
- `_internal.discovery` imports `ProviderHandle` for the `provider(...) -> ProviderHandle` annotation.
- `src/rivretrieve/__init__.py` imports and re-exports `ProviderHandle`.
- `_internal.registry` does not need to import `ProviderHandle`; conformance stays structural.

This avoids a cycle: `handle.py` depends on leaf type modules, while `registry.py` and `discovery.py` may depend on `handle.py`, not the inverse. If implementation discovers a cycle, stop and revise this module layout rather than papering over it with broad local imports.

### Q8. ProviderHandle module location

Place `ProviderHandle` in `src/rivretrieve/_internal/handle.py`.

Rationale: it is the public-facing sibling of `_internal/provider_module.py`, which defines the inverse provider-module Protocol. Keeping both Protocols in `_internal` preserves the package policy that public names are re-exported through `rivretrieve.__init__` rather than implemented at package root.

### Q9. ObservationResult export

Do not export `ObservationResult`, `CatalogResult`, `AnnotationSchema`, `CatalogSource`, `OnIssue`, or catalogue schema names through `rr.__all__` / the package surface.

They can be imported inside `handle.py` and used in annotations without being public top-level names. The package-level `ProviderHandle` symbol is public; the referenced implementation/support types remain internal for M2.

### Q10. M2 exit-criteria sweep design

Add one integration file, `tests/test_m2_exit_criteria.py`, modeled after `tests/test_m1_exit_criteria.py`. It should use public `import rivretrieve as rr` calls and the existing `registered_stub` fixture, while importing internal exception/result classes only where required to assert class identity or fatal type.

The sweep should walk the tracker bullets once each rather than duplicating every focused unit test from earlier steps. It should cover packaged catalogue calls, live-source issue policy behavior, observation single/bulk calls, pre-dispatch missing-date fatals, undeclared annotation validation, and long-table export equivalence.

### Q11. Public-surface contract pinning

Add a dedicated Protocol-shape test instead of relying only on the integration sweep.

T116 inventories the seven public method names. T117 introspects each signature for parameter names, keyword-only markers, defaults, and return annotations. The integration sweep then proves behavior through the public handle.

For method inventory, prefer `ProviderHandle.__protocol_attrs__` if present in this Python/runtime combination. If it is unavailable or unstable, use a small introspection helper over `ProviderHandle.__dict__` filtered to public callable Protocol declarations. The test must pin the seven names exactly.

### Q12. T22 ordering

Update the T22 present-set in `tests/test_package.py` to include `ProviderHandle` in alphabetical position among the function names:

```python
{
    "ProviderHandle",
    "product_info",
    "products",
    "provider",
    "provider_info",
    "providers",
    "stations",
}
```

`__version__` remains asserted separately via `vars(rivretrieve)`.

## 4. Fatal/Issue routing summary

No new fatal paths are expected. No new Issue-routed paths are expected.

The promotion must preserve existing behavior:

- Unknown `rr.provider(provider_id)` raises `UnknownProviderError`.
- Invalid catalogue `source` remains a direct fatal contract error.
- Unsupported `source="live"` still follows the existing catalogue issue policy.
- Observation request validation and annotation-name validation remain direct fatal paths from step 05.
- The public Protocol must not introduce wrappers that catch, translate, silence, or route existing exceptions differently.

## 5. Test inventory

T110. `tests/test_provider_handle.py::test_provider_handle_imported_from_package_root`: `from rivretrieve import ProviderHandle` succeeds and `rr.ProviderHandle is ProviderHandle`.

T111. `tests/test_provider_handle.py::test_provider_handle_is_runtime_checkable_protocol`: `ProviderHandle` is a Protocol class and supports runtime structural checks, e.g. via `_is_protocol` / `_is_runtime_protocol` or an equivalent stable runtime hook.

T112. `tests/test_provider_handle.py::test_private_provider_handle_structurally_conforms_to_public_protocol`: an artifact-only `_ProviderHandle` instance is `isinstance(handle, ProviderHandle)`.

T113. `tests/test_provider_handle.py::test_public_provider_returns_provider_handle_protocol_instance`: a stub handle returned by `rr.provider("stub_provider")` is `isinstance(..., ProviderHandle)`.

T114. `tests/test_provider_handle.py::test_public_provider_return_annotation_is_provider_handle`: `typing.get_type_hints(rr.provider)["return"] is ProviderHandle`, and `uv run ty check` validates a typed reference pattern such as `handle: rr.ProviderHandle = rr.provider("stub_provider")`.

T115. `tests/test_provider_handle.py::test_public_provider_unknown_still_raises_unknown_provider_error`: unknown lookup still raises `UnknownProviderError` directly.

T116. `tests/test_provider_handle.py::test_provider_handle_protocol_declares_exactly_seven_public_methods`: method inventory is exactly `{"info", "products", "stations", "station_products", "row_annotation_schema", "series_annotation_schema", "observations"}`.

T117. `tests/test_provider_handle.py::test_provider_handle_protocol_method_signatures_match_tracker`: each Protocol method signature matches tracker lines 120-126 for names, keyword-only markers, default values, and return annotations.

T118. `tests/test_m2_exit_criteria.py::test_m2_exit_criteria_public_surface_sweep`: one integration test walks every M2 exit criterion through public `rr.*` calls and the registered stub provider.

T119. `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface`: T22 present-set expands to `ProviderHandle`, `product_info`, `products`, `provider`, `provider_info`, `providers`, and `stations`; `__version__` remains present.

T120. `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion`: T23 must preserve the existing `tests/test_package.py::deferred_names` list verbatim minus the single entry `ProviderHandle`. Concretely, after this step the absence-set is `{"ProviderInfo", "ProviderModule", "_ProviderHandle", "observations", "map_stations", "ObservationResult", "ObservationRequest", "ObservationProvenance", "AnnotationSchema", "AnnotationTable", "RawPayload", "Issue", "CatalogResult", "StationCatalog", "ProductCatalog", "StationProductCatalog", "ProviderInfoCatalog", "PackagedCatalogArtifact", "CorruptCatalogArtifactError", "LiveCatalogueUnsupportedIssue", "LiveCatalogueRoutingNotImplementedError", "ObservationDataSchema", "RowAnnotationTableSchema", "SeriesAnnotationTableSchema", "AnnotationSchemaDeclaration", "InvalidObservationRequestError", "ObservationsUnavailableError", "ObservationDataSchemaError", "AnnotationSchemaViolationError"}`. Only `ProviderHandle` moves from absence to presence; no other name is added or removed in this step.

## 6. Implementation order

1. Add `src/rivretrieve/_internal/handle.py`.
   - Define `@runtime_checkable class ProviderHandle(Protocol)` with the exact seven-method surface.
   - Run `uv run pytest tests/test_package.py` as a no-op checkpoint if no public import has been added yet.

2. Modify `src/rivretrieve/_internal/discovery.py`.
   - Import `ProviderHandle`.
   - Change `provider(provider_id: str) -> object` to `provider(provider_id: str) -> ProviderHandle`.
   - Keep the body as `_registry.get(provider_id)`.
   - Run `uv run pytest tests/test_internal_registry.py tests/test_discovery.py`.

3. Modify `src/rivretrieve/__init__.py`.
   - Import `ProviderHandle` from `_internal.handle`.
   - Do not import or expose observation/result/support types.
   - Run `uv run pytest tests/test_package.py`.

4. Add `tests/test_provider_handle.py`.
   - Cover T110-T117.
   - Use existing stub artifact fixtures and `registered_stub`; do not touch `tests/_stubs/stub_provider.py`.
   - Run `uv run pytest tests/test_provider_handle.py`.

5. Modify `tests/test_package.py`.
   - Expand T22 to include `ProviderHandle`.
   - Remove `ProviderHandle` from the T23 absence set while keeping private/internal support types absent.
   - Run `uv run pytest tests/test_package.py`.

6. Add `tests/test_m2_exit_criteria.py`.
   - Cover T118 as one public integration sweep.
   - Reuse earlier focused tests for detailed unit coverage; this test should prove the milestone boundary, not re-spec every helper.
   - Run `uv run pytest tests/test_m2_exit_criteria.py`.

7. Run full verification.
   - `uv run ruff format`
   - `uv run ruff check --fix`
   - `uv run ty check`
   - `uv run pytest`

8. Versioning step for executor only.
   - Because project policy says every commit bumps patch, the executor should run `uv run bump-my-version bump patch` before committing. This planning commit does not perform that bump unless the reviewer dispatches implementation.

## 7. Out-of-scope guards

- No new methods on `_ProviderHandle` or `ProviderHandle`.
- No behavior changes to existing `_ProviderHandle` methods.
- No new fatal exception classes.
- No new Issue-routed paths.
- No changes to `ProviderModule`.
- No new provider modules and no `src/rivretrieve/providers/` registration work.
- No promotion of `ObservationResult`, `ObservationRequest`, `AnnotationSchema`, `CatalogResult`, `CatalogProvenance`, `PackagedCatalogArtifact`, or observation exception classes to the package root.
- No changes to `tests/_stubs/stub_provider.py`.
- No changes to existing T01-T109 tests except the public-surface rebound in `tests/test_package.py`.
- No top-level `rr.observations(...)` and no `rr.map_stations()`.

## 8. D3 candidates surfaced during planning

- Public annotation dependencies remain internal even though they appear in `ProviderHandle` annotations. This is intentional for M2, but D3 should decide whether later documentation or `.pyi` support needs a clearer public typing story for users who want to name `ObservationResult` directly.
- The tracker writes catalogue return types as `CatalogResult[ProductCatalog]`, `CatalogResult[StationCatalog]`, and `CatalogResult[StationProductCatalog]`; implementation currently uses `CatalogResult[pl.DataFrame]`. D3 can decide whether to add public/internal type aliases for catalogue-shaped frames or keep the runtime `pl.DataFrame` annotation.
- `ProviderHandle.__protocol_attrs__` may vary across Python versions. If T116 needs a fallback introspection helper, D3 can record the chosen stable Protocol-introspection pattern for later public Protocols.
- The public package has no explicit `__all__`; T22 uses `vars(rivretrieve)` as the surface contract. D3 can decide whether the package should add `__all__` before broader public API growth.

## 9. Stopping conditions

- If the M2 exit-criteria integration sweep cannot be written without changing existing behavior, stop. That means step 05 or earlier shipped an incomplete behavior, not that step 06 should silently fix it.
- If introducing `ProviderHandle` creates a circular import, stop and revise the module proposal. `handle.py` must depend only on leaf type modules; registry/discovery may import it, not the inverse.
- If `uv run ty check` rejects the Protocol declaration or the `rr.provider(...)` narrowing, stop and surface the typing conflict in this plan's D3 section before implementation proceeds.
- If `_ProviderHandle` does not structurally conform to the Protocol because method signatures differ from tracker lines 120-126, stop. That is a step 05 signature defect, not a step 06 promotion task.
- If runtime-checkable `isinstance(handle, ProviderHandle)` cannot be made meaningful without nominal inheritance or exporting `_ProviderHandle`, stop and revisit Q2/Q4 rather than weakening encapsulation.

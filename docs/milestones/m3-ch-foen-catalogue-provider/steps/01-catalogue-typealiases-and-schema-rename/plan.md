# 01-catalogue-typealiases-and-schema-rename Plan

## 1. Goal and scope

This step resolves D3 path (b): make the catalogue table names usable as static element aliases while preserving the existing runtime schema objects under explicit `*_SCHEMA` names.

Ships in this single step:

- Define four catalogue element aliases, all equal to `pl.DataFrame`: `StationCatalog`, `ProductCatalog`, `StationProductCatalog`, and `ProviderInfoCatalog`.
- Rename the four runtime `CatalogueSchema` bindings that currently occupy those names to `STATION_CATALOG_SCHEMA`, `PRODUCT_CATALOG_SCHEMA`, `STATION_PRODUCT_CATALOG_SCHEMA`, and `PROVIDER_INFO_CATALOG_SCHEMA`.
- Update internal schema call sites to use `*_SCHEMA`.
- Re-annotate public catalogue result surfaces from `CatalogResult[pl.DataFrame]` to the new aliases where the return semantics are unambiguous.
- Update `docs/discoveries.md` D3 in place to record the resolution.

No `ch_foen` provider code, no catalogue artifact changes, no runtime behavior change, no architecture.md edit, and no public re-export of the aliases are in scope.

The D2 gate is satisfied at HEAD: `architecture.md` §7 contains the packaged Parquet `metadata` JSON-string wire encoding, and §9 contains the `ProviderInfo` identifying fields (`provider_id`, `name`, `catalogue_version`) plus capability fields.

## 2. API surface touched

Public Protocol method annotations change form, not runtime behavior:

- `ProviderHandle.products(...) -> CatalogResult[ProductCatalog]`
- `ProviderHandle.stations(...) -> CatalogResult[StationCatalog]`
- `ProviderHandle.station_products(...) -> CatalogResult[StationProductCatalog]`

Global discovery function annotations change form, not runtime behavior:

- `provider_info() -> CatalogResult[ProviderInfoCatalog]`
- `stations() -> CatalogResult[StationCatalog]`
- `products() -> CatalogResult[ProductCatalog]`
- `product_info() -> CatalogResult[ProductCatalog]`
- `_global_products() -> CatalogResult[ProductCatalog]` may be narrowed as the private helper behind `products()` and `product_info()`.

No new public symbols are exported. `src/rivretrieve/__init__.py` currently exports only `ProviderHandle`, `product_info`, `products`, `provider`, `provider_info`, `providers`, `stations`, and `__version__`; the four alias names remain absent from the package root. T119 and T120 public-surface expectations are unchanged.

Do not change observation annotations. Do not change `CatalogResult`, `ProviderHandle` method bodies, `CatalogueReader` behavior, registry behavior, provider registration, or artifact format.

## 3. Data structures and types

Source of truth: the four current schema instances live in `src/rivretrieve/_internal/catalogues/schemas.py`, not a separate `types.py` module. Import path today and after this step remains `rivretrieve._internal.catalogues.schemas`.

Add these aliases in `src/rivretrieve/_internal/catalogues/schemas.py`, colocated with the runtime schema specs and using the module's existing PEP 695 alias convention:

```python
type StationCatalog = pl.DataFrame
type ProductCatalog = pl.DataFrame
type StationProductCatalog = pl.DataFrame
type ProviderInfoCatalog = pl.DataFrame
```

Recommendation: colocate the aliases with the renamed `CatalogueSchema` bindings. This keeps the conceptual table contract and runtime schema contract discoverable in one module and avoids introducing a sibling types module for four aliases.

Rename the runtime schema bindings in the same file:

| Old runtime binding | New runtime binding |
| --- | --- |
| `StationCatalog` | `STATION_CATALOG_SCHEMA` |
| `ProductCatalog` | `PRODUCT_CATALOG_SCHEMA` |
| `StationProductCatalog` | `STATION_PRODUCT_CATALOG_SCHEMA` |
| `ProviderInfoCatalog` | `PROVIDER_INFO_CATALOG_SCHEMA` |

Keep each `CatalogueSchema.name` string unchanged (`"StationCatalog"`, `"ProductCatalog"`, `"StationProductCatalog"`, `"ProviderInfoCatalog"`). Those strings appear in validation messages and issue details; this step is a binding rename, not a schema identity rename.

Use PEP 695 `type X = ...` by default because this same file already declares `type CatalogueDtype = pl.DataType | type[pl.DataType]`. Fall back to `typing.TypeAlias` only if `ty` rejects a runtime `pl.DataFrame` RHS in a PEP 695 alias. `pl.DataFrame` is a normal class object, so it is valid as a type-alias target and has no runtime instantiation side effect.

## 4. Errors and failure modes

None new.

The rename touches no fatal-raise paths and no Issue-routed paths. `validate_catalogue`, `CatalogueReader`, artifact loading, provider-info row validation, and discovery aggregation continue to call the same validators with the same `CatalogueSchema` object values under new binding names. The two-channel pattern is unaffected: direct contract failures still raise fatal exceptions, and recoverable catalogue issues still flow through `on_issue`.

## 5. Tests

Tests that import or reference renamed runtime schema symbols and must migrate to `*_SCHEMA`:

- `tests/test_internal_catalogue_schemas.py`: imports all four runtime schema objects and asserts columns, dtypes, nullable behavior, enum behavior, metadata JSON validation, and provider-info row shape. Rename all schema-object references to `*_SCHEMA`; no assertion should target alias identity unless a new test is deliberately added.
- `tests/test_internal_catalogue_reader.py`: imports `ProductCatalog`, `StationCatalog`, and `StationProductCatalog` for `.polars_schema` assertions around packaged, filtered, empty, and live-unsupported catalogue paths. Rename to `*_SCHEMA`.
- `tests/test_discovery.py`: imports `ProductCatalog`, `ProviderInfoCatalog`, and `StationCatalog` for aggregate discovery schema assertions and fixture DataFrame construction. Rename to `*_SCHEMA`.
- `tests/test_provider_handle.py::test_provider_handle_protocol_method_signatures_match_tracker`: update expected return strings from `CatalogResult[pl.DataFrame]` to `CatalogResult[ProductCatalog]`, `CatalogResult[StationCatalog]`, and `CatalogResult[StationProductCatalog]`.

Negative controls this step owns:

- T119 `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface`: unchanged present set; the four alias names must not appear in the package-root surface.
- T120 `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion`: keep `StationCatalog`, `ProductCatalog`, `StationProductCatalog`, and `ProviderInfoCatalog` in the deferred absence list.
- `uv run ty check` passes after alias definitions and annotation narrowing.
- All 335 M2-close tests still pass with no new tests added.

Default test position: no new tests. A runtime alias-identity test is not warranted because these aliases are static annotation affordances, not public runtime API; with PEP 695 syntax the runtime object is a type-alias object, so `StationCatalog is pl.DataFrame` is not the right assertion unless the executor had to fall back to `typing.TypeAlias` assignment syntax.

Verified by grep: no current test asserts `schema.__name__` or the string name of a `CatalogueSchema` instance directly. Existing validator-message tests may still observe `schema.name` in exception text; keeping the `CatalogueSchema.name` strings unchanged preserves them.

## 6. Files

Implementation order below keeps `uv run pytest` green at every intermediate state by first adding `*_SCHEMA` compatibility bindings, then migrating runtime users, then converting the old names into type aliases. This intentionally differs from the tempting "define aliases first" order: the old names cannot simultaneously be `pl.DataFrame` aliases and runtime objects with `.polars_schema`.

1. Modify `src/rivretrieve/_internal/catalogues/schemas.py`.
   - Add new runtime schema bindings as the canonical `CatalogueSchema(...)` assignments: `STATION_CATALOG_SCHEMA`, `PRODUCT_CATALOG_SCHEMA`, `STATION_PRODUCT_CATALOG_SCHEMA`, `PROVIDER_INFO_CATALOG_SCHEMA`.
   - Temporarily keep the old runtime names as compatibility aliases to the new schema objects only until call sites are migrated. Because the old names are ordinary object bindings, there is no subclass or `ClassVar` trap.
   - Run `uv run ty check src/rivretrieve/_internal/catalogues/schemas.py` as an early fail-fast probe for the new bindings.
   - Run `uv run pytest`.

2. Modify `src/rivretrieve/_internal/catalogue_reader.py`.
   - Import `PRODUCT_CATALOG_SCHEMA`, `STATION_CATALOG_SCHEMA`, and `STATION_PRODUCT_CATALOG_SCHEMA`.
   - Replace `ProductCatalog.polars_schema` -> `PRODUCT_CATALOG_SCHEMA.polars_schema`.
   - Replace `StationCatalog.polars_schema` -> `STATION_CATALOG_SCHEMA.polars_schema`.
   - Replace `StationProductCatalog.polars_schema` -> `STATION_PRODUCT_CATALOG_SCHEMA.polars_schema`.
   - Replace `validate_catalogue(..., ProductCatalog/StationCatalog/StationProductCatalog, ...)` with the matching `*_SCHEMA`.
   - Run `uv run pytest tests/test_internal_catalogue_reader.py`.

3. Modify `src/rivretrieve/_internal/catalogues/artifact.py`.
   - Import all four `*_SCHEMA` bindings.
   - Replace provider-info conversion and validation with `PROVIDER_INFO_CATALOG_SCHEMA`.
   - Replace product, station, and station-product validation with the matching `*_SCHEMA`.
   - Run `uv run pytest tests/test_internal_packaged_catalogue_artifact.py tests/test_internal_catalogue_schemas.py`.

4. Modify `src/rivretrieve/_internal/provider_info.py`.
   - Import `PROVIDER_INFO_CATALOG_SCHEMA`.
   - Replace column selection, one-row DataFrame construction, validation, and error-message schema access with `PROVIDER_INFO_CATALOG_SCHEMA`.
   - Run `uv run pytest tests/test_internal_provider_info.py`.

5. Modify `src/rivretrieve/_internal/discovery.py`.
   - Import the four `*_SCHEMA` names for runtime validation.
   - Keep annotations as `CatalogResult[pl.DataFrame]` at this checkpoint because the old names are still runtime compatibility bindings.
   - Leave the existing `ProductCatalog`/`ProviderInfoCatalog`/`StationCatalog` imports in place even if temporarily unused; they are reused as alias references at step 8. Do not run `ruff check --fix` before step 8.
   - Replace runtime `.polars_schema` and `validate_catalogue` references with `*_SCHEMA`.
   - Run `uv run pytest tests/test_discovery.py`.

6. Modify tests that import renamed runtime schema objects.
   - `tests/test_internal_catalogue_schemas.py`: old `StationCatalog`/`ProductCatalog`/`StationProductCatalog`/`ProviderInfoCatalog` runtime schema imports -> new `*_SCHEMA` imports.
   - `tests/test_internal_catalogue_reader.py`: old runtime schema imports -> new `*_SCHEMA` imports.
   - `tests/test_discovery.py`: old runtime schema imports -> new `*_SCHEMA` imports.
   - Run `uv run pytest tests/test_internal_catalogue_schemas.py tests/test_internal_catalogue_reader.py tests/test_discovery.py tests/test_package.py`.

7. Modify `src/rivretrieve/_internal/catalogues/schemas.py` again.
   - Replace the temporary old runtime compatibility bindings with the four PEP 695 aliases: `type StationCatalog = pl.DataFrame`, `type ProductCatalog = pl.DataFrame`, `type StationProductCatalog = pl.DataFrame`, `type ProviderInfoCatalog = pl.DataFrame`.
   - Leave the four `*_SCHEMA` runtime schema bindings as the only runtime schema objects.
   - If `ty` rejects the PEP 695 form, fall back locally to `typing.TypeAlias` assignments and document that deviation in the execution record.
   - Run `uv run pytest`.

8. Modify `src/rivretrieve/_internal/discovery.py` again.
   - Import the four type alias names for annotations alongside the `*_SCHEMA` names for runtime validation.
   - Narrow annotations: `provider_info -> CatalogResult[ProviderInfoCatalog]`, `stations -> CatalogResult[StationCatalog]`, `products/product_info/_global_products -> CatalogResult[ProductCatalog]`.
   - Remove the now-unused `polars as pl` import only if it is no longer needed by helper signatures or implementation.
   - Run `uv run pytest tests/test_discovery.py`.

9. Modify `src/rivretrieve/_internal/handle.py`.
   - Import `ProductCatalog`, `StationCatalog`, and `StationProductCatalog`.
   - Remove the now-unused `polars as pl` import if no longer needed.
   - Narrow public Protocol catalogue returns to the three aliases.
   - In the same local slice, modify `tests/test_provider_handle.py` expected return strings to match the new annotations.
   - Run `uv run pytest tests/test_provider_handle.py`.

10. Optional internal annotation cleanup only if `ty check` requires it.
    - Candidate files with `CatalogResult[pl.DataFrame]` that are not public API: `src/rivretrieve/_internal/provider_module.py`, `src/rivretrieve/_internal/registry.py`, `src/rivretrieve/_internal/catalogue_reader.py`, and `tests/_stubs/stub_provider.py`.
    - Recommendation: do not churn these unless needed. If `ty` requires cleanup, narrow only the specific file(s) and method(s) it complains about, not all candidate files. These annotations are internal/runtime-compatible because the aliases equal `pl.DataFrame`; this step is specifically about public Protocol and global discovery signatures.

11. Modify `docs/discoveries.md`.
    - Update D3 in place under its "How to apply going forward" block with a "Resolved at M3 step 01" note: aliases introduced, runtime schemas renamed to `*_SCHEMA`, no public export, and T119/T120 unchanged.
    - Do not remove the entry; D1, D2, D4, and D5 remain a historical decision log pattern.
    - Run `uv run pytest tests/test_package.py` if only docs changed, or the full suite if any code changed since the previous checkpoint.

12. Final verification.
    - `uv run ruff format`
    - `uv run ruff check --fix`
    - `uv run ty check`
    - `uv run pytest`

## 7. Open questions

1. Where do the four current `CatalogueSchema` instances actually live?
   Recommendation: `src/rivretrieve/_internal/catalogues/schemas.py`, import path `rivretrieve._internal.catalogues.schemas`. Verified by grep: lines 35, 53, 72, and 89 hold the four `CatalogueSchema(...)` assignments.

2. Should aliases live with schemas or in a sibling types module?
   Recommendation: colocate in `schemas.py`. There is no existing `src/rivretrieve/_internal/catalogues/types.py`; splitting four aliases would add navigation cost without reducing coupling.

3. Are the four aliases currently imported by a public re-export path?
   Recommendation: no. `src/rivretrieve/__init__.py` exports only the M2 public surface and does not import any catalogue schema names. T119/T120 remain unchanged negative controls.

4. Which public Protocol methods and global discovery functions currently bear `CatalogResult[pl.DataFrame]` annotations?
   Recommendation: narrow the public `ProviderHandle` catalogue methods in `src/rivretrieve/_internal/handle.py`: `products`, `stations`, `station_products`. Narrow global discovery functions in `src/rivretrieve/_internal/discovery.py`: `provider_info`, `stations`, `products`, `product_info`, and private helper `_global_products`. Do not narrow `provider()` because it already returns `ProviderHandle`. Do not narrow observation methods.

5. Does `ty check` accept `pl.DataFrame` as a type-alias target?
   Recommendation: yes. `pl.DataFrame` is the same class currently used directly in annotations, so replacing repeated direct annotations with named aliases should be type-checker-neutral. Use `type X = pl.DataFrame` first to match the local `schemas.py` convention; the final `uv run ty check` is the verifier, with a fallback to `typing.TypeAlias` only if needed.

6. Does adding `*_SCHEMA` aliases alongside old runtime names keep the suite green?
   Recommendation: yes. The current old names are ordinary module-level `CatalogueSchema` objects. The executor can bind `STATION_CATALOG_SCHEMA = CatalogueSchema(...)` and temporarily bind `StationCatalog = STATION_CATALOG_SCHEMA` until migration, then replace `StationCatalog` with `type StationCatalog = pl.DataFrame` only after runtime users are on `*_SCHEMA`. No subclassing, descriptor, or class-variable behavior is involved.

7. How should D3 be handled?
   Recommendation: update in place with a resolved note. Removing it would erase useful historical context about why the alias/schema split exists.

8. Does any test assert the string name of a `CatalogueSchema` instance?
   Recommendation: no direct string-name assertion was found. Keep `CatalogueSchema.name` unchanged anyway to avoid changing validator messages and issue details.

## 8. Deferrals

- No `ch_foen` provider code, provider metadata models, generator, packaged artifacts, registration, or observations placeholder.
- No architecture.md edit.
- No public re-export of `StationCatalog`, `ProductCatalog`, `StationProductCatalog`, or `ProviderInfoCatalog`.
- No public-surface T119/T120 changes.
- No runtime behavior changes to `CatalogResult`, `ProviderHandle`, `CatalogueReader`, registry, provider modules, artifact format, validation, or issue policy.
- Annotation churn outside the fixed catalogue targets is deferred unless `ty check` makes it necessary. In particular, observation result annotations and non-catalogue types are out of scope.
- Product vocabulary and ProviderInfo row contract remain unchanged.

## 9. Stopping conditions for the executor

- Stop if `architecture.md` §7 no longer contains the Parquet `metadata` JSON-string encoding or §9 no longer contains ProviderInfo identifying fields and capabilities.
- Stop if the four current names are not runtime `CatalogueSchema` instances at execution time.
- Stop if any of the four `*_SCHEMA` identifiers collide with a pre-existing binding in `src/rivretrieve/_internal/catalogues/schemas.py` or any file importing it.
- Stop if any of the four names are exported from `rivretrieve/__init__.py` or otherwise require changing T119/T120's expected public surface.
- Stop if a `CatalogResult[pl.DataFrame]` annotation chosen for narrowing cannot be mapped unambiguously to one of the four aliases.
- Stop if an intermediate ordering cannot keep `uv run pytest` green; do not land a half-migrated binding state.
- Stop if the rename would require runtime behavior changes, artifact rewrites, provider registration changes, or Issue/fatal-path changes.
- Stop if `ty check` rejects the alias approach in a way that cannot be fixed by local import ordering or annotation cleanup.

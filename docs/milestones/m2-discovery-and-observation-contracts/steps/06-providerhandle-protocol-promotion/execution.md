# 06-providerhandle-protocol-promotion Execution

## 1. What shipped

- Commit SHA: recorded on the implementation commit for this execution artifact.
- Tag: `v0.1.14`.
- Version: `0.1.13` -> `0.1.14`.
- Test count delta: `326` -> `335` (`+9`: T110-T117 plus T118).
- Final gates:
  - `uv run ruff format` passed.
  - `uv run ruff check --fix` passed.
  - `uv run ty check` passed.
  - `uv run pytest` passed: `335 passed`.

## 2. Files added / modified

Added:

- `src/rivretrieve/_internal/handle.py`
- `tests/test_provider_handle.py`
- `tests/test_m2_exit_criteria.py`
- `docs/milestones/m2-discovery-and-observation-contracts/steps/06-providerhandle-protocol-promotion/execution.md`

Modified:

- `src/rivretrieve/__init__.py`
- `src/rivretrieve/_internal/discovery.py`
- `tests/test_package.py`
- `pyproject.toml`
- `uv.lock`

Step artifacts staged with the implementation:

- `docs/milestones/m2-discovery-and-observation-contracts/steps/06-providerhandle-protocol-promotion/plan.md`
- `docs/milestones/m2-discovery-and-observation-contracts/steps/06-providerhandle-protocol-promotion/critique.md`
- `docs/milestones/m2-discovery-and-observation-contracts/steps/06-providerhandle-protocol-promotion/execution.md`

## 3. Test enumeration

- T110 PASS: `tests/test_provider_handle.py:22`
- T111 PASS: `tests/test_provider_handle.py:29`
- T112 PASS: `tests/test_provider_handle.py:36`
- T113 PASS: `tests/test_provider_handle.py:45`
- T114 PASS: `tests/test_provider_handle.py:18`, `tests/test_provider_handle.py:59`
- T115 PASS: `tests/test_provider_handle.py:68`
- T116 PASS: `tests/test_provider_handle.py:73`
- T117 PASS: `tests/test_provider_handle.py:92`
- T118 PASS: `tests/test_m2_exit_criteria.py:25`
- T119 PASS: `tests/test_package.py:11`
- T120 PASS: `tests/test_package.py:26`

## 4. Negative-control inventory

T22 present-set composition:

- `ProviderHandle`
- `product_info`
- `products`
- `provider`
- `provider_info`
- `providers`
- `stations`
- `__version__` remains asserted separately.

T23 absence-set composition:

- `ProviderInfo`
- `ProviderModule`
- `_ProviderHandle`
- `observations`
- `map_stations`
- `ObservationResult`
- `ObservationRequest`
- `ObservationProvenance`
- `AnnotationSchema`
- `AnnotationTable`
- `RawPayload`
- `Issue`
- `CatalogResult`
- `StationCatalog`
- `ProductCatalog`
- `StationProductCatalog`
- `ProviderInfoCatalog`
- `PackagedCatalogArtifact`
- `CorruptCatalogArtifactError`
- `LiveCatalogueUnsupportedIssue`
- `LiveCatalogueRoutingNotImplementedError`
- `ObservationDataSchema`
- `RowAnnotationTableSchema`
- `SeriesAnnotationTableSchema`
- `AnnotationSchemaDeclaration`
- `InvalidObservationRequestError`
- `ObservationsUnavailableError`
- `ObservationDataSchemaError`
- `AnnotationSchemaViolationError`

T115 UnknownProviderError preserved:

- `tests/test_provider_handle.py:68` asserts `rr.provider("missing")` raises `UnknownProviderError`.
- `tests/test_m2_exit_criteria.py:32` also re-pins the optional N1 continuity checks for `rr.providers()` and missing provider lookup.

T118 tracker-bullet coverage:

- Public `ProviderHandle` Protocol with full method set: `tests/test_m2_exit_criteria.py:36`
- Provider and global catalogue methods return `CatalogResult` with Polars data, packaged path: `tests/test_m2_exit_criteria.py:48`
- Invalid source raises fatal: `tests/test_m2_exit_criteria.py:70`
- `source="live"` warn / raise / ignore: `tests/test_m2_exit_criteria.py:73`
- Fake provider returns `ObservationResult` for one and many stations/products through the same method: `tests/test_m2_exit_criteria.py:96`
- Missing `start` / `end` raises before provider execution: `tests/test_m2_exit_criteria.py:81`
- Undeclared annotation names fail validation: `tests/test_m2_exit_criteria.py:118`
- `result.data == result.to_polars() == result.to_pandas()` canonical long table: `tests/test_m2_exit_criteria.py:114`
- `uv run pytest` passed: `335 passed`.

Stub ID invariant:

- T118 uses only step-05 stub station IDs `station-1`, `station-2` and product IDs `level`, `flow`, `level_hourly`, `level_max`.

Registry signature guard:

- No changes were made to `src/rivretrieve/_internal/registry.py`; `git diff -- src/rivretrieve/_internal/registry.py` was empty before commit.

## 5. Deviations from plan §6

- The package-surface checkpoint after adding `ProviderHandle` to `__init__.py` failed until T22/T23 were updated, because the old test still asserted `ProviderHandle` was absent. This was the expected transient failure from applying the surface change before rebounding `tests/test_package.py`.
- T117 uses `inspect.get_annotations(..., eval_str=False)` for Protocol method annotations. `typing.get_type_hints()` on `CatalogResult[pl.DataFrame]` forces Pydantic to materialize a parametrized generic schema for `pl.DataFrame`, which is unnecessary for this signature-shape pin and raises before the assertion can run.

## 6. Surprises

- `@runtime_checkable` plus `isinstance(handle, ProviderHandle)` worked cleanly for both a fresh `_ProviderHandle` and the public `rr.provider("stub_provider")` return.
- The Protocol keyword-only signature shape matched the dataclass instance methods.
- `ty check` accepted the Protocol declaration and the narrowed `rr.provider(...) -> ProviderHandle` return. The only friction was test-side access to CPython private Protocol marker attributes, handled through an `Any` view.
- The circular-import analysis held. `handle.py` imports only leaf type modules, and no import from `registry.py` into `handle.py` was needed.

## 7. D3 entries to surface in docs/discoveries.md

- D3-2: `ProviderHandle.products`, `stations`, and `station_products` return `CatalogResult[pl.DataFrame]` to match the concrete implementation, while the tracker shorthand names `ProductCatalog`, `StationCatalog`, and `StationProductCatalog` payload concepts. This should be surfaced after the step commit because `docs/discoveries.md` is outside this step's file-edit whitelist.
- D3-3: T117 uses raw postponed annotations instead of `get_type_hints()` for `CatalogResult[pl.DataFrame]` to avoid runtime Pydantic generic schema materialization.
- D3-4: The package still has no explicit `__all__`; T22 continues to define the public surface through `vars(rivretrieve)`.

## 8. M2 milestone status

All M2 exit criteria are met. This step closes M2 and is ready for the M2 `REPORT.md`.

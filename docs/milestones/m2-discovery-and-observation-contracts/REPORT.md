# M2 — Discovery and Observation Contracts — Milestone Report

**Status:** closed.
**Range:** `a62aea9` (M2 step 01) … `ae5f661` (M2 step 06, close), branch `docs/provider-redesign-proposal`, not pushed.
**Tracker entry:** [docs/milestone-tracker.md §3 "M2 — Discovery and observation contracts"](../../milestone-tracker.md).

M2 completes the no-provider harness surface against stub providers. After this milestone, the public `ProviderHandle` Protocol exposes the full seven-method catalogue and observation surface required by architecture.md §9, provider-level `source="packaged" | "live"` handling is capability-aware, the long-form observation contract is normalized with annotation schemas, and `rr.stations()` / `rr.products()` / `rr.product_info()` aggregate packaged catalogues offline. Architecture sections covered: §3, §4, §5, §6, §7, §8, §9, §11, §12, §13, §14, §15, §16, §17.

## 1. Steps executed

| Step | Commit | Tag | Tests after | Net new |
|------|--------|-----|-------------|---------|
| 01-provider-info-and-module-contract | `a62aea9` | `v0.1.9` | 123 | +32 |
| 02-catalogue-methods-packaged | `c213942` | `v0.1.10` | 150 | +27 |
| 03-live-source-capability-routing | `105b150` | `v0.1.11` | 185 | +35 |
| 04-observation-types | `95d0773` | `v0.1.12` | 286 | +101 |
| 05-observations-method | `ea9a8dd` | `v0.1.13` | 326 | +40 |
| 06-providerhandle-protocol-promotion | `ae5f661` | `v0.1.14` | 335 | +9 |

Tag inventory across M2: `v0.1.9` through `v0.1.14` sequentially, no gaps. Each step's commit bundles `plan.md`, `critique.md`, and `execution.md` together with the implementation, per the policy formalized in M1 (REPORT §7.1) and observed throughout M2.

## 2. Public API shipped — vs. tracker

| Tracker entry (line 115–126) | Shipped | Location | Divergence |
|---|---|---|---|
| `class ProviderHandle(Protocol): ...` | ✓ | `_internal.handle.ProviderHandle` re-exported as `rr.ProviderHandle` | none |
| `def provider(provider_id: str) -> ProviderHandle` | ✓ | `_internal.discovery.provider` (re-exported) | none — return type narrowed from `object` (M1) to `ProviderHandle` in step 06 |
| `def stations(...) -> CatalogResult[StationCatalog]` | ✓ | `_internal.discovery.stations` | annotation reads `CatalogResult[pl.DataFrame]` per D3-2 below |
| `def products(...) -> CatalogResult[ProductCatalog]` | ✓ | `_internal.discovery.products` | same as `stations` |
| `def product_info(...) -> CatalogResult[ProductCatalog]` | ✓ | `_internal.discovery.product_info` | same as `stations` |
| `ProviderHandle.info() -> ProviderInfo` | ✓ | `_internal.registry._ProviderHandle.info` | none |
| `ProviderHandle.products(*, source, observed_property, frequency, statistic, on_issue)` | ✓ | `_internal.registry._ProviderHandle.products` | annotation reads `CatalogResult[pl.DataFrame]` per D3-2 below |
| `ProviderHandle.stations(*, source, on_issue)` | ✓ | `_internal.registry._ProviderHandle.stations` | same |
| `ProviderHandle.station_products(stations, *, source, on_issue)` | ✓ | `_internal.registry._ProviderHandle.station_products` | same |
| `ProviderHandle.row_annotation_schema()` | ✓ | step 05 `_internal.registry._ProviderHandle.row_annotation_schema` | none |
| `ProviderHandle.series_annotation_schema()` | ✓ | step 05 `_internal.registry._ProviderHandle.series_annotation_schema` | none |
| `ProviderHandle.observations(*, stations, products, start, end, on_issue)` | ✓ | step 05 `_internal.registry._ProviderHandle.observations` | none |
| `ObservationResult.to_polars()` | ✓ | `_internal.observations.ObservationResult.to_polars` | identity — returns `self.data` |
| `ObservationResult.to_pandas()` | ✓ | same | boundary conversion via `pl.DataFrame.to_pandas` |

Public surface at M2 close (`rr.__init__` defined names, alphabetized): `ProviderHandle`, `product_info`, `products`, `provider`, `provider_info`, `providers`, `stations`, plus `__version__`. The negative control `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` (T119) asserts this exact set; `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion` (T120) confirms a 29-name deferred list — including `_ProviderHandle`, `ProviderModule`, `ObservationsUnavailableError`, `ObservationResult`, `ObservationRequest`, `AnnotationSchema`, `CatalogResult`, `CatalogProvenance`, `PackagedCatalogArtifact`, `LiveCatalogueUnsupportedIssue` — does not leak.

## 3. Internal types introduced — vs. tracker

All 12 tracker-named internal types landed:

| Type | Tracker line | Step |
|---|---|---|
| `ProviderInfo` | 128 | 01 |
| `ProviderHandle` | 129 | 06 (public Protocol; private dataclass `_ProviderHandle` already in M1) |
| `ProviderModule` | 130 | 01 |
| `CatalogueReader` | 131 | 02 |
| `CatalogueValidator` | 132 | — (continued as free function `validate_catalogue` from M1 step 02; tracker name is satisfied by the existing helper, not by a new class) |
| `LiveCatalogueUnsupportedIssue` | 133 | 03 |
| `ObservationRequest` | 134 | 04 |
| `ObservationResult` | 135 | 04 |
| `ObservationProvenance` | 136 | 04 |
| `AnnotationSchema` | 137 | 04 |
| `AnnotationTable` | 138 | 04 |
| `RawPayload` | 139 | 04 |

**Implementation-required additions not enumerated by the tracker (all internal):**

- **Step 01**: extension of `_ProviderHandle` with `.info()` delegating to a packaged `ProviderInfo` constructed via `ProviderInfo.from_row`; tests-only `tests/_stubs/stub_provider.py` (Protocol-conformant catalogue stub that raises `NotImplementedError` for catalogue methods at this step, becomes real in M2 step 05); `ProviderModule` declared as `@runtime_checkable Protocol` with `@staticmethod` members so module instances pass `isinstance` (the load-bearing pattern reused by `ProviderHandle` in step 06).
- **Step 02**: `CatalogueReader` as the single delegation site for `_ProviderHandle.products`/`stations`/`station_products`; three identical `if source != "packaged"` source-fatal stopgaps inside `CatalogueReader` set up the step 03 capability-aware replacement.
- **Step 03**: `LiveCatalogueRoutingNotImplementedError` (FatalContractError subclass) as the defensive route for the live-capable but unimplemented branch; `LiveCatalogueUnsupportedIssue` (Issue subclass) for the live-unsupported branch routed via `apply_on_issue`. The capability-aware routing replaced the step 02 stopgaps exactly as planned.
- **Step 04**: `ObservationDataSchema`, `RowAnnotationTableSchema`, `SeriesAnnotationTableSchema` (Polars-schema constants); `AnnotationSchemaDeclaration` (frozen-dataclass representation of one provider-declared annotation name and its value-validator); `validate_annotation_names`, `validate_observation_data` (free-function validators). The six tracker-named observation/annotation types all landed as Pydantic v2 frozen models with `ConfigDict(arbitrary_types_allowed=True)` so they could carry Polars frames.
- **Step 05**: `ObservationsUnavailableError`, `InvalidObservationRequestError`, `ObservationDataSchemaError`, `AnnotationSchemaViolationError` (all FatalContractError subclasses); extension of `_ProviderHandle` with `.observations`, `.row_annotation_schema`, `.series_annotation_schema`; `_module: ProviderModule | None = None` field on `_ProviderHandle` (default `None` preserves M1 / M2 step 02 / step 04 direct-construction tests); `ProviderRegistry.register` extended with optional `provider_module` parameter.
- **Step 06**: public `ProviderHandle` Protocol class in `_internal/handle.py` (sibling of `provider_module.py`); single in-scope edit to `_internal/discovery.py` narrowing the `provider(...)` return-type annotation.

None of these contradicts the tracker — all are derived primitives the tracker entry implies but does not name. The two load-bearing architectural choices that should be carried forward unmodified into M3 are: (a) the **module-check-first dispatch order** in `_ProviderHandle.observations` (step 05 round-1 m1 fold: module-presence check raises `ObservationsUnavailableError` before request construction); and (b) the **always-on annotation-name validation** in the handle (step 05 round-1 m2 fold: stricter-than-architecture-§13 interpretation, validates row AND series tables on every call).

## 4. Runtime dependencies added

None. M2 consumed only the four dependencies pinned in M1 (`polars`, `pandas`, `pydantic`, `requests`). The lockfile resolution carried forward unchanged except for the per-commit version-literal bumps captured by `uv.lock` and `pyproject.toml`.

## 5. Test count delta and negative-control inventory

**Total: 335 passing.** Net **+244** from M1 close.

**Negative-control tests, each enforcing one M2 exit criterion (tracker §3 lines 147–156):**

| Test | Enforces | Location |
|---|---|---|
| `test_m2_exit_criteria_public_surface_sweep` | every M2 exit-criterion bullet through `rr.*` calls and the registered stub | `tests/test_m2_exit_criteria.py` |
| `test_provider_handle_protocol_declares_exactly_seven_public_methods` (T116) | tracker §3 L120-126 method-name surface | `tests/test_provider_handle.py` |
| `test_provider_handle_protocol_method_signatures_match_tracker` (T117) | tracker §3 L120-126 signature shape verbatim (param names, kw-only, defaults, return annotations) | `tests/test_provider_handle.py` |
| `test_private_provider_handle_structurally_conforms_to_public_protocol` (T112) | `isinstance(_ProviderHandle, ProviderHandle)` via structural conformance, no inheritance | `tests/test_provider_handle.py` |
| `test_catalogue_reader_invalid_source_remains_direct_fatal_for_all_methods` (T40) and parametrized siblings | invalid `source` raises fatal regardless of `on_issue`; no `IssuePolicyError` chain | `tests/test_internal_catalogue_reader.py` |
| `test_catalogue_reader_live_*_{warn,raise,ignore}` (T31-T39) | live source → `warn` warns and returns issue, `raise` wraps the issue, `ignore` carries issue without warning | `tests/test_internal_catalogue_reader.py` |
| `test_handle_observations_*_request_fatal_under_{warn,raise,ignore}` (T89-T93) | missing/empty/wrong-type request inputs raise direct fatal before provider execution; no `IssuePolicyError` chain | `tests/test_internal_handle_observations.py` |
| `test_handle_observations_unavailable_*` (T94-T96) | module-absent registered handle raises `ObservationsUnavailableError` direct; `on_issue` cannot silence | `tests/test_internal_handle_observations.py` |
| `test_handle_observations_annotation_*_undeclared_under_{warn,raise,ignore}` (T97-T98) | undeclared row or series annotation names raise `AnnotationSchemaViolationError` direct | `tests/test_internal_handle_observations.py` |
| `test_observation_result_to_polars_returns_data_identity` (T538), `test_observation_result_to_pandas_matches_polars_boundary_conversion` (T544) | `result.data`, `to_polars()`, `to_pandas()` are the same canonical long table | `tests/test_internal_observations.py` |
| `test_init_public_surface_exports_m2_provider_handle_surface` (T119) | seven public symbols at M2 close, no leakage | `tests/test_package.py` |
| `test_deferred_public_names_remain_absent_after_provider_handle_promotion` (T120) | 29-name deferred list including internal types and FatalContractError subclasses stays absent | `tests/test_package.py` |
| `test_import_rivretrieve_does_not_import_providers_stubs_or_generators` | subprocess `sys.modules` after `import rivretrieve` does not pull `tests._stubs.stub_provider`, provider modules, or `generate_catalogue.py` | `tests/test_offline_import.py` |
| `test_stub_catalogue_functions_remain_explicitly_unimplemented` (T103, formerly T25) | stub `products`/`stations`/`station_products` keep `NotImplementedError` — even after step 05 added real `observations` | `tests/test_internal_provider_module.py` |

**Two-channel pattern continued from M1.** Every M2 fatal (`InvalidCatalogueSourceError`, `LiveCatalogueRoutingNotImplementedError`, `InvalidObservationRequestError`, `ObservationsUnavailableError`, `ObservationDataSchemaError`, `AnnotationSchemaViolationError`) is a `FatalContractError` subclass, raises direct, and has `_issue_policy_error_chain(exc) == []`. Step-by-step inline assertions enforce this in every parametrized × `on_issue` matrix. The only recoverable Issue path introduced in M2 is `LiveCatalogueUnsupportedIssue` (step 03), routed through `apply_on_issue` per architecture.md §15.

**Offline import invariant preserved.** Even after step 05 made `tests._stubs.stub_provider` Protocol-conformant with real `observations()`, the subprocess offline-import test still asserts the stub module is absent from `sys.modules` after `import rivretrieve` (T108 / T15-renamed-from-M1).

## 6. Discoveries logged

No new entry was committed to `docs/discoveries.md` during M2. Three M2-internal candidate discoveries were surfaced but deferred:

- **D3-2 (CatalogResult element-type annotation reconciliation).** Tracker §3 L121-123 names the public catalogue method return types as `CatalogResult[ProductCatalog]` / `CatalogResult[StationCatalog]` / `CatalogResult[StationProductCatalog]`. The implementation (private `_ProviderHandle` from M1 step 03 onward, public `ProviderHandle` Protocol in step 06) uses `CatalogResult[pl.DataFrame]` because `StationCatalog` etc. are runtime `CatalogueSchema` instances, not type aliases. Step 06 reviewer flagged this in critique §L11 as non-blocking; step 06 reconciled in plan §3 Q3 by pinning the Protocol annotation to the implementation value and surfacing D3-2 for a separate commit. **Action item: write D3-2 into `docs/discoveries.md` and decide between (a) a tracker note clarifying the shorthand, or (b) introducing `TypeAlias` definitions for `StationCatalog`/`ProductCatalog`/`StationProductCatalog` in M3.**
- **D3-3 (Protocol-introspection pattern stability).** Step 06's T116 / T117 rely on a stable runtime hook for enumerating Protocol members and their signatures. The plan §3 Q11 picked `inspect.getmembers` + `inspect.signature` over `__protocol_attrs__` because the latter is private CPython API. **Action item: surface to discoveries.md if a future Python upgrade breaks introspection.**
- **D3-4 (explicit `__all__` on the public package).** `rivretrieve/__init__.py` currently uses module-attribute access for the public surface; T119 enumerates `module_defined_names`. Adopting an explicit `__all__` would tighten the negative control. **Action item: defer to post-M3 or post-M5.**

The previously-queued **D2** (JSON-in-Parquet encoding and `ProviderInfoCatalog` column-set addenda) carries over unchanged from M1's REPORT §6 / §7.2-7.3 and is still uncommitted in the working tree. It does **not** block M3 dispatch *behaviorally* — the M3 planner consumes the implementation contract from M1 step 02 §3 lines 124-139 plus M2 step 01's `ProviderInfo.from_row` — but the architecture.md addendum that D2 names is still owed before `ch_foen` `generate_catalogue.py` lands.

## 7. Surprises and candidate updates for the coordinator's M3 prep

Items the project coordinator should review before M3 dispatch:

1. **`_ProviderHandle._module` field with a `None` default is load-bearing for back-compat.** Step 05 round-1 Q2 resolved this: the field defaults to `None` so that step 02 / step 04 tests that construct `_ProviderHandle` directly with two positional args (`provider_id`, `_artifact`) remain green at every intermediate pytest checkpoint. The `register()` signature extension (`provider_module: ProviderModule | None = None`) is the keyword-route counterpart. M3 will register `ch_foen` with a non-None module; M3 planner must consume the three-arg shape and *not* re-litigate the default. See step 05 plan §3 Q1-Q2.

2. **Module-check-first dispatch ordering in `_ProviderHandle.observations`.** Step 05 round-1 m1 fold pinned the dispatch order: `(a) module-presence check first, (b) ObservationRequest construction, (c) module call, (d/e) row + series annotation validation, (f) return`. The reviewer reasoned that a missing module is a stable registry-wiring fatal that is reportable before call-site input errors. M3 inherits this ordering when wiring real `ch_foen` observations into M4; M4 planner must not invert it to "validate inputs first." See step 05 plan §3 Q5.

3. **Always-on annotation-name validation is a deliberate stricter-than-§13 reading.** Architecture.md §13 says annotation schemas are validated "in tests/debug." Step 05 round-1 m2 fold made validation always-on in the handle on the rationale that the check is cheap, structural, and the architecture does not forbid production enforcement. M3's `ch_foen.row_annotation_schema` / `series_annotation_schema` declarations are therefore load-bearing: any row or series annotation name emitted by `ch_foen.observations` MUST be declared in the corresponding schema list, or every call will raise `AnnotationSchemaViolationError`. Surface this to the M3 planner.

4. **Stub observations universe is hardcoded, not artifact-driven.** Step 05 round-1 n2 fold: `stub_provider.observations` uses hardcoded station IDs (`station-1`, `station-2`) and product IDs (`level`, `flow`, `level_hourly`, `level_max`), independent of which artifact is registered alongside it. This is the **opposite** convention from how `ch_foen` will work in M3. M3 planner: the `ch_foen` station/product universes derive from the packaged catalogue artifacts; do not use the stub's hardcoded-universe pattern as a model.

5. **Public `ProviderHandle` is a structural Protocol with no inheritance link to `_ProviderHandle`.** Step 06 plan §3 Q4: the concrete frozen dataclass does NOT inherit from the public Protocol. Conformance is verified by `@runtime_checkable` + `isinstance` (T112). M3's `ch_foen` provider does NOT need to subclass anything — its module-level `observations` / `row_annotation_schema` / `series_annotation_schema` / `info` / `products` / `stations` / `station_products` functions just need to match the `ProviderModule` Protocol shape, exactly like `tests/_stubs/stub_provider.py` does. The `_ProviderHandle` wrapper carries the module reference and dispatches; provider authors never see it.

6. **`CatalogueReader` is the single catalogue-method delegation site.** All three `_ProviderHandle` catalogue methods (`products`, `stations`, `station_products`) flow through `_internal.catalogue_reader.CatalogueReader`. Step 03's capability-aware routing lives there. M3 must NOT introduce a parallel reader for `ch_foen`; the packaged-artifact behavior is purely shape-driven and any `ch_foen`-specific behavior belongs in the registered artifact or in the provider module's catalogue functions.

7. **D2 addendum is still uncommitted.** The working tree carries the D2 entry as an unstaged diff to `docs/discoveries.md` since M1 closeout. M3 dispatch should either (a) commit D2 standalone before M3 step 01 dispatch, or (b) include it in M3 step 01's commit. The architecture.md §7 / §9 addendum it names remains required-before-`generate_catalogue.py`.

8. **The reviewer/planner loop converged within 2 rounds on every M2 step.** Step 05 took two rounds with twelve fold items (m1-m7, n1-n5); every other step DISPATCHED AS-IS in round 1 or with one folded minor. No escalation to the human was needed.

## 8. Escalations

None. All architectural questions resolved within the planner/reviewer/executor loop. The step 05 round-1 fold count was the highest in any M1 or M2 step but did not require coordinator intervention.

## 9. Ready for M3

The no-provider harness is shippable. Steps 01–06 are committed, tagged, tested, and verified.

- `uv run pytest` at M2 close: **335 passing**.
- Public surface stable: `{ProviderHandle, provider, providers, provider_info, stations, products, product_info, __version__}`.
- Stub provider proves end-to-end behavior for catalogue methods (step 02), source-aware routing (step 03), observation contracts (step 05), and Protocol conformance through the public surface (step 06).
- No `ch_foen`-bound code leaked into M2 commits.

**M3 planner entry points:**
- The deferral list at the end of each M2 step's `plan.md` §7 enumerates exactly what M3 owns.
- This report's §3 (implementation-required additions per step) is the canonical record of the M2 internal contract.
- This report's §7.1, §7.2, §7.3, §7.5, §7.6 are the load-bearing patterns M3 must consume unchanged.
- Before M3 step 01 dispatch, the coordinator should: (a) commit the uncommitted D2 entry, (b) author the architecture.md §7 (JSON-in-Parquet) and §9 (`name` + `catalogue_version` columns) addenda named by D2, and (c) decide D3-2 (TypeAlias vs tracker note for the catalogue element-type shorthand).

The M3 planner can begin from a clean tree at `ae5f661` / `v0.1.14`.

# 03-registry-and-surface Execution

## What landed

- Files added/modified:
  - `docs/milestones/m1-harness-foundation/steps/03-registry-and-surface/plan.md`
  - `docs/milestones/m1-harness-foundation/steps/03-registry-and-surface/critique.md`
  - `docs/milestones/m1-harness-foundation/steps/03-registry-and-surface/execution.md`
  - `src/rivretrieve/__init__.py`
  - `src/rivretrieve/_internal/registry.py`
  - `src/rivretrieve/_internal/discovery.py`
  - `tests/conftest.py`
  - `tests/test_internal_registry.py`
  - `tests/test_discovery.py`
  - `tests/test_package.py`
  - `tests/test_offline_import.py`
  - `tests/test_m1_exit_criteria.py`
  - `pyproject.toml`
  - `uv.lock`
- Internal symbols added:
  - `rivretrieve._internal.registry.UnknownProviderError`
  - `rivretrieve._internal.registry._ProviderHandle`
  - `rivretrieve._internal.registry._ProviderRecord`
  - `rivretrieve._internal.registry.ProviderRegistry`
  - `rivretrieve._internal.registry._registry`
  - `rivretrieve._internal.discovery.providers`
  - `rivretrieve._internal.discovery.provider`
  - `rivretrieve._internal.discovery.provider_info`
- Public symbols added:
  - `rivretrieve.providers`
  - `rivretrieve.provider`
  - `rivretrieve.provider_info`
- Public surface delta:
  - Newly exported from `rivretrieve`: `providers`, `provider`, `provider_info`.

## Plan adherence

- §6.1: done as planned; `tests/conftest.py` first added only the stub artifact builder fixture, and `uv run pytest` passed with 72 tests.
- §6.2: done as planned; added `registry.py`, then added `_registry.clear()` autouse cleanup and internal registry tests. `uv run pytest` passed with 82 tests.
- §6.3: done as planned; added `discovery.py`, with `__version__` imported inside `provider_info()`. Initial discovery tests imported through the internal implementation before package-root export, and `uv run pytest` passed with 89 tests.
- §6.4: implemented with adjustment; `__init__.py` export and `tests/test_package.py` update were applied together because exporting first would necessarily make the old negative-control test fail. `uv run pytest tests/test_package.py` passed.
- §6.5: done as planned; public-surface assertion uses the exact equality shape and deferred-name loop from the plan.
- §6.6: done as planned; added subprocess offline-import negative control. `uv run pytest` passed with 90 tests.
- §6.7: done as planned; added compact M1 exit-criteria smoke sweep. `uv run pytest` passed with 91 tests.
- §6.8: done as planned; `execution.md` created and the staged set includes `plan.md`, `critique.md`, and `execution.md`.
- §6.9: done as planned; ran required tool sequence before the version bump, then `uv run bump-my-version bump patch`, then pytest. Version is `0.1.8`.
- §6.10: done as planned; inspected tags before tagging. Existing tags were `v0.1.2` through `v0.1.7`, so expected tag is `v0.1.8`.

Plan §5 tests:

- #1 `test_registry_initially_empty`: implemented.
- #2 `test_registry_registers_stub_provider_and_returns_handle`: implemented.
- #3 `test_registry_rejects_duplicate_provider_id`: implemented.
- #4 `test_registry_rejects_invalid_provider_id_format`: implemented.
- #5 `test_registry_rejects_provider_id_mismatch`: implemented.
- #6 `test_registry_get_unknown_provider_raises_unknown_provider_error`: implemented.
- #7 `test_providers_empty_registry_returns_empty_list`: implemented.
- #8 `test_providers_sorted_independent_of_registration_order`: implemented.
- #9 `test_provider_returns_registered_placeholder_object`: implemented.
- #10 `test_provider_unknown_raises_unknown_provider_error`: implemented; asserts no `IssuePolicyError` on the raised exception or anywhere in the cause/context graph.
- #11 `test_provider_info_empty_registry_returns_schema_conformant_catalog_result`: implemented; uses full `CatalogProvenance` object equality.
- #12 `test_provider_info_aggregates_registered_provider_rows`: implemented; exercises one `catalogue_version=None` row and one string row.
- #13 `test_import_rivretrieve_does_not_import_providers_or_generators`: implemented; subprocess command is `[sys.executable, "-c", script]`, and the affirmative sentinel `rivretrieve._internal.catalogues.artifact in sys.modules` is asserted.
- #14 `test_init_public_surface_exports_m1_discovery_only`: implemented with exact public-name equality and deferred-name absence loop.
- #15 `test_m1_exit_criteria_smoke_sweep`: implemented.

## Architecture invariants verified

- `rr.provider()` public return type is `object`: `src/rivretrieve/_internal/discovery.py` annotates `provider(provider_id: str) -> object`; `test_provider_returns_registered_placeholder_object` exercises the runtime private handle without narrowing the public signature.
- No public `ProviderHandle` Protocol export: no Protocol was introduced, and `test_init_public_surface_exports_m1_discovery_only` asserts `ProviderHandle` is absent from `rivretrieve`.
- `UnknownProviderError` raises regardless of `on_issue`: `ProviderRegistry.get()` raises `UnknownProviderError` directly; `test_provider_unknown_raises_unknown_provider_error` asserts no `IssuePolicyError` appears in the exception graph.
- Offline-import invariant: no provider package, generator, entry-point scan, or plugin discovery was added; `test_import_rivretrieve_does_not_import_providers_or_generators` enforces the subprocess `sys.modules` negative control.
- `on_issue` is the sole policy knob; `rr.provider()` takes none: discovery signatures expose no `on_issue`; missing lookup is direct fatal behavior.
- Polars-canonical: `provider_info()` constructs empty and non-empty `ProviderInfoCatalog` frames from `ProviderInfoCatalog.polars_schema`, then validates them. Tests #11 and #12 cover both paths.
- Provider ID regex enforced at registration only: `_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")` is used only by `ProviderRegistry.register()`. `test_provider_lookup_malformed_id_is_membership_miss` proves malformed lookup raises `UnknownProviderError`.
- No speculative abstractions: no Protocol, ABC, plugin loader, discovery base, provider package, or observation/annotation contract was added.
- `__init__.py` D1 reframing: only `providers`, `provider`, `provider_info`, and the version bump changed package-root public behavior; `test_init_public_surface_exports_m1_discovery_only` catches leaks.

## Negative-control evidence

- Test #10 assertion form:

```python
with pytest.raises(UnknownProviderError) as exc_info:
    rr.provider("missing")

assert not isinstance(exc_info.value, IssuePolicyError)
assert _issue_policy_error_chain(exc_info.value) == []
```

The helper traverses both `__cause__` and `__context__`.

- Test #11 expected provenance matches plan §3 / critical gate:

```python
expected_provenance = CatalogProvenance(
    source="packaged",
    provider_id=None,
    rivretrieve_version=rr.__version__,
    catalogue_version=None,
    artifact_id=None,
    artifact_path=None,
    artifact_hash=None,
    generated_at=None,
    retrieved_at=None,
    endpoints=(),
    query=None,
    response_version=None,
)
```

- Test #13 subprocess command and assertions:

```python
subprocess.run([sys.executable, "-c", script], capture_output=True, check=False, text=True)
assert "rivretrieve._internal.catalogues.artifact" in sys.modules
assert "rivretrieve.providers" not in sys.modules
for module_name in sys.modules:
    assert not module_name.startswith(("rivretrieve.providers.",))
    assert module_name.rsplit(".", 1)[-1] != "generate_catalogue"
```

The affirmative sentinel assertion passed.

- Test #14 assertion form:

```python
assert "__version__" in vars(rivretrieve)
module_defined_names = {name for name in vars(rivretrieve) if not name.startswith("_")}
assert module_defined_names == {"providers", "provider", "provider_info"}
for name in deferred_names:
    assert not hasattr(rivretrieve, name)
```

## M1 closure summary

- `rr.providers()` deterministic and offline: `test_providers_sorted_independent_of_registration_order` and `test_m1_exit_criteria_smoke_sweep`.
- `rr.provider("missing")` raises fatal: `test_provider_unknown_raises_unknown_provider_error` and `test_m1_exit_criteria_smoke_sweep`.
- `rr.provider_info()` returns `CatalogResult`: `test_provider_info_empty_registry_returns_schema_conformant_catalog_result` and `test_m1_exit_criteria_smoke_sweep`.
- Stub packaged artifacts validate: step 02 tests plus this step's shared `stub_packaged_catalogue_artifact` fixture and `test_m1_exit_criteria_smoke_sweep`.
- Corrupt artifacts raise immediately regardless of `on_issue`: step 02 T34 coverage remains in `tests/test_internal_packaged_catalogue_artifact.py`.
- Common schema nullability for `elevation_m` / `drainage_area_km2`: step 02 T04 coverage remains in `tests/test_internal_catalogue_schemas.py`.
- Importing `rivretrieve` does not import provider/generator: `test_import_rivretrieve_does_not_import_providers_or_generators`.
- `uv run pytest` passes: 91 passed.

## Operational notes for the orchestrator's REPORT.md

- Public API shipped vs tracker: matches M1 tracker entry exactly: `providers`, `provider`, `provider_info`.
- Internal types introduced vs tracker: matches M1 tracker entry; `ProviderRegistry` is internal, with private `_ProviderHandle`, `_ProviderRecord`, and `_registry`.
- Total test count delta: step 02 closed at 72; this step closes at 91, a net +19 tests.
- Negative-control tests landed in this step: unknown-provider no-`IssuePolicyError` chain, package-root public-surface equality, subprocess offline-import provider/generator absence.
- Tracker vs reality surprise: `__init__.py` export and package-surface test update had to be applied in the same local slice to keep the intermediate pytest-green invariant.

## Tool runs

- `uv run ruff format`: pass; 20 files left unchanged.
- `uv run ruff check --fix`: initially fixed one unused import and flagged explicit package-root re-exports; after redundant aliases, pass. Auto-fix applied to remove an unused test import.
- `uv run ty check`: pass; no warnings suppressed.
- `uv run pytest`: pass; 91 passed.
- New test names:
  - `test_registry_initially_empty`
  - `test_registry_registers_stub_provider_and_returns_handle`
  - `test_registry_rejects_duplicate_provider_id`
  - `test_registry_rejects_invalid_provider_id_format`
  - `test_registry_rejects_provider_id_mismatch`
  - `test_registry_get_unknown_provider_raises_unknown_provider_error`
  - `test_providers_empty_registry_returns_empty_list`
  - `test_providers_sorted_independent_of_registration_order`
  - `test_provider_returns_registered_placeholder_object`
  - `test_provider_unknown_raises_unknown_provider_error`
  - `test_provider_info_empty_registry_returns_schema_conformant_catalog_result`
  - `test_provider_info_aggregates_registered_provider_rows`
  - `test_provider_lookup_malformed_id_is_membership_miss`
  - `test_import_rivretrieve_does_not_import_providers_or_generators`
  - `test_m1_exit_criteria_smoke_sweep`

## Discoveries

- No contradiction with `architecture.md`, the milestone tracker, or the plan surfaced.
- No project-level discovery was added to `docs/discoveries.md`.

## Open items handed forward to M2

- M2 narrows `rr.provider()`'s return type from `object` to `ProviderHandle`. The runtime `_ProviderHandle` in `_internal/registry.py` is the object M2 extends; M2 will add the seven Protocol methods: `info`, `products`, `stations`, `station_products`, `row_annotation_schema`, `series_annotation_schema`, and `observations`.
- Other M2 deferrals: public `ProviderHandle` Protocol, provider catalogue methods, singular `ProviderInfo`, observation request/result contracts, annotation schemas, and top-level `stations` / `products` / `product_info` functions.
- M3 handoff: provider packages call `_registry.register(...)` from their explicit runtime package import path, not from any `rivretrieve.__init__.py`-triggered discovery loop.

## Verification

- Commit hash of landed step: pending until the commit is created.
- Tag created: pending; expected `v0.1.8` because existing tags stop at `v0.1.7`.
- Staged diff summary before commit: 14 files changed, 1266 insertions, 13 deletions.

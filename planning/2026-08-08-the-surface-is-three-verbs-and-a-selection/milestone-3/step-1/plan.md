# m3-s1 implementation plan — retain `products` as the canonical product vocabulary view

Pinned implementation ref: `4b16c5749817787b56f3ac54233c78529fb2a0ab`.

The executor starts with no vision-directory context and no network. Treat this plan and the tracked repository at the pinned ref as the complete specification. Inspect tracked inputs with `git show 4b16c5749817787b56f3ac54233c78529fb2a0ab:<path>` and `git grep ... 4b16c5749817787b56f3ac54233c78529fb2a0ab -- ...`; do not read or depend on vision, milestone, step, review, or planning artifacts.

## 1. Objective

Replace only the public top-level `rivretrieve.products(provider=None)` result with a deterministic vocabulary view: without a provider it returns the twelve sorted canonical product identifier strings, and with a registered provider it returns that provider's advertised identifiers in the same sorted `list[str]` shape. An unknown provider raises `UnknownProviderError`. The result is never a `CatalogResult` or a Polars `DataFrame`. Keep provider-specific descriptive product metadata internal and leave the existing `product_info`, provider-handle catalogue methods, packaged catalogue artifacts, and every other public capability unchanged.

## 2. Semantics to implement

### Public contract

Implement this exact callable contract in `src/rivretrieve/_internal/discovery.py`:

```python
def products(provider: str | None = None) -> list[str]:
```

Its operative rules are:

1. Call `_ensure_default_providers_registered()` before resolving either the global or scoped result.
2. Obtain the deterministic registered-provider vocabulary from `_registry.list_provider_ids()`.
3. When `provider is None`, inspect every registered provider's packaged product rows through `CatalogueReader.read_products()` and return the sorted, deduplicated union of their `product_id` strings. An empty registry, possible only in tests with default registration disabled, returns `[]`.
4. When `provider` is a string, first require exact membership in `_registry.list_provider_ids()`. If it is absent—including malformed strings—raise `UnknownProviderError(provider)` directly. Do not return an empty list and do not route the condition through issue policy.
5. For a registered provider, inspect only that provider's packaged product rows through `CatalogueReader.read_products()` and return its sorted, deduplicated `product_id` strings. The outer type is exactly the same built-in `list` as the global result.
6. Do not expose any product-row field other than `product_id`; in particular, do not return `provider_id`, `observed_property`, `frequency`, `statistic`, `period_type`, `period_anchor`, `unit`, or `native_id`.
7. Do not accept or add `source`, filtering, issue-policy, selection, or live-catalogue parameters. This function is a pure packaged-catalogue vocabulary view.
8. Keep the package-root export `rivretrieve.products` already present in `src/rivretrieve/__init__.py`; its imported function changes contract automatically, so `src/rivretrieve/__init__.py` itself is not edited.
9. Keep `product_info()` and `_global_products()` byte-for-byte unchanged in behavior: they continue to return the existing global table-shaped `CatalogResult[ProductCatalog]`. Milestone 9 owns the `product_info` alias. Do not redirect `product_info()` through the new `products()` function and do not remove, rename, export, or otherwise alter it in this step.
10. Keep `_ProviderHandle.products()` and all provider-module `products()` methods unchanged. They remain internal/provider-level table readers returning `CatalogResult[pl.DataFrame]`; only the top-level `rivretrieve.products(...)` changes.
11. Add this denotation line as the `products` function docstring so the new computation is explicit without pretending the entire existing discovery module computes one object:

```python
"""products : PackagedProductCatalogues × (ProviderId ∪ {None}) → list[ProductId]."""
```

12. Import `UnknownProviderError` beside `_registry` in `discovery.py`. Continue using the existing `CatalogueReader.read_products`; do not add a reader method or read parquet paths directly.

Use this implementation shape so provider validation, selection, deduplication, and ordering are not left implicit:

```python
def products(provider: str | None = None) -> list[str]:
    """products : PackagedProductCatalogues × (ProviderId ∪ {None}) → list[ProductId]."""
    _ensure_default_providers_registered()
    provider_ids = _registry.list_provider_ids()
    if provider is not None and provider not in provider_ids:
        raise UnknownProviderError(provider)
    selected_provider_ids = set(provider_ids if provider is None else [provider])
    return sorted(
        {
            product_id
            for record in _registry.iter_records()
            if record.provider_id in selected_provider_ids
            for product_id in CatalogueReader(record.artifact, record.provider_id)
            .read_products()
            .data["product_id"]
            .to_list()
        }
    )
```

Allow `ruff format` to choose the final line wrapping without changing this behavior.

### Fixed measured inputs

The following are established facts at the pinned ref and are acceptance inputs, not choices to revisit:

- There are exactly 53 provider-product rows across exactly 13 providers.
- There are exactly 12 distinct `product_id` values.
- After excluding source identity (`provider_id`) and source addressing (`native_id`), the exact descriptive tuple `(observed_property, frequency, statistic, period_type, period_anchor, unit)` has 21 distinct combinations over those twelve identifiers.
- Every provider advertises at least two products; provider counts range from 2 to 9.
- `_registry.list_provider_ids`, `UnknownProviderError`, and `CatalogueReader.read_products` all exist at the pinned ref and are the existing mechanisms this step consumes.
- `discovery.products` currently returns `CatalogResult[ProductCatalog]`; that table-shaped global accessor is the contract being replaced.

Do not add a pre-derived correctness argument or reopen the approved decision. Encode the fixed behavior and exact assertions below.

## 3. Write-set

This is the complete implementation write-set. Modify or create no other file.

| Path | Status | Required change |
|---|---|---|
| `src/rivretrieve/_internal/discovery.py` | modify | Change only top-level `products` to the optional-provider `list[str]` vocabulary contract; import and raise `UnknownProviderError`; retain `product_info` and `_global_products` unchanged. |
| `tests/test_discovery.py` | modify | Replace legacy global product-table assertions with exact vocabulary, all-provider scoping, plain-result-shape, reader delegation, empty-registry, and loud unknown-provider assertions. Keep explicit coverage that `product_info` retains its independent table contract. |
| `tests/test_catalogue_only_br_ana_jp_mlit_no_nve_th_thaiwater.py` | modify | In `test_catalogue_only_provider_remains_discoverable_and_readable`, replace the old global table filter with `rr.products(provider=provider_id)` and assert the exact existing parameterized ID set and count. Provider-handle and module table assertions remain unchanged. |
| `tests/test_catalogue_only_ch_foen_cz_chmi_fr_hubeau_lt_lhmt.py` | modify | In `test_catalogue_only_provider_remains_discoverable_and_readable`, replace the old global table filter with `rr.products(provider=provider_id)` and assert the exact existing parameterized ID set and count. Provider-handle and module table assertions remain unchanged. |
| `tests/test_m2_exit_criteria.py` | modify | Remove `rr.products()` from the list of table-shaped `CatalogResult` values and assert its exact stub vocabulary separately as a built-in list; keep all provider-handle catalogue assertions unchanged. |
| `tests/test_m5_exit_criteria.py` | modify | Delete the two obsolete assertions that introspect metadata columns through `rr.products().data`; the new exact twelve-ID assertion in `tests/test_discovery.py` supersedes their public-surface scope. Keep the wide-form-helper test unchanged. Do not move these assertions to `product_info`, because this step must not extend or redefine that milestone-9-owned alias. |
| `pr-body.md` | create, repository root, untracked | Write the exact PR body supplied in section 5. Never stage or commit it. |

There are no new or modified fixtures. No parquet, JSON, CSV, HTML, PDF, lockfile, configuration, version, documentation, glossary, ADR, package export, or provider file belongs in the write-set. In particular, do not edit `CONTEXT.md`: although it mentions canonical product ids, documentation authoring is outside this approved step's scope.

## 4. Existing assertions affected

Update or remove every affected assertion as follows.

### `tests/test_discovery.py`

- `test_global_products_aggregates_registered_packaged_artifacts`: rename/rewrite it to assert that two registered stub artifacts advertising `"level"` yield exactly `products() == ["level"]`. This proves sorting/deduplication at the public boundary; remove `.data`, schema, provenance, and issue assertions because those objects are no longer returned.
- `test_global_product_info_matches_products_contract`: rename/rewrite it to prove the deliberate separation. For one `stub_provider`, assert `products() == ["level"]`, while `product_info()` remains a `CatalogResult`, its `.data` is frame-equal to the registered artifact's complete products frame, its issues are `()`, and its provenance source is `"packaged"`. Do not change production `product_info` behavior.
- `test_global_discovery_disabled_defaults_empty_registry_returns_empty_catalog_result`: rename it to distinguish result kinds. Retain the existing station and `product_info` empty typed-frame assertions, but replace the old product-frame assertions with exact `products() == []` and `type(products()) is list`.
- `test_global_discovery_provenance_is_global_packaged`: remove only `assert products().provenance == expected`; retain the station and `product_info` provenance assertions because they still return catalogue envelopes.
- `test_global_discovery_uses_reader_for_table_selection_and_validation`: retain the `CatalogueReader.read_products` monkeypatch and exact final call count `{"stations": 1, "products": 2}`. Assert the vocabulary call returns `["level"]`, assert `product_info().data` is the products frame, and thereby prove both public forms still delegate packaged table reading to the reader.
- Add a default-catalogue acceptance test, named `test_products_returns_exact_global_vocabulary_and_every_provider_subset`, using the complete constants in section 5. It must assert the exact global list, exact provider-key order/set, exact list for each of all thirteen scopes, sortedness, subset membership, and built-in-list shape.
- Add `test_products_result_is_not_a_catalogue_or_dataframe`, asserting `type(rr.products()) is list`, `not isinstance(rr.products(), CatalogResult)`, and `not isinstance(rr.products(), pl.DataFrame)`.
- Add `test_products_unknown_provider_raises_loudly`, calling `rr.products(provider="missing_provider")`, asserting `UnknownProviderError`, exact `str(exc_info.value) == "Provider is not registered: missing_provider"`, exact `exc_info.value.provider_id == "missing_provider"`, and an empty `IssuePolicyError` chain.

### `tests/test_catalogue_only_br_ana_jp_mlit_no_nve_th_thaiwater.py`

- `test_catalogue_only_provider_remains_discoverable_and_readable`: only its global-product block changes. Replace `rr.products().data.filter(...)` with `global_products = rr.products(provider=provider_id)`, then assert `len(global_products) == product_count` and `set(global_products) == product_ids`. Every provider-handle/module `products().data` assertion in this file is intentionally untouched because it tests a different, retained internal/provider-level table contract.

### `tests/test_catalogue_only_ch_foen_cz_chmi_fr_hubeau_lt_lhmt.py`

- `test_catalogue_only_provider_remains_discoverable_and_readable`: only its global-product block changes. Replace the aggregate DataFrame/filter sequence with `global_products = rr.products(provider=provider_id)`, then assert `len(global_products) == product_count` and `set(global_products) == product_ids`. Every provider-handle/module `products().data` assertion is intentionally untouched.

### `tests/test_m2_exit_criteria.py`

- `test_m2_exit_criteria_public_surface_sweep`: remove `rr.products()` from `packaged_results`, so the existing `CatalogResult`, DataFrame, and provenance assertions continue to cover `provider_info`, `product_info`, `stations`, and provider-handle results only. Add exact `rr.products() == ["flow", "level", "level_hourly", "level_max"]`, `type(rr.products()) is list`, and `not isinstance(rr.products(), CatalogResult)`. Leave the provider-handle `handle.products()` result and its source/filter/issue assertions untouched.

### `tests/test_m5_exit_criteria.py`

- `test_v1_products_have_no_derivation_fields`: remove this function. It asserts metadata columns on the deleted public table shape. The exact vocabulary assertion contains no metadata fields and is stronger for the retained public capability.
- `test_v1_observed_property_vocabulary_remains_river_gauge_scope`: remove this function. The exact twelve canonical IDs in section 5 are the new complete public-vocabulary assertion.
- `test_v1_deferred_wide_form_helpers_remain_absent`: proven untouched; it does not call product discovery.

### Existing assertions proven untouched

- `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` remains unchanged: `products` is still exported and no public name is added or removed.
- `tests/test_provider_handle.py::test_provider_handle_protocol_method_signatures_match_tracker` remains unchanged: this step does not change `ProviderHandle.products`.
- `tests/test_internal_catalogue_reader.py::test_catalogue_reader_products_returns_packaged_catalog_result`, `test_catalogue_reader_product_filters_are_exact_and_case_sensitive`, `test_catalogue_reader_product_filter_no_match_returns_empty_result`, `test_catalogue_reader_products_use_exact_reduced_schema`, `test_catalogue_reader_packaged_products_unchanged_by_live_capability`, `test_catalogue_reader_live_products_warn_returns_empty_result_with_issue`, `test_catalogue_reader_live_products_raise_wraps_unsupported_issue`, `test_catalogue_reader_live_products_ignore_returns_issue_without_warning`, `test_catalogue_reader_live_capable_products_raise_defensive_fatal_for_every_on_issue`, and `test_catalogue_reader_live_products_invalid_filter_remains_direct_fatal` remain unchanged: `CatalogueReader.read_products` retains its internal table-shaped contract.
- `tests/test_map_stations.py::test_map_stations_reads_stations_not_products` remains unchanged: mapping must still avoid product reads.
- `tests/test_catalogue_only_br_ana_jp_mlit_no_nve_th_thaiwater.py::test_catalogue_only_module_retains_only_catalogue_surface` and `tests/test_catalogue_only_ch_foen_cz_chmi_fr_hubeau_lt_lhmt.py::test_catalogue_only_module_retains_only_catalogue_surface` remain unchanged: provider modules still expose their existing table readers.
- Provider-specific module tests such as `tests/test_ba_fhmzbih_module.py::test_ba_fhmzbih_products_offline`, `tests/test_pl_imgw_module.py::test_pl_imgw_products_offline`, `tests/test_usgs_nwis_module.py::test_usgs_nwis_products_offline`, and `tests/test_za_dws_module.py::test_za_dws_products_offline` remain unchanged for the same reason.
- `tests/test_domain_context.py` remains unchanged because `CONTEXT.md` is outside this step's write-set.

## 5. Authored data

### Exact global vocabulary

Use this complete value, including order, as the expected result of `rr.products()`:

```python
EXPECTED_PRODUCT_IDS = [
    "discharge_daily_max",
    "discharge_daily_mean",
    "discharge_hourly_mean",
    "discharge_instantaneous",
    "stage_daily_max",
    "stage_daily_mean",
    "stage_daily_min",
    "stage_hourly_mean",
    "stage_instantaneous",
    "water_temperature_daily_mean",
    "water_temperature_hourly_mean",
    "water_temperature_instantaneous",
]
```

### Exact provider-advertised subsets

Use this complete mapping, including every identifier string, as the parameter oracle for all thirteen provider scopes:

```python
EXPECTED_PRODUCTS_BY_PROVIDER = {
    "ba_fhmzbih": [
        "discharge_instantaneous",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    ],
    "br_ana": [
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_daily_mean",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    ],
    "ca_eccc": [
        "discharge_daily_mean",
        "stage_daily_mean",
    ],
    "ch_foen": [
        "discharge_instantaneous",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    ],
    "cz_chmi": [
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_daily_mean",
        "stage_instantaneous",
        "water_temperature_daily_mean",
    ],
    "fr_hubeau": [
        "discharge_daily_max",
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_daily_max",
        "stage_instantaneous",
        "water_temperature_instantaneous",
    ],
    "jp_mlit": [
        "discharge_daily_mean",
        "discharge_hourly_mean",
        "stage_daily_mean",
        "stage_hourly_mean",
    ],
    "lt_lhmt": [
        "discharge_daily_mean",
        "stage_daily_mean",
    ],
    "no_nve": [
        "discharge_daily_mean",
        "discharge_hourly_mean",
        "discharge_instantaneous",
        "stage_daily_mean",
        "stage_hourly_mean",
        "stage_instantaneous",
        "water_temperature_daily_mean",
        "water_temperature_hourly_mean",
        "water_temperature_instantaneous",
    ],
    "pl_imgw": [
        "discharge_daily_mean",
        "stage_daily_mean",
        "water_temperature_daily_mean",
    ],
    "th_thaiwater": [
        "discharge_instantaneous",
        "stage_instantaneous",
    ],
    "usgs_nwis": [
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_daily_max",
        "stage_daily_mean",
        "stage_daily_min",
        "stage_instantaneous",
    ],
    "za_dws": [
        "discharge_daily_mean",
        "discharge_instantaneous",
        "stage_instantaneous",
    ],
}
```

The all-provider test must additionally assert these exact relationships:

```python
assert list(EXPECTED_PRODUCTS_BY_PROVIDER) == rr.providers()
assert rr.products() == EXPECTED_PRODUCT_IDS
for provider_id, expected in EXPECTED_PRODUCTS_BY_PROVIDER.items():
    actual = rr.products(provider=provider_id)
    assert actual == expected
    assert type(actual) is list
    assert actual == sorted(actual)
    assert set(actual) <= set(EXPECTED_PRODUCT_IDS)
```

### Exact stub values

The existing single-row stub artifact advertises exactly:

```python
["level"]
```

The existing rich stub artifact used by `test_m2_exit_criteria_public_surface_sweep` advertises these values after required sorting:

```python
["flow", "level", "level_hourly", "level_max"]
```

### Exact unknown-provider failure

Use exactly this request and expected exception state:

```python
with pytest.raises(UnknownProviderError) as exc_info:
    rr.products(provider="missing_provider")

assert str(exc_info.value) == "Provider is not registered: missing_provider"
assert exc_info.value.provider_id == "missing_provider"
assert _issue_policy_error_chain(exc_info.value) == []
```

### Result-shape assertions

Use the exact public shape checks:

```python
result = rr.products()
assert type(result) is list
assert not isinstance(result, CatalogResult)
assert not isinstance(result, pl.DataFrame)
```

### Fixtures

Author no fixture. All acceptance values above are literal test constants derived from the pinned, unchanged packaged `products.parquet` artifacts. Do not rewrite those artifacts.

### Exact `pr-body.md`

Create `pr-body.md` at the worktree root with exactly:

```markdown
## Summary

- retain `products(provider=None)` as the canonical product vocabulary view
- return the same sorted list shape for every provider scope and reject unknown providers
- keep provider-specific catalogue metadata internal and leave `product_info` unchanged

## Validation

- `uv sync`
- `uv run ruff format`
- `uv run ruff check --fix`
- `uv run ty check src`
- `uv run pytest`
- `uv build`
```

Leave this file untracked and do not include it in the commit.

## 6. Acceptance criteria

Run focused checks during implementation as useful, but the ordered full gates in section 7 are authoritative.

1. Command:

   ```bash
   uv run pytest tests/test_discovery.py -q
   ```

   Expected observation: exit 0; the global result equals the exact twelve-element sorted list, all thirteen named provider calls equal their exact lists, the empty-registry result is `[]`, the public result is a built-in list and neither `CatalogResult` nor `pl.DataFrame`, and `missing_provider` raises the exact error text.

2. Command:

   ```bash
   uv run pytest tests/test_catalogue_only_br_ana_jp_mlit_no_nve_th_thaiwater.py tests/test_catalogue_only_ch_foen_cz_chmi_fr_hubeau_lt_lhmt.py -q
   ```

   Expected observation: exit 0; each of the nine catalogue-only providers remains readable through its provider-handle table APIs, while each top-level scoped vocabulary is the exact provider-advertised subset in section 5.

3. Command:

   ```bash
   uv run pytest tests/test_m2_exit_criteria.py tests/test_m5_exit_criteria.py tests/test_package.py tests/test_provider_handle.py tests/test_internal_catalogue_reader.py tests/test_map_stations.py -q
   ```

   Expected observation: exit 0; the new top-level list contract coexists with unchanged package export, `product_info`, provider-handle, catalogue-reader, mapping, and observation-result contracts.

4. Command:

   ```bash
   git diff --check
   ```

   Expected observation: exit 0 with no output.

5. Command:

   ```bash
   git status --short
   ```

   Expected observation before commit: only the six tracked paths in section 3 are modified and `pr-body.md` is untracked. Expected observation after the one commit: the six tracked paths are clean and only `?? pr-body.md` remains. No catalogue artifact, fixture, documentation, contract, version, or lockfile appears.

6. Command:

   ```bash
   git log -1 --format=%s
   ```

   Expected observation after commit: exactly `feat: retain products as vocabulary view`.

The default-branch baseline is `1622 passed, 2 skipped`. The implementation may change the collected/passed count because assertions are added and two obsolete tests are removed, but the full suite must have zero failures and exactly the repository's two pre-existing skips. Do not encode a guessed new pass count.

## 7. Gate commands

Run these commands verbatim, in exactly this order, before creating the commit:

```bash
uv sync
uv run ruff format
uv run ruff check --fix
uv run ty check src
uv run pytest
uv build
```

Every command must exit 0. `uv run ruff format` is mutating; after it and `uv run ruff check --fix`, inspect the diff and retain only in-scope formatting/fixes. Any red gate is caused by this change and must be fixed before proceeding.

## 8. Constraints and prohibitions

### Environment hazards — binding verbatim knowledge

1. "uv opens ~/.cache/uv/sdists-v9/.git for write on EVERY invocation, so no uv command can run under a sandbox that denies writes there. pce measures stated gates under a Seatbelt profile whose only writable roots are the repository root and the platform temporary directory, and the codex sandbox allows workdir, /tmp and $TMPDIR; neither allows ~/.cache. The machine therefore carries ~/.config/uv/uv.toml setting cache-dir to a warm shared cache under $TMPDIR, which both sandboxes permit. Measured: all five stated gates green in a cold fresh worktree with network denied. If a gate fails with 'Failed to initialize cache' / 'Operation not permitted (os error 1)', that config is missing or the temp cache was purged; recreate it and re-warm with uv sync --reinstall outside any sandbox. Do not point cache-dir inside the repository: uv warns it may be included in distributions and every fresh worktree starts cold with no network."
2. "Mutation testing must set PYTHONDONTWRITEBYTECODE=1 and pytest -p no:cacheprovider: same-size edits written within one mtime second collide under CPython (mtime, size) pyc invalidation and produce a false killed result."
3. "A full-suite run inside a git archive extraction shows a spurious extra failure in tests/test_ch_foen_generate_catalogue.py because that test shells out to git show HEAD: and an extraction is not a repository."
4. "The default-branch gate baseline is fully green as of the commit that introduced this file, and pce contract check aborts on the first red gate. Any red gate an executor observes is therefore caused by its own change and must be fixed, not tolerated against a historical baseline. The previous run's red baseline (a B905 at br_ana/generate_catalogue.py:507, an invalid-argument-type at br_ana/generate_catalogue.py:623, and an unresolved-import of tqdm at jp_mlit/generate_catalogue.py:202) was closed in that same commit; tqdm is now a declared dev dependency, so the deliberately-optional import at jp_mlit/generate_catalogue.py:202 resolves for ty while its try/except ImportError still governs runtime."
5. "tests/typecheck/nominal_window_misuse.py is an INTENTIONAL negative type-check fixture asserted by tests/test_internal_engine_contracts.py. It is excluded from the stated typecheck gate because that gate is scoped to src. Whole-project uv run ty check therefore reports it and must never be used as the gate. Never repair or suppress that fixture."
6. "uv run ruff format is the stated format gate and rewrites files in place rather than reporting; it exits 0 even when it reformats. Use uv run ruff format --check to observe drift without mutating the tree."

### Gate ordering — binding verbatim knowledge

1. "uv sync before format before lint before typecheck before test; uv build last"

### Lockfile rule — binding verbatim knowledge

1. "uv.lock is tracked and must stay synchronized with pyproject.toml; uv sync reports 0 changes at this baseline"

### Not-touched scope fence

- Do not modify `product_info`, `_global_products`, `src/rivretrieve/__init__.py`, `ProviderHandle`, `_ProviderHandle.products`, `CatalogueReader.read_products`, provider modules, catalogue schemas, catalogue generation, or packaged catalogue artifacts.
- Do not change any field under `stated` in `.pce/repository-contract.json`; do not edit that file at all.
- Do not modify `pyproject.toml` or `uv.lock`; add no dependency and make no version bump.
- Do not update `__version__`, create a release tag, or decide whether native tables ship in the wheel. Version policy is NONE.
- Do not create a new ADR and do not edit `CONTEXT.md` or any documentation. The exact behavior is already fixed for this step, and documentation authoring is out of scope.
- Do not touch the vision, graphs, milestones, steps, review artifacts, prior plans, or reports.
- Do not add bounding-box behavior, `record_covers`, shipped `source="live"`, a coverage snapshot, harmonised name/river search, a chained query language, PyPI publication, provider porting, or any selection behavior.
- Do not add or alter fixtures. Do not regenerate any `products.parquet`; this change reads the already packaged rows.
- Do not collapse descriptive product fields into a canonical metadata row and do not expose provider-specific catalogue metadata from top-level `products`.
- Do not plan or implement another milestone. Milestone 9 owns `product_info`; this step neither removes nor redesigns it.
- Preserve reversibility: the exact expected values in section 5 and this explicit scope fence are the record of what changed and what did not. Do not add a design-correctness essay.

## 9. Executor policies

1. Implement and validate this step as exactly ONE squash-merge-ready conventional commit. Use this exact commit subject:

   ```text
   feat: retain products as vocabulary view
   ```

2. Run every gate in section 7 before the commit. If any gate rewrites a file or exposes a failure, inspect and fix it, then restart the ordered gate sequence from `uv sync`.
3. Create `pr-body.md` at the worktree root with the exact contents in section 5 and leave it UNTRACKED. Do not stage or commit it.
4. Create NO tag. Do NOT push.
5. Add NO attribution footers or co-author lines.
6. Do not edit any field under `stated` in `.pce/repository-contract.json`.
7. After committing, verify that `git status --short` reports only `?? pr-body.md`, `git log -1 --format=%s` reports the exact subject above, and `git diff HEAD^ --name-only` reports exactly these six tracked paths:

   ```text
   src/rivretrieve/_internal/discovery.py
   tests/test_catalogue_only_br_ana_jp_mlit_no_nve_th_thaiwater.py
   tests/test_catalogue_only_ch_foen_cz_chmi_fr_hubeau_lt_lhmt.py
   tests/test_discovery.py
   tests/test_m2_exit_criteria.py
   tests/test_m5_exit_criteria.py
   ```

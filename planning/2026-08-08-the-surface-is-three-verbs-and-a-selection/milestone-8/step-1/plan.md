# m8-s1 implementation plan: exclude `source_metadata` from the public surface

## 1. Objective

Codify the installed package's public contract by adding an explicit regression assertion that `rivretrieve.source_metadata` does not exist. Do not implement, import, re-export, or dynamically provide `source_metadata`; retain the four-field packaged-catalogue carrier and the existing exact top-level public-name set. This step is test-only: it records the approved absence as observable behaviour without changing runtime code, catalogue data, or packaging.

## 2. Semantics to implement

Implement these rules exactly:

1. After `import rivretrieve`, `hasattr(rivretrieve, "source_metadata")` must be exactly `False`.
2. The complete set of non-underscore names defined by `rivretrieve` must remain exactly:

   ```python
   {
       "ProviderHandle",
       "RawMode",
       "map_stations",
       "observations",
       "product_info",
       "products",
       "provider",
       "provider_info",
       "providers",
       "stations",
   }
   ```

3. Do not add a `source_metadata` function, method, attribute, alias, lazy attribute, import, export, protocol member, result carrier, or exception anywhere in `src/`.
4. `PackagedCatalogArtifact` must continue to carry exactly these four fields, in this order and with these existing types:

   ```python
   provider_info: dict[str, object]
   products: pl.DataFrame
   stations: pl.DataFrame
   station_products: pl.DataFrame
   ```

5. `REQUIRED_ARTIFACT_FILES` must remain exactly:

   ```python
   (
       "provider.json",
       "products.parquet",
       "stations.parquet",
       "station_products.parquet",
   )
   ```

   A native table is not a required packaged catalogue artifact.
6. `read_native_table` remains internal and continues to require a caller-supplied filesystem path through its existing signature `read_native_table(path: Path | str) -> NativeTable`; do not turn it into an installed-resource lookup or a public API.
7. The tracked tree at ref `4b16c5749817787b56f3ac54233c78529fb2a0ab` contains `catalogue/native.parquet` for exactly these eleven providers:

   ```text
   ba_fhmzbih
   ca_eccc
   ch_foen
   cz_chmi
   fr_hubeau
   jp_mlit
   lt_lhmt
   pl_imgw
   th_thaiwater
   usgs_nwis
   za_dws
   ```

   It is absent for exactly these two of the thirteen providers:

   ```text
   br_ana
   no_nve
   ```

   Binding approved outcome: expose no public source-metadata capability, including one described as source-checkout-only. Do not attempt to fill the two missing tables.
8. `pyproject.toml` continues to use this build system verbatim:

   ```toml
   [build-system]
   requires = ["uv_build>=0.11.16,<0.12"]
   build-backend = "uv_build"
   ```

   There is no separate package-data configuration at the ref. The summary's literal phrase "no build-backend or package-data section" cannot be restated literally as a verified fact because the quoted `[build-system]` does contain `build-backend = "uv_build"`; the verified repository fact is that there is no additional backend-specific or package-data configuration. Do not add any packaging configuration and do not decide whether native tables should ship in a wheel; that remains issue #51's scope.
9. `source_metadata` appears nowhere in the tracked files at the ref. The only new occurrence introduced by this step is the literal in the regression assertion in `tests/test_package.py` (and the untracked PR-body description). No production occurrence is permitted.
10. The approved summary refers to ADR-0020, but `docs/adr/0020-*.md` is not present at the exact planning ref (the tracked ADR sequence ends at `0018-raw-is-what-parse-read.md`), so the executor must not rely on an unavailable citation. Apply the complete behavioural rule in item 7 directly.

These are measured repository facts and required outcomes, not an invitation to revisit the public-surface decision.

## 3. Write-set

The complete authored write-set is:

- `tests/test_package.py` — modify the existing `test_init_public_surface_exports_m2_provider_handle_surface` test by adding one explicit assertion after the unchanged exact-name-set assertion:

  ```python
  assert not hasattr(rivretrieve, "source_metadata")
  ```

  Keep every existing import, test, expected name, and assertion unchanged. Do not add a fixture and do not change production code.
- `pr-body.md` — create at the worktree root with the exact contents in section 5. Leave it untracked and do not commit it.

There are no other authored files. In particular, the tracked commit contains exactly `tests/test_package.py`; `pr-body.md` is deliberately untracked. Gate-created ignored build/environment artifacts such as `.venv/`, tool caches, and `dist/` are not authored implementation files and must not be staged. If any tracked file other than `tests/test_package.py` changes during the work or gates, restore the unintended change without using a destructive broad reset and rerun the relevant gate.

## 4. Existing assertions affected

- `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` is the sole updated test. Preserve its existing `"__version__" in vars(rivretrieve)` assertion, the exact ten-name set quoted in section 2, and `rivretrieve.RawMode is RawMode`. Add only `assert not hasattr(rivretrieve, "source_metadata")` after the exact-set assertion. The existing exact-set assertion already excludes the name; the new assertion additionally guards against a module-level dynamic attribute.
- `tests/test_package.py::test_version` is proven untouched: neither the package version nor version metadata changes.
- `tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion` is proven untouched: preserve its complete existing `deferred_names`, `removed_contract_names`, and `affected_modules` values. Do not add `source_metadata` to `deferred_names`; this step records an approved absence, not a public promise to add it later.
- `tests/test_package.py::test_all_packaged_catalogues_expose_exact_reduced_carriers` is proven untouched: no catalogue schema, provider list, packaged artifact, licence/citation value, or metadata assertion changes.
- `tests/test_m2_exit_criteria.py::test_m2_exit_criteria_public_surface_sweep` is proven untouched: the top-level verbs and `ProviderHandle` protocol remain unchanged; `source_metadata` is not added as a verb or handle method.
- `tests/test_internal_packaged_catalogue_artifact.py::test_packaged_artifact_from_components_happy_path` and `tests/test_internal_packaged_catalogue_artifact.py::test_packaged_artifact_from_path_happy_path` are proven untouched: the four artifact fields and four required files do not change.
- `tests/test_catalogue_native.py::test_native_table_parquet_round_trip` is proven untouched: `read_native_table` retains its filesystem-path contract and remains internal.
- `tests/test_offline_import.py::test_import_rivretrieve_does_not_import_providers_stubs_or_generators` is proven untouched: the package import graph does not change because there is no runtime implementation.

No other existing assertion is affected because the tracked diff changes only a test assertion and makes no runtime, schema, catalogue, data, dependency, or packaging change.

## 5. Authored data

There are no fixtures, frames, station identifiers, error messages, catalogue rows, or binary data authored by this step.

The exact new regression assertion is:

```python
assert not hasattr(rivretrieve, "source_metadata")
```

Its complete expected value is `False`; it produces no expected error text.

For avoidance of ambiguity, the complete affected test must end in this assertion sequence after `module_defined_names` is computed:

```python
assert "__version__" in vars(rivretrieve)
assert module_defined_names == {
    "ProviderHandle",
    "RawMode",
    "map_stations",
    "observations",
    "product_info",
    "products",
    "provider",
    "provider_info",
    "providers",
    "stations",
}
assert not hasattr(rivretrieve, "source_metadata")
assert rivretrieve.RawMode is RawMode
```

Create `pr-body.md` with exactly:

```markdown
## Summary

- codify that `source_metadata` is absent from the installed package public surface
- preserve the existing three-verbs-and-a-selection API and four-field packaged catalogue artifact
- leave runtime code, catalogue data, and packaging configuration unchanged

## Validation

- `uv sync`
- `uv run ruff format`
- `uv run ruff check --fix`
- `uv run ty check src`
- `uv run pytest`
- `uv build`
```

The exact conventional commit subject is:

```text
test: exclude source_metadata from the public surface
```

## 6. Acceptance criteria

1. Run `uv sync`. It exits zero, reports no lockfile/dependency changes at this baseline, and leaves `uv.lock` byte-for-byte unchanged.
2. Run `uv run ruff format`. It exits zero; the resulting `tests/test_package.py` is formatted and no unrelated tracked file changes.
3. Run `uv run ruff check --fix`. It exits zero with no remaining lint diagnostics and makes no additional tracked-file change.
4. Run `uv run ty check src`. It exits zero. The gate is intentionally scoped to `src`, and this test-only change adds no production type error.
5. Run `uv run pytest`. It exits zero with the baseline count `1622 passed, 2 skipped`; no test is added or removed, because the new evidence is an assertion in an existing test. In particular, `tests/test_package.py::test_init_public_surface_exports_m2_provider_handle_surface` passes only when the complete name set remains the exact ten strings in section 2 and `hasattr(rivretrieve, "source_metadata")` is `False`.
6. Run `uv build`. It exits zero and produces the version `0.1.49` source distribution and wheel without any packaging-configuration or version change.
7. Before committing, `git diff --name-only` reports exactly `tests/test_package.py`. `git diff -- tests/test_package.py` shows only the one added assertion. `git status --short` also shows `?? pr-body.md`; do not stage it.
8. Commit exactly once with subject `test: exclude source_metadata from the public surface`. After the commit, `git show --name-only --format= HEAD` lists exactly `tests/test_package.py`, `git status --short` lists only `?? pr-body.md`, and there is no tag or push.

The default-branch baseline is fully green (`1622 passed, 2 skipped`). Any red gate is caused by this change or its execution environment and must be fixed; never accept or document a red result as historical.

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

Do not substitute a broader typecheck command. Gates run before the commit. If a gate edits a tracked file, inspect it, keep only an in-scope necessary change, and rerun that gate plus every later command in the sequence.

## 8. Constraints and prohibitions

- Modify no production source file. In particular, do not edit `src/rivretrieve/__init__.py`, `src/rivretrieve/_internal/catalogues/native.py`, `src/rivretrieve/_internal/catalogues/artifact.py`, discovery code, handle/protocol code, provider modules, or catalogue generators.
- Do not implement or export `source_metadata` anywhere and do not add it to `__all__`, dynamic `__getattr__`, a `ProviderHandle`, or any internal/public result type.
- Do not edit any `native.parquet`, canonical catalogue artifact, fixture, schema, origin declaration, or provider data. Do not create the absent `br_ana` or `no_nve` native tables.
- Do not alter packaging configuration. Do not add a package-data section, change the build backend, or decide whether native tables ship in a wheel; issue #51 owns that decision.
- Do not modify `pyproject.toml`, `uv.lock`, `src/rivretrieve/__init__.py`, version `0.1.49`, or bump-version configuration. Version policy is NONE: no version bump and no tag.
- Do not edit any field under `stated` in `.pce/repository-contract.json`.
- Do not touch the vision, milestone/step graphs, planning/review artifacts, ADRs, documentation, or changelog.
- Plan and implement only m8-s1. Add no bounding box, `record_covers`, shipped `source="live"`, coverage snapshot, harmonised name/river search, chained query language, PyPI publication, documentation authoring, provider porting, or decision about native tables in the wheel.
- Keep the explicit not-touched fence repeatable: the implementation is exactly one assertion, with the exact existing public-name expectation retained. Do not add a pre-derived design-correctness argument to code or PR text.
- Use `uv` exclusively for the Python environment and commands; never use `pip`, Poetry, Conda, or pip-tools directly.

Binding repository knowledge, quoted verbatim:

1. "uv opens ~/.cache/uv/sdists-v9/.git for write on EVERY invocation, so no uv command can run under a sandbox that denies writes there. pce measures stated gates under a Seatbelt profile whose only writable roots are the repository root and the platform temporary directory, and the codex sandbox allows workdir, /tmp and $TMPDIR; neither allows ~/.cache. The machine therefore carries ~/.config/uv/uv.toml setting cache-dir to a warm shared cache under $TMPDIR, which both sandboxes permit. Measured: all five stated gates green in a cold fresh worktree with network denied. If a gate fails with 'Failed to initialize cache' / 'Operation not permitted (os error 1)', that config is missing or the temp cache was purged; recreate it and re-warm with uv sync --reinstall outside any sandbox. Do not point cache-dir inside the repository: uv warns it may be included in distributions and every fresh worktree starts cold with no network."
2. "Mutation testing must set PYTHONDONTWRITEBYTECODE=1 and pytest -p no:cacheprovider: same-size edits written within one mtime second collide under CPython (mtime, size) pyc invalidation and produce a false killed result."
3. "A full-suite run inside a git archive extraction shows a spurious extra failure in tests/test_ch_foen_generate_catalogue.py because that test shells out to git show HEAD: and an extraction is not a repository."
4. "The default-branch gate baseline is fully green as of the commit that introduced this file, and pce contract check aborts on the first red gate. Any red gate an executor observes is therefore caused by its own change and must be fixed, not tolerated against a historical baseline. The previous run's red baseline (a B905 at br_ana/generate_catalogue.py:507, an invalid-argument-type at br_ana/generate_catalogue.py:623, and an unresolved-import of tqdm at jp_mlit/generate_catalogue.py:202) was closed in that same commit; tqdm is now a declared dev dependency, so the deliberately-optional import at jp_mlit/generate_catalogue.py:202 resolves for ty while its try/except ImportError still governs runtime."
5. "tests/typecheck/nominal_window_misuse.py is an INTENTIONAL negative type-check fixture asserted by tests/test_internal_engine_contracts.py. It is excluded from the stated typecheck gate because that gate is scoped to src. Whole-project uv run ty check therefore reports it and must never be used as the gate. Never repair or suppress that fixture."
6. "uv run ruff format is the stated format gate and rewrites files in place rather than reporting; it exits 0 even when it reformats. Use uv run ruff format --check to observe drift without mutating the tree."
7. "uv sync before format before lint before typecheck before test; uv build last"
8. "uv.lock is tracked and must stay synchronized with pyproject.toml; uv sync reports 0 changes at this baseline"

If mutation testing is voluntarily used in addition to the required gates, invoke pytest with `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider` as required above. Mutation testing is not an acceptance gate for this step.

## 9. Executor policies

- Work on the m8-s1 step branch targeting `pce/the-surface-is-three-verbs-and-a-selection/milestone-8`; the pull request is squash-merged into that milestone branch.
- Produce exactly ONE conventional commit, after every command in section 7 is green. Use exactly `test: exclude source_metadata from the public surface` as its subject.
- Write the PR body to `pr-body.md` at the worktree root using the exact contents in section 5. Leave `pr-body.md` UNTRACKED. Do not stage or commit it.
- Create NO tag.
- Do NOT push.
- Add NO attribution footers, including no `Co-authored-by`, `Signed-off-by`, or tool attribution.
- Do not edit any field under `stated` in `.pce/repository-contract.json`.
- Do not commit gate-generated build artifacts, caches, or environment files.
- Gates run BEFORE the commit. If any gate is red, fix the cause and repeat from the affected point in the required order; do not commit a red state.

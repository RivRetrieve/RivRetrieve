# 03-registry-and-surface Critique

## Verdict
DISPATCH WITH MINORS FOLDED

The plan is substantively correct on the two highest-risk regression vectors (R1 fatal-by-direct-raise, R2 subprocess sys.modules inspection), the determinism contract (sorted, tested with non-alphabetical registration), the empty-registry provenance shape, the deferral set, the D1 `__init__.py` exemption wording, and the M2-forward-compat handle shape. A handful of tightenings are needed before dispatch — most procedurally, the §6 file list does not include `plan.md` and `critique.md` in the staged set, and the conftest fixture-introduction ordering risks breaking the intermediate `uv run pytest` invariant. Both fold in cleanly without re-planning.

## Major findings

None.

## Minor findings

### M-1. §6 omits `plan.md` and `critique.md` from the staged commit set (L17)

Plan §6 step 8 only names `execution.md` as a step file: *"Executor creates this after implementation, not during planning, with self-review and command evidence."* The orchestrator's just-decided audit-trail policy stages plan.md + critique.md + execution.md TOGETHER with the step's commit. Step 02 followed this (the `02-catalogue-schemas/` directory holds all three); step 03 must do the same.

**Fix:** add a line to §6 stating the staged set includes `docs/milestones/m1-harness-foundation/steps/03-registry-and-surface/{plan.md, critique.md, execution.md}` in the commit alongside source/test files and the version bump.

### M-2. conftest fixture-introduction ordering can break the intermediate-state invariant (L8)

Plan §6 step 1 says: *"Add a stub artifact fixture and registry cleanup fixture. […] If adding this alone, existing tests should still pass."* But the registry cleanup fixture must call `_registry.clear()`, which is defined in step 2 (`registry.py`). If the fixture lives in `tests/conftest.py` and imports `rivretrieve._internal.registry` at module load time before step 2 runs, `uv run pytest` collection fails repository-wide — not just for the new tests.

Architecture.md §0 (tracker line 9) requires *"the package installable/importable and `uv run pytest` green at every milestone boundary; no milestone may leave half-wired public imports or failing placeholder behavior."* Step boundaries are similarly bound.

**Fix:** either (a) merge step 1 into step 2 (introduce conftest helpers and the registry module in one commit-internal slice), or (b) explicitly state that step 1 only adds the stub-artifact builder (which depends on step 02's already-shipped `packaged_catalogue_artifact_from_components`), and the registry-clear fixture is added in step 2 alongside `registry.py`.

### M-3. The "rr.provider('missing') under on_issue='ignore' still raises" test is not specified — but the API does not expose `on_issue`, so the brief's expected regression test is mechanically infeasible (L4, R1)

The critique brief asked me to verify a test of the form `rr.provider("missing", on_issue="ignore")` still raises. The tracker §3 line 58 pins the signature as `def provider(provider_id: str) -> object: ...` with no `on_issue` parameter, so that test cannot be written as posed. The plan correctly does not invent an `on_issue` parameter, and Tests #6/#10 do prove `UnknownProviderError` is raised via `raise`, not encoded via `apply_on_issue`.

That said, the R1 regression vector — encoding unknown-provider as a recoverable Issue rather than a direct raise — should still get an explicit guard. The current Tests #6/#10 prove an exception is raised, but not that the exception was raised by a direct `raise`, not by `apply_on_issue` with `on_issue="raise"`.

**Fix:** add one line to Test #10 (or a new test) asserting `UnknownProviderError` is *not* a subclass of `IssuePolicyError` and that no `IssuePolicyError` is in the chain. This is a one-line `isinstance` check that prospectively blocks anyone "improving" the registry by routing the unknown-ID case through the issue policy.

### M-4. Offline-import test misses the affirmative side of its assertion (L12)

Plan §5 Test 13 / §6 step 6 lists the three negative assertions (no `rivretrieve.providers`, no `rivretrieve.providers.*`, no `*.generate_catalogue`). That's the necessary safety net. The brief flagged a bonus: also assert that `rivretrieve._internal.catalogues.artifact` *is* in `sys.modules` after `import rivretrieve`. Without that, the test would still pass in an even more pathological future state where `import rivretrieve` is silently a no-op or partially fails.

**Fix:** add `assert "rivretrieve._internal.catalogues.artifact" in sys.modules` (or whatever module `provider_info()` ultimately depends on) as the "did rivretrieve actually load?" affirmative. Cheap, defensive, and survives future restructuring.

### M-5. Test #11 under-specifies the provenance assertion (L15)

Plan §5 Test 11 says provenance "source is packaged, version is populated, and issues are empty." Plan §3 specifies eleven fields of `CatalogProvenance` with exact expected values (`provider_id=None`, `artifact_id=None`, `endpoints=()`, etc.). The test should assert all eleven, not a subset, because the M2 provider-scoped `stations()`/`products()` aggregate provenance will need to be consistent with the M1 aggregate shape. A loose Test 11 would silently let drift creep in.

**Fix:** Test 11 asserts the full `CatalogProvenance` equality (construct the expected value once and compare with `==`, since `CatalogProvenance` is a frozen Pydantic BaseModel).

### M-6. ProviderInfoCatalog row construction from `artifact.provider_info` is under-specified for dtype coercion (L4, §3)

Plan §3 says: *"Convert each `_ProviderRecord.artifact.provider_info` dict into a row. Build a `pl.DataFrame(rows, schema=ProviderInfoCatalog.polars_schema)`."* But `artifact.provider_info` is the dict returned by `pl.DataFrame.row(0, named=True)` (artifact.py:88) — its `metadata` value is already the canonical JSON string per step 02, but boolean fields come back as Python `bool` and `catalogue_version` may be `None`. Building `pl.DataFrame(rows, schema=...)` with a nullable Utf8 column and a list of dicts where the value is `None` should work, but the plan should explicitly note that the dict-rows approach is exercised by Test #12 with at least one row where `catalogue_version is None` and one row where it is a real string, to confirm null-Utf8 dtype coercion works as expected.

**Fix:** strengthen Test #12 to register two stub providers with differing nullability on `catalogue_version`, so the test exercises the nullable column rather than just the all-nulls or all-strings case.

## Nits

### N-1. Q4 placeholder exposes `provider_id` as a public attribute on the runtime object (L13)

`_ProviderHandle(provider_id: ProviderId, _artifact: PackagedCatalogArtifact)` is a private dataclass, but its instance is the object returned by the public `rr.provider()`. Users who do `getattr(handle, "provider_id")` can read it, even though the public type is `object`. This isn't a contract violation (the runtime object can carry whatever fields it wants), but a future user could come to depend on it and constrain M2. Consider naming it `_provider_id` to underline that it is implementation detail. Cheap and forward-compatible.

### N-2. The `^[a-z][a-z0-9_]*$` regex permits `usgs__nwis` and trailing underscores like `usgs_`

Both are weird but not forbidden by tracker line 11 (*"Provider IDs are `snake_case`, identify source/agency where possible"*). Acceptable for M1; flagging in case the M2/M3 executor wants to tighten the rule when a real provider name surfaces it.

### N-3. Plan §6 step 3 hand-waves `__version__` imports

*"Prefer importing `rivretrieve.__version__` inside `provider_info()` or defining a tiny internal version accessor only if needed to avoid circular imports."* This is a judgment call left to the executor. Concrete recommendation: import inside the function body to defer the circular-import question to call time rather than module load time. Not worth blocking on.

## Lens-by-lens summary

- L1 (scope completeness): ✅ — registry, UnknownProviderError, three public functions, offline-import test, exit-criteria sweep, test_package.py update, version bump all present.
- L2 (over-reach): ✅ — no ProviderHandle Protocol, no observation types, no annotations, no real catalogue data, no extra rr.* functions, no plugin entry points.
- L3 (citations): ✅ — verified architecture.md §15 line 607 (fatal-regardless-of-on_issue), §2 lines 60-67 (provider ID examples), §9 lines 399-425 (M2 Protocol method list), tracker §3 lines 56-59 (provider() returns object), §3 lines 82-89 (M1 exit criteria), schemas.py 89-101 (ProviderInfoCatalog), results.py 12-26 (CatalogProvenance), artifact.py 30-31 (CorruptCatalogArtifactError local pattern), 64-71 (`packaged_catalogue_artifact_from_components`), 88 (`row(0, named=True)`). All confirmed; legacy `__init__.py` country-fetcher claim verified in `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/__init__.py:3-21`.
- L4 (test coverage adequacy): ⚠️ — see M-3 (R1 isinstance guard missing), M-4 (offline-import affirmative side missing), M-5 (provenance full-equality missing), M-6 (catalogue_version nullable not exercised). Determinism test ✓, empty-registry provider_info test ✓, double-register test ✓, format-rejection test ✓.
- L5 (error handling): ✅ — every fatal path raises a typed `FatalContractError` subclass; nothing leaks `KeyError`/`ValueError`.
- L6 (open questions Q1–Q14): ✅ with caveats — Q4 placeholder has no method-name collision with M2 Protocol (info/products/stations/station_products/row_annotation_schema/series_annotation_schema/observations); Q6 regex rejects `BAD-Provider`, `ProviderId`, `1provider`, `provider id`, accepts `usgs_nwis`/`uk_ea`/`uk_nrfa`/`ch_foen`; Q8 empty-DataFrame construction via `polars_schema` is correctly specified; Q11 specifies subprocess + sys.modules with the right absences (M-4 adds the affirmative).
- L7 (deferral hygiene): ✅ — ProviderHandle Protocol → M2 (tracker line 52, line 22), observation contracts → M2 (tracker lines 100-126), real ch_foen → M3 (tracker lines 164-208), plugin entry points → post-V1 (tracker line 339).
- L8 (implementation order keeps pytest green): ⚠️ — see M-2 (conftest fixture introduction may break intermediate state).
- L9 (stopping conditions): ✅ — §9 calls out lazy-vs-eager discovery, R1 vector, R2 vector via "subprocess test cannot be made meaningful," plugin entry points, and empty-DataFrame edge.
- L10 (architecture commitment compliance): ✅ — `def provider(provider_id: str) -> object` matches tracker line 58 verbatim; no ProviderHandle Protocol; no observation contracts; Polars canonical for empty provider_info; `on_issue` is the only policy knob; UnknownProviderError raises by direct `raise`.
- L11 (speculative abstractions): ✅ — no ABC, no plugin entry points, no Loader/Discovery base class, no unauthorized ProviderRegistry hooks. `_ProviderHandle` placeholder is correctly empty of methods.
- L12 (offline-import test rigor): ⚠️ — see M-4. Subprocess ✓; module-name enumeration ✓; meaningful-pre-providers ✓ via prospective guard; affirmative side missing.
- L13 (forward-compat with M2): ✅ — placeholder has no method-name collisions with M2 Protocol; placeholder is private (`_ProviderHandle`), so M2 can refactor freely. See N-1 for an attribute-name nit.
- L14 (determinism rigor): ✅ — sorted ascending; Test #8 specifically registers in non-alphabetical order.
- L15 (provenance shape for empty `rr.provider_info()`): ✅ in plan §3, ⚠️ in test — all eleven CatalogProvenance fields enumerated with expected values, but Test #11 only verifies a subset (see M-5).
- L16 (D1 reconciliation): ✅ — plan §6 step 4: *"this step may add only the three tracker-authorized public function symbols plus the version bump line. No `ProviderHandle`, `CatalogResult`, `Issue`, catalogue schemas, provider classes, or rearranged legacy-style imports."* Phrasing aligns with D1 exactly.
- L17 (audit-trail discipline): ❌ — see M-1. §6 step 8 only mentions `execution.md`; `plan.md` and this `critique.md` are not listed in the staged set.

## Adversarial probes attempted

- Opened `architecture.md` §15 line 607 to verify unknown-provider-fatal claim — confirmed (*"Fatal contract failures raise immediately regardless of `on_issue`, including unknown provider IDs, invalid catalogue source values, corrupt packaged catalogue artifacts, and provider implementation schema violations."*).
- Walked the M2 ProviderHandle method list (architecture.md §9 lines 399-425: `info`, `products`, `stations`, `station_products`, `row_annotation_schema`, `series_annotation_schema`, `observations`) against plan §Q4 placeholder methods — no collision (placeholder declares no methods, only fields `provider_id` and `_artifact`).
- Tested the planner's `^[a-z][a-z0-9_]*$` regex against `usgs_nwis`, `uk_ea`, `uk_nrfa`, `ch_foen`, `BAD-Provider`, `ProviderId`, `1provider`, `provider id`, `usgs__nwis`, `provider_` — accepts the four legitimate IDs, rejects the four bad inputs as required, accepts the two weird-but-legal cases (flagged as N-2).
- Checked plan §5/§6 for `on_issue="ignore"` unknown-provider test — not present, but the public `provider()` signature has no `on_issue` parameter (tracker line 58), so the test is mechanically infeasible. The R1 vector is instead guarded by direct `raise` in plan §4. See M-3 for the residual isinstance check.
- Checked plan §Q11 / §5 Test 13 / §6 step 6 for actual sys.modules inspection vs. import-success-only — subprocess + sys.modules inspection with three explicit absence assertions is specified. Confirmed not vacuous. See M-4 for the missing affirmative half.
- Verified `def provider(provider_id: str) -> object` in plan §2 against tracker line 58 — exact match, no narrower return type.
- Verified `_ProviderHandle` is private (underscore prefix) so M2 can promote without breaking — confirmed in plan §2 internal-surface list.
- Walked plan §6 file list looking for `plan.md` + `critique.md` in the staged set — neither is listed; only `execution.md` and source/test files. See M-1.
- Walked plan §6 step 1 (conftest fixtures) and step 2 (registry.py) for import-order safety — registry-clear fixture appears to depend on a module that step 1 has not yet created. See M-2.
- Verified `tests/test_package.py` line 12-15 currently asserts `module_defined_names == set()`; plan §6 step 5 / §Q13 correctly proposes replacing with `{"providers", "provider", "provider_info"}` plus an explicit absence list.
- Verified empty-DataFrame validation passes through `validate_catalogue` against `ProviderInfoCatalog`: `null_count() > 0` is `False` for empty (0 nulls), `is_duplicated().sum()` is `0`, metadata JSON validator iterates 0 rows — all pass.
- Verified legacy claim *"The legacy package exposes country fetcher classes from `rivretrieve/__init__.py`"* against `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python/rivretrieve/__init__.py:3-21` — confirmed (`USAFetcher`, `CanadaFetcher`, `UKEAFetcher`, etc. all re-exported from package root).
- Verified `CatalogProvenance` field set in plan §3 against `results.py:12-26` — all eleven fields enumerated match the model definition.

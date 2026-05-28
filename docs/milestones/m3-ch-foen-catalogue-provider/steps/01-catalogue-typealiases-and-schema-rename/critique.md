# Critique — 01-catalogue-typealiases-and-schema-rename

## Verdict

**DISPATCH WITH MINORS FOLDED.**

The plan correctly identifies the call-site universe, satisfies the D2 gate at HEAD, preserves the T119/T120 public surface, and stages the rename so `uv run pytest` stays green between every checkpoint. Three minor fold-ins below would tighten it. None are dispatch-blocking.

Verified spot-checks that earned the "as-is path" verdict:

- D2 §7 wire encoding: architecture.md L267–270 ("Inside Parquet, the `metadata` column holds JSON-encoded strings in a `pl.Utf8` column") — present.
- D2 §9 ProviderInfo identifying + capability fields: architecture.md L431–433 — present.
- Schema instances live at `src/rivretrieve/_internal/catalogues/schemas.py:35,53,72,89` as `CatalogueSchema(...)` runtime objects — confirmed by direct read.
- `src/rivretrieve/__init__.py` re-exports only `ProviderHandle`, `product_info`, `products`, `provider`, `provider_info`, `providers`, `stations`, `__version__`. None of the four names are reachable from the package root — T120 absence list stays intact.
- Full call-site set (9 files): plan covers every one.
- D3 disposition is stated ("update in place with a resolved note") — step 11.

## Major findings

None.

## Minor findings

### M-1. PEP 695 `type X = Y` form is the established schemas.py convention; plan pins to `TypeAlias = …` without rationale (§3, §6 step 7).

Plan §3 says: *"Use `typing.TypeAlias` unless `ty` rejects it. The project already uses Python 3.13 syntax elsewhere (`type CatalogueDtype = …`), but the step is explicitly pinned to the `TypeAlias = pl.DataFrame` form."*

The very file being edited — `src/rivretrieve/_internal/catalogues/schemas.py:13` — uses `type CatalogueDtype = pl.DataType | type[pl.DataType]`. Introducing a *different* alias-declaration style in the same module is a gratuitous style split.

**Fold-in:** Use `type StationCatalog = pl.DataFrame` (and three siblings) to match the existing convention in the same file. Keep the "fall back to `TypeAlias` if `ty` rejects PEP 695 with a runtime `pl.DataFrame` RHS" escape hatch — but the default should be the project's existing pattern, not a new one.

### M-2. Transient unused-import window in `discovery.py` between steps 5 and 8 is not stated (§6 steps 5, 8).

Step 5 replaces every runtime body reference in `discovery.py` to `*_SCHEMA` names and explicitly *keeps* annotations at `CatalogResult[pl.DataFrame]`. That leaves the existing `ProductCatalog`, `ProviderInfoCatalog`, `StationCatalog` imports at the top of the file unused from step 5 → step 7 (when those names become TypeAliases) → step 8 (when they are re-consumed as annotations).

If the executor runs `uv run ruff check` (or `--fix`) at any intermediate checkpoint, the import gets stripped, then must be re-added in step 8. If the executor relies on `ruff --fix` from a personal editor save, an intermediate state is left mid-rename.

**Fold-in:** Add one line to step 5: *"Leave the existing `ProductCatalog`/`ProviderInfoCatalog`/`StationCatalog` imports in place — they will be reused as TypeAlias references at step 8. Do not run `ruff check --fix` before step 8."* This is a one-line clarification, not a scope change.

### M-3. §9 stopping conditions omit `*_SCHEMA` name-collision check (§9).

The plan introduces four module-level constants — `STATION_CATALOG_SCHEMA`, `PRODUCT_CATALOG_SCHEMA`, `STATION_PRODUCT_CATALOG_SCHEMA`, `PROVIDER_INFO_CATALOG_SCHEMA`. Adversarial grep confirms no current `*_SCHEMA` identifier exists in the repo. But the stopping-condition list does not encode this check, so if the executor lands in a state where some other future name collides, the failure mode is not pinned.

**Fold-in:** Append to §9: *"Stop if any of the four `*_SCHEMA` identifiers collide with a pre-existing binding in `src/rivretrieve/_internal/catalogues/schemas.py` or any file importing it."*

## Nits

- §6 step 11 says to update D3 "in place with a 'resolved at M3 step 01' note" but doesn't pin exact wording. The D3 entry is dense (it cites tracker lines, the M2 step 06 critique §L11, and the M2 REPORT §6); a one-line resolution note appended below the existing body would suffice, but the plan should say which subsection (the "How to apply going forward" block) the resolution lands under.
- §7 Q5 hedges on `uv run ty check`; this is correct, but it would be cheaper to recommend a sub-second probe — `uv run ty check src/rivretrieve/_internal/catalogues/schemas.py` — at step 1 (right after the `*_SCHEMA` compatibility bindings exist but before any propagation) to fail fast.
- §6 step 10 lists `provider_module.py`, `registry.py`, `catalogue_reader.py`, and `tests/_stubs/stub_provider.py` as "candidate" cleanup files. Recommendation is "do not churn unless `ty` requires it" — good — but the plan should also say what to do if `ty` *does* require churn: namely, narrow only the file(s) ty complains about, not all four. Without that fence, "optional cleanup" reads as license to do internal annotation churn that exceeds the step's stated scope.

## Lens-by-lens summary

- **L1 (scope completeness):** ✅ — All 9 referencing files (4 src, 4 test, 1 `__init__.py` literal-string list) covered. `tests/test_internal_provider_info.py` correctly excluded (no references).
- **L2 (scope over-reach):** ✅ — No `ch_foen`, no `architecture.md`, no `product_dictionary.md`, no observation annotations, no `CatalogueReader` behavior change, no public re-export.
- **L3 (citation verification):** ✅ — Spot-checked: D2 §7 + §9 confirmed at HEAD (commit `4f68b68`); M2 REPORT §6 D3-2 quoted accurately; schemas.py line numbers (35/53/72/89) confirmed.
- **L4 (test coverage adequacy):** ✅ — Names T119, T120, `ty check`, full 335-test suite. No new tests proposed (correct default). Alias-identity test deliberately deferred unless reviewer demands.
- **L5 (error handling):** ✅ — Plan §4 explicitly says "None new" with rationale that no fatal-raise paths and no Issue-routed paths are touched. No scope creep.
- **L6 (open question rigor):** ✅ — All 8 questions have evidence-backed recommendations. Q1 cites grep'd line numbers; Q3 cites `__init__.py` contents; Q6 walks the staged-binding reasoning.
- **L7 (deferral hygiene):** ✅ — Deferrals are real (ch_foen content, broader annotation churn). No suspicious deferrals.
- **L8 (implementation order):** ✅ with one tightening (M-2). Walked steps 1→9 mentally:
  - After (1), `*_SCHEMA` canonicals + old names as compat aliases → both work, suite green.
  - After (2)–(5), each internal caller flips to `*_SCHEMA` while old names still resolve → suite green at each pytest checkpoint.
  - After (6), tests use `*_SCHEMA` → suite green.
  - After (7), old names become `TypeAlias = pl.DataFrame` → any unmigrated `X.polars_schema` access would now fail. Steps 2–6 covered every site (verified by my grep).
  - After (8)–(9), annotations narrowed. T117 inspects only `ProviderHandle` Protocol annotation strings (`_assert_signature` reads `inspect.get_annotations(method)` on the *Protocol*, not on `_ProviderHandle`), so `_ProviderHandle.products` keeping `CatalogResult[pl.DataFrame]` does not break T117. Confirmed by reading `tests/test_provider_handle.py:168-183`.
- **L9 (stopping conditions):** ✅ with one tightening (M-3). Covers partial rename, T119/T120 surface attempts, D2 gate, and intermediate ordering, but misses explicit `*_SCHEMA` name-collision pin.
- **L10 (architecture alignment):** ✅ — Four TypeAliases use exactly the names architecture §9 cites (`ProductCatalog`, `StationCatalog`, `StationProductCatalog`). `ProviderInfoCatalog` row encoding (eight columns) is consistent with §9's identifying-plus-capability field list, codified by D2.
- **L11 (speculative abstraction check):** ✅ — No parallel reader, no base class, no "for later" hook. Rename + four aliases + one D3 doc edit; nothing else.
- **L_two_channel (two-channel exception hygiene):** ✅ — `validate_catalogue`, `CatalogueReader`, `provider_info.from_row` keep their existing fatal-vs-`on_issue` shape. The `*_SCHEMA` substitution swaps a binding, not a control-flow path.
- **L_inherited_patterns (M2 pattern compliance):** ✅ — `CatalogueReader` remains the single delegation site; no public type promotion (T119/T120 absence list intact for the four names); `ProviderInfo` row contract preserved (schema.name strings and `*_SCHEMA.columns` unchanged at line-level use in `provider_info.py:31, 40, 48`).
- **L_legacy_citation_fidelity:** N/A — plan introduces no `git show origin/switzerland:` references. (Spot-check confirms.)
- **L_vocabulary_boundary:** N/A — no product IDs touched; product dictionary unmodified.
- **L_offline_invariant:** ✅ — TypeAliases live in `_internal/catalogues/schemas.py`; nothing in the plan re-exports them or pulls a provider module at import time. `__init__.py` is untouched.
- **L_rename_atomicity (step-specific):** ✅ — Plan's staged order anticipates each well-known rename trap:
  - dangling imports → step 5–6 migrate users before step 7 flips the binding kind;
  - typo'd new names passing tests because both coexist → mitigated because step 7 *removes* the old runtime binding, surfacing typos at suite run;
  - string-name assertions → §5 verifies by grep that no test pins `__name__` or `repr`; `CatalogueSchema.name` strings deliberately preserved;
  - editor auto-imports → not perfectly defended, but the staged plan localizes the risk.

## Adversarial probes attempted

1. Grep'd `src/ tests/` for `\b(StationCatalog|ProductCatalog|StationProductCatalog|ProviderInfoCatalog)\b` — 9 files, 100+ occurrences. Cross-checked against the plan's §6 file list: every referencing file is covered. No orphans.
2. Inspected the four assignments in `src/rivretrieve/_internal/catalogues/schemas.py` — confirmed they are `CatalogueSchema(...)` runtime instances at lines 35, 53, 72, 89. Plan §3 / §7-Q1 claim verified.
3. Read `src/rivretrieve/__init__.py` (10 lines) — confirmed the four names are not re-exported. T120's absence claim is consistent.
4. Read `tests/test_package.py:11-59` — T119's positive set and T120's negative-list both include exactly the names the plan claims they include. The four names are absent-list members; plan's "no change to T119/T120" claim holds.
5. Read architecture.md §7 (L267-270) and §9 (L431-433) at HEAD — D2 wire encoding and ProviderInfo identifying+capability fields are present. `git log --oneline architecture.md` shows commit `4f68b68` ("Architecture addenda for D2: codify M1 implementation contracts") is on the current branch, confirming D2 landed.
6. Read `tests/test_provider_handle.py:92-183` (T117 body) — `_assert_signature` only introspects `ProviderHandle` Protocol methods via `inspect.get_annotations(method)`. Does NOT inspect `_ProviderHandle`. Therefore the planned divergence between Protocol annotation (`CatalogResult[ProductCatalog]`) and concrete dataclass annotation (`CatalogResult[pl.DataFrame]`) does not break T117. Plan's omission of `_ProviderHandle.products/stations/station_products` annotations from the narrowing list is therefore correct, not a gap.
7. Grep'd for the literal strings `"StationCatalog"`, `"ProductCatalog"`, `"StationProductCatalog"`, `"ProviderInfoCatalog"` — only hits: (a) the `name=` fields in schemas.py (preserved by plan), (b) the T120 deferred-names list (literal strings, no binding). No test pins `CatalogueSchema` instance string identity. Plan §5's grep claim corroborated.
8. Grep'd for `schema.name`, `catalog.name` accesses — all hits are inside `validate_catalogue` body and `provider_info.py:48`. `*_SCHEMA.name` substitution preserves these since `CatalogueSchema.name` strings stay unchanged. No two-channel exception text shifts.
9. Verified the PEP 695 convention in the repo: `type CatalogueDtype = ...` at schemas.py:13 is the only `type X = Y` form; primitives.py uses bare `X = Literal[...]`. Plan picks a third pattern (`X: TypeAlias = …`) without justification. This grounds M-1.
10. Counted M2-close test total at REPORT.md §9 ("335 passing") — matches plan §5's claim.
11. Searched for any place that does `isinstance(x, StationCatalog)` or `issubclass(StationCatalog, ...)` — none found. The instance-vs-class flip at step 7 has no runtime-isinstance users.

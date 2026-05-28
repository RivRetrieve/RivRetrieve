# Discoveries

Cross-milestone notes that future planners, reviewers, and executors should know but that are not part of architecture.md or the milestone tracker.

## D1 — Per-commit version bump touches `src/rivretrieve/__init__.py`

**Found during:** M1 step 01-foundations executor handoff.

**The fact:** `AGENTS.md` §3 requires `uv run bump-my-version bump patch` before every commit. The `[[tool.bumpversion.files]]` configuration in `pyproject.toml` updates two files in lockstep:

- `pyproject.toml` `version = "..."`
- `src/rivretrieve/__init__.py` `__version__ = "..."`

This means **every step commit in this project mutates `src/rivretrieve/__init__.py`**, even when the step's plan explicitly forbids editing that file for API-surface reasons.

**Why it matters:** Step plans that include a "no `__init__.py` edits" scope guard (M1 step 01 had one; future M1 steps may want one) must distinguish between:

- API-shape edits (forbidden until the step that owns the public surface — M1 step 03)
- Version-literal bumps (mandatory per commit, do not count as scope drift)

**How to apply going forward:**

1. **Step planners:** When writing a "no `__init__.py` edits" guard, phrase it as "no API-shape edits to `__init__.py` (no symbol additions, no re-exports, no import changes)." Do not phrase it as a blanket file-modification ban. Explicitly mention that the per-commit version bump is exempt.

2. **Step reviewers:** Do not flag the version-literal mutation as scope drift on a step that disclaims API-shape edits. Do flag it as drift on a step that performs ANY other mutation to `__init__.py`.

3. **Step executors:** Run `uv run bump-my-version bump patch` after all other staged changes pass `ruff format`, `ruff check --fix`, `ty check`, and `pytest`, and before committing. Tag with `v$(uv run bump-my-version show current_version)` after commit.

4. **The negative-control test that the public surface is unchanged** (M1 step 01 T17, and the offline-import test M1 step 03 will own) must assert *symbol absence* (`providers`, `provider`, `provider_info`, internal type leakage), not file-content equality. The current T17 already does this correctly.

**Architecture status:** Not an architecture.md contradiction. This is project commit policy interacting with step scope guards. Resolved at orchestrator level for M1 step 01; recorded here so subsequent step planners encode the exemption explicitly rather than re-deriving it.

**Forward implication:** Each M1 step lands its own patch bump. This branch already had a `v0.1.3` tag on commit `6488f6e` while configured files still said `0.1.2`, so M1 step 01 resolved to the next unoccupied patch tag, `v0.1.4`. Future step planners should inspect existing tags before assuming the next version from file literals alone. The M1 closing version is therefore not a planner decision — it falls out of the step count and pre-existing tag inventory. Note for the M5 conformance milestone: any version-tag inventory should expect step-granular tags, not just milestone-granular tags.

## D2 — Queued architecture.md addenda from M1 implementation, due before M3 dispatch

**Found during:** M1 post-milestone reconciliation (REPORT §7.2 and §7.3).

**The fact:** M1 implementation pinned two load-bearing details that architecture.md is currently *silent* on (not contradicted — silent). Both first bind at M3 when `ch_foen` generates real packaged catalogue artifacts and registers a real `ProviderInfo`.

1. **Packaged Parquet `metadata` column wire encoding.** Architecture.md §7 names "plain dictionaries at public table boundaries" but does not specify how nested provider metadata is encoded inside packaged Parquet artifacts. M1 step 02 selected `pl.Utf8` columns holding JSON-encoded strings after the reviewer caught that `pl.Object` does not round-trip through Parquet. This is now the de-facto contract for all four catalogue schemas (`StationCatalog`, `ProductCatalog`, `StationProductCatalog`, `ProviderInfoCatalog`).

2. **`ProviderInfoCatalog` column set beyond architecture.md's capability flags.** Architecture.md §9 (lines 432–433) names the three `live_*` flags and `bulk_observations` capability but is silent on `name` and `catalogue_version` columns. M1 step 02 Q5 pinned the full column set `{provider_id, name, live_stations, live_products, live_station_products, bulk_observations, catalogue_version, metadata}`. M2's singular `ProviderInfo` type must be isomorphic to this row contract.

**Why it matters:** Both ship in M1 commits and are now load-bearing for any subsequent provider port. If a later provider (or a third-party provider port in V2) reads architecture.md alone, it has no contract to follow for either point. M3's `ch_foen` `generate_catalogue.py` will produce these artifacts; without an arch lock, future providers could legitimately diverge.

**How to apply going forward:**

1. **Before M3 dispatch:** The project coordinator queues a small architecture.md addendum touching §7 (JSON-in-Parquet encoding) and §9 (the two additional `ProviderInfo` columns). Neither addendum changes M1/M2 behavior — they codify existing implementation.

2. **M2 planner brief:** Does NOT need to wait on the addenda. M2 lands the singular `ProviderInfo` type, which is internal and isomorphic to the catalogue row. The M2 planner cites M1 step 02 §3 lines 124–139 as the row contract source until the arch addendum lands.

3. **M2 reviewer brief:** No new lens needed for D2; the existing L1 architecture-coverage lens will continue to flag any §7 or §9 silence that bites a later milestone.

4. **M3 planner brief:** MUST verify the §7 and §9 addenda exist before scoping `generate_catalogue.py`. If not, the M3 planner stops and surfaces — this is exactly the architecture-update-before-next-milestone gate the project workflow specifies.

**Architecture status:** Two arch addenda queued, neither blocking M2. Tracked here so they do not drift between now (M1 close) and M3 start.

**Forward implication:** The two-channel exception design (M1 step 01) and the catalogue schema representation (M1 step 02) are NOT in this queued-addenda list because they are internal implementation patterns, not public contract gaps — architecture.md does not need to know how `apply_on_issue` is structured, only that fatal contract failures raise regardless of `on_issue`. The §7 and §9 items are different: they describe public artifact shape that downstream providers will read.

## D3 — `CatalogResult` element-type annotation: tracker shorthand vs. implementation

**Found during:** M2 step 06 planning (plan §3 Q3) and review (critique §L11). Recorded post-M2 with the milestone REPORT.

**The fact:** The milestone tracker spells the public catalogue method return types as parameterized on the named schema:

- `def stations(...) -> CatalogResult[StationCatalog]`
- `def products(...) -> CatalogResult[ProductCatalog]`
- `def product_info(...) -> CatalogResult[ProductCatalog]`
- `ProviderHandle.station_products(...) -> CatalogResult[StationProductCatalog]`

(tracker §3 L117, L121–123; same shape for the per-handle siblings.)

The implementation since M1 step 03 (private `_ProviderHandle.products`/`stations`/`station_products`) and continuing through M2 step 06's public Protocol uses `CatalogResult[pl.DataFrame]`. The reason is that `StationCatalog`, `ProductCatalog`, `StationProductCatalog`, and `ProviderInfoCatalog` are M1 step 02 **runtime `CatalogueSchema` instances** (frozen dataclasses describing column shape), not Python type aliases. Subscripting a runtime instance is meaningless to the type system, so the annotation reads `CatalogResult[pl.DataFrame]` to satisfy `ty` while behavior is unchanged.

**Why it matters:** M2 step 06 T117 introspects the public Protocol signatures and asserts they match the implementation. The reviewer surfaced this as non-blocking but noted that the tracker shorthand and the runtime annotation are *not* the same artifact — a third-party provider port reading the tracker alone could write `CatalogResult[StationCatalog]` on its own provider module and produce a confusing static-typing experience.

**How to apply going forward:**

Resolved at M3 step 01: path (b) was chosen. `StationCatalog`, `ProductCatalog`, `StationProductCatalog`, and `ProviderInfoCatalog` are now PEP 695 type aliases for `pl.DataFrame`; the runtime `CatalogueSchema` instances were renamed to `STATION_CATALOG_SCHEMA`, `PRODUCT_CATALOG_SCHEMA`, `STATION_PRODUCT_CATALOG_SCHEMA`, and `PROVIDER_INFO_CATALOG_SCHEMA`. The aliases are not exported from the package root, and T119/T120 remain unchanged.

1. **Coordinator decision needed before M3 step 01 dispatch.** Two paths reconcile this:
   - **(a) Tracker addendum.** Note that `StationCatalog` / `ProductCatalog` / `StationProductCatalog` / `ProviderInfoCatalog` are runtime schema instances. The public method annotations read `CatalogResult[pl.DataFrame]`. This is the cheapest path and matches existing behavior.
   - **(b) `TypeAlias` introduction.** Introduce `StationCatalog: TypeAlias = pl.DataFrame` (and siblings) so the tracker shorthand becomes meaningful at the type system level too. The runtime `CatalogueSchema` instances would need renaming (e.g., `STATION_CATALOG_SCHEMA`). Heavier touch; lands in M3 if chosen.

2. **M3 planner brief:** Cite this discovery and pin the chosen path before scoping `ch_foen` provider module annotations. If (b) is chosen, M3 owns the rename.

3. **M3 reviewer brief:** New lens — verify `ch_foen.observations` and the three catalogue functions consume whichever convention the coordinator pins.

**Architecture status:** Not an architecture.md contradiction. The tracker shorthand vs. the implementation annotation are reconciled by the chosen path above; today (M2 close) the implementation is canonical and T117 enforces it.

**Forward implication:** Independent of (a) vs (b), public method return values are Polars `DataFrame`s wrapped in a `CatalogResult` envelope. The choice affects only the type annotation surface, not runtime behavior.

## D4 — Protocol introspection relies on `inspect.signature`, not `__protocol_attrs__`

**Found during:** M2 step 06 plan §3 Q11.

**The fact:** M2 step 06 T116 (Protocol method-name surface) and T117 (Protocol method-signature shape) introspect the public `ProviderHandle` Protocol using `inspect.getmembers` + `inspect.signature`. The planner explicitly rejected `typing.Protocol.__protocol_attrs__` because that name is private CPython API and unstable across Python versions.

**Why it matters:** If a future Python upgrade changes the layout of `typing.Protocol` (member visibility, ordering, default-value semantics in Protocol declarations), the T117 signature-equality check can fail without a behavior change. The failure mode is loud (pytest red) so the consequence is bounded, but the test author should know which CPython hooks they are *not* relying on.

**How to apply going forward:**

1. **Future Python upgrade triage:** If T117 ever fails, first check whether `inspect.signature` semantics changed for kw-only markers or default values on Protocol methods. The Protocol declaration itself uses standard `typing.Protocol` + `typing.runtime_checkable`; the test reads it through public `inspect` surface only.

2. **No action required pre-M3.** This is a forward-looking discovery; the load-bearing decision (use public introspection) is already in the tree.

**Architecture status:** Not a contradiction. A note for future maintainers.

## D5 — Public `__all__` deferred; negative control reads `module_defined_names`

**Found during:** M2 step 06 plan §3 Q11 / §7 (out-of-scope guards).

**The fact:** `src/rivretrieve/__init__.py` does not declare `__all__`. The public-surface negative control (`tests/test_package.py::T22`) enumerates `module_defined_names` — names attached to the module object — and asserts that set equals the seven public symbols `{ProviderHandle, provider, providers, provider_info, stations, products, product_info}` plus `__version__`.

This is a working contract: any new import statement that lands a name on the module object will fail T22 immediately. But it is weaker than an explicit `__all__` because `from rivretrieve import *` resolves via Python's default rules (everything not starting with underscore), which could in principle include type-only imports added for annotation purposes.

**Why it matters:** As M3 introduces real provider modules and M4 introduces top-level `rr.observations(...)`, the import graph at `__init__.py` will grow. The risk is silent leakage of internal types into `from rivretrieve import *` semantics, which T22 would not catch (T22 reads module attributes, not `__all__` semantics).

**How to apply going forward:**

1. **Post-M5 or post-M3 cleanup candidate.** Introduce an explicit `__all__` listing the public surface. Extend T22 to assert `__all__` equals the present-set and that `from rivretrieve import *` lands exactly those names in a subprocess.

2. **No M3 / M4 / M5 dispatch is blocked.** The current T22 / T23 negative-control pair remains meaningful; the gap is between "names attached to module" and "names that `import *` would export."

**Architecture status:** Not a contradiction. Project hygiene item for V1 closeout.

## D6 — Provider subpackage path shadowed public callable `rr.providers`.

**Found during:** M3 step 02 6A execution.

**What:** Original M3 step 02 plan placed ch_foen at `src/rivretrieve/providers/ch_foen/`. Python import mechanics bind `rivretrieve.providers` to the subpackage module on first import, overwriting the `rivretrieve._internal.discovery.providers` callable re-exported at `src/rivretrieve/__init__.py:5`. Subsequent `rr.providers()` calls raised `TypeError: 'module' object is not callable`. Executor blocked at 6A.

**Which section it contradicts:** Not an architecture.md contradiction; a contradiction between the M3 orchestrator-prompt-suggested path and the M1/M2-established public callable surface.

**Why it matters:** Any provider subpackage colliding with a public callable name will exhibit this. Future provider ports (M6+ if more providers come) face the same trap.

**What we did:** Relocated to `src/rivretrieve/_internal/providers/ch_foen/`. The public surface (`rr.providers()`) is unaffected. Lazy registration via `from rivretrieve._internal.providers.ch_foen import module as ch_foen_module` preserves the offline-import invariant. Plan amended in place; executor resumes at 6A.

**What the coordinator should review:** Whether to amend the orchestrator prompt's §"What M3 ships" path snippet for future milestones, and whether to add an "import-time-attribute-shadowing" probe to the reviewer's L_offline_invariant or L_inherited_patterns lens going forward.

**Resolution:** Implemented in M3 step 02.

## D7 — Pydantic extra='allow' constructor kwargs trip ty; use model_validate(dict) for extras assertions in tests.

**Found during:** M3 step 02 6A execution.

**What:** M3 step 02 metadata models declare `extra="allow"` so Existenz.ch source fields aren't discarded on ingest. Tests that exercised extras via constructor kwargs (`Model(source_specific=...)`) failed ty with `unknown-argument` because Pydantic's `__init__` signature only declares known fields; runtime `extra="allow"` is invisible to the type checker.

**Why it matters:** Any future Pydantic model with `extra="allow"` will hit this if tested via constructor kwargs. Affects M4 if observation models also need `extra="allow"`.

**What we did:** Split the metadata tests so declared-fields use constructor kwargs, which type-checks cleanly, and the extras-allow assertion uses `Model.model_validate({...})` with `model_extra` introspection. Plan §5.1 form adjustment within executor authority; intent unchanged.

**What the coordinator should review:** Add an "extras-allow - ty interaction" probe to the reviewer's L_protocol_conformance or a new test-shape lens for M4 and any future provider port adding Pydantic models with extras.

**Resolution:** Implemented in M3 step 02.

## D9 — isinstance(x, Mapping) erases generics under ty; use dict for JSON-loaded data.

**Found during:** M3 step 02 6B execution.

**What:** `isinstance(x, Mapping)` narrows to a bare `Mapping` whose key/value types ty infers as `Never`. Subsequent `.get(...)` calls fail `invalid-argument-type`. The runtime check is correct; only the type narrowing is over-conservative.

**Why it matters:** Any provider port that walks `json.loads`-produced data with `isinstance` checks against `Mapping` / `Sequence` will hit this. Affects future provider ports (M4 observation parsing, M6+ new providers).

**What we did:** Use `isinstance(x, dict)` / `isinstance(x, list)` for JSON-loaded data, which is always concretely typed by Python's json module. The abstract ABCs are not needed at the parser boundary.

**What the coordinator should review:** Optional lint rule (or convention note in docs/discoveries.md) that `isinstance` checks against bare ABCs are discouraged inside provider code unless the abstract polymorphism is actually needed. For ingest code that takes `json.loads` output, `dict` / `list` is the right check.

**Resolution:** Implemented in M3 step 02.

## D10 — Legacy `origin/switzerland` ref lives on the upstream RivRetrieve-Python clone, not on the target repo.

**Found during:** M4 step 01 execution.

**What:** The M4 orchestrator-prompt section "CONTEXT" instructs planners and reviewers to consult the unmerged ch_foen port source via `git show origin/switzerland:<path>` "of the same repo." In practice:

- `/Users/nicolaslazaro/Desktop/work/RivRetrieve` (target repo) has only `origin/HEAD -> origin/main`, `origin/main`, and `origin/docs/provider-redesign-proposal`. `git rev-parse origin/switzerland` fails with `unknown revision`.
- `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python` (the upstream Python project clone) DOES carry `origin/switzerland` at `cd9b0305e4b65dd23bb3cfb541e9a6ee53ff77fd` — the same `cd9b030 "Restore public Switzerland token"` cited in M3 REPORT §7.2.

So every legacy `git show origin/switzerland HEAD:<path>` command needs to be issued from the legacy checkout's working directory, not the target repo's.

**Which section it contradicts:** Not an architecture.md contradiction. A wording bug in the orchestrator-prompt "CONTEXT" section that misled the literal reading of "the same repo." The M4 step 01 reviewer worked around this by citing the legacy filesystem path explicitly in the critique; the executor confirmed `cd9b030` matched after running `git log origin/switzerland --oneline -1` inside the legacy clone.

**Why it matters:** Every remaining M4 step's planner, reviewer, and executor inherits the "git show origin/switzerland HEAD:<path>" instruction. If a planner literally pastes that command into a target-repo shell, it fails silently in the sense that the planner then either fabricates a citation, falls back to the local source-of-truth-by-prose, or stalls. The fix is purely operational: pin the legacy checkout path in every M4 step brief from step 02 onward.

The same pattern will affect any future provider port that consults a sibling legacy ref (e.g., `origin/<country>` branches on `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python`).

**How to apply going forward:**

1. **M4 step planners (step 02 onward):** When consulting legacy SwitzerlandFetcher, observation tests, or the three fixture CSVs, issue `git -C /Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python show origin/switzerland:<path>` or `cd` into that directory first. Cite the absolute path the read came from in plan §3 / §5 so the reviewer can re-run verbatim.

2. **M4 step reviewers (step 02 onward):** When verifying `L_legacy_citation_fidelity`, run the citation from the legacy checkout directory. Treat a planner citation that does not name the legacy-checkout path as a citation-fidelity Minor finding (the planner is hiding which working directory they assumed); upgrade to Major only if the cited line is actually wrong.

3. **M4 step executors:** Default to the legacy checkout for token probes and fixture extraction. Confirm `git log origin/switzerland --oneline -1` returns `cd9b030 Restore public Switzerland token` BEFORE any token-related verification. If the legacy checkout has drifted (e.g., a future `git fetch` advances `origin/switzerland`), pin to `cd9b030` explicitly with `git show cd9b030:<path>`.

4. **Reviewer lens phrasing:** `L_legacy_citation_fidelity` should be reworded across remaining M4 briefs to read "run `git show` against `cd9b030` from the legacy checkout at `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve-Python`" instead of "run git show against origin/switzerland HEAD (not just `origin/switzerland`, which may have drifted)." The drift concern remains valid — pinning to `cd9b030` addresses it directly.

**Architecture status:** Not a contradiction. An operational correction to the M4 orchestrator-prompt working method.

**Forward implication:** When the coordinator scopes M5 or any future provider port that consults a sibling legacy branch, the briefs should name the legacy-checkout absolute path inline rather than relying on the reader to figure out "the same repo" pragma. If a future provider's legacy lives elsewhere (e.g., the R lineage at `/Users/nicolaslazaro/Desktop/thirdparty/RivRetrieve`), the same rule applies: cite the working directory.

**Resolution:** Operationally resolved at M4 step 01 (executor used the legacy checkout per critique citation, confirmed `cd9b030`). Forward step briefs pinned in this entry.

## D8 — M1/M2 catalogue contracts use asymmetric encodings; generator-side serialization obligations weren't exercised before M3 step 02.

**Found during:** M3 step 02 6B execution.

**What:** `PROVIDER_INFO_CATALOG_SCHEMA`'s `metadata` column is `pl.Utf8` per arch.md §7 (D2 addendum). The loader canonicalizes JSON-compatible metadata into a JSON string. The generator side of the round-trip (dict -> JSON-string before parquet/write validation) was not exercised in M1 (loader tested with hand-built parquet) or M2 (no provider generated artifacts). M3 step 02 is the first generator-side exercise; the obligation surfaced only at typed-frame construction time inside the generator's validation step.

**Why it matters:** Any future provider port that generates packaged artifacts will hit the same trap if their generator forgets to serialize. The artifact loader's normalization is invisible from the generator side.

**What we did:** Generator now uses `json.dumps(metadata, sort_keys=True)` before typed-frame construction.

**What the coordinator should review:** Add an "M1/M2 contract round-trip" probe to the reviewer's lens inventory for M4 and future provider ports. The probe: for every catalogue/result column with an asymmetric encoding (anything where loader semantics differ from raw parquet type), verify the GENERATOR side serializes correctly, not just the LOADER side deserializes. Candidate columns to audit proactively in M4: anything in observation results with JSON-encoded annotations, timestamp columns with timezone normalization, etc.

**Resolution:** Implemented in M3 step 02.

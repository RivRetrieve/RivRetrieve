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

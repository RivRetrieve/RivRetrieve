# M5 - Map and V1 Closeout - Milestone Report

**Status:** closed. This is the FINAL milestone; with it, V1 is feature-complete.
**Range:** `5d28bc8` (M5 step 01) ... `705444d` (M5 step 02 closeout), branch `docs/provider-redesign-proposal`, not pushed.
**Tracker entry:** [docs/milestone-tracker.md §3 "M5 - Map and V1 closeout"](../../milestone-tracker.md).

M5 ships the final V1 public method, `rr.map_stations(...)`, as an offline view over the packaged station catalogue behind an optional `map` extra, and closes V1 with a documented architecture-conformance checklist mapping `architecture.md` §0-§18 to real tests and §19 to explicit deferral. No architecture contradictions surfaced; no §0-§18 commitment was found unimplemented.

## 1. Steps executed

| Step | Commit | Tag | Tests after (collected / passed / skipped) | Net new |
|------|--------|-----|---------------------------------------------|---------|
| 01-map-stations-and-optional-extra | `5d28bc8` | `v0.1.23` | 439 / 437 / 2 | +13 collected (+11 passing offline, +2 folium-gated) |
| 02-conformance-and-v1-closeout | `705444d` | `v0.1.24` | 442 / 440 / 2 | +3 collected (the three §19 absence controls) |

The 2 persistent skips are the `folium`-gated real-backend map render tests; they skip when the optional `map` extra is absent (the default offline environment) and run when `folium` is installed. Each step ran the full `uv run ruff format` / `ruff check --fix` / `ty check` / `pytest` sweep green, then patch-bumped and tagged per D1.

## 2. Public API shipped vs. tracker

M5 shipped the tracker-owned final public callable:

```python
rr.map_stations(
    *,
    providers: str | Sequence[str] | None = None,
    country: str | Sequence[str] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> object
```

It is implemented in `src/rivretrieve/_internal/discovery.py` and re-exported from `src/rivretrieve/__init__.py`. It reads only the packaged station catalogue (offline), applies providers/country/bbox filters over existing catalogue columns (`provider_id`, `country`, `latitude`/`longitude`), and returns a backend-native `folium.Map`. `bbox` uses `(min_lon, min_lat, max_lon, max_lat)`, inclusive bounds. It takes no `on_issue` parameter and never touches provider APIs, the observation client, or the Influx token.

`map_stations` is the **only** public-surface change in all of M5. T119 (`test_init_public_surface_exports_m2_provider_handle_surface`) now pins the package root as `{ProviderHandle, map_stations, observations, product_info, products, provider, provider_info, providers, stations}`. T120 (`test_deferred_public_names_remain_absent_after_provider_handle_promotion`) removes `map_stations` from the forbidden list and adds `StationMap` and `MissingOptionalDependencyError`; all M2/M4 internal types remain forbidden.

`rr.stations()` was deliberately left unchanged (no filters retrofitted); `map_stations` owns map-specific filtering.

## 3. Internal types introduced vs. tracker

| Area | Internal symbols |
|---|---|
| Map view | `StationMap` (frozen-dataclass thin builder over a filtered `pl.DataFrame`; stays internal, not promoted to the root), `_filter_stations(...) -> pl.DataFrame` (backend-free pure filter seam), lazy `folium` backend loader |
| Errors | `MissingOptionalDependencyError(FatalContractError)` (fatal, message names `folium` and `pip install rivretrieve[map]`; raised regardless of policy, never routed through `apply_on_issue`) |

`StationMap` is the tracker-named internal type for this milestone. The no-public-type-promotion pattern holds: neither `StationMap` nor `MissingOptionalDependencyError` is exported from the root (verified by T120 and direct introspection).

## 4. Runtime dependencies added

The map backend ships as an **optional extra**, not a hard runtime dependency:

```toml
[project.optional-dependencies]
map = ["folium"]
```

Core install deps are unchanged (`polars`, `pandas`, `pydantic`, `requests`, `pyarrow>=24.0.0`). `folium` was chosen over the tracker's `leafmap` candidate because the deliverable is a packaged station-marker view, not a geospatial workbench, and `leafmap` pulls a broad notebook/geospatial stack that conflicts with the lean-core-install constraint. The optional-extra-with-fatal-error structure is the coordinator-settled design; `import rivretrieve` does not import `folium`/`leafmap`/`ipyleaflet` (verified independently and by the offline-import subprocess test).

## 5. Test count delta and negative-control inventory

End state: **442 collected, 440 passed, 2 skipped** offline. M5 moved from M4's 426 passing to 437 passing after step 01 to 440 passing after step 02.

Negative controls landed/expanded in M5:

| Control | Status |
|---|---|
| T119 public surface | Expanded with `map_stations` and passing |
| T120 forbidden surface | `map_stations` removed; `StationMap` + `MissingOptionalDependencyError` added; M2/M4 internals still absent; passing |
| Offline import with map extra absent | `import rivretrieve` imports no map backend / provider runtime / generator; passing |
| Missing-backend fatal raise | `MissingOptionalDependencyError` (a `FatalContractError`), message names extra+backend, no `IssuePolicyError` in chain; passing |
| Filter correctness | providers / country / bbox assert on `_filter_stations` over the real 246-row packaged frame; Brugg-anchored bbox catches lat/lon transposition; passing |
| Empty filter result | valid zero-match filter returns an empty map, not a raise; passing |
| Packaged-data-only / no-token | observation client, default transport, and token path proven untouched by `map_stations`; passing |
| Nullable columns | render does not require `elevation_m` / `drainage_area_km2`; passing (folium-gated) |
| §19 wide-form helper absence | `test_v1_deferred_wide_form_helpers_remain_absent`; passing |
| §19 derived-product absence | `test_v1_products_are_not_rivretrieve_derived`; passing |
| §19 vocabulary-scope absence | `test_v1_observed_property_vocabulary_remains_river_gauge_scope`; passing |

## 6. Discoveries logged

No D11+ discovery. M5 surfaced no architecture contradiction. A "V1 Closeout Note" was appended to `docs/discoveries.md` recording the status of the standing review items:

- **D5** (explicit `__all__`) remains a post-V1 hygiene candidate; T119/T120 still guard accidental public expansion.
- **D6** (provider path shadowing) remains resolved by keeping provider packages under `rivretrieve._internal.providers`; the new `map_stations` callable was placed to avoid the same trap.
- **D7 / D9** did not fire in M4 or M5 map work; keep them as provider-code review probes, not permanent architecture lenses.

## 7. Surprises and notes

- **`rr.stations()` has no filters today.** The tracker's "same basic filters already supported by `rr.stations()` where implemented" resolves to *none implemented*, while arch §3 commits `map_stations` to providers/country/bbox. Resolution: all three filters are satisfiable from existing catalogue columns with **no schema change**, so they were implemented in `map_stations` only, with `rr.stations()` left untouched. No escalation was needed.
- **`leafmap` vs `folium`.** The tracker named `leafmap` as a candidate; the planner chose `folium` and defended it on the lean-core-install constraint. Recorded here because a future V2 richer-map need may revisit this.
- The conformance checklist lives in `docs/v1-conformance.md` (separate from this report) so the executor-authored acceptance evidence stays distinct from report narrative.

## 8. Escalations

None. Neither step required an architecture amendment, a second provider, a §19 implementation, a new core dependency, or live network. No filter-semantics conflict with the catalogue shape arose, and no §0-§18 completeness gap was found.

## 9. V1 completeness statement

**Yes - V1 is conformant.** The architecture-conformance checklist at `docs/v1-conformance.md` maps every `architecture.md` §0-§18 commitment to implemented behavior backed by real, named tests with negative controls, and reaffirms §19 as explicitly deferred. The artifact's status tally is 17 `realized`, 5 `structural/process` (the §0 no-speculative-abstractions and §18 feedback-loop process commitments, honestly labeled with structural controls rather than fabricated behavioral tests), and 13 §19 `deferred` rows - **zero `blocker` rows**. The single textual "blocker" mention is the explicit statement "No §0-§18 conformance blocker was found during executor evidence audit," not a flagged row.

The reviewer's L_conformance_honesty pass opened ≥3 cited tests and confirmed they are genuine negative controls (fail on regression, not pass-regardless), and the ~99 cited test names were verified to exist. Orchestrator reconciliation independently confirmed: all sections §0-§19 present, no status cell marked `blocker`, and the three §19 absence controls pass. No `architecture.md` §0-§18 commitment was found unimplemented by any milestone. V1 is feature-complete and signed off at the conformance-evidence level.

## 10. Coordinator closeout queue (orchestrator tees up; coordinator decides)

These are **not** orchestrator actions. Each is teed up with enough context for the coordinator to decide post-M5:

1. **PR / merge to main.** The redesign has lived on `docs/provider-redesign-proposal` (M1-M5, never pushed). Decide whether to open/convert the PR and merge to `main`. The branch is clean, all sweeps green, V1 conformant.
2. **V1 release tag and version.** Per-commit D1 patch bumps walked the version to **`v0.1.24`**, far past the original `0.1.x` intent - the tags are step-granular, not release-granular. Decide the actual V1 release version (e.g. promote to `1.0.0` or a deliberate `0.2.0`) and cut the release tag; the `0.1.x` walk should not be mistaken for the V1 release version.
3. **Post-V1 architecture recommendations from the conformance sweep.** None are *required* (no gap), but the checklist and M5 notes recommend the coordinator weigh: whether `folium` vs `leafmap` should be revisited if V2 needs richer map layers; and whether any structural/process row (§0, §18) warrants a stronger codified control.
4. **Standing "coordinator should review" discovery items never promoted.** From `docs/discoveries.md`:
   - **D5** - introduce explicit `__all__` for the package root (post-V1 hygiene; T119/T120 currently guard module attributes, not `import *` semantics).
   - **D6** - consider adding an import-time-attribute-shadowing probe as a permanent reviewer lens for future provider ports.
   - **D7 / D9** - optional lint conventions (Pydantic `extra="allow"` via `model_validate`; concrete `dict`/`list` over ABC `isinstance` for JSON-loaded data) for future provider code; did not fire in M4/M5.
   - **D8** - the generator-side round-trip probe for asymmetric-encoding columns, if/when a second provider generates packaged artifacts.
5. **Deferred §19 questions** (wide-form pandas helpers, RivRetrieve-derived products, vocabulary expansion beyond river-gauge variables) remain reaffirmed-deferred. Schedule any that V2 demand makes worth re-opening; architecture changes must be made explicitly, not via implementation drift.

---

M5 is closed. With the map view shipped and the conformance checklist signed off, the provider-based RivRetrieve redesign is **V1 feature-complete**.

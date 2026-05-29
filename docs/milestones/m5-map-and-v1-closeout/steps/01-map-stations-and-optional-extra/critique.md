# Critique — 01-map-stations-and-optional-extra

Adversarial review of `docs/milestones/m5-map-and-v1-closeout/steps/01-map-stations-and-optional-extra/plan.md`.

## Verdict

**DISPATCH WITH MINORS FOLDED.**

I tried to break this plan and could not find a contract violation that blocks dispatch. The four hardest attack vectors — filter-satisfiability against the catalogue shape, the missing-backend two-channel boundary, the offline-import invariant, and the D6 shadowing trap on the new callable — all hold, and the plan's load-bearing facts (246 rows, `country="Switzerland"`, all-null `elevation_m`/`drainage_area_km2`, Brugg=`2016`, return type `object`) are individually verified against the live artifacts, not just cited. No ESCALATE trigger fires: every filter sources from an existing non-nullable column, the backend stays an optional extra, and nothing breaks the import invariant.

The Minors below are fold-in clarifications the executor should bank before/while implementing; none require returning to the planner. The strongest of them (M-1, the `on_issue` dead-knob, and M-2, backend-free filter assertions) are design-hygiene fixes, not doubts about whether the step can ship.

## Major findings

None.

I actively hunted for these and they did not materialize:

- **No filter-semantics conflict with catalogue shape.** I read `STATION_CATALOG_SCHEMA` (`src/rivretrieve/_internal/catalogues/schemas.py:35-51`): `provider_id`, `country`, `latitude`, `longitude` are all present and **non-nullable**. All three filters source from these. No schema change, no ESCALATE.
- **No hard-dependency drift.** `folium` is declared only under `[project.optional-dependencies]`, imported lazily, and a stopping condition guards against it becoming a runtime dep.
- **No offline-invariant break.** `import rivretrieve` does not reach the backend; the D6 trap is explicitly closed for the *new* callable (§2 forbids `src/rivretrieve/map_stations.py`, `…/map_stations/`, `…/_internal/map_stations.py`).
- **No retrofit of filters onto `rr.stations()`.** §3 and Q2 resolve the tension by keeping `rr.stations()` unfiltered and putting filters only on `map_stations` — exactly what L2 demands.
- **No two-channel inversion.** Missing-backend is a `FatalContractError` subclass raised regardless of `on_issue`, never routed through `apply_on_issue`; empty filter result is a successful empty view, not fatal and not an Issue.

## Minor findings

### M-1 — `on_issue` on `map_stations` is likely a dead/misleading knob; it has no sibling precedent and no actuating path
- **Plan section:** §2 "Signature rules"; §4 "Recoverable issues"; Q5.
- **Quoted line:** "`on_issue` is accepted only for catalogue validation/recoverable issues from the existing packaged catalogue read path." / Q5: "yes, but only to remain compatible with existing catalogue validation policy if recoverable catalogue issues surface while reading packaged data."
- **Problem:** The global packaged-station read path the plan reuses **hardcodes** policy. `discovery.stations()` is `def stations() -> CatalogResult[StationCatalog]` with **no** `on_issue` parameter and calls `validate_catalogue(data, STATION_CATALOG_SCHEMA, on_issue="raise")` (`src/rivretrieve/_internal/discovery.py:90,98`). So (a) `map_stations` would expose a policy knob its own sibling `rr.stations()` does not, an inconsistency in the *final* V1 surface; and (b) over the current read path the knob has nothing to actuate — extra-column warnings are the only recoverable issue the catalogue validator emits, and the existing global path raises hardcoded. The risk is a parameter that reads as meaningful but is inert.
- **Contract touched:** architecture §15 (`on_issue` is the sole knob *for recoverable issues*) — fine in principle, but the plan must not ship a knob with no recoverable channel behind it.
- **Concrete fix:** Either (a) thread `on_issue` into a genuine recoverable read (call the per-provider/reader path with `on_issue` and add a test that a recoverable catalogue issue is warned/raised/ignored accordingly), or (b) drop `on_issue` from `map_stations` to match `rr.stations()`'s no-knob shape. Whichever is chosen, keep the existing guarantee that `on_issue` never touches missing-backend (already specified, keep it).

### M-2 — Filter-correctness tests (#7–#11) need a backend-free assertion target; "selects the 246 rows" is not observable through an opaque `folium.Map`
- **Plan section:** §5 tests 7–11; §5 "Test mechanics recommendation".
- **Quoted line:** Test 7: "`providers="ch_foen"` selects the 246 packaged `ch_foen` rows".
- **Problem:** `map_stations` returns `StationMap(filtered).render()` — an opaque `folium.Map`. Asserting "selects 246 rows" or "selects zero rows" through a rendered map either requires `folium` (which would gate the filter tests behind the extra and violate "suite passes WITHOUT the extra") or requires reaching into folium internals. The plan gestures at a "small fake backend object for filter/offline tests" but never states that the filter assertions inspect the *captured station frame*, not the map.
- **Contract touched:** L4 ("filter correctness incl. empty result" must run without the extra); L8 (green without the extra at every step).
- **Concrete fix:** Make the filter step a pure, separately-testable helper — e.g. `_filter_stations(df, *, providers, country, bbox) -> pl.DataFrame` in `station_map.py` — and assert filter correctness directly on the returned DataFrame (`.height`, `station_id` set, boundary equality) with **no backend at all**. Reserve the fake-backend seam for the "render was invoked with the filtered frame" wiring test and `pytest.importorskip("folium")` for real marker/HTML assertions. State this split explicitly in §5.

### M-3 — `MissingOptionalDependencyError` is excluded from the public surface but not added to the negative control
- **Plan section:** §2 ("Do not re-export … `MissingOptionalDependencyError` …"); §5 test 2.
- **Quoted line:** Test 2: "remove `map_stations` from forbidden names; add `StationMap`; keep all M2/M4 internal types absent."
- **Problem:** The plan promises `MissingOptionalDependencyError` is not re-exported, but the T120 negative control (`tests/test_package.py::test_deferred_public_names_remain_absent_after_provider_handle_promotion`) is the thing that *enforces* non-export, and the plan only adds `StationMap` to it. The existing forbidden list already enumerates fatal subclasses (`InvalidObservationRequestError`, `ObservationsUnavailableError`, …), so omitting the new one is an inconsistency that lets a future accidental re-export slip through.
- **Concrete fix:** Add both `StationMap` **and** `MissingOptionalDependencyError` to the T120 forbidden-name list in the step-6 flip.

### M-4 — The pyproject guard is phrased for the wrong direction of leakage
- **Plan section:** §6 step 2.
- **Quoted line:** "Do not move core dependencies into the extra."
- **Problem:** The packaging risk L_extra_packaging_correctness actually guards is the opposite: `folium` leaking *into* core `[project.dependencies]` (or being duplicated there), which would defeat the lean-core install. The plan's wording guards a direction nobody is tempted to take.
- **Concrete fix:** Reword to: "`folium` appears **only** under `[project.optional-dependencies].map` and is **not** present (nor duplicated) in core `[project.dependencies]`; the extra name `map` matches the `pip install rivretrieve[map]` string in the error message verbatim." (The name/message match itself is correct as written — verified `map` ↔ `rivretrieve[map]`.)

### M-5 — Conditional D9: if popup rendering decodes the `metadata` JSON column, use `dict`/`list` isinstance checks
- **Plan section:** §3 "Station rows used by the map" ("decoded `metadata` only if this does not add schema requirements").
- **Problem:** `metadata` is a `pl.Utf8` JSON-string column (schemas.py:48). If popups parse it with `json.loads` and then walk the result with `isinstance(x, Mapping)`, D9 bites (ty narrows to `Never`). This only fires if the executor implements metadata popups, which the plan marks optional.
- **Concrete fix:** Note in §3 that any `json.loads` walk of `metadata` uses concrete `isinstance(x, dict)` / `isinstance(x, list)` per D9. (M4 REPORT §6 recommends not promoting D9 as a permanent lens; this is the one place in this step it could re-fire.)

## Nits

- **N-1 (bbox ordering footgun):** `(min_lon, min_lat, max_lon, max_lat)` is stated unambiguously (good — L_filter_satisfiability passes), but lon/lat transposition is a classic silent bug. Have test #9 use a bbox that would select the *wrong* set under the transposed convention so the ordering is locked by a test, and restate the order in the docstring and in any "reversed bounds" error message.
- **N-2 (test numbering):** The plan refers to "T119/T120," but the live function names are `test_init_public_surface_exports_m2_provider_handle_surface` and `test_deferred_public_names_remain_absent_after_provider_handle_promotion` (the `_m2_` name persisted through M4 even though the present-set now includes `observations`). This matches the orchestrator/M4-REPORT convention; just flagging so the executor edits the right functions and does not rename them.
- **N-3 (StationMap is a thin builder):** `map_stations` returns `render()`'s output and discards the `StationMap` instance, so the dataclass is a near-passthrough. This is fine — the tracker mandates `StationMap` as the M5 internal type — but the executor should not feel pressure to grow it into a wrapper; keeping it minimal is correct.

## Lens-by-lens summary

- **L1 Scope completeness** ✅ — extra, internal `StationMap`, `map_stations`, providers/country/bbox filters, missing-backend fatal, T119/T120 flip all present.
- **L2 Scope over-reach** ✅ — checklist/README/REPORT/second-provider/§19/arch-amendment all deferred to step 02; filters live on `map_stations`, not retrofitted onto `rr.stations()`; no map-specific catalogue metadata.
- **L3 Citation verification** ✅ — verified 246 rows, `country="Switzerland"`, all-null elevation/drainage, Brugg=`2016` against the live parquet; tracker §3 return type `object` and M4 REPORT §7 nullable claim confirmed.
- **L4 Test coverage adequacy** ✅ (with M-2 fold) — all M5 negative controls present; backend render gated via `importorskip`; filter assertions need the backend-free target per M-2.
- **L5 Error-handling completeness** ✅ — missing-backend is a `FatalContractError` subclass naming the extra; empty result explicitly not fatal; bbox-shape validation fatal.
- **L6 Open-question rigor** ✅ — backend choice, filter semantics, return contract are evidence-backed (folium vs leafmap weight argument; catalogue-column sourcing).
- **L7 Deferral hygiene** ✅ — deferrals are genuine; none is a hidden dependency of step 01.
- **L8 Implementation order** ✅ — green without network and without the extra at each boundary; the surface flip lands with the re-export (step 6), never before.
- **L9 Stopping-conditions adequacy** ✅ — eleven concrete stop conditions cover schema-change, policy-routing, fatal/empty inversion, import leakage, hard-dep drift, `rr.stations()` signature, D6, observation/token touch, nullable columns, scope drift, and green-at-each-boundary.
- **L10 Architecture-commitment compliance** ✅ — optional-extra structure and lazy-backend-import both held; M-4 only sharpens the pyproject guard wording.
- **L11 Speculative-abstraction check** ✅ — no ABC/parallel-reader/post-V1 hook; `StationMap` and the `_load_folium` seam are tracker-authorized internals, not speculative.
- **L_two_channel** ✅ — missing-backend fatal-raises bypassing policy; empty filter result non-fatal. Both directions correct.
- **L_inherited_patterns** ✅ — `StationMap` stays internal (no public promotion); 246-row / all-null nullable facts respected (tests 7, 16); Polars-canonical filtering; D1 patch bump preserved.
- **L_legacy_citation_fidelity** ✅ — NO legacy citations made; tracker confirms "no direct legacy analogue for mapping." External cites are folium/leafmap docs, not Switzerland.
- **L_vocabulary_boundary** ✅ — map renders stations, no product-vocabulary broadening via map metadata.
- **L_offline_invariant_explicit** ✅ — `import rivretrieve` does not import folium/leafmap/ipyleaflet/provider runtime/`generate_catalogue`; backend imported lazily; D6 shadowing closed for the new `map_stations` callable.
- **L_asymmetric_encoding_round_trip** ✅ NA — no new packaged artifact or column; `metadata` is read-only here, no generator side. Confirmed NA.
- **L_conformance_honesty** ✅ — no pre-claim of V1 conformance; no checklist rows written; checklist deferred to step 02.
- **L_D7_probe** ✅ NA — no Pydantic `extra="allow"` model introduced.
- **L_D9_probe** ⚠️ conditional — NA unless metadata-popup JSON walking is implemented; see M-5.
- **L_filter_satisfiability** ✅ — providers→`provider_id`, country→`country`, bbox→`latitude`/`longitude`, all existing non-nullable columns, no schema change; bbox convention stated (tighten via N-1). No ESCALATE.
- **L_extra_packaging_correctness** ✅ (with M-4 reword) — extra `map` ↔ `pip install rivretrieve[map]` matches; backend kept out of core; guard wording sharpened.
- **L_map_return_contract** ✅ — return is backend-native `folium.Map` typed `object`, documented and tested (#15); `StationMap` role unambiguous (internal builder, not returned).

## Adversarial probes attempted

1. **Read `tests/test_package.py`** — confirmed `map_stations` currently sits in the forbidden `deferred_names` list (line 35) and the present-set is exactly 8 names; the plan's step-6 flip (add to present, remove from forbidden, add `StationMap`) is therefore correct. Caught that `MissingOptionalDependencyError` is not added to the forbidden list (M-3).
2. **Read the live packaged parquet** via `uv run python` over `src/rivretrieve/_internal/providers/ch_foen/catalogue/stations.parquet` — confirmed **246 rows**, `country` uniques `['Switzerland']`, `elevation_m`/`drainage_area_km2` **246/246 null**, station `2016` = `Brugg` at `(47.4825, 8.1949)`. Every load-bearing data claim in the plan is real, not assumed.
3. **Read `STATION_CATALOG_SCHEMA`** (`schemas.py:35-51`) — confirmed all three filter columns exist and are non-nullable, so no ESCALATE on filter-satisfiability; also confirmed `metadata` is `pl.Utf8` (JSON string), which is what gated the D9 conditional (M-5).
4. **Read `discovery.py`** — confirmed `stations()` has **no** `on_issue` parameter and hardcodes `validate_catalogue(..., on_issue="raise")` (lines 90, 98), exposing the dead-knob inconsistency (M-1); confirmed `_ensure_default_providers_registered()` imports the provider lazily at call time, so reusing it inside `map_stations` does not break the offline-import invariant.
5. **Read `issues.py`** — confirmed `FatalContractError`, `IssuePolicyError`, and `apply_on_issue` shapes so the missing-backend fatal-raise (subclass of `FatalContractError`, bypassing `apply_on_issue`, no `IssuePolicyError` in chain) is implementable exactly as the plan specifies.
6. **Read `tests/conftest.py`** — confirmed the existing monkeypatch/fixture/`pl.DataFrame` stub style the plan leans on; noted the stub stations use `country="CH"` whereas the real catalogue uses `"Switzerland"`, so the plan is correct to anchor filter tests to the **real packaged catalogue** (246 rows / `Switzerland`) and not to the `CH` stub — a test that filtered the stub on `country="Switzerland"` would wrongly select zero. The plan's tests 7–8 target the packaged rows, so this is consistent; flagged here so the executor does not cross the wires.
7. **Read `tests/test_offline_import.py`** — confirmed the subprocess `sys.modules` assertion pattern the plan extends; the folium/leafmap/ipyleaflet additions slot into the existing loop cleanly and pass trivially whether or not the extra is installed (lazy import).

# 01-map-stations-and-optional-extra Plan

## 1. Goal and scope

Ship `rr.map_stations(...)` as the final V1 public method: an offline map view over the packaged station catalogue.

This step lands:

- A `[project.optional-dependencies]` block in `pyproject.toml` with a `map` extra.
- One internal `StationMap` helper that builds the map object and remains absent from the package root.
- `rr.map_stations(...)`, implemented through `_internal.discovery` and re-exported from `rivretrieve.__init__`.
- Lazy map-backend import inside the map path only.
- A `MissingOptionalDependencyError(FatalContractError)` fatal for absent backend packages.
- `providers`, `country`, and `bbox` filters over existing packaged station columns.
- T119/T120 public-surface flip: `map_stations` becomes present, `StationMap` and `MissingOptionalDependencyError` become forbidden.
- Per-commit patch bump per D1.

Out of scope:

- Step 02 closeout work: architecture-conformance checklist, final `docs/provider_ports/ch_foen.md` updates, discoveries closeout, `REPORT.md`, README/user docs unless step 02 decides they are needed.
- Any signature change to `rr.stations()`. Its current no-argument contract stays intact; `map_stations` owns map-specific filters.
- Map-specific metadata not already present in the station catalogue.
- Any observation-client, Influx-token, provider-API, live catalogue, or network path.
- Any second provider, §19 deferred feature, architecture amendment, wide-form export, derived product, or vocabulary expansion.

The method is a view. It reads the same packaged/offline station catalogue as `rr.stations()` and must work without contacting providers.

## 2. API surface

New public callable:

```python
def map_stations(
    *,
    providers: str | Sequence[str] | None = None,
    country: str | Sequence[str] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> object: ...
```

Signature rules:

- Keyword-only, matching the existing package-root style for non-trivial public methods.
- `providers` filters station rows by `provider_id`.
- `country` filters station rows by the catalogue `country` column.
- `bbox` uses `(min_lon, min_lat, max_lon, max_lat)`, matching common GIS bounding-box order.
- No `on_issue` parameter. `rr.stations()` has no policy knob and its current global packaged read path validates with `on_issue="raise"`; adding an inert map-only policy parameter would mislead users.
- Return annotation stays `object`, matching tracker §3 and avoiding a hard public type dependency on the optional backend.

Implementation location:

- Add `map_stations` to `src/rivretrieve/_internal/discovery.py`, near `stations()`.
- Add any larger map-building helper in an internal module named so it does not shadow the public callable. Recommended path: `src/rivretrieve/_internal/station_map.py`.
- Do not create `src/rivretrieve/map_stations.py`, `src/rivretrieve/map_stations/`, `src/rivretrieve/_internal/map_stations.py`, or any public module path that can bind `rivretrieve.map_stations` as a module instead of the callable. This is the D6 shadowing trap applied to the new public symbol.

Package-root re-export:

- Add exactly `from rivretrieve._internal.discovery import map_stations as map_stations` to `src/rivretrieve/__init__.py`.
- Do not re-export `StationMap`, `MissingOptionalDependencyError`, `Issue`, `CatalogResult`, `StationCatalog`, or any backend-native type.
- The mandatory D1 patch version literal also changes in `src/rivretrieve/__init__.py`; that is separate from the API-shape edit.

## 3. Data structures and types

Recommendation: use `folium` as the backend package and declare the extra as:

```toml
[project.optional-dependencies]
map = [
    "folium",
]
```

Rationale:

- The tracker names `leafmap` as a candidate, but the goal is a packaged station-catalogue view, not a geospatial-analysis workbench. `folium` is enough for an offline-created Leaflet map with station markers/popups.
- `leafmap` is richer but currently pulls a broad geospatial/Jupyter stack, including `folium`, `ipyleaflet`, widgets, `geopandas`, plotting packages, and related dependencies. Its own documentation describes optional geospatial dependencies as potentially challenging on some systems. That conflicts with the lean-core-install constraint for a small V1 view.
- `folium` keeps the optional extra narrow and still returns a backend-native object users can render in notebooks or save as HTML.
- The install command named in errors should be `pip install rivretrieve[map]`, even though project development uses `uv`; package users understand extras through pip syntax and the prompt requires that exact shape.

Internal helper:

```python
@dataclass(frozen=True)
class StationMap:
    stations: pl.DataFrame

    def render(self) -> object: ...
```

`StationMap` is an internal thin builder, not the public return type. `rr.map_stations(...)` should return the backend-native `folium.Map` object produced by `StationMap.render()`. Do not grow `StationMap` into a public wrapper or secondary API surface.

Pure filter helper:

```python
def _filter_stations(
    stations: pl.DataFrame,
    *,
    providers: str | Sequence[str] | None = None,
    country: str | Sequence[str] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> pl.DataFrame: ...
```

This helper is internal and backend-free. It exists so filter behavior can be asserted directly on a `pl.DataFrame` without installing `folium` or inspecting backend internals.

Return-contract recommendation:

- Return a backend-native `folium.Map`, typed publicly as `object`.
- Keep `StationMap` internal because exposing a wrapper would promote a new public type in the final V1 surface and create a long-term API commitment that the tracker does not require.
- Tests can assert backend-native behavior only when `folium` is importable; the always-on suite should primarily assert missing-backend, filtering, offline behavior, and public-surface controls.

Station rows used by the map:

- Required for rendering: `provider_id`, `station_id`, `name`, `latitude`, `longitude`, `country`.
- Optional popup/context fields may include `start_date`, `end_date`, and decoded `metadata` only if this does not add schema requirements.
- If popup rendering decodes the JSON-string `metadata` column, any `json.loads` walk must use concrete `isinstance(x, dict)` / `isinstance(x, list)` checks per D9, not `Mapping` / `Sequence` ABC checks.
- `elevation_m` and `drainage_area_km2` must not be required; M4 handoff says they are nullable for all current `ch_foen` rows.

Filter semantics:

- `providers`: accept `str | Sequence[str] | None`. Normalize a single string to one ID. Match exactly against `provider_id`; provider IDs are canonical snake_case and case-sensitive.
- `country`: accept `str | Sequence[str] | None`. Normalize a single string to one country value. Match exactly, case-sensitive, against the catalogue `country` column. Current `ch_foen` catalogue stores `Switzerland`; do not invent aliases such as `CH` unless the catalogue contains them.
- `bbox`: accept `(min_lon, min_lat, max_lon, max_lat)`. Bounds are inclusive on all sides: `min_lon <= longitude <= max_lon` and `min_lat <= latitude <= max_lat`. Repeat this lon/lat order in the function docstring and in any reversed-bounds error message.
- Combined filters are logical AND.
- All three filters are satisfiable from the existing station catalogue columns (`provider_id`, `country`, `latitude`, `longitude`) with no schema change.
- The `rr.stations()` no-filter tension is resolved by implementing filtering only in `map_stations`; do not retrofit filters onto `rr.stations()`.

Empty result:

- An empty filtered station table returns an empty map object with no markers.
- This is not fatal and should not create a recoverable issue by itself. A user asking for a valid filter that matches zero rows has a valid empty view.

## 4. Errors and failure modes

New fatal:

```python
class MissingOptionalDependencyError(FatalContractError):
    ...
```

Behavior:

- Raised when `folium` cannot be imported by the map-rendering path.
- Message must name the backend and exact extra command: `pip install rivretrieve[map]`.
- It is a `FatalContractError` subclass.
- It raises directly and is never controlled by recoverable-issue policy.
- It must not call or be routed through `apply_on_issue`; no `IssuePolicyError` should appear in its exception chain.

Recommended location:

- Define `MissingOptionalDependencyError` in `src/rivretrieve/_internal/issues.py`, next to other fatal contract subclasses.
- Do not re-export it at package root.

Other fatal validation:

- Invalid `bbox` shape, non-numeric bbox values, or reversed bounds (`min_lon > max_lon` or `min_lat > max_lat`) should raise a fatal contract error, preferably `FatalContractError` or a small internal subclass if the executor finds an existing validation-error pattern worth matching.
- Invalid `providers`/`country` container values should raise fatal input errors rather than silently guessing. Strings are scalar values, not sequences of characters.
- Corrupt packaged catalogue artifacts and schema violations keep using existing fatal paths from catalogue loading/validation.

Recoverable issues:

- Missing backend, invalid filter shape, corrupt artifacts, and implementation/schema violations are fatal direct raises.
- Empty filters matching zero stations are successful empty views, not recoverable issues and not fatal.

Lazy import invariant:

- `folium` import happens inside `StationMap.render()` or an internal `_load_backend()` called only from `map_stations`.
- `import rivretrieve` must not import `folium`, `leafmap`, `ipyleaflet`, provider runtime modules, or `generate_catalogue.py`.

## 5. Tests

1. T119 expansion: `map_stations` now appears in the package-root present public set.
2. T120 negative control: remove `map_stations` from forbidden names; add `StationMap` and `MissingOptionalDependencyError`; keep all M2/M4 internal types absent.
3. Offline-import preservation with the map extra absent: `import rivretrieve` does not import `folium`, `leafmap`, `ipyleaflet`, provider runtime modules, or any `generate_catalogue` module.
4. Missing-backend fatal raise: simulate absent backend and assert `rr.map_stations(...)` raises `MissingOptionalDependencyError`, which is a `FatalContractError`.
5. Missing-backend message: assert the exception text includes `pip install rivretrieve[map]` and the backend name `folium`.
6. Missing-backend bypasses recoverable-issue policy: assert the fatal direct raise has no `IssuePolicyError` chain. There is no public `on_issue` parameter on `map_stations`.
7. Filter correctness, providers: call `_filter_stations` directly on the real packaged station frame and assert `providers="ch_foen"` selects the 246 packaged `ch_foen` rows; an unknown provider ID filter returns an empty frame, not a fatal lookup.
8. Filter correctness, country: call `_filter_stations` directly on the real packaged station frame and assert `country="Switzerland"` selects the 246 packaged rows; case-mismatched or absent country values select zero rows under exact matching. Do not use the generic conftest stub for this assertion because it uses `country="CH"`.
9. Filter correctness, bbox: call `_filter_stations` directly on the real packaged station frame; use a bbox around Brugg (`station_id="2016"`) that would select a different set if lat/lon ordering were accidentally transposed; assert outside bbox returns zero rows and boundary equality is included.
10. Combined filters: providers + country + bbox apply as AND and return the expected subset.
11. Empty-result behavior: `_filter_stations` returns an empty frame for a valid zero-match filter, and `map_stations` with a fake backend returns an empty map object without raising.
12. Packaged-data-only proof: monkeypatch provider observation client factory, default observation transport, and/or provider module observation functions to fail if touched; call `map_stations` through the backend stub and assert none are called.
13. No token touch: set or delete `CH_FOEN_INFLUX_TOKEN` and spy on `ChFoenObservationClient.resolved_token`/factory path if needed; `map_stations` must not instantiate the client.
14. Reader path proof: spy on `CatalogueReader.read_stations` and assert `map_stations` reads station catalogue data, not products/station-products or live provider methods.
15. Backend-available render: gated test using `pytest.importorskip("folium")`; assert the returned object is `folium.Map` and marker count or rendered HTML reflects the selected station subset.
16. Backend-available all-null nullable columns: use a stub station frame where `elevation_m` and `drainage_area_km2` are all null; rendering still succeeds.
17. Backend simulation without installing extra: use monkeypatch/import-shadowing rather than uninstalling. Existing tests already use monkeypatch and subprocess `sys.modules` assertions; add a focused import hook or monkeypatch the internal backend loader to raise `ModuleNotFoundError` for always-on missing-backend tests, and use `pytest.importorskip("folium")` for real backend behavior.

Test mechanics recommendation for extra absence:

- Prefer an internal `_load_folium()` helper in `station_map.py`; tests monkeypatch that helper to raise `ModuleNotFoundError("folium")` for absent-backend behavior and to return a small fake backend object for wiring/offline tests.
- Assert filter correctness primarily through `_filter_stations(...) -> pl.DataFrame`, not through an opaque `folium.Map`. Use the fake backend only to prove `map_stations` invokes rendering with the filtered frame.
- Also add one subprocess offline-import assertion that checks the real package import path leaves `folium`, `leafmap`, and `ipyleaflet` out of `sys.modules`.
- This matches the repository's existing monkeypatch style in `tests/conftest.py`, `tests/test_discovery.py`, and observation transport tests, without requiring dependency uninstallation.
- The public-surface test functions are currently named `test_init_public_surface_exports_m2_provider_handle_surface` and `test_deferred_public_names_remain_absent_after_provider_handle_promotion`; edit those existing T119/T120 controls rather than renaming them.

## 6. Files in implementation order

The order below keeps `uv run pytest` green without network and without `folium` installed at every intermediate point. The public-surface test flip lands only after the callable exists.

1. `src/rivretrieve/_internal/issues.py`
   - Add `MissingOptionalDependencyError(FatalContractError)`.
   - No public-surface changes yet; existing tests should remain green.

2. `pyproject.toml`
   - Add `[project.optional-dependencies] map = ["folium"]`.
   - Ensure `folium` appears only under `[project.optional-dependencies].map` and is not present or duplicated in core `[project.dependencies]`; the extra name `map` must match the `pip install rivretrieve[map]` message verbatim.
   - Existing tests should remain green because the extra is optional and absent by default.

3. `src/rivretrieve/_internal/station_map.py`
   - Add internal `StationMap`, backend loader, `_filter_stations`, and map-rendering logic.
   - Keep `folium` imported lazily inside the loader/render path only.
   - Do not attach anything to package root.

4. `tests/test_map_stations.py` or focused additions to `tests/test_discovery.py`
   - Add internal/backend-loader tests that import `_internal.station_map` directly and do not require package-root `rr.map_stations` yet.
   - Keep tests green by testing internal helpers or fake backend injection only.

5. `src/rivretrieve/_internal/discovery.py`
   - Add public internal function `map_stations(...)` that calls `_ensure_default_providers_registered()`, reads packaged station data, validates/applies filters, and returns `StationMap(filtered).render()`.
   - Do not change `rr.stations()` signature.

6. `src/rivretrieve/__init__.py` and `tests/test_package.py`
   - Re-export `map_stations`.
   - Flip T119/T120 in the same edit: add `map_stations` to the present set, remove it from forbidden, add `StationMap` and `MissingOptionalDependencyError` to forbidden.
   - This is the first point where package-root public-surface tests expect the new callable.

7. `tests/test_offline_import.py`
   - Extend subprocess assertions so `import rivretrieve` does not import `folium`, `leafmap`, `ipyleaflet`, provider runtime modules, or generators.

8. `tests/test_map_stations.py`
   - Add public `rr.map_stations(...)` tests for missing backend, filters, empty result, packaged-only behavior, nullable elevation/drainage handling, and backend-available gated render.

9. Formatting and verification files touched by tools only
   - Run `uv run ruff format`.
   - Run `uv run ruff check --fix`.
   - Run `uv run ty check`.
   - Run `uv run pytest`.

10. Version bump and commit metadata
    - Run `uv run bump-my-version bump patch`.
    - Stage code, tests, `pyproject.toml`, `uv.lock` if changed, and version-literal changes.
    - Commit once.
    - Tag `v$(uv run bump-my-version show current_version)`.

If adding the optional dependency requires updating `uv.lock`, do it with `uv lock` after the `pyproject.toml` edit and before final verification. If `uv lock` needs network and sandboxing blocks it, request escalation rather than hand-editing the lockfile.

## 7. Open questions

Q1. Map backend package and exact extra name.

Recommendation: use extra name `map` and backend package `folium`. The user-facing command is `pip install rivretrieve[map]`. `leafmap` remains a reasonable later upgrade if V2 needs richer geospatial layers, but it is too heavy for a V1 station-marker view and pulls `folium` plus a broader notebook/geospatial stack. `folium` directly satisfies station markers and a renderable map while preserving lean core installs.

Q2. Filter semantics.

Recommendation: `providers: str | Sequence[str] | None`, exact case-sensitive match on `provider_id`; `country: str | Sequence[str] | None`, exact case-sensitive match on the `country` column (`Switzerland` for current `ch_foen` rows); `bbox: (min_lon, min_lat, max_lon, max_lat)`, inclusive bounds. All filters use existing columns and require no schema change. `rr.stations()` remains unfiltered.

Q3. Return contract and `StationMap` role.

Recommendation: `rr.map_stations(...) -> object` returns the backend-native `folium.Map`. `StationMap` is an internal builder/rendering helper and is not returned publicly. This keeps the final V1 public surface to one callable and avoids promoting a wrapper type.

Q4. Empty-filter result.

Recommendation: return an empty map object with no markers. Do not raise and do not emit an issue solely because no rows match valid filters.

Q5. Does `map_stations` accept `on_issue`?

Recommendation: no. `rr.stations()` has no `on_issue` parameter and the current global packaged station path validates with `on_issue="raise"`. Adding `on_issue` to `map_stations` would be a dead or misleading map-only knob unless the executor rewired a genuine recoverable catalogue path. Keep the public signature small and make missing optional dependency and invalid filter contracts fatal direct exceptions.

Q6. How to simulate absent extra in tests without uninstalling.

Recommendation: add an internal backend-loader seam and monkeypatch it. The repository already uses monkeypatch for registry defaults, provider delegation, and transport injection, plus subprocess `sys.modules` checks for offline import. Use those patterns instead of uninstalling packages. Always-on absent-backend tests monkeypatch the loader to raise `ModuleNotFoundError`; real-backend tests use `pytest.importorskip("folium")`.

## 8. Deferrals

- Step 02 owns architecture-conformance checklist, final M5 report, final provider-port notes, discoveries closeout, and README/user docs decisions.
- No filters on `rr.stations()`.
- No `on_issue` policy knob on `map_stations` unless a future architecture update gives global packaged discovery a real recoverable policy channel.
- No live/global map discovery.
- No provider API calls, observation map overlays, token handling, observation popups, or time-aware/product-aware map behavior.
- No map-specific catalogue columns or metadata enrichment.
- No `leafmap`/`ipyleaflet` multi-backend abstraction.
- No public `StationMap` export and no public backend-policy abstraction.
- No second provider, plugin entry points, cross-provider station deduplication, quality harmonization, derived products, or §19 deferred work.

## 9. Stopping conditions for the executor

- Stop and escalate if `providers`, `country`, or `bbox` cannot be implemented from existing station catalogue columns without a schema change.
- Stop if missing-backend behavior is routed through `apply_on_issue` or can raise `IssuePolicyError`.
- Stop if a valid empty filter result is implemented as fatal or recoverable issue behavior.
- Stop if `on_issue` is added to `map_stations` without a real recoverable catalogue path and explicit planner/reviewer approval.
- Stop if `folium`, `leafmap`, `ipyleaflet`, provider runtime modules, observation clients, or `generate_catalogue.py` are imported by `import rivretrieve`.
- Stop if the map backend becomes a hard runtime dependency instead of an optional extra.
- Stop if implementation requires changing `rr.stations()`'s signature.
- Stop if D6-style module shadowing appears for `rivretrieve.map_stations` or any existing public callable.
- Stop if map rendering touches observation retrieval, the Influx token, provider APIs, live catalogue modes, or default network transports.
- Stop if all-null `elevation_m` or `drainage_area_km2` prevents map rendering.
- Stop if the work drifts into step 02 closeout docs, architecture amendments, §19 deferred features, a second provider, or README/user docs.
- Stop if the workspace cannot stay importable and `uv run pytest` green without network and without the `map` extra installed at each file-order boundary.

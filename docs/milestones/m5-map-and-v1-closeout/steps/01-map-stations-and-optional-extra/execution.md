# Execution — 01-map-stations-and-optional-extra

## Outcome

Implemented step 01 as planned:

- Added `MissingOptionalDependencyError(FatalContractError)` in `_internal/issues.py`.
- Added `[project.optional-dependencies].map = ["folium"]`; `folium` is not in core dependencies.
- Added internal `_internal/station_map.py` with `StationMap`, lazy `_load_folium()`, and backend-free `_filter_stations(...)`.
- Added `rr.map_stations(...)` through `_internal.discovery` and package-root re-export.
- Kept `rr.stations()` unchanged.
- Flipped T119/T120: `map_stations` is public; `StationMap` and `MissingOptionalDependencyError` remain absent from package root.

Chosen backend: `folium`.

Extra name: `map`.

## Verification

Final sweep on the post-bump tree:

- `uv run ruff format` passed.
- `uv run ruff check --fix` passed.
- `uv run ty check` passed.
- `uv run pytest` passed: 439 collected, 437 passed, 2 skipped.

Delta from baseline: +13 collected tests versus the 426-test handoff baseline.

The 2 skipped tests are the `pytest.importorskip("folium")` real-backend render checks, skipped because `folium` is absent from the current environment.

## Negative Controls

- T119/T120 public-surface flip is covered in `tests/test_package.py`.
- Offline import with the map extra absent is covered in `tests/test_offline_import.py`; `import rivretrieve` leaves `folium`, `leafmap`, `ipyleaflet`, provider runtime modules, and `generate_catalogue.py` out of `sys.modules`.
- Missing backend is a direct `MissingOptionalDependencyError`, is a `FatalContractError`, mentions `folium` and `pip install rivretrieve[map]`, and has no `IssuePolicyError` in its exception chain.
- Filters are asserted backend-free against the packaged catalogue: `providers="ch_foen"` and `country="Switzerland"` each select 246 rows; exact-match misses return empty frames; combined filters apply as AND.
- Bbox uses inclusive `(min_lon, min_lat, max_lon, max_lat)` order. Brugg `station_id="2016"` is selected by a tight lon/lat bbox and by exact boundary equality; this guards against lat/lon transposition.
- Valid empty filters are not fatal; fake-backend `map_stations(providers="unknown_provider")` returns an empty map object with no markers.
- Packaged-data-only behavior is covered by forbidding observation factory/default transport/token property access during `map_stations`.
- Reader-path proof spies on `CatalogueReader`: `read_stations` is called once; products and station-products are not read.
- Nullable-column render is covered with all-null `elevation_m` and `drainage_area_km2` in the folium-gated real-backend test.

## Tactical Deviations

- Used `importlib.import_module("folium")` in `_load_folium()` instead of a direct `import folium` so `ty check` stays green when the optional extra is absent.
- Kept popups to required station fields plus start/end dates; did not decode `metadata`, so the D9 JSON-walk concern does not apply.
- Added `uv lock` after editing `pyproject.toml`; it resolved locally without escalation.

## Discoveries

No new discovery candidate for `docs/discoveries.md`.

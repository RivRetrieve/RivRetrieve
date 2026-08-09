## Summary

- Adds keyword-only `raw: bool = False` and `on_issue: OnIssue = "warn"` controls to `fetch` and `fetch_by_provider`.
- Removes `RawMode` from the package root while retaining `RawMode.OMIT` and `RawMode.INCLUDE` in the internal observations API.
- Preserves the legacy package-root names owned by milestone 9.

## Observable evidence

- Default fetches return empty raw-entry tuples.
- `raw=True` retains the selected parse inputs in order, including `b"usgs_nwis|station-1|level"` and `b"usgs_nwis|station-2|level_hourly"`, with their exact provider-scoped `SourceCallOrigin` values.
- Multi-provider raw results retain one provider-scoped receipt per partition.
- Merged warning and error issues remain ordered. The default emits each authored warning once, `ignore` returns both without warnings, and `raise` fetches both selected series before raising with both issues.
- `fetch_by_provider(..., on_issue="ignore")` returns each provider's own issue tuple without warnings.

## Gates

- `uv sync` — passed
- `uv run ruff format` — passed, 167 files unchanged
- `uv run ruff check --fix` — passed
- `uv run ty check src` — passed
- `uv run pytest` — passed: 1660 passed, 2 skipped; only the unchanged missing-folium skips in `tests/test_map_stations.py`
- `uv build` — passed; built `rivretrieve-0.1.49` source and wheel distributions

## Not touched

- No bounding box, `record_covers`, shipped `source="live"` capability, coverage snapshot, harmonised name/river search, chained query language, PyPI publication, documentation authoring, provider porting, or native-table wheel decision.
- No milestone-9 deletion: `ProviderHandle`, `provider`, `observations`, `stations`, `provider_info`, `product_info`, and `map_stations` remain public.
- No changes to legacy observations or provider-handle signatures, `_ProviderHandle`, registries, provider modules, catalogues, native tables, fixtures, `CONTEXT.md`, ADRs, planning/review artifacts, repository-contract `stated` fields, `tests/typecheck/nominal_window_misuse.py`, or `tests/test_map_stations.py`.
- No dependency, `pyproject.toml`, `uv.lock`, version, tag, or publication change.

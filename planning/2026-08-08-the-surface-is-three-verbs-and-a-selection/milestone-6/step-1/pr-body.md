## Summary

- add public `rivretrieve.to_utc(result)` as a pure `ObservationResult` transformation
- convert every established fixed-offset or IANA wall clock row by row to naive UTC and stamp `+00:00`
- refuse atomically when any row publishes `time_zone == "unknown"`, reporting the provider and affected-row count
- preserve frame order/schema and the original provenance, issues, and raw payload objects without mutating the input
- cover a source-shaped USGS DST boundary fixture proving each payload offset is honored without catalogue access

## Verification

- `uv sync`
- `uv run ruff format`
- `uv run ruff check --fix`
- `uv run ty check src`
- `uv run pytest` — 1627 passed, 2 skipped
- `uv build`

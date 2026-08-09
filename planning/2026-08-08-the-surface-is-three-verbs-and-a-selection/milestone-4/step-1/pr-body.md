## Summary

- add single-provider `fetch` with pre-I/O empty and mixed-selection guards
- route sparse selected series without station-product Cartesian expansion
- add provider-partitioned `fetch_by_provider` with singular provenance and raw identity
- preserve the legacy observation surface and request semantics

## Validation

- `uv sync`
- `uv run ruff format`
- `uv run ruff check --fix`
- `uv run ty check src`
- `uv run pytest`
- `uv build`

## Summary

- update immutable catalogue selections to consume the renamed published-record bound columns
- preserve the selection API, edge semantics, and exact frame assertions

## Validation

- `uv sync`
- `uv run ruff format`
- `uv run ruff check --fix`
- `uv run ty check src`
- `uv run pytest` — 1,637 passed, 2 skipped
- `uv build`

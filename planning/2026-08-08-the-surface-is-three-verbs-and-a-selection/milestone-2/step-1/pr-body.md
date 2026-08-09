## Summary

- add immutable catalogue selections at provider/station/product series grain
- add total `find` and catalogue-scoped `pick` discovery with reason-carrying empty results
- add deterministic Polars conversion through `as_frame` and `from_frame`
- preserve the legacy public surface while exporting the four new functions

## Validation

- `uv sync`
- `uv run ruff format`
- `uv run ruff check --fix`
- `uv run ty check src`
- `uv run pytest`
- `uv build`

## Summary

- codify that `source_metadata` is absent from the installed package public surface
- preserve the existing three-verbs-and-a-selection API and four-field packaged catalogue artifact
- leave runtime code, catalogue data, and packaging configuration unchanged

## Validation

- `uv sync`
- `uv run ruff format`
- `uv run ruff check --fix`
- `uv run ty check src`
- `uv run pytest`
- `uv build`

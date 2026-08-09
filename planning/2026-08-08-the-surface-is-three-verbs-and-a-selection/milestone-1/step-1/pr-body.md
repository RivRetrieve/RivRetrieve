## Summary
- rename canonical station-product record bounds to `published_record_start_date` and `published_record_end_date`
- update all thirteen generators and value-preservingly rename all thirteen packaged station-product artifacts
- align schema regression coverage, affected content pins, and current ADR terminology

## Validation
- `uv sync`
- `uv run ruff format`
- `uv run ruff check --fix`
- `uv run ty check src`
- `uv run pytest`
- `uv build`

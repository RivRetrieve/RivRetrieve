## Summary

- retain `products(provider=None)` as the canonical product vocabulary view
- return the same sorted list shape for every provider scope and reject unknown providers
- keep provider-specific catalogue metadata internal and leave `product_info` unchanged

## Validation

- `uv sync`
- `uv run ruff format`
- `uv run ruff check --fix`
- `uv run ty check src`
- `uv run pytest`
- `uv build`

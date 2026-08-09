## Summary

- retire ProviderHandle and the legacy provider, observation, global table, product-info, and map-stations surface
- make catalogue reads packaged-only and remove CatalogSource routing
- keep products, selection mapping, internal fetch dispatch, and independent USGS live maintenance behavior intact

## Validation

- uv sync
- uv run ruff format
- uv run ruff check --fix
- uv run ty check src
- uv run pytest
- uv build
- installed-wheel public-surface smoke check

## Summary

- project series-grain selections to deterministic unique `(provider_id, station_id)` station rows without mutating the selection or packaged catalogues
- render the catalogue's exact CRS in every popup, using orange icons for `unknown` and blue icons for established CRS values
- preserve the legacy `map_stations` filtering surface, five-column `StationMap` input, empty-map centre, and lazy optional Folium dependency
- verify catalogue immutability with fresh packaged-artifact reads before and after rendering, bypassing the in-process registry cache

## Validation

- `uv sync`: passed
- `uv run ruff format`: passed
- `uv run ruff check --fix`: passed
- `uv run ty check src`: passed
- `uv run pytest`: passed (`1648 passed, 2 skipped`)
- `uv build`: passed

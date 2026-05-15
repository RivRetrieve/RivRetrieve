# Project Instructions

## 0. Project Overview

A Python package for downloading global river gauge data.

## 1. Python Environment

Use `uv` exclusively.

- Add dependencies: `uv add <package>`
- Remove dependencies: `uv remove <package>`
- Sync environment: `uv sync`
- Run commands: `uv run <command>`
- Run tests: `uv run pytest`

Do not use `pip`, `poetry`, `conda`, or `pip-tools` directly.

## 2. Code Style

Use `ruff` for formatting and linting, and `ty` for type checking.

```bash
uv run ruff format
uv run ruff check --fix
uv run ty check
```

Use modern Python typing syntax:

- Prefer built-in generics: `list[str]`, `dict[str, int]`, `tuple[str, ...]`.
- Prefer `|` unions: `str | None`.
- Avoid importing legacy aliases from `typing` such as `List`, `Dict`, `Tuple`, or `Optional`.
- Import from `typing` only when needed for features with no built-in equivalent, such as `Protocol`, `Literal`, or `NewType`.

## 3. Versioning and Tags

Every commit must include a patch version bump.

Before committing:

```bash
uv run bump-my-version bump patch
```

Stage the version files with the code changes, commit normally, then tag:

```bash
git tag v$(uv run bump-my-version show current_version)
```

Only bump minor or major versions when explicitly requested.

## 4. Testing Complex Data Objects

Prefer third-party testing utilities over manual element-wise assertions when comparing complex data objects.

Avoid manually checking lengths, schemas, coordinates, dimensions, shapes, dtypes, or element-wise equality when a library-specific assertion exists.

### NumPy

Use `numpy.testing`.

```python
import numpy as np

np.testing.assert_array_equal(result, expected)
np.testing.assert_allclose(result, expected)
```

### Xarray

Use `xarray.testing`.

```python
import xarray as xr

xr.testing.assert_equal(result, expected)
xr.testing.assert_identical(result, expected)
xr.testing.assert_allclose(result, expected)
```

### Polars

Use `polars.testing`.

```python
import polars.testing as pl_testing

pl_testing.assert_frame_equal(result_df, expected_df)
pl_testing.assert_series_equal(result_series, expected_series)
```

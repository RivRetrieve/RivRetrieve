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

## 5. Packaged Catalogue Rule

When porting a new provider, the packaged catalogue artifacts (`catalogue/*.parquet`, `catalogue/provider.json`) **must be generated from the live provider API** before the provider is committed.

- `tests/test_data/<provider>_metadata_*.json` is a **test fixture** — a minimal offline snapshot used only for unit tests. It must never be used to generate the packaged catalogue.
- After writing all provider code and tests, run `generate_catalogue.py --live --out src/rivretrieve/_internal/providers/<provider>/catalogue/` to produce the real packaged artifacts.
- Commit the resulting parquet files alongside the code.

Some generators include a provider-specific minimum-station guard that raises `FatalContractError` when `--live` returns an implausibly small count — catching silent fetch failures or accidental fixture-backed invocations. The threshold is calibrated per provider (e.g. 10 000 for USGS which has 26 000+ gauges; Lithuania has only 97 stations so no such guard is needed there). Do not copy a numeric threshold from one provider to another.

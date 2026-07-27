# Project Instructions

A rule appears in this file only if (a) it encodes a project choice that cannot be inferred from the code, or (b) default model output violates it. Practices a model already follows unprompted, and anything ruff or ty enforces mechanically, are deliberately absent.

## 0. Project Overview

RivRetrieve downloads river gauge data from national hydrology agencies and returns it in one shape.

The promise it cannot break: **faithful, traceable access through one consistent shape across every provider.** A user can trust a number and follow it back to its source.

The boundary that keeps that promise finite: **harmonise identity and physics, never harmonise judgement.** Units, column shape, time representation and product identity are objective, so we convert them. Quality codes, station identity across borders, and river naming are interpretation, so we surface them exactly as the source gave them and adjudicate nothing.

Domain terms are defined in `CONTEXT.md`. Decisions that are hard to reverse are recorded in `docs/adr/`.

## 1. Python Environment

Use `uv` exclusively.

- Add dependencies: `uv add <package>` (dev: `uv add --dev <package>`)
- Sync environment: `uv sync`
- Run anything: `uv run <command>`, tests: `uv run pytest`

Do not use `pip`, `poetry`, `conda`, or `pip-tools` directly.

Format, lint, and type-check with:

```bash
uv run ruff format
uv run ruff check --fix
uv run ty check
```

## 2. Design Doctrine

Four rules. They are one design stance seen four ways: a module means one thing, receives exactly what it needs, in types that cannot lie, and dies rather than guess.

### 2.1 Denotation line

Before implementing a module, state in one line what it computes as a mathematical object, and record that line in the module docstring. Carriers must be named domain types, not placeholders.

```
preprocess : RawForcing × Attributes → Dataset   (pure)
training run = fold(update, θ₀, batches)
evaluation = map(metric) over (basin × model) pairs
```

If the line cannot be written, the design is not ready; say so instead of coding around it. In review, when the denotation line and the diff disagree, one of them is wrong.

### 2.2 Authority narrows

All wiring happens at the composition root: only the entry point (CLI command or `main()`) reads config files, reads environment variables, resolves paths, and opens stores. Every other module receives what it needs as arguments.

At every call, pass the narrowest argument that suffices: the two columns, not the DataFrame; the file path, not the directory; the three fields, not the config object. A function outside the entry module whose signature accepts the full config, or which constructs a `Path` from a literal, is a violation.

### 2.3 Parse, don't validate

Convert raw input (CLI args, YAML, NetCDF attributes) into domain types once, at the composition root. Downstream functions accept and return only domain types for concepts that carry an invariant or unit ambiguity: identifiers, physical quantities, config. A `float` that might be mm/day or m³/s must not exist past the boundary.

Enums over booleans: never `bool` for a domain state with two named possibilities. Use an `Enum` or `Literal["upstream", "downstream"]`, not `upstream: bool` — applies to parameters, fields, and return values.

Limits: domain types (`NewType`, frozen dataclass, enum) are for concepts with invariants, not for every value. Bulk numerical data stays in `xarray`/`polars` carriers; do not wrap arrays in classes.

### 2.4 Fail loud

Crash early on broken assumptions. No fallback values for required inputs (`.get(key, default)` on a required config key is a bug). No exception handler that logs and continues.

The one exception: a batch loop over independent items (e.g. per-basin processing) may have exactly one named isolation point that catches per-item failure, records which item failed and why, and continues. That point exists once per pipeline, not once per function.

## 3. Testing Complex Data Objects

Prefer library-specific assertions over manual element-wise checks of lengths, schemas, coordinates, shapes, or dtypes.

```python
np.testing.assert_allclose(result, expected)
xr.testing.assert_identical(result, expected)
pl_testing.assert_frame_equal(result_df, expected_df)
```

## 4. Packaged Catalogue Rule

When porting a new provider, the packaged catalogue artifacts (`catalogue/*.parquet`, `catalogue/provider.json`) **must be generated from the live provider API** before the provider is committed.

- `tests/test_data/<provider>_metadata_*.json` is a **test fixture** — a minimal offline snapshot used only for unit tests. It must never be used to generate the packaged catalogue.
- After writing all provider code and tests, run `generate_catalogue.py --live --out src/rivretrieve/_internal/providers/<provider>/catalogue/` to produce the real packaged artifacts.
- Commit the resulting parquet files alongside the code.

Some generators include a provider-specific minimum-station guard that raises `FatalContractError` when `--live` returns an implausibly small count — catching silent fetch failures or accidental fixture-backed invocations. The threshold is calibrated per provider (e.g. 10 000 for USGS which has 26 000+ gauges; Lithuania has only 97 stations so no such guard is needed there). Do not copy a numeric threshold from one provider to another.
